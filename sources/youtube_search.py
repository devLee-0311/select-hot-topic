"""YouTube RSS 피드로 Claude 관련 최신 영상 검색 (API 키 불필요)."""

import requests
from bs4 import BeautifulSoup

SEARCH_URL = "https://www.youtube.com/results"
QUERIES = ["claude code", "anthropic claude code", "claude code tutorial"]
TIMEOUT = 10


def _search_youtube(query: str) -> list[dict]:
    """YouTube 검색 결과 페이지를 파싱하여 영상 목록 반환."""
    try:
        resp = requests.get(
            SEARCH_URL,
            params={"search_query": query, "sp": "CAISBAgBEAE%3D"},  # 최근 1주일, 관련성순
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Accept-Language": "en-US,en;q=0.9",
            },
            timeout=TIMEOUT,
        )
        resp.raise_for_status()
    except requests.RequestException as e:
        print(f"  [!] YouTube 검색 실패 ({query}): {e}")
        return []

    results = []
    # YouTube 검색 결과는 JSON이 HTML 안에 포함됨
    import json
    import re

    # ytInitialData에서 영상 데이터 추출
    match = re.search(r"var ytInitialData\s*=\s*({.*?});\s*</script>", resp.text)
    if not match:
        # 대안 패턴
        match = re.search(r"ytInitialData\s*=\s*({.*?});\s*", resp.text)
    if not match:
        return []

    try:
        data = json.loads(match.group(1))
    except json.JSONDecodeError:
        return []

    # 영상 렌더러 탐색
    try:
        contents = (
            data["contents"]["twoColumnSearchResultsRenderer"]
            ["primaryContents"]["sectionListRenderer"]["contents"]
        )
    except (KeyError, TypeError):
        return []

    for section in contents:
        items = section.get("itemSectionRenderer", {}).get("contents", [])
        for item in items:
            renderer = item.get("videoRenderer")
            if not renderer:
                continue

            video_id = renderer.get("videoId", "")
            title_runs = renderer.get("title", {}).get("runs", [])
            title = "".join(r.get("text", "") for r in title_runs)

            # 조회수 파싱
            view_text = renderer.get("viewCountText", {}).get("simpleText", "0")
            views = _parse_view_count(view_text)

            # 게시일
            published = renderer.get("publishedTimeText", {}).get("simpleText", "")

            if video_id and title:
                results.append({
                    "source": "youtube",
                    "title": title,
                    "url": f"https://www.youtube.com/watch?v={video_id}",
                    "description": title,
                    "views": views,
                    "published": published,
                    "engagement": views // 100,  # 조회수를 engagement로 변환 (스케일 조정)
                })

    return results


def _parse_view_count(text: str) -> int:
    """조회수 텍스트를 숫자로 변환. 예: '1,234 views' -> 1234"""
    import re
    digits = re.sub(r"[^\d]", "", text)
    return int(digits) if digits else 0


def fetch_youtube_search() -> list[dict]:
    """YouTube에서 Claude 관련 최신 영상 검색."""
    results = []
    seen_urls = set()

    for query in QUERIES:
        for item in _search_youtube(query):
            if item["url"] not in seen_urls:
                seen_urls.add(item["url"])
                results.append(item)

    # engagement 높은 순, 상위 15개
    results.sort(key=lambda x: x["engagement"], reverse=True)
    return results[:15]
