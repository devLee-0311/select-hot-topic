"""Unit and integration tests for pipeline.py.

All data is synthetic — no network calls.
Each test verifies exactly one behavior.
"""

from __future__ import annotations

import time

import pytest

from pipeline import (
    adapt_for_filter_seen,
    classify_content_type,
    compute_final_scores,
    detect_clusters,
    normalize_engagement,
    run_pipeline,
    tag_tiers,
)


# ===========================================================================
# tag_tiers
# ===========================================================================


def test_tag_tiers_tier1_passes_low_engagement(sample_tier1_item):
    """tier1 item (contains 'claude') with engagement=0 is kept and tagged tier1."""
    result = tag_tiers([sample_tier1_item])
    assert len(result) == 1
    assert result[0]["matched_tier"] == "tier1"


def test_tag_tiers_tier2_below_threshold_dropped(sample_tier2_item):
    """tier2 item (contains 'cursor') below hackernews threshold (10) is dropped."""
    # engagement=5, hackernews threshold=10 → should be dropped
    result = tag_tiers([sample_tier2_item])
    assert len(result) == 0


def test_tag_tiers_tier3_cross_source_kept():
    """tier3 item is kept when it has a cross-source counterpart with similar title."""
    # Two items with the same topic from different source families
    item_a = {
        "title": "LLM inference optimization techniques",
        "source": "hacker_news",
        "engagement": 1,
        "url": "https://hn.example.com/llm-inference",
        "description": "",
    }
    item_b = {
        "title": "LLM inference optimization techniques",
        "source": "reddit_localllama",
        "engagement": 1,
        "url": "https://reddit.com/llm-inference",
        "description": "",
    }
    result = tag_tiers([item_a, item_b])
    # Both should survive because each has a cross-source counterpart
    assert any(it["matched_tier"] == "tier3" for it in result)


def test_tag_tiers_tier3_low_percentile_dropped():
    """tier3 item alone in batch with low engagement is dropped (no cross-source, not top10)."""
    item = {
        "title": "LLM inference optimization techniques",
        "source": "reddit_localllama",
        "engagement": 1,
        "url": "https://reddit.com/llm-inference",
        "description": "",
    }
    # Batch: this item + 9 high-engagement items with titles that share no stems
    # with "LLM inference optimization techniques" (verified similarity < 0.4 each)
    filler_titles = [
        "Weekend hiking trail review",
        "Baking sourdough bread recipe",
        "Stock market quarterly earnings",
        "Ocean swimming safety tips",
        "Gardening tomato planting calendar",
        "Chess opening strategy endgame",
        "Knitting wool sweater pattern",
        "Astronomy telescope stargazing guide",
        "Vintage car restoration bodywork",
    ]
    high_items = [
        {
            "title": title,
            "source": "hacker_news",
            "engagement": 1000 * (i + 1),
            "url": f"https://hn.example.com/filler-{i}",
            "description": "",
        }
        for i, title in enumerate(filler_titles)
    ]
    result = tag_tiers([item] + high_items)
    # The tier3 item should be dropped; high items have no tier keywords so also dropped
    tier3_items = [it for it in result if it.get("matched_tier") == "tier3"]
    assert len(tier3_items) == 0


def test_tag_tiers_no_match_dropped():
    """Item with no tier keyword is excluded from result."""
    item = {
        "title": "Weekend hiking trip report",
        "source": "reddit_hiking",
        "engagement": 999,
        "url": "https://reddit.com/r/hiking/trip-report",
        "description": "",
    }
    result = tag_tiers([item])
    assert len(result) == 0


def test_tag_tiers_skip_tiering_all_pass_tier2():
    """skip_tiering=True gives all items matched_tier='tier2' regardless of keywords."""
    items = [
        {"title": "Weekend hiking trip", "source": "reddit", "engagement": 0, "url": "u1", "description": ""},
        {"title": "Claude new model", "source": "hacker_news", "engagement": 0, "url": "u2", "description": ""},
        {"title": "Random news story", "source": "geeknews", "engagement": 0, "url": "u3", "description": ""},
    ]
    result = tag_tiers(items, skip_tiering=True)
    assert len(result) == 3
    assert all(it["matched_tier"] == "tier2" for it in result)


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
    tagged = [dict(it, matched_tier="tier1") for it in items]
    result_items, clusters = detect_clusters(tagged)
    assert result_items[0]["cluster_id"] == result_items[1]["cluster_id"]
    assert result_items[0]["cross_source_boost"] == 1.5
    assert result_items[1]["cross_source_boost"] == 1.5


