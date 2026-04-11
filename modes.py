"""모드 설정. 핫토픽 / 보편 주제 모드별 소스·가중치·UI 텍스트 정의."""

from dataclasses import dataclass, field
from functools import partial

from sources import (
    fetch_anthropic_releases,
    fetch_geeknews,
    fetch_github_trending,
    fetch_hacker_news,
    fetch_reddit_claude,
    fetch_reddit_eli5,
    fetch_reddit_eli5_filtered,
    fetch_reddit_localllama,
    fetch_reddit_openai,
    fetch_reddit_programming,
    fetch_reddit_technology,
    fetch_reddit_technology_filtered,
    fetch_youtube_search,
)


@dataclass
class ModeConfig:
    name: str
    label: str
    banner_text: str
    fetchers: dict = field(default_factory=dict)
    scorer_weights: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# 핫토픽 모드 (기존 동작)
# ---------------------------------------------------------------------------

HOT_CONFIG = ModeConfig(
    name="hot",
    label="핫토픽 (트렌딩 AI/개발 주제)",
    banner_text=(
        "[bold]AI & DevTools 핫토픽 파인더[/]\n"
        "AI/LLM, 개발자 도구 트렌드를 수집하여 유튜브 주제를 추천합니다."
    ),
    fetchers={
        "GitHub Trending": fetch_github_trending,
        "Reddit r/ClaudeAI": fetch_reddit_claude,
        "Reddit r/LocalLLaMA": fetch_reddit_localllama,
        "Reddit r/OpenAI": fetch_reddit_openai,
        "Reddit r/programming": fetch_reddit_programming,
        "Hacker News": fetch_hacker_news,
        "YouTube": fetch_youtube_search,
        "GeekNews": fetch_geeknews,
        "Anthropic Releases": fetch_anthropic_releases,
    },
    scorer_weights={
        "eng_multiplier": 0.005,
        "eng_cap": 25,
        "cross_bonus": 10,
        "related_multiplier": 0.005,
        "related_cap": 10,
        "base_score": 15,
    },
)


# ---------------------------------------------------------------------------
# 보편 주제 모드 (비개발자 / 어그로 / 헷갈리는 상식)
# ---------------------------------------------------------------------------

GENERAL_QUERIES_YT = [
    "AI 쉽게 설명", "IT 용어 정리", "AI for beginners",
    "what is AI", "AI vs ML difference", "how LLM works",
    "tech controversy AI", "AI news 2026",
    "cybersecurity explained", "cloud computing explained",
]

GENERAL_QUERIES_HN = [
    "AI explained", "machine learning",
    "internet privacy", "cybersecurity",
    "cloud computing", "software engineering",
    "AI regulation", "tech antitrust",
    "open source", "programming language",
]

GENERAL_KEYWORDS_GN = [
    "ai", "인공지능", "기술", "보안", "프라이버시", "클라우드",
    "스마트폰", "앱", "테크", "it", "디지털", "자동화",
    "로봇", "사이버", "해킹", "개인정보",
]

GENERAL_KEYWORDS_REDDIT = [
    "ai", "artificial intelligence", "machine learning", "llm", "gpt",
    "openai", "google", "apple", "microsoft", "meta", "amazon",
    "claude", "anthropic", "chatbot", "algorithm", "data",
    "privacy", "cybersecurity", "hack", "encryption", "vpn",
    "cloud", "saas", "api", "software", "app", "browser",
    "internet", "wifi", "5g", "smartphone", "chip", "semiconductor",
    "robot", "automation", "self-driving",
    "blockchain", "crypto", "quantum",
    "computer", "cpu", "gpu", "server", "linux", "windows",
    "open source", "programming", "developer", "coding",
]

GENERAL_CONFIG = ModeConfig(
    name="general",
    label="보편 주제 (비개발자도 궁금한 기술 상식)",
    banner_text=(
        "[bold]보편 주제 파인더[/]\n"
        "비개발자도 궁금할 만한 기술/AI 상식 주제를 추천합니다."
    ),
    fetchers={
        "Reddit r/technology": partial(fetch_reddit_technology_filtered, keywords=GENERAL_KEYWORDS_REDDIT),
        "Reddit r/ELI5": partial(fetch_reddit_eli5_filtered, keywords=GENERAL_KEYWORDS_REDDIT),
        "Reddit r/ClaudeAI": fetch_reddit_claude,
        "Reddit r/OpenAI": fetch_reddit_openai,
        "YouTube": partial(fetch_youtube_search, queries=GENERAL_QUERIES_YT),
        "Hacker News": partial(fetch_hacker_news, queries=GENERAL_QUERIES_HN),
        "GeekNews": partial(fetch_geeknews, keywords=GENERAL_KEYWORDS_GN),
    },
    scorer_weights={
        "eng_multiplier": 0.008,
        "eng_cap": 25,
        "cross_bonus": 10,
        "related_multiplier": 0.005,
        "related_cap": 10,
        "base_score": 15,
    },
)

MODES = {"hot": HOT_CONFIG, "general": GENERAL_CONFIG}
