"""Anthropic 공식 블로그 + 뉴스 수집."""

import re
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

from bs4 import BeautifulSoup

import net

BLOG_URL = "https://claude.com/blog"
NEWS_URL = "https://www.anthropic.com/news"
TIMEOUT = 10
# 페이지당 fetch 개수. anthropic_official 섹터는 종류별 3개(per_kind_limit)만 노출하므로
# 10개씩 가져올 필요가 없다. dedup/파싱 실패 여유분을 둔 5개만 가져온다 (이전 10 → 5).
FETCH_PER_PAGE = 5

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9",
}

# 제목에서 날짜·카테고리 prefix 캡처 (예: "Apr 6, 2026AnnouncementsActual Title")
DATE_PREFIX_RE = re.compile(
    r"^((?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d{1,2},\s+\d{4})"
)

CATEGORY_LABELS = {"Announcements", "Policy", "Research", "Product", "Safety", "Engineering"}


def _parse_title(raw: str) -> tuple[str, datetime | None]:
    """raw 제목에서 (cleaned_title, published_at) 분리. 날짜 prefix가 없으면 (raw, None)."""
    m = DATE_PREFIX_RE.match(raw)
    if not m:
        return raw, None
    try:
        published = datetime.strptime(m.group(1), "%b %d, %Y")
    except ValueError:
        published = None
    rest = raw[m.end():].strip()
    for label in CATEGORY_LABELS:
        if rest.startswith(label):
            rest = rest[len(label):].strip()
            break
    return (rest or raw), published


def _fetch_meta_description(url: str) -> str:
    """개별 글 페이지에서 og:description 추출."""
    result = net.fetch_html(url, headers=HEADERS, timeout=TIMEOUT)
    if result.text is None:
        return ""
    try:
        soup = BeautifulSoup(result.text, "html.parser")
        og = soup.find("meta", attrs={"property": "og:description"})
        if og:
            return og.get("content", "").strip()
        meta = soup.find("meta", attrs={"name": "description"})
        if meta:
            return meta.get("content", "").strip()
    except Exception:
        pass
    return ""


def _enrich_descriptions(items: list[dict]) -> list[dict]:
    """각 글의 og:description을 병렬로 가져와서 description 필드 채움."""
    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = {executor.submit(_fetch_meta_description, item["url"]): i for i, item in enumerate(items)}
        for future in as_completed(futures):
            idx = futures[future]
            desc = future.result()
            if desc:
                items[idx]["description"] = desc
    return items


def _fetch_page(url: str, path_prefix: str) -> list[dict]:
    """단일 페이지에서 글 목록 수집. 날짜 prefix가 있으면 published_at 필드에 저장."""
    result = net.fetch_html(url, headers=HEADERS, timeout=TIMEOUT)
    if result.text is None:
        print(f"  [!] Anthropic 페이지 요청 실패 ({url}): 모든 fetch 티어 실패", file=sys.stderr)
        return []

    soup = BeautifulSoup(result.text, "html.parser")
    results = []
    seen = set()

    for a_tag in soup.find_all("a", href=True):
        href = a_tag["href"]
        if path_prefix not in href or href.rstrip("/") == path_prefix.rstrip("/"):
            continue
        if "/category/" in href or href in seen:
            continue

        heading = a_tag.find(["h2", "h3", "h4"])
        raw_title = heading.get_text(strip=True) if heading else a_tag.get_text(strip=True)

        if not raw_title or len(raw_title) < 10 or raw_title == "Read more":
            continue

        title, published_at = _parse_title(raw_title)
        if not title or len(title) < 10:
            continue

        seen.add(href)
        full_url = href if href.startswith("http") else f"https://{'claude.com' if 'blog' in path_prefix else 'www.anthropic.com'}{href}"

        results.append({
            "source": "anthropic_releases",
            "title": title,
            "url": full_url,
            "description": title,
            "published_at": published_at,
        })

    return results


def _sort_by_date(items: list[dict]) -> list[dict]:
    """published_at 내림차순 정렬. None은 가장 뒤로."""
    return sorted(
        items,
        key=lambda it: it.get("published_at") or datetime.min,
        reverse=True,
    )


def fetch_anthropic_releases() -> list[dict]:
    """Anthropic 공식 블로그 + 뉴스에서 최신 글 수집 (날짜 내림차순)."""
    blog_items = _sort_by_date(_fetch_page(BLOG_URL, "/blog/"))[:FETCH_PER_PAGE]
    news_items = _sort_by_date(_fetch_page(NEWS_URL, "/news/"))[:FETCH_PER_PAGE]

    combined = blog_items + news_items
    if not combined:
        net.record_source_empty("anthropic_releases")
    return _enrich_descriptions(combined)
