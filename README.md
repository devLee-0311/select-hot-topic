# select-hot-topic

IT/AI 관련 핫토픽을 여러 소스에서 자동 수집하고, 유튜브 영상 주제로 추천해주는 CLI 툴입니다.

## 주요 기능

- **멀티소스 병렬 수집** - 6개 소스에서 동시에 데이터를 가져옵니다
- **자동 스코어링** - engagement 기반 점수 산정 + 교차 소스 언급 보너스
- **중복 방지** - 이력 관리를 통해 이미 다룬 주제는 자동 제외
- **관련 자료 자동 매칭** - 제목 유사도 분석으로 같은 이슈의 다른 소스 자료를 묶어서 제공

## 데이터 소스

| 소스 | 수집 방식 | 필터링 |
|------|----------|--------|
| GitHub Trending | 웹 스크래핑 | AI/Claude 관련 키워드 |
| Reddit r/ClaudeAI | PRAW API 또는 JSON 폴백 | 서브레딧 핫글 |
| Hacker News | Algolia API | Claude/AI 검색 쿼리 |
| YouTube | 검색 결과 파싱 | Claude Code 관련 영상 |
| GeekNews (news.hada.io) | 웹 스크래핑 | AI/Claude 관련 키워드 |
| Anthropic Releases | 웹 스크래핑 | 공식 릴리즈 노트 |

## 설치

```bash
pip install -e .
```

## 환경 변수 (선택)

`.env` 파일에 설정합니다. Reddit API 키가 없어도 JSON 폴백으로 동작합니다.

```env
REDDIT_CLIENT_ID=your_client_id
REDDIT_CLIENT_SECRET=your_client_secret
REDDIT_USER_AGENT=hot-topic-bot/0.1
```

## 사용법

```bash
# 토픽 1개 추천 (기본)
hot-topic

# 토픽 3개 추천
hot-topic -n 3

# 이력 보기
hot-topic --history
```

## 출력 예시

추천된 토픽은 스코어(0~100), 선정 근거, 레퍼런스(출처별 링크 + engagement)를 포함하여 터미널에 표시됩니다. 추천 후 이력에 저장할지 선택할 수 있습니다.

## 스코어링 기준

- **기본 점수**: 20점
- **Engagement 점수**: 원본 engagement x 0.02 (최대 40점)
- **교차 소스 보너스**: 다른 소스에서 관련 자료가 발견될 때 소스당 15점
- **관련 자료 engagement**: 관련 자료의 engagement 합산 x 0.01 (최대 15점)

## 프로젝트 구조

```
select-hot-topic/
├── main.py          # CLI 진입점, 데이터 수집 및 출력
├── scorer.py        # 토픽 스코어링 및 관련 자료 매칭
├── history.py       # 추천 이력 관리 (history.json)
├── pyproject.toml   # 프로젝트 설정 및 의존성
└── sources/         # 데이터 소스 모듈
    ├── github_trending.py
    ├── reddit_claude.py
    ├── hacker_news.py
    ├── youtube_search.py
    ├── geeknews.py
    └── anthropic_releases.py
```

## 의존성

- Python >= 3.10
- requests
- beautifulsoup4
- praw (Reddit API, 선택)
- rich (터미널 UI)
- python-dotenv
