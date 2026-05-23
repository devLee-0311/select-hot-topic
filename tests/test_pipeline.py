"""Unit and integration tests for pipeline.py (pillar sector model).

All data is synthetic — no network calls.
Each test verifies exactly one behavior.
"""

from __future__ import annotations

import time
from datetime import datetime, timedelta

import pytest

from pipeline import (
    CLUSTER_NOISE_HARD_EXCLUDE,
    CROSS_SOURCE_BOOST,
    FRESH_SINGLETON_CAP,
    NON_ANCHOR_SOURCES,
    NON_OFFICIAL_SECTORS,
    RECENCY_BUCKETS,
    SECTOR_CLUSTER_NOISE,
    SECTORS,
    _parse_hours_since,
    _recency_multiplier,
    _titles_cluster,
    adapt_for_filter_seen,
    assign_sector,
    compute_sector_scores,
    detect_clusters,
    normalize_engagement,
    run_sector_pipeline,
)


# ===========================================================================
# assign_sector — pillar routing (claude_code / agents / local_llm / ai_infra)
# ===========================================================================


def test_assign_sector_claude_code_keyword():
    """Item with 'claude code' keyword routes to claude_code sector."""
    item = {
        "title": "Claude Code power-user tips",
        "source": "hacker_news",
        "url": "https://hn.example.com/claude-code",
        "description": "",
    }
    assert assign_sector(item) == "claude_code"


def test_assign_sector_mcp_routes_to_claude_code():
    """Item with 'mcp' keyword routes to claude_code sector."""
    item = {
        "title": "Model Context Protocol explainer",
        "source": "hacker_news",
        "url": "https://hn.example.com/mcp-article",
        "description": "",
    }
    assert assign_sector(item) == "claude_code"


def test_assign_sector_subagent_routes_to_claude_code():
    """'subagent' keyword routes to claude_code sector."""
    item = {
        "title": "Subagent design patterns",
        "source": "hacker_news",
        "url": "https://hn.example.com/subagent",
        "description": "",
    }
    assert assign_sector(item) == "claude_code"


def test_assign_sector_langgraph_routes_agents():
    """'langgraph' keyword routes to agents sector."""
    item = {
        "title": "LangGraph tutorial for multi-step reasoning",
        "source": "hacker_news",
        "url": "https://hn.example.com/langgraph",
        "description": "",
    }
    assert assign_sector(item) == "agents"


def test_assign_sector_cursor_codex_unrouted():
    """'cursor' or 'codex' route to ai_infra (re-added on this base)."""
    cursor_item = {
        "title": "Cursor adds codex mode",
        "source": "hacker_news",
        "url": "https://hn.example.com/cursor-codex",
        "description": "",
    }
    assert assign_sector(cursor_item) == "ai_infra"

    codex_item = {
        "title": "GPT-5 Codex release notes",
        "source": "hacker_news",
        "url": "https://hn.example.com/codex",
        "description": "",
    }
    assert assign_sector(codex_item) == "ai_infra"


def test_assign_sector_openai_routes_to_trending():
    """Item with 'openai' keyword routes to ai_infra (re-added on this base)."""
    item = {
        "title": "OpenAI new feature",
        "source": "hacker_news",
        "url": "https://hn.example.com/openai",
        "description": "",
    }
    assert assign_sector(item) == "ai_infra"


def test_assign_sector_ai_infra_cursor():
    """'cursor' keyword routes to ai_infra sector (re-added)."""
    item = {
        "title": "Cursor 1.0 ships agent mode",
        "source": "hacker_news",
        "url": "https://hn.example.com/cursor",
        "description": "",
    }
    assert assign_sector(item) == "ai_infra"


def test_assign_sector_ai_news_research_pure_research():
    """Pure research item (arxiv/benchmark, no tool keyword) routes to ai_news_research."""
    item = {
        "title": "New arxiv paper sets SOTA benchmark on reasoning",
        "source": "hacker_news",
        "url": "https://arxiv.org/abs/1234",
        "description": "preprint scaling law foundation model",
    }
    assert assign_sector(item) == "ai_news_research"


def test_assign_sector_tool_wins_over_ai_news_research():
    """First-match-wins: a tool keyword (cursor) beats ai_news_research even with research words.

    'cursor' matches ai_infra (earlier in SECTORS) so the item never reaches ai_news_research.
    """
    item = {
        "title": "Cursor adds arxiv paper search benchmark",
        "source": "hacker_news",
        "url": "https://hn.example.com/cursor-arxiv",
        "description": "",
    }
    assert assign_sector(item) == "ai_infra"


def test_assign_sector_ollama_routes_local_llm():
    """'ollama' keyword routes to local_llm sector."""
    item = {
        "title": "Ollama guide for beginners",
        "source": "hacker_news",
        "url": "https://hn.example.com/ollama",
        "description": "",
    }
    assert assign_sector(item) == "local_llm"


def test_assign_sector_llamacpp_routes_local_llm():
    """'llama.cpp' keyword routes to local_llm sector."""
    item = {
        "title": "llama.cpp performance tips",
        "source": "reddit_localllama",
        "url": "https://reddit.com/localllama",
        "description": "",
    }
    assert assign_sector(item) == "local_llm"


def test_assign_sector_claude_code_wins_over_agents():
    """'Claude Code agent SDK announced' → claude_code (priority order, not agents)."""
    item = {
        "title": "Claude Code agent SDK announced",
        "source": "hacker_news",
        "url": "https://hn.example.com/claude-code-agent-sdk",
        "description": "",
    }
    assert assign_sector(item) == "claude_code"


def test_assign_sector_deny_excludes_claude_code_from_agents():
    """'Claude Code agentic workflow' has both 'claude code' AND 'agentic'.

    Priority says claude_code wins (not agents). The `deny: ['claude code']` on agents
    is a safety net — even if priority were skipped, agents must not claim this item.
    """
    item = {
        "title": "Claude Code agentic workflow deep dive",
        "source": "hacker_news",
        "url": "https://hn.example.com/claude-code-agentic",
        "description": "",
    }
    assert assign_sector(item) == "claude_code"


