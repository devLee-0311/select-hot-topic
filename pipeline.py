"""섹터 라우팅 → 클러스터 → 정규화 → 스코어링 파이프라인."""

from __future__ import annotations

import re
import time
from collections import defaultdict
from datetime import datetime

from utils import clean_for_compare, similarity

# ── 섹터 정의 ────────────────────────────────────────────────
# 순서가 중요: 첫 매칭 섹터가 승리. 각 섹터는 5개 슬롯씩 배정.

SECTORS: list[tuple[str, dict]] = [
    (
        "anthropic_news",
        {
            "label": "Anthropic 공식 뉴스",
            "emoji": "📰",
            "match_url": "anthropic.com/news",
            "count": 5,
        },
    ),
    (
        "anthropic_blog",
        {
            "label": "Anthropic 공식 블로그",
            "emoji": "📝",
            "match_url": "claude.com/blog",
            "count": 5,
        },
    ),
    (
        "claude_code",
        {
            "label": "Claude Code",
            "emoji": "🧡",
            "include": [
                "claude code", "claude-code", "claudecode", "subagent",
                "sub-agent", "skills", "slash command", "hooks", "mcp",
                "model context protocol", "클로드 코드",
            ],
            "deny": [],
            "count": 5,
        },
    ),
    (
        "agents",
        {
            "label": "에이전트 / 자동화",
            "emoji": "🤖",
            "include": [
                "langgraph", "crewai", "autogen", "autogpt", "agentops",
                "devin", "hermes", "multi-agent", "multi agent", "swarm",
                "agent sdk", "agentic", "browser use", "computer use",
                "tool use", "function calling", "에이전트", "에이전틱",
                "ai agent", "ai agents", "autonomous agent", "agent framework",
                "agent builder", "agent workflow", "workflow agent",
                "langchain", "llamaindex", "llama-index",
                "n8n", "dify", "flowise", "openhands", "smolagents",
                "openai agents", "agents sdk", "pydantic-ai", "pydantic ai",
                "agno", "mastra", "letta", "memgpt", "openai swarm",
            ],
            "deny": ["claude code"],
            "count": 5,
        },
    ),
    (
        "local_llm",
        {
            "label": "로컬 LLM",
            "emoji": "💻",
            "include": [
                "ollama", "lm studio", "llama.cpp", "llamacpp", "llama ",
                "mistral", "deepseek", "qwen", "gguf", "quantiz",
                "gpt4all", "koboldcpp", "textgen", "로컬 llm",
            ],
            "deny": ["anthropic only", "claude-only"],
            "count": 5,
        },
    ),
    (
        "ai_infra",
        {
            "label": "AI 인프라 / 툴링",
            "emoji": "⚙️",
            "include": [
                "codex", "gpt-5", "gpt5", "sora", "chatgpt", "cursor",
                "windsurf", "copilot", "aider", "continue.dev",
                "openrouter", "vercel ai", "openai",
            ],
            "deny": [],
            "count": 5,
        },
    ),
]

SECTORS_BY_KEY: dict[str, dict] = {name: cfg for name, cfg in SECTORS}

# 키워드 기반 섹터 (URL 라우팅이 아닌 섹터) — non-anchor 제외 대상.
KEYWORD_SECTORS = {"claude_code", "agents", "local_llm", "ai_infra"}

# 클러스터 노이즈에서 강제로 제외되는 단어 — generic하지만 섹터 구분에 필수.
# 이 단어들이 SECTOR_CLUSTER_NOISE에 포함되면 클러스터링 신호가 너무 얕아진다.
CLUSTER_NOISE_HARD_EXCLUDE = {
    "agent", "agents", "agentic", "tool", "use", "hooks", "skills",
    "cc", "codex", "mcp",
}


SOURCE_FAMILY = {
    "github_trending": "github",
    "hacker_news": "hackernews",
    "youtube": "youtube",
    "geeknews": "geeknews",
    "anthropic_releases": "anthropic",
}

# Sources that can contribute to cross_source_count and refs, but cannot be anchor items.
# Rationale: YouTube competes directly with user's own YouTube content; GeekNews is 한국
# 애그리게이터라 이미 다른 소스에서 긁어오는 파생 콘텐츠다.
NON_ANCHOR_SOURCES = {"youtube", "geeknews"}

