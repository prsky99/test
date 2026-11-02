# 기존 어드민과 리뉴얼 어드민 기능 비교

2026-10-24. 기존 어드민의 21개 최상위 메뉴 전체와 리뉴얼의 메뉴 등록·실제 렌더 모듈·버튼·API 연결을 비교했습니다. 비교 항목은 **62개 업무 묶음**입니다. 버튼 62개 또는 누락 화면 62개라는 뜻이 아닙니다. 개별 항목에서 소스 근거와 격리 브라우저 확인을 구분했습니다.

**앞서 71개 화면 구현 완료라고 설명했지만, 기존 기능의 동등 이관 검증은 충분하지 않았습니다.** 화면 정의와 화면 렌더 검증을 통과한 사실은 기존의 모든 메뉴·조회·변경 동작이 이관됐다는 의미가 아닙니다. 이번 비교에서 실제 누락을 확인했습니다.

## 결제 관리의 현재 위치와 실제 누락

리뉴얼의 `고객·지원 → 결제·정산 기록(U09)`에 결제 조회 화면은 있습니다. 경로는 `/admin/next#/customers/u09`이며 최고관리자 본문/API 권한이 필요합니다. 이 화면은 전체·준비금, 정산, 에이전트 계정, 결제 원장이라는 4개 조회 탭만 제공합니다.

기존의 **수동 충전·지급, 출금·회수, 에스크로 환불, 만료 보류·대기 결제 정리**는 새 UI에서 누락됐습니다. 기존 서버의 POST API는 남아 있지만 새 결제 별칭은 GET만 연결합니다. 기존 계정 원장과 고객 무료 이용 크레딧(U07)은 서로 다른 체계이므로 후자를 대체 기능으로 볼 수 없습니다.

또한 U09 메뉴 정의는 admin에게 보이지만 본문·API는 superadmin만 허용합니다. 이것은 결제 권한을 넓혀 해결할 문제가 아니라 메뉴 표시와 실제 권한을 일치시킬 문제입니다.

## 판정별 비교 항목 수

- 이동·유지: 20개 업무 묶음
- 누락: 16개 업무 묶음
- 부분: 19개 업무 묶음
- 권한 불일치: 1개 업무 묶음
- 제한 변경: 1개 업무 묶음
- 표시 오류: 1개 업무 묶음
- 실행 오류: 1개 업무 묶음
- 기존 문제: 3개 업무 묶음

서버 API가 남아 있다는 이유만으로 이관됐다고 분류하지 않았습니다. 메뉴에서 실제로 갈 수 있는지, 같은 대상 데이터를 다루는지, 같은 조회·변경 요청을 만드는지까지 구분했습니다. 역할에 따른 정상 제한과 의도적으로 달라진 동의·승인 절차는 전부 누락으로 집계하지 않았습니다.

## 먼저 복원·정리할 순서

1. **통합 검색 오류와 재평가 명칭:** X03의 `active is not defined`를 수정하고, C02의 rescan을 실제 대상인 고객 추천 요청 재평가로 설명해야 합니다. 클릭이 무반응인 오류와 실제 영향이 다른 명령 안내부터 고쳐야 합니다.
2. **결제 관리의 동등 이관:** 독립 메뉴 또는 명확한 금융 하위 메뉴를 노출하고, 기존 4개 변경 기능을 최고관리자 권한·원장 단위·금액 검증·명시적 검토·중복 실행 방지와 함께 이관해야 합니다. 기존의 미확인 지표 정상 표시나 단위 혼동을 복사하면 안 됩니다.
3. **기존 전역 워크플로:** 전역/직원/고객 워크플로를 구분해 원래 대상의 AI 생성·수정, 실행·취소, 예약·수신처, 앱·SDK 배포 관리를 연결해야 합니다. 직원 typed 실행·릴리스가 존재한다고 전역 기능을 이관한 것으로 볼 수 없습니다.
4. **운영 진단과 고객 추천 요청:** 오류 원인·호스트·체인별 실패, 실행/전달 복구 조회, 폴백 정책 편집, needs/offers 업무를 복원해야 합니다.
5. **탐색·대량 관리:** AI/RAG 추천, 출처·카테고리·등급·비활성 필터·서버 전체 정렬, 보고서 kind/grade/tag, 보안/감사 결과 필터를 복원해야 합니다.
6. **수집·모델 운영과 편의:** ERC-8004 재시도, 벡터 제한 배치, 기간별 지표, 관리자 시뮬레이터, 테스트 타임아웃·최근 세션 이력과 학습 경로를 보완해야 합니다.

## 기존 메뉴 전체 매핑

### 1. 개요 — 부분 누락·차이

홈에 고정 6시간 지표·24시간 실행 요약. 해당 기간 선택·처리량 시계열 없음 / H01/C03/C04에 일부 합계와 최근 대상만 분산

비교 항목: F09, F10.

### 2. 알아보기 — 부분 누락·차이

동등한 관리자 가이드 메뉴 없음. P06에서 공개 배우기 화면 링크 제공

비교 항목: F11.

### 3. 탐색 — 부분 누락·차이

A01 전체 에이전트에서 이름·주소·프로토콜·상태 검색 / A01의 일반 목록 검색으로 대체. 추천 설명·RAG 호출·동등 조건 없음

비교 항목: F12, F13.

### 4. SNS — 이동·유지

P04 SNS 운영에서 대응. 공식 글 작성·게시·보관은 검토/승인으로 전환

비교 항목: F14.

### 5. 방문 에이전트 — 부분 누락·차이

P02 방문·연락 동의, P03 알림, U06 문의로 분리 / P02에는 방문자 조회·대응만 있으며 동등한 관리자 테스트 채팅 없음

비교 항목: F15, F16.

### 6. 접속자 보안 — 부분 누락·차이

S03 현황, S04 규칙, S01 승인으로 분리. 보안 완화는 승인 경유 / S03은 최근 50개 조회 중심, IP·이벤트 종류 필터 없음

비교 항목: F17, F18.

### 7. 에이전트 등록 — 부분 누락·차이

A06 주소 조사·검토 후 등록 / 고급 JSON으로 일부 값 전달 가능. 전용 폼·최근 직접 등록 영역 없음

비교 항목: F19, F20.

### 8. 에이전트 테스트 — 부분 누락·차이

A03 이름 선택·명세·샘플·공유 검토·단일 실행, 고급 응답 접기 / MCP는 명세 목록 도구 선택, 비MCP는 공통 메시지, timeout_seconds:10 고정 / 최근 결과 한 개 표시와 저장된 보고서 링크만 제공

비교 항목: F21, F22, F23.

### 9. 테스트 결과 — 부분 누락·차이

A04/A05 자동 조회·검색·50개 페이지·상세 / q 검색 위주. 목록은 제목/프로토콜/등급 3열, 상세는 일반 데이터 뷰

비교 항목: F24, F25.

### 10. 워크플로우 — 부분 누락·차이

P05는 공개용 정의·편집·게시, W01은 직원 멤버십 범위 초안/typed 목록 / W03/E01은 비공개 typed 실행. 전역 워크플로의 동일 실행·취소 UI는 없음 / 전역 워크플로의 같은 예약·수신처 관리 UI 없음 / W03은 수동으로 검증된 MCP를 연결하는 편집기. 같은 생성·수정 흐름 없음 / W06/E04/E05는 직원 저장본·typed 배포. 같은 전역 배포 관리 경로 없음 / 전역 composer의 동일 비교·검토 문서 UI 없음 / 18개 직원 전문 패널은 다른 도메인. 해당 전역 흐름 없음 / A07 키·T05 현재 모델 값. 같은 워크플로 연결 패널 없음

