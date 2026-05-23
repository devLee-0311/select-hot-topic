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
    DIVERSIFY_SECTORS,
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
    diversify_enabled,
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


def test_assign_sector_cursor_codex_routes_ai_infra():
    """'cursor' or 'codex' route to ai_infra sector."""
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


def test_assign_sector_openai_routes_to_ai_infra():
    """Item with 'openai' keyword (no claude code / agents) routes to ai_infra sector."""
    item = {
        "title": "OpenAI new feature",
        "source": "hacker_news",
        "url": "https://hn.example.com/openai",
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
    """source=anthropic_releases with /news/ URL routes to anthropic_news."""
    item = {
        "title": "New announcement",
        "source": "anthropic_releases",
        "url": "https://www.anthropic.com/news/some-announcement",
        "description": "",
    }
    assert assign_sector(item) == "anthropic_news"


def test_assign_sector_anthropic_releases_blog_url():
    """source=anthropic_releases with claude.com/blog URL routes to anthropic_blog."""
    item = {
        "title": "New blog post",
        "source": "anthropic_releases",
        "url": "https://claude.com/blog/some-post",
        "description": "",
    }
    assert assign_sector(item) == "anthropic_blog"


def test_assign_sector_no_match_returns_none():
    """Item with no matching pillar keyword → None (dropped)."""
    item = {
        "title": "Weekend hiking trail review",
        "source": "reddit_hiking",
        "url": "https://reddit.com/r/hiking/x",
        "description": "",
    }
    assert assign_sector(item) is None


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
        {"title": "Claude model context protocol deep dive", "source": "hacker_news", "engagement": 50, "url": "https://hn.example.com/mcp", "description": ""},
        {"title": "Claude model context protocol deep dive review", "source": "reddit_localllama", "engagement": 30, "url": "https://reddit.com/mcp", "description": ""},
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

    Both titles share 'subagents' + 'feature' and have high similarity after noise is stripped.
    """
    assert _titles_cluster(
        "Claude Code adds new subagents feature",
        "Claude Code subagents feature released",
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
    # AI infra pillar tokens
    assert "cursor" in SECTOR_CLUSTER_NOISE
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
    """Synthetic items across all sectors (2 anthropic + 4 pillars + diversify)."""
    return [
        # anthropic_news (URL-routed)
        {
            "title": "Anthropic announces new safety research",
            "source": "anthropic_releases",
            "url": "https://www.anthropic.com/news/safety-research",
            "engagement": 0,
            "description": "",
        },
        # anthropic_blog (URL-routed)
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
        # ai_news_research (pure research, no tool keyword)
        {
            "title": "DeepMind publishes new scaling-law paper benchmark",
            "source": "reddit_machinelearning",
            "url": "https://reddit.com/r/machinelearning/scaling-law",
            "engagement": 90,
            "description": "scaling law foundation model research",
        },
        # trending_catch_all pair (no keyword match, 2 source families, shared URL)
        {
            "title": "Mystery viral AI demo takes over the internet",
            "source": "hacker_news",
            "url": "https://example.com/viral-ai-demo",
            "engagement": 400,
            "description": "viral demo no keyword",
        },
        {
            "title": "Mystery viral AI demo takes over the internet",
            "source": "reddit_technology",
            "url": "https://example.com/viral-ai-demo",
            "engagement": 350,
            "description": "viral demo no keyword",
        },
        # No match, single source — dropped
        {
            "title": "Weekend hiking report",
            "source": "reddit_hiking",
            "url": "https://reddit.com/hike",
            "engagement": 50,
            "description": "",
        },
    ]


def test_run_sector_pipeline_returns_8_sectors():
    """run_sector_pipeline returns all 8 sectors (2 anthropic + 4 pillar + 2 diversify)."""
    items = _synthetic_sector_items()
    result = run_sector_pipeline(items)
    assert "sectors" in result
    expected = {name for name, _ in SECTORS}
    assert set(result["sectors"].keys()) == expected
    assert len(expected) == 8


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


def test_github_trending_excluded_from_keyword_sector():
    """Phase 2: a GitHub-only item (no cross-source mention) does NOT lead a keyword sector."""
    items = [
        {
            "title": "Claude Code solo trending tool",
            "source": "github_trending",
            "engagement": 500,
            "url": "https://github.com/solo-cc-tool",
            "description": "claude code tool",
        },
    ]
    result = run_sector_pipeline(items)
    sources = [it["source"] for it in result["sectors"]["claude_code"]]
    assert "github_trending" not in sources
    assert result["sectors"]["claude_code"] == []  # github demoted → no anchor


def test_github_trending_still_appears_via_hn_anchor():
    """Phase 2: a GitHub item that also trends on HN still appears (HN anchor, GitHub in refs)."""
    items = [
        {
            "title": "Claude Code mega feature launch",
            "source": "github_trending",
            "engagement": 500,
            "url": "https://example.com/cc-mega",
            "description": "claude code mega feature",
        },
        {
            "title": "Claude Code mega feature launch",
            "source": "hacker_news",
            "engagement": 300,
            "url": "https://example.com/cc-mega",
            "description": "claude code mega feature",
        },
    ]
    result = run_sector_pipeline(items)
    cc = result["sectors"]["claude_code"]
    # The HN item leads (anchor); github_trending appears only as a ref.
    assert len(cc) == 1
    assert cc[0]["source"] == "hacker_news"
    ref_sources = [r["source"] for r in cc[0].get("cluster_refs", [])]
    assert "github_trending" in ref_sources
    assert cc[0]["cross_source_count"] >= 2


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
    """NON_OFFICIAL_SECTORS covers all 4 pillar sectors."""
    assert "claude_code" in NON_OFFICIAL_SECTORS
    assert "agents" in NON_OFFICIAL_SECTORS
    assert "local_llm" in NON_OFFICIAL_SECTORS
    assert "ai_infra" in NON_OFFICIAL_SECTORS


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
    """anthropic_news 섹터에서는 NON_OFFICIAL_SECTORS 제외 규칙이 적용되지 않아
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
    news_items = result["sectors"]["anthropic_news"]
    assert len(news_items) == 1
    anth = news_items[0]
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
            "anthropic_news": [
                {
                    "title": "Anthropic announces update",
                    "url": "https://www.anthropic.com/news/update",
                    "source": "anthropic_releases",
                    "final_score": 4.0,
                    "cross_source_count": 1,
                    "description": "Anthropic safety update",
                    "cluster_refs": [],
                },
            ],
            "anthropic_blog": [
                {
                    "title": "Best practices for Claude",
                    "url": "https://claude.com/blog/best",
                    "source": "anthropic_releases",
                    "final_score": 3.5,
                    "cross_source_count": 1,
                    "description": "Prompting patterns",
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
            "ai_news_research": [
                {
                    "title": "New scaling-law paper",
                    "url": "https://reddit.com/r/ml/scaling",
                    "source": "reddit_machinelearning",
                    "final_score": 2.0,
                    "cross_source_count": 1,
                    "description": "scaling law research",
                    "cluster_refs": [],
                },
            ],
            "trending_catch_all": [
                {
                    "title": "Viral AI demo",
                    "url": "https://example.com/viral",
                    "source": "hacker_news",
                    "final_score": 3.0,
                    "cross_source_count": 2,
                    "description": "viral demo",
                    "cluster_refs": [],
                },
            ],
        },
    }


def test_format_sector_html_returns_list():
    """format_sector_html returns a list of strings."""
    from main import format_sector_html

    chunks = format_sector_html(_fake_sector_result(), "섹터별 핫토픽", max_score=6.0)
    assert isinstance(chunks, list)
    assert all(isinstance(c, str) for c in chunks)


def test_format_sector_html_length_matches_sectors():
    """format_sector_html returns exactly len(SECTORS) chunks even with empty sectors."""
    from main import format_sector_html

    chunks = format_sector_html(_fake_sector_result(), "섹터별 핫토픽", max_score=6.0)
    assert len(chunks) == len(SECTORS)


def test_format_sector_html_empty_sector_has_placeholder():
    """Empty sectors still get a chunk containing '(없음)'."""
    from main import format_sector_html

    chunks = format_sector_html(_fake_sector_result(), "섹터별 핫토픽", max_score=6.0)
    agents_idx = next(i for i, (name, _) in enumerate(SECTORS) if name == "agents")
    assert "(없음)" in chunks[agents_idx]


def test_format_sector_html_chunk_starts_with_sector_header():
    """Each chunk begins with the sector's emoji followed by a <b> tag."""
    from main import format_sector_html

    chunks = format_sector_html(_fake_sector_result(), "섹터별 핫토픽", max_score=6.0)
    for chunk, (_name, cfg) in zip(chunks, SECTORS):
        emoji = cfg.get("emoji", "")
        assert chunk.startswith(f"{emoji} <b>"), (
            f"Chunk should start with '{emoji} <b>' but got: {chunk[:40]!r}"
        )


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


# ===========================================================================
# Phase 1: ai_news_research routing (after-tools order, A1 tradeoff)
# ===========================================================================


def test_assign_sector_ai_news_research_keyword():
    """Research keyword (no tool keyword) routes to ai_news_research."""
    item = {
        "title": "New benchmark released for foundation models",
        "source": "hacker_news",
        "url": "https://hn.example.com/benchmark",
        "description": "",
    }
    assert assign_sector(item) == "ai_news_research"


def test_pure_research_routes_to_ai_news_research():
    """Pure research item (no tool keyword) routes to ai_news_research."""
    item = {
        "title": "Google DeepMind publishes new scaling-law paper",
        "source": "hacker_news",
        "url": "https://hn.example.com/scaling-law",
        "description": "",
    }
    assert assign_sector(item) == "ai_news_research"


def test_ai_regulation_routes_to_ai_news_research():
    """Policy/news item (no tool keyword) routes to ai_news_research."""
    item = {
        "title": "EU passes comprehensive AI regulation act",
        "source": "hacker_news",
        "url": "https://hn.example.com/eu-ai-act",
        "description": "",
    }
    assert assign_sector(item) == "ai_news_research"


def test_mixed_tool_research_item_stays_in_tool_sector():
    """Mixed tool+research items route to their tool sector (A1 zero-leakage tradeoff)."""
    # "openai" matches ai_infra first → not ai_news_research
    openai_item = {
        "title": "OpenAI announces GPT-5 with breakthrough reasoning paper",
        "source": "hacker_news",
        "url": "https://hn.example.com/gpt5-paper",
        "description": "",
    }
    assert assign_sector(openai_item) == "ai_infra"

    # "langgraph" matches agents first → no leakage into ai_news_research
    langgraph_item = {
        "title": "LangGraph adds chain of thought reasoning",
        "source": "hacker_news",
        "url": "https://hn.example.com/langgraph-cot",
        "description": "",
    }
    assert assign_sector(langgraph_item) == "agents"


def test_assign_sector_deny_prevents_tool_leak():
    """Deny list on ai_news_research blocks tool terms (defensive belt-and-suspenders).

    A title that ONLY matches a research keyword plus a denied tool term must not
    land in ai_news_research. 'cursor' is in the deny list; here the research term
    'multimodal' would match include, but 'cursor' triggers deny.

    Note: 'cursor' also matches ai_infra (which is checked first), so this item
    routes to ai_infra. The deny is a safety net if ordering ever changed.
    """
    item = {
        "title": "Cursor multimodal preview",
        "source": "hacker_news",
        "url": "https://hn.example.com/cursor-multimodal",
        "description": "",
    }
    # ai_infra wins by order; critically NOT ai_news_research.
    assert assign_sector(item) == "ai_infra"
    assert assign_sector(item) != "ai_news_research"


def test_assign_sector_trending_catch_all_never_keyword_routed():
    """assign_sector never returns trending_catch_all even though it is in KEYWORD_SECTORS."""
    # An item with no keyword match → None (not catch-all; that's step 3b's job)
    item = {
        "title": "Completely unrelated cooking recipe",
        "source": "reddit_food",
        "url": "https://reddit.com/food",
        "description": "",
    }
    assert assign_sector(item) is None
    # Even a research-flavored item never returns trending_catch_all from assign_sector
    research = {
        "title": "New benchmark paper",
        "source": "hacker_news",
        "url": "https://hn.example.com/b",
        "description": "",
    }
    assert assign_sector(research) != "trending_catch_all"


# ===========================================================================
# Phase 1: trending_catch_all post-clustering routing (step 3b)
# ===========================================================================


def test_catch_all_captures_unrouted_corroborated_item():
    """Item matching no keyword sector with cross_source_count=2 lands in trending_catch_all."""
    items = [
        {
            "title": "Mystery viral demo sweeps the web",
            "source": "hacker_news",
            "url": "https://example.com/viral-x",
            "engagement": 400,
            "description": "no keyword here",
        },
        {
            "title": "Mystery viral demo sweeps the web",
            "source": "reddit_technology",
            "url": "https://example.com/viral-x",
            "engagement": 350,
            "description": "no keyword here",
        },
    ]
    result = run_sector_pipeline(items)
    # Both items corroborate each other (shared URL, 2 families) → catch-all.
    catch_all = result["sectors"]["trending_catch_all"]
    assert len(catch_all) >= 1
    for it in catch_all:
        assert it["sector"] == "trending_catch_all"
        assert it["cross_source_count"] >= 2


def test_catch_all_single_source_stays_dropped():
    """Item matching no keyword sector with cross_source_count=1 stays None (dropped)."""
    items = [
        {
            "title": "Lonely uncorroborated curiosity",
            "source": "hacker_news",
            "url": "https://example.com/lonely",
            "engagement": 400,
            "description": "no keyword",
        },
    ]
    result = run_sector_pipeline(items)
    assert result["sectors"]["trending_catch_all"] == []
    # The item itself stays unrouted.
    lonely = next(i for i in result["all_scored"] if i["title"].startswith("Lonely"))
    assert lonely["sector"] is None


def test_catch_all_keyword_item_not_captured():
    """An item that DOES match a keyword sector never falls into catch-all even if corroborated."""
    items = [
        {
            "title": "Claude Code new feature",
            "source": "hacker_news",
            "url": "https://example.com/cc-feat",
            "engagement": 400,
            "description": "claude code",
        },
        {
            "title": "Claude Code new feature",
            "source": "reddit_programming",
            "url": "https://example.com/cc-feat",
            "engagement": 350,
            "description": "claude code",
        },
    ]
    result = run_sector_pipeline(items)
    # Routed to claude_code, not catch-all.
    assert result["sectors"]["trending_catch_all"] == []
    assert len(result["sectors"]["claude_code"]) >= 1


# ===========================================================================
# Phase 1: research item with real engagement gets a slot
# ===========================================================================


def test_research_item_from_machinelearning_gets_slot():
    """A low-engagement r/MachineLearning research item appears in ai_news_research."""
    items = [
        {
            "title": "New paper on mixture of experts scaling",
            "source": "reddit_machinelearning",
            "url": "https://reddit.com/r/machinelearning/moe-paper",
            "engagement": 15,  # low but real
            "description": "mixture of experts scaling law",
        },
    ]
    result = run_sector_pipeline(items)
    research = result["sectors"]["ai_news_research"]
    assert len(research) == 1
    item = research[0]
    assert item["source"] == "reddit_machinelearning"
    # Real engagement → final_score > 0 (singleton normalized to 1.0 * boost 1.0 * recency)
    assert item["final_score"] > 0


def test_mixed_pipeline_produces_both_tool_and_research():
    """Full mixed pipeline yields output in BOTH a tool sector AND ai_news_research."""
    items = _synthetic_sector_items()
    result = run_sector_pipeline(items)
    assert len(result["sectors"]["claude_code"]) >= 1
    assert len(result["sectors"]["ai_news_research"]) >= 1


# ===========================================================================
# Phase 1: sectors_full exposure + cluster_refs before slice (N1)
# ===========================================================================


def test_run_sector_pipeline_returns_sectors_full():
    """Result includes sectors_full (unsliced per-sector candidate pool)."""
    items = _synthetic_sector_items()
    result = run_sector_pipeline(items)
    assert "sectors_full" in result
    assert set(result["sectors_full"].keys()) == {name for name, _ in SECTORS}


def test_sectors_full_superset_of_sliced():
    """sectors_full[name] contains at least as many items as the sliced sectors[name]."""
    # 6 claude_code items but count caps display at 5 → full has 6, sliced has 5.
    items = [
        {
            "title": f"Claude Code article {i}",
            "source": "hacker_news",
            "url": f"https://hn.example.com/claude-code-{i}",
            "engagement": 100 + i,
            "description": "",
        }
        for i in range(6)
    ]
    result = run_sector_pipeline(items)
    assert len(result["sectors_full"]["claude_code"]) == 6
    assert len(result["sectors"]["claude_code"]) == 5


def test_cluster_refs_attached_before_slice():
    """cluster_refs are attached to items beyond the count slice (N1 fix).

    Build a clustered claude_code topic ranked beyond the slice and confirm it
    carries cluster_refs in sectors_full.
    """
    items = []
    # 5 high-engagement singletons to fill the top-5 slice.
    for i in range(5):
        items.append({
            "title": f"Claude Code distinct topic {i}",
            "source": "hacker_news",
            "url": f"https://hn.example.com/cc-distinct-{i}",
            "engagement": 1000 + i,
            "description": "",
        })
    # A clustered (2-source) claude_code item with LOW engagement → ranked beyond slice.
    items.append({
        "title": "Claude Code niche corroborated thing",
        "source": "hacker_news",
        "url": "https://example.com/cc-niche",
        "engagement": 5,
        "description": "claude code niche",
    })
    items.append({
        "title": "Claude Code niche corroborated thing",
        "source": "reddit_programming",
        "url": "https://example.com/cc-niche",
        "engagement": 3,
        "description": "claude code niche",
    })
    result = run_sector_pipeline(items)
    full = result["sectors_full"]["claude_code"]
    niche = next(it for it in full if "niche" in it["title"])
    # The niche item is beyond the top-5 slice but still carries cluster_refs.
    assert niche["cross_source_count"] >= 2
    assert "cluster_refs" in niche
    assert len(niche["cluster_refs"]) >= 1


# ===========================================================================
# Phase 1: rollback (DISABLE_DIVERSIFY_SECTORS)
# ===========================================================================


def test_diversify_enabled_default_true(monkeypatch):
    """diversify_enabled() returns True when env var is unset."""
    monkeypatch.delenv("DISABLE_DIVERSIFY_SECTORS", raising=False)
    assert diversify_enabled() is True


def test_diversify_enabled_false_when_disabled(monkeypatch):
    """diversify_enabled() returns False when DISABLE_DIVERSIFY_SECTORS=1."""
    monkeypatch.setenv("DISABLE_DIVERSIFY_SECTORS", "1")
    assert diversify_enabled() is False


def test_rollback_env_var_reverts_to_6_sectors(monkeypatch, tmp_path, capsys):
    """DISABLE_DIVERSIFY_SECTORS=1 → pipeline yields 6 sectors AND main.py floor is inert.

    Verifies the cross-module gate: both run_sector_pipeline (6 keys, no catch-all)
    AND the main.py diversity-floor block must be disabled by the same env var.
    """
    monkeypatch.setenv("DISABLE_DIVERSIFY_SECTORS", "1")

    # --- Part 1: pipeline yields 6 sectors, no diversify sectors, catch-all skipped ---
    items = _synthetic_sector_items()
    result = run_sector_pipeline(items)
    assert result["diversify_enabled"] is False
    assert set(result["sectors"].keys()) == {
        "anthropic_news", "anthropic_blog",
        "claude_code", "agents", "local_llm", "ai_infra",
    }
    assert len(result["sectors"]) == 6
    for diversify_name in DIVERSIFY_SECTORS:
        assert diversify_name not in result["sectors"]
    # The corroborated unrouted pair must NOT be captured (catch-all disabled).
    for it in result["all_scored"]:
        assert it.get("sector") != "trending_catch_all"

    # --- Part 2: main.py floor block is inert under the env var ---
    import builtins
    import sys as sys_mod

    import history as history_mod
    import main as main_mod
    import rolling_stats as rs

    hist_path = tmp_path / "history.json"
    monkeypatch.setattr(history_mod, "HISTORY_FILE", str(hist_path))
    stats_path = tmp_path / "score_stats.json"
    orig_load = rs.load_rolling_stats
    orig_save = rs.save_rolling_stats
    monkeypatch.setattr(
        rs, "load_rolling_stats", lambda path=None: orig_load(path=str(stats_path))
    )
    monkeypatch.setattr(
        rs, "save_rolling_stats",
        lambda samples, today_max, path=None, keep_days=7:
            orig_save(samples, today_max, path=str(stats_path), keep_days=keep_days),
    )

    fake_items = [
        {
            "title": "Claude Code article",
            "source": "hacker_news",
            "url": "https://hn.example.com/cc-rollback",
            "engagement": 120,
            "description": "",
        },
    ]
    monkeypatch.setattr(main_mod, "collect_all", lambda *a, **k: list(fake_items))

    def _fail_input(*a, **k):
        raise AssertionError("input() must not be called in auto-save mode")

    monkeypatch.setattr(builtins, "input", _fail_input)
    from rich.console import Console as _RichConsole
    monkeypatch.setattr(_RichConsole, "input", lambda self, *a, **k: _fail_input())
    monkeypatch.setattr(sys_mod, "argv", [
        "main.py", "--mode", "sector", "--format", "markdown", "--auto-save",
    ])

    try:
        main_mod.cli()
    except SystemExit:
        pass

    out = capsys.readouterr().out
    # Output should have exactly 6 sector chunks (delimiter count = 5).
    assert out.count("@@@SECTOR_BREAK@@@") == 5
    # Diversify sector labels must not appear.
    assert "AI 뉴스 & 연구" not in out
    assert "AI 트렌딩" not in out


# ===========================================================================
# Phase 1: diversity floor (main.py) — backfill fresh / no resurface
# ===========================================================================


def _run_cli_markdown(monkeypatch, tmp_path, capsys, fake_items, seed_history_urls=None):
    """Drive main.cli() in markdown auto-save mode with mocked sources + isolated history.

    Returns the captured stdout (markdown output).
    """
    import builtins
    import sys as sys_mod

    import history as history_mod
    import main as main_mod
    import rolling_stats as rs

    hist_path = tmp_path / "history.json"
    monkeypatch.setattr(history_mod, "HISTORY_FILE", str(hist_path))

    # Seed history with already-shown URLs (mark them "seen").
    if seed_history_urls:
        import json as _json
        from datetime import datetime as _dt
        entries = [
            {
                "topic": f"seed {i}",
                "score": 0,
                "reasons": [],
                "references": [u],
                "mode": "sector",
                "saved_at": _dt.now().isoformat(),
            }
            for i, u in enumerate(seed_history_urls)
        ]
        with open(hist_path, "w", encoding="utf-8") as f:
            _json.dump(entries, f)

    stats_path = tmp_path / "score_stats.json"
    orig_load = rs.load_rolling_stats
    orig_save = rs.save_rolling_stats
    monkeypatch.setattr(
        rs, "load_rolling_stats", lambda path=None: orig_load(path=str(stats_path))
    )
    monkeypatch.setattr(
        rs, "save_rolling_stats",
        lambda samples, today_max, path=None, keep_days=7:
            orig_save(samples, today_max, path=str(stats_path), keep_days=keep_days),
    )

    monkeypatch.setattr(main_mod, "collect_all", lambda *a, **k: list(fake_items))

    def _fail_input(*a, **k):
        raise AssertionError("input() must not be called in auto-save mode")

    monkeypatch.setattr(builtins, "input", _fail_input)
    from rich.console import Console as _RichConsole
    monkeypatch.setattr(_RichConsole, "input", lambda self, *a, **k: _fail_input())
    monkeypatch.setattr(sys_mod, "argv", [
        "main.py", "--mode", "sector", "--format", "markdown", "--auto-save",
    ])

    try:
        main_mod.cli()
    except SystemExit:
        pass

    return capsys.readouterr().out


def _floor_keepalive_item():
    """A fresh claude_code anchor item that always survives filter_seen.

    Keeps the global `wrapped` list non-empty so main.cli() does NOT take the
    early "새로운 추천 토픽이 없습니다." return before the floor block runs.
    """
    return {
        "title": "Keepalive Claude Code tip",
        "source": "hacker_news",
        "url": "https://hn.example.com/keepalive-cc",
        "engagement": 500,
        "description": "claude code",
    }


def _research_items_4_seen_1_fresh():
    """4 high-score SEEN research items + 1 low-score FRESH research item (all reddit_ML).

    All 5 share the reddit family so engagement normalization gives distinct ranks;
    the fresh item (lowest engagement) ranks 5th, beyond the count=4 slice.

    Titles/descriptions are deliberately distinct (different research keywords) so the
    items do NOT cluster together — this keeps the floor test focused on primary-entry
    backfill behavior rather than incidental cluster_refs.
    """
    seen_specs = [
        ("Distillation tradeoffs in compact transformers", "distillation"),
        ("Reward model calibration under rlhf drift", "rlhf"),
        ("Long context retrieval for retrieval systems", "long context"),
        ("Mixture of experts routing stability study", "mixture of experts"),
    ]
    seen = [
        {
            "title": title,
            "source": "reddit_machinelearning",
            "url": f"https://reddit.com/r/ml/seen-{i}",
            "engagement": 200 - i * 10,  # 200,190,180,170 → top-4 by rank
            "description": kw,
        }
        for i, (title, kw) in enumerate(seen_specs)
    ]
    fresh = {
        "title": "Fresh unseen scaling law preprint",
        "source": "reddit_machinelearning",
        "url": "https://reddit.com/r/ml/fresh-unseen",
        "engagement": 5,  # lowest → ranked 5th, beyond count=4 slice
        "description": "scaling law preprint",
    }
    return seen, fresh


def test_floor_backfills_fresh_item_after_filter_seen(monkeypatch, tmp_path, capsys):
    """When sliced ai_news_research items are all seen but sectors_full has an unseen
    candidate, the floor restores >= 1 FRESH item that is not in history."""
    monkeypatch.delenv("DISABLE_DIVERSIFY_SECTORS", raising=False)
    seen, fresh = _research_items_4_seen_1_fresh()
    keepalive = _floor_keepalive_item()
    fake_items = seen + [fresh, keepalive]
    # Only the seen research items are in history (keepalive + fresh stay unseen).
    seen_urls = [s["url"] for s in seen]

    out = _run_cli_markdown(
        monkeypatch, tmp_path, capsys, fake_items, seed_history_urls=seen_urls
    )
    # The fresh (unseen) item should be backfilled into the ai_news_research chunk.
    assert "Fresh unseen scaling law preprint" in out
    # None of the seen items should resurface as a primary entry.
    for s in seen:
        assert s["title"] not in out


def test_floor_does_not_resurface_seen_items(monkeypatch, tmp_path, capsys):
    """When EVERY candidate (sliced + unsliced) is seen, ai_news_research stays empty —
    no stale repeat (A2)."""
    monkeypatch.delenv("DISABLE_DIVERSIFY_SECTORS", raising=False)
    seen, fresh = _research_items_4_seen_1_fresh()
    keepalive = _floor_keepalive_item()
    fake_items = seen + [fresh, keepalive]
    # Seed ALL research urls (including the would-be-fresh one) as seen.
    # keepalive stays unseen so the pipeline still produces output.
    all_urls = [s["url"] for s in seen] + [fresh["url"]]

    out = _run_cli_markdown(
        monkeypatch, tmp_path, capsys, fake_items, seed_history_urls=all_urls
    )
    # No research item resurfaces.
    for s in seen:
        assert s["title"] not in out
    assert "Fresh unseen scaling law preprint" not in out
    # The ai_news_research chunk shows the empty placeholder.
    # Match by the sector emoji (🔬) since the label '&' is HTML-escaped to '&amp;'.
    chunks = out.split("@@@SECTOR_BREAK@@@")
    research_chunk = next(c for c in chunks if "🔬" in c)
    assert "(없음)" in research_chunk


# ===========================================================================
# Phase 1: observability logging
# ===========================================================================


def test_sector_item_counts_logged(caplog):
    """run_sector_pipeline emits a per-run sector_item_counts log line."""
    import logging
    items = _synthetic_sector_items()
    with caplog.at_level(logging.INFO, logger="pipeline"):
        run_sector_pipeline(items)
    assert any("sector_item_counts" in rec.message for rec in caplog.records)


# ===========================================================================
# Phase 1: format_sector_html handles 8 sectors
# ===========================================================================


def test_format_sector_html_8_chunks():
    """format_sector_html returns exactly 8 chunks (one per sector)."""
    from main import format_sector_html

    chunks = format_sector_html(_fake_sector_result(), "섹터별 핫토픽", max_score=6.0)
    assert len(chunks) == 8
    assert len(chunks) == len(SECTORS)


# ===========================================================================
# Phase 1: r/MachineLearning fetcher shape (mocked HTTP)
# ===========================================================================


def test_reddit_machinelearning_fetcher_shape(monkeypatch):
    """fetch_reddit_machinelearning returns dicts with source=reddit_machinelearning, engagement>0."""
    import sources.reddit_subs as reddit_subs

    class _FakeResp:
        def raise_for_status(self):
            pass

        def json(self):
            return {
                "data": {
                    "children": [
                        {
                            "data": {
                                "title": "New SOTA on ImageNet",
                                "selftext": "We present a new model...",
                                "permalink": "/r/MachineLearning/comments/abc/new_sota/",
                                "score": 120,
                                "num_comments": 45,
                                "created_utc": 1_700_000_000,
                                "stickied": False,
                            }
                        },
                        {
                            "data": {
                                "title": "Stickied megathread",
                                "selftext": "",
                                "permalink": "/r/MachineLearning/comments/xyz/megathread/",
                                "score": 9999,
                                "num_comments": 9999,
                                "created_utc": 1_700_000_000,
                                "stickied": True,
                            }
                        },
                    ]
                }
            }

    def _fake_get(url, **kwargs):
        assert "MachineLearning" in url
        return _FakeResp()

    monkeypatch.setattr(reddit_subs.requests, "get", _fake_get)

    results = reddit_subs.fetch_reddit_machinelearning()
    assert len(results) == 1  # stickied filtered out
    item = results[0]
    assert item["source"] == "reddit_machinelearning"
    assert item["engagement"] == 165  # 120 + 45
    assert item["engagement"] > 0
    assert item["url"].startswith("https://reddit.com/")
    assert item["title"] == "New SOTA on ImageNet"
