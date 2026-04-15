"""추천 이력 관리. 확인된 토픽만 기록하여 다음 추천에서 제외."""

import json
import os
from datetime import datetime, timedelta

HISTORY_FILE = os.path.join(os.path.dirname(__file__), "history.json")

# 이력 파일 무한 증가 방지 상한.
HISTORY_MAX_ENTRIES = 500
HISTORY_MAX_DAYS = 14


def _apply_history_cap(history: list[dict]) -> list[dict]:
    """최근 HISTORY_MAX_DAYS 이내 + 최대 HISTORY_MAX_ENTRIES 개만 유지.

    saved_at 필드가 없는 legacy 엔트리는 날짜 필터를 건너뛰고 count 캡만 적용.
    원래 순서(삽입 순서) 유지. 초과분은 앞에서 잘라낸다.
    """
    if not history:
        return history

    cutoff = datetime.now() - timedelta(days=HISTORY_MAX_DAYS)
    kept: list[dict] = []
    for entry in history:
        saved_at = entry.get("saved_at")
        if not saved_at:
            # legacy: 날짜 필터 패스
            kept.append(entry)
            continue
        try:
            dt = datetime.fromisoformat(str(saved_at).replace("Z", "+00:00"))
            # tz-aware면 naive로 맞춰 비교
            if dt.tzinfo is not None:
                dt = dt.replace(tzinfo=None)
        except (ValueError, TypeError):
            kept.append(entry)
            continue
        if dt >= cutoff:
            kept.append(entry)

    if len(kept) > HISTORY_MAX_ENTRIES:
        kept = kept[-HISTORY_MAX_ENTRIES:]
    return kept


def load_history() -> list[dict]:
    """이력 파일 로드. 로드 시점에 캡 적용 (읽기는 메모리 내에서만)."""
    if not os.path.exists(HISTORY_FILE):
        return []
    with open(HISTORY_FILE, "r", encoding="utf-8") as f:
        history = json.load(f)
    if not isinstance(history, list):
        return []
    return _apply_history_cap(history)


def save_topic(topic: dict, mode: str = "hot") -> None:
    """토픽을 이력에 저장. 파일에 쓸 때도 동일한 캡 적용."""
    # 파일에서 원본 그대로 읽어서 append 후 캡 적용 → 쓰기
    if os.path.exists(HISTORY_FILE):
        with open(HISTORY_FILE, "r", encoding="utf-8") as f:
            history = json.load(f)
        if not isinstance(history, list):
            history = []
    else:
        history = []

    history.append({
        "topic": topic["topic"],
        "score": topic["score"],
        "reasons": topic["reasons"],
        "references": [ref["url"] for ref in topic["references"]],
        "mode": mode,
        "saved_at": datetime.now().isoformat(),
    })
    history = _apply_history_cap(history)
    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)


def get_used_urls() -> set[str]:
    """이력에 기록된 모든 레퍼런스 URL 집합 반환."""
    history = load_history()
    urls = set()
    for entry in history:
        for url in entry.get("references", []):
            urls.add(url)
    return urls


def get_used_topic_names() -> set[str]:
    """이력에 기록된 토픽 이름 집합 반환."""
    history = load_history()
    return {entry["topic"].lower() for entry in history}
