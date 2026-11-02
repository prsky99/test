# Agent Concierge v1.41 — bounded implementation and verification

2026-10-19 · 선택된 구현 범위를 소스 고정·통합 검증했다. **전체 2차 고도화 완료나 실제 운영 수용을 의미하지 않는다.**

후속 재시작 점검은 [별도 기록](POST_RESTART_VERIFICATION.md)에 구분했다. 읽기 전용46/46 및 추가 변경의 고유270개 영향 회귀를 확인했지만, 실제 서버는 이전 HTML 코드를 반환하고 동시 수정도 계속됐다. 아래2,206개는 수용 당시 고정 snapshot의 결과이며 현재 전체 소스의 승인으로 확장하지 않는다.

최종 결과는 **142개 영향 모듈, 고유 2,206개 통과, 실패·오류·skip 0건**이다. 최종 소스 입력 957개에서 예상하지 않은 변경은 없었다. 최초 실행과 수정 후 실행을 모듈 단위로 교체해 계산했으며, 과거 1,313개나 컴포넌트 재실행·중첩 native 계약을 더하지 않았다.

- [최종 검증 원본](verification.json)
- [중복 제거 결과](accepted-summary.json) · [개별 최종 테스트](accepted-cases.json)
- [수용 소스 SHA-256](accepted-source-snapshot.json)
- [단일 후속 작업 순서](../../docs/REMAINING_WORK_BATCHES.md)

## 권장 9개 작업에서 반영한 범위

1. **정확성·관리자 흐름·CI:** corpus ID와 hash 일치, 보관 manifest 재선택, admission 재검토·재개, replan 변경 비교를 연결했다. 개인정보 요청은 접수와 완료를 분리하고, 완료에 검토 메모와 SHA-256 증거 참조를 요구한다. 중앙 검토 모달은 목록 자동 갱신 중에도 유지된다. 공통 CI 선택은 280개 모듈, 4×70개 분할이며 필수 23개 누락을 실행 전에 차단한다. Hosted CI 실행 수용은 별도다.
2. **초기 응답·저장소:** 초기 HTML은 카탈로그 계산을 제한 시간만 기다리고 기존 API로 내용을 채운다. 일회성 작업·프로세스 슬롯·inline 크기를 제한하면서 현재 실패·버전·권한 검사를 유지했다. 비동기 템플릿 로딩에서도 Daily Tech 기본 선택과 저장한 캔버스를 보존했다. PostgreSQL caller-owned 워커와 제한된 writer binding/rollback 계약을 추가했다. 전체 서버 전환·HA를 완료한 것은 아니다.
3. **비공개 조립:** cached graph 생성 전 typed 설정을 받는 builder와 고객/수신기 ASGI 앱, 공통 worker lifecycle을 연결했다. 정확한 HTTPS origin과 허용 호스트를 요구하며 listener를 실행하거나 운영 설정을 자동 발견하지 않는다.
4. **운영 증거 승인:** 기존 증거 plane에 현재 출처·버전·목적·승인·만료·철회에 묶인 운영 자격 계약을 추가했다. 독립 판정은 트랜잭션 밖에서 준비하고 최종 dispatch는 검증된 로컬 판정만 읽는다. 지정된 독립 평가자/qualifier 없이 운영 자격을 부여하지 않는다.
5. **독립 품질·연구 준비:** 정확한 corpus 식별자, 보관 연구 자료의 재사용·변경·만료·철회와 restore 차단을 검증했다. 합성 시험을 실제 독립 품질·조기 종료 개입 성과로 승격하지 않는다.
6. **고객·알림·SDK:** 고객을 staff로 변환하지 않고 조직 권한으로 draft→snapshot→시험→릴리스→배포·기존 패키지 조회/다운로드·철회를 연결했다. 별도 목적의 metadata-only 전달 grant와 제한된 변경 consumer를 기존 수신/영수증/중복 방지 경로에 연결했다. 실제 비공개 로그인·수신·Push 클릭·SDK 왕복 수용은 미실행이다.
7. **라우팅·신뢰 준비:** circuit의 명시적 제어·현재 증거·승인 probe를 관리자 화면과 연결했다. 기존 Ed25519 receipt 위에 별도 opt-in 공개 앱 factory를 추가했다. 기본 404이고 매 요청마다 정확한 공개 승인·키 게시/철회·HTTPS/host를 검증한다. 일반 공개 앱에는 자동 탑재하지 않았다. 실제 early-stop controller와 운영 개입 평가는 남아 있다.
8. **목적 기반 제안·선택 A2A profile:** 최소한의 공개 목적·승인 후보만 모델에 전달하고, 제안은 검토 후 별도 초안으로 저장한다. 자동 실행하지 않는다. 선택된 private A2A 작업은 명시적 send/poll/cancel, 현재 권한·버전·만료, 암호화된 제한 결과, 중복 전송 차단과 수동 관리자 화면을 제공한다. API 기록은 추후 polling을 자동 수행하지 않는다. session/streaming·범용 고객 DAG·실제 자체 에이전트 성과는 완료 범위가 아니다.
9. **암호·결제 준비:** Base Sepolia USDC exact EIP-3009의 선택된 EOA 서명 profile을 독립 요구 값과 대조하는 offline 검사를 구현했다. 관리자 화면에서 별도 동의 후에만 호출한다. `signature_valid`와 실제 잔고·nonce 소비·chain domain·결제·정산 승인을 구분하며 RPC·서명 생성·broadcast·금융 이벤트를 만들지 않는다. 실제 PSP/facilitator·환불·지급 adapter를 대신하지 않는다.