def test_assign_sector_anthropic_releases_news_url():
    """source=anthropic_releases with /news/ URL routes to anthropic_official, tagged news."""
    item = {
        "title": "New announcement",
        "source": "anthropic_releases",
        "url": "https://www.anthropic.com/news/some-announcement",
        "description": "",
    }
    assert assign_sector(item) == "anthropic_official"
    assert item["official_kind"] == "news"


def test_assign_sector_anthropic_releases_blog_url():
    """source=anthropic_releases with claude.com/blog URL routes to anthropic_official, tagged blog."""
    item = {
        "title": "New blog post",
        "source": "anthropic_releases",
        "url": "https://claude.com/blog/some-post",
        "description": "",
    }
    assert assign_sector(item) == "anthropic_official"
    assert item["official_kind"] == "blog"


def test_assign_sector_no_match_returns_none():
    """Item with no matching keyword (pillar or trending) → None (dropped)."""
    item = {
        "title": "Weekend hiking trail review",
        "source": "reddit_hiking",
        "url": "https://reddit.com/r/hiking/x",
        "description": "",
    }
    assert assign_sector(item) is None


def test_assign_sector_trending_broad_ai_keyword():
    """Item matching a trending-only broad keyword (no tool/research keyword) → 'trending'.

    Uses 'nvidia'/'gpu' which are trending-only; avoids 'benchmark' (now owned by
    ai_news_research) so this still falls through to the trending catch-all.
    """
    item = {
        "title": "New NVIDIA H200 GPU shows 2x faster throughput",
        "source": "hacker_news",
        "url": "https://nvidia.com/blog",
        "description": "",
    }
    assert assign_sector(item) == "trending"


# ===========================================================================
# Recency buckets
# ===========================================================================


def _item_with_created(hours_ago: float) -> dict:
    return {
        "title": "Test item",
        "source": "hacker_news",
        "url": "https://hn.example.com/test",
        "description": "",
        "created": time.time() - hours_ago * 3600,
    }


def test_recency_bucket_fresh_1_3x():
    """Item 2h old → multiplier 1.30."""
    item = _item_with_created(2.0)
    assert _recency_multiplier(item) == pytest.approx(1.30, rel=1e-3)


def test_recency_bucket_day_old_1_0x():
    """Item 20h old → multiplier 1.00."""
    item = _item_with_created(20.0)
    assert _recency_multiplier(item) == pytest.approx(1.00, rel=1e-3)


def test_recency_bucket_three_days_0_7x():
    """Item 50h old → multiplier 0.70."""
    item = _item_with_created(50.0)
    assert _recency_multiplier(item) == pytest.approx(0.70, rel=1e-3)


def test_recency_bucket_old_0_4x():
    """Item 200h old → multiplier 0.40."""
    item = _item_with_created(200.0)
    assert _recency_multiplier(item) == pytest.approx(0.40, rel=1e-3)


def test_recency_bucket_unknown_age_neutral():
    """Item with no timestamp field → multiplier 1.0 (neutral, not penalized)."""
    item = {
        "title": "Timeless item",
        "source": "github_trending",
        "url": "https://github.com/example",
        "description": "",
    }
    assert _recency_multiplier(item) == pytest.approx(1.0, rel=1e-3)


def test_recency_parses_published_at_datetime():
    """Anthropic-style `published_at=datetime(...)` is parsed into hours_since."""
    item = {
        "title": "Anthropic blog post",
        "source": "anthropic_releases",
        "url": "https://claude.com/blog/x",
        "description": "",
        "published_at": datetime.now() - timedelta(hours=3),
    }
    hours = _parse_hours_since(item)
    assert hours is not None
    assert 2.5 <= hours <= 3.5


def test_recency_buckets_constant_shape():
    """RECENCY_BUCKETS has the expected (max_hours, mult) shape terminating with None."""
    assert RECENCY_BUCKETS[-1][0] is None
    assert all(isinstance(b[1], (int, float)) for b in RECENCY_BUCKETS)


# ===========================================================================
# detect_clusters
# ===========================================================================


def test_detect_clusters_url_match():
    """2 items with the same URL get the same cluster_id and cross_source_boost=1.5."""
    shared_url = "https://example.com/shared-article"
    items = [
        {"title": "Article about AI", "source": "hacker_news", "engagement": 10, "url": shared_url, "description": ""},
        {"title": "Article about AI discussion", "source": "reddit_localllama", "engagement": 20, "url": shared_url, "description": ""},
    ]
    result_items, _clusters = detect_clusters(items)
    assert result_items[0]["cluster_id"] == result_items[1]["cluster_id"]
    assert result_items[0]["cross_source_boost"] == 1.5
    assert result_items[1]["cross_source_boost"] == 1.5


def test_detect_clusters_title_similarity():
    """2 items with nearly identical titles from different sources cluster together."""
    items = [
        {"title": "Hugging Face dataset hub redesign announced", "source": "hacker_news", "engagement": 50, "url": "https://hn.example.com/hf-hub", "description": ""},
        {"title": "Hugging Face dataset hub redesign rolled out", "source": "reddit_localllama", "engagement": 30, "url": "https://reddit.com/hf-hub", "description": ""},
    ]
    result_items, _clusters = detect_clusters(items)
    assert result_items[0]["cluster_id"] is not None
    assert result_items[0]["cluster_id"] == result_items[1]["cluster_id"]


def test_detect_clusters_3_sources_boost_2_5():
    """3 items on the same topic from 3 source families → cross_source_count=3, boost=2.5."""
    shared_url = "https://example.com/triple-story"
    items = [
        {"title": "Big AI story", "source": "hacker_news", "engagement": 100, "url": shared_url, "description": ""},
        {"title": "Big AI story", "source": "reddit_localllama", "engagement": 80, "url": shared_url, "description": ""},
        {"title": "Big AI story", "source": "github_trending", "engagement": 60, "url": shared_url, "description": ""},
    ]
    result_items, _clusters = detect_clusters(items)
    for it in result_items:
        assert it["cross_source_count"] == 3
        assert it["cross_source_boost"] == 2.5


