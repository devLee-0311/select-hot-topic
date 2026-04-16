"""AI/개발자 도구 섹터별 핫토픽 & 보편 주제 선정 CLI 툴."""

import argparse
import html as html_mod
import io
import os
import re
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urlparse

from dotenv import load_dotenv
from rich.console import Console
from rich.panel import Panel

from history import get_used_urls, save_topic
from modes import MODES, SECTOR_CONFIG
from pipeline import (
    DISPLAY_SCORE_CAP_BY_CROSS,
    FRESH_SINGLETON_CAP,
    SECTORS,
    SECTORS_BY_KEY,
    adapt_for_filter_seen,
    run_sector_pipeline,
)

console = Console()

SOURCE_ICONS = {
    "reddit": "[bold orange1]Reddit[/]",
    "reddit_localllama": "[bold orange1]Reddit LLaMA[/]",
    "reddit_openai": "[bold orange1]Reddit OpenAI[/]",
    "reddit_programming": "[bold orange1]Reddit Prog[/]",
    "reddit_technology": "[bold orange1]Reddit Tech[/]",
    "reddit_explainlikeimfive": "[bold orange1]Reddit ELI5[/]",
    "reddit_artificial": "[bold orange1]Reddit Artificial[/]",
    "reddit_machinelearning": "[bold orange1]Reddit ML[/]",
    "reddit_singularity": "[bold orange1]Reddit Singularity[/]",
    "reddit_stablediffusion": "[bold orange1]Reddit StableDiff[/]",

    "reddit_promptengineering": "[bold orange1]Reddit PromptEng[/]",
    "github_trending": "[bold white]GitHub[/]",
    "hacker_news": "[bold yellow]HN[/]",
    "youtube": "[bold red]YouTube[/]",
    "geeknews": "[bold green]GeekNews[/]",
    "anthropic_releases": "[bold magenta]Anthropic[/]",
}


def collect_all(fetchers: dict, quiet: bool = False) -> list[dict]:
    """소스에서 병렬로 데이터 수집."""
    all_items = []
    _console = Console(file=io.StringIO()) if quiet else console

    with _console.status("[bold green]데이터 수집 중..."):
        with ThreadPoolExecutor(max_workers=len(fetchers)) as executor:
            futures = {
                executor.submit(fn): name
                for name, fn in fetchers.items()
            }

            for future in as_completed(futures):
                name = futures[future]
                try:
                    items = future.result()
                    count = len(items)
                    if count > 0:
                        _console.print(f"  [green]OK[/] {name}: {count}개 수집")
                    else:
                        _console.print(f"  [yellow]--[/] {name}: 결과 없음")
                    all_items.extend(items)
                except Exception as e:
                    _console.print(f"  [red]ERR[/] {name}: {e}")

    return all_items


def filter_seen(topics: list[dict]) -> list[dict]:
    """이력에 기록된 URL과 대부분 겹치는 토픽만 제외. 같은 주제라도 새 레퍼런스가 있으면 추천."""
    used_urls = get_used_urls()

    filtered = []
    for topic in topics:
        ref_urls = {ref["url"] for ref in topic["references"]}
        new_urls = ref_urls - used_urls
        # 새로운 레퍼런스가 절반 미만이면 스킵 (이미 다룬 내용)
        if len(ref_urls) > 0 and len(new_urls) < len(ref_urls) / 2:
            continue

        filtered.append(topic)

    return filtered


