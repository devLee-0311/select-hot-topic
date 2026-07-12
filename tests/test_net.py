"""net.py의 티어 폴백 로직(requests -> curl_cffi -> jina) 및 degradation 원장 테스트.

네트워크 호출은 전혀 하지 않는다 - requests.get / curl_cffi 모듈을 모두 monkeypatch로 대체.
"""

from __future__ import annotations

import types
from unittest.mock import Mock

import pytest
import requests

import net
from sources import github_trending


@pytest.fixture(autouse=True)
def _reset_ledger():
    """모든 테스트 전후로 degradation 원장을 초기화해 테스트 간 상태 누수를 막는다."""
    net.reset()
    yield
    net.reset()


def _resp(status_code: int = 200, text: str = "ok") -> Mock:
    resp = Mock()
    resp.status_code = status_code
    resp.text = text
    return resp


# ---------------------------------------------------------------------------
# 1. 티어 폴백: requests 403 -> curl_cffi 성공
# ---------------------------------------------------------------------------


def test_falls_through_to_curl_cffi_on_403(monkeypatch):
    monkeypatch.setattr(requests, "get", Mock(return_value=_resp(status_code=403, text="blocked")))
    monkeypatch.setattr(net, "_HAS_CURL_CFFI", True)
    fake_cffi = types.SimpleNamespace(get=Mock(return_value=_resp(status_code=200, text="<html>curl_cffi ok</html>")))
    monkeypatch.setattr(net, "cffi_requests", fake_cffi)

    result = net.fetch_html("https://example.com/blocked")

    assert result.tier == "curl_cffi"
    assert result.degraded is True
    assert result.text == "<html>curl_cffi ok</html>"
    fake_cffi.get.assert_called_once()


# ---------------------------------------------------------------------------
# 2. curl_cffi 미설치 경로: 403 -> curl_cffi 스킵 -> jina 성공
# ---------------------------------------------------------------------------


def test_missing_curl_cffi_falls_through_to_jina(monkeypatch):
    monkeypatch.setattr(net, "_HAS_CURL_CFFI", False)

    call_urls = []

    def fake_get(url, **kwargs):
        call_urls.append(url)
        if "r.jina.ai" in url:
            return _resp(status_code=200, text="jina reader text")
        return _resp(status_code=403, text="blocked")

    monkeypatch.setattr(requests, "get", Mock(side_effect=fake_get))

    result = net.fetch_html("https://example.com/blocked")

    assert result.tier == "jina"
    assert result.degraded is True
    assert result.text == "jina reader text"
    # jina 티어는 r.jina.ai/{url} 형태로 원본 URL을 감싼다
    assert any("r.jina.ai" in u for u in call_urls)


def test_all_tiers_fail(monkeypatch):
    monkeypatch.setattr(net, "_HAS_CURL_CFFI", False)
    monkeypatch.setattr(requests, "get", Mock(return_value=_resp(status_code=403, text="")))

    result = net.fetch_html("https://example.com/blocked")

    assert result == net.FetchResult(text=None, tier=None, degraded=True, url="https://example.com/blocked")


# ---------------------------------------------------------------------------
# 3. 예외가 절대 밖으로 새어나가지 않아야 함
# ---------------------------------------------------------------------------


def test_no_exception_escapes_on_connection_error(monkeypatch):
    monkeypatch.setattr(net, "_HAS_CURL_CFFI", False)
    monkeypatch.setattr(requests, "get", Mock(side_effect=requests.exceptions.ConnectionError("boom")))

    result = net.fetch_html("https://example.com/unreachable")

    assert result.text is None
    assert result.tier is None
    assert result.degraded is True


def test_no_exception_escapes_when_curl_cffi_raises(monkeypatch):
    monkeypatch.setattr(requests, "get", Mock(side_effect=requests.exceptions.ConnectionError("boom")))
    monkeypatch.setattr(net, "_HAS_CURL_CFFI", True)
    fake_cffi = types.SimpleNamespace(get=Mock(side_effect=RuntimeError("curl_cffi internal error")))
    monkeypatch.setattr(net, "cffi_requests", fake_cffi)

    result = net.fetch_html("https://example.com/unreachable")

    assert result.text is None
    assert result.degraded is True


# ---------------------------------------------------------------------------
# 4. 정상 경로 (티어 1 성공) 은 degraded=False
# ---------------------------------------------------------------------------


def test_plain_requests_success_not_degraded(monkeypatch):
    monkeypatch.setattr(requests, "get", Mock(return_value=_resp(status_code=200, text="<html>fine</html>")))

    result = net.fetch_html("https://example.com/ok")

    assert result.tier == "requests"
    assert result.degraded is False
    assert result.text == "<html>fine</html>"
    # 정상 경로는 degradation 원장에 기록되지 않는다
    assert net.get_degradation_report() == []


# ---------------------------------------------------------------------------
# 5. Degradation 원장
# ---------------------------------------------------------------------------


def test_ledger_records_winning_tier_and_source_empty(monkeypatch):
    monkeypatch.setattr(requests, "get", Mock(return_value=_resp(status_code=403, text="blocked")))
    monkeypatch.setattr(net, "_HAS_CURL_CFFI", True)
    fake_cffi = types.SimpleNamespace(get=Mock(return_value=_resp(status_code=200, text="ok")))
    monkeypatch.setattr(net, "cffi_requests", fake_cffi)

    net.fetch_html("https://example.com/a")
    net.record_source_empty("some_source")

    report = net.get_degradation_report()
    assert len(report) == 2
    assert report[0]["label"] == "https://example.com/a"
    assert report[0]["outcome"] == "curl_cffi"
    assert report[1]["label"] == "some_source"
    assert report[1]["outcome"] == "source_empty"


def test_ledger_reset_clears_events():
    net.record_source_empty("some_source")
    assert len(net.get_degradation_report()) == 1

    net.reset()

    assert net.get_degradation_report() == []


# ---------------------------------------------------------------------------
# 6. 통합: github_trending이 net.fetch_html의 curl_cffi 티어 결과를 그대로 소비
# ---------------------------------------------------------------------------

_TRENDING_HTML = """
<html><body>
<article class="Box-row">
  <h2><a href="/anthropics/claude-code">anthropics / claude-code</a></h2>
  <p>Claude Code is Anthropic's agentic coding CLI</p>
  <span class="d-inline-block float-sm-right">42 stars today</span>
</article>
</body></html>
"""


def test_github_trending_accepts_curl_cffi_tier_result(monkeypatch):
    """403 -> curl_cffi 폴백으로 얻은 결과라도 파서가 정상적으로 아이템을 반환해야 한다."""
    fake_result = net.FetchResult(
        text=_TRENDING_HTML,
        tier="curl_cffi",
        degraded=True,
        url="https://github.com/trending?since=daily",
    )
    monkeypatch.setattr(net, "fetch_html", Mock(return_value=fake_result))

    items = github_trending.fetch_github_trending()

    assert len(items) == 1
    assert items[0]["title"] == "anthropics/claude-code"
    assert items[0]["source"] == "github_trending"
