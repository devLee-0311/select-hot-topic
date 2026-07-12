"""US-004: degradation observability + quiet-day heartbeat (markdown/CI output path).

Drives main.cli() end-to-end (no network) via the same monkeypatch seams as
tests/test_snapshots.py: modes.SECTOR_CONFIG.fetchers + main.get_used_urls.
Uses capsys with SEPARATE assertions on captured.out (Telegram payload, must
never contain ::warning:: lines) vs captured.err (GitHub Actions annotations,
must never contain the stdout footer/heartbeat text).
"""

from __future__ import annotations

import sys

import pytest

import history as history_mod
import main
import net
from tests.test_snapshots import (
    _fake_fetcher_agents,
    _fake_fetcher_claude_code,
    _golden,
    _patch_cli_sources,
)


@pytest.fixture(autouse=True)
def _reset_ledger():
    """main.cli() also calls net.reset() at its own start, but tests that
    inject events directly (without going through cli()) need isolation too."""
    net.reset()
    yield
    net.reset()


def _run_cli_markdown(monkeypatch, fetchers, *, auto_save: bool = False) -> None:
    _patch_cli_sources(monkeypatch, fetchers)
    argv = ["main.py", "--mode", "sector", "--format", "markdown"]
    if auto_save:
        argv.append("--auto-save")
    monkeypatch.setattr(sys, "argv", argv)


def _degraded_fetcher_agents():
    """Same items as _fake_fetcher_agents(), but records a source_empty-style
    degradation event as a side effect (mirrors how a real source module
    calls net.record_source_empty() when it comes back empty)."""
    net.record_source_empty("agents_source")
    return _fake_fetcher_agents()


# ---------------------------------------------------------------------------
# 1. Clean run: no degradation events -> byte-identical to existing golden,
#    no ⚠️ footer, no ::warning:: annotations in either stream.
# ---------------------------------------------------------------------------


def test_clean_run_no_degradation_markers(monkeypatch, capsys):
    fetchers = {"A": _fake_fetcher_claude_code, "B": _fake_fetcher_agents}
    _run_cli_markdown(monkeypatch, fetchers)

    main.cli()

    captured = capsys.readouterr()
    assert captured.out == _golden("cli_markdown_sector.txt")
    assert "⚠️ 수집 상태" not in captured.out
    assert "::warning::" not in captured.out
    assert "::warning::" not in captured.err


# ---------------------------------------------------------------------------
# 2. Degraded run with topics present: footer is the LAST @@@SECTOR_BREAK@@@
#    segment in stdout; ::warning:: lines appear in stderr only.
# ---------------------------------------------------------------------------


def test_degraded_run_with_topics_footer_and_warnings(monkeypatch, capsys):
    fetchers = {"A": _fake_fetcher_claude_code, "B": _degraded_fetcher_agents}
    _run_cli_markdown(monkeypatch, fetchers)

    main.cli()

    captured = capsys.readouterr()
    chunks = captured.out.rstrip("\n").split("\n@@@SECTOR_BREAK@@@\n")
    assert chunks[-1] == "⚠️ 수집 상태: agents_source → 빈 결과"
    assert "::warning::" not in captured.out

    assert "::warning::fetch degraded: agents_source → source_empty" in captured.err
    assert "⚠️ 수집 상태" not in captured.err


# ---------------------------------------------------------------------------
# 3. Zero topics + degradation: stdout gets the footer (non-empty!), stderr
#    gets the ::warning:: line.
# ---------------------------------------------------------------------------


_BOTH_FETCHER_URLS = {
    "https://hn.example.com/claude-code-subagents",
    "https://github.com/example/langgraph-release",
}


def test_zero_topics_with_degradation(monkeypatch, capsys):
    fetchers = {"A": _fake_fetcher_claude_code, "B": _degraded_fetcher_agents}
    _patch_cli_sources(monkeypatch, fetchers)
    # Force filter_seen to drop everything -> wrapped == [] even though
    # all_items is non-empty (distinct from the "collection failed" path).
    monkeypatch.setattr(main, "get_used_urls", lambda: set(_BOTH_FETCHER_URLS))
    monkeypatch.setattr(sys, "argv", ["main.py", "--mode", "sector", "--format", "markdown"])

    main.cli()

    captured = capsys.readouterr()
    assert captured.out.strip() == "⚠️ 수집 상태: agents_source → 빈 결과"
    assert "::warning::fetch degraded: agents_source → source_empty" in captured.err
    assert "새로운 추천 토픽이 없습니다." in captured.err


# ---------------------------------------------------------------------------
# 4. Zero topics + no degradation: quiet-day heartbeat, exactly one message.
# ---------------------------------------------------------------------------


def test_zero_topics_no_degradation_heartbeat(monkeypatch, capsys):
    fetchers = {"A": _fake_fetcher_claude_code, "B": _fake_fetcher_agents}
    _patch_cli_sources(monkeypatch, fetchers)
    monkeypatch.setattr(main, "get_used_urls", lambda: set(_BOTH_FETCHER_URLS))
    monkeypatch.setattr(sys, "argv", ["main.py", "--mode", "sector", "--format", "markdown"])

    main.cli()

    captured = capsys.readouterr()
    assert captured.out.strip() == "이상없음 — 새로운 추천 토픽 없음"
    assert "@@@SECTOR_BREAK@@@" not in captured.out
    assert "::warning::" not in captured.err
    assert "새로운 추천 토픽이 없습니다." in captured.err


# ---------------------------------------------------------------------------
# 5. auto_save guard: heartbeat-only run with --auto-save must not touch history.
# ---------------------------------------------------------------------------


def test_auto_save_skipped_on_heartbeat_only_output(monkeypatch, capsys, tmp_path):
    hist_path = tmp_path / "history.json"
    monkeypatch.setattr(history_mod, "HISTORY_FILE", str(hist_path))

    fetchers = {"A": _fake_fetcher_claude_code, "B": _fake_fetcher_agents}
    _patch_cli_sources(monkeypatch, fetchers)
    monkeypatch.setattr(main, "get_used_urls", lambda: set(_BOTH_FETCHER_URLS))
    monkeypatch.setattr(
        sys, "argv",
        ["main.py", "--mode", "sector", "--format", "markdown", "--auto-save"],
    )

    main.cli()

    captured = capsys.readouterr()
    assert captured.out.strip() == "이상없음 — 새로운 추천 토픽 없음"
    assert not hist_path.exists()
    assert history_mod.load_history() == []
