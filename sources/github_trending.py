"""GitHub Trending 페이지에서 Claude/AI 관련 레포를 스크래핑."""

import requests
from bs4 import BeautifulSoup

TRENDING_URL = "https://github.com/trending"
KEYWORDS = [
    "claude", "anthropic", "claude-code", "mcp", "llm", "ai-agent",
    "ai-coding", "cursor", "copilot", "agentic", "vibe-coding", "vibe-code",
    "openai", "gpt", "gemini", "chatbot", "rag", "langchain", "autogen",
    "agent", "prompt", "embedding", "transformer", "diffusion",
    "machine-learning", "deep-learning", "neural", "inference",
]
TIMEOUT = 10


def _parse_repo_row(article) -> dict | None:
    """단일 trending 레포 행을 파싱."""
    # h2 > a 에서 레포 경로 추출 (여러 셀렉터 시도)
    a_tag = None
    for selector in ["h2 a", "h1 a", ".lh-condensed a"]:
        a_tag = article.select_one(selector)
        if a_tag:
            break
    if not a_tag or not a_tag.get("href"):
        return None

    repo_path = a_tag["href"].strip("/")
    repo_url = f"https://github.com/{repo_path}"
    repo_name = repo_path.split("/")[-1] if "/" in repo_path else repo_path

    desc_p = article.select_one("p")
    description = desc_p.get_text(strip=True) if desc_p else ""

    # stars today - 여러 셀렉터 시도
    stars_today = 0
    for selector in [
        "span.d-inline-block.float-sm-right",
        "span.float-sm-right",
        ".f6 span:last-child",
    ]:
        stars_span = article.select_one(selector)
        if stars_span:
            text = stars_span.get_text(strip=True).replace(",", "")
            digits = "".join(c for c in text if c.isdigit())
            if digits:
                stars_today = int(digits)
                break

    return {
        "repo_path": repo_path,
        "repo_name": repo_name,
        "repo_url": repo_url,
        "description": description,
        "stars_today": stars_today,
    }


def fetch_github_trending() -> list[dict]:
    """GitHub Trending에서 AI/Claude 관련 레포를 필터링하여 반환."""
    try:
        resp = requests.get(
            TRENDING_URL,
            params={"since": "daily"},
            timeout=TIMEOUT,
            headers={
                "User-Agent": "Mozilla/5.0 (compatible; hot-topic-bot/0.1)",
                "Accept-Language": "en-US,en;q=0.9",
            },
        )
        resp.raise_for_status()
    except requests.RequestException as e:
        print(f"  [!] GitHub Trending 요청 실패: {e}")
        return []

    soup = BeautifulSoup(resp.text, "html.parser")
    results = []

    # 여러 셀렉터 시도 (GitHub UI가 변경될 수 있음)
    articles = soup.select("article.Box-row")
    if not articles:
        articles = soup.select("article")
    if not articles:
        articles = soup.select("[class*='Box-row']")

    for article in articles:
        parsed = _parse_repo_row(article)
        if not parsed:
            continue

        searchable = f"{parsed['repo_path']} {parsed['description']}".lower()
        if any(kw in searchable for kw in KEYWORDS):
            results.append({
                "source": "github_trending",
                "title": parsed["repo_path"],
                "name": parsed["repo_name"],
                "url": parsed["repo_url"],
                "description": parsed["description"],
                "stars_today": parsed["stars_today"],
                "engagement": parsed["stars_today"],
            })

    return results