def test_detect_clusters_title_similarity():
    """2 items with nearly identical titles from different sources cluster together."""
    items = [
        {"title": "Claude model context protocol deep dive", "source": "hacker_news", "engagement": 50, "url": "https://hn.example.com/mcp", "description": ""},
        {"title": "Claude model context protocol deep dive review", "source": "reddit_localllama", "engagement": 30, "url": "https://reddit.com/mcp", "description": ""},
    ]
    tagged = [dict(it, matched_tier="tier1") for it in items]
    result_items, clusters = detect_clusters(tagged)
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
    tagged = [dict(it, matched_tier="tier1") for it in items]
    result_items, clusters = detect_clusters(tagged)
    for it in result_items:
        assert it["cross_source_count"] == 3
        assert it["cross_source_boost"] == 2.5


def test_detect_clusters_4_plus_sources_boost_4_0():
    """4+ items from 4 different source families get cross_source_boost=4.0."""
    shared_url = "https://example.com/quad-story"
    items = [
        {"title": "Viral AI story", "source": "hacker_news", "engagement": 200, "url": shared_url, "description": ""},
        {"title": "Viral AI story", "source": "reddit_localllama", "engagement": 150, "url": shared_url, "description": ""},
        {"title": "Viral AI story", "source": "github_trending", "engagement": 100, "url": shared_url, "description": ""},
        {"title": "Viral AI story", "source": "youtube", "engagement": 50, "url": shared_url, "description": ""},
    ]
    tagged = [dict(it, matched_tier="tier1") for it in items]
    result_items, clusters = detect_clusters(tagged)
    for it in result_items:
        assert it["cross_source_boost"] == 4.0


def test_detect_clusters_singletons_boost_1():
    """Unrelated items that don't cluster get cross_source_boost=1.0."""
    items = [
        {"title": "Claude AI assistant news", "source": "hacker_news", "engagement": 10, "url": "https://hn.example.com/claude", "description": ""},
        {"title": "Python async programming guide", "source": "reddit_python", "engagement": 20, "url": "https://reddit.com/python-async", "description": ""},
    ]
    tagged = [dict(it, matched_tier="tier1") for it in items]
    result_items, _ = detect_clusters(tagged)
    for it in result_items:
        assert it["cross_source_boost"] == 1.0


# ===========================================================================
# normalize_engagement
# ===========================================================================


def test_normalize_engagement_rank_within_source(sample_items_single_source):
    """5 reddit items with engagement [10,20,30,40,50] → normalized values are monotonically increasing in [0,1]."""
    result = normalize_engagement(sample_items_single_source)
    # Sort by original engagement to check monotonicity
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
        # High views, low engagement → should rank high
        {"title": "Popular video", "source": "youtube", "engagement": 10, "views": 100000, "url": "u1", "description": ""},
        {"title": "Unpopular video A", "source": "youtube", "engagement": 500, "views": 100, "url": "u2", "description": ""},
        {"title": "Unpopular video B", "source": "youtube", "engagement": 600, "views": 200, "url": "u3", "description": ""},
        {"title": "Unpopular video C", "source": "youtube", "engagement": 700, "views": 300, "url": "u4", "description": ""},
        {"title": "Unpopular video D", "source": "youtube", "engagement": 800, "views": 400, "url": "u5", "description": ""},
    ]
    result = normalize_engagement(items)
    popular = next(it for it in result if it["title"] == "Popular video")
    others = [it for it in result if it["title"] != "Popular video"]
    # Popular video has highest views → highest engagement_normalized
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
# classify_content_type
# ===========================================================================


def _make_classified_item(**kwargs) -> dict:
    """Build a minimal item ready for classify_content_type (needs engagement_normalized, cross_source_count)."""
    base = {
        "title": kwargs.get("title", "Test item"),
        "source": kwargs.get("source", "hacker_news"),
        "engagement": kwargs.get("engagement", 0),
        "url": kwargs.get("url", "https://example.com/test"),
        "description": kwargs.get("description", ""),
        "engagement_normalized": kwargs.get("engagement_normalized", 0.5),
        "cross_source_count": kwargs.get("cross_source_count", 1),
        "cross_source_boost": kwargs.get("cross_source_boost", 1.0),
        "matched_tier": kwargs.get("matched_tier", "tier2"),
    }
    for field in ("created", "published", "views"):
        if field in kwargs:
            base[field] = kwargs[field]
    return base


def test_classify_hot_signal_keyword():
    """Item with 'release' in title is classified as hot regardless of age."""
    item = _make_classified_item(
        title="New model release announcement",
        engagement_normalized=0.1,
        cross_source_count=1,
    )
    result = classify_content_type([item])
    assert result[0]["content_type"] == "hot"


def test_classify_evergreen_signal_keyword():
    """Item with 'tutorial' in title is classified as evergreen."""
    item = _make_classified_item(
        title="Complete tutorial for beginners",
        engagement_normalized=0.1,
        cross_source_count=1,
    )
    result = classify_content_type([item])
    assert result[0]["content_type"] == "evergreen"