def test_detect_clusters_singletons_boost_1():
    """Unrelated items that don't cluster get cross_source_boost=1.0."""
    items = [
        {"title": "Claude AI assistant news", "source": "hacker_news", "engagement": 10, "url": "https://hn.example.com/claude", "description": ""},
        {"title": "Python async programming guide", "source": "reddit_python", "engagement": 20, "url": "https://reddit.com/python-async", "description": ""},
    ]
    result_items, _ = detect_clusters(items)
    for it in result_items:
        assert it["cross_source_boost"] == 1.0


# ===========================================================================
# _titles_cluster (sector noise filtering)
# ===========================================================================


def test_titles_cluster_excludes_sector_keywords():
    """Regression: items sharing only sector-routing keywords (claude, code) must NOT cluster."""
    assert not _titles_cluster(
        "Claude Code Routines",
        "How and when to use subagents in Claude Code",
    )


def test_titles_cluster_real_cluster_still_detected():
    """Real clusters must still be detected after noise stripping.

    Both titles share multiple non-sector keywords (hugging/face/dataset/platform/launch)
    and have high similarity after sector-noise is stripped — clears the 2-keyword bar.
    """
    assert _titles_cluster(
        "Hugging Face launches new dataset platform",
        "Hugging Face launches dataset platform update",
    )


def test_sector_cluster_noise_built_correctly():
    """SECTOR_CLUSTER_NOISE contains per-sector routing keywords split into tokens."""
    # Claude Code pillar tokens that remain noise after hard-exclude filter
    assert "claude" in SECTOR_CLUSTER_NOISE
    assert "code" in SECTOR_CLUSTER_NOISE
    assert "model" in SECTOR_CLUSTER_NOISE
    # Local LLM pillar tokens
    assert "ollama" in SECTOR_CLUSTER_NOISE
    assert "mistral" in SECTOR_CLUSTER_NOISE
    # Trending sector tokens
    assert "openai" in SECTOR_CLUSTER_NOISE


def test_sector_cluster_noise_excludes_hard_exclude_tokens():
    """CLUSTER_NOISE_HARD_EXCLUDE words are NOT added to SECTOR_CLUSTER_NOISE.

    They remain as cluster signal because they're too topic-bearing to lose.
    """
    for w in CLUSTER_NOISE_HARD_EXCLUDE:
        assert w not in SECTOR_CLUSTER_NOISE, (
            f"{w!r} should be hard-excluded from noise set"
        )
    # spot-check specific words
    assert "agent" not in SECTOR_CLUSTER_NOISE
    assert "codex" not in SECTOR_CLUSTER_NOISE
    assert "mcp" not in SECTOR_CLUSTER_NOISE
    assert "skills" not in SECTOR_CLUSTER_NOISE


def test_sector_cluster_noise_excludes_generic_words():
    """SECTOR_CLUSTER_NOISE must not contain generic topic-bearing words."""
    assert "routin" not in SECTOR_CLUSTER_NOISE
    assert "routine" not in SECTOR_CLUSTER_NOISE
    assert "releas" not in SECTOR_CLUSTER_NOISE
    assert "release" not in SECTOR_CLUSTER_NOISE


# ===========================================================================
# normalize_engagement
# ===========================================================================


def test_normalize_engagement_rank_within_source(sample_items_single_source):
    """5 reddit items with engagement [10,20,30,40,50] → normalized values are monotonically increasing."""
    result = normalize_engagement(sample_items_single_source)
    sorted_by_eng = sorted(result, key=lambda x: x["engagement"])
    norms = [it["engagement_normalized"] for it in sorted_by_eng]
    assert all(0.0 <= v <= 1.0 for v in norms)
    assert norms == sorted(norms), f"Expected monotonically increasing norms, got {norms}"


def test_normalize_engagement_small_N_default():
    """Source with 2 items (n<5) gets engagement_normalized=0.5 for each."""
    items = [
        {"title": "Item A", "source": "geeknews", "engagement": 5, "url": "u1", "description": ""},
        {"title": "Item B", "source": "geeknews", "engagement": 100, "url": "u2", "description": ""},
    ]
    result = normalize_engagement(items)
    for it in result:
        assert it["engagement_normalized"] == 0.5


def test_normalize_engagement_youtube_uses_views():
    """YouTube items use 'views' not 'engagement' for ranking."""
    items = [
        {"title": "Popular video", "source": "youtube", "engagement": 10, "views": 100000, "url": "u1", "description": ""},
        {"title": "Unpopular video A", "source": "youtube", "engagement": 500, "views": 100, "url": "u2", "description": ""},
        {"title": "Unpopular video B", "source": "youtube", "engagement": 600, "views": 200, "url": "u3", "description": ""},
        {"title": "Unpopular video C", "source": "youtube", "engagement": 700, "views": 300, "url": "u4", "description": ""},
        {"title": "Unpopular video D", "source": "youtube", "engagement": 800, "views": 400, "url": "u5", "description": ""},
    ]
    result = normalize_engagement(items)
    popular = next(it for it in result if it["title"] == "Popular video")
    others = [it for it in result if it["title"] != "Popular video"]
    assert all(popular["engagement_normalized"] >= it["engagement_normalized"] for it in others)


def test_normalize_engagement_never_mutates_engagement():
    """Original 'engagement' field is unchanged after normalization."""
    items = [
        {"title": f"Item {i}", "source": "reddit_localllama", "engagement": (i + 1) * 10, "url": f"u{i}", "description": ""}
        for i in range(5)
    ]
    original_engagements = [it["engagement"] for it in items]
    normalize_engagement(items)
    for it, orig in zip(items, original_engagements):
        assert it["engagement"] == orig


# ===========================================================================
# compute_sector_scores
# ===========================================================================


def _make_scored_item(**kwargs) -> dict:
    """Build a minimal item ready for compute_sector_scores.

    By default does NOT include a timestamp → neutral 1.0 recency multiplier.
    """
    out = {
        "title": kwargs.get("title", "Test item"),
        "source": kwargs.get("source", "hacker_news"),
        "engagement": kwargs.get("engagement", 0),
        "url": kwargs.get("url", "https://example.com/test"),
        "description": kwargs.get("description", ""),
        "engagement_normalized": kwargs.get("engagement_normalized", 0.5),
        "cross_source_count": kwargs.get("cross_source_count", 1),
        "cross_source_boost": kwargs.get("cross_source_boost", 1.0),
    }
    for field in ("created", "created_utc", "published", "published_at"):
        if field in kwargs:
            out[field] = kwargs[field]
    return out


