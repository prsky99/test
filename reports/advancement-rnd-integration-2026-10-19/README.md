# R&D source integration — 2026-10-19

현재 제한 소스 묶음 **v1.40**을 구현·통합 검증했다. 기존 **POST139R-01~09**를 유지하며 별도 중복 로드맵이나 실행기·worker·저널·금융 원장을 만들지 않았다. 전체 1~9의 실제 운영 수용이나 2차 고도화 전체 출시를 의미하지 않는다.

최종 근거는 [verification.json](verification.json), [고유 사례 목록](accepted-cases.json), [소스 입력 해시](accepted-source-snapshot.json), [구현 상태](implementation-status.json)다.

[독립 최종 대조](docs-final-review.json)에서 문서/캐시·15개 과제·같은9개 순서·실제 JUnit 출처·소스 해시·미완료 운영 조건의 실질 모순0건을 확인했다.

**재시작 후속:** 사용자 재시작·새로고침 후 읽기 전용38개 조건과 소스700개 일치를 확인했다. 추가 재시작은 필요 없다. 단 공개 홈 HTML의 첫12초 제한 초과·후속약13초 지연은 성능 보완 항목으로 남는다. [최신 반영 확인](post-restart-readonly.md)을 참고한다. 아래는 소스 통합 당시의 기록이다.

## 구현한 범위

- 기존 typed run/step과 목적별 암호화 증거를 연결했다. 원본과 서명 입력 해시가 일치할 때만 입력을 재구성하며 삭제·누락 자료는 미평가로 남긴다.
- 고정 docs/news MR·정확 항목 oracle·manifest·이산 실험 셀과 단계 shadow를 연결했다. 별도 오프라인 producer는 기존 평가 worker로 합성 8쌍/16호출을 실행한다. 실패·unknown·미평가·coverage를 보존한다.
- 단일 admission은 기존 실행기/계량을 사용하며 선택 제공자1·호출1·replacement0, 실행별 동의와 현재 권한 fence를 적용한다. 출력 계약 실패를 성공 계량으로 남기거나 새 snapshot으로 파일럿 정책을 우회하지 못한다.
- 기본 off circuit/probe core는 서명된 현재 관측과 별도 승인된 기존 평가 job을 사용한다. 정확한 MCP adapter의 응답 검증 증거를 원래 job에 바인딩하고 routing/admission이 같은 projection을 읽는다. 자동 API/UI·수집·probe dispatch는 없다.
- 명시적 2–6노드 변경 검토는 새 typed 초안을 만든다. 기존/진행 중 그래프는 바꾸지 않는다. 제한 영어 intent를 지원하며 범용 AI planner로 표현하지 않는다.
- SDK/BFF의 중복 JSON 키·비유한 수·깊이 제한과 최종 PKCE 세션 한도를 보강했다. 공개 SDK1.x를 유지한다.
- 명시 키 기반 offline Ed25519 receipt helper와 TEST_UNIT protocol 대사를 추가했다. 공개 서명 서비스나 실제 EVM/facilitator/AP2/MPP 결제 구현은 아니다. 보고서 생성은 금융 이벤트를 추가하지 않는다.
- 기존 개별 관리자/desktop·중앙 dialog·세션 폐기 경계를 유지하면서 비공개 관리 기능과 고정 nonce 자산을 연결했다. 복원 시 연구/정책/protocol/circuit 권한을 영구 차단하고 서명 이력은 보존한다.

## 통합에서 발견해 해결한 문제

1. 파일럿 출력 검증을 성공 저장/계량 전에 수행하도록 고쳤다. 같은 초안의 새 snapshot과 손상된 서명 locator를 통한 우회도 차단했다.
2. 복원되거나 만료된 평가 job이 호스트 실행 자리를 계속 차지하지 않도록 수정했다. 미확정 업무를 자동 재호출하지 않는다.
3. 직접 `#workspaces` 접속 시 인증과 목록 조회가 성공해도 main 화면이 숨겨지던 문제를 수정했다. 현재 세션의 options/list 성공 후에만 화면을 표시하며 실패·철회·이전 세션의 늦은 응답은 계속 차단한다.
4. admission 보호가 typed version을 legacy snapshot으로 조회해 정상 릴리스를 거부하던 호환성 문제를 수정했다. typed 경로는 이미 서명 검증한 workspace/flow scope를 내부 전달하고 같은 전체 서명 registry 검증을 유지한다. legacy 누락 행 차단도 유지한다.
5. 새 검색 대기열 정리 UPDATE와 현재 claim SELECT의 native SQL 누락을 수정했다. 기존 finite catalog에 각 51개 지원 형태만 등록했다. 입력값은 bind하며 51개 초과 ID·변조 SQL은 계속 거부한다. 실행 SQL 검사나 active/generation/health 필터를 완화하지 않았다.
6. 운영 개선에 따른 보고서 subject·측정 증거 조건을 과거 native 합성 fixture에 반영했다. 새 helper의 읽기 세션·이벤트 참조 형식·서로 독립된 평가 시간 창도 현재 계약에 맞췄다. shared host budget을 늘려 시험을 통과시키지 않았다.

