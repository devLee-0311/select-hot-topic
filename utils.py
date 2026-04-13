"""공유 유틸리티: 제목 비교, 유사도 계산 등."""

import re
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
RELATED_THRESHOLD = 0.30
MIN_SHARED_KEYWORDS = 2


def stem(word: str) -> str:
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


def clean_for_compare(title: str) -> str:
    """비교용으로 제목을 정제."""
    title = title.lower()
    title = re.sub(r"^(tell hn|show hn|ask hn|launch hn)\s*:\s*", "", title)
    title = re.sub(r"^\[.*?\]\s*", "", title)
    title = re.sub(r"https?://\S+", "", title)
    title = re.sub(r"[^\w\s-]", " ", title)
    words = title.split()
    words = [w for w in words if w not in NOISE_WORDS and w not in CONTEXT_NOISE and len(w) > 1]
    words = [stem(w) for w in words]
    return " ".join(words)


def similarity(a: str, b: str) -> float:
    """두 제목의 유사도."""
    ca, cb = clean_for_compare(a), clean_for_compare(b)
    if not ca or not cb:
        return 0.0
    words_a, words_b = set(ca.split()), set(cb.split())
    jaccard = len(words_a & words_b) / len(words_a | words_b) if words_a | words_b else 0
    seq = SequenceMatcher(None, ca, cb).ratio()
    return max(jaccard, seq)


def is_related(title_a: str, title_b: str) -> bool:
    """두 제목이 같은 이슈를 다루는지 판정. 유사도 + 최소 키워드 겹침."""
    ca = clean_for_compare(title_a)
    cb = clean_for_compare(title_b)
    if not ca or not cb:
        return False

    # 키워드 겹침 수 확인
    words_a = set(ca.split())
    words_b = set(cb.split())
    shared = words_a & words_b
    if len(shared) < MIN_SHARED_KEYWORDS:
        return False

    # 유사도 확인
    return similarity(title_a, title_b) >= RELATED_THRESHOLD


def url_same_article(url_a: str, url_b: str) -> bool:
    """두 URL이 같은 페이지인지. 쿼리 파라미터 포함 비교."""
    if not url_a or not url_b:
        return False
    # 후행 슬래시만 정규화, 쿼리 파라미터는 유지 (HN item?id= 등 구분 필요)
    a = url_a.rstrip("/")
    b = url_b.rstrip("/")
    return a == b
