# Chat 재시험 (agentconcierge.biz/#chat)

- **일시:** 2026-10-27
- **비교 대상:** `reports/Chat 자연어 요청 브라우저 테스트.md`(2026-10-26, 개선 14건)
- **방법:**
  - 지난번과 같은 Chromium, 같은 화면(1366×900), 같은 질문 33개를 "Find matches"로 보냈습니다. 질문마다 새 브라우저를 썼습니다.
  - 대화 이어 가기, 키보드, 전송 중 버튼 상태, 시작 버튼, 프로토콜 선택을 다시 확인했습니다.
  - 프로토콜 선택과 속도는 `POST /chat` API로도 확인했습니다.

## 요약
- **14건 결과:** 개선 6건, 일부 개선 4건, 그대로 4건
- **확실히 좋아진 것:**
  - Enter로 전송
  - 시작 버튼이 바로 전송
  - 전송 중 버튼 비활성
  - 사용자가 보낸 말이 "Your request:"로 보임
  - 민감·불가능한 요청에 안내(카드번호 제거, "예약하지 않았음", 로또 불가)
  - 프로토콜 선택이 결과에 반영됨
  - 속도(아래)
- **추천 방식이 바뀌었습니다.** 단어 대신 도구 이름으로 맞춥니다. 번역 → `ai_translate`, 메일 → `send_email`, 비트코인 → `crypto_price`, GitHub → `search_github_issues`가 나와 지난번보다 맞는 경우가 많습니다.
  - 다만 여러 도구를 모아 둔 서비스 하나(Agent Tollgate)가 번역·비트코인·GitHub 세 요청에서 1위를 차지합니다.
  - 서울 날씨는 오히려 나빠졌습니다. 영어로 물으면 스키장 눈 정보, 한국어로 물으면 "Korea Benefits Eligibility"가 나옵니다.
- **남은 문제:**
  - 있는 분야도 "맞는 결과 없음"(7건)
  - 모호한 요청에 되묻지 않음
  - 여러 의도를 한 번에 말하면 0건
  - 내부 용어
  - "Why selected"가 비어 있음

## 속도
| | 지난번(10/26) | 이번(10/27) |
|---|---|---|
| 화면, 중앙값 | 7.3초 | 4.9초 |
| 화면, 최대 | 10.6초 | 6.6초 |
| 화면, 최소 | 3.3초 | 3.3초 |
| `/chat` 응답(브라우저에서 잰 값), 중앙값 | (측정 안 함) | 2.1초 |
| `/chat` 응답, 최대 | | 3.8초 |
| API 직접, 1회차 중앙값 / 최대 | | 1.6초 / 1.8초 |
| API 직접, 같은 질문 2회차 중앙값 | | 0.6초 |

- 화면 시간에는 답이 다 그려졌는지 확인하는 대기(약 2.4초)가 지난번과 똑같이 들어 있습니다. 그래도 7.3초에서 4.9초로 약 2.4초 줄었습니다.
- 같은 질문을 다시 보내면 0.6초로, 이제 캐시가 동작하는 것으로 보입니다.
- 2회차에서 1번 429가 났습니다. 2.5초 간격으로 16번 보냈을 때입니다.
- 33개 중 1번(한국어 서울 날씨)은 502였습니다. 화면은 "The request could not be completed. Your question is kept; try again when ready."로 잘 안내했고, API로 다시 보내니 200이었습니다.

## 14건 재확인

| # | 지난번 문제 | 이번 결과 | 판정 |
|---|---|---|---|
| 1 | 단어 하나에 걸린 추천 | 도구 이름으로 맞춤: 번역 → Agent Tollgate(`ai_translate`), 메일 → Agent Broker(`send_email`), 비트코인 → Agent Tollgate(`crypto_price`), 회의록 → Xenition("Turn a meeting…"). 하지만 서울 날씨(영어) → SnowSure Answer Engine(스키장 눈), 서울 날씨(한국어) → Korea Benefits Eligibility. Agent Tollgate가 서로 다른 세 요청의 1위 | 일부 개선 |
| 2 | 있는 에이전트도 "맞는 결과 없음" | 스페인어 번역은 DePunks TRANSLATOR로 해결. SPF/DKIM, 이미지 생성, PostgreSQL MCP, x402 주식(1센트 미만), 일본어 날씨, 한국어 계약서 번역, 사이트 감시+텔레그램은 여전히 없음. 한국어 주식 시세는 지난번 추천 → 이번 없음 | 그대로 |
| 3 | 대화가 이어지지 않음 | 보낸 말이 "Your request: …"로 4개 모두 보임. 2턴 "only free ones"는 날씨를 이어 받음(Weather & Geo Intel). 3턴 "what about the second one?"은 직전 2번째가 아니라 새 목록(NOAA Weather). 4턴 "how do I connect to it?"은 Peerlace로 맥락을 잃음 | 일부 개선 |
| 4 | 모호·범위 밖 질문에 되묻지 않음 | "make my business better", "What's the capital of France?", "🌧️❓"는 여전히 "No currently verified match". 오타 "wether forcast for londn"은 Mat Web & Data Toolkit의 US weather forecast로 연결(런던과 안 맞음) | 그대로 |
| 5 | 민감한 요청에 안내 없음 | 카드번호: 서버로 보내지 않고 "[Card number removed]"로 바꾼 뒤 "Remove card numbers, passwords and access keys…No action was run." 항공권 예약: "No message or reservation has been made." 로또: "Lottery results cannot be guaranteed." 와이파이 해킹: 여전히 "맞는 결과 없음"만 나오고 거절 이유가 없음 | 개선 |
| 6 | Enter로 보낼 수 없음 | Enter로 전송, Shift+Enter는 줄바꿈 | 개선 |
| 7 | 응답이 느림 | 위 속도 표 | 개선 |
| 8 | 시작 버튼이 입력만 채움 | "Weather forecast"를 누르면 바로 전송(POST 1건) | 개선 |
| 9 | 프로토콜을 골라도 결과가 맞지 않음 | API: x402+weather → x402 날씨 API 3개, A2A+translate → DePunks TRANSLATOR, MCP+github issues → GitHub 도구 3개. 화면에서는 선택이 눌리지만, 앞 추천이 쌓여 있어 어느 것이 새 결과인지 구분하기 어려움 | 개선(API 확인) |
| 10 | 여러 의도를 하나만 처리 | "weather data, a translator and a stock price feed"가 이번엔 0건 | 그대로(조금 나빠짐) |
| 11 | 내부 용어가 보임 | "Selected tool check: Not separately recorded" 13번, "Test report: No published report" 13번. "Recommendation 1 · Latest"는 결과가 없을 때도 붙음(33개 중 32개) | 그대로 |
| 12 | "Why selected"가 단어 나열·원문 조각 | 도구로 맞춘 추천은 "Why selected:" 아래가 **비어 있음**(Agent Tollgate 등). 일부는 제공자 설명 원문 | 일부 개선(형식은 바뀜, 내용 없음) |
| 13 | hi·help에 한 줄 안내뿐 | "Describe the task. I will return up to three relevant agents." 한 줄 그대로 | 그대로 |
| 14 | 전송 중에도 버튼이 눌리는 상태 | 전송 중 비활성, "Finding relevant matches…" 표시 | 개선 |

