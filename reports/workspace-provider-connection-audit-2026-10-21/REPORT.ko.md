# 워크스페이스 제공자 OAuth·API 키 연결 UX 점검

점검일: 2026-10-21. 대상: 현재 저장소의 고객 워크스페이스 메뉴, 워크플로우 에디터, 후보 목록 API, 검토·실행 정책, 로그인 및 자격증명 저장 경로.

## 결론

현재 고객이 유료 에이전트 제공자의 OAuth 또는 API 키를 연결하는 기능은 구현되어 있지 않다. 앞서 제안한 고객 직접 결제형(BYOC)은 앞으로 개발할 사업·제품 방향이다. 이미 연결 화면이 잘 갖춰져 있다는 의미가 아니다.

입력 UI를 추가하는 일에 앞서 워크스페이스별 제공자 연결, 키 저장·접근 통제, 실행 시 자격증명 사용과 지출 승인의 연결이 필요하다. 현재 보호 정책을 단순 해제해서 지원할 수 없다.

## 확인한 문제

1. **필수 연결 경로 부재 / 출시 전 필수**
   - 워크스페이스 메뉴는 Overview, Workflows, Members & invitations, Plan & credits, Support, Account로 구성된다. Provider connections 또는 이에 해당하는 연결 관리 메뉴가 없다.
   - 에디터에 제공자 OAuth 시작, API 키 입력, 키 발급 안내, 연결 확인·변경·해제 기능이 없다.
   - 사용자 관점에서는 유료 제공자 계정이 있어도 어디에 연결해야 하는지 알 수 없으며, 현재 실제로 연결할 수도 없다.

2. **실행할 수 없는 후보가 선택 목록에 남을 수 있음 / 우선 개선**
   - 수동 선택 API `TypedFlows.options()`는 capability approval 기록으로 후보를 만든다. 현재 가격·인증 상태를 각 후보에 대해 재검증하지 않는다.
   - 격리 데이터에서 이미 승인된 후보를 `price_usdc=1` 또는 `auth_observed=1`로 바꾸어도 `Research search · Connection 1`이 선택 가능했다.
   - 검토 단계의 `_pin()`과 `admit()`는 이를 차단한다. 따라서 현재 보호 장치는 동작하지만, 화면의 선택 가능 상태와 실제 사용 가능 상태가 어긋난다.
   - AI 후보 생성의 `_candidates()`는 현재 실행 조건을 검사한다. 수동 선택과 AI 제안의 후보 판정 방식도 서로 다르다.

3. **오류 원인과 다음 행동 안내 부족 / 우선 개선**
   - 두 경우 모두 검토 POST가 403으로 거절되었다.
   - 화면: `Your current access does not allow this action. Check workspace access before continuing.`
   - 실제 조건은 제공자 인증 또는 가격에 따른 제한인데, 사용자가 자신의 워크스페이스 권한 문제로 이해할 수 있다. 연결 기능이 없는 현재에는 미지원 사유와 가능한 대체 후보를 안내해야 한다. 기능 도입 후에는 해당 제공자 연결 화면으로 안내해야 한다.

4. **후보 식별·비교 정보 부족 / 사용성 개선**
   - 수동 목록은 `Research search · Connection 1`처럼 작업 유형과 내부 번호 위주다.
   - 제공자·에이전트 이름, 인증 방식, 연결 상태, 마지막 확인 시점, 이 단계에서 사용할 연결을 표시하지 않는다.
   - 같은 작업을 하는 후보를 비교하거나 고객이 보유한 제공자 계정을 선택하기 어렵다.

5. **로그인·제공자 인증·크레딧의 구분 안내 필요 / 출시 전 필수**
   - Google/GitHub OAuth는 고객 로그인용이다. 이것으로 외부 유료 에이전트 호출 권한을 획득하는 기능이 아니다.
   - 현재 비현금성 저장·다운로드 크레딧은 제공자 API 잔액이나 지출 승인과 별개다.
   - 플랫폼 자격증명 암호화 코드가 존재하지만, 확인한 경로는 `platform_credentials`의 운영용 저장 기능이다. 고객 워크스페이스별 제공자 연결 CRUD·권한·회전·폐기 기능이 완성되었다는 근거가 아니다.