# anthropic_releases 아이템이 cluster boost나 refs로 "끼어들면 안 되는" 섹터들.
# 이유: anthropic_releases는 anthropic_news/anthropic_blog 전용 섹터를 따로 갖는다.
# claude/codex/local_llm 섹터에서 anthropic_releases가 끼면 (a) 같은 공식 글이
# 두 번 노출되는 시각적 중복, (b) cross-source 부스트로 점수가 과도하게 부풀려진다.
NON_OFFICIAL_SECTORS = {"claude_code", "agents", "local_llm", "ai_infra"}
ANTHROPIC_SOURCE_FAMILY = "anthropic"  # _source_family("anthropic_releases")

CROSS_SOURCE_BOOST = {1: 1.0, 2: 1.5, 3: 2.5}
SIMILARITY_THRESHOLD = 0.4

DISPLAY_SCORE_CAP_BY_CROSS = {1: 70, 2: 85, 3: 99, 4: 99, 5: 99}
FRESH_SINGLETON_CAP = 90  # singleton + 신선도(<6h, multiplier>=1.3) 일 때 상한 완화

# 시간 감쇠 스텝 버킷: (max_hours, multiplier).
# 마지막 튜플의 max_hours=None은 "그보다 오래됨"의 기본값을 의미.
RECENCY_BUCKETS: list[tuple[float | None, float]] = [
    (6, 1.30),
    (24, 1.00),
    (72, 0.70),
    (None, 0.40),
]

CLUSTER_SIMILARITY_THRESHOLD = 0.45  # 섹터 노이즈 제거 후 짧아진 문자열용
CLUSTER_MIN_SHARED_KEYWORDS = 1      # 섹터 키워드는 빼고 1개 이상 공유


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
    """섹터 매칭용 검색 텍스트."""
    return f"{item.get('title', '')} {item.get('description', '')} {item.get('url', '')}".lower()


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


# ── 섹터 라우팅 ─────────────────────────────────────────────

def assign_sector(item: dict) -> str | None:
    """아이템을 섹터 키에 매핑. 규칙 순서 준수, 첫 매칭 승리.

    1. source=anthropic_releases + URL에 'anthropic.com/news' → anthropic_news
    2. source=anthropic_releases + URL에 'claude.com/blog' → anthropic_blog
    3. 4개 pillar 순회 (claude_code → agents → local_llm → ai_infra):
       include 키워드 히트 AND deny 키워드 미스 → 해당 pillar
    4. 매칭 없음 → None (제외)
    """
    source = item.get("source", "")
    url = item.get("url", "").lower()

    if source == "anthropic_releases":
        if "anthropic.com/news" in url:
            return "anthropic_news"
        if "claude.com/blog" in url:
            return "anthropic_blog"

    text = _searchable_text(item)
    for name, cfg in SECTORS:
        if name not in KEYWORD_SECTORS:
            continue
        include = cfg.get("include", [])
        deny = cfg.get("deny", [])
        if not any(kw in text for kw in include):
            continue
        if any(dkw in text for dkw in deny):
            continue
        return name
    return None


# ── 클러스터 노이즈 ─────────────────────────────────────────

def _build_sector_cluster_noise() -> frozenset[str]:
    """섹터 라우팅 키워드를 클러스터 신호에서 제외하기 위한 노이즈 셋.

    SECTORS의 include 키워드를 clean_for_compare로 정제 후 토큰 단위로 모은다.
    예: 'claude code' → {'claude', 'code'}, 'gpt-5-codex' → {'gpt-5-codex'}.
    `CLUSTER_NOISE_HARD_EXCLUDE`에 속하는 단어는 섹터 신호로 필수이므로
    노이즈에서 강제로 제외하여 클러스터 신호로 남긴다.
    """
    words: set[str] = set()
    for _, spec in SECTORS:
        for kw in spec.get("include", []):
            cleaned = clean_for_compare(kw)
            words.update(cleaned.split())
    words -= CLUSTER_NOISE_HARD_EXCLUDE
    return frozenset(words)


SECTOR_CLUSTER_NOISE = _build_sector_cluster_noise()


# ── 파이프라인 단계 ──────────────────────────────────────────

