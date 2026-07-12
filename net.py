"""티어 방식 회복성 있는 HTTP fetch 레이어.

requests(기본) -> curl_cffi(TLS impersonation, 선택적 의존성) -> Jina Reader
순으로 폴백하며, 모든 티어가 실패해도 예외를 던지지 않고
FetchResult(text=None, ...)를 반환한다. 각 소스는 raw requests.get() 대신
fetch_html()을 호출해 403/WAF 차단에 회복력을 가진다.
"""

import json
import threading
import time
from dataclasses import dataclass

import requests
from bs4 import BeautifulSoup

try:
    from curl_cffi import requests as cffi_requests
    _HAS_CURL_CFFI = True
except ImportError:  # curl_cffi는 선택적 의존성 (pyproject.toml의 [project.optional-dependencies].fetch)
    cffi_requests = None
    _HAS_CURL_CFFI = False

# 소스들이 이미 쓰고 있던 브라우저 UA 패턴을 기본값으로 사용
DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}

JINA_READER_URL = "https://r.jina.ai/{url}"


@dataclass
class FetchResult:
    """fetch_html()의 결과. text=None이면 모든 티어가 실패한 것."""

    text: str | None          # HTML/text (성공 시), 전체 실패 시 None
    tier: str | None          # "requests" | "curl_cffi" | "jina" | None
    degraded: bool            # plain requests 이상의 티어가 필요했거나 전체 실패면 True
    url: str


# 성능 저하(degradation) 이력. 관측 가능성(observability) 출력은 main.py의
# get_degradation_report() 호출부(markdown/CI 모드)에서 이 데이터를 소비한다. 여기서는 기록만 담당.
_LEDGER_LOCK = threading.Lock()
DEGRADATION_EVENTS: list[dict] = []


def record_source_empty(source_name: str) -> None:
    """소스가 파싱된 아이템 0개로 끝났을 때 기록."""
    with _LEDGER_LOCK:
        DEGRADATION_EVENTS.append({
            "label": source_name,
            "outcome": "source_empty",
            "ts": time.time(),
        })


def _record_degradation(label: str, outcome: str) -> None:
    with _LEDGER_LOCK:
        DEGRADATION_EVENTS.append({
            "label": label,
            "outcome": outcome,
            "ts": time.time(),
        })


def get_degradation_report() -> list[dict]:
    """지금까지 기록된 degradation 이벤트의 복사본을 반환."""
    with _LEDGER_LOCK:
        return list(DEGRADATION_EVENTS)


def reset() -> None:
    """테스트 등에서 이력을 초기화."""
    with _LEDGER_LOCK:
        DEGRADATION_EVENTS.clear()


def _try_requests(url: str, headers: dict, timeout: int) -> str | None:
    try:
        resp = requests.get(url, headers=headers, timeout=timeout)
    except requests.RequestException:
        return None
    if 200 <= resp.status_code < 300 and resp.text:
        return resp.text
    return None


def _try_curl_cffi(url: str, timeout: int) -> str | None:
    if not _HAS_CURL_CFFI:
        return None
    try:
        resp = cffi_requests.get(url, impersonate="chrome", timeout=timeout)
    except Exception:  # curl_cffi 자체 예외 계층은 requests와 다름 - 폭넓게 방어
        return None
    if resp.status_code < 400 and resp.text:
        return resp.text
    return None


def _try_jina(url: str, timeout: int) -> str | None:
    # jina Reader가 자체적으로 원본 URL을 fetch하므로 호출자가 넘긴 headers는 의도적으로 사용하지 않는다.
    try:
        resp = requests.get(JINA_READER_URL.format(url=url), timeout=timeout)
    except requests.RequestException:
        return None
    if 200 <= resp.status_code < 300 and resp.text:
        return resp.text
    return None


def fetch_html(url: str, *, headers: dict | None = None, timeout: int = 10) -> FetchResult:
    """티어 순서대로 fetch 시도: requests -> curl_cffi -> Jina Reader.

    Jina Reader 티어(https://r.jina.ai/)는 HTML이 아니라 정제된 텍스트/마크다운을
    반환하므로, HTML 구조(select/select_one 등)에 의존하는 파서는 이 티어에서
    빈 결과를 얻을 가능성이 높다. 그래도 meta description 같은 텍스트 기반
    추출은 살아남을 수 있어 최후의 수단으로 남겨둔다.

    예외는 절대 밖으로 새어나가지 않는다 - 모든 티어 실패 시
    FetchResult(text=None, tier=None, degraded=True, url=url)을 반환한다.
    """
    active_headers = headers or DEFAULT_HEADERS

    text = _try_requests(url, active_headers, timeout)
    if text:
        # 정상 경로(순수 requests 성공)는 degradation이 아니므로 원장에 기록하지 않는다.
        return FetchResult(text=text, tier="requests", degraded=False, url=url)

    text = _try_curl_cffi(url, timeout)
    if text:
        _record_degradation(url, "curl_cffi")
        return FetchResult(text=text, tier="curl_cffi", degraded=True, url=url)

    text = _try_jina(url, timeout)
    if text:
        _record_degradation(url, "jina")
        return FetchResult(text=text, tier="jina", degraded=True, url=url)

    _record_degradation(url, "all_failed")
    return FetchResult(text=None, tier=None, degraded=True, url=url)


def _extract_from_jina_text(text: str) -> str | None:
    """jina 티어(HTML이 아닌 plain text/markdown)에서 대략적인 설명을 뽑는다.

    첫 substantial(20자 이상) 텍스트 줄을 그대로 반환. 없으면 None.
    """
    for line in text.splitlines():
        line = line.strip()
        if len(line) >= 20:
            return line
    return None


def _extract_from_html(html: str) -> str | None:
    """og:description -> twitter:description -> JSON-LD description ->
    <meta name="description"> 순으로 첫 non-empty 값을 반환. 없으면 None.
    """
    soup = BeautifulSoup(html, "html.parser")

    og = soup.find("meta", attrs={"property": "og:description"})
    if og:
        content = (og.get("content") or "").strip()
        if content:
            return content

    twitter = soup.find("meta", attrs={"name": "twitter:description"})
    if twitter:
        content = (twitter.get("content") or "").strip()
        if content:
            return content

    for script in soup.find_all("script", attrs={"type": "application/ld+json"}):
        try:
            data = json.loads(script.string or "")
        except (ValueError, TypeError):
            continue
        candidates = data if isinstance(data, list) else [data]
        for candidate in candidates:
            if isinstance(candidate, dict):
                desc = candidate.get("description")
                if isinstance(desc, str) and desc.strip():
                    return desc.strip()

    meta = soup.find("meta", attrs={"name": "description"})
    if meta:
        content = (meta.get("content") or "").strip()
        if content:
            return content

    return None


def extract_meta_description(url: str, *, timeout: int = 8) -> str | None:
    """URL에서 헤드리스로 메타 설명을 추출한다 (제목만 있는 아이템 보강용).

    fetch_html()의 티어를 그대로 활용한다. jina 티어(plain text)는 HTML 파서로
    풀 수 없으므로 첫 substantial 텍스트 줄을 대략적인 설명으로 사용한다.
    실패(fetch 실패, 파싱 예외, 설명 없음) 시 항상 None을 반환 - 예외는 절대
    밖으로 새어나가지 않는다.
    """
    try:
        result = fetch_html(url, timeout=timeout)
    except Exception:
        return None

    if result.text is None:
        return None

    try:
        if result.tier == "jina":
            return _extract_from_jina_text(result.text)
        return _extract_from_html(result.text)
    except Exception:
        return None