## 검증 결과와 집계

**700개 소스 입력, 영향 78개 모듈의 고유 1,313개 사례 통과. 최종 실패/error/skip0, 최종 동결/작업 소스 변경0.**

- 먼저 동결한 76모듈/1,278개에서 native2건이 실패했다. 수정 뒤 영향14모듈/174개를 검증했고, 남은 native helper 사례만 별도 재검증했다. 최종 고유 사례는 마지막 결과로 치환했다. 중복 실행·진단·구성요소 검사와 이전536개 결과는 더하지 않았다.
- 실제 disposable Unix-socket PostgreSQL에서 application 내부 계약 **80개**를 검증했다. 이는 pytest 사례에 추가하지 않는다. [native 결과](native/application-contracts.json).
- 고정 SQL 목록 **3,153항목**, 정규화 등록 **3,106문**, 테이블 **202개**가 현재 소스와 일치했다. 전체 application/운영 이전 준비 판정은 여전히 false다.
- 공개 콘텐츠 **81개 파일 위반0**, `front.py.HTML`과 `extracted_html.txt` 일치. 공개 Chat·노출·게이트웨이·보고서·Home·관리자 세션/권한·API·브라우저·SDK·복원 회귀를 영향 범위에서 검증했다.
- 최소 환경과 mock/loopback fixture만 사용했다. 검사한 Python network guard의 금지 대상 접속0, 실제 제공자/운영 DB/실제 알림·금융 거래0이다. Chromium 경로는 fixture routing을 사용했다.

기록: [초기 통합](final/summary.json), [영향 재검증](recovery/summary.json), [최종 native](native-verified/summary.json). `frozen/`의 이전 중단 진단과 `native-final/`, `native-closure/`의 helper 실패도 삭제하지 않았으며 최종 성공 근거와 구분한다.

## 보안 검토

제품/지원 경로 Python **30개**의 Bandit 원시 경고는 **High0/Medium3/Low3**이다. 두 낮음 경고는 숫자 성공 counter, 세 중간 경고는 고정 내부 table/predicate SQL, 나머지 낮음은 신뢰된 운영자 subprocess 능력이다. 요청값을 SQL 구문이나 shell 명령으로 합치지 않는다. 경고를 숨기지 않았고 기존 규칙별 제외1건과 실행 파일/파일시스템 신뢰 한계도 기록했다.

별도 build generator는 중간 경고 **23건(기존22/신규1)**이며 source-owned SQL/finite placeholder 생성 지점을 검토했다. legacy native helper3개의 낮음6건과 최종 변경 helper2개의 경고0도 별도 범위로 보존했다. 이를 단일 전체 플랫폼 무취약 판정으로 합치지 않는다.

근거: [원시30파일 scan](recovery/bandit.json), [독립 검토](final/security-review-independent.json), [typed 릴리스 독립 검토](final/typed-release-fix-independent.json), [finite SQL 검토](final/vector-claim-catalog-recovery.json), [최종 helper scan](native-verified/bandit.json).

기존 GET/HEAD overview OpenAPI operation ID 경고와 generator 정규식 invalid-escape 경고는 무억제 보존했다. 이 검증은 전체 저장소 보안 인증, 실제 프록시 설정 확인, 침투시험 또는 외부 운영 수용을 대신하지 않는다.

## 남은 조건과 한 번의 반영

실제 관리자/hosted CI, Google/GitHub와 HTTPS/BFF, 독립 품질 평가자, 검증 수신처/Push 클릭, 대표 운영 부하·DR, 실제 결제 sandbox는 아직 지정·수용되지 않았다. 이를 성공으로 꾸미거나 임의 운영 대상으로 시험하지 않았다.

실제 조기 종료의 권한/임계값 기반 승격 validator와 controller, 공개 receipt/projection transport, 범용 planner, remote 장기 A2A/session/streaming, 신규 자체 agent의 독립 업무성과와 실제 결제 adapter는 조건부 추가 source다. circuit 자동 운영 계층도 현재 core와 구분한다. 오프라인 prefix 중단은 반사실 replay이며 실제 개입0·실제 개입 지표null·promotion off다.

공개 Workspace·광고·실거래는 계속 off다. 고객 Google/GitHub는 프론트엔드 전용이며 관리자는 기존 개별 로그인과 desktop을 사용한다. 다음 권위 순서는 [같은9개 작업](../../docs/REMAINING_WORK_BATCHES.md)에서 완료한 제한 소스를 반복하지 않고 실제 수용/명시 조건부 source만 이어가는 방식이다.

**운영 서버를 시작·중지·재시작하지 않았다.** 소스 통합 당시 필요했던 사용자 재시작·관리자 새로고침은 완료 보고와 후속 읽기 표본으로 확인했다. 실제 배포 프록시 설정과 인증 기능·운영 성능 수용은 별도다.