def test_classify_recent_high_engagement_hot():
    """Item created 1 hour ago with engagement_normalized=0.9 is classified as hot."""
    now = time.time()
    item = _make_classified_item(
        title="Breaking news item",
        engagement_normalized=0.9,
        cross_source_count=1,
        created=now - 3600,  # 1 hour ago
    )
    result = classify_content_type([item])
    assert result[0]["content_type"] == "hot"


def test_classify_old_moderate_engagement_evergreen():
    """Item created 5 days ago with engagement_normalized=0.6 is classified as evergreen."""
    now = time.time()
    item = _make_classified_item(
        title="In-depth comparison of frameworks",
        engagement_normalized=0.6,
        cross_source_count=1,
        created=now - 5 * 24 * 3600,  # 5 days ago
    )
    result = classify_content_type([item])
    assert result[0]["content_type"] == "evergreen"


def test_classify_no_timestamp_defaults():
    """Item with no created/published field gets hours_since_published=None; not forced to hot with low engagement and no cross-source."""
    item = _make_classified_item(
        title="Some neutral item",
        engagement_normalized=0.2,
        cross_source_count=1,
    )
    result = classify_content_type([item])
    assert result[0]["hours_since_published"] is None
    # Low engagement (0.2 < 0.5) and no cross-source → should be evergreen, not hot
    assert result[0]["content_type"] == "evergreen"


def test_classify_youtube_published_parsed():
    """YouTube item with published='2 days ago' is parsed to ~48 hours."""
    item = _make_classified_item(
        title="YouTube tutorial video",
        source="youtube",
        engagement_normalized=0.5,
        cross_source_count=1,
        published="2 days ago",
    )
    result = classify_content_type([item])
    hours = result[0]["hours_since_published"]
    assert hours is not None
    assert 47 <= hours <= 49, f"Expected ~48 hours, got {hours}"


# ===========================================================================
# compute_final_scores
# ===========================================================================


def _make_scored_item(**kwargs) -> dict:
    """Build a minimal item ready for compute_final_scores."""
    return {
        "title": kwargs.get("title", "Test item"),
        "source": kwargs.get("source", "hacker_news"),
        "engagement": kwargs.get("engagement", 0),
        "url": kwargs.get("url", "https://example.com/test"),
        "description": kwargs.get("description", ""),
        "engagement_normalized": kwargs.get("engagement_normalized", 0.5),
        "cross_source_count": kwargs.get("cross_source_count", 1),
        "cross_source_boost": kwargs.get("cross_source_boost", 1.0),
        "matched_tier": kwargs.get("matched_tier", "tier2"),
        "content_type": kwargs.get("content_type", "hot"),
        "hours_since_published": kwargs.get("hours_since_published", None),
    }


def test_final_score_tier1_floor():
    """tier1 item with engagement_normalized=0.01 still scores >= floor.

    Expected minimum: max(0.01, 0.1) * 1.5 * 1.0 = 0.15
    """
    item = _make_scored_item(
        matched_tier="tier1",
        engagement_normalized=0.01,
        cross_source_boost=1.0,
        content_type="evergreen",  # no recency decay
    )
    result = compute_final_scores([item])
    assert result[0]["final_score"] >= 0.15


def test_final_score_recency_decay_hot_only():
    """Hot item is decayed by age; evergreen item with same score inputs is not."""
    hot_item = _make_scored_item(
        matched_tier="tier2",
        engagement_normalized=0.5,
        cross_source_boost=1.0,
        content_type="hot",
        hours_since_published=36.0,  # halfway through decay window
    )
    evergreen_item = _make_scored_item(
        matched_tier="tier2",
        engagement_normalized=0.5,
        cross_source_boost=1.0,
        content_type="evergreen",
        hours_since_published=36.0,
    )
    hot_result = compute_final_scores([hot_item])[0]
    ever_result = compute_final_scores([evergreen_item])[0]
    # Hot item should be decayed → lower score
    assert hot_result["final_score"] < ever_result["final_score"]


def test_final_score_cross_source_multiplier():
    """Cluster with 3 sources (boost=2.5) scores higher than singleton (boost=1.0) given same other inputs."""
    singleton = _make_scored_item(
        matched_tier="tier3",
        engagement_normalized=0.5,
        cross_source_boost=1.0,
        content_type="evergreen",
    )
    clustered = _make_scored_item(
        matched_tier="tier3",
        engagement_normalized=0.5,
        cross_source_boost=2.5,
        content_type="evergreen",
    )
    single_result = compute_final_scores([singleton])[0]
    cluster_result = compute_final_scores([clustered])[0]
    assert cluster_result["final_score"] == pytest.approx(single_result["final_score"] * 2.5, rel=1e-3)


# ===========================================================================
# run_pipeline integration
# ===========================================================================


