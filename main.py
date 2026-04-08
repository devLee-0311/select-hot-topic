"""AI/개발자 도구 핫토픽 & 보편 주제 선정 CLI 툴."""

import argparse
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed

from dotenv import load_dotenv
from rich.console import Console
from rich.panel import Panel

from history import get_used_urls, save_topic
from modes import HOT_CONFIG, GENERAL_CONFIG, MODES, ModeConfig
from scorer import score_topics

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
    "anthropic_releases": "[bold magenta]Anthropic[/]",
}


def collect_all(fetchers: dict) -> list[dict]:
    """소스에서 병렬로 데이터 수집."""
    all_items = []

    with console.status("[bold green]데이터 수집 중...") as status:
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
                        console.print(f"  [green]OK[/] {name}: {count}개 수집")
                    else:
                        console.print(f"  [yellow]--[/] {name}: 결과 없음")
                    all_items.extend(items)
                except Exception as e:
                    console.print(f"  [red]ERR[/] {name}: {e}")

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
        "--mode", "-m",
        choices=["hot", "general"],
        default=None,
        help="모드 선택: hot (핫토픽) 또는 general (보편 주제). 미지정시 대화형 선택.",
    )
    parser.add_argument(
        "--history",
        action="store_true",
        help="이력 목록 보기",
    )
    args = parser.parse_args()

    load_dotenv()

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

    console.print(
        Panel(mode_config.banner_text, border_style="bright_blue")
    )
    console.print()

    # 데이터 수집
    all_items = collect_all(mode_config.fetchers)

    if not all_items:
        console.print("\n[bold red]수집된 데이터가 없습니다.[/]")
        console.print("네트워크 연결을 확인하거나 API 키를 설정해주세요.\n")
        sys.exit(1)

    console.print(f"\n[bold]총 {len(all_items)}개 항목 수집 완료. 분석 중...[/]\n")

    # 스코어링 (여유분 포함해서 계산 후 필터링)
    topics = score_topics(all_items, top_n=args.count + 10, weights=mode_config.scorer_weights)
    topics = filter_seen(topics)

    if not topics:
        console.print("[bold red]새로운 추천 토픽이 없습니다.[/] (이전 추천이 모두 이력에 있음)")
        return

    # 요청 수만큼만 출력
    show_topics = topics[:args.count]

    for i, topic in enumerate(show_topics, 1):
        display_topic(topic, rank=i)

    # 이력 저장 확인
    console.print()
    try:
        answer = console.input("[bold cyan]이력에 저장하시겠습니까? (y/n): [/]")
        if answer.strip().lower() in ("y", "yes", "ㅇ", "ㅇㅇ"):
            for topic in show_topics:
                save_topic(topic, mode=mode_config.name)
            console.print(f"[green]✓ {len(show_topics)}개 토픽이 이력에 저장되었습니다.[/]")
        else:
            console.print("[yellow]이력에 저장하지 않았습니다.[/]")
    except EOFError:
        console.print("[yellow]입력 없음 - 이력에 저장하지 않았습니다.[/]")


if __name__ == "__main__":
    cli()