선택 A2A profile은 [A2A 0.3 specification](https://a2a-protocol.org/v0.3.0/specification/)의 task polling 경로를 기준으로 한다. Offline 암호 검사는 [x402 exact EVM scheme](https://github.com/x402-foundation/x402/blob/main/specs/schemes/exact/scheme_exact_evm.md)의 선택된 EIP-3009 형식만 다룬다. 실제 제공자 적합성 수용은 수행하지 않았다.

## 발견한 문제와 조치

최초 고정 실행은 2,185건 중 실패 7건·준비 오류 2건이었다. 공개 보고서 갱신의 중복 resource 조회를 요청 내 메모로 수정했고, 나머지는 오래된 inline hydration/실행 증거 fixture, 실제 recipe와 불일치한 signals 도구 fixture, 종료 후 제거되는 Future에 의존한 검사, 새 상태 영역과 충돌한 브라우저 선택자를 고쳤다. 수정 후 영향 56개 모듈을 재검증했다.

이후 cached-click 피드백 1건은 180ms 표시를 여러 automation 왕복으로 읽는 타이밍 문제였다. 제품의 표시 시간을 늘리지 않고 실제 클릭 이벤트에서 DOM 표시·접근성·중앙 배치·입력 보존을 확인하도록 고쳤다. 해당 모듈 15개는 새 고정 사본·최소 환경·네트워크 가드에서 다시 통과했다. 최초 실패 자료는 `final/`, 회복 자료는 `recovery/`, 마지막 검사는 `final-check/`에 보존했다.

추가로 PostgreSQL의 JSON 경로 4개를 명시적 native projection으로 교정했다. 실제 임시 PostgreSQL에서 **93개 중첩 계약**과 caller-owned 워커/binding을 확인했다. 고객 authoring·metadata 목적 grant·remote task·qualification·모델 제안의 native 경로도 포함한다. 이 계약 수는 2,206개 pytest 수에 더하지 않는다.

## 성능·보안 검증

115,009개 합성 자원·실행 증거 1,000건·canonical 보고서 200건의 격리 read 측정에서 HTML 응답은 **181.514ms / 29.381ms**, gzip은 **124,559 / 124,950 bytes**였다. 수집 트리거는 임시 시드 중에만 비활성화하고 원래 정의를 복원한 뒤 읽었다. 운영 DB, 수집기 경합, 운영 p95·SLA·RPO/RTO 측정은 아니다. [측정 자료](representative-html.json)

공개 콘텐츠 **87개 파일 위반 0건**, embedded/extracted HTML 일치, SQL catalog **3,238 entries / 205 tables** 정합성을 확인했다. Python 입력 910개 구문 검사와 변경된 JavaScript 구문 검사도 통과했다.

선택한 Python 제품 소스 42개에 Bandit 원시 경고 **124건(High 0 / Medium 86 / Low 38)**이 있었다. 전부 소스와 대조했으며, 확인된 신규 High/Medium 결함은 없었다. SQL 식별자 허용목록·바인드 값과 HTML 오탐 등의 근거를 개별 fingerprint로 남겼고, Low 28건의 예외/기본값 처리 견고성 관찰은 삭제하거나 숨기지 않았다. 새 억제 설정은 추가하지 않았다. [원시 결과](recovery/bandit.json) · [개별 검토](recovery/static-triage.json) · [독립 수정 재검토](remediation-review.json)

격리 Chromium/API 검증은 권한·조직 간 격리·같은 출처·현재 버전·만료/철회/restore·XSS·알 수 없는 결과의 재전송 차단·동의 초기화·금융 데이터 불변을 다룬다. 최종 수용에 사용한 7개 네트워크 가드는 운영 포트와 외부 연결을 허용하지 않았고 차단 시도도 0건이었다. 전체 플랫폼의 취약점 부재를 인증하는 결과는 아니다.

## 남은 범위와 반영

감사 finding 19개 중 선택된 소스 누락 12개와 문서 정합성 1개를 닫았다. 다음 조건부 추가 소스 6개는 완료 처리하지 않았다.

- 전체 PostgreSQL 서버의 지속 cutover/rollback·HA·운영 DR
- 승인 threshold에 묶인 실제 early-stop controller와 개입 평가
- A2A session/streaming과 선택된 단일 도구를 넘어서는 고객 typed authoring
- 독립적인 자체 에이전트 업무 성과·예측 우선순위 profile
- 실제 PSP/facilitator/finality·환불·지급 adapter와 대사
- 독립 증명이 필요한 유일 소유자 신원 복구

실제 Google/GitHub·보호된 `agentconcierge.biz` gateway ingress·독립 corpus/rubric/평가자·검증된 수신처/Push·실제 sandbox도 지정·수용되지 않았다. 같은 POST139R 식별자의 [단일 작업 순서](../../docs/REMAINING_WORK_BATCHES.md)에서 추가 소스와 실제 수용을 구분한다.

**공개 Workspace·광고 전달·실거래는 off다. 운영 서버/DB를 조작하지 않았다.** 이번 묶음의 Python 변경 반영에는 사용자 터미널에서 서버 재시작과 관리자 새로고침이 한 번 필요하다.