def display_topic(topic: dict, rank: int = 1) -> None:
    """단일 토픽을 rich로 출력."""
    score = topic["score"]
    score_bar = "█" * (score // 5) + "░" * (20 - score // 5)
    header = f"추천 주제 #{rank}: \"{topic['topic']}\""

    if score >= 70:
        score_color = "green"
    elif score >= 40:
        score_color = "yellow"
    else:
        score_color = "red"

    lines = []
    lines.append(f"[{score_color}]스코어: {score}/100 {score_bar}[/]")
    lines.append("")
    lines.append("[bold]선정 근거:[/]")
    for reason in topic["reasons"]:
        lines.append(f"  - {reason}")

    lines.append("")
    lines.append("[bold]레퍼런스:[/]")
    for j, ref in enumerate(topic["references"], 1):
        source_label = SOURCE_ICONS.get(ref["source"], ref["source"])
        eng = ref.get("engagement", 0)
        eng_str = f" (engagement: {eng})" if eng > 0 else ""
        title = ref["title"][:60]
        lines.append(f"  [{j}] {source_label} {title}")
        lines.append(f"      [link={ref['url']}]{ref['url']}[/link]{eng_str}")

    content = "\n".join(lines)

    panel = Panel(
        content,
        title=f"[bold yellow]{header}[/]",
        border_style="bright_blue",
        padding=(1, 2),
    )
    console.print(panel)


def format_topics_html(topics: list[dict], mode_label: str) -> str:
    """토픽 목록을 Telegram HTML 형식으로 변환."""
    esc = html_mod.escape
    NUMBER_EMOJIS = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣"]
    emoji = "🔥" if "핫" in mode_label else "💡"
    lines = [f"{emoji} <b>{mode_label} TOP {len(topics)}</b>", ""]

    for i, topic in enumerate(topics, 1):
        score = topic["score"]
        num_emoji = NUMBER_EMOJIS[i - 1] if i <= len(NUMBER_EMOJIS) else f"{i}."
        lines.append(f"{num_emoji} <b>{esc(topic['topic'])}</b>")
        if score >= 90:
            grade = "🔴 필수 다루기"
        elif score >= 70:
            grade = "🟠 강력 추천"
        elif score >= 50:
            grade = "🟡 고려 대상"
        else:
            grade = "⚪ 참고용"
        lines.append(f"   📊 {score}/100 — {grade}")
        desc = topic.get("description", "")
        if desc and desc != topic["topic"]:
            if len(desc) > 100:
                desc = desc[:97] + "..."
            lines.append(f"   📝 {esc(desc)}")
        else:
            # description이 없으면 첫 번째 레퍼런스의 도메인으로 출처 표시
            refs = topic.get("references", [])
            if refs:
                domain = urlparse(refs[0]["url"]).netloc.replace("www.", "")
                lines.append(f"   📝 via {domain}")
        for reason in topic["reasons"]:
            lines.append(f"   • {esc(reason)}")
        refs = topic.get("references", [])
        for ref in refs[:3]:
            title = esc(ref["title"][:50])
            url = esc(ref["url"])
            lines.append(f"   🔗 <a href=\"{url}\">{title}</a>")
        lines.append("")

    return "\n".join(lines).rstrip()


def format_sector_html(result: dict, mode_label: str, max_score: float = 6.0) -> list[str]:
    """run_sector_pipeline() 결과를 Telegram HTML 섹터별 청크 리스트로 변환.

    각 청크 = 단일 섹터의 독립적인 HTML 메시지 (자체 헤더 + 아이템).
    anthropic_news + anthropic_blog는 하나의 청크로 병합한다.
    mode_label은 하위 호환을 위해 남겨두었지만 현재 출력에는 사용하지 않는다.
    """
    del mode_label  # 각 청크가 독립 메시지이므로 전체 래퍼 헤더는 출력하지 않음
    esc = html_mod.escape
    NUMBER_EMOJIS = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣"]

    sectors = result.get("sectors", {})
    chunks: list[str] = []

    # anthropic_news + anthropic_blog를 하나의 청크로 병합
    ANTHROPIC_MERGE = {"anthropic_news", "anthropic_blog"}
    anthropic_chunk_parts: list[str] = []

    for name, cfg in SECTORS:
        emoji = cfg.get("emoji", "")
        label = cfg.get("label", name)
        sector_items = sectors.get(name, [])

        lines: list[str] = [f"{emoji} <b>{esc(label)}</b>", ""]

        if not sector_items:
            lines.append("(없음)")
        else:
            for i, item in enumerate(sector_items, 1):
                num_emoji = NUMBER_EMOJIS[i - 1] if i <= len(NUMBER_EMOJIS) else f"{i}."
                title = esc(item.get("title", ""))
                url = esc(item.get("url", ""))
                lines.append(f"{num_emoji} <a href=\"{url}\">{title}</a>")

                final_score = item.get("final_score", 0)
                cross = item.get("cross_source_count", 1)
                cap = DISPLAY_SCORE_CAP_BY_CROSS.get(min(cross, 5), 99)
                if cross == 1 and item.get("recency_multiplier", 1.0) >= 1.3:
                    cap = FRESH_SINGLETON_CAP
                display_score = min(cap, int(final_score / max_score * 99) if max_score > 0 else 0)
                score_line = f"   📊 {display_score}/100"

                if cross >= 2:
                    score_line += f"  🔗 {cross} 소스"

                lines.append(score_line)

                desc = item.get("description", "")
                if desc and desc != item.get("title", ""):
                    if len(desc) > 100:
                        desc = desc[:97] + "..."
                    lines.append(f"   📝 {esc(desc)}")

                source = item.get("source", "")
                source_label = SOURCE_ICONS.get(source, source)
                # SOURCE_ICONS values contain rich markup; strip for HTML output
                plain_source = re.sub(r"\[.*?\]", "", source_label).strip()
                if plain_source:
                    lines.append(f"   {esc(plain_source)}")

                cluster_refs = item.get("cluster_refs", [])
                for ref in cluster_refs:
                    ref_title = esc(ref.get("title", "")[:60])
                    ref_url = esc(ref.get("url", ""))
                    ref_source = esc(ref.get("source", ""))
                    lines.append(f"   🔗 <a href=\"{ref_url}\">{ref_source}: {ref_title}</a>")

                lines.append("")

        text = "\n".join(lines).rstrip()

        if name in ANTHROPIC_MERGE:
            anthropic_chunk_parts.append(text)
            # anthropic_blog가 마지막 병합 대상이므로 여기서 합쳐서 청크에 추가
            if name == "anthropic_blog":
                merged = "\n\n".join(anthropic_chunk_parts)
                header = "📢 <b>Anthropic 공식</b>\n\n"
                merged = header + merged
                if len(merged) > 4000:
                    merged = merged[:3997] + "..."
                chunks.append(merged)
        else:
            if len(text) > 4000:
                text = text[:3997] + "..."
            chunks.append(text)

    return chunks


def _translate_descriptions(items: list[dict]) -> list[dict]:
    """Anthropic 글 설명을 한글로 번역 (Haiku 사용)."""
    try:
        import anthropic
    except ImportError:
        return items

    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        return items

    # 번역할 description 모아서 한 번에 요청
    descs = []
    for item in items:
        desc = item.get("description", "")
        if desc and desc != item["title"]:
            descs.append(desc)
        else:
            descs.append(item["title"])

    numbered = "\n".join(f"[{i+1}] {d}" for i, d in enumerate(descs))
    try:
        client = anthropic.Anthropic(api_key=api_key)
        resp = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=1024,
            messages=[{
                "role": "user",
                "content": (
                    f"아래 영문 설명 {len(descs)}개를 각각 한글 1줄 요약으로 번역해.\n"
                    f"반드시 [번호] 형식을 유지하고, 각 항목당 정확히 1줄만 출력해.\n\n"
                    f"{numbered}"
                ),
            }],
        )
        text = resp.content[0].text.strip()
        for i in range(len(items)):
            marker = f"[{i+1}]"
            for line in text.split("\n"):
                line = line.strip()
                if line.startswith(marker):
                    items[i]["description_ko"] = line[len(marker):].strip()
                    break
    except Exception as e:
        print(f"  [!] 번역 실패: {e}", file=sys.stderr)

    return items


