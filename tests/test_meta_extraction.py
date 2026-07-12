"""US-005: net.extract_meta_description() 및 main.fill_missing_descriptions() 테스트.

네트워크 호출은 전혀 하지 않는다 - net.fetch_html을 모두 monkeypatch로 대체.
"""

from __future__ import annotations

import time

import net
from main import fill_missing_descriptions


def _fetch_result(text: str | None, tier: str | None = "requests", degraded: bool = False, url: str = "https://example.com") -> net.FetchResult:
    return net.FetchResult(text=text, tier=tier, degraded=degraded, url=url)


# ---------------------------------------------------------------------------
# net.extract_meta_description
# ---------------------------------------------------------------------------


def test_extract_meta_description_og_present(monkeypatch):
    html = '<html><head><meta property="og:description" content="An og description"></head></html>'
    monkeypatch.setattr(net, "fetch_html", lambda url, **kw: _fetch_result(html))

    result = net.extract_meta_description("https://example.com/a")

    assert result == "An og description"


def test_extract_meta_description_falls_back_to_json_ld(monkeypatch):
    html = (
        '<html><head>'
        '<script type="application/ld+json">{"@type": "Article", "description": "JSON-LD description here"}</script>'
        '</head></html>'
    )
    monkeypatch.setattr(net, "fetch_html", lambda url, **kw: _fetch_result(html))

    result = net.extract_meta_description("https://example.com/b")

    assert result == "JSON-LD description here"


def test_extract_meta_description_nothing_present(monkeypatch):
    html = "<html><head><title>No metadata here</title></head></html>"
    monkeypatch.setattr(net, "fetch_html", lambda url, **kw: _fetch_result(html))

    result = net.extract_meta_description("https://example.com/c")

    assert result is None


def test_extract_meta_description_fetch_fails(monkeypatch):
    monkeypatch.setattr(
        net, "fetch_html", lambda url, **kw: net.FetchResult(text=None, tier=None, degraded=True, url=url)
    )

    result = net.extract_meta_description("https://example.com/d")

    assert result is None


def test_extract_meta_description_jina_tier_uses_first_substantial_line(monkeypatch):
    text = "\n\n  Short  \nThis is a substantial first line of jina reader text\nSecond line\n"
    monkeypatch.setattr(net, "fetch_html", lambda url, **kw: _fetch_result(text, tier="jina", degraded=True))

    result = net.extract_meta_description("https://example.com/e")

    assert result == "This is a substantial first line of jina reader text"


def test_extract_meta_description_jina_tier_no_substantial_line(monkeypatch):
    text = "hi\nyo\n"
    monkeypatch.setattr(net, "fetch_html", lambda url, **kw: _fetch_result(text, tier="jina", degraded=True))

    result = net.extract_meta_description("https://example.com/f")

    assert result is None


def test_extract_meta_description_twitter_used_when_og_missing(monkeypatch):
    html = '<html><head><meta name="twitter:description" content="Twitter description"></head></html>'
    monkeypatch.setattr(net, "fetch_html", lambda url, **kw: _fetch_result(html))

    result = net.extract_meta_description("https://example.com/g")

    assert result == "Twitter description"


def test_extract_meta_description_name_description_last_resort(monkeypatch):
    html = '<html><head><meta name="description" content="Plain meta description"></head></html>'
    monkeypatch.setattr(net, "fetch_html", lambda url, **kw: _fetch_result(html))

    result = net.extract_meta_description("https://example.com/h")

    assert result == "Plain meta description"


# ---------------------------------------------------------------------------
# main.fill_missing_descriptions
# ---------------------------------------------------------------------------


def _display_item(title: str, url: str, description: str = "") -> dict:
    return {"title": title, "url": url, "description": description}


def test_fill_missing_descriptions_fills_empty_description(monkeypatch):
    monkeypatch.setattr(net, "extract_meta_description", lambda url, **kw: "Fetched description")
    item = _display_item("Some title", "https://example.com/1", description="")
    display_sectors = {"trending": [item]}

    fill_missing_descriptions(display_sectors)

    assert item["description"] == "Fetched description"


def test_fill_missing_descriptions_fills_description_equal_to_title(monkeypatch):
    monkeypatch.setattr(net, "extract_meta_description", lambda url, **kw: "Fetched description")
    item = _display_item("Same as title", "https://example.com/2", description="Same as title")
    display_sectors = {"trending": [item]}

    fill_missing_descriptions(display_sectors)

    assert item["description"] == "Fetched description"


def test_fill_missing_descriptions_never_overwrites_real_description(monkeypatch):
    monkeypatch.setattr(net, "extract_meta_description", lambda url, **kw: "Should never be used")
    item = _display_item("Some title", "https://example.com/3", description="A real, pre-existing description")
    display_sectors = {"trending": [item]}

    fill_missing_descriptions(display_sectors)

    assert item["description"] == "A real, pre-existing description"


def test_fill_missing_descriptions_none_result_leaves_item_unchanged(monkeypatch):
    monkeypatch.setattr(net, "extract_meta_description", lambda url, **kw: None)
    item = _display_item("Some title", "https://example.com/4", description="")
    display_sectors = {"trending": [item]}

    fill_missing_descriptions(display_sectors)

    assert item["description"] == ""


def test_fill_missing_descriptions_exception_in_one_item_does_not_affect_others(monkeypatch):
    def _maybe_raise(url, **kw):
        if url == "https://example.com/bad":
            raise RuntimeError("boom")
        return f"desc for {url}"

    monkeypatch.setattr(net, "extract_meta_description", _maybe_raise)
    bad_item = _display_item("Bad title", "https://example.com/bad", description="")
    good_item = _display_item("Good title", "https://example.com/good", description="")
    display_sectors = {"trending": [bad_item, good_item]}

    fill_missing_descriptions(display_sectors)

    assert bad_item["description"] == ""
    assert good_item["description"] == "desc for https://example.com/good"


def test_fill_missing_descriptions_timeout_guard_does_not_hang_batch(monkeypatch):
    """A slow extraction (beyond the per-item timeout) must not block the batch
    from returning within a bounded time."""

    def _slow_or_fast(url, **kw):
        if url == "https://example.com/slow":
            time.sleep(2)
            return "too late"
        return "fast description"

    monkeypatch.setattr(net, "extract_meta_description", _slow_or_fast)
    slow_item = _display_item("Slow title", "https://example.com/slow", description="")
    fast_item = _display_item("Fast title", "https://example.com/fast", description="")
    display_sectors = {"trending": [slow_item, fast_item]}

    start = time.monotonic()
    fill_missing_descriptions(display_sectors, timeout=0.2)
    elapsed = time.monotonic() - start

    # Bounded: must return well before the slow item's 2s sleep completes.
    assert elapsed < 1.5
    assert slow_item["description"] == ""
    assert fast_item["description"] == "fast description"