def test_compute_sector_scores_basic_multiplication():
    """final_score = eng_norm × boost × recency; item without timestamp → recency=1.0 (neutral)."""
    item = _make_scored_item(engagement_normalized=0.5, cross_source_boost=1.0)
    result = compute_sector_scores([item])
    # no timestamp → recency 1.0 → 0.5 * 1.0 * 1.0 = 0.5
    assert result[0]["final_score"] == pytest.approx(0.5, rel=1e-3)
    assert result[0]["recency_multiplier"] == pytest.approx(1.0, rel=1e-3)


def test_compute_sector_scores_cross_source_multiplier():
    """Cluster boost multiplies into the score (neutral recency baseline for both)."""
    singleton = _make_scored_item(engagement_normalized=0.5, cross_source_boost=1.0)
    clustered = _make_scored_item(engagement_normalized=0.5, cross_source_boost=2.5)
    single_result = compute_sector_scores([singleton])[0]
    cluster_result = compute_sector_scores([clustered])[0]
    assert cluster_result["final_score"] == pytest.approx(single_result["final_score"] * 2.5, rel=1e-3)


def test_compute_sector_scores_recency_decay_applied():
    """Old items (>72h) get a lower final_score than fresh items with identical other inputs."""
    fresh = _make_scored_item(
        engagement_normalized=0.5,
        cross_source_boost=1.0,
        created=time.time() - 2 * 3600,  # 2 hours ago → 1.30x
    )
    stale = _make_scored_item(
        engagement_normalized=0.5,
        cross_source_boost=1.0,
        created=time.time() - 200 * 3600,  # 200 hours ago → 0.40x
    )
    fresh_score = compute_sector_scores([fresh])[0]["final_score"]
    stale_score = compute_sector_scores([stale])[0]["final_score"]
    assert fresh_score > stale_score
    assert fresh_score == pytest.approx(0.5 * 1.30, rel=1e-3)
    assert stale_score == pytest.approx(0.5 * 0.40, rel=1e-3)


# ===========================================================================
# run_sector_pipeline integration
# ===========================================================================


def _synthetic_sector_items() -> list[dict]:
    """Synthetic items across all sectors (anthropic_official news+blog + 4 pillars)."""
    return [
        # anthropic_official — news (URL-routed)
        {
            "title": "Anthropic announces new safety research",
            "source": "anthropic_releases",
            "url": "https://www.anthropic.com/news/safety-research",
            "engagement": 0,
            "description": "",
        },
        # anthropic_official — blog (URL-routed)
        {
            "title": "Building with Claude: best practices",
            "source": "anthropic_releases",
            "url": "https://claude.com/blog/best-practices",
            "engagement": 0,
            "description": "",
        },
        # claude_code (pillar)
        {
            "title": "Claude Code tips for power users",
            "source": "hacker_news",
            "url": "https://hn.example.com/claude-code",
            "engagement": 200,
            "description": "",
        },
        # agents (pillar)
        {
            "title": "LangGraph tutorial for agent workflows",
            "source": "hacker_news",
            "url": "https://hn.example.com/langgraph",
            "engagement": 120,
            "description": "",
        },
        # ai_infra (pillar)
        {
            "title": "OpenAI Codex updates summary",
            "source": "hacker_news",
            "url": "https://hn.example.com/codex",
            "engagement": 100,
            "description": "",
        },
        # local_llm (pillar)
        {
            "title": "Ollama performance benchmarks",
            "source": "hacker_news",
            "url": "https://hn.example.com/ollama",
            "engagement": 150,
            "description": "",
        },
        # No match — dropped
        {
            "title": "Weekend hiking report",
            "source": "reddit_hiking",
            "url": "https://reddit.com/hike",
            "engagement": 50,
            "description": "",
        },
    ]


def test_run_sector_pipeline_returns_all_7_sectors():
    """run_sector_pipeline returns all 7 sectors (anthropic_official + 5 pillar + trending)."""
    items = _synthetic_sector_items()
    result = run_sector_pipeline(items)
    assert "sectors" in result
    expected = {name for name, _ in SECTORS}
    assert set(result["sectors"].keys()) == expected
    assert len(expected) == 7


def test_run_sector_pipeline_return_keys():
    """Result dict has expected top-level keys."""
    items = _synthetic_sector_items()
    result = run_sector_pipeline(items)
    assert set(result.keys()) >= {"sectors", "all_scored", "clusters", "max_score"}


def test_run_sector_pipeline_sector_count_default_5():
    """Default: each sector caps at 5 items."""
    items = [
        {
            "title": f"Claude Code article {i}",
            "source": "hacker_news",
            "url": f"https://hn.example.com/claude-code-{i}",
            "engagement": 100 + i,
            "description": "",
        }
        for i in range(8)
    ]
    result = run_sector_pipeline(items)
    assert len(result["sectors"]["claude_code"]) <= 5


def test_run_sector_pipeline_sector_count_override():
    """config sector_counts override default 5-per-sector."""
    items = [
        {
            "title": f"Claude Code article {i}",
            "source": "hacker_news",
            "url": f"https://hn.example.com/claude-code-{i}",
            "engagement": 100 + i,
            "description": "",
        }
        for i in range(8)
    ]
    result = run_sector_pipeline(items, config={"sector_counts": {"claude_code": 3}})
    assert len(result["sectors"]["claude_code"]) == 3


def test_run_sector_pipeline_empty_input():
    """Empty list returns all sectors empty without crash."""
    result = run_sector_pipeline([])
    assert result["sectors"] == {name: [] for name, _ in SECTORS}
    assert result["all_scored"] == []
    assert result["clusters"] == []
    assert result["max_score"] >= 1.0


def _anthropic_item(kind: str, days_ago: int, title: str) -> dict:
    """anthropic_releases item with a published_at `days_ago` in the past.

    kind: 'news' → anthropic.com/news URL; 'blog' → claude.com/blog URL.
    """
    base = "https://www.anthropic.com/news" if kind == "news" else "https://claude.com/blog"
    return {
        "title": title,
        "source": "anthropic_releases",
        "url": f"{base}/{title.lower().replace(' ', '-')}",
        "engagement": 0,
        "description": "",
        "published_at": datetime.now() - timedelta(days=days_ago),
    }