비교 항목: F26, F27, F28, F29, F30, F31, F32, F33.

### 11. 구독/크레딧 — 이동·유지

U07 가입·크레딧, U01/U02 고객 상세, S01 승인

비교 항목: F34.

### 12. 워크스페이스 통합관리 — 부분 누락·차이

U01~U08, S01/S05로 업무별 분리 / customers.js의 overview 구현은 남지만 71개 화면 registry가 이를 기본 업무로 연결하지 않음

비교 항목: F35, F36.

### 13. 조직 작업공간 — 이동·유지

W02 직원 작업공간에서 원래 관리 컨트롤러 연결 / W07과 E01~E18에 같은 직원 전문 계열 연결

비교 항목: F37, F38.

### 14. 수집 진행 — 부분 누락·차이

C01/C02 실제 제공자 기록·작업자 신호·접수/완료 분리 / C01은 최근 수집/제공자, C03은 50개 다음 점검 대상 중심

비교 항목: F39, F40.

### 15. 에이전트 — 부분 누락·차이

A01/A02 상세·상태 점검·변경·기록 / q/kind/status 위주. 기본 API는 active=1. 표시된 행 정렬은 전체 정렬과 다름

비교 항목: F41, F42.

### 16. 에러 — 부분 누락·차이

S05는 운영 사고, T03는 로그, C01은 최근 수집으로 분산. 같은 종합 실패 분석 없음 / W04/W05는 최근 50개 platform_operations/attempts 메타데이터. 동일 복구·전달 정보 없음 / T05 서비스 설정과 S01 승인으로 이동 / 전역 폴백 스위치/준비 상태와 범용 입출력 변환은 있으나 같은 정책 편집 UI 없음 / T03는 일반 테이블 보존 정책. 같은 실행 보존 명령 UI 없음 / A02 호출·버전·증거·감사 및 A08 도구·연결 검증

비교 항목: F43, F44, F45, F46, F47, F48.

### 17. 고객 요청 — 부분 누락·차이

U06은 문의/개인정보/수신 해지. needs·offers 목록 없음 / U06 요청 종류 선택과 P03 알림으로 분리 / U06 cancellations는 읽기 전용. 재활성화 동작 없음

비교 항목: F49, F50, F51.

### 18. 관리 — 부분 누락·차이

C02에 실제 작업자 상태·검토 후 요청 / C02에 해당 제어 없음 / C05는 검색 반영 현황 조회. 수동 색인 버튼 없음 / C02 버튼은 게이트웨이 에이전트 재검색. 실제 service.rescan은 활성 needs를 재평가

비교 항목: F52, F53, F54, F55.

### 19. 결제 관리 — 부분 누락·차이

고객·지원 → 결제·정산 기록(U09). 전체·준비금/정산/에이전트 계정/결제 원장 4개 조회 탭 / U09에는 조회 기능만 있고 해당 입력·변경 호출이 없음 / 상태 필터 없음. 계정·서비스 검색과 단순 원장·상세만 제공 / 전체·준비금 탭의 일반 데이터 뷰로 표시. 값의 존재 여부는 실제 응답에 따름 / U09 메뉴 정의는 admin도 허용하지만 본문과 API는 superadmin만 허용

비교 항목: F01, F02, F03, F04, F05, F06, F07, F08.

### 20. 관리자 관리 — 이동·유지

T04 관리자·권한, 일부 변경은 S01 검토 후 적용

비교 항목: F56.

### 21. 관리자 감사 — 부분 누락·차이

S02 관리자 작업 이력, action/user와 페이지 유지 / S02는 action·username 필터만 제공

비교 항목: F57, F58.

## 기능별 상세와 근거

### F01. 결제 관리 / 결제·정산 메뉴와 원장 조회

판정: **이동·유지** · P1

- 기존: 독립 결제 관리 메뉴, 청산·계정·온체인 원장·준비금 탭
- 리뉴얼: 고객·지원 → 결제·정산 기록(U09). 전체·준비금/정산/에이전트 계정/결제 원장 4개 조회 탭
- 영향: 메뉴명·위치 변경으로 찾기 어려움. 상단의 기존 결제·지급·정산 기능을 잃지 않는다는 목적 문구와 조회 전용 구현도 불일치.
- 필요한 조치: 결제 관리를 명확히 노출하고 구독용 고객 크레딧과 분리

근거: [dashboard.html:1020](<저장소>/agent_market/gateway/dashboard.html:1020), [desk.js:12](<저장소>/agent_market/gateway/admin_next/areas/desk.js:12).

### F02. 결제 관리 / 수동 크레딧 충전·지급

판정: **누락** · P0

- 기존: 기존 버튼·입력·POST API 연결
- 리뉴얼: U09에는 조회 기능만 있고 해당 입력·변경 호출이 없음
- 영향: 대상 계정에 수동 지급하는 경로가 없음
- 필요한 조치: 기존 권한·원장 단위·금액 검증을 보존한 검토·결과 확인 UI 이관

근거: [dashboard.html:13354](<저장소>/agent_market/gateway/dashboard.html:13354), [dashboard.py:3552](<저장소>/agent_market/gateway/dashboard.py:3552), [desk.js:12](<저장소>/agent_market/gateway/admin_next/areas/desk.js:12), [workspace_admin_specialists.py:101](<저장소>/agent_market/workspace_admin_specialists.py:101).

### F03. 결제 관리 / 수동 출금·회수

판정: **누락** · P0

- 기존: 기존 버튼·입력·POST API 연결
- 리뉴얼: U09에는 조회 기능만 있고 해당 입력·변경 호출이 없음
- 영향: 대상 계정 회수·출금 입력 및 검토 경로가 없음
- 필요한 조치: 기존 권한·원장 단위·금액 검증을 보존한 검토·결과 확인 UI 이관

근거: [dashboard.html:13387](<저장소>/agent_market/gateway/dashboard.html:13387), [dashboard.py:3574](<저장소>/agent_market/gateway/dashboard.py:3574), [desk.js:12](<저장소>/agent_market/gateway/admin_next/areas/desk.js:12), [workspace_admin_specialists.py:101](<저장소>/agent_market/workspace_admin_specialists.py:101).

### F04. 결제 관리 / 에스크로 환불

판정: **누락** · P0

- 기존: 기존 버튼·입력·POST API 연결
- 리뉴얼: U09에는 조회 기능만 있고 해당 입력·변경 호출이 없음
- 영향: 거래별 환불을 처리할 수 없음
- 필요한 조치: 기존 권한·원장 단위·금액 검증을 보존한 검토·결과 확인 UI 이관

근거: [dashboard.html:13239](<저장소>/agent_market/gateway/dashboard.html:13239), [dashboard.py:3625](<저장소>/agent_market/gateway/dashboard.py:3625), [desk.js:12](<저장소>/agent_market/gateway/admin_next/areas/desk.js:12), [workspace_admin_specialists.py:101](<저장소>/agent_market/workspace_admin_specialists.py:101).

### F05. 결제 관리 / 만료 보류·대기 결제 정리

판정: **누락** · P0