def _titles_cluster(a: str, b: str) -> bool:
    """두 제목이 클러스터링 기준을 충족하는지 판정. 섹터 라우팅 키워드는 신호에서 제외.

    두 가지 동시 충족 시 True:
      1. SECTOR_CLUSTER_NOISE를 뺀 공유 단어가 CLUSTER_MIN_SHARED_KEYWORDS개 이상
      2. 노이즈 제거된 문자열 간 similarity가 CLUSTER_SIMILARITY_THRESHOLD 이상
    """
    ca, cb = clean_for_compare(a), clean_for_compare(b)
    if not ca or not cb:
        return False
    words_a = set(ca.split())
    words_b = set(cb.split())
    shared = (words_a & words_b) - SECTOR_CLUSTER_NOISE
    if len(shared) < CLUSTER_MIN_SHARED_KEYWORDS:
        return False
    ca_stripped = " ".join(w for w in ca.split() if w not in SECTOR_CLUSTER_NOISE)
    cb_stripped = " ".join(w for w in cb.split() if w not in SECTOR_CLUSTER_NOISE)
    if not ca_stripped or not cb_stripped:
        return False
    return similarity(ca_stripped, cb_stripped) >= CLUSTER_SIMILARITY_THRESHOLD


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

    for group in groups.values():
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
    """아이템의 게시 후 경과 시간(hours) 계산.

    읽는 필드 우선순위:
      1. YouTube의 `published` 문자열 (e.g. "2 days ago")
      2. `created` / `created_utc` (unix timestamp 또는 ISO 문자열)
      3. `published_at` (Anthropic RSS — datetime 객체 혹은 ISO 문자열)
    """
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

    # published_at (Anthropic RSS) — datetime 혹은 ISO 문자열
    raw = item.get("published_at")
    if raw is not None:
        if isinstance(raw, datetime):
            try:
                return max(0, (now - raw.timestamp()) / 3600)
            except (ValueError, OSError):
                pass
        elif isinstance(raw, (int, float)):
            return max(0, (now - raw) / 3600)
        elif isinstance(raw, str):
            try:
                dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
                return max(0, (now - dt.timestamp()) / 3600)
            except (ValueError, OSError):
                pass

    return None


def _recency_multiplier(item: dict) -> float:
    """시간 버킷에 따른 배수 반환. 타임스탬프 없으면 중립 1.0."""
    hours = _parse_hours_since(item)
    if hours is None:
        return 1.0
    for cap, mult in RECENCY_BUCKETS:
        if cap is None or hours <= cap:
            return mult
    return 0.4


def compute_sector_scores(items: list[dict]) -> list[dict]:
    """섹터 모델 최종 점수 계산. 스텝 버킷 recency multiplier 반영.

    final_score = engagement_normalized × cross_source_boost × recency_multiplier

    - recency_multiplier는 `_recency_multiplier`로 계산. 타임스탬프 없으면 1.0(중립).
    - 디버깅/표시용으로 item["recency_multiplier"]에 배수를 저장.
    """
    for item in items:
        eng_norm = item.get("engagement_normalized", 0.5)
        boost = item.get("cross_source_boost", 1.0)
        rec = _recency_multiplier(item)
        item["recency_multiplier"] = rec
        item["final_score"] = round(eng_norm * boost * rec, 4)
    return items