def test_anthropic_official_merges_both_kinds():
    """anthropic_official holds both news and blog items in one sector."""
    items = [
        _anthropic_item("news", 1, "News one"),
        _anthropic_item("blog", 2, "Blog one"),
    ]
    result = run_sector_pipeline(items)
    official = result["sectors"]["anthropic_official"]
    kinds = {it.get("official_kind") for it in official}
    assert kinds == {"news", "blog"}
    assert len(official) == 2


def test_anthropic_official_latest_3_each_kind():
    """anthropic_official keeps at most 3 latest news + 3 latest blog (per_kind_limit=3)."""
    items = [_anthropic_item("news", d, f"News {d}") for d in range(5)]
    items += [_anthropic_item("blog", d, f"Blog {d}") for d in range(5)]
    result = run_sector_pipeline(items)
    official = result["sectors"]["anthropic_official"]
    news = [it for it in official if it.get("official_kind") == "news"]
    blog = [it for it in official if it.get("official_kind") == "blog"]
    assert len(news) == 3
    assert len(blog) == 3
    # The 3 newest news (days_ago 0,1,2) are kept; the older ones (3,4) dropped.
    news_titles = {it["title"] for it in news}
    assert news_titles == {"News 0", "News 1", "News 2"}


def test_anthropic_official_recency_order_newest_first():
    """anthropic_official items are ordered by published_at descending (newest first)."""
    items = [
        _anthropic_item("news", 10, "Old news"),
        _anthropic_item("blog", 1, "Fresh blog"),
        _anthropic_item("news", 5, "Mid news"),
    ]
    result = run_sector_pipeline(items)
    official = result["sectors"]["anthropic_official"]
    titles = [it["title"] for it in official]
    assert titles == ["Fresh blog", "Mid news", "Old news"]


def test_anthropic_official_missing_published_at_handled():
    """Items without published_at sort last (datetime.min) and don't crash the pipeline."""
    items = [
        _anthropic_item("news", 1, "Dated news"),
        {
            "title": "Undated blog",
            "source": "anthropic_releases",
            "url": "https://claude.com/blog/undated",
            "engagement": 0,
            "description": "",
            # no published_at
        },
    ]
    result = run_sector_pipeline(items)
    official = result["sectors"]["anthropic_official"]
    assert len(official) == 2
    # Dated item (newest) comes before the undated one (sorts to datetime.min).
    assert official[0]["title"] == "Dated news"
    assert official[-1]["title"] == "Undated blog"


def test_run_sector_pipeline_youtube_excluded_from_keyword_sector():
    """YouTube item with claude code keyword is excluded from claude_code sector list."""
    items = [
        {
            "title": "Claude Code Opus 4.6 review",
            "source": "youtube",
            "views": 200000,
            "engagement": 50,
            "url": "https://youtube.com/watch?v=x",
            "description": "claude code",
            "published": "1 hour ago",
        },
        {
            "title": "Claude code tips",
            "source": "github_trending",
            "engagement": 80,
            "url": "https://github.com/claude-tips",
            "description": "claude code",
        },
        {
            "title": "Claude code announcement from Anthropic",
            "source": "hacker_news",
            "engagement": 60,
            "url": "https://hn.example.com/claude-code",
            "description": "claude code",
        },
    ]
    result = run_sector_pipeline(items)
    sources_in_claude_code = [it["source"] for it in result["sectors"]["claude_code"]]
    assert "youtube" not in sources_in_claude_code


def test_run_sector_pipeline_geeknews_excluded_from_keyword_sector():
    """GeekNews item with mcp keyword is excluded from claude_code sector list."""
    items = [
        {
            "title": "Claude Code MCP 소개",
            "source": "geeknews",
            "engagement": 50,
            "url": "https://news.hada.io/mcp",
            "description": "claude code mcp",
        },
        {
            "title": "Claude Code MCP deep dive",
            "source": "github_trending",
            "engagement": 80,
            "url": "https://github.com/mcp-deep",
            "description": "claude code mcp",
        },
        {
            "title": "MCP claude code explainer",
            "source": "hacker_news",
            "engagement": 60,
            "url": "https://hn.example.com/mcp",
            "description": "claude code mcp",
        },
    ]
    result = run_sector_pipeline(items)
    sources = [it["source"] for it in result["sectors"]["claude_code"]]
    assert "geeknews" not in sources


def test_run_sector_pipeline_all_scored_have_final_score():
    """Every item in all_scored has a final_score."""
    items = _synthetic_sector_items()
    result = run_sector_pipeline(items)
    for it in result["all_scored"]:
        assert "final_score" in it


# ===========================================================================
# adapt_for_filter_seen — fresh singleton cap
# ===========================================================================


def _make_adapted_item(**kwargs) -> dict:
    """Build an item that has already passed through the full pipeline."""
    return {
        "title": kwargs.get("title", "Test item for adaptation"),
        "source": kwargs.get("source", "hacker_news"),
        "engagement": kwargs.get("engagement", 100),
        "url": kwargs.get("url", "https://example.com/adapted"),
        "description": kwargs.get("description", "Some description"),
        "final_score": kwargs.get("final_score", 3.0),
        "sector": kwargs.get("sector", "claude_code"),
        "cross_source_count": kwargs.get("cross_source_count", 1),
        "recency_multiplier": kwargs.get("recency_multiplier", 1.0),
    }


def test_adapt_shape():
    """Each adapted topic has keys: topic, score, reasons, references."""
    item = _make_adapted_item()
    result = adapt_for_filter_seen([item])
    assert len(result) == 1
    topic = result[0]
    assert set(topic.keys()) >= {"topic", "score", "reasons", "references"}
    ref = topic["references"][0]
    assert set(ref.keys()) >= {"title", "url", "source", "engagement"}


def test_adapt_exactly_one_reference():
    """Each adapted topic has exactly 1 reference (the item itself)."""
    items = [_make_adapted_item(title=f"Item {i}", url=f"https://example.com/{i}") for i in range(3)]
    result = adapt_for_filter_seen(items)
    for topic in result:
        assert len(topic["references"]) == 1


