"""개별 아이템 기반 토픽 랭킹. 각 아이템이 하나의 토픽, 다른 소스에서 관련 자료를 찾아 첨부."""

import time
from datetime import datetime

from utils import (
    is_related, url_same_article,
)


def score_topics(all_items: list[dict], top_n: int = 5, weights: dict | None = None) -> list[dict]:
    """
    개별 아이템 기반 토픽 랭킹.

    1. engagement 순으로 아이템 정렬
    2. 각 아이템 = 하나의 토픽
    3. 다른 소스에서 관련 자료를 찾아 레퍼런스로 첨부
    4. 교차 소스 언급이 있으면 스코어 보너스
    """
    if not all_items:
        return []

    # 최신성 필터: 7일 이상 된 아이템 제거
    cutoff = time.time() - 7 * 86400
    filtered_items = []
    for item in all_items:
        created = item.get("created") or item.get("created_utc")
        if created is None:
            filtered_items.append(item)  # 날짜 정보 없으면 통과
        elif isinstance(created, (int, float)):
            if created > cutoff:
                filtered_items.append(item)
        elif isinstance(created, str):
            try:
                ts = datetime.fromisoformat(created.replace("Z", "+00:00")).timestamp()
                if ts > cutoff:
                    filtered_items.append(item)
            except (ValueError, OSError):
                filtered_items.append(item)
    all_items = filtered_items

    w = weights or {}
    eng_multiplier = w.get("eng_multiplier", 0.02)
    eng_cap = w.get("eng_cap", 40)
    cross_bonus_per = w.get("cross_bonus", 15)
    related_multiplier = w.get("related_multiplier", 0.01)
    related_cap = w.get("related_cap", 15)
    base = w.get("base_score", 20)

    # engagement 높은 순 정렬
    sorted_items = sorted(all_items, key=lambda x: x.get("engagement", 0), reverse=True)

    topics = []
    used_urls: set[str] = set()

    for anchor in sorted_items:
        anchor_url = anchor.get("url", "")

        # 이미 다른 토픽의 앵커로 사용된 URL 스킵
        if anchor_url in used_urls:
            continue

        # 다른 소스에서 관련 자료 찾기
        related = []
        anchor_title = anchor.get("title", "")

        for candidate in sorted_items:
            if candidate is anchor:
                continue
            cand_url = candidate.get("url", "")
            if cand_url in used_urls:
                continue

            cand_title = candidate.get("title", "")

            # URL이 같으면 무조건 관련
            if url_same_article(anchor_url, cand_url):
                related.append(candidate)
            elif is_related(anchor_title, cand_title):
                related.append(candidate)

        # 스코어 계산
        base_eng = anchor.get("engagement", 0)
        eng_score = min(base_eng * eng_multiplier, eng_cap)

        # 교차 소스 보너스
        related_sources = {item["source"] for item in related}
        cross_bonus = len(related_sources) * cross_bonus_per

        # 관련 자료 engagement 보너스
        related_eng = sum(item.get("engagement", 0) for item in related)
        related_score = min(related_eng * related_multiplier, related_cap)

        score = min(int(base + eng_score + cross_bonus + related_score), 100)

        # 토픽 제목
        topic_title = anchor_title
        if len(topic_title) > 80:
            topic_title = topic_title[:77] + "..."

        # 근거 생성
        reasons = _build_reasons(anchor, related)

        # 레퍼런스: 앵커 + 관련 자료 (최대 5개)
        refs = [_make_ref(anchor)]
        seen_ref_urls = {anchor_url}
        for item in sorted(related, key=lambda x: x.get("engagement", 0), reverse=True):
            item_url = item.get("url", "")
            if item_url not in seen_ref_urls:
                seen_ref_urls.add(item_url)
                refs.append(_make_ref(item))
            if len(refs) >= 5:
                break

        topics.append({
            "topic": topic_title,
            "description": anchor.get("description", ""),
            "score": score,
            "reasons": reasons,
            "references": refs,
        })

        # 사용된 URL 기록
        used_urls.add(anchor_url)
        for item in related:
            used_urls.add(item.get("url", ""))

        if len(topics) >= top_n:
            break

    return topics


def _make_ref(item: dict) -> dict:
    """아이템을 레퍼런스 형식으로 변환."""
    return {
        "title": item.get("title", ""),
        "url": item.get("url", ""),
        "source": item["source"],
        "engagement": item.get("engagement", 0),
    }


def _build_reasons(anchor: dict, related: list[dict]) -> list[str]:
    """토픽 선정 근거."""
    reasons = []

    source_labels = {
        "reddit": "Reddit r/ClaudeAI",
        "reddit_localllama": "Reddit r/LocalLLaMA",
        "reddit_openai": "Reddit r/OpenAI",
        "reddit_programming": "Reddit r/programming",
        "github_trending": "GitHub Trending",
        "hacker_news": "Hacker News",
        "youtube": "YouTube",
        "geeknews": "GeekNews",
    }

    # 앵커 소스 정보
    anchor_label = source_labels.get(anchor["source"], anchor["source"])
    anchor_eng = anchor.get("engagement", 0)
    reasons.append(f"{anchor_label}에서 화제 (engagement {anchor_eng:,})")

    # 교차 소스
    if related:
        related_sources = set()
        for item in related:
            related_sources.add(item["source"])

        cross_labels = [source_labels.get(s, s) for s in related_sources]
        if cross_labels:
            reasons.append(f"관련 자료: {', '.join(cross_labels)}에서도 언급")

    return reasons
