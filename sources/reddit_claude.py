"""Reddit r/ClaudeAI 핫글 수집. PRAW(API 키) 또는 JSON 엔드포인트 사용."""

import os
import requests

TIMEOUT = 10
SUBREDDIT = "ClaudeAI"


def _fetch_via_praw() -> list[dict] | None:
    """PRAW를 사용하여 Reddit API로 핫글 수집."""
    client_id = os.getenv("REDDIT_CLIENT_ID")
    client_secret = os.getenv("REDDIT_CLIENT_SECRET")
    user_agent = os.getenv("REDDIT_USER_AGENT", "hot-topic-bot/0.1")

    if not client_id or not client_secret:
        return None

    try:
        import praw
    except ImportError:
        print("  [!] praw 미설치 - Reddit JSON 폴백 사용")
        return None

    try:
        reddit = praw.Reddit(
            client_id=client_id,
            client_secret=client_secret,
            user_agent=user_agent,
        )
        subreddit = reddit.subreddit(SUBREDDIT)
        results = []
        for post in subreddit.hot(limit=20):
            if post.stickied:
                continue
            results.append({
                "source": "reddit",
                "title": post.title,
                "url": f"https://reddit.com{post.permalink}",
                "description": (post.selftext[:200] + "...") if len(post.selftext) > 200 else post.selftext,
                "score": post.score,
                "num_comments": post.num_comments,
                "engagement": post.score + post.num_comments,
                "created": post.created_utc,
            })
        return results
    except Exception as e:
        print(f"  [!] Reddit PRAW 요청 실패: {e}")
        return None


def _fetch_via_json() -> list[dict]:
    """Reddit JSON 엔드포인트를 사용하여 핫글 수집 (API 키 불필요)."""
    url = f"https://www.reddit.com/r/{SUBREDDIT}/hot.json"
    headers = {"User-Agent": "hot-topic-bot/0.1"}

    try:
        resp = requests.get(url, headers=headers, timeout=TIMEOUT, params={"limit": 20})
        resp.raise_for_status()
        data = resp.json()
    except (requests.RequestException, ValueError) as e:
        print(f"  [!] Reddit JSON 요청 실패: {e}")
        return []

    results = []
    for child in data.get("data", {}).get("children", []):
        post = child.get("data", {})
        if post.get("stickied"):
            continue
        selftext = post.get("selftext", "")
        results.append({
            "source": "reddit",
            "title": post.get("title", ""),
            "url": f"https://reddit.com{post.get('permalink', '')}",
            "description": (selftext[:200] + "...") if len(selftext) > 200 else selftext,
            "score": post.get("score", 0),
            "num_comments": post.get("num_comments", 0),
            "engagement": post.get("score", 0) + post.get("num_comments", 0),
            "created": post.get("created_utc", 0),
        })

    return results


def fetch_reddit_claude() -> list[dict]:
    """Reddit r/ClaudeAI 핫글 수집. PRAW 우선, 실패 시 JSON 폴백."""
    result = _fetch_via_praw()
    if result is not None:
        return result
    return _fetch_via_json()