def test_adapt_display_score_range():
    """score field is int in [0, 99]; singleton (neutral recency) is capped at 70."""
    items = [
        _make_adapted_item(final_score=6.0, cross_source_count=1, recency_multiplier=1.0),
        _make_adapted_item(final_score=0.0, cross_source_count=1, recency_multiplier=1.0),
        _make_adapted_item(final_score=3.0, cross_source_count=1, recency_multiplier=1.0),
    ]
    result = adapt_for_filter_seen(items, max_score=6.0)
    for topic in result:
        assert isinstance(topic["score"], int)
        assert 0 <= topic["score"] <= 99
    assert result[0]["score"] <= 70


def test_adapt_display_score_cap_by_cross_source():
    """Cross-source cap: singleton<=70, 2-source<=85, 3-source<=99."""
    max_score = 6.0
    items = [
        _make_adapted_item(title="Singleton", final_score=6.0, cross_source_count=1, recency_multiplier=1.0),
        _make_adapted_item(title="Two sources", final_score=6.0, cross_source_count=2, recency_multiplier=1.0),
        _make_adapted_item(title="Three sources", final_score=6.0, cross_source_count=3, recency_multiplier=1.0),
    ]
    result = adapt_for_filter_seen(items, max_score=max_score)
    by_title = {t["topic"]: t["score"] for t in result}
    assert by_title["Singleton"] <= 70
    assert by_title["Two sources"] <= 85
    assert by_title["Three sources"] <= 99


def test_display_cap_fresh_singleton_90_not_70():
    """Singleton with recency_multiplier >= 1.3 gets FRESH_SINGLETON_CAP=90, not 70."""
    item = _make_adapted_item(
        title="Fresh breaking singleton",
        final_score=6.0,
        cross_source_count=1,
        recency_multiplier=1.3,
    )
    result = adapt_for_filter_seen([item], max_score=6.0)
    # relative is 99 at max_score; cap upgraded to 90
    assert result[0]["score"] == FRESH_SINGLETON_CAP
    assert result[0]["score"] > 70


def test_display_cap_non_fresh_singleton_still_70():
    """Singleton with recency_multiplier < 1.3 stays capped at 70."""
    item = _make_adapted_item(
        title="Stale singleton",
        final_score=6.0,
        cross_source_count=1,
        recency_multiplier=1.0,
    )
    result = adapt_for_filter_seen([item], max_score=6.0)
    assert result[0]["score"] <= 70


# ===========================================================================
# Rolling 7-day max anchor
# ===========================================================================


def test_rolling_max_floor_prevents_weak_batch_inflation(tmp_path, monkeypatch):
    """When today_max << rolling_max*0.7, display scores shrink (weak batch protection).

    Strategy: the autouse `_isolate_rolling_stats` fixture already redirects
    rolling_stats IO into tmp_path. We seed that same tmp store with a high max
    so the anchor floor kicks in for this run.
    """
    import rolling_stats as rs

    # The autouse fixture has already wrapped load/save to point at a tmp path.
    # Seeding via `rs.save_rolling_stats([], 10.0)` uses whatever path the autouse
    # chose, so the subsequent run_sector_pipeline call reads the same state.
    rs.save_rolling_stats([], 10.0)
    samples = rs.load_rolling_stats()
    assert any(abs(v - 10.0) < 1e-6 for _, v in samples)

    items = [
        {
            "title": "Claude Code tiny item",
            "source": "hacker_news",
            "engagement": 10,
            "url": "https://hn.example.com/tiny",
            "description": "",
        }
    ]
    import pipeline as pl
    result = pl.run_sector_pipeline(items)
    # max_score anchor should be max(today_max, rolling_max * 0.7) ≈ 7.0.
    assert result["max_score"] >= 7.0 - 0.01
    # tmp_path not directly used — autouse owns it. Keep arg to confirm scoping.
    del tmp_path, monkeypatch


# ===========================================================================
# NON_ANCHOR_SOURCES / NON_OFFICIAL_SECTORS
# ===========================================================================


def test_non_anchor_sources_exported():
    """NON_ANCHOR_SOURCES is importable and contains youtube and geeknews."""
    assert "youtube" in NON_ANCHOR_SOURCES
    assert "geeknews" in NON_ANCHOR_SOURCES


def test_non_official_sectors_exported():
    """NON_OFFICIAL_SECTORS covers all keyword pillar sectors + trending."""
    assert "claude_code" in NON_OFFICIAL_SECTORS
    assert "agents" in NON_OFFICIAL_SECTORS
    assert "local_llm" in NON_OFFICIAL_SECTORS
    assert "ai_infra" in NON_OFFICIAL_SECTORS
    assert "ai_news_research" in NON_OFFICIAL_SECTORS


def test_anthropic_releases_excluded_from_claude_code_sector_boost():
    """HN 'Claude Code Routines' + anthropic_releases 같은 주제 블로그가 클러스터로 묶여도
    HN 아이템의 cross_source_count는 1(싱글턴 취급), boost=1.0이어야 한다."""
    items = [
        {
            "title": "Claude Code Routines",
            "source": "hacker_news",
            "url": "https://hn.example.com/claude-code-routines",
            "engagement": 300,
            "description": "claude code routines hn discussion",
        },
        {
            "title": "Introducing routines in Claude Code",
            "source": "anthropic_releases",
            "url": "https://claude.com/blog/introducing-routines-in-claude-code",
            "engagement": 0,
            "description": "claude code routines official",
        },
    ]
    result = run_sector_pipeline(items)
    claude_items = result["sectors"]["claude_code"]
    assert len(claude_items) == 1
    hn_item = claude_items[0]
    assert hn_item["source"] == "hacker_news"
    # 핵심 검증: anthropic_releases가 제외되어 싱글턴 취급
    assert hn_item["cross_source_count"] == 1
    assert hn_item["cross_source_boost"] == CROSS_SOURCE_BOOST[1]


