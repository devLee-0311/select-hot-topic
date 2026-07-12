"""Byte-level characterization ("golden snapshot") tests for the output/rendering layer.

Purpose: freeze CURRENT behavior of main.py's rendering functions as a safety net
for an upcoming behavior-preserving refactor. These tests do NOT judge whether the
output is "correct" -- they only assert that it does not change. If a future change
alters any of these snapshots, either the change was unintended (bug) or the golden
file must be deliberately regenerated as part of that change.

Frozen seams:
  1. main.format_sector_html()  -- markdown/Telegram HTML per-sector chunk rendering,
     including the display-score cap formula (delegated to pipeline.display_score(),
     which applies DISPLAY_SCORE_CAP_BY_CROSS / FRESH_SINGLETON_CAP) and the
     >4000-char chunk truncation.
  2. main._anthropic_output()  -- Anthropic official news/blog HTML rendering
     (kind="all"/"blog"/"news", including the empty-data branches).
  3. main.cli() markdown path (--format markdown --mode sector) -- the full
     "@@@SECTOR_BREAK@@@"-joined stdout output assembled in cli()'s markdown
     branch, driven end-to-end by monkeypatching the fetchers in
     modes.SECTOR_CONFIG (no network) and history.get_used_urls (no repo state
     touched).
  4. main.cli() rich path (default --format rich) -- the same pipeline.display_score()
     call, reused (not duplicated) in cli()'s non-markdown loop, frozen by
     swapping main.console for a `rich.Console(record=True)` and snapshotting
     `export_text()` (plain-text render, no ANSI, fixed width for determinism).

No network is used anywhere in this file. All source-fetching functions are
monkeypatched. rolling_stats/history file IO is isolated by the autouse
`_isolate_rolling_stats` fixture in conftest.py (rolling stats) and by
monkeypatching `main.get_used_urls` (history reads) / never calling `--auto-save`
(history writes never triggered).
"""

from __future__ import annotations

import io
import sys
from datetime import datetime
from pathlib import Path

from rich.console import Console

import main
import modes
import sources.anthropic_releases as ar
from pipeline import SECTORS

GOLDEN_DIR = Path(__file__).parent / "goldens"


def _golden(name: str) -> str:
    return (GOLDEN_DIR / name).read_text(encoding="utf-8")


# ===========================================================================
# 1. format_sector_html -- markdown/Telegram HTML chunk rendering
# ===========================================================================


def _sector_html_fixture_items() -> dict:
    """Hand-built pipeline-item-shaped fixtures (mirrors what run_sector_pipeline
    produces), covering: HTML escaping, cluster_refs rendering, a description
    equal to the title (no description line), an unknown source (fallback to raw
    source string), and every branch of the display-score cap formula:
      - cross_source_count=2 -> cap 85 (formula value 74 does not hit the cap)
      - cross_source_count=1, recency_multiplier=1.0 -> cap 70 (formula value 97
        gets clamped down to 70)
      - cross_source_count=1, recency_multiplier=1.4 (fresh singleton) -> cap 90
        (formula value 98 gets clamped down to 90)
      - cross_source_count=3 -> cap 99 (no clamping; formula value itself is 99)
    """
    return {
        "sectors": {
            "claude_code": [
                {
                    "title": "Claude Code <tips> & tricks for power users",
                    "url": "https://hn.example.com/claude-code-tips?x=1&y=2",
                    "description": (
                        "A deep dive into Claude Code's subagent system, hooks, and MCP "
                        "integrations for power users who want to "
                        "A deep dive into Claude Code's subagent system, hooks, and MCP "
                        "integrations for power users who want to "
                    ),
                    "source": "hacker_news",
                    "final_score": 4.5,
                    "cross_source_count": 2,
                    "recency_multiplier": 1.0,
                    "cluster_refs": [
                        {
                            "title": "Claude Code power user thread",
                            "url": "https://reddit.com/r/ClaudeAI/thread1",
                            "source": "reddit_claude",
                        },
                    ],
                },
                {
                    "title": "MCP servers roundup",
                    "url": "https://example.com/mcp-roundup",
                    "description": "MCP servers roundup",
                    "source": "unknown_source_xyz",
                    "final_score": 5.9,
                    "cross_source_count": 1,
                    "recency_multiplier": 1.0,
                    "cluster_refs": [],
                },
            ],
            "ai_infra": [
                {
                    "title": "Cursor ships new agent mode",
                    "url": "https://example.com/cursor-agent-mode",
                    "description": "",
                    "source": "github_trending",
                    "final_score": 5.95,
                    "cross_source_count": 1,
                    "recency_multiplier": 1.4,
                    "cluster_refs": [],
                },
            ],
            "ai_news_research": [
                {
                    "title": "New scaling law paper from three labs",
                    "url": "https://example.com/scaling-law-paper",
                    "description": "",
                    "source": "reddit_machinelearning",
                    "final_score": 6.0,
                    "cross_source_count": 3,
                    "recency_multiplier": 1.0,
                    "cluster_refs": [],
                },
            ],
        }
    }