## 필요한 사용자 흐름

1. 에이전트 선택 시 제공자 이름·작업·인증 방식·지원 여부를 표시한다. 가격 정보가 없다는 이유만으로 무료라고 표시하지 않는다.
2. 해당 단계에서 `Connect provider`를 누르면 연결 안내를 연다. 기존 연결이 있으면 선택할 수 있도록 한다.
3. OAuth: 연결할 제공자와 요청 권한을 먼저 설명하고, 제공자 승인 화면으로 이동한다. 취소·거절·만료·실패 후 복귀 동작과 재시도를 제공한다.
4. API 키: 제공자 공식 발급 안내, 필요한 최소 권한, 연결 이름, 마스킹 입력·표시 전환, 붙여넣기 지원, 연결 확인 버튼을 제공한다. 키는 워크플로우 입력이나 AI 프롬프트에 붙여넣지 않도록 안내한다. 입력 UI만 만들고 안전한 서버 저장·실행 경로 없이 수집하지 않는다.
5. 연결 확인은 가능한 경우 과금 없는 검증 API를 사용한다. 검증 호출에도 비용이 발생하면 사전 안내와 승인을 받는다. 키 원문을 브라우저 저장소·로그·다운로드 앱에 남기지 않는다.
6. 연결 완료 후 원래 워크플로우 단계로 돌아와 입력을 유지한다. Connected, Expired, Reconnect required 등 상태와 마지막 확인 시점을 표시한다.
7. 고객 직접 결제 방식과 비용 부담자, 실행 승인·사용량 한도를 확인한다. 인증 성공이 지출 승인을 의미하지 않게 한다.
8. 연결 관리 화면에서 적용 중인 워크플로우, 변경·해제 영향, 키 교체·권한 철회를 확인한다. owner/editor/runner별 연결 관리·사용 권한을 분리한다.

## 검증과 증적

실제 고객 UI와 FastAPI 핸들러를 사용하는 격리 Chromium에서 합성 고객·임시 DB로 재현했다. 실제 고객 로그인 세션이나 운영 워크스페이스 설정에 접근한 점검은 아니다. 제공자 OAuth 승인·실제 키 검증은 해당 기능이 없어 수행하지 않았다.

- 감사 시나리오 2건 통과: 현재 결함의 재현 성공을 뜻하며, 유료 연결 기능의 품질 통과를 뜻하지 않는다.
- 검토 요청은 각각 403, 저장 버튼은 비활성화, 추가 에이전트 호출 0건, 외부 네트워크 요청 0건, 브라우저 JS 오류 0건.
- 처음 실행은 macOS 샌드박스의 Chromium 시작 제한으로 실패했다. 격리 브라우저 실행 권한으로 재실행한 결과는 `audit-final.log` 및 `audit-final.xml`에 기록했다.
- 화면 증적: [유료 조건 검토 전](paid-before-review.png), [유료 조건 검토 후](paid-after-review.png), [인증 필요 조건 검토 전](provider-auth-before-review.png), [인증 필요 조건 검토 후](provider-auth-after-review.png).
- 재현 코드: `test_provider_connection_audit.py`. 상세 관찰: `paid-evidence.json`, `provider-auth-evidence.json`.

## 소스 근거

- `agent_market/customer_workspace_pearl.py:38` — 고객 메뉴 구성.
- `agent_market/customer_typed_authoring_view.py:41` — 일반화된 오류 안내.
- `agent_market/customer_typed_authoring_view.py:43` — 후보 이름·선택 UI.
- `agent_market/workspace_typed_flows.py:258` — 수동 후보 조회.
- `agent_market/workspace_typed_flows.py:149` — 검토 시 현재 연결 검증.
- `agent_market/workspace_app_factory.py:93` — AI 후보 현재 상태 검증.
- `agent_market/concierge/execution_policy.py:70` — 가격·인증 조건 제한.
- `agent_market/customer_identity.py:267` — 로그인 OAuth 범위.
- `agent_market/gateway/store.py:2465` — 플랫폼 자격증명 저장 경로.

이번 작업은 점검·재현과 개선안 작성이다. 제품 코드, 운영 DB, 서버 설정은 변경하지 않았다.