- 기존: 기존 버튼·입력·POST API 연결
- 리뉴얼: U09에는 조회 기능만 있고 해당 입력·변경 호출이 없음
- 영향: 고아 보류·미결제 청소를 요청할 수 없음
- 필요한 조치: 기존 권한·원장 단위·금액 검증을 보존한 검토·결과 확인 UI 이관

근거: [dashboard.html:13253](<저장소>/agent_market/gateway/dashboard.html:13253), [dashboard.py:3597](<저장소>/agent_market/gateway/dashboard.py:3597), [desk.js:12](<저장소>/agent_market/gateway/admin_next/areas/desk.js:12), [workspace_admin_specialists.py:101](<저장소>/agent_market/workspace_admin_specialists.py:101).

### F06. 결제 관리 / 정산·원장 상태 필터와 금액·계정 열

판정: **부분** · P1

- 기존: 상태·규격·최소 잔액 UI, 가용/보류/총액/USD·영수증 열
- 리뉴얼: 상태 필터 없음. 계정·서비스 검색과 단순 원장·상세만 제공
- 영향: 보류·실패·환불건 선별 및 자산 파악의 편의가 축소
- 필요한 조치: 지원 API 조건과 일치하는 필터 및 의미가 분명한 금액 열 복원

근거: [dashboard.html:2652](<저장소>/agent_market/gateway/dashboard.html:2652), [dashboard.html:2702](<저장소>/agent_market/gateway/dashboard.html:2702), [desk.js:18](<저장소>/agent_market/gateway/admin_next/areas/desk.js:18).

### F07. 결제 관리 / 지급준비금·가스·Nonce·RPC 표시

판정: **부분** · P1

- 기존: 전용 대시보드와 지표별 설명·상태 표시
- 리뉴얼: 전체·준비금 탭의 일반 데이터 뷰로 표시. 값의 존재 여부는 실제 응답에 따름
- 영향: 필드가 있어도 실무 지표 확인과 이상 판단이 어려움
- 필요한 조치: 관측 가능한 값만 전용 카드로 구성하고 미확인 상태를 명시

근거: [dashboard.html:13142](<저장소>/agent_market/gateway/dashboard.html:13142), [desk.js:17](<저장소>/agent_market/gateway/admin_next/areas/desk.js:17), [dashboard.py:3492](<저장소>/agent_market/gateway/dashboard.py:3492).

### F08. 결제 관리 / 일반 관리자에게 표시되는 결제 메뉴

판정: **권한 불일치** · P1

- 기존: 최고관리자 대상 결제 관리
- 리뉴얼: U09 메뉴 정의는 admin도 허용하지만 본문과 API는 superadmin만 허용
- 영향: 메뉴를 클릭했는데 사용할 수 없다는 안내만 표시; 격리 브라우저 재현
- 필요한 조치: 결제 메뉴 노출과 서버의 최고관리자 권한을 일치

근거: [screens.js:3](<저장소>/agent_market/gateway/admin_next/core/screens.js:3), [desk.js:13](<저장소>/agent_market/gateway/admin_next/areas/desk.js:13), [workspace_admin_specialists.py:61](<저장소>/agent_market/workspace_admin_specialists.py:61).

### F09. 개요 / 헬스체크 기간별 처리량 그래프

판정: **부분** · P1

- 기존: 6시간·24시간·7일 선택 및 처리량 시계열
- 리뉴얼: 홈에 고정 6시간 지표·24시간 실행 요약. 해당 기간 선택·처리량 시계열 없음
- 영향: 여러 기간의 점검 처리량 변화를 비교하기 어려움
- 필요한 조치: 기존 timeseries 조회를 기간 선택형으로 연결

근거: [dashboard.html:1041](<저장소>/agent_market/gateway/dashboard.html:1041), [dashboard.py:730](<저장소>/agent_market/gateway/dashboard.py:730), [home.js:46](<저장소>/agent_market/gateway/admin_next/areas/home.js:46).

### F10. 개요 / 프로토콜별 독립 레인·카테고리·수명주기 상세 집계

판정: **부분** · P1

- 기존: 헬스 레인·대기열·카테고리·retired 재활성화·온체인 신원 상세
- 리뉴얼: H01/C03/C04에 일부 합계와 최근 대상만 분산
- 영향: 고장난 수집 레인이나 대상 편중을 한눈에 판단하기 어려움
- 필요한 조치: 핵심 운영 상세 지표를 공통 조회 모델에 연결

근거: [dashboard.html:1049](<저장소>/agent_market/gateway/dashboard.html:1049), [collection.js:18](<저장소>/agent_market/gateway/admin_next/areas/collection.js:18), [home.js:54](<저장소>/agent_market/gateway/admin_next/areas/home.js:54).

### F11. 알아보기 / 관리자용 프로토콜 가이드·실제 데이터 예시

판정: **부분** · P2

- 기존: 프로토콜 카드·가이드 목차·실제 에이전트 예시
- 리뉴얼: 동등한 관리자 가이드 메뉴 없음. P06에서 공개 배우기 화면 링크 제공
- 영향: 관리 화면 내 학습·실데이터 예시 접근 축소
- 필요한 조치: 가이드를 관리자 도움말로 명확히 연결

근거: [dashboard.html:1067](<저장소>/agent_market/gateway/dashboard.html:1067), [desk.js:29](<저장소>/agent_market/gateway/admin_next/areas/desk.js:29).

### F12. 탐색 / 이름 기반 에이전트 목록 탐색

판정: **이동·유지** · P2

- 기존: 탐색 결과 및 에이전트 목록
- 리뉴얼: A01 전체 에이전트에서 이름·주소·프로토콜·상태 검색
- 영향: 검색 업무의 위치가 변경됨
- 필요한 조치: 구 메뉴별 새 위치 안내를 제공

근거: [dashboard.html:1070](<저장소>/agent_market/gateway/dashboard.html:1070), [catalog.js:18](<저장소>/agent_market/gateway/admin_next/areas/catalog.js:18).

### F13. 탐색 / AI/RAG 맞춤 추천과 검증·인증 조건

판정: **누락** · P0

- 기존: /rag/ask와 /explore를 통한 추천, 카테고리·검증됨·인증 불필요 조건
- 리뉴얼: A01의 일반 목록 검색으로 대체. 추천 설명·RAG 호출·동등 조건 없음
- 영향: 키워드 일치 목록과 AI 추천의 의미가 다름
- 필요한 조치: AI 추천 업무를 명시적으로 복원하고 추천 근거·조건 검증

근거: [dashboard.html:6192](<저장소>/agent_market/gateway/dashboard.html:6192), [dashboard.html:1076](<저장소>/agent_market/gateway/dashboard.html:1076), [catalog.js:18](<저장소>/agent_market/gateway/admin_next/areas/catalog.js:18).

### F14. SNS / 피드·검색·프로토콜·작성자 필터·상세·게시·보관

판정: **이동·유지** · P2

- 기존: 추천/최신/인기, 필터, 글·댓글·반응·삭제
- 리뉴얼: P04 SNS 운영에서 대응. 공식 글 작성·게시·보관은 검토/승인으로 전환
- 영향: 동작 방식은 바뀌었으나 전부 누락된 메뉴는 아님
- 필요한 조치: 승인 대기와 즉시 반응을 구분해 안내

근거: [dashboard.html:1094](<저장소>/agent_market/gateway/dashboard.html:1094), [public-operations.js:76](<저장소>/agent_market/gateway/admin_next/areas/public-operations.js:76).