def test_format_sector_html_frozen_output():
    """Full byte-identical snapshot of format_sector_html() across all 7 sectors
    (3 populated + 4 empty '(없음)' sectors), joined the same way main.py's
    markdown branch joins chunks (with '@@@SECTOR_BREAK@@@')."""
    result = _sector_html_fixture_items()
    chunks = main.format_sector_html(result, "unused-mode-label", max_score=6.0)

    assert len(chunks) == len(SECTORS) == 7
    joined = "\n@@@SECTOR_BREAK@@@\n".join(chunks)
    assert joined == _golden("format_sector_html_basic.txt")


def test_format_sector_html_display_score_cap_formula():
    """Focused check on the display-score cap formula so a change to
    min(cap, int(final_score/max_score*99)) / DISPLAY_SCORE_CAP_BY_CROSS /
    FRESH_SINGLETON_CAP breaks this test even if the surrounding layout doesn't."""
    result = _sector_html_fixture_items()
    chunks = main.format_sector_html(result, "unused-mode-label", max_score=6.0)
    by_sector = dict(zip((name for name, _ in SECTORS), chunks))

    # cross_source_count=2 -> cap 85, formula value int(4.5/6*99)=74 (under cap)
    assert "📊 74/100  🔗 2 소스" in by_sector["claude_code"]
    # cross_source_count=1, not fresh -> cap 70, formula value int(5.9/6*99)=97 (clamped to 70)
    assert "📊 70/100" in by_sector["claude_code"]
    # cross_source_count=1, fresh singleton (recency>=1.3) -> cap 90, formula value
    # int(5.95/6*99)=98 (clamped to 90)
    assert "📊 90/100" in by_sector["ai_infra"]
    # cross_source_count=3 -> cap 99, formula value int(6.0/6*99)=99 (no clamp needed)
    assert "📊 99/100  🔗 3 소스" in by_sector["ai_news_research"]


def test_format_sector_html_truncates_at_4000_chars():
    """A sector chunk whose rendered text exceeds 4000 chars is truncated to
    text[:3997] + '...' (main.py's per-chunk length guard)."""
    items = [
        {
            "title": f"Trending AI story number {i} about neural nets and gpus",
            "url": f"https://example.com/trending-{i}",
            "description": (
                "This is a fairly long description repeated to pad out the chunk length. " * 3
            ),
            "source": "hacker_news",
            "final_score": 1.0,
            "cross_source_count": 1,
            "recency_multiplier": 1.0,
            "cluster_refs": [],
        }
        for i in range(20)
    ]
    result = {"sectors": {"trending": items}}
    chunks = main.format_sector_html(result, "unused-mode-label", max_score=6.0)
    trending_idx = [i for i, (name, _cfg) in enumerate(SECTORS) if name == "trending"][0]
    text = chunks[trending_idx]

    assert len(text) == 4000
    assert text.endswith("...")
    assert text == _golden("format_sector_html_truncated.txt")


# ===========================================================================
# 2. _anthropic_output -- Anthropic official news/blog HTML rendering
# ===========================================================================


