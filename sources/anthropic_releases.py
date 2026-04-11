"""Anthropic 공식 릴리즈 노트 스크래핑."""

import sys

import requests
from bs4 import BeautifulSoup

RELEASE_NOTES_URL = "https://docs.anthropic.com/en/release-notes/overview"
TIMEOUT = 10


def fetch_anthropic_releases() -> list[dict]:
    """Anthropic 릴리즈 노트에서 최신 항목을 파싱."""
    try:
        resp = requests.get(
            RELEASE_NOTES_URL,
            timeout=TIMEOUT,
            headers={
                "User-Agent": "Mozilla/5.0 (compatible; hot-topic-bot/0.1)",
                "Accept-Language": "en-US,en;q=0.9",
            },
        )
        resp.raise_for_status()
    except requests.RequestException as e:
        print(f"  [!] Anthropic 릴리즈 노트 요청 실패: {e}", file=sys.stderr)
        return []

    soup = BeautifulSoup(resp.text, "html.parser")
    results = []

    # 릴리즈 노트 항목 파싱 - 구조에 따라 선택자 조정 필요
    # 일반적으로 h2/h3 헤더 + 날짜 + 내용 구조
    for heading in soup.select("h2, h3"):
        title = heading.get_text(strip=True)
        if not title:
            continue

        # 헤더 다음 형제 요소에서 설명 추출
        desc_parts = []
        sibling = heading.find_next_sibling()
        while sibling and sibling.name not in ("h2", "h3"):
            text = sibling.get_text(strip=True)
            if text:
                desc_parts.append(text)
            sibling = sibling.find_next_sibling()

        description = " ".join(desc_parts)[:300]

        # 앵커 링크 생성
        anchor = heading.get("id", "")
        url = f"{RELEASE_NOTES_URL}#{anchor}" if anchor else RELEASE_NOTES_URL

        results.append({
            "source": "anthropic_releases",
            "title": title,
            "url": url,
            "description": description,
            "engagement": 0,  # 릴리즈 노트는 engagement 없음
        })

    # 최근 10개만 반환
    return results[:10]
