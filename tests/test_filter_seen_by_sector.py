"""Unit tests for apply_filter_seen_by_sector() (main.py).

Covers the extracted filter_seen sector round-trip: items seen in history are
dropped, survivors are re-grouped under their original sector, and slot caps
are respected.
"""

from __future__ import annotations

import json
from datetime import datetime

import pytest

import history as history_mod
from main import apply_filter_seen_by_sector
from pipeline import SECTORS


def _pipeline_item(title: str, url: str, sector: str, final_score: float = 3.0) -> dict:
    """Minimal pipeline-output item shape consumed by adapt_for_filter_seen."""
    return {
        "title": title,
        "description": "",
        "url": url,
        "source": "hacker_news",
        "engagement": 100,
        "final_score": final_score,
        "sector": sector,
        "cross_source_count": 1,
        "recency_multiplier": 1.0,
    }


def _pipeline_result(sectors: dict[str, list[dict]]) -> dict:
    all_sectors = {name: [] for name, _ in SECTORS}
    all_sectors.update(sectors)
    return {"sectors": all_sectors, "max_score": 6.0}


@pytest.fixture
def _isolated_history(tmp_path, monkeypatch):
    """Redirect history.json to tmp_path so tests don't touch the real history file."""
    hist_path = tmp_path / "history.json"
    monkeypatch.setattr(history_mod, "HISTORY_FILE", str(hist_path))
    return hist_path


def _seed_history(hist_path, urls: list[str]) -> None:
    entries = [
        {
            "topic": f"Seen {i}",
            "score": 50,
            "reasons": [],
            "references": [url],
            "mode": "sector",
            "saved_at": datetime.now().isoformat(),
        }
        for i, url in enumerate(urls)
    ]
    with open(hist_path, "w", encoding="utf-8") as f:
        json.dump(entries, f)


def test_items_seen_in_history_are_dropped(_isolated_history):
    """An item whose URL is already in history is filtered out of wrapped and display_sectors."""
    seen_url = "https://hn.example.com/already-seen"
    _seed_history(_isolated_history, [seen_url])

    item = _pipeline_item("Already covered topic", seen_url, "claude_code")
    pipeline_result = _pipeline_result({"claude_code": [item]})

    wrapped, display_sectors = apply_filter_seen_by_sector(pipeline_result)

    assert wrapped == []
    assert display_sectors["claude_code"] == []


def test_survivors_regrouped_under_original_sector(_isolated_history):
    """Items not in history survive and are re-grouped under their original sector key."""
    claude_item = _pipeline_item("New Claude Code feature", "https://hn.example.com/new-1", "claude_code")
    agents_item = _pipeline_item("New agent framework", "https://hn.example.com/new-2", "agents")
    pipeline_result = _pipeline_result({
        "claude_code": [claude_item],
        "agents": [agents_item],
    })

    wrapped, display_sectors = apply_filter_seen_by_sector(pipeline_result)

    assert len(wrapped) == 2
    assert [it["url"] for it in display_sectors["claude_code"]] == ["https://hn.example.com/new-1"]
    assert [it["url"] for it in display_sectors["agents"]] == ["https://hn.example.com/new-2"]
    # Untouched sectors stay empty.
    assert display_sectors["local_llm"] == []


def test_slot_caps_respected(_isolated_history):
    """More survivors than a sector's configured count are truncated to the cap."""
    claude_cfg = next(cfg for name, cfg in SECTORS if name == "claude_code")
    limit = claude_cfg.get("count", 5)

    items = [
        _pipeline_item(f"Claude Code item {i}", f"https://hn.example.com/cc-{i}", "claude_code")
        for i in range(limit + 3)
    ]
    pipeline_result = _pipeline_result({"claude_code": items})

    wrapped, display_sectors = apply_filter_seen_by_sector(pipeline_result)

    assert len(wrapped) == limit + 3  # filter_seen itself doesn't cap
    assert len(display_sectors["claude_code"]) == limit


def test_empty_wrapped_yields_all_empty_sectors(_isolated_history):
    """When every item is filtered out, display_sectors has empty lists for all sectors."""
    seen_url = "https://hn.example.com/seen-only"
    _seed_history(_isolated_history, [seen_url])
    item = _pipeline_item("Fully seen topic", seen_url, "local_llm")
    pipeline_result = _pipeline_result({"local_llm": [item]})

    wrapped, display_sectors = apply_filter_seen_by_sector(pipeline_result)

    assert wrapped == []
    assert display_sectors == {name: [] for name, _ in SECTORS}
