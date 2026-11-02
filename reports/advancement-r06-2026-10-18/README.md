# R-06 제한된 호환 검색·shadow·명시적 canary 검증

2026-10-18 · 소스 구현/격리 검증 완료 · 운영 전환 기본 비활성

사용자 재시작 후 R-05 영속 실행 생산자를 확인하고 다음 권장 작업 R-06을 진행했다. [구현 계약](../../docs/WORKFLOW_FALLBACK.md), [설계서 v1.9](../../docs/PLATFORM_ADVANCEMENT_DESIGN.md), [검증 JSON](verification.json).

## 적용 내용

- 현재 성공 실행·계약 증거와 정확한 입출력 스키마, read-only/non-destructive/idempotent annotations를 가진 **stateless MCP 뉴스·문서 검색**에 한해 최고관리자가 명시한 대체 연결을 승인한다. 주 연결의 도구명·전체 버전·승인 시각·graph와 대체 연결을 고정한다. 일반 카탈로그 자동 검색/대체나 공급자 전수 품질 인증은 아니다.
- 대체 에이전트를 호출하지 않는 **shadow**가 정상 주 응답과 후보의 현재 근거만 검증한다. 완료된 정상 workflow와 서명된 workflow/run/node/graph/pair 증거가 있어야 canary를 구성한다. 승인/스키마/입력 graph/후보 변경은 readiness를 무효화한다.
- **기본 off**의 독립 CAS 제어와 서명 정책·실행별 동의를 적용했다. Canary는 최대 10%·선택 접수 100회·24시간, 전체 실행당 대체 시도 최대 1회다. 독립 runtime이 같은 DB를 사용해도 접수 상한을 넘지 않는다. off→on으로 예전 실행의 전환 권한이 되살아나지 않는다.
- 원래 25초 deadline 안에서 주 12초·대체 8초 예산을 사용한다. 도구 전송 전 네트워크 실패, 확인된 MCP 오류 응답, 완료됐지만 계약에 맞지 않는 출력만 제한적으로 전환한다. 전송 후 응답 유실/불명, 취소, 권한·정책·스키마 거절, 근거 만료, 시간 부족은 자동 반복하지 않는다. 늦은 응답도 성공한 전환으로 반영하지 않는다.
- 실제 전송 직전에 현재 실행 주체/역할, 소유자/fence/deadline/취소, 정책/제어 revision, graph·연결·승인·증거를 재검증한다. 별도 ordinal 시도와 고정 판단 사유를 영속 기록하고, 대체 예약 경계/전송 후 프로세스 종료는 재실행 대신 검토를 요구한다. 완료된 서명 체크포인트는 재호출 없이 재사용한다.
- 성공한 대체 출력을 검증해 체크포인트에 반영한 경우에만 `fallback_used`와 실제 선택된 agent ref/resource를 결과에 넣는다. 최종 결과/count/outbox는 기존 원자적 commit을 유지한다. 모의 수신처 검증에서도 제공자 시도 2회 뒤 결과 알림은 1회였다.
- 최고관리자 **오류 → 읽기 전용 호환 폴백**에 제어/정책 편집·조회, 복구 dialog에 시도·판단 기록을 추가했다. 정책 editor는 1개 노드를 편집하며 여러 노드 정책은 덮어쓰지 않는다. 로그아웃 시 사적 입력/상태와 동의를 초기화한다.
- 공개 Workflow의 **Allow one verified alternative**는 준비된 정책이 있을 때만 표시하고 미리 선택하지 않는다. 동일 작업 입력이 다른 에이전트에 공유될 수 있음을 설명하며 매 실행 초기화한다. 마케팅/알림/결과 전달 동의와 분리했다. Home·메타를 영어로 반영하고 embedded HTML과 extracted HTML을 동기화했다.
- 정책 변경은 runtime digest를 변경하고 기존 결과 전달 grant를 철회한다. 백업 복원은 전환 제어를 끄고 정책/shadow 증거를 제거한다. 기존 public SDK 1.0·admin SDK 1.1 다운로드는 실행 동의를 새로 보내지 않으므로 baseline 동작을 유지한다. [패키지 구현 해시 보존](package-preservation.json).

## 재시작 확인과 운영 범위

[재시작 확인](restart-verification.json): 정상 공개 workflow **1건 succeeded**, 독립 read-only DB에서 체크포인트 **3건**, 성공 도구 시도 **2건**, 완료 이벤트 **1건**, public 결과 전송 없음. Home 200/R-05 안내/CSP, 템플릿 3개, 관리자 복구 API 익명 403을 확인했다. 이번에 live 관리자 자격증명은 없었고 인가를 우회하지 않았다.

사용자 서버 중지·실행·재시작·교체 **0회**, 직접 운영 DB 쓰기/수동 migration **0회**, 운영 fallback 정책 생성/전환 활성화 **0회**, 실제 외부 알림/광고/결제 신규 활성화 **0회**다. 정상 공개 workflow smoke는 서비스 실행 이력을 생성하며 등록된 제공자를 호출할 수 있다. 장애·악성 입력·SIGKILL·복원은 격리 DB/프로세스와 모의 MCP/수신처만 대상으로 했다.