### F15. 방문 에이전트 / 방문·연락 동의·대응·목적별 알림 관리

판정: **이동·유지** · P2

- 기존: 방문자/출처/프로토콜/연락 권한 필터와 관리
- 리뉴얼: P02 방문·연락 동의, P03 알림, U06 문의로 분리
- 영향: 단일 화면이 여러 업무로 나뉨
- 필요한 조치: 이전 메뉴에서 새 업무로 연결되는 안내 제공

근거: [dashboard.html:1189](<저장소>/agent_market/gateway/dashboard.html:1189), [public-operations.js:43](<저장소>/agent_market/gateway/admin_next/areas/public-operations.js:43), [public-operations.js:71](<저장소>/agent_market/gateway/admin_next/areas/public-operations.js:71).

### F16. 방문 에이전트 / 관리자 컨시어지 채팅 시뮬레이터

판정: **누락** · P1

- 기존: 프로토콜을 선택해 /visitors/simulate로 전송·대화 초기화
- 리뉴얼: P02에는 방문자 조회·대응만 있으며 동등한 관리자 테스트 채팅 없음
- 영향: 실제 방문과 분리한 추천 대화 검증 불가
- 필요한 조치: 시뮬레이션 출처 표시·별도 검토를 유지한 관리자 테스트 복원

근거: [dashboard.html:6616](<저장소>/agent_market/gateway/dashboard.html:6616), [public-operations.js:43](<저장소>/agent_market/gateway/admin_next/areas/public-operations.js:43).

### F17. 접속자 보안 / IP 규칙·비상 방어·속도 배율·만료 정리

판정: **이동·유지** · P2

- 기존: 차단/허용·비상 방어·배율·만료 규칙 정리
- 리뉴얼: S03 현황, S04 규칙, S01 승인으로 분리. 보안 완화는 승인 경유
- 영향: 위치·승인 절차 변경. 기능 전체 삭제는 아님
- 필요한 조치: JSON 중심 입력을 단계별 폼으로 개선

근거: [dashboard.html:1209](<저장소>/agent_market/gateway/dashboard.html:1209), [public-operations.js:99](<저장소>/agent_market/gateway/admin_next/areas/public-operations.js:99).

### F18. 접속자 보안 / 보안 이벤트 IP·종류 필터

판정: **부분** · P1

- 기존: IP/이벤트 유형 검색
- 리뉴얼: S03은 최근 50개 조회 중심, IP·이벤트 종류 필터 없음
- 영향: 특정 IP·차단 원인 추적이 어려움
- 필요한 조치: 동등 필터·페이지 이동 연결

근거: [dashboard.html:1276](<저장소>/agent_market/gateway/dashboard.html:1276), [security.js:67](<저장소>/agent_market/gateway/admin_next/areas/security.js:67).

### F19. 에이전트 등록 / 주소 조사·등록 정보 편집·등록

판정: **이동·유지** · P2

- 기존: 주소 자동 채움·이름·설명·종류·등록
- 리뉴얼: A06 주소 조사·검토 후 등록
- 영향: 기본 등록 흐름은 존재
- 필요한 조치: 현재 검토 절차 유지

근거: [dashboard.html:1308](<저장소>/agent_market/gateway/dashboard.html:1308), [catalog-tools.js:39](<저장소>/agent_market/gateway/admin_next/areas/catalog-tools.js:39).

### F20. 에이전트 등록 / 가격·네트워크·결제 주소 폼 및 최근 등록

판정: **부분** · P1

- 기존: 구조화된 결제 정보 입력, 초기화, 최근 직접 등록 목록
- 리뉴얼: 고급 JSON으로 일부 값 전달 가능. 전용 폼·최근 직접 등록 영역 없음
- 영향: 등록 자체는 가능해도 입력 난도와 결과 확인 비용 증가
- 필요한 조치: JSON으로 보존된 필드의 선택형 입력과 최근 등록 조회 복원

근거: [dashboard.html:1350](<저장소>/agent_market/gateway/dashboard.html:1350), [dashboard.html:1387](<저장소>/agent_market/gateway/dashboard.html:1387), [catalog-tools.js:41](<저장소>/agent_market/gateway/admin_next/areas/catalog-tools.js:41).

### F21. 에이전트 테스트 / 에이전트 선택·명세·샘플·1회 실행·응답

판정: **이동·유지** · P2

- 기존: MCP/A2A/x402 대상 선택·입력·실행·응답
- 리뉴얼: A03 이름 선택·명세·샘플·공유 검토·단일 실행, 고급 응답 접기
- 영향: 기본 실행 경로 유지. 원시 응답은 접힌 영역으로 이동
- 필요한 조치: 프로토콜별 경계와 실행 동의를 유지

근거: [dashboard.html:1527](<저장소>/agent_market/gateway/dashboard.html:1527), [agent-workbench.js:23](<저장소>/agent_market/gateway/admin_next/areas/agent-workbench.js:23).

### F22. 에이전트 테스트 / 수동 도구명·A2A 스킬·x402 요청·타임아웃 선택

판정: **부분** · P1

- 기존: 직접 도구명/여러 입력 템플릿/A2A 스킬/x402 URL/5~30초 선택
- 리뉴얼: MCP는 명세 목록 도구 선택, 비MCP는 공통 메시지, timeout_seconds:10 고정
- 영향: 고급·프로토콜별 문제 재현과 장기 응답 비교 축소
- 필요한 조치: 지원 동작을 프로토콜별로 복원하고 시간 제한을 명시

근거: [dashboard.html:1459](<저장소>/agent_market/gateway/dashboard.html:1459), [dashboard.html:1520](<저장소>/agent_market/gateway/dashboard.html:1520), [agent-workbench.js:23](<저장소>/agent_market/gateway/admin_next/areas/agent-workbench.js:23).

### F23. 에이전트 테스트 / 최근 테스트 세션 이력·선택·비우기

판정: **누락** · P1

- 기존: 현재 세션의 실행 이력과 이력 비우기
- 리뉴얼: 최근 결과 한 개 표시와 저장된 보고서 링크만 제공
- 영향: 여러 입력의 연속 비교·이전 실행 결과 재선택이 어려움
- 필요한 조치: 브라우저 세션 내 테스트 이력 복원; 저장 보고서와 구분

근거: [dashboard.html:1583](<저장소>/agent_market/gateway/dashboard.html:1583), [agent-workbench.js:23](<저장소>/agent_market/gateway/admin_next/areas/agent-workbench.js:23).

### F24. 테스트 결과 / 보고서 검색·목록·상세·추가 페이지

판정: **이동·유지** · P2

- 기존: 최신 보고서 피드·검색·상세
- 리뉴얼: A04/A05 자동 조회·검색·50개 페이지·상세
- 영향: 리포트 전체가 삭제되거나 사라진 것은 아님
- 필요한 조치: 기존 상세 의미를 유지

근거: [dashboard.html:8391](<저장소>/agent_market/gateway/dashboard.html:8391), [catalog-tools.js:45](<저장소>/agent_market/gateway/admin_next/areas/catalog-tools.js:45).

### F25. 테스트 결과 / 프로토콜·등급·태그 필터와 풍부한 보고서 읽기

판정: **부분** · P1

