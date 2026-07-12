"""US-006: --enrich 플래그 동작 테스트.

--enrich는 rich(비-markdown) 모드에서만 동작한다: 정상 출력 뒤에 파싱 가능한
"=== ENRICH CANDIDATES ===" 블록을 stdout에 추가 출력해, Claude Code 에이전트가
insane-search 스킬로 URL 전문을 수집하고 요약을 보강할 수 있게 한다.

markdown 모드에서는 플래그가 no-op이어야 한다 (CI는 절대 이 플래그를 넘기지
않지만, 혹시 넘기더라도 출력이 바이트 단위로 동일해야 한다).

tests/test_snapshots.py의 _patch_cli_sources 시드(no-network fetchers, history
스텁, fill_missing_descriptions no-op)를 그대로 재사용한다.
"""

from __future__ import annotations

import io
import sys

import main
from rich.console import Console
from tests.test_snapshots import (
    _FakeStdout,
    _fake_fetcher_agents,
    _fake_fetcher_claude_code,
    _patch_cli_sources,
)


def _run_rich_cli(monkeypatch, extra_argv: list[str]) -> str:
    """main.cli()를 rich(비-markdown) 모드로 구동하고, plain print()로 나가는
    stdout(--enrich 블록 포함)과 rich Console 출력을 모두 capsys 없이 하나의
    텍스트로 합쳐 반환한다 (record Console.export_text() + 실제 stdout 캡처는
    호출부에서 capsys로 처리)."""
    fetchers = {"A": _fake_fetcher_claude_code, "B": _fake_fetcher_agents}
    _patch_cli_sources(monkeypatch, fetchers)
    monkeypatch.setattr(sys, "argv", ["main.py", "--mode", "sector", *extra_argv])

    record_console = Console(record=True, width=100, file=io.StringIO(), force_terminal=False)
    record_console.input = lambda *a, **kw: (_ for _ in ()).throw(EOFError())
    monkeypatch.setattr(main, "console", record_console)

    main.cli()
    return record_console.export_text()


def test_rich_with_enrich_prints_block(monkeypatch, capsys):
    """rich + --enrich: stdout에 ENRICH CANDIDATES 블록이 표시된 두 아이템과
    함께 출력된다 (제목/URL/섹터/설명 포함)."""
    _run_rich_cli(monkeypatch, ["--enrich"])
    captured = capsys.readouterr()

    assert "=== ENRICH CANDIDATES ===" in captured.out
    assert "=== END ENRICH CANDIDATES ===" in captured.out
    assert "Claude Code subagent tips for teams" in captured.out
    assert "https://hn.example.com/claude-code-subagents" in captured.out
    assert "sector=claude_code" in captured.out
    assert "LangGraph powered agent workflow release" in captured.out
    assert "https://github.com/example/langgraph-release" in captured.out
    assert "sector=agents" in captured.out
    # description은 fixture에서 빈 문자열 -> EMPTY로 표시
    assert "desc=EMPTY" in captured.out


def test_rich_without_enrich_no_block(monkeypatch, capsys):
    """rich (플래그 없음): ENRICH 블록이 전혀 출력되지 않는다."""
    _run_rich_cli(monkeypatch, [])
    captured = capsys.readouterr()

    assert "ENRICH CANDIDATES" not in captured.out


def test_markdown_with_enrich_is_noop(monkeypatch):
    """markdown + --enrich: 플래그가 없을 때와 바이트 단위로 동일한 출력."""
    fetchers = {"A": _fake_fetcher_claude_code, "B": _fake_fetcher_agents}

    _patch_cli_sources(monkeypatch, fetchers)
    monkeypatch.setattr(sys, "argv", ["main.py", "--mode", "sector", "--format", "markdown"])
    stdout_without = _FakeStdout()
    monkeypatch.setattr(sys, "stdout", stdout_without)
    main.cli()
    output_without = stdout_without.getvalue()

    _patch_cli_sources(monkeypatch, fetchers)
    monkeypatch.setattr(
        sys, "argv", ["main.py", "--mode", "sector", "--format", "markdown", "--enrich"]
    )
    stdout_with = _FakeStdout()
    monkeypatch.setattr(sys, "stdout", stdout_with)
    main.cli()
    output_with = stdout_with.getvalue()

    assert "ENRICH CANDIDATES" not in output_with
    assert output_with == output_without