def _anthropic_raw_fixture() -> list[dict]:
    """7 raw anthropic_releases items (3 news, 4 blog) with fixed published_at
    dates, modeled on sources.anthropic_releases.fetch_anthropic_releases()'s
    return shape. _anthropic_output() itself slices news[:2] and blog[:3] in
    input order (it does not re-sort by date), so item order here matters."""
    return [
        {
            "title": "Anthropic news item 1",
            "url": "https://www.anthropic.com/news/item-1",
            "description": (
                "News description number 1 that is somewhat long and might get "
                "truncated if it exceeds one hundred and twenty characters total "
                "length here"
            ),
            "published_at": datetime(2026, 7, 10, 9, 0, 0),
            "source": "anthropic_releases",
        },
        {
            "title": "Anthropic news item 2",
            "url": "https://www.anthropic.com/news/item-2",
            "description": (
                "News description number 2 that is somewhat long and might get "
                "truncated if it exceeds one hundred and twenty characters total "
                "length here"
            ),
            "published_at": datetime(2026, 7, 9, 9, 0, 0),
            "source": "anthropic_releases",
        },
        {
            "title": "Anthropic news item 3",
            "url": "https://www.anthropic.com/news/item-3",
            "description": "News description number 3",
            "published_at": datetime(2026, 7, 8, 9, 0, 0),
            "source": "anthropic_releases",
        },
        {
            "title": "Anthropic blog post 1",
            "url": "https://claude.com/blog/post-1",
            "description": "Blog description number 1",
            "published_at": datetime(2026, 7, 11, 9, 0, 0),
            "source": "anthropic_releases",
        },
        {
            "title": "Anthropic blog post 2",
            "url": "https://claude.com/blog/post-2",
            "description": "Blog description number 2",
            "published_at": datetime(2026, 7, 7, 9, 0, 0),
            "source": "anthropic_releases",
        },
        {
            "title": "Anthropic blog post 3",
            "url": "https://claude.com/blog/post-3",
            "description": "Blog description number 3",
            "published_at": datetime(2026, 7, 6, 9, 0, 0),
            "source": "anthropic_releases",
        },
        {
            "title": "Anthropic blog post 4",
            "url": "https://claude.com/blog/post-4",
            "description": "Blog description number 4",
            "published_at": datetime(2026, 7, 5, 9, 0, 0),
            "source": "anthropic_releases",
        },
    ]


def _patch_anthropic_source(monkeypatch, raw: list[dict]) -> None:
    """No network: stub fetch_anthropic_releases() and disable Haiku translation
    (unset ANTHROPIC_API_KEY -> _translate_descriptions() short-circuits and
    returns items unchanged)."""
    monkeypatch.setattr(ar, "fetch_anthropic_releases", lambda: raw)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)


def test_anthropic_output_kind_all_frozen(monkeypatch):
    """kind='all': news[:2] + blog[:3], rendered as two labeled sub-sections."""
    _patch_anthropic_source(monkeypatch, _anthropic_raw_fixture())
    html_out, items = main._anthropic_output(kind="all")
    assert html_out == _golden("anthropic_output_all.txt")
    assert [it["title"] for it in items] == [
        "Anthropic news item 1",
        "Anthropic news item 2",
        "Anthropic blog post 1",
        "Anthropic blog post 2",
        "Anthropic blog post 3",
    ]


def test_anthropic_output_kind_blog_frozen(monkeypatch):
    """kind='blog': latest 3 blog items only."""
    _patch_anthropic_source(monkeypatch, _anthropic_raw_fixture())
    html_out, items = main._anthropic_output(kind="blog")
    assert html_out == _golden("anthropic_output_blog.txt")
    assert len(items) == 3


def test_anthropic_output_kind_news_frozen(monkeypatch):
    """kind='news': latest 2 news items only."""
    _patch_anthropic_source(monkeypatch, _anthropic_raw_fixture())
    html_out, items = main._anthropic_output(kind="news")
    assert html_out == _golden("anthropic_output_news.txt")
    assert len(items) == 2


def test_anthropic_output_empty_all(monkeypatch):
    _patch_anthropic_source(monkeypatch, [])
    html_out, items = main._anthropic_output(kind="all")
    assert html_out == _golden("anthropic_output_all_empty.txt")
    assert items == []


def test_anthropic_output_empty_blog(monkeypatch):
    _patch_anthropic_source(monkeypatch, [])
    html_out, items = main._anthropic_output(kind="blog")
    assert html_out == _golden("anthropic_output_blog_empty.txt")
    assert items == []