- 기존: kind/grade/tag 필터·해시태그, 가공된 보고서 상세
- 리뉴얼: q 검색 위주. 목록은 제목/프로토콜/등급 3열, 상세는 일반 데이터 뷰
- 영향: 고품질 결과 선별·태그 탐색·읽기 가독성 축소
- 필요한 조치: 기존 필터와 요약·본문·검증 항목의 구조화 상세 복원

근거: [dashboard.html:1634](<저장소>/agent_market/gateway/dashboard.html:1634), [dashboard.html:1640](<저장소>/agent_market/gateway/dashboard.html:1640), [catalog-tools.js:56](<저장소>/agent_market/gateway/admin_next/areas/catalog-tools.js:56).

### F26. 워크플로우 / 전체 템플릿·팀 워크플로 정의 조회·편집

판정: **부분** · P0

- 기존: 같은 전역 워크플로의 캔버스/템플릿/팀 보기
- 리뉴얼: P05는 공개용 정의·편집·게시, W01은 직원 멤버십 범위 초안/typed 목록
- 영향: 동일 데이터 공간이 아님. 전역 워크플로의 작업 흐름이 분리됨
- 필요한 조치: 전역·직원·고객 워크플로의 종류와 원래 작업 경로를 분리해 복원

근거: [dashboard.html:1746](<저장소>/agent_market/gateway/dashboard.html:1746), [public-operations.js:83](<저장소>/agent_market/gateway/admin_next/areas/public-operations.js:83), [workflow-search.js:11](<저장소>/agent_market/gateway/admin_next/areas/workflow-search.js:11).

### F27. 워크플로우 / 기존 전역 워크플로 직접 실행·이력·취소

판정: **누락** · P0

- 기존: 전역 /workflows/{id}/run, /runs, cancel
- 리뉴얼: W03/E01은 비공개 typed 실행. 전역 워크플로의 동일 실행·취소 UI는 없음
- 영향: 별도 직원 실행기가 원래 실행 기능을 대체하지 못함
- 필요한 조치: 전역 정의에서 실행 검토·이력·취소로 이어지는 동등 경로 복원

근거: [dashboard.py:3420](<저장소>/agent_market/gateway/dashboard.py:3420), [dashboard.py:3446](<저장소>/agent_market/gateway/dashboard.py:3446), [workflow-editor.js:33](<저장소>/agent_market/gateway/admin_next/areas/workflow-editor.js:33).

### F28. 워크플로우 / 기존 예약·반복 실행·결과 수신처 확인

판정: **누락** · P0

- 기존: schedule 편집, destination 등록·검증·삭제
- 리뉴얼: 전역 워크플로의 같은 예약·수신처 관리 UI 없음
- 영향: 기존 예약 업무를 새 어드민에서 관리할 수 없음
- 필요한 조치: 실행·수신 목적 동의를 분리한 기존 예약·수신처 UI 이관

근거: [dashboard.html:11998](<저장소>/agent_market/gateway/dashboard.html:11998), [dashboard.py:3474](<저장소>/agent_market/gateway/dashboard.py:3474), [workflow-editor.js:33](<저장소>/agent_market/gateway/admin_next/areas/workflow-editor.js:33).

### F29. 워크플로우 / AI 생성·수정·검토 후 저장

판정: **누락** · P0

- 기존: /workflows/ai-generate, workflow-composer/save·revise
- 리뉴얼: W03은 수동으로 검증된 MCP를 연결하는 편집기. 같은 생성·수정 흐름 없음
- 영향: AI를 활용하는 핵심 작성 기능이 빠짐
- 필요한 조치: 같은 생성 대상·검증·검토 범위를 연결; 수동 편집기를 동등 이관으로 간주하지 않기

근거: [dashboard.html:10136](<저장소>/agent_market/gateway/dashboard.html:10136), [dashboard.html:10149](<저장소>/agent_market/gateway/dashboard.html:10149), [workflow-editor.js:5](<저장소>/agent_market/gateway/admin_next/areas/workflow-editor.js:5).

### F30. 워크플로우 / 기존 웹앱·SDK 버전별 내보내기·배포 철회

판정: **부분** · P0

- 기존: 전역 워크플로 export-app·v12·연결 SDK 관리
- 리뉴얼: W06/E04/E05는 직원 저장본·typed 배포. 같은 전역 배포 관리 경로 없음
- 영향: 전역과 직원 배포의 대상·권한·버전이 달라 대체 관계가 아님
- 필요한 조치: 기존 전역 배포와 새 직원 릴리스를 명확히 분리하고 원래 관리 경로 복원

근거: [dashboard.html:10528](<저장소>/agent_market/gateway/dashboard.html:10528), [dashboard.py:3048](<저장소>/agent_market/gateway/dashboard.py:3048), [release-selector.js:10](<저장소>/agent_market/gateway/admin_next/areas/release-selector.js:10).

### F31. 워크플로우 / 연결 테스트 비교·입력 출처·검토 문서

판정: **누락** · P1

- 기존: comparison/resolved-input/review-packet·다운로드
- 리뉴얼: 전역 composer의 동일 비교·검토 문서 UI 없음
- 영향: 기존 테스트 비교·검토 자료 생성 불가
- 필요한 조치: 기존 전역 테스트 ID·권한을 유지한 비교·다운로드 이관

근거: [dashboard.html:9585](<저장소>/agent_market/gateway/dashboard.html:9585), [dashboard.html:9683](<저장소>/agent_market/gateway/dashboard.html:9683), [specialists.js:3](<저장소>/agent_market/gateway/admin_next/areas/specialists.js:3).

### F32. 워크플로우 / Controlled pair·공개 연결·연결 SDK 검토

판정: **누락** · P1

- 기존: controlled-pair·workflow-publications·connected SDK 검토/발급
- 리뉴얼: 18개 직원 전문 패널은 다른 도메인. 해당 전역 흐름 없음
- 영향: 동명 배포/품질 패널이 있어도 같은 공개 연결을 관리할 수 없음
- 필요한 조치: 공개 연결의 검토·발급·철회를 별도 관리자 업무로 복원

근거: [dashboard.html:9925](<저장소>/agent_market/gateway/dashboard.html:9925), [dashboard.html:9780](<저장소>/agent_market/gateway/dashboard.html:9780), [specialists.js:3](<저장소>/agent_market/gateway/admin_next/areas/specialists.js:3).

### F33. 워크플로우 / LLM 연동·모델 안내

판정: **부분** · P1

- 기존: LLM 연동 & 모델 패널·모델 이용 작업 연결
- 리뉴얼: A07 키·T05 현재 모델 값. 같은 워크플로 연결 패널 없음
- 영향: 설정 값 확인과 실제 작성 연동 안내가 분리됨
- 필요한 조치: 현재 모델을 사용하는 관리자 작성 흐름과 연결 상태를 표시

근거: [dashboard.html:1750](<저장소>/agent_market/gateway/dashboard.html:1750), [desk.js:32](<저장소>/agent_market/gateway/admin_next/areas/desk.js:32), [connections.js:3](<저장소>/agent_market/gateway/admin_next/areas/connections.js:3).

### F34. 구독/크레딧 / 고객 가입·크레딧 정책·대사·승인 조정

판정: **이동·유지** · P2

- 기존: 고객 Free 가입·크레딧 조회와 통합관리 조정
- 리뉴얼: U07 가입·크레딧, U01/U02 고객 상세, S01 승인
- 영향: 결제/에스크로 원장과 다른 고객 크레딧 체계
- 필요한 조치: U09 금융 크레딧과 이름·단위를 명확히 구분