def _anthropic_output(kind: str = "all") -> tuple[str, list[dict]]:
    """Anthropic 공식 블로그/뉴스를 (HTML, 선택된 items) 튜플로 반환.

    kind: "blog" | "news" | "all"

    items는 URL/title을 포함한 raw dict 리스트로, auto-save용으로도 쓰인다.
    """
    import html as html_mod
    esc = html_mod.escape
    from sources.anthropic_releases import fetch_anthropic_releases

    raw = fetch_anthropic_releases()

    blog_all = [i for i in raw if "claude.com/blog" in i["url"]]
    news_all = [i for i in raw if "anthropic.com/news" in i["url"]]

    def _fmt_items(items, start=1):
        result = []
        for idx, item in enumerate(items, start):
            title = esc(item["title"])
            url = esc(item["url"])
            date_str = ""
            if item.get("published_at"):
                date_str = f" ({item['published_at'].strftime('%Y-%m-%d')})"
            result.append(f"<b>{idx}.</b> <a href=\"{url}\">{title}</a>{date_str}")
            desc_ko = item.get("description_ko", "")
            if desc_ko:
                result.append(f"  {esc(desc_ko)}")
            else:
                desc = item.get("description", "")
                if desc and desc != item["title"]:
                    if len(desc) > 120:
                        desc = desc[:117] + "..."
                    result.append(f"  {esc(desc)}")
        return result

    if kind == "blog":
        items = blog_all[:3]
        if not items:
            return "📝 <b>Anthropic 블로그</b>\n\n데이터 없음", []
        items = _translate_descriptions(items)
        lines = ["📝 <b>Anthropic 블로그 (최신 3개)</b>", ""]
        lines.extend(_fmt_items(items))
        return "\n".join(lines), items

    if kind == "news":
        items = news_all[:2]
        if not items:
            return "📰 <b>Anthropic 뉴스</b>\n\n데이터 없음", []
        items = _translate_descriptions(items)
        lines = ["📰 <b>Anthropic 뉴스 (최신 2개)</b>", ""]
        lines.extend(_fmt_items(items))
        return "\n".join(lines), items

    # kind == "all": 뉴스 2개 + 블로그 3개 섹션 분리
    news = news_all[:2]
    blog = blog_all[:3]
    all_items = news + blog

    if not all_items:
        return "📢 <b>Anthropic 공식</b>\n\n데이터 없음", []

    all_items = _translate_descriptions(all_items)
    news_t = all_items[:len(news)]
    blog_t = all_items[len(news):]

    lines = ["📢 <b>Anthropic 공식 — 최신 뉴스 &amp; 블로그</b>", ""]
    lines.append("📰 <b>뉴스 (최신 2개)</b>")
    lines.append("")
    lines.extend(_fmt_items(news_t))
    lines.append("")
    lines.append("📝 <b>블로그 (최신 3개)</b>")
    lines.append("")
    lines.extend(_fmt_items(blog_t))

    return "\n".join(lines), all_items