def test_anthropic_output_empty_news(monkeypatch):
    _patch_anthropic_source(monkeypatch, [])
    html_out, items = main._anthropic_output(kind="news")
    assert html_out == _golden("anthropic_output_news_empty.txt")
    assert items == []


# ===========================================================================
# 3 & 4. Full main.cli() markdown + rich paths, driven end-to-end
# ===========================================================================


def _fake_fetcher_claude_code():
    return [
        {
            "title": "Claude Code subagent tips for teams",
            "source": "hacker_news",
            "url": "https://hn.example.com/claude-code-subagents",
            "engagement": 500,
            "description": "",
        },
    ]


def _fake_fetcher_agents():
    return [
        {
            "title": "LangGraph powered agent workflow release",
            "source": "github_trending",
            "url": "https://github.com/example/langgraph-release",
            "engagement": 300,
            "description": "",
        },
    ]


def _patch_cli_sources(monkeypatch, fetchers: dict) -> None:
    """No network: swap SECTOR_CONFIG's fetchers, stub history reads (repo's
    history.json is never touched), and no-op load_dotenv for determinism
    regardless of a local .env file. --auto-save is never passed by these
    tests, so history.save_topic is never invoked (no repo state written).

    fill_missing_descriptions() (US-005) is also no-op'd here: the fixture
    fetchers below return items with empty descriptions, which would otherwise
    trigger real net.extract_meta_description() HTTP calls against fake
    example.com URLs during main.cli()'s markdown/rich paths."""
    monkeypatch.setattr(modes.SECTOR_CONFIG, "fetchers", fetchers)
    monkeypatch.setattr(main, "get_used_urls", lambda: set())
    monkeypatch.setattr(main, "load_dotenv", lambda *a, **kw: None)
    monkeypatch.setattr(main, "fill_missing_descriptions", lambda display_sectors, **kw: display_sectors)


class _FakeStdout(io.StringIO):
    """io.StringIO doesn't implement TextIOWrapper.reconfigure(); main.py's
    markdown branch calls sys.stdout.reconfigure(encoding='utf-8') before
    printing, so this stub no-ops it."""

    def reconfigure(self, *args, **kwargs):
        pass


def test_cli_markdown_sector_output_frozen(monkeypatch, capsys):
    """End-to-end main.cli() with `--mode sector --format markdown`: exercises
    the full markdown-assembly seam at main.py's markdown branch (chunks joined
    with '@@@SECTOR_BREAK@@@'). Two synthetic items route to two different
    sectors (claude_code, agents); every other sector renders '(없음)'."""
    fetchers = {"A": _fake_fetcher_claude_code, "B": _fake_fetcher_agents}
    _patch_cli_sources(monkeypatch, fetchers)
    monkeypatch.setattr(sys, "argv", ["main.py", "--mode", "sector", "--format", "markdown"])
    fake_stdout = _FakeStdout()
    monkeypatch.setattr(sys, "stdout", fake_stdout)

    main.cli()

    output = fake_stdout.getvalue()
    assert output.count("@@@SECTOR_BREAK@@@") == 6  # 7 sectors -> 6 separators
    assert output == _golden("cli_markdown_sector.txt")


def test_cli_rich_sector_output_frozen(monkeypatch):
    """End-to-end main.cli() with the default (rich, non-markdown) format:
    exercises the display-score cap formula (pipeline.display_score(), reused
    in cli()'s rich loop) by swapping main.console for a Console(record=True)
    and snapshotting export_text() (plain text, fixed width=100, no ANSI)."""
    fetchers = {"A": _fake_fetcher_claude_code, "B": _fake_fetcher_agents}
    _patch_cli_sources(monkeypatch, fetchers)
    monkeypatch.setattr(sys, "argv", ["main.py", "--mode", "sector"])

    record_console = Console(record=True, width=100, file=io.StringIO(), force_terminal=False)
    record_console.input = lambda *a, **kw: (_ for _ in ()).throw(EOFError())
    monkeypatch.setattr(main, "console", record_console)

    main.cli()

    text = record_console.export_text()
    assert "70/100" in text
    assert text == _golden("cli_rich_sector.txt")