def run_sector_pipeline(items: list[dict], config: dict | None = None) -> dict:
    """섹터 라우팅 기반 전체 파이프라인.

    1. detect_clusters
    2. normalize_engagement
    3. assign_sector (각 아이템)
    4. 섹터별 클러스터 효과 재조정 — anthropic_releases는 non-official 섹터에서 제외
    5. compute_sector_scores (재조정된 boost 반영)
    6. 섹터별 그룹핑 — 키워드 섹터는 NON_ANCHOR_SOURCES 제외, 점수 내림차순 정렬, count 슬롯으로 자름
    7. cluster_refs 부착 (동일한 섹터 기반 제외 규칙 적용)
    8. max_score 계산

    config 옵션:
      sector_counts: dict[str, int] — 섹터별 기본 5 슬롯 오버라이드
    """
    if config is None:
        config = {}

    sector_counts_override = config.get("sector_counts", {}) or {}

    # 1. 클러스터링
    items, clusters = detect_clusters(items)
    # 2. 정규화
    items = normalize_engagement(items)
    # 3. 섹터 할당 (스코어링 전에 먼저 — per-sector 클러스터 재조정을 위해)
    for item in items:
        item["sector"] = assign_sector(item)

    # 4. 섹터별 클러스터 효과 재조정
    #    anthropic_releases 아이템은 NON_OFFICIAL_SECTORS 소속 아이템의 교차 소스 카운트와
    #    cross_source_boost에 기여하지 않는다. 싱글턴(cluster_id is None)은 영향 없음.
    cluster_map: dict[int, list[dict]] = defaultdict(list)
    for it in items:
        cid = it.get("cluster_id")
        if cid is not None:
            cluster_map[cid].append(it)

    for it in items:
        cid = it.get("cluster_id")
        if cid is None:
            continue
        sector = it.get("sector")
        excluded_families: set[str] = set()
        if sector in NON_OFFICIAL_SECTORS:
            excluded_families.add(ANTHROPIC_SOURCE_FAMILY)
        if not excluded_families:
            continue  # 기존 값 유지
        families = set()
        for m in cluster_map[cid]:
            fam = _source_family(m.get("source", ""))
            if fam in excluded_families:
                continue
            families.add(fam)
        eff_count = max(1, len(families))
        eff_boost = CROSS_SOURCE_BOOST.get(eff_count, 4.0) if eff_count <= 3 else 4.0
        it["cross_source_count"] = eff_count
        it["cross_source_boost"] = eff_boost

    # 5. 스코어링 (재조정된 boost 기준)
    items = compute_sector_scores(items)

    # 6. 섹터별 그룹핑 / 필터링 / 정렬 / 자르기
    sectors_out: dict[str, list[dict]] = {name: [] for name, _ in SECTORS}
    grouped: dict[str, list[dict]] = defaultdict(list)
    for item in items:
        sec = item.get("sector")
        if sec is None:
            continue
        grouped[sec].append(item)

    for name, cfg in SECTORS:
        group = grouped.get(name, [])
        if name in KEYWORD_SECTORS:
            group = [
                it for it in group
                if _source_family(it.get("source", "")) not in NON_ANCHOR_SOURCES
            ]
        group.sort(key=lambda x: x.get("final_score", 0), reverse=True)
        count = sector_counts_override.get(name, cfg.get("count", 5))
        sectors_out[name] = group[:count]

    # 7. cluster_refs 부착
    for name, sector_items in sectors_out.items():
        for it in sector_items:
            cid = it.get("cluster_id")
            if cid is not None and len(cluster_map[cid]) >= 2:
                # NON_ANCHOR_SOURCES(youtube/geeknews)는 anchor는 못 되지만 refs에는
                # 보여줘야 한다 (cross_source_count에도 포함됨). 여기서는 제외하지 않음.
                excluded_families: set[str] = set()
                if name in NON_OFFICIAL_SECTORS:
                    excluded_families.add(ANTHROPIC_SOURCE_FAMILY)
                others = [
                    m for m in cluster_map[cid]
                    if m is not it
                    and _source_family(m.get("source", "")) not in excluded_families
                ]
                others.sort(key=lambda m: _get_raw_engagement(m), reverse=True)
                it["cluster_refs"] = [
                    {
                        "title": m.get("title", ""),
                        "url": m.get("url", ""),
                        "source": m.get("source", ""),
                        "engagement": _get_raw_engagement(m),
                    }
                    for m in others
                ]
            else:
                it["cluster_refs"] = []

    # 8. max_score 계산 (디스플레이 정규화 앵커)
    #    ranking은 여전히 item["final_score"] 기준. 이 값은 표시용 normalization 앵커로만 사용.
    today_max = max((i.get("final_score", 0.0) for i in items), default=1.0) or 1.0
    try:
        from rolling_stats import load_rolling_stats, save_rolling_stats
        samples = load_rolling_stats()
        rolling_max = max((s for _, s in samples), default=today_max)
        max_score = max(today_max, rolling_max * 0.7)
        save_rolling_stats(samples, today_max)
    except Exception:
        max_score = today_max

    return {
        "sectors": sectors_out,
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
        # 신선한 singleton은 상한을 FRESH_SINGLETON_CAP로 완화 (속보 반응성)
        if cross == 1 and item.get("recency_multiplier", 1.0) >= 1.3:
            cap = FRESH_SINGLETON_CAP
        relative = int(item.get("final_score", 0) / max_score * 99) if max_score > 0 else 0
        score = min(cap, relative)

        reasons = [f"{source} 화제 (engagement {int(raw_eng):,})"]
        if cross >= 2:
            reasons.append(f"교차 소스 {cross}곳 언급")
        sector = item.get("sector")
        if sector:
            reasons.append(f"sector:{sector}")

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