근거: [dashboard.html:1035](<저장소>/agent_market/gateway/dashboard.html:1035), [customers.js:395](<저장소>/agent_market/gateway/admin_next/areas/customers.js:395).

### F35. 워크스페이스 통합관리 / 고객·조직·지원·승인·운영 사고

판정: **이동·유지** · P2

- 기존: workspace_operations 여러 업무 탭
- 리뉴얼: U01~U08, S01/S05로 업무별 분리
- 영향: 다른 위치에 있어 메뉴가 없어졌다고 보일 수 있음
- 필요한 조치: 기존 통합관리에서 새 업무까지 경로 안내

근거: [dashboard.html:1034](<저장소>/agent_market/gateway/dashboard.html:1034), [customers.js:6](<저장소>/agent_market/gateway/admin_next/areas/customers.js:6), [customer-management.js:30](<저장소>/agent_market/gateway/admin_next/areas/customer-management.js:30).

### F36. 워크스페이스 통합관리 / 전용 통합 개요의 실제 운영 투영·누락 경보

판정: **부분** · P1

- 기존: 운영 현황·이벤트 투영 지연·누락·불확실 결과 경보
- 리뉴얼: customers.js의 overview 구현은 남지만 71개 화면 registry가 이를 기본 업무로 연결하지 않음
- 영향: 코드가 있어도 정상 메뉴에서 개요에 도달하지 못함
- 필요한 조치: U01 기본 고객 목록과 별개로 통합 운영 개요를 다시 노출

근거: [customers.js:8](<저장소>/agent_market/gateway/admin_next/areas/customers.js:8), [screens.js:4](<저장소>/agent_market/gateway/admin_next/core/screens.js:4).

### F37. 조직 작업공간 / 직원 작업공간·구성원·초안·저장본

판정: **이동·유지** · P2

- 기존: workspaces 직원 멤버십·비공개 초안
- 리뉴얼: W02 직원 작업공간에서 원래 관리 컨트롤러 연결
- 영향: 고객 조직 메뉴 U03과 직원 W02를 혼동하기 쉬움
- 필요한 조치: 고객 조직과 직원 작업공간의 목적 차이를 안내

근거: [dashboard.html:1680](<저장소>/agent_market/gateway/dashboard.html:1680), [staff-workspaces.js:3](<저장소>/agent_market/gateway/admin_next/areas/staff-workspaces.js:3).

### F38. 조직 작업공간 / 18개 비공개 전문 관리·실행·릴리스

판정: **이동·유지** · P2

- 기존: 직원 권한 기반 전문 모듈
- 리뉴얼: W07과 E01~E18에 같은 직원 전문 계열 연결
- 영향: 전문 메뉴 전체 누락은 아님. 전역 워크플로와 구분 필요
- 필요한 조치: 기능 대상·현재 멤버십을 명확히 표시

근거: [dashboard.html:1680](<저장소>/agent_market/gateway/dashboard.html:1680), [specialists.js:3](<저장소>/agent_market/gateway/admin_next/areas/specialists.js:3).

### F39. 수집 진행 / 제공자별 최근 수집 결과·접수 작업 상태

판정: **이동·유지** · P2

- 기존: 최근 30회 수집 결과·현재 진행
- 리뉴얼: C01/C02 실제 제공자 기록·작업자 신호·접수/완료 분리
- 영향: 조회와 실행 상태의 구분은 개선됨
- 필요한 조치: 유지하면서 상세 항목 보완

근거: [dashboard.html:2234](<저장소>/agent_market/gateway/dashboard.html:2234), [collection.js:43](<저장소>/agent_market/gateway/admin_next/areas/collection.js:43).

### F40. 수집 진행 / ERC-8004 체인·루프·헬스 대기열 세부 진행

판정: **부분** · P1

- 기존: 체인별 진행, 루프 마지막 결과, 대기열 세부 현황
- 리뉴얼: C01은 최근 수집/제공자, C03은 50개 다음 점검 대상 중심
- 영향: 특정 체인의 실패·정체·루프별 상황 파악 축소
- 필요한 조치: 체인/작업 종류별 상세 진행·마지막 결과 연결

근거: [dashboard.html:2240](<저장소>/agent_market/gateway/dashboard.html:2240), [collection.js:30](<저장소>/agent_market/gateway/admin_next/areas/collection.js:30), [admin_console_operations.py:21](<저장소>/agent_market/admin_console_operations.py:21).

### F41. 에이전트 / 에이전트 상세·상태 확인·비활성/활성

판정: **이동·유지** · P2

- 기존: 목록·상세·단일 점검·활성 변경
- 리뉴얼: A01/A02 상세·상태 점검·변경·기록
- 영향: 기본 관리 동작은 있음
- 필요한 조치: 관리 동작의 검토·이력 유지

근거: [dashboard.html:2246](<저장소>/agent_market/gateway/dashboard.html:2246), [catalog.js:28](<저장소>/agent_market/gateway/admin_next/areas/catalog.js:28).

### F42. 에이전트 / 출처·카테고리·등급·비활성 검색·전체 정렬

판정: **부분** · P0

- 기존: source/category/grade/active/sort 선택
- 리뉴얼: q/kind/status 위주. 기본 API는 active=1. 표시된 행 정렬은 전체 정렬과 다름
- 영향: 비활성 대상을 찾아 복구하거나 대량 데이터를 분류하기 어려움
- 필요한 조치: 필터와 서버 전체 정렬·페이지 상태를 원래 수준으로 복원

근거: [dashboard.html:2261](<저장소>/agent_market/gateway/dashboard.html:2261), [dashboard.html:2262](<저장소>/agent_market/gateway/dashboard.html:2262), [catalog.js:18](<저장소>/agent_market/gateway/admin_next/areas/catalog.js:18), [admin_next.py:33](<저장소>/agent_market/admin_next.py:33).

### F43. 에러 / 실패 원인·호스트·ERC 오류·도구 조사·수집 실패

판정: **누락** · P0

- 기존: /errors 집계와 원인별 표
- 리뉴얼: S05는 운영 사고, T03는 로그, C01은 최근 수집으로 분산. 같은 종합 실패 분석 없음
- 영향: 사고 접수와 실패 원인 진단을 같은 기능으로 볼 수 없음
- 필요한 조치: 전용 오류 분석 메뉴와 원인별 교차 탐색 복원

근거: [dashboard.html:2276](<저장소>/agent_market/gateway/dashboard.html:2276), [dashboard.py:1008](<저장소>/agent_market/gateway/dashboard.py:1008), [security.js:89](<저장소>/agent_market/gateway/admin_next/areas/security.js:89).

### F44. 에러 / 공통 실행 참조 추적·회복/전달 조회

판정: **부분** · P0

- 기존: /observations, wr 실행 복구·전달 상태 상세
- 리뉴얼: W04/W05는 최근 50개 platform_operations/attempts 메타데이터. 동일 복구·전달 정보 없음
- 영향: 실행 상태만으로 미확정 결과와 전달 문제를 진단하기 어려움
- 필요한 조치: 실행 종류별 원래 상세·복구 조회 연결

근거: [dashboard.html:2331](<저장소>/agent_market/gateway/dashboard.html:2331), [dashboard.html:5082](<저장소>/agent_market/gateway/dashboard.html:5082), [execution-log.js:6](<저장소>/agent_market/gateway/admin_next/areas/execution-log.js:6).

