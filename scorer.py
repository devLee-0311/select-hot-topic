"""개별 아이템 기반 토픽 랭킹. 각 아이템이 하나의 토픽, 다른 소스에서 관련 자료를 찾아 첨부."""

import re
import time
from datetime import datetime
from difflib import SequenceMatcher

# 제목 비교 시 무시할 단어
NOISE_WORDS = {
    "the", "a", "an", "is", "are", "was", "were", "be", "been",
    "have", "has", "had", "do", "does", "did", "will", "would",
    "to", "of", "in", "for", "on", "with", "at", "by", "from",
    "as", "and", "or", "but", "not", "no", "so", "if", "this",
    "that", "it", "its", "i", "me", "my", "we", "you", "they",
    "about", "just", "how", "why", "what", "which", "who", "when",
    "tell", "show", "ask", "hn",
}

# 비교 시 제거할 컨텍스트 공통어 (스코프가 넓으므로 최소한만)
CONTEXT_NOISE = {"built", "build", "new", "use", "using", "get", "make"}

# 관련 자료 판정: 유사도 임계값 + 최소 공유 키워드 수
RELATED_THRESHOLD = 0.40
MIN_SHARED_KEYWORDS = 2


def _clean_for_compare(title: str) -> str:
    """비교용으로 제목을 정제."""
    title = title.lower()
    title = re.sub(r"^(tell hn|show hn|ask hn|launch hn)\s*:\s*", "", title)
    title = re.sub(r"^\[.*?\]\s*", "", title)
    title = re.sub(r"https?://\S+", "", title)
    title = re.sub(r"[^\w\s-]", " ", title)
    words = title.split()
    words = [w for w in words if w not in NOISE_WORDS and w not in CONTEXT_NOISE and len(w) > 1]
    words = [_stem(w) for w in words]
    return " ".join(words)


def _stem(word: str) -> str:
    """간단한 영어 어미 제거. leaked→leak, tools→tool 등."""
    if len(word) <= 3:
        return word
    for suffix in ("ation", "ness", "ment", "ible", "able"):
        if word.endswith(suffix) and len(word) - len(suffix) >= 3:
            return word[:-len(suffix)]
    for suffix in ("ing", "ied", "ies", "ous", "ive"):
        if word.endswith(suffix) and len(word) - len(suffix) >= 3:
            return word[:-len(suffix)]
    if word.endswith("ed") and len(word) > 4:
        return word[:-2]
    if word.endswith("es") and len(word) > 4:
        return word[:-2]
    if word.endswith("s") and not word.endswith("ss") and len(word) > 3:
        return word[:-1]
    return word


def _similarity(a: str, b: str) -> float:
    """두 제목의 유사도."""
    ca, cb = _clean_for_compare(a), _clean_for_compare(b)
    if not ca or not cb:
        return 0.0
    words_a, words_b = set(ca.split()), set(cb.split())
    jaccard = len(words_a & words_b) / len(words_a | words_b) if words_a | words_b else 0
    seq = SequenceMatcher(None, ca, cb).ratio()
    return max(jaccard, seq)


def _is_related(title_a: str, title_b: str) -> bool:
    """두 제목이 같은 이슈를 다루는지 판정. 유사도 + 최소 키워드 겹침."""
    ca = _clean_for_compare(title_a)
    cb = _clean_for_compare(title_b)
    if not ca or not cb:
        return False

    # 키워드 겹침 수 확인
    words_a = set(ca.split())
    words_b = set(cb.split())
    shared = words_a & words_b
    if len(shared) < MIN_SHARED_KEYWORDS:
        return False

    # 유사도 확인
    return _similarity(title_a, title_b) >= RELATED_THRESHOLD


def _url_same_article(url_a: str, url_b: str) -> bool:
    """두 URL이 같은 페이지인지. 쿼리 파라미터 포함 비교."""
    if not url_a or not url_b:
        return False
    # 후행 슬래시만 정규화, 쿼리 파라미터는 유지 (HN item?id= 등 구분 필요)
    a = url_a.rstrip("/")
    b = url_b.rstrip("/")
    return a == b


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
        anchor_source = anchor["source"]

        for candidate in sorted_items:
            if candidate is anchor:
                continue
            cand_url = candidate.get("url", "")
            if cand_url in used_urls:
                continue

            cand_title = candidate.get("title", "")

            # URL이 같으면 무조건 관련
            if _url_same_article(anchor_url, cand_url):
                related.append(candidate)
            elif _is_related(anchor_title, cand_title):
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
        "anthropic_releases": "Anthropic 릴리즈 노트",
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
