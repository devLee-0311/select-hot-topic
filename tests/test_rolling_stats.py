"""Tests for rolling_stats.py — load/save roundtrip + corrupt/missing fallback."""

from __future__ import annotations

import json
from datetime import datetime, timedelta

from rolling_stats import load_rolling_stats, save_rolling_stats


def test_load_missing_file_returns_empty(tmp_path):
    """Missing file → returns empty list (no crash)."""
    path = tmp_path / "absent.json"
    assert load_rolling_stats(path=str(path)) == []


def test_load_corrupt_file_returns_empty(tmp_path):
    """Corrupt JSON → returns empty list."""
    path = tmp_path / "corrupt.json"
    with open(path, "w", encoding="utf-8") as f:
        f.write("{not valid json")
    assert load_rolling_stats(path=str(path)) == []


def test_load_missing_samples_key_returns_empty(tmp_path):
    """File without 'samples' key → returns empty list."""
    path = tmp_path / "noKey.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"other": 1}, f)
    assert load_rolling_stats(path=str(path)) == []


def test_save_then_load_roundtrip(tmp_path):
    """save_rolling_stats writes a sample; load returns it back."""
    path = tmp_path / "stats.json"
    save_rolling_stats([], 5.5, path=str(path))
    loaded = load_rolling_stats(path=str(path))
    assert len(loaded) == 1
    ts, val = loaded[0]
    assert val == 5.5
    # ISO timestamp should parse
    datetime.fromisoformat(ts.replace("Z", "+00:00"))


def test_save_appends_and_trims_old_samples(tmp_path):
    """Samples older than keep_days are dropped when saving."""
    path = tmp_path / "stats.json"
    old_ts = (datetime.now() - timedelta(days=30)).isoformat()
    fresh_ts = (datetime.now() - timedelta(days=1)).isoformat()
    existing = [(old_ts, 9.9), (fresh_ts, 4.4)]
    save_rolling_stats(existing, 6.6, path=str(path), keep_days=7)

    loaded = load_rolling_stats(path=str(path))
    vals = [v for _, v in loaded]
    assert 9.9 not in vals  # ancient sample trimmed
    assert 4.4 in vals  # recent preserved
    assert 6.6 in vals  # newly appended today_max


def test_save_keeps_multiple_fresh_samples(tmp_path):
    """Multiple saves within keep_days all persist."""
    path = tmp_path / "stats.json"
    save_rolling_stats([], 1.0, path=str(path))
    samples = load_rolling_stats(path=str(path))
    save_rolling_stats(samples, 2.0, path=str(path))
    samples = load_rolling_stats(path=str(path))
    save_rolling_stats(samples, 3.0, path=str(path))
    samples = load_rolling_stats(path=str(path))
    vals = sorted(v for _, v in samples)
    assert vals == [1.0, 2.0, 3.0]


def test_save_atomicity_via_rename(tmp_path):
    """Save writes to a tmp file then renames — target file is always valid on read."""
    path = tmp_path / "stats.json"
    save_rolling_stats([], 7.0, path=str(path))
    # confirm no .tmp leftover in the target dir
    leftovers = [p for p in tmp_path.iterdir() if p.name.startswith(".score_stats_")]
    assert not leftovers, f"temp file leftover: {leftovers}"