### F45. 에러 / 호출·워크플로·전달 중지/재개 스위치

판정: **이동·유지** · P2

- 기존: 실행 제어 패널
- 리뉴얼: T05 서비스 설정과 S01 승인으로 이동
- 영향: 재개 승인 절차는 남아 있음
- 필요한 조치: 변경 영향과 승인 대기를 계속 안내

근거: [dashboard.html:2296](<저장소>/agent_market/gateway/dashboard.html:2296), [gateway.js:78](<저장소>/agent_market/gateway/admin_next/areas/gateway.js:78).

### F46. 에러 / 워크플로별 폴백 정책·Shadow/Canary 설정

판정: **부분** · P0

- 기존: 대상·노드·모드·비율·건수·유효시간·별도 공유 승인
- 리뉴얼: 전역 폴백 스위치/준비 상태와 범용 입출력 변환은 있으나 같은 정책 편집 UI 없음
- 영향: 켜기 버튼이 있어도 적격 정책을 새 화면에서 준비·수정할 수 없음
- 필요한 조치: 정책 편집·Shadow 확인·Canary 전환·공유 재승인 전체 경로 연결

근거: [dashboard.html:2319](<저장소>/agent_market/gateway/dashboard.html:2319), [gateway.js:87](<저장소>/agent_market/gateway/admin_next/areas/gateway.js:87), [io-transforms.js:2](<저장소>/agent_market/gateway/admin_next/areas/io-transforms.js:2).

### F47. 에러 / 워크플로 실행 보존 단일 배치·미확정 보호

판정: **부분** · P1

- 기존: /workflows/maintenance 미리보기·최대 20개 배치 승인
- 리뉴얼: T03는 일반 테이블 보존 정책. 같은 실행 보존 명령 UI 없음
- 영향: 일반 로그 보존과 서명된 실행/전달 보존 정책은 동등하지 않음
- 필요한 조치: 기존 실행 보존 도메인을 별도 연결

근거: [dashboard.html:2326](<저장소>/agent_market/gateway/dashboard.html:2326), [dashboard.html:4988](<저장소>/agent_market/gateway/dashboard.html:4988), [system.js:100](<저장소>/agent_market/gateway/admin_next/areas/system.js:100).

### F48. 에러 / 연결 버전·계약 승인·실행 근거

판정: **이동·유지** · P2

- 기존: 에러 패널의 연결 버전·계약 승인·테스트
- 리뉴얼: A02 호출·버전·증거·감사 및 A08 도구·연결 검증
- 영향: 같은 정보가 다른 업무로 이동
- 필요한 조치: 오류 분석에서 A02/A08로 상호 연결

근거: [dashboard.html:2336](<저장소>/agent_market/gateway/dashboard.html:2336), [connection-review.js:3](<저장소>/agent_market/gateway/admin_next/areas/connection-review.js:3), [insights.js:8](<저장소>/agent_market/gateway/admin_next/areas/insights.js:8).

### F49. 고객 요청 / 에이전트 추천 요청 needs·제안 offers 관리

판정: **누락** · P0

- 기존: watching/active/matched/closed 요청·카테고리·추천 제안 상세
- 리뉴얼: U06은 문의/개인정보/수신 해지. needs·offers 목록 없음
- 영향: 고객 추천 요청과 일반 지원 문의를 혼동해 실제 추천 업무가 빠짐
- 필요한 조치: 추천 요청을 독립 업무로 복원하고 제안·재평가·상태 연결

근거: [dashboard.html:2434](<저장소>/agent_market/gateway/dashboard.html:2434), [dashboard.html:5596](<저장소>/agent_market/gateway/dashboard.html:5596), [customers.js:14](<저장소>/agent_market/gateway/admin_next/areas/customers.js:14).

### F50. 고객 요청 / 문의 답변·개인정보 요청·수신 해지 조회

판정: **이동·유지** · P2

- 기존: 지원 문의/개인정보 권리/해지 목록·상태
- 리뉴얼: U06 요청 종류 선택과 P03 알림으로 분리
- 영향: 일반 지원 요청 관리는 남아 있음
- 필요한 조치: 추천 요청 메뉴와 별도로 유지

근거: [dashboard.html:2452](<저장소>/agent_market/gateway/dashboard.html:2452), [customers.js:20](<저장소>/agent_market/gateway/admin_next/areas/customers.js:20).

### F51. 고객 요청 / 기존 수신 해지 재활성화

판정: **제한 변경** · P1

- 기존: 일부 legacy 해지는 재활성화 버튼, task_updates는 새 신청 안내
- 리뉴얼: U06 cancellations는 읽기 전용. 재활성화 동작 없음
- 영향: 기능 차이는 있으나 새 동의 없이 일괄 복구하면 안 됨
- 필요한 조치: 목적별 현재 동의·주소 검증을 확인해 허용된 재신청/재개만 설계

근거: [dashboard.html:5540](<저장소>/agent_market/gateway/dashboard.html:5540), [customers.js:88](<저장소>/agent_market/gateway/admin_next/areas/customers.js:88).

### F52. 관리 / 수집 중지/재개·증분/전체 실행

판정: **이동·유지** · P2

- 기존: pause/resume/crawl/full 버튼
- 리뉴얼: C02에 실제 작업자 상태·검토 후 요청
- 영향: 기본 수집 제어는 있음
- 필요한 조치: 유지

근거: [dashboard.html:2550](<저장소>/agent_market/gateway/dashboard.html:2550), [collection.js:38](<저장소>/agent_market/gateway/admin_next/areas/collection.js:38).

### F53. 관리 / ERC-8004 등록 파일 실패 재시도

판정: **누락** · P1

- 기존: /actions/erc8004-retry 명령
- 리뉴얼: C02에 해당 제어 없음
- 영향: 실패 등록 파일의 수동 복구 경로 없음
- 필요한 조치: 기존 작업자 큐·중복 방지와 연결

근거: [dashboard.html:2554](<저장소>/agent_market/gateway/dashboard.html:2554), [dashboard.py:1846](<저장소>/agent_market/gateway/dashboard.py:1846), [collection.js:4](<저장소>/agent_market/gateway/admin_next/areas/collection.js:4).

### F54. 관리 / 수동 벡터 배치 색인

판정: **누락** · P1

- 기존: /rag/index 배치 100개 실행
- 리뉴얼: C05는 검색 반영 현황 조회. 수동 색인 버튼 없음
- 영향: 자동 작업 이상 시 관리자가 제한된 색인을 요청할 수 없음
- 필요한 조치: 현재 PostgreSQL/pgvector 작업자를 대상으로 제한 배치·상태 확인 연결

근거: [dashboard.html:2560](<저장소>/agent_market/gateway/dashboard.html:2560), [dashboard.py:1306](<저장소>/agent_market/gateway/dashboard.py:1306), [collection.js:25](<저장소>/agent_market/gateway/admin_next/areas/collection.js:25).

### F55. 관리 / 고객 요청 재평가 rescan의 의미 표시

판정: **표시 오류** · P0

- 기존: 버튼은 고객 요청 재평가, 더 좋은 에이전트 찾아 재소개
- 리뉴얼: C02 버튼은 게이트웨이 에이전트 재검색. 실제 service.rescan은 활성 needs를 재평가
- 영향: 수집/헬스 재검사로 오해할 수 있고 추천 제안·조건부 알림 영향이 있음
- 필요한 조치: 실제 처리 대상과 외부 영향에 맞는 이름·검토 안내로 복구

