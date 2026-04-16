"""여러 Reddit 서브레딧에서 핫글 수집 (RSS → Arctic Shift → JSON 폴백)."""

import sys
import time
import xml.etree.ElementTree as ET

import requests

TIMEOUT = 10
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"}

# Arctic Shift API — Reddit 데이터 아카이브, 인증 불필요
ARCTIC_SHIFT_URL = "https://arctic-shift.photon-reddit.com/api/posts/search"


def _fetch_via_rss(subreddit: str, limit: int = 20) -> list[dict] | None:
    """Reddit RSS 피드로 핫글 수집. 실패 시 None 반환."""
    url = f"https://www.reddit.com/r/{subreddit}/hot.rss"
    try:
        resp = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
        resp.raise_for_status()
    except (requests.RequestException, ValueError) as e:
        print(f"  [!] Reddit RSS r/{subreddit} 요청 실패: {e}", file=sys.stderr)
        return None

    try:
        root = ET.fromstring(resp.text)
    except ET.ParseError:
        return None

    ns = {"atom": "http://www.w3.org/2005/Atom"}
    entries = root.findall("atom:entry", ns)
    if not entries:
        return None

    results = []
    for entry in entries[:limit]:
        title = entry.findtext("atom:title", "", ns)
        link = entry.findtext("atom:link", "", ns)
        # RSS entry의 link는 <link href="..."/> 형태
        link_el = entry.find("atom:link", ns)
        if link_el is not None:
            link = link_el.get("href", "")

        # content에서 selftext 추출은 어려우므로 title만 사용
        results.append({
            "source": f"reddit_{subreddit.lower()}",
            "title": title,
            "url": link,
            "description": "",
            "score": 0,
            "num_comments": 0,
            "engagement": 0,  # RSS에는 score/comments 정보 없음
            "created": 0,
        })

    return results if results else None


def _fetch_via_arctic_shift(subreddit: str, limit: int = 20) -> list[dict] | None:
    """Arctic Shift API로 최근 인기글 수집. 실패 시 None 반환."""
    try:
        resp = requests.get(
            ARCTIC_SHIFT_URL,
            params={
                "subreddit": subreddit,
                "sort": "score",
                "order": "desc",
                "limit": limit,
                "after": int(time.time()) - 7 * 86400,  # 최근 7일
            },
            headers=HEADERS,
            timeout=TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()
    except (requests.RequestException, ValueError) as e:
        print(f"  [!] Arctic Shift r/{subreddit} 요청 실패: {e}", file=sys.stderr)
        return None

    posts = data.get("data", [])
    if not posts:
        return None

    results = []
    for post in posts:
        if post.get("stickied"):
            continue
        title = post.get("title", "")
        selftext = post.get("selftext", "")
        score = post.get("score", 0) or 0
        comments = post.get("num_comments", 0) or 0
        permalink = post.get("permalink", "")

        results.append({
            "source": f"reddit_{subreddit.lower()}",
            "title": title,
            "url": f"https://reddit.com{permalink}" if permalink else "",
            "description": (selftext[:200] + "...") if len(selftext) > 200 else selftext,
            "score": score,
            "num_comments": comments,
            "engagement": score + comments,
            "created": post.get("created_utc", 0),
        })

    return results if results else None


def _fetch_via_json(subreddit: str, limit: int = 20) -> list[dict]:
    """Reddit JSON 엔드포인트로 핫글 수집 (최후 폴백)."""
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
    """단일 서브레딧의 핫글 수집. RSS → Arctic Shift → JSON 순으로 시도."""
    # 1) RSS
    result = _fetch_via_rss(subreddit, limit)
    # 2) Arctic Shift
    if result is None:
        result = _fetch_via_arctic_shift(subreddit, limit)
    # 3) JSON (최후 수단)
    if result is None:
        result = _fetch_via_json(subreddit, limit)

    if not result:
        return []

    # 키워드 필터링
    if keywords:
        result = [
            item for item in result
            if any(kw in f"{item['title']} {item['description']}".lower() for kw in keywords)
        ]

    return result


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
