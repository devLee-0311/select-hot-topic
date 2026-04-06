"""추천 이력 관리. 확인된 토픽만 기록하여 다음 추천에서 제외."""

import json
import os
from datetime import datetime

HISTORY_FILE = os.path.join(os.path.dirname(__file__), "history.json")


def load_history() -> list[dict]:
    """이력 파일 로드."""
    if not os.path.exists(HISTORY_FILE):
        return []
    with open(HISTORY_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def save_topic(topic: dict) -> None:
    """토픽을 이력에 저장."""
    history = load_history()
    history.append({
        "topic": topic["topic"],
        "score": topic["score"],
        "reasons": topic["reasons"],
        "references": [ref["url"] for ref in topic["references"]],
        "saved_at": datetime.now().isoformat(),
    })
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