## 남은 개선 필요 (우선순위 순)
1. **도구 매칭의 쏠림과 날씨 오답(1번)**
   - **집합형 서비스 쏠림:** 여러 도구를 모아 둔 서비스(Agent Tollgate, Mat Web & Data Toolkit)가 도구 하나만 맞아도 1위가 됩니다.
     - 도구가 서비스의 주 기능인지에 가중치를 둡니다. 서비스 설명·카테고리와 맞는지 함께 봅니다.
     - 같은 서비스가 다른 요청에 계속 1위로 나오면 다양성 제한을 겁니다.
   - **날씨 오답:** "Seoul weather" → 스키장 눈, "서울 날씨" → 복지 자격 서비스.
     - 지역명(서울, Tokyo)은 매칭 단어에서 빼고 작업(weather forecast)만 씁니다.
     - 지난번 1위였던 Geocoding & Weather가 왜 빠졌는지 순위 로그로 확인합니다.
2. **"맞는 결과 없음" 7건(2번):** SPF/DKIM, 이미지 생성, PostgreSQL, x402 주식, 일본어 날씨, 한국어 계약서 번역, 사이트 감시. 엄격한 기준으로 0건이면, 기준을 낮춘 후보를 "검증 전" 표시와 함께 보여 줍니다. Explore에는 이 분야 항목이 있습니다.
3. **대화 지시어(3번):**
   - "the second one", "it"은 직전 추천 목록의 순서를 가리키게 합니다.
   - 4턴처럼 맥락을 잃지 않도록, 방문 토큰의 마지막 추천 목록을 이어 씁니다. REST의 `details 2`와 같은 처리입니다.
4. **여러 의도 나누기(10번):** "A, B and C"를 의도별로 나눠 각각 1개씩 추천합니다. 지금은 0건입니다.
5. **"Why selected"(12번):** 비어 있으면 "도구 `ai_translate`가 요청의 '번역'과 맞음"처럼 매칭 근거 한 문장을 채웁니다.
6. **내부 용어(11번):**
   - 기록이 없으면 "Selected tool check / Test report" 줄은 숨깁니다.
   - "Recommendation N · Latest"는 실제 추천이 있을 때만 붙입니다.
7. **되묻기·안내(4, 13번):**
   - 모호한 요청에는 예시를 들어 되묻습니다.
   - 범위 밖 질문에는 "에이전트 추천 서비스"임을 알립니다.
   - 해킹 같은 요청에는 거절 이유를 밝힙니다.
   - hi·help에는 할 수 있는 일 예시 3~4개를 보여 줍니다.
8. **화면에서 새 결과 구분(9번):** 새 추천이 오면 그 블록으로 스크롤하고 강조합니다. 프로토콜을 바꿨으면 블록 머리에 프로토콜을 적습니다.
9. **속도:** 화면 기준 중앙값 4.9초입니다. 서버 응답(약 2초)보다 화면 쪽 처리가 깁니다.
   - 응답이 오면 바로 그리고, 카드 세부(검증 시각 등)는 나중에 채웁니다.
   - 서버는 캐시가 생긴 만큼, 첫 요청의 2초도 Explore 개선 방안(검색어 정규화, 카운트 쿼리 정리)으로 줄일 수 있습니다.
   - `/chat` 한도가 2.5초 간격 16번 정도라 사람이 쓰기에는 충분합니다. 다만 429에는 `Retry-After`를 넣습니다.

## 확인하지 못한 것
- 화면에서 프로토콜을 바꾼 뒤의 결과는 이전 추천과 섞여 정확히 읽지 못했습니다. 그래서 API로 확인했습니다.
- "Calling details", "Get updates for this task"를 누른 뒤의 흐름은 이번에도 확인하지 않았습니다.
