# v1.40 restart follow-up — 2026-10-19 KST

사용자의 재시작·관리자 새로고침 후 로컬 읽기 전용 기능 확인 **38/38개가 통과**했다. 승인된700개 소스 입력은 변경·누락0이다. 제품 소스 수정이나 추가 재시작은 없다.

- 상태 응답과 관리자 페이지가 정상 반환됐다.
- 기존5개·신규4개의 관리자 JavaScript가 현재 파일과 바이트 단위로 일치했고, HTML의 현재 CSP nonce도 일치했다.
- 최초 Workspace 표시 보정 코드가 제공 중인 관리자 HTML에 포함됐다.
- 신규 typed 증거·연구·단일 admission·protocol API를 포함한15개 비공개 GET이 미인증 접근을401로 차단했다.
- 공개 고객 로그인·Workspace와 private receiver 경로의 보류 상태, 공개 HTML의 영어·메타데이터·CSP를 확인했다.

이 결과는 로그인한 관리자 기능 실행, 실제 Google/GitHub·제공자·수신처/Push·운영 DR·결제의 수용이 아니다. 인증정보를 읽거나 실행·발송 명령을 보내지 않았다. 운영 DB 직접 변경·서버 제어0이며 일반 요청 로그는 생성될 수 있다. 기존1,313개 회귀는 반복하지 않았다.

## 성능 관찰 — 미해결

브라우저 HTML 요청은 첫 시도에서 **12초 ReadTimeout**, 더 긴 제한의 후속 확인에서 **12.998초 후200**을 보였다. 따라서 기능 확인 통과를 전체 성능 정상으로 해석하지 않는다. 성능 SLA나 지연 분포를 측정한 결과도 아니다.

공개 루트의 기본 `Accept: */*` 응답은 의도된 머신 discovery JSON이다. 초기 메타데이터 검사에서 이를 HTML로 가정한 부분은 검사 조건의 문제였으며, 원시 초기 기록을 보존하고 `Accept: text/html` 확인으로 보정했다. 이미 통과한37개 조건은 반복하지 않았다.

소스상 HTML 응답은 overview·검증된 Explore·Insights·템플릿·예제를 포함한 전체 bootstrap 준비를 기다린다. prewarm/cache lock 대기, 현재 증거 조건의 집계 및 카드별 재검증이 지연 가능한 경계다. 운영 DB에 직접 접속하거나 단계별 계측을 하지 않았으므로 특정 SQL을 원인으로 확정하지 않는다.

다음 성능 확인은 기존 **POST139R-06**에서 격리된 대표 크기 fixture로 cold/warm 단계별 시간·SQL 수를 측정하고, 확인된 원인만 보완한다. 현재 권한·증거·보고서 subject 검증을 완화하지 않는다. 새 로드맵이나 반복 재개발 항목은 만들지 않았다.

근거: [최종 읽기 결과](post-restart-readonly.json), [초기 협상 진단](post-restart-readonly-initial.json), [HTML 지연 관찰](post-restart-html-diagnostic.json).
