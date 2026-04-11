"""Anthropic 공식 블로그 + 뉴스 수집."""

import re
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests
from bs4 import BeautifulSoup

BLOG_URL = "https://claude.com/blog"
NEWS_URL = "https://www.anthropic.com/news"
TIMEOUT = 10
BASE_ENGAGEMENT = 1500  # 공식 소스 기본 가산점

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9",
}

# 제목에서 날짜·카테고리 prefix 제거 (예: "Apr 6, 2026AnnouncementsActual Title")
DATE_CATEGORY_RE = re.compile(
    r"^(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d{1,2},\s+\d{4}"
    r"(?:Announcements|Policy|Research|Product|Safety)?"
)

CATEGORY_LABELS = {"Announcements", "Policy", "Research", "Product", "Safety", "Engineering"}


def _clean_title(raw: str) -> str:
    """날짜·카테고리 prefix를 제거한 제목 반환."""
    title = DATE_CATEGORY_RE.sub("", raw).strip()
    # 남은 카테고리 라벨 제거
    for label in CATEGORY_LABELS:
        if title.startswith(label):
            title = title[len(label):].strip()
    return title


def _fetch_meta_description(url: str) -> str:
    """개별 글 페이지에서 og:description 추출."""
    try:
        resp = requests.get(url, timeout=TIMEOUT, headers=HEADERS)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
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


def _fetch_page(url: str, path_prefix: str, clean_titles: bool = False) -> list[dict]:
    """단일 페이지에서 글 목록 수집."""
    try:
        resp = requests.get(url, timeout=TIMEOUT, headers=HEADERS)
        resp.raise_for_status()
    except requests.RequestException as e:
        print(f"  [!] Anthropic 페이지 요청 실패 ({url}): {e}", file=sys.stderr)
        return []

    soup = BeautifulSoup(resp.text, "html.parser")
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

        title = _clean_title(raw_title) if clean_titles else raw_title
        if not title or len(title) < 10:
            continue

        seen.add(href)
        full_url = href if href.startswith("http") else f"https://{'claude.com' if 'blog' in path_prefix else 'www.anthropic.com'}{href}"

        results.append({
            "source": "anthropic_releases",
            "title": title,
            "url": full_url,
            "description": title,
            "engagement": BASE_ENGAGEMENT,
        })

    return results[:15]


def fetch_anthropic_releases() -> list[dict]:
    """Anthropic 공식 블로그 + 뉴스에서 최신 글 수집."""
    blog_items = _fetch_page(BLOG_URL, "/blog/", clean_titles=False)
    news_items = _fetch_page(NEWS_URL, "/news/", clean_titles=True)

    # 합쳐서 최대 20개, description 병렬 수집
    combined = (blog_items + news_items)[:20]
    return _enrich_descriptions(combined)