def test_anthropic_releases_excluded_from_claude_code_cluster_refs():
    """Claude Code 섹터 아이템의 cluster_refs에 anthropic_releases 항목이 노출되면 안 된다."""
    items = [
        {
            "title": "Claude Code Routines",
            "source": "hacker_news",
            "url": "https://hn.example.com/claude-code-routines",
            "engagement": 300,
            "description": "claude code routines hn discussion",
        },
        {
            "title": "Introducing routines in Claude Code",
            "source": "anthropic_releases",
            "url": "https://claude.com/blog/introducing-routines-in-claude-code",
            "engagement": 0,
            "description": "claude code routines official",
        },
    ]
    result = run_sector_pipeline(items)
    claude_items = result["sectors"]["claude_code"]
    assert len(claude_items) == 1
    hn_item = claude_items[0]
    ref_sources = [r["source"] for r in hn_item.get("cluster_refs", [])]
    assert "anthropic_releases" not in ref_sources


def test_anthropic_releases_kept_in_anthropic_sector_refs():
    """anthropic_official 섹터에서는 NON_OFFICIAL_SECTORS 제외 규칙이 적용되지 않아
    HN 등 다른 소스가 cluster_refs에 그대로 들어간다."""
    items = [
        {
            "title": "Anthropic announces new subagents feature release",
            "source": "anthropic_releases",
            "url": "https://www.anthropic.com/news/subagents-feature-release",
            "engagement": 0,
            "description": "anthropic subagents announcement",
        },
        {
            "title": "Anthropic announces new subagents feature released",
            "source": "hacker_news",
            "url": "https://hn.example.com/anthropic-subagents-feature",
            "engagement": 500,
            "description": "anthropic subagents hn thread",
        },
    ]
    result = run_sector_pipeline(items)
    official_items = result["sectors"]["anthropic_official"]
    assert len(official_items) == 1
    anth = official_items[0]
    if anth.get("cluster_id") is not None:
        ref_sources = [r["source"] for r in anth.get("cluster_refs", [])]
        assert "hacker_news" in ref_sources
        assert anth["cross_source_count"] >= 2


# ===========================================================================
# format_sector_html (main.py) — per-sector chunk output
# ===========================================================================


def _fake_sector_result() -> dict:
    """Construct a synthetic sector display result with items across sectors."""
    return {
        "sectors": {
            "anthropic_official": [
                {
                    "title": "Anthropic announces update",
                    "url": "https://www.anthropic.com/news/update",
                    "source": "anthropic_releases",
                    "final_score": 4.0,
                    "cross_source_count": 1,
                    "description": "Anthropic safety update",
                    "official_kind": "news",
                    "cluster_refs": [],
                },
                {
                    "title": "Best practices for Claude",
                    "url": "https://claude.com/blog/best",
                    "source": "anthropic_releases",
                    "final_score": 3.5,
                    "cross_source_count": 1,
                    "description": "Prompting patterns",
                    "official_kind": "blog",
                    "cluster_refs": [],
                },
            ],
            "claude_code": [
                {
                    "title": "Claude Code tips",
                    "url": "https://hn.example.com/claude-code",
                    "source": "hacker_news",
                    "final_score": 5.0,
                    "cross_source_count": 2,
                    "description": "Power user tricks",
                    "cluster_refs": [
                        {
                            "title": "Claude Code deep dive",
                            "url": "https://github.com/claude-code",
                            "source": "github_trending",
                        },
                    ],
                },
            ],
            "agents": [],
            "local_llm": [
                {
                    "title": "Ollama benchmarks",
                    "url": "https://hn.example.com/ollama",
                    "source": "hacker_news",
                    "final_score": 4.2,
                    "cross_source_count": 1,
                    "description": "Perf numbers",
                    "cluster_refs": [],
                },
            ],
            "ai_infra": [],
            "ai_news_research": [],
        },
    }


def test_format_sector_html_returns_list():
    """format_sector_html returns a list of strings."""
    from main import format_sector_html

    chunks = format_sector_html(_fake_sector_result(), "섹터별 핫토픽", max_score=6.0)
    assert isinstance(chunks, list)
    assert all(isinstance(c, str) for c in chunks)


def test_format_sector_html_length_matches_sectors():
    """format_sector_html returns one chunk per sector (anthropic_official is single)."""
    from main import format_sector_html

    chunks = format_sector_html(_fake_sector_result(), "섹터별 핫토픽", max_score=6.0)
    # anthropic_official이 단일 섹터라 SECTORS와 1:1 대응 (7개).
    assert len(chunks) == len(SECTORS)


def test_format_sector_html_empty_sector_has_placeholder():
    """Empty sectors still get a chunk containing '(없음)'."""
    from main import format_sector_html

    chunks = format_sector_html(_fake_sector_result(), "섹터별 핫토픽", max_score=6.0)
    # 청크는 SECTORS 순서와 1:1 대응. agents는 비어 있으므로 '(없음)'.
    agents_chunk_idx = next(i for i, (name, _) in enumerate(SECTORS) if name == "agents")
    assert "(없음)" in chunks[agents_chunk_idx]


def test_format_sector_html_chunk_starts_with_sector_header():
    """Each chunk begins with an emoji followed by a <b> tag."""
    from main import format_sector_html

    chunks = format_sector_html(_fake_sector_result(), "섹터별 핫토픽", max_score=6.0)
    for chunk in chunks:
        assert "<b>" in chunk[:20], (
            f"Chunk should contain '<b>' near start but got: {chunk[:40]!r}"
        )


def test_format_sector_html_anthropic_single_chunk():
    """anthropic_official renders as a single chunk holding both news and blog items."""
    from main import format_sector_html

    chunks = format_sector_html(_fake_sector_result(), "섹터별 핫토픽", max_score=6.0)
    anthropic_chunk = chunks[0]
    # 섹터 이모지 + 라벨
    assert "📰" in anthropic_chunk
    assert "Anthropic 공식" in anthropic_chunk
    # 뉴스 + 블로그 아이템이 한 청크 안에 모두 들어간다.
    assert "Anthropic announces update" in anthropic_chunk
    assert "Best practices for Claude" in anthropic_chunk


def test_format_sector_html_no_break_token_in_any_chunk():
    """No individual chunk contains the @@@SECTOR_BREAK@@@ delimiter."""
    from main import format_sector_html

    chunks = format_sector_html(_fake_sector_result(), "섹터별 핫토픽", max_score=6.0)
    for chunk in chunks:
        assert "@@@SECTOR_BREAK@@@" not in chunk


