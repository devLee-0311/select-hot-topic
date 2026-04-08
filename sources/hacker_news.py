"""Hacker News Algolia API로 Claude/AI 관련 핫글 검색."""

import requests

SEARCH_URL = "https://hn.algolia.com/api/v1/search"
QUERIES = [
    "claude code", "anthropic claude", "claude AI", "MCP server",
    "LLM", "OpenAI GPT", "AI agent", "AI coding",
    "developer tools", "devtools CLI",
]
TIMEOUT = 10


def fetch_hacker_news(queries: list[str] | None = None) -> list[dict]:
    """Hacker News에서 최근 인기글 검색. queries를 지정하면 해당 쿼리로 검색."""
    results = []
    seen_ids = set()

    for query in (queries or QUERIES):
        try:
            resp = requests.get(
                SEARCH_URL,
                params={
                    "query": query,
                    "tags": "story",
                    "numericFilters": "points>5",
                    "hitsPerPage": 15,
                },
                timeout=TIMEOUT,
            )
            resp.raise_for_status()
            data = resp.json()
        except (requests.RequestException, ValueError) as e:
            print(f"  [!] Hacker News 요청 실패 ({query}): {e}")
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

    # engagement 높은 순 정렬, 상위 20개
    results.sort(key=lambda x: x["engagement"], reverse=True)
    return results[:20]
