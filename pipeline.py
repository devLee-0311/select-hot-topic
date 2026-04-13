"""키워드 티어링 → 클러스터 → 정규화 → 분류 → 최종 스코어링 파이프라인."""

from __future__ import annotations

import re
import time
from collections import defaultdict
from datetime import datetime

from utils import clean_for_compare, similarity

# ── 키워드 티어 ──────────────────────────────────────────────

KEYWORD_TIERS = {
    "tier1_core": {
        "keywords": [
            "claude", "anthropic", "mcp", "claude code",
            "model context protocol", "클로드", "앤트로픽",
        ],
        "min_engagement": 0,
    },
    "tier2_adjacent": {
        "keywords": [
            "cursor", "copilot", "langchain", "langgraph",
            "ai-agent", "agentic", "openai", "gemini",
            "windsurf", "cline", "v0", "bolt",
            "autogen", "crewai", "dspy",
        ],
        "min_engagement": {
            "github": 50, "hackernews": 10, "reddit": 50,
            "youtube": 5000, "geeknews": 3,
        },
    },
    "tier3_broad": {
        "keywords": [
            "llm", "gpt", "ai", "machine learning",
            "devtools", "developer tools", "rag",
            "fine-tuning", "prompt engineering",
            "vector database", "embedding",
            "transformer", "diffusion",
            "cybersecurity", "cloud", "privacy",
        ],
        "min_engagement_percentile": 90,
        "or_cross_source_count": 2,
    },
}

SOURCE_FAMILY = {
    "github_trending": "github",
    "hacker_news": "hackernews",
    "youtube": "youtube",
    "geeknews": "geeknews",
    "anthropic_releases": "anthropic",
}

TIER_WEIGHTS = {"tier1": 1.5, "tier2": 1.0, "tier3": 0.6}

CROSS_SOURCE_BOOST = {1: 1.0, 2: 1.5, 3: 2.5}
SIMILARITY_THRESHOLD = 0.4

DISPLAY_SCORE_CAP_BY_CROSS = {1: 70, 2: 85, 3: 99, 4: 99, 5: 99}

CLUSTER_SIMILARITY_THRESHOLD = 0.55
CLUSTER_MIN_SHARED_KEYWORDS = 2

HOT_SIGNAL_KEYWORDS = [
    "release", "launch", "announce", "breaking",
    "outage", "deprecated", "출시", "발표", "장애", "지원중단",
]
EVERGREEN_SIGNAL_KEYWORDS = [
    "tutorial", "guide", "how-to", "comparison",
    "vs", "비교", "가이드", "입문", "정리",
]

RECENCY_DECAY_HOURS = 72
RECENCY_FLOOR = 0.3
TIER1_ENGAGEMENT_FLOOR = 0.1


# ── 헬퍼 ────────────────────────────────────────────────────

def _source_family(source: str) -> str:
    """소스 문자열을 패밀리로 매핑."""
    if source.startswith("reddit"):
        return "reddit"
    return SOURCE_FAMILY.get(source, source)


def _get_raw_engagement(item: dict) -> float:
    """소스별 원시 engagement 값 반환. YouTube는 views 사용."""
    if _source_family(item.get("source", "")) == "youtube":
        return float(item.get("views", item.get("engagement", 0)))
    return float(item.get("engagement", 0))


def _searchable_text(item: dict) -> str:
    """티어 매칭용 검색 텍스트."""
    return f"{item.get('title', '')} {item.get('description', '')} {item.get('url', '')}".lower()


def _match_tier(text: str) -> tuple[str | None, list[str]]:
    """텍스트가 매칭되는 최상위 티어와 매칭 키워드 반환."""
    for tier_name, tier_order in [("tier1_core", "tier1"), ("tier2_adjacent", "tier2"), ("tier3_broad", "tier3")]:
        tier = KEYWORD_TIERS[tier_name]
        matched = [kw for kw in tier["keywords"] if kw in text]
        if matched:
            return tier_order, matched
    return None, []


def _has_cross_source_mention(item: dict, all_items: list[dict]) -> bool:
    """다른 소스 패밀리에서 유사한 제목 또는 URL이 존재하는지 확인."""
    my_family = _source_family(item.get("source", ""))
    my_title = item.get("title", "")
    my_url = item.get("url", "")

    for other in all_items:
        if other is item:
            continue
        other_family = _source_family(other.get("source", ""))
        if other_family == my_family:
            continue
        # URL 부분 문자열 검사
        other_url = other.get("url", "")
        if my_url and other_url and (my_url in other_url or other_url in my_url):
            return True
        # 제목 유사도 검사
        if similarity(my_title, other.get("title", "")) >= SIMILARITY_THRESHOLD:
            return True
    return False


