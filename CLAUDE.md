# Select Hot Topic — Project Instructions

## 검색 결과 출력 형식

웹 검색 후 주제를 추천할 때 아래 형식을 따른다. **가장 흥미로운 주제 1개만** 출력한다.

```
### 주제
{주제명}

### 근거
- {왜 이 주제인지, 핫토픽/에버그린 여부, 연관 프로젝트와의 접점 등}

### 레퍼런스
- [제목](URL)
- [제목](URL)
- ...
```

## GitHub Actions (Telegram 알림) 출력 형식

`--format markdown` 모드에서는 위와 동일한 형식을 따르되, **점수가 높은 순으로 3개**를 출력한다. hot/general 모드 각각 3개씩.
