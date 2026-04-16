"""여러 Reddit 서브레딧에서 핫글 수집 (PRAW 우선, JSON 폴백)."""

import os
import sys

import requests

TIMEOUT = 10
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"}

# PRAW 인스턴스 캐시 (여러 서브레딧이 같은 인증으로 재사용)
_praw_reddit = None
_praw_checked = False


def _get_praw_reddit():
    """PRAW Reddit 인스턴스를 반환. 인증 불가하면 None."""
    global _praw_reddit, _praw_checked
    if _praw_checked:
        return _praw_reddit
    _praw_checked = True

    client_id = os.getenv("REDDIT_CLIENT_ID")
    client_secret = os.getenv("REDDIT_CLIENT_SECRET")
    if not client_id or not client_secret:
        return None

    try:
        import praw
        _praw_reddit = praw.Reddit(
            client_id=client_id,
            client_secret=client_secret,
            user_agent=os.getenv("REDDIT_USER_AGENT", "hot-topic-bot/0.1"),
        )
        return _praw_reddit
    except Exception:
        return None


def _fetch_via_praw(subreddit: str, limit: int = 20, keywords: list[str] | None = None) -> list[dict] | None:
    """PRAW를 사용하여 Reddit API로 핫글 수집."""
    reddit = _get_praw_reddit()
    if reddit is None:
        return None

    try:
        sub = reddit.subreddit(subreddit)
        results = []
        for post in sub.hot(limit=limit):
            if post.stickied:
                continue
            title = post.title
            selftext = post.selftext or ""

            if keywords:
                searchable = f"{title} {selftext}".lower()
                if not any(kw in searchable for kw in keywords):
                    continue

            results.append({
                "source": f"reddit_{subreddit.lower()}",
                "title": title,
                "url": f"https://reddit.com{post.permalink}",
                "description": (selftext[:200] + "...") if len(selftext) > 200 else selftext,
                "score": post.score,
                "num_comments": post.num_comments,
                "engagement": post.score + post.num_comments,
                "created": post.created_utc,
            })
        return results
    except Exception as e:
        print(f"  [!] Reddit PRAW r/{subreddit} 요청 실패: {e}", file=sys.stderr)
        return None


def _fetch_via_json(subreddit: str, limit: int = 20, keywords: list[str] | None = None) -> list[dict]:
    """Reddit JSON 엔드포인트를 사용하여 핫글 수집 (폴백)."""
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


def _fetch_subreddit(subreddit: str, limit: int = 20, keywords: list[str] | None = None) -> list[dict]:
    """단일 서브레딧의 핫글 수집. PRAW 우선, 실패 시 JSON 폴백."""
    result = _fetch_via_praw(subreddit, limit, keywords)
    if result is not None:
        return result
    return _fetch_via_json(subreddit, limit, keywords)


def fetch_reddit_localllama() -> list[dict]:
    """Reddit r/LocalLLaMA 핫글 수집."""
    return _fetch_subreddit("LocalLLaMA")


def fetch_reddit_openai() -> list[dict]:
    """Reddit r/OpenAI 핫글 수집."""
    return _fetch_subreddit("OpenAI")


def fetch_reddit_programming() -> list[dict]:
    """Reddit r/programming 핫글 수집."""
    return _fetch_subreddit("programming")


def fetch_reddit_artificial() -> list[dict]:
    """Reddit r/artificial 핫글 수집."""
    return _fetch_subreddit("artificial")


def fetch_reddit_machinelearning() -> list[dict]:
    """Reddit r/MachineLearning 핫글 수집."""
    return _fetch_subreddit("MachineLearning")


def fetch_reddit_singularity() -> list[dict]:
    """Reddit r/singularity 핫글 수집."""
    return _fetch_subreddit("singularity")


def fetch_reddit_stablediffusion() -> list[dict]:
    """Reddit r/StableDiffusion 핫글 수집."""
    return _fetch_subreddit("StableDiffusion")


def fetch_reddit_chatgpt() -> list[dict]:
    """Reddit r/ChatGPT 핫글 수집."""
    return _fetch_subreddit("ChatGPT")


def fetch_reddit_promptengineering() -> list[dict]:
    """Reddit r/PromptEngineering 핫글 수집."""
    return _fetch_subreddit("PromptEngineering")