def format_anthropic_html(kind: str = "all") -> str:
    """Anthropic 공식 블로그/뉴스를 Telegram HTML 형식으로 변환 (하위호환 래퍼)."""
    html_out, _ = _anthropic_output(kind=kind)
    return html_out


def cli():
    """CLI 진입점."""
    parser = argparse.ArgumentParser(
        description="AI/LLM 및 개발자 도구 섹터별 핫토픽을 수집하고 추천합니다.",
    )
    parser.add_argument(
        "--mode", "-m",
        choices=["hot", "sector", "anthropic"],
        default=None,
        help=(
            "모드 선택: sector/hot (섹터별 핫토픽), "
            "anthropic (공식 콘텐츠). 미지정시 섹터 모드로 실행."
        ),
    )
    parser.add_argument(
        "--kind",
        choices=["blog", "news", "all"],
        default="all",
        help="anthropic 모드 전용: 블로그/뉴스 영역 분리 (기본: all)",
    )
    parser.add_argument(
        "--history",
        action="store_true",
        help="이력 목록 보기",
    )
    parser.add_argument(
        "--format",
        choices=["rich", "markdown"],
        default="rich",
        dest="fmt",
        help="출력 형식: rich (기본) 또는 markdown (CI/Telegram용)",
    )
    parser.add_argument(
        "--auto-save",
        action="store_true",
        dest="auto_save",
        help=(
            "markdown 모드에서 출력된 모든 아이템 URL을 이력에 자동 저장 "
            "(CI에서 사용, 인터랙티브 프롬프트 우회)."
        ),
    )
    args = parser.parse_args()

    load_dotenv()

    markdown_mode = args.fmt == "markdown"

    # markdown 모드에서 --mode 필수 검사
    if markdown_mode and not args.mode:
        parser.error("--format markdown 모드에서는 --mode가 필수입니다. (sector, hot, anthropic)")

    # anthropic 모드: 공식 콘텐츠만 출력
    if args.mode == "anthropic":
        html_out, anth_items = _anthropic_output(kind=args.kind)
        if markdown_mode:
            sys.stdout.reconfigure(encoding="utf-8")
            print(html_out)
        else:
            console.print(html_out)
        # auto-save: markdown 모드에서 출력된 URL들을 이력에 저장 (프롬프트 없음)
        if markdown_mode and args.auto_save and html_out.strip() and anth_items:
            for anth in anth_items:
                save_topic(
                    {
                        "topic": anth.get("title", "")[:80],
                        "score": 0,
                        "reasons": [f"anthropic:{args.kind}"],
                        "references": [{"url": anth.get("url", "")}],
                    },
                    mode=f"anthropic_{args.kind}",
                )
        return

    # 이력 보기 모드
    if args.history:
        from history import load_history
        history = load_history()
        if not history:
            console.print("[yellow]저장된 이력이 없습니다.[/]")
            return
        console.print(f"\n[bold]저장된 토픽 이력 ({len(history)}개):[/]\n")
        for i, entry in enumerate(history, 1):
            console.print(f"  {i}. [bold]{entry['topic']}[/] (스코어: {entry['score']}) - {entry['saved_at'][:10]}")
            for url in entry.get("references", []):
                console.print(f"     {url}")
            console.print()
        return

    # 모드 선택: --mode 미지정 시 섹터 모드 기본
    if args.mode:
        mode_config = MODES[args.mode]
    else:
        mode_config = SECTOR_CONFIG

    if not markdown_mode:
        console.print(
            Panel(mode_config.banner_text, border_style="bright_blue")
        )
        console.print()

    # 데이터 수집
    all_items = collect_all(mode_config.fetchers, quiet=markdown_mode)

    if not all_items:
        if markdown_mode:
            print("데이터 수집 실패: 수집된 항목이 없습니다.", file=sys.stderr)
        else:
            console.print("\n[bold red]수집된 데이터가 없습니다.[/]")
            console.print("네트워크 연결을 확인하거나 API 키를 설정해주세요.\n")
        sys.exit(1)

    if not markdown_mode:
        console.print(f"\n[bold]총 {len(all_items)}개 항목 수집 완료. 분석 중...[/]\n")

    # 섹터 파이프라인 실행
    pipeline_cfg = dict(mode_config.pipeline_config)
    pipeline_result = run_sector_pipeline(all_items, pipeline_cfg)

    # filter_seen 적용: 섹터 아이템을 flat 리스트로 변환 → 필터 → 섹터별 재분배
    all_topics_flat: list[dict] = []
    for name, _cfg in SECTORS:
        all_topics_flat.extend(pipeline_result["sectors"].get(name, []))

    wrapped = adapt_for_filter_seen(all_topics_flat, max_score=pipeline_result.get("max_score", 6.0))

    # 섹터 메타데이터 전달 (재분배용)
    for i, item in enumerate(all_topics_flat):
        wrapped[i]["_pipeline_item"] = item
        wrapped[i]["_sector"] = item.get("sector")

    wrapped = filter_seen(wrapped)

    if not wrapped:
        if markdown_mode:
            print("새로운 추천 토픽이 없습니다.", file=sys.stderr)
        else:
            console.print("[bold red]새로운 추천 토픽이 없습니다.[/] (이전 추천이 모두 이력에 있음)")
        return

    # 섹터별 재분배
    display_sectors: dict[str, list[dict]] = {name: [] for name, _ in SECTORS}
    for w in wrapped:
        sec = w.get("_sector")
        if sec in display_sectors:
            display_sectors[sec].append(w["_pipeline_item"])

    # 섹터별 slot 제한 적용
    for name, cfg in SECTORS:
        limit = cfg.get("count", 5)
        display_sectors[name] = display_sectors[name][:limit]

    display_result = {"sectors": display_sectors}

    if markdown_mode:
        sys.stdout.reconfigure(encoding="utf-8")
        chunks = format_sector_html(
            display_result,
            mode_config.label,
            max_score=pipeline_result.get("max_score", 6.0),
        )
        output = "\n@@@SECTOR_BREAK@@@\n".join(chunks)
        print(output)
        # auto-save: 출력된 모든 아이템의 URL을 이력에 저장 (프롬프트 없음).
        # 파이프라인 워크플로에서 같은 주제가 다음 런에 재추천되지 않도록 dedup 용도.
        if args.auto_save and output.strip():
            for name, _cfg in SECTORS:
                for item in display_sectors.get(name, []):
                    save_topic(
                        {
                            "topic": item.get("title", "")[:80],
                            "score": 0,
                            "reasons": [f"sector:{name}"],
                            "references": [{"url": item.get("url", "")}],
                        },
                        mode=mode_config.name,
                    )
        return

    # rich CLI 출력: 섹터별로 구분자와 함께 출력
    _max = pipeline_result.get("max_score", 6.0)
    rank = 0
    for name, cfg in SECTORS:
        sector_items = display_sectors.get(name, [])
        if not sector_items:
            continue
        emoji = cfg.get("emoji", "")
        label = cfg.get("label", name)
        console.print()
        console.print(f"[bold cyan]{emoji} {label}[/]")
        console.print()
        for item in sector_items:
            rank += 1
            raw_eng = item.get("engagement", 0)
            source = item.get("source", "")
            _cross = item.get("cross_source_count", 1)
            _cap = DISPLAY_SCORE_CAP_BY_CROSS.get(min(_cross, 5), 99)
            if _cross == 1 and item.get("recency_multiplier", 1.0) >= 1.3:
                _cap = FRESH_SINGLETON_CAP
            score = min(_cap, int(item.get("final_score", 0) / _max * 99) if _max > 0 else 0)
            reasons = [f"{source} 화제 (engagement {int(raw_eng):,})"]
            if _cross >= 2:
                reasons.append(f"교차 소스 {_cross}곳 언급")
            reasons.append(f"sector:{name}")
            legacy_topic = {
                "topic": f"[{emoji} {SECTORS_BY_KEY[name]['label']}] {item.get('title', '')}"[:80],
                "description": item.get("description", ""),
                "score": score,
                "reasons": reasons,
                "references": [{
                    "title": item.get("title", ""),
                    "url": item.get("url", ""),
                    "source": source,
                    "engagement": raw_eng,
                }],
            }
            display_topic(legacy_topic, rank=rank)

    # 이력 저장 확인
    console.print()
    try:
        answer = console.input("[bold cyan]이력에 저장하시겠습니까? (y/n): [/]")
        if answer.strip().lower() in ("y", "yes", "ㅇ", "ㅇㅇ"):
            for w in wrapped:
                save_topic(w, mode=mode_config.name)
            console.print(f"[green]✓ {len(wrapped)}개 토픽이 이력에 저장되었습니다.[/]")
        else:
            console.print("[yellow]이력에 저장하지 않았습니다.[/]")
    except EOFError:
        console.print("[yellow]입력 없음 - 이력에 저장하지 않았습니다.[/]")


if __name__ == "__main__":
    cli()