def _synthetic_items_8() -> list[dict]:
    """8 synthetic items for integration tests."""
    now = time.time()
    return [
        # tier1 items
        {"title": "Claude 3 new release today", "source": "hacker_news", "engagement": 300, "url": "https://hn.example.com/claude3", "description": "", "created": now - 1800},
        {"title": "Anthropic MCP announcement", "source": "reddit_localllama", "engagement": 200, "url": "https://reddit.com/mcp", "description": "", "created": now - 3600},
        # tier2 items — must meet per-source threshold
        {"title": "Cursor IDE new features", "source": "reddit_programming", "engagement": 100, "url": "https://reddit.com/cursor", "description": "", "created": now - 7200},
        {"title": "OpenAI GPT new release", "source": "hacker_news", "engagement": 50, "url": "https://hn.example.com/openai", "description": "", "created": now - 900},
        # tier3 items with cross-source
        {"title": "LLM benchmark comparison results", "source": "github_trending", "engagement": 400, "url": "https://github.com/llm-bench", "description": "", "created": now - 2700},
        {"title": "LLM benchmark comparison results", "source": "hacker_news", "engagement": 150, "url": "https://github.com/llm-bench", "description": "", "created": now - 5400},
        # additional tier1
        {"title": "Claude code assistant walkthrough", "source": "youtube", "engagement": 50, "views": 8000, "url": "https://youtube.com/claude-code", "description": "", "published": "3 hours ago"},
        {"title": "Model context protocol tutorial", "source": "geeknews", "engagement": 5, "url": "https://geeknews.example.com/mcp-tutorial", "description": "", "created": now - 1200},
    ]


def test_run_pipeline_end_to_end():
    """run_pipeline returns dict with hot/evergreen/all_scored/clusters keys; top items have final_score."""
    items = _synthetic_items_8()
    result = run_pipeline(items)
    assert set(result.keys()) == {"hot", "evergreen", "all_scored", "clusters"}
    assert isinstance(result["hot"], list)
    assert isinstance(result["evergreen"], list)
    assert isinstance(result["all_scored"], list)
    assert isinstance(result["clusters"], list)
    # All scored items must have final_score
    for it in result["all_scored"]:
        assert "final_score" in it


def test_run_pipeline_tier1_reserved_slot():
    """tier1 item with engagement=0 still appears in hot output even when 4 tier3 items score higher."""
    now = time.time()
    # 1 tier1 item with zero engagement
    tier1 = {"title": "Claude API major update", "source": "hacker_news", "engagement": 0, "url": "https://hn.example.com/claude-api", "description": ""}
    # 4 tier3 items from different sources (cross-source so they pass tag_tiers)
    shared_url = "https://example.com/llm-story"
    tier3_items = [
        {"title": "LLM performance benchmark test", "source": "hacker_news", "engagement": 5000, "url": shared_url, "description": "", "created": now - 100},
        {"title": "LLM performance benchmark test", "source": "reddit_localllama", "engagement": 4000, "url": shared_url, "description": "", "created": now - 200},
        {"title": "LLM performance benchmark test", "source": "github_trending", "engagement": 3000, "url": shared_url, "description": "", "created": now - 300},
        {"title": "LLM performance benchmark test", "source": "youtube", "engagement": 2000, "views": 50000, "url": shared_url, "description": "", "published": "1 hour ago"},
    ]
    result = run_pipeline([tier1] + tier3_items, config={"hot_count": 3})
    hot_tiers = [it.get("matched_tier") for it in result["hot"]]
    assert "tier1" in hot_tiers, f"Expected tier1 in hot output, got tiers: {hot_tiers}"


def test_run_pipeline_respects_hot_count():
    """hot_count=2 returns at most 2 hot items."""
    items = _synthetic_items_8()
    result = run_pipeline(items, config={"hot_count": 2})
    assert len(result["hot"]) <= 2


def test_run_pipeline_empty_input():
    """Empty list returns the expected empty-dict structure without crash."""
    result = run_pipeline([])
    assert result == {"hot": [], "evergreen": [], "all_scored": [], "clusters": []}


# ===========================================================================
# adapt_for_filter_seen
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
        "matched_tier": kwargs.get("matched_tier", "tier2"),
        "cross_source_count": kwargs.get("cross_source_count", 1),
    }


def test_adapt_shape():
    """Each adapted topic has keys: topic, score, reasons, references; each reference has title/url/source/engagement."""
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
    """score field is int in [0, 100]."""
    # final_score=6.0 → score=100 (max); final_score=0 → score=0
    items = [
        _make_adapted_item(final_score=6.0),
        _make_adapted_item(final_score=0.0),
        _make_adapted_item(final_score=3.0),
    ]
    result = adapt_for_filter_seen(items)
    for topic in result:
        assert isinstance(topic["score"], int)
        assert 0 <= topic["score"] <= 100