# ── 파이프라인 단계 ──────────────────────────────────────────

def tag_tiers(items: list[dict], skip_tiering: bool = False) -> list[dict]:
    """각 아이템에 matched_tier, matched_keywords 필드 부여. 매칭 안 되면 제외."""
    if skip_tiering:
        for item in items:
            item["matched_tier"] = "tier2"
            item["matched_keywords"] = []
        return items

    # tier3 필터링용: 상위 10% engagement 임계값 계산
    engagements = sorted([_get_raw_engagement(it) for it in items if _get_raw_engagement(it) > 0])
    if engagements:
        idx = max(0, int(len(engagements) * 0.9) - 1)
        top10_threshold = engagements[idx]
    else:
        top10_threshold = float("inf")

    result = []
    for item in items:
        text = _searchable_text(item)
        tier, matched_kws = _match_tier(text)
        if tier is None:
            continue

        item["matched_tier"] = tier
        item["matched_keywords"] = matched_kws

        # tier2: per-source min_engagement 필터
        if tier == "tier2":
            family = _source_family(item.get("source", ""))
            min_eng = KEYWORD_TIERS["tier2_adjacent"]["min_engagement"]
            if isinstance(min_eng, dict):
                threshold = min_eng.get(family, 0)
            else:
                threshold = min_eng
            if _get_raw_engagement(item) < threshold:
                continue

        # tier3: cross-source 또는 상위 10% engagement 필요
        if tier == "tier3":
            has_cross = _has_cross_source_mention(item, items)
            in_top10 = _get_raw_engagement(item) >= top10_threshold
            if not has_cross and not in_top10:
                continue

        result.append(item)

    return result


def _titles_cluster(a: str, b: str) -> bool:
    """두 제목이 클러스터링 기준을 충족하는지 판정.

    CLUSTER_MIN_SHARED_KEYWORDS 이상의 공유 단어 AND
    similarity >= CLUSTER_SIMILARITY_THRESHOLD 를 모두 만족해야 True.
    """
    ca, cb = clean_for_compare(a), clean_for_compare(b)
    if not ca or not cb:
        return False
    words_a = set(ca.split())
    words_b = set(cb.split())
    if len(words_a & words_b) < CLUSTER_MIN_SHARED_KEYWORDS:
        return False
    return similarity(a, b) >= CLUSTER_SIMILARITY_THRESHOLD


def detect_clusters(items: list[dict]) -> tuple[list[dict], list[dict]]:
    """아이템을 클러스터링. URL 부분 문자열 또는 제목 유사도 기준.

    전이적 유니온-파인드 대신 pairwise-strict 그리디 방식 사용:
    새 아이템은 기존 클러스터의 모든 멤버와 유사해야 병합.
    """
    n = len(items)
    # cluster_of[i] = 클러스터 인덱스 (None이면 미배정)
    cluster_of: list[int | None] = [None] * n
    # clusters_members[c] = 해당 클러스터에 속한 아이템 인덱스 목록
    clusters_members: list[list[int]] = []

    def _url_linked(i: int, j: int) -> bool:
        url_i = items[i].get("url", "")
        url_j = items[j].get("url", "")
        return bool(url_i and url_j and (url_i in url_j or url_j in url_i))

    def _pair_linked(i: int, j: int) -> bool:
        if _url_linked(i, j):
            return True
        return _titles_cluster(items[i].get("title", ""), items[j].get("title", ""))

    for i in range(n):
        merged = False
        for c_idx, members in enumerate(clusters_members):
            # 새 아이템이 클러스터의 모든 기존 멤버와 연결되어야 병합
            if all(_pair_linked(i, m) for m in members):
                members.append(i)
                cluster_of[i] = c_idx
                merged = True
                break
        if not merged:
            cluster_of[i] = len(clusters_members)
            clusters_members.append([i])

    # 클러스터 그룹핑
    groups: dict[int, list[int]] = defaultdict(list)
    for i in range(n):
        groups[cluster_of[i]].append(i)

    cluster_id_counter = 0
    clusters: list[dict] = []

    for indices in groups.values():
        cluster_items = [items[idx] for idx in indices]
        families = {_source_family(it.get("source", "")) for it in cluster_items}
        source_count = len(families)
        boost = CROSS_SOURCE_BOOST.get(source_count, 4.0) if source_count <= 3 else 4.0

        if len(indices) == 1:
            # 싱글턴
            items[indices[0]]["cluster_id"] = None
            items[indices[0]]["cross_source_count"] = source_count
            items[indices[0]]["cross_source_boost"] = boost
        else:
            cid = cluster_id_counter
            cluster_id_counter += 1
            # canonical: 가장 높은 engagement 아이템의 제목
            best = max(cluster_items, key=lambda it: _get_raw_engagement(it))
            for idx in indices:
                items[idx]["cluster_id"] = cid
                items[idx]["cross_source_count"] = source_count
                items[idx]["cross_source_boost"] = boost
            clusters.append({
                "cluster_id": cid,
                "canonical_title": best.get("title", ""),
                "sources": sorted(families),
                "source_count": source_count,
                "items": cluster_items,
                "cross_source_boost": boost,
            })

    return items, clusters


