"""모드 설정. 섹터 모드별 소스·UI 텍스트 정의."""

from dataclasses import dataclass, field

from sources import (
    fetch_anthropic_releases,
    fetch_geeknews,
    fetch_github_trending,
    fetch_hacker_news,
    fetch_reddit_claude,
    fetch_reddit_localllama,
    fetch_reddit_openai,
    fetch_reddit_programming,
    fetch_youtube_search,
)


@dataclass
class ModeConfig:
    name: str
    label: str
    banner_text: str
    fetchers: dict = field(default_factory=dict)
    scorer_weights: dict = field(default_factory=dict)
    pipeline_config: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# 섹터 모드 (기존 핫토픽 모드 대체)
# ---------------------------------------------------------------------------

SECTOR_CONFIG = ModeConfig(
    name="sector",
    label="섹터별 핫토픽",
    banner_text=(
        "[bold]섹터별 핫토픽 파인더[/]\n"
        "7개 섹터 × 5개 = 35개 주제 (Claude / 에이전트 / 로컬LLM / AI인프라 / 트렌딩 / 공식뉴스·블로그)"
    ),
    fetchers={
        "Anthropic Releases": fetch_anthropic_releases,
        "GitHub Trending": fetch_github_trending,
        "Reddit r/ClaudeAI": fetch_reddit_claude,
        "Reddit r/LocalLLaMA": fetch_reddit_localllama,
        "Reddit r/OpenAI": fetch_reddit_openai,
        "Reddit r/programming": fetch_reddit_programming,
        "Hacker News": fetch_hacker_news,
        "YouTube": fetch_youtube_search,
        "GeekNews": fetch_geeknews,
    },
    scorer_weights={},
    pipeline_config={},
)


# "hot"은 섹터 모드의 backward-compat alias (기존 CLI/CI 호환).
MODES = {
    "sector": SECTOR_CONFIG,
    "hot": SECTOR_CONFIG,
}
