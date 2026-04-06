"""GeekNews(news.hada.io)에서 Claude/AI 관련 글 수집."""

import re
import requests
from bs4 import BeautifulSoup

BASE_URL = "https://news.hada.io"
PAGES = ["/new", "/"]
KEYWORDS = [
    "claude", "anthropic", "mcp", "llm", "ai agent", "agentic",
    "cursor", "copilot", "vibe coding", "클로드", "앤트로픽",
    "코딩 에이전트", "바이브 코딩", "openai", "gpt", "gemini",
]
TIMEOUT = 10


def fetch_geeknews() -> list[dict]:
    """GeekNews에서 Claude/AI 관련 최신 글 수집."""
    results = []
    seen_ids = set()

    for page_path in PAGES:
        try:
            resp = requests.get(
                f"{BASE_URL}{page_path}",
                timeout=TIMEOUT,
                headers={
                    "User-Agent": "Mozilla/5.0 (compatible; hot-topic-bot/0.1)",
                    "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.8",
                },
            )
            resp.raise_for_status()
        except requests.RequestException as e:
            print(f"  [!] GeekNews 요청 실패 ({page_path}): {e}")
            continue

        soup = BeautifulSoup(resp.text, "html.parser")

        for row in soup.select("div.topic_row"):
            # article ID 추출
            vote_link = row.find("a", href=re.compile(r"javascript:vote\(\d+"))
            if not vote_link:
                continue
            match = re.search(r"vote\((\d+)", vote_link.get("href", ""))
            if not match:
                continue
            article_id = match.group(1)
            if article_id in seen_ids:
                continue
            seen_ids.add(article_id)

            # 제목 & URL: 외부 링크 (http로 시작하는 첫 번째 a 태그)
            title = ""
            url = ""
            for a_tag in row.find_all("a"):
                href = a_tag.get("href", "")
                if href.startswith("http"):
                    title = a_tag.get_text(strip=True)
                    url = href
                    break

            if not title:
                # topic 링크에서 제목 가져오기
                topic_link = row.find("a", href=re.compile(r"topic\?id="))
                if topic_link:
                    title = topic_link.get_text(strip=True)
                    url = f"{BASE_URL}/{topic_link['href']}"

            if not title:
                continue

            # 포인트 파싱
            points = 0
            text_content = row.get_text()
            points_match = re.search(r"(\d+)\s*point", text_content)
            if points_match:
                points = int(points_match.group(1))

            # 댓글 수 파싱
            comments = 0
            comment_match = re.search(r"(\d+)개", text_content)
            if comment_match:
                comments = int(comment_match.group(1))

            # GeekNews 토론 페이지 URL
            geeknews_url = f"{BASE_URL}/topic?id={article_id}"

            # 키워드 필터링
            searchable = f"{title}".lower()
            if not any(kw in searchable for kw in KEYWORDS):
                continue

            results.append({
                "source": "geeknews",
                "title": title,
                "url": url,
                "geeknews_url": geeknews_url,
                "description": title,
                "points": points,
                "num_comments": comments,
                "engagement": points + comments,
            })

    # engagement 높은 순
    results.sort(key=lambda x: x["engagement"], reverse=True)
    return results[:20]