def normalize_engagement(items: list[dict]) -> list[dict]:
    """소스 패밀리별 engagement 백분위 정규화."""
    groups: dict[str, list[dict]] = defaultdict(list)
    for item in items:
        family = _source_family(item.get("source", ""))
        groups[family].append(item)

    for family, group in groups.items():
        n = len(group)
        if n == 1:
            group[0]["engagement_normalized"] = 1.0
            continue
        if n < 5:
            for it in group:
                it["engagement_normalized"] = 0.5
            continue

        # rank ascending by raw engagement
        raw_vals = [_get_raw_engagement(it) for it in group]
        sorted_pairs = sorted(enumerate(raw_vals), key=lambda x: x[1])

        # 동일 값 평균 순위 계산
        ranks = [0.0] * n
        i = 0
        while i < n:
            j = i
            while j < n and sorted_pairs[j][1] == sorted_pairs[i][1]:
                j += 1
            avg_rank = sum(range(i, j)) / (j - i)
            for k in range(i, j):
                ranks[sorted_pairs[k][0]] = avg_rank
            i = j

        for idx, it in enumerate(group):
            it["engagement_normalized"] = round(ranks[idx] / (n - 1), 4)

    return items


_YOUTUBE_TIME_MULTIPLIERS = {
    "second": 1 / 3600,
    "minute": 1 / 60,
    "hour": 1,
    "day": 24,
    "week": 168,
    "month": 720,
    "year": 8760,
}


def _parse_hours_since(item: dict) -> float | None:
    """아이템의 게시 후 경과 시간(hours) 계산."""
    now = time.time()

    # YouTube published 필드 (e.g. "2 days ago")
    published = item.get("published", "")
    if published:
        m = re.search(r"(\d+)\s*(second|minute|hour|day|week|month|year)", published, re.IGNORECASE)
        if m:
            val = int(m.group(1))
            unit = m.group(2).lower()
            return val * _YOUTUBE_TIME_MULTIPLIERS.get(unit, 1)

    # created / created_utc (unix timestamp 또는 ISO 문자열)
    for field in ("created", "created_utc"):
        raw = item.get(field)
        if raw is None:
            continue
        if isinstance(raw, (int, float)):
            return max(0, (now - raw) / 3600)
        if isinstance(raw, str):
            try:
                dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
                return max(0, (now - dt.timestamp()) / 3600)
            except (ValueError, OSError):
                pass

    return None


def classify_content_type(items: list[dict]) -> list[dict]:
    """각 아이템을 hot/evergreen으로 분류."""
    for item in items:
        hours = _parse_hours_since(item)
        item["hours_since_published"] = hours
        eng_norm = item.get("engagement_normalized", 0.5)
        cross = item.get("cross_source_count", 1)
        text = _searchable_text(item)

        is_hot = False
        is_evergreen = False

        # HOT 판정
        if hours is not None and hours < 24 and eng_norm >= 0.80:
            is_hot = True
        if cross >= 2:
            is_hot = True
        if any(kw in text for kw in HOT_SIGNAL_KEYWORDS):
            is_hot = True

        # EVERGREEN 판정
        if hours is not None and hours >= 72 and eng_norm >= 0.50:
            is_evergreen = True
        source = item.get("source", "")
        if _source_family(source) == "youtube" and hours is not None and hours >= 168 and eng_norm >= 0.60:
            is_evergreen = True
        if any(kw in text for kw in EVERGREEN_SIGNAL_KEYWORDS):
            is_evergreen = True

        if is_hot:
            item["content_type"] = "hot"
        elif is_evergreen:
            item["content_type"] = "evergreen"
        else:
            # 기본값: cross-source 또는 높은 engagement가 있으면 hot, 아니면 evergreen
            if cross >= 2 or eng_norm >= 0.5:
                item["content_type"] = "hot"
            else:
                item["content_type"] = "evergreen"

    return items