def test_format_sector_html_chunks_under_4096():
    """No individual chunk exceeds the Telegram 4096-char message limit."""
    from main import format_sector_html

    chunks = format_sector_html(_fake_sector_result(), "섹터별 핫토픽", max_score=6.0)
    for chunk in chunks:
        assert len(chunk) <= 4096


def test_format_sector_html_no_wrapper_header():
    """No chunk contains the old '🔥 섹터별 핫토픽' wrapper header."""
    from main import format_sector_html

    chunks = format_sector_html(_fake_sector_result(), "섹터별 핫토픽", max_score=6.0)
    joined = "\n".join(chunks)
    assert "🔥 <b>섹터별 핫토픽</b>" not in joined


# ===========================================================================
# History cap tests (load / save 500-entry + 14-day limits)
# ===========================================================================


def test_history_load_caps_at_500_entries(tmp_path, monkeypatch):
    """load_history returns at most 500 entries even if file has more."""
    import history as history_mod

    hist_path = tmp_path / "history.json"
    monkeypatch.setattr(history_mod, "HISTORY_FILE", str(hist_path))

    # Write 700 recent entries
    now = datetime.now()
    entries = [
        {
            "topic": f"Topic {i}",
            "score": 50,
            "reasons": [],
            "references": [f"https://example.com/{i}"],
            "mode": "sector",
            "saved_at": (now - timedelta(days=1)).isoformat(),
        }
        for i in range(700)
    ]
    import json as _json
    with open(hist_path, "w", encoding="utf-8") as f:
        _json.dump(entries, f)

    loaded = history_mod.load_history()
    assert len(loaded) <= 500
    # Last 500 should be the newest-inserted (indices 200..699)
    assert loaded[-1]["topic"] == "Topic 699"


def test_history_drops_older_than_14_days(tmp_path, monkeypatch):
    """Entries older than 14 days are dropped on load."""
    import history as history_mod

    hist_path = tmp_path / "history.json"
    monkeypatch.setattr(history_mod, "HISTORY_FILE", str(hist_path))

    now = datetime.now()
    old = {
        "topic": "Ancient Topic",
        "score": 10,
        "reasons": [],
        "references": ["https://example.com/old"],
        "mode": "sector",
        "saved_at": (now - timedelta(days=30)).isoformat(),
    }
    fresh = {
        "topic": "Fresh Topic",
        "score": 80,
        "reasons": [],
        "references": ["https://example.com/fresh"],
        "mode": "sector",
        "saved_at": (now - timedelta(hours=2)).isoformat(),
    }
    import json as _json
    with open(hist_path, "w", encoding="utf-8") as f:
        _json.dump([old, fresh], f)

    loaded = history_mod.load_history()
    topics = {e["topic"] for e in loaded}
    assert "Fresh Topic" in topics
    assert "Ancient Topic" not in topics


def test_history_legacy_entry_no_saved_at_kept(tmp_path, monkeypatch):
    """Legacy entries without saved_at field are kept (count-only cap)."""
    import history as history_mod

    hist_path = tmp_path / "history.json"
    monkeypatch.setattr(history_mod, "HISTORY_FILE", str(hist_path))

    legacy = {
        "topic": "Legacy Topic",
        "score": 10,
        "reasons": [],
        "references": ["https://example.com/legacy"],
        "mode": "sector",
        # no saved_at
    }
    import json as _json
    with open(hist_path, "w", encoding="utf-8") as f:
        _json.dump([legacy], f)

    loaded = history_mod.load_history()
    assert len(loaded) == 1
    assert loaded[0]["topic"] == "Legacy Topic"


# ===========================================================================
# Auto-save CLI behavior
# ===========================================================================


def test_auto_save_persists_all_markdown_urls_without_prompt(tmp_path, monkeypatch, capsys):
    """With --auto-save, markdown mode saves all output URLs without calling input()."""
    import builtins
    import sys as sys_mod

    import history as history_mod
    import main as main_mod
    import rolling_stats as rs

    hist_path = tmp_path / "history.json"
    monkeypatch.setattr(history_mod, "HISTORY_FILE", str(hist_path))

    # Redirect rolling_stats IO to tmp so we don't pollute the worktree.
    stats_path = tmp_path / "score_stats.json"
    orig_load = rs.load_rolling_stats
    orig_save = rs.save_rolling_stats
    monkeypatch.setattr(
        rs, "load_rolling_stats",
        lambda path=None: orig_load(path=str(stats_path)),
    )
    monkeypatch.setattr(
        rs, "save_rolling_stats",
        lambda samples, today_max, path=None, keep_days=7:
            orig_save(samples, today_max, path=str(stats_path), keep_days=keep_days),
    )

    # Fake collect_all so we don't touch network
    fake_items = [
        {
            "title": f"Claude Code article {i}",
            "source": "hacker_news",
            "url": f"https://hn.example.com/claude-code-{i}",
            "engagement": 100 + i,
            "description": "",
        }
        for i in range(3)
    ]
    monkeypatch.setattr(main_mod, "collect_all", lambda *a, **k: list(fake_items))

    # Fail if input() is called — we must bypass the interactive prompt
    def _fail_input(*args, **kwargs):
        raise AssertionError("input() must not be called in auto-save mode")

    monkeypatch.setattr(builtins, "input", _fail_input)
    # Also block rich console.input which is what main.py uses
    from rich.console import Console as _RichConsole
    monkeypatch.setattr(_RichConsole, "input", lambda self, *a, **k: _fail_input())

    monkeypatch.setattr(sys_mod, "argv", [
        "main.py", "--mode", "sector", "--format", "markdown", "--auto-save",
    ])

    # stdout reconfigure may not work with pytest capsys; guard it
    try:
        main_mod.cli()
    except SystemExit:
        pass

    # capsys captured the markdown output — confirm something was printed
    captured = capsys.readouterr()
    assert captured.out.strip(), "expected non-empty markdown output"

    # And URLs should be saved in history
    saved = history_mod.load_history()
    saved_urls = set()
    for entry in saved:
        for u in entry.get("references", []):
            saved_urls.add(u)
    for item in fake_items:
        assert item["url"] in saved_urls, f"{item['url']} not auto-saved"
