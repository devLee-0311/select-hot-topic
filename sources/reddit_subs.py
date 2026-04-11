"""여러 Reddit 서브레딧에서 핫글 수집 (JSON 엔드포인트)."""

import sys

import requests

TIMEOUT = 10
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"}


def _fetch_subreddit(subreddit: str, limit: int = 20, keywords: list[str] | None = None) -> list[dict]:
    """단일 서브레딧의 핫글을 JSON 엔드포인트로 수집. keywords 지정 시 필터링."""
    url = f"https://old.reddit.com/r/{subreddit}/hot.json"

    try:
        resp = requests.get(
            url, headers=HEADERS, timeout=TIMEOUT, params={"limit": limit},
        )
        resp.raise_for_status()
        data = resp.json()
    except (requests.RequestException, ValueError) as e:
        print(f"  [!] Reddit r/{subreddit} 요청 실패: {e}", file=sys.stderr)
        return []

    results = []
    for child in data.get("data", {}).get("children", []):
        post = child.get("data", {})
        if post.get("stickied"):
            continue
        title = post.get("title", "")
        selftext = post.get("selftext", "")

        # 키워드 필터링
        if keywords:
            searchable = f"{title} {selftext}".lower()
            if not any(kw in searchable for kw in keywords):
                continue

        results.append({
            "source": f"reddit_{subreddit.lower()}",
            "title": title,
            "url": f"https://reddit.com{post.get('permalink', '')}",
            "description": (selftext[:200] + "...") if len(selftext) > 200 else selftext,
            "score": post.get("score", 0),
            "num_comments": post.get("num_comments", 0),
            "engagement": post.get("score", 0) + post.get("num_comments", 0),
            "created": post.get("created_utc", 0),
        })

    return results


def fetch_reddit_localllama() -> list[dict]:
    """Reddit r/LocalLLaMA 핫글 수집."""
    return _fetch_subreddit("LocalLLaMA")


def fetch_reddit_openai() -> list[dict]:
    """Reddit r/OpenAI 핫글 수집."""
    return _fetch_subreddit("OpenAI")


def fetch_reddit_programming() -> list[dict]:
    """Reddit r/programming 핫글 수집."""
    return _fetch_subreddit("programming")


def fetch_reddit_technology() -> list[dict]:
    """Reddit r/technology 핫글 수집."""
    return _fetch_subreddit("technology")


def fetch_reddit_eli5() -> list[dict]:
    """Reddit r/explainlikeimfive 핫글 수집."""
    return _fetch_subreddit("explainlikeimfive")


def fetch_reddit_technology_filtered(keywords: list[str]) -> list[dict]:
    """Reddit r/technology 핫글을 키워드 필터링하여 수집."""
    return _fetch_subreddit("technology", limit=50, keywords=keywords)


def fetch_reddit_eli5_filtered(keywords: list[str]) -> list[dict]:
    """Reddit r/explainlikeimfive 핫글을 키워드 필터링하여 수집."""
    return _fetch_subreddit("explainlikeimfive", limit=50, keywords=keywords)
