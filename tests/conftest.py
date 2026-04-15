"""Shared pytest fixtures for pipeline tests."""

import time

import pytest


@pytest.fixture(autouse=True)
def _isolate_rolling_stats(tmp_path, monkeypatch):
    """Redirect rolling_stats file IO to tmp_path to avoid polluting the worktree.

    Without this, pipeline tests that call run_sector_pipeline would write a
    real score_stats.json into the project root on every run. Tests that need
    specific rolling state override the monkeypatch explicitly.
    """
    import rolling_stats as rs

    stats_path = tmp_path / "score_stats.json"
    orig_load = rs.load_rolling_stats
    orig_save = rs.save_rolling_stats

    def _load(path=None):
        # Tests that pass an explicit path (e.g. test_rolling_stats.py) bypass redirect.
        return orig_load(path=str(stats_path)) if path is None else orig_load(path=path)

    def _save(samples, today_max, path=None, keep_days=7):
        target = str(stats_path) if path is None else path
        return orig_save(samples, today_max, path=target, keep_days=keep_days)

    monkeypatch.setattr(rs, "load_rolling_stats", _load)
    monkeypatch.setattr(rs, "save_rolling_stats", _save)
    yield


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _item(
    title: str,
    source: str,
    engagement: int = 0,
    url: str = "",
    description: str = "",
    views: int | None = None,
    created: float | None = None,
    published: str = "",
) -> dict:
    item: dict = {
        "title": title,
        "source": source,
        "engagement": engagement,
        "url": url or f"https://example.com/{title.lower().replace(' ', '-')}",
        "description": description,
    }
    if views is not None:
        item["views"] = views
    if created is not None:
        item["created"] = created
    if published:
        item["published"] = published
    return item


# ---------------------------------------------------------------------------
# Multi-source fixture (6 items, varied sources and engagement)
# ---------------------------------------------------------------------------

@pytest.fixture
def sample_items_multi_source():
    """6+ synthetic items from 5 different sources with varying engagement."""
    now = time.time()
    return [
        _item(
            "Claude 3.5 new model release",
            source="hacker_news",
            engagement=200,
            url="https://hn.example.com/claude-35",
            created=now - 3600,
        ),
        _item(
            "LLM fine-tuning best practices guide",
            source="reddit_localllama",
            engagement=500,
            url="https://reddit.com/r/localllama/llm-guide",
            created=now - 7200,
        ),
        _item(
            "OpenAI GPT-5 launch announcement",
            source="github_trending",
            engagement=1000,
            url="https://github.com/openai/gpt5",
            created=now - 1800,
        ),
        _item(
            "RAG vector database tutorial",
            source="youtube",
            engagement=100,
            views=15000,
            url="https://youtube.com/watch?v=rag-tutorial",
            published="1 day ago",
        ),
        _item(
            "Anthropic MCP model context protocol deep dive",
            source="geeknews",
            engagement=8,
            url="https://geeknews.example.com/mcp-deep-dive",
            created=now - 600,
        ),
        _item(
            "Cursor AI editor comparison vs Copilot",
            source="reddit_programming",
            engagement=300,
            url="https://reddit.com/r/programming/cursor-vs-copilot",
            created=now - 5400,
        ),
    ]


# ---------------------------------------------------------------------------
# Single-source fixture (5 items all from reddit)
# ---------------------------------------------------------------------------

@pytest.fixture
def sample_items_single_source():
    """5 items all from the same reddit source family."""
    now = time.time()
    return [
        _item("LLM prompt engineering tricks", source="reddit_localllama", engagement=10, created=now - 3600),
        _item("AI devtools comparison 2024", source="reddit_localllama", engagement=20, created=now - 7200),
        _item("GPT vs Claude benchmark review", source="reddit_localllama", engagement=30, created=now - 10800),
        _item("Machine learning transformer architecture", source="reddit_localllama", engagement=40, created=now - 14400),
        _item("RAG embedding vector database setup", source="reddit_localllama", engagement=50, created=now - 18000),
    ]