## 검증 결과

전체 회귀 **1,192건** 중 초기 **1,189건 통과·3건 실패**를 보존했다. 메타 설명이 기존 section 검사 범위를 넘은 2건은 설명을 간결하게 정리했고, 이전 템플릿 선택 오류 문구의 1건은 검증 순서를 조정해 호환을 유지했다. 테스트 기대값을 완화하지 않았다. [초기 통합 로그](final.log), [XML](final/regression.xml).

최종 소스의 영향 경로 **326건 통과·실패/오류/skip 0건**이다. 초기 통합과 최종 실행을 testcase 식별자로 대조해 최신 결과를 우선하면 **고유 1,213건 통과, 미해결 실패/오류/skip 0건**이다. 최종에는 새 경계 12건과 기존 admin SDK 브라우저 9건이 추가됐으며 중간 46/52/110/116/145건을 따로 합산하지 않았다. [최종 로그](final-validation.log), [XML](final-validation.xml), [대조 근거](test-reconciliation.json). 초기 통합 이후 최종 소스로 전체 통합을 재실행한 것은 아니며, 실제 변경의 모든 영향 경로를 마지막에 다시 확인했다. 한 번의 최종 목록 입력 오류로 수집만 종료된 기록은 validation-collection.log에 남겼고 테스트 수에 넣지 않았다.

최종 검증은 실제 Chromium의 공개/관리자 동의·역할·로그아웃·중앙 dialog, API allowlist/권한/no-store/키 경계, 뉴스 기간/최신순, 문서 계약, 없음/양쪽 오류/늦은 응답/응답 유실, 정책·schema·승인·만료·취소·권한 변경, 전송 직전 중단, 독립 runtime cap과 서명 변조를 포함한다. 격리 워커를 실제 SIGKILL한 위치는 **대체 예약 직후, 대체 제공자 수락을 모사한 전송 경계, 서명 체크포인트 저장 직후**다. 전자는 보수적으로 중단하고 후자는 완료 단계를 재호출하지 않는다.

R-06 제공자 장애는 모의 MCP transport, 수신처는 기록용 fixture로 검증했다. Chromium/API는 격리 TestClient와 연결했고 외부 브라우저 요청을 차단했다. 기존 관리형 gateway/워크플로우 HTTP/TLS·inbox·SDK/ZIP 실제 소켓/브라우저 회귀도 최종 실행에 포함했다. 실제 공급자 장애 주입이나 운영 TLS canary 실험을 했다고 해석하지 않는다.

공개 콘텐츠 **53개 파일 위반 0건**, embedded/extracted HTML 일치, 기존 CSP/출력 escaping/입력 마스킹·gateway 경계를 확인했다. [공개 동의 화면](public-fallback-consent.png), [관리자 제어](admin-fallback-controls.png).

정적 Bandit은 변경한 Python **6개 모듈**에서 **High 0·Medium 22·Low 29**다. 새 router/runtime/persistence/backup 모듈은 경고 0건이며, 남은 51건은 이전 개별 검토와 코드 블록이 동일한 기존 SQL 구성/예외 처리/공개 상수 경고다. 각 항목을 재검토해 [원본](bandit.json)과 [개별 판단](static-triage.json)에 기록했다. 다른 범위의 R-05 수치와 단순 비교하거나 전체 보안 무결함을 인증하지 않는다.

## 운영 반영과 남은 작업

**새 Python 라우터·제어·정책을 적용하려면 사용자가 프론트엔드와 어드민을 재시작해야 한다.** 화면 파일만 새로 보이는 것은 Python API가 반영됐다는 근거가 아니다. 재시작 후 기본 off·정책 없음과 인증된 관리자 조회부터 확인해야 한다. 실제 전환은 현재 근거를 검토한 명시적 후보의 정상 shadow 후 별도로 허용해야 하며, 이번 개발에서는 운영 전환을 켜지 않았다.

새 주 에이전트 실패 기록 뒤에는 다음 전환 시험 전에 재검증이 필요할 수 있는 보수적 pilot이며 연속 자동 장애 복구를 보장하지 않는다. 전체 G0/G1·실제 승인 공급자의 shadow/canary cohort·전문가 의미/품질 benchmark·전체 카탈로그 실제 호출·외부 배포/과거 artifact·hosted CI·확대 용량/보존/HA는 미완료다. A2A task/session·x402·쓰기/결제·자격증명·제품 비교의 단위 정규화는 폴백 대상에서 제외한다. R-05의 PostgreSQL 15-table 리허설은 새 R-06 routing 테이블과 전체 Store adapter를 포함하지 않는다. 외부 exactly-once나 이미 수락된 요청의 소급 취소를 보장하지 않는다.

설계서·구조화 backlog·기존 Canvas를 **v1.9**로 동기화했다. [Canvas 문법/inline plan 검증](canvas-validation.json), AC 14개·권장 순서 10개·Gate 4개를 유지했다. 다음 소스 개발은 **R-07 AI 워크플로우 합성·검증·동일 입력 비교**다. [최종 소스 해시](final-source-snapshot.json).
