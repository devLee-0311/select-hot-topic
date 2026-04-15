"""일일 max_score 표본을 보관해 디스플레이 정규화 앵커를 안정화한다.

디스플레이 점수는 배치 내 상대값으로 정규화되므로, 조용한 날에는 약한 아이템이
95/100처럼 보이는 부작용이 있다. 최근 7일 max_score의 70%를 하한 앵커로 사용하면
약한 배치의 인플레이션을 완화할 수 있다.

파일 포맷: JSON
  {"samples": [["2026-04-13T23:00:00", 5.8], ["2026-04-14T23:00:00", 6.2], ...]}
"""

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timedelta

DEFAULT_PATH = os.path.join(os.path.dirname(__file__), "score_stats.json")


def load_rolling_stats(path: str = DEFAULT_PATH) -> list[tuple[str, float]]:
    """최근 max_score 표본 `[(iso_ts, max_score), ...]` 로드.

    파일이 없거나 파싱 실패 시 빈 리스트 반환 (try/except로 폴백).
    """
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        raw = data.get("samples", []) if isinstance(data, dict) else []
        out: list[tuple[str, float]] = []
        for entry in raw:
            if (
                isinstance(entry, (list, tuple))
                and len(entry) == 2
                and isinstance(entry[0], str)
                and isinstance(entry[1], (int, float))
            ):
                out.append((entry[0], float(entry[1])))
        return out
    except (OSError, ValueError, json.JSONDecodeError):
        return []


def save_rolling_stats(
    samples: list[tuple[str, float]],
    today_max: float,
    path: str = DEFAULT_PATH,
    keep_days: int = 7,
) -> None:
    """오늘 max를 샘플에 추가하고 keep_days 넘는 오래된 샘플 제거 후 원자적 저장.

    실패는 조용히 무시 (점수 통계는 optional).
    """
    now = datetime.now()
    cutoff = now - timedelta(days=keep_days)
    merged: list[tuple[str, float]] = []
    for ts, val in samples:
        try:
            dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            # naive 비교를 위해 tz 제거
            dt = dt.replace(tzinfo=None)
        except (ValueError, AttributeError):
            continue
        if dt >= cutoff:
            merged.append((ts, float(val)))
    merged.append((now.isoformat(), float(today_max)))

    payload = {"samples": [list(s) for s in merged]}
    try:
        dirname = os.path.dirname(os.path.abspath(path)) or "."
        fd, tmp_path = tempfile.mkstemp(prefix=".score_stats_", suffix=".tmp", dir=dirname)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)
            os.replace(tmp_path, path)
        except Exception:
            # tmp 파일 정리
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise
    except OSError:
        pass
