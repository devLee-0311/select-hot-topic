"""Shared pytest fixtures for pipeline tests."""

import time

import pytest


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


# ---------------------------------------------------------------------------
# Single-item tier fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def sample_tier1_item():
    """Single item whose title contains a tier1 keyword."""
    return _item(
        "Claude code new feature release",
        source="hacker_news",
        engagement=0,
        url="https://hn.example.com/claude-code",
    )


@pytest.fixture
def sample_tier2_item():
    """Single item whose title contains a tier2 keyword (cursor)."""
    return _item(
        "Cursor IDE tab completion update",
        source="hacker_news",
        engagement=5,  # below hackernews threshold of 10
        url="https://hn.example.com/cursor-update",
    )


@pytest.fixture
def sample_tier3_item():
    """Single item whose title contains a tier3 keyword (llm)."""
    return _item(
        "LLM inference optimization techniques",
        source="reddit_localllama",
        engagement=100,
        url="https://reddit.com/r/localllama/llm-inference",
    )