근거: [dashboard.html:2553](<저장소>/agent_market/gateway/dashboard.html:2553), [collection.js:37](<저장소>/agent_market/gateway/admin_next/areas/collection.js:37), [service.py:194](<저장소>/agent_market/gateway/service.py:194).

### F56. 관리자 관리 / 생성·수정·역할·비밀번호 초기화·비활성

판정: **이동·유지** · P2

- 기존: 기존 관리자 관리
- 리뉴얼: T04 관리자·권한, 일부 변경은 S01 검토 후 적용
- 영향: 기본 계정 관리는 남아 있음
- 필요한 조치: 새 권한·세션 철회 경계 유지

근거: [dashboard.html:2867](<저장소>/agent_market/gateway/dashboard.html:2867), [admin-accounts.js:2](<저장소>/agent_market/gateway/admin_next/areas/admin-accounts.js:2).

### F57. 관리자 감사 / 관리자·작업 검색 및 감사 목록

판정: **이동·유지** · P2

- 기존: action/user/status 검색·페이지
- 리뉴얼: S02 관리자 작업 이력, action/user와 페이지 유지
- 영향: 주요 감사 조회는 남아 있음
- 필요한 조치: 유지

근거: [dashboard.html:2908](<저장소>/agent_market/gateway/dashboard.html:2908), [security.js:37](<저장소>/agent_market/gateway/admin_next/areas/security.js:37).

### F58. 관리자 감사 / 감사 성공/실패 결과 필터

판정: **부분** · P1

- 기존: SUCCESS/FAILED/전체 선택
- 리뉴얼: S02는 action·username 필터만 제공
- 영향: 실패한 변경·로그인을 선별하기 어려움
- 필요한 조치: status 필터와 현재 조건 보존 복원

근거: [dashboard.html:2938](<저장소>/agent_market/gateway/dashboard.html:2938), [security.js:6](<저장소>/agent_market/gateway/admin_next/areas/security.js:6).

### F59. 공통 / 통합 이름 검색 실행

판정: **실행 오류** · P0

- 기존: 기존 개별 업무 검색 사용
- 리뉴얼: X03의 agent/workflow/customer 검색이 finance 내부 변수 active를 참조
- 영향: ReferenceError: active is not defined. 격리 브라우저에서 검색 후 이동하지 않음
- 필요한 조치: 범위 밖 변수 참조 제거 및 세 대상별 검색 후 화면 변화 회귀 검사

근거: [desk.js:36](<저장소>/agent_market/gateway/admin_next/areas/desk.js:36).

### F60. 기존 결제의 문제 / 기존 결제 필터와 API 인자 불일치

판정: **기존 문제** · P1

- 기존: clearing은 q, accounts는 min_balance, ledger는 scheme를 전달
- 리뉴얼: 기존 서버는 각각 account_id, q만/최소잔액 없음, service_name를 지원
- 영향: 옛 필터가 모두 동작했다고 가정하고 복사하면 오류를 그대로 가져옴
- 필요한 조치: 요청·응답 계약을 일치시키며 실제 필터 결과를 검증

근거: [dashboard.html:12976](<저장소>/agent_market/gateway/dashboard.html:12976), [dashboard.html:13047](<저장소>/agent_market/gateway/dashboard.html:13047), [dashboard.html:2749](<저장소>/agent_market/gateway/dashboard.html:2749), [dashboard.py:3543](<저장소>/agent_market/gateway/dashboard.py:3543), [dashboard.py:3548](<저장소>/agent_market/gateway/dashboard.py:3548), [dashboard.py:3536](<저장소>/agent_market/gateway/dashboard.py:3536).

### F61. 기존 결제의 문제 / 부재 데이터를 HEALTHY·100%로 표시

판정: **기존 문제** · P0

- 기존: reserve_audit가 없어도 HEALTHY/100%+, SLA 누락 시 100%로 표시
- 리뉴얼: 새 화면이 이를 그대로 계승하지는 않지만 지표 복원 시 주의 필요
- 영향: 실제 준비금/SLA 근거 없는 정상 판정 위험
- 필요한 조치: 미지원·미확인·오류와 정상 값을 구분

근거: [dashboard.html:12942](<저장소>/agent_market/gateway/dashboard.html:12942), [dashboard.html:12939](<저장소>/agent_market/gateway/dashboard.html:12939), [dashboard.py:3501](<저장소>/agent_market/gateway/dashboard.py:3501).

### F62. 기존 결제의 문제 / 고객 무료 크레딧과 금전성 원장 단위 혼동

판정: **기존 문제** · P0

- 기존: 금융 UI는 Credits 및 0.001 USD 환산. amount_credits를 전달
- 리뉴얼: 서버는 amount_credits도 micro-USDC 정수로 처리. U07 고객 크레딧은 별도 체계
- 영향: 같은 크레딧이라는 단어로 금액/고객 이용권을 혼동할 위험
- 필요한 조치: 원장별 단위 정의·환산·금액 미리보기·감사 값 일치부터 검증

근거: [dashboard.html:13191](<저장소>/agent_market/gateway/dashboard.html:13191), [dashboard.py:3556](<저장소>/agent_market/gateway/dashboard.py:3556), [store.py:1300](<저장소>/agent_market/gateway/store.py:1300).

## 확인 방법과 한계

- 소스 비교: 기존 dashboard.html의 메뉴 21개와 정적 입력·버튼을 추출했습니다. 동적으로 생성되는 거래 행·모달 동작은 해당 핸들러와 기존 API도 대조했습니다. 새 메뉴 registry, module dispatch, 도달 가능한 컨트롤러와 별칭 API까지 확인했습니다.
- 격리 브라우저: 실제 대시보드 앱·임시 저장소로 결제 U09 조회 전용, admin 메뉴/본문 권한 불일치, X03 통합 검색 ReferenceError를 재현했습니다. 검사 1개에서 위 3개 상황을 확인했습니다. 결과는 browser-probes.json입니다.
- 전역 워크플로와 직원·고객 워크스페이스는 서로 다른 대상·멤버십·실행/배포 권한을 사용합니다. 비슷한 이름의 화면을 대체 기능으로 간주하지 않았습니다.
- 기존 모든 버튼이 실제 운영에서 정상 동작했음을 검증한 것은 아닙니다. 특히 기존 결제의 무효한 필터·미확인 정상 표시·단위 불일치는 별도 기존 문제 3개 업무 묶음으로 분리했습니다.
- 실제 결제·환불·외부 전송·수집을 실행하거나 운영 데이터를 변경하지 않았습니다. 이번 작업은 비교 결과 정리이며 제품 소스 수정·배포는 수행하지 않았습니다.

캡처: [최고관리자 결제 조회 화면](<저장소>/reports/admin-legacy-renewal-comparison-2026-10-24/renewal-finance-readonly.png), [일반 관리자 메뉴/본문 불일치](<저장소>/reports/admin-legacy-renewal-comparison-2026-10-24/renewal-finance-role-mismatch.png), [검색 오류 재현 화면](<저장소>/reports/admin-legacy-renewal-comparison-2026-10-24/renewal-global-search-error.png).

기계 판독용: [comparison.json](<저장소>/reports/admin-legacy-renewal-comparison-2026-10-24/comparison.json). 이 자료의 항목 수는 구현 완료율이나 운영 성공률이 아닙니다.
