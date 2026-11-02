# 사용자 재시작 후 재점검

2026-10-25. 서버·제품 소스·운영 설정은 이 점검에서 변경하지 않았다. 신규 경로의 반영 확인과 앞서 재현한 설계 결함의 재확인을 수행했다.

## 운영 반영: 확인 완료

로컬 프론트엔드(8400)와 공개 `https://agentconcierge.biz`에서 모두 다음을 확인했다.

- 홈: 200.
- `/skill.md`, `/.well-known/skill.md`: 200. 스킬 문서는 Markdown이며 ETag가 있다. `/skill.md`의 조건부 GET은 304.
- `/.well-known/agent-entry.json`: 200. `interfaces.skill=/skill.md`와 재방문 정책 존재.
- `/api/agent/v1/badge/999999999.svg`: 200, SVG, Unverified. 없는 리소스를 검증 완료로 표시하지 않음.
- `/api/agent/v1/resume` 무토큰 요청: 401. 기대한 보호 동작.

`live-get-results.json`은 12개 GET 점검 결과다. 스킬 별칭의 공개 단건 응답에서 약 6.28초가 관측됐다. 로컬은 약 6ms였으며, 공개 관측에는 네트워크·프록시가 포함된다. 반복적인 서버 지연이나 운영 SLA 충족 여부는 이 한 번으로 단정하지 않는다.

## 합성 방문자의 실제 검색·재방문

실제 고객 계정 대신 합성 방문자로 공개 `/chat`에 weather forecast를 질문했다.

- 채팅 200, 약 1.81초.
- A2A 3개 추천, 추천 주소는 모두 관리형 게이트웨이.
- 토큰을 메모리에서만 사용한 인증된 resume 200, context_ready.
- 실제 제공자 호출·워크플로우 실행·고객 크레딧 사용 없음.

토큰은 로그·JSON 결과 파일에 저장하지 않았다. 결과는 `live-session-results.json`에 있다.

## 공개 resume의 추가 조건부 응답 문제

공개 resume에서는 동일한 ETag를 다시 보내도 **304 대신 200**이 반환됐다. 재확인 결과는 다음과 같다(`conditional-details.json`).

- 공개 gzip 응답의 ETag는 `W/`로 시작하는 약한 ETag였다.
- 그 값을 그대로 `If-None-Match`로 재전송했다.
- 응답은 200이며, 해석한 JSON 본문과 ETag 값은 첫 응답과 완전히 같았다.
- 압축을 끈 요청에 약한 ETag를 보내도 200이었다.

`agent_entry.py`는 If-None-Match를 자체 생성한 강한 태그와 문자열로만 비교한다. 따라서 중간 계층이 약한 ETag를 반환하는 공개 경로에서 조건부 요청 최적화가 동작하지 않는다. 약한 비교와 태그 목록 등 HTTP 조건부 요청 의미를 처리하는 공통 함수를 사용해야 한다. 기존 F03의 계약 변경 시 잘못된 304와는 다른 방향의 문제이며, 같은 ETag 개선 작업에 포함한다. 참고: https://www.rfc-editor.org/rfc/rfc9110.html#name-if-none-match

## 기존 설계 결함: 미해결

- 설계 경계 검사 **23건 중 6건 통과, 17건 실패**. 앞선 배지 판정·후속 안전/프로토콜 필터·계약 변경 ETag·프리페치 500·복구 독립성/범위·누락 응답 계약 등이 그대로 재현된다.
- 영향받는 기존 discovery 회귀 **6건 통과**.
- 콘텐츠 **267파일, 위반 0건**.
- 화면·생성 HTML/JavaScript는 앞선 감사와 동일해 기존 브라우저 27건 결과를 재사용했다. 이번 재점검에서 브라우저 27건을 새로 실행했다고 주장하지 않는다.

처음 감사와 비교해 `agent_entry.py`와 `front.py`가 바뀌었으나, 현재 배지/재방문/후속 추천/실패 복구 경계는 수정되지 않았다. 새 경로의 방문 집계 등과 결함 수정을 구분해야 한다.

**판정: 신규 기능의 운영 반영은 완료됐으나 설계 전체 합격 상태는 아니다.** 기존 보고서의 권장 수정 순서를 유지하고, ETag 수정에 공개 경로의 약한 ETag 재검증을 포함한다. 단순 재시작을 반복할 이유는 없으며 먼저 해당 소스 결함을 수정해야 한다.

증거: `validation-summary.json`, `audit-results.xml`, `audit-cases.log`, `discovery-results.xml`, `discovery-tests.log`, `content-policy.log`, `live-get-results.json`, `live-session-results.json`, `conditional-details.json`.
