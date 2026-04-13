"""AI/개발자 도구 핫토픽 & 보편 주제 선정 CLI 툴."""

import argparse
import html as html_mod
import io
import os
import re
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from math import ceil
from urllib.parse import urlparse

from dotenv import load_dotenv
from rich.console import Console
from rich.panel import Panel

from history import get_used_urls, save_topic
from modes import HOT_CONFIG, GENERAL_CONFIG, MODES
from pipeline import run_pipeline, adapt_for_filter_seen

console = Console()

SOURCE_ICONS = {
    "reddit": "[bold orange1]Reddit[/]",
    "reddit_localllama": "[bold orange1]Reddit LLaMA[/]",
    "reddit_openai": "[bold orange1]Reddit OpenAI[/]",
    "reddit_programming": "[bold orange1]Reddit Prog[/]",
    "reddit_technology": "[bold orange1]Reddit Tech[/]",
    "reddit_explainlikeimfive": "[bold orange1]Reddit ELI5[/]",
    "github_trending": "[bold white]GitHub[/]",
    "hacker_news": "[bold yellow]HN[/]",
    "youtube": "[bold red]YouTube[/]",
    "geeknews": "[bold green]GeekNews[/]",
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


def format_pipeline_html(result: dict, mode_label: str) -> str:
    """run_pipeline() 결과를 Telegram HTML 형식으로 변환 (hot + evergreen 2섹션)."""
    esc = html_mod.escape
    NUMBER_EMOJIS = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣"]

    def render_items(items: list[dict], header: str) -> list[str]:
        lines = [header, ""]
        if not items:
            lines.append("(없음)")
            lines.append("")
            return lines
        for i, item in enumerate(items, 1):
            num_emoji = NUMBER_EMOJIS[i - 1] if i <= len(NUMBER_EMOJIS) else f"{i}."
            title = esc(item.get("title", ""))
            url = esc(item.get("url", ""))
            lines.append(f"{num_emoji} <a href=\"{url}\">{title}</a>")

            final_score = item.get("final_score", 0)
            display_score = min(100, int(final_score / 6.0 * 100))
            score_line = f"   📊 {display_score}/100"

            tier = item.get("matched_tier", "")
            if tier in ("tier1", "tier2"):
                tier_num = tier.replace("tier", "")
                score_line += f"  🎯 tier{tier_num}"

            cross = item.get("cross_source_count", 1)
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
            for ref in cluster_refs[:3]:
                ref_title = esc(ref.get("title", "")[:60])
                ref_url = esc(ref.get("url", ""))
                ref_source = esc(ref.get("source", ""))
                lines.append(f"   🔗 <a href=\"{ref_url}\">{ref_source}: {ref_title}</a>")

            lines.append("")
        return lines

    hot_items = result.get("hot", [])
    ever_items = result.get("evergreen", [])

    lines: list[str] = []
    lines += render_items(hot_items, f"🔥 <b>{mode_label} — HOT</b>")
    lines += render_items(ever_items, f"💡 <b>{mode_label} — EVERGREEN</b>")

    text = "\n".join(lines).rstrip()
    # Trim to 3500 char budget
    if len(text) > 3500:
        text = text[:3497] + "..."
    return text


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


def format_anthropic_html(kind: str = "all") -> str:
    """Anthropic 공식 블로그/뉴스를 Telegram HTML 형식으로 변환.

    kind: "blog" | "news" | "all"
    """
    import html as html_mod
    esc = html_mod.escape
    from sources.anthropic_releases import fetch_anthropic_releases

    raw = fetch_anthropic_releases()

    if kind == "blog":
        items = [i for i in raw if "claude.com/blog" in i["url"]][:4]
        header = "📝 <b>Anthropic 블로그</b>"
    elif kind == "news":
        items = [i for i in raw if "anthropic.com/news" in i["url"]][:4]
        header = "📰 <b>Anthropic 뉴스</b>"
    else:
        blog = [i for i in raw if "claude.com/blog" in i["url"]][:4]
        news = [i for i in raw if "anthropic.com/news" in i["url"]][:3]
        items = blog + news
        header = "📢 <b>Anthropic 공식</b>"

    if not items:
        return f"{header}\n\n데이터 없음"

    items = _translate_descriptions(items)

    lines = [header, ""]
    for item in items:
        title = esc(item["title"])
        url = esc(item["url"])
        lines.append(f"• <a href=\"{url}\">{title}</a>")
        desc_ko = item.get("description_ko", "")
        if desc_ko:
            lines.append(f"  {esc(desc_ko)}")
        else:
            desc = item.get("description", "")
            if desc and desc != item["title"]:
                if len(desc) > 120:
                    desc = desc[:117] + "..."
                lines.append(f"  {esc(desc)}")

    return "\n".join(lines)


def cli():
    """CLI 진입점."""
    parser = argparse.ArgumentParser(
        description="AI/LLM 및 개발자 도구 관련 핫토픽을 수집하고 추천합니다.",
    )
    parser.add_argument(
        "--count", "-n",
        type=int,
        default=1,
        help="추천할 토픽 수 (기본: 1)",
    )
    parser.add_argument(
        "--hot-n",
        type=int,
        default=None,
        dest="hot_n",
        help="HOT 섹션 항목 수 (지정 시 --count 비례 분할 무시)",
    )
    parser.add_argument(
        "--evergreen-n",
        type=int,
        default=None,
        dest="evergreen_n",
        help="EVERGREEN 섹션 항목 수 (지정 시 --count 비례 분할 무시)",
    )
    parser.add_argument(
        "--mode", "-m",
        choices=["hot", "general", "anthropic"],
        default=None,
        help="모드 선택: hot (핫토픽), general (보편 주제), anthropic (공식 콘텐츠). 미지정시 대화형 선택.",
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
    args = parser.parse_args()

    load_dotenv()

    markdown_mode = args.fmt == "markdown"

    # markdown 모드에서 --mode 필수 검사
    if markdown_mode and not args.mode:
        parser.error("--format markdown 모드에서는 --mode가 필수입니다. (hot, general, anthropic)")

    # anthropic 모드: 공식 콘텐츠만 출력
    if args.mode == "anthropic":
        if markdown_mode:
            sys.stdout.reconfigure(encoding="utf-8")
            print(format_anthropic_html(kind=args.kind))
        else:
            console.print(format_anthropic_html(kind=args.kind))
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

    # 모드 선택
    if args.mode:
        mode_config = MODES[args.mode]
    else:
        console.print()
        console.print("[bold]모드를 선택하세요:[/]")
        console.print("  [cyan]1[/]) 핫토픽 — 트렌딩 AI/개발 주제")
        console.print("  [cyan]2[/]) 보편 주제 — 비개발자도 궁금한 기술 상식")
        console.print()
        try:
            choice = console.input("[bold cyan]선택 (1/2): [/]").strip()
        except EOFError:
            choice = "1"
        mode_config = GENERAL_CONFIG if choice == "2" else HOT_CONFIG

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

    # 파이프라인 설정 (hot/evergreen 개수 결정)
    pipeline_cfg = dict(mode_config.pipeline_config)
    if args.hot_n is not None or args.evergreen_n is not None:
        hot_count = args.hot_n if args.hot_n is not None else 3
        evergreen_count = args.evergreen_n if args.evergreen_n is not None else 2
    elif args.count <= 1:
        hot_count = 1
        evergreen_count = 0
    else:
        hot_count = max(1, ceil(args.count * 0.6))
        evergreen_count = args.count - hot_count
    pipeline_cfg["hot_count"] = hot_count
    pipeline_cfg["evergreen_count"] = evergreen_count

    pipeline_result = run_pipeline(all_items, pipeline_cfg)

    # filter_seen 적용
    all_topics_flat = pipeline_result["hot"] + pipeline_result["evergreen"]
    wrapped = adapt_for_filter_seen(all_topics_flat)

    # content_type 메타데이터를 wrapped에 전달 (split 복원용)
    for i, item in enumerate(all_topics_flat):
        wrapped[i]["_content_type"] = item.get("content_type", "hot")
        wrapped[i]["_pipeline_item"] = item

    wrapped = filter_seen(wrapped)

    if not wrapped:
        if markdown_mode:
            print("새로운 추천 토픽이 없습니다.", file=sys.stderr)
        else:
            console.print("[bold red]새로운 추천 토픽이 없습니다.[/] (이전 추천이 모두 이력에 있음)")
        return

    # hot/evergreen 재분리
    seen_hot = [w["_pipeline_item"] for w in wrapped if w.get("_content_type") == "hot"][:hot_count]
    seen_ever = [w["_pipeline_item"] for w in wrapped if w.get("_content_type") == "evergreen"][:evergreen_count]
    display_result = {"hot": seen_hot, "evergreen": seen_ever}

    if markdown_mode:
        sys.stdout.reconfigure(encoding="utf-8")
        print(format_pipeline_html(display_result, mode_config.label))
        return

    # rich CLI 출력
    all_display = seen_hot + seen_ever
    for i, item in enumerate(all_display, 1):
        ctype = item.get("content_type", "hot")
        badge = "[🔥 HOT]" if ctype == "hot" else "[💡 EVERGREEN]"
        # wrap as legacy topic shape for display_topic
        raw_eng = item.get("engagement", 0)
        source = item.get("source", "")
        score = min(100, int(item.get("final_score", 0) / 6.0 * 100))
        reasons = [f"{source} 화제 (engagement {int(raw_eng):,})"]
        cross = item.get("cross_source_count", 1)
        if cross >= 2:
            reasons.append(f"교차 소스 {cross}곳 언급")
        tier = item.get("matched_tier", "")
        if tier:
            reasons.append(tier)
        legacy_topic = {
            "topic": f"{badge} {item.get('title', '')}"[:80],
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
        display_topic(legacy_topic, rank=i)

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