def compute_final_scores(items: list[dict], config: dict | None = None) -> list[dict]:
    """최종 점수 계산."""
    weights = TIER_WEIGHTS
    if config and "tier_weights" in config:
        weights = config["tier_weights"]

    for item in items:
        tier = item.get("matched_tier", "tier2")
        tier_w = weights.get(tier, 1.0)
        eng_norm = item.get("engagement_normalized", 0.5)
        boost = item.get("cross_source_boost", 1.0)

        # tier1 floor
        if tier == "tier1":
            eng_norm = max(eng_norm, TIER1_ENGAGEMENT_FLOOR)

        score = eng_norm * tier_w * boost

        # hot recency 보정
        if item.get("content_type") == "hot" and item.get("hours_since_published") is not None:
            recency = max(RECENCY_FLOOR, 1.0 - item["hours_since_published"] / RECENCY_DECAY_HOURS)
            score *= recency

        item["final_score"] = round(score, 4)

    return items


def run_pipeline(items: list[dict], config: dict | None = None) -> dict:
    """전체 파이프라인 실행. config: skip_tiering, hot_count, evergreen_count, tier_weights."""
    if config is None:
        config = {}

    hot_count = config.get("hot_count", 3)
    evergreen_count = config.get("evergreen_count", 2)

    # 파이프라인 단계 순차 실행
    items = tag_tiers(items, skip_tiering=config.get("skip_tiering", False))
    items, clusters = detect_clusters(items)
    items = normalize_engagement(items)
    items = classify_content_type(items)
    items = compute_final_scores(items, config)

    # 점수 내림차순 정렬
    items.sort(key=lambda x: x.get("final_score", 0), reverse=True)

    # hot / evergreen 분리
    hot_items = [it for it in items if it.get("content_type") == "hot"]
    ever_items = [it for it in items if it.get("content_type") == "evergreen"]

    hot_top = hot_items[:hot_count]
    ever_top = ever_items[:evergreen_count]

    # Tier1 reserved slot: hot에 tier1이 없으면 전체에서 가장 높은 tier1 삽입
    has_tier1_in_hot = any(it.get("matched_tier") == "tier1" for it in hot_top)
    if not has_tier1_in_hot:
        tier1_all = [it for it in items if it.get("matched_tier") == "tier1"]
        if tier1_all:
            best_tier1 = tier1_all[0]  # 이미 점수순 정렬됨
            if hot_top:
                hot_top[-1] = best_tier1
            else:
                hot_top.append(best_tier1)

    # Attach cluster_refs to each hot/evergreen item
    cluster_map: dict[int, list[dict]] = defaultdict(list)
    for it in items:
        cid = it.get("cluster_id")
        if cid is not None:
            cluster_map[cid].append(it)

    for it in hot_top + ever_top:
        cid = it.get("cluster_id")
        if cid is not None and len(cluster_map[cid]) >= 2:
            others = [
                m for m in cluster_map[cid]
                if m is not it
            ]
            others.sort(key=lambda m: _get_raw_engagement(m), reverse=True)
            it["cluster_refs"] = [
                {
                    "title": m.get("title", ""),
                    "url": m.get("url", ""),
                    "source": m.get("source", ""),
                    "engagement": _get_raw_engagement(m),
                }
                for m in others[:4]
            ]
        else:
            it["cluster_refs"] = []

    max_score = max((i.get("final_score", 0.0) for i in items), default=1.0) or 1.0

    return {
        "hot": hot_top,
        "evergreen": ever_top,
        "all_scored": items,
        "clusters": clusters,
        "max_score": max_score,
    }


def adapt_for_filter_seen(items: list[dict], max_score: float = 6.0) -> list[dict]:
    """파이프라인 출력을 filter_seen() 호환 형태로 변환."""
    topics = []
    for item in items:
        raw_eng = _get_raw_engagement(item)
        source = item.get("source", "")
        cross = item.get("cross_source_count", 1)
        cap = DISPLAY_SCORE_CAP_BY_CROSS.get(min(cross, 5), 99)
        relative = int(item.get("final_score", 0) / max_score * 99) if max_score > 0 else 0
        score = min(cap, relative)

        reasons = [f"{source} 화제 (engagement {int(raw_eng):,})"]
        cross = item.get("cross_source_count", 1)
        if cross >= 2:
            reasons.append(f"교차 소스 {cross}곳 언급")
        tier = item.get("matched_tier", "")
        if tier:
            reasons.append(tier)

        topics.append({
            "topic": item.get("title", "")[:80],
            "description": item.get("description", ""),
            "score": score,
            "reasons": reasons,
            "references": [
                {
                    "title": item.get("title", ""),
                    "url": item.get("url", ""),
                    "source": source,
                    "engagement": item.get("engagement", 0),
                },
            ],
        })
    return topics
