"""Hacker News Algolia API로 Claude/AI 관련 핫글 검색 + Top Stories 수집."""

import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests

SEARCH_URL = "https://hn.algolia.com/api/v1/search"
TOP_STORIES_URL = "https://hacker-news.firebaseio.com/v0/topstories.json"
ITEM_URL = "https://hacker-news.firebaseio.com/v0/item/{}.json"
QUERIES = [
    "claude code", "anthropic claude", "claude AI", "MCP server",
    "LLM", "OpenAI GPT", "AI agent", "AI coding",
    "developer tools", "devtools CLI",
    "duct tape openai", "gpt image", "AI image generation",
]
TOP_STORIES_LIMIT = 60  # 프론트페이지 상위 N개 가져와서 AI 관련만 필터
TIMEOUT = 10


def _fetch_hn_item(item_id: int) -> dict | None:
    """단일 HN 아이템을 Firebase API로 가져온다."""
    try:
        resp = requests.get(ITEM_URL.format(item_id), timeout=TIMEOUT)
        resp.raise_for_status()
        return resp.json()
    except (requests.RequestException, ValueError):
        return None


def _fetch_top_stories() -> list[dict]:
    """HN Top Stories (프론트페이지)에서 AI/개발 관련 글을 필터링하여 반환."""
    try:
        resp = requests.get(TOP_STORIES_URL, timeout=TIMEOUT)
        resp.raise_for_status()
        story_ids = resp.json()[:TOP_STORIES_LIMIT]
    except (requests.RequestException, ValueError) as e:
        print(f"  [!] Hacker News Top Stories 요청 실패: {e}", file=sys.stderr)
        return []

    # 병렬로 아이템 가져오기
    items: list[dict] = []
    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = {executor.submit(_fetch_hn_item, sid): sid for sid in story_ids}
        for future in as_completed(futures):
            item = future.result()
            if item and item.get("type") == "story" and item.get("title"):
                items.append(item)

    results = []
    for item in items:
        obj_id = str(item.get("id", ""))
        points = item.get("score", 0) or 0
        comments = item.get("descendants", 0) or 0

        results.append({
            "source": "hacker_news",
            "title": item.get("title", ""),
            "url": item.get("url") or f"https://news.ycombinator.com/item?id={obj_id}",
            "description": item.get("title", ""),
            "hn_url": f"https://news.ycombinator.com/item?id={obj_id}",
            "points": points,
            "num_comments": comments,
            "engagement": points + comments,
            "created": item.get("time", 0),
        })

    return results


def fetch_hacker_news(queries: list[str] | None = None) -> list[dict]:
    """Hacker News에서 최근 인기글 검색 + Top Stories 프론트페이지 수집."""
    results = []
    seen_ids = set()

    # 1) 키워드 검색 (기존)
    for query in (queries or QUERIES):
        try:
            resp = requests.get(
                SEARCH_URL,
                params={
                    "query": query,
                    "tags": "story",
                    "numericFilters": f"points>5,created_at_i>{int(time.time()) - 7*86400}",
                    "hitsPerPage": 15,
                },
                timeout=TIMEOUT,
            )
            resp.raise_for_status()
            data = resp.json()
        except (requests.RequestException, ValueError) as e:
            print(f"  [!] Hacker News 요청 실패 ({query}): {e}", file=sys.stderr)
            continue

        for hit in data.get("hits", []):
            obj_id = hit.get("objectID", "")
            if obj_id in seen_ids:
                continue
            seen_ids.add(obj_id)

            points = hit.get("points", 0) or 0
            comments = hit.get("num_comments", 0) or 0

            results.append({
                "source": "hacker_news",
                "title": hit.get("title", ""),
                "url": hit.get("url") or f"https://news.ycombinator.com/item?id={obj_id}",
                "description": hit.get("title", ""),
                "hn_url": f"https://news.ycombinator.com/item?id={obj_id}",
                "points": points,
                "num_comments": comments,
                "engagement": points + comments,
                "created": hit.get("created_at", ""),
            })

    # 2) Top Stories 프론트페이지 (키워드 무관, 핫한 글 자동 수집)
    for item in _fetch_top_stories():
        hn_url = item.get("hn_url", "")
        obj_id = hn_url.split("id=")[-1] if "id=" in hn_url else ""
        if obj_id in seen_ids:
            continue
        seen_ids.add(obj_id)
        results.append(item)

    # engagement 높은 순 정렬, 상위 30개
    results.sort(key=lambda x: x["engagement"], reverse=True)
    return results[:30]
