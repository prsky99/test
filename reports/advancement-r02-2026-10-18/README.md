# R-02 공통 운영 관측 구현 및 검증

2026-10-18 · Agent Concierge · 소스 검증 완료 / 다음 사용자 재시작 후 Python API 배포 확인 대기

R-01 재시작 반영을 확인한 뒤 권장 순서의 R-02를 구현했다. 공통 카탈로그 SQLite에 개인정보 없는 논리 업무·개별 시도·이벤트를 기록하고, 인증된 superadmin이 관리자 **오류 → 공통 실행 추적**에서 지원 참조로 상태·사유·시도·이력을 조회한다. 상세는 중앙 native dialog이며 목록 자동 새로고침이 열린 상세를 닫지 않는다.

## 구현과 측정의 의미

- Chat 업무 검색/매칭, Testbench·관리형·기존 proxy 실행, workflow의 실제 provider 단계, 기존 동의된 task/workflow 전달을 계측했다. 한 workflow의 여러 단계와 한 전달의 재시도를 별도 성공 업무로 부풀리지 않는다.
- 정책 거절은 실제 dispatch 0회다. demo·프로토콜 handshake/discovery·status polling은 실제 업무 성공으로 집계하지 않는다. 저장된 run/전달 event의 내부 ID로만 중복을 묶으며 사용자 trace 헤더를 신뢰하지 않는다.
- 전송 경계 진입 후 결과를 확인하지 못하면 unknown을 보존한다. 늦은 결과는 확정 상태를 덮지 않는다. 요청이 끝난 관리형 worker는 추적 저장에서 분리했다. 오래된 미완료 관측의 unknown 표시는 조회 projection이며 업무를 재실행·복구하지 않는다.
- elapsed wall time과 adapter의 dispatch-to-result 구간을 구분한다. 네트워크 bytes 전송·제공자 수신·provider CPU 시간·방문자별 추천 전환·사용자 도착 확인·과금 지표는 측정했다고 주장하지 않는다.
- API는 superadmin 인증, 고정 형식 reference/범위 제한, read-only 일관된 조회 transaction, SQL parameter binding, no-store를 적용했다. UI는 값을 escape하고 로그아웃 시 열린 상세/지연 응답을 폐기한다.
- 입력·출력·raw wire·URL·연락처·방문자·IP·토큰·run key를 추적 테이블에 복제하지 않는다. 7일 목표의 증분 정리, 최대 20,000업무·업무당 100시도다. 유휴 시 정리가 지연될 수 있다. 저장 경합/장애/보존 삭제로 누락될 수 있어 `coverage_complete=false`를 명시한다.

정확한 계약·원시/운영 데이터 구분·배포/복원 절차: [OPERATIONAL_OBSERVABILITY.md](../../docs/OPERATIONAL_OBSERVABILITY.md).

## 최종 검증

최종 통합 **942개 통과**와 추가 edge 실행 **21개 통과**의 중복을 제거하면 **고유 944개 통과, 실패·skip 0건**이다. 21개 중 19개는 통합 실행에도 포함되며 2개는 이후 추가한 저장 장애/온라인 백업 복원 검사다. 이전 targeted 107개 등 중간 실행을 합산하지 않는다.

- 통합 진입점: `.venv/bin/python scripts/run_frontend_regressions.py --output reports/advancement-r02-2026-10-18/final`. 기능/API/Chromium/TLS/출력 은닉/SSRF·입력/권한·동의·기존 workflow/다운로드 호환 회귀를 격리 DB와 제공자 fixture로 실행했다.
- 신규 회귀: operation/attempt 분모, duplicate callback, 늦은 성공, dispatch 전/후 timeout, 전달 재시도, trace header 위조, 불필요한 raw/개인정보 비저장, 프로세스별 독립 SQLite 연결·재열기, 기존 business transaction 비침범, 최대 50ms SQLite busy wait 복원, 보존 삭제 시 catalog 유지, read-only stale projection, superadmin 경계·입력 필터, 브라우저 중앙 dialog·키보드·새로고침 유지·XSS 입력 거부.
- 추가 검사: 관측 저장 실패 중에도 Testbench 실제 fixture 실행이 성공함을 확인했다. SQLite online backup을 복원하고 catalog marker·업무 기록·`integrity_check=ok`를 확인했다. 운영 DB 복원 훈련은 아니다.
- 공개 콘텐츠 **53개 파일 위반 0건**. `front.py` embedded HTML과 `extracted_html.txt` 동기화 확인. 공개/어드민 다운로드 builder 및 공개 workflow 앱 JS는 R-01 snapshot과 동일하다.
- 기존 설계서·JSON·Canvas를 v1.5로 갱신했다. Canvas TSX 구문, inline JSON 일치, 14개 AC/10개 R/4개 Gate와 선행 순서를 검증했다. 전체 G0는 open이다.

원시 근거: [통합 로그](final-regression.log), [통합 XML](final/regression.xml), [최종 edge 로그](final-edge.log), [edge XML](final-edge.xml), [관리자 화면](admin-trace-dialog.png), [검증 JSON](verification.json).

## 보안 점검과 수정 이력

9개 변경 Python 모듈을 정적 점검했다. 어드민 dashboard 전체가 추가된 넓은 범위에서 **High 0 / Medium 22 / Low 30**의 기존 경고를 개별 검토했다. 신규 observability 모듈 경고는 0건이다. 기존 SQL의 고정 fragment/allowlist 및 parameter binding, 예외 fallback, 비밀이 아닌 public asset 값의 경고는 유지했다. 이전 R-01 Medium 8/Low 12와 범위가 달라 단순 증가·감소로 해석하지 않는다. [원본](bandit.json), [개별 검토](static-triage.json).

중간 integration 실행에서 시간 초과 이후 worker가 닫힌 DB에 추적 결과를 쓰는 경합으로 SQLite crash가 발생했다. 결과 저장을 요청 범위로 옮기고 종료된 요청의 trace를 worker에서 분리해 수정했다. 늦은 worker가 저장을 호출하면 실패하는 재현 테스트와 전체 회귀가 통과했다. 초기 문자열 assertion 1건과 브라우저 fixture의 Mock 응답 설정 문제도 수정했다. 중간 실패 로그는 보존하며 모든 과거 실행이 성공했다고 주장하지 않는다. 이 수정은 R-05 전체 worker 종료/영속 복구 보장이 아니다.

## 운영 확인과 남은 범위

R-01은 사용자 재시작 후 로컬/공개 HTML에서 새 가드를 확인했다. 기본 실제 예제 4개가 사용 가능하고 템플릿은 3개다. 공개 뉴스 예제 1건의 정상 API 실호출은 완료·simulated=false, 지원 참조 존재, 약 1,424ms였다. 이전 예제 4개/workflow 3개 실호출 결과를 이번에 모두 반복한 것은 아니다. [재시작 근거](restart-verification.json).

마지막 정상 HTML GET에서 로컬/공개 frontend와 admin은 200이었다. 어드민 HTML은 요청 시 파일을 읽으므로 새 추적 UI가 먼저 보이지만, 새 Python route나 producer가 운영 반영됐다는 근거가 되지 않는다. **프론트엔드·어드민 서버를 사용자가 다음에 재시작한 뒤 인증된 조회와 공통 DB 기록을 확인해야 한다.** 새 관측 테이블의 운영 생성/수집은 확인하지 않았고 직접 migration을 실행하지 않았다. [상태 기록](deployment-status.json).

서버 중지/시작/교체, 운영 DB 직접 쓰기, 운영 공격 경로 probe, 외부 알림/광고/결제 활성화는 하지 않았다. 정상 공개 예제 호출은 일반 API 경로이며 그 업무의 기존 실행 기록이 생길 수 있다. GitHub CI 설정은 같은 로컬 진입점으로 검증했고 hosted job은 미확인이다.

다음 순서는 R-02 배포 확인 → **R-03 versioned agent/binding/profile·CapabilityContract·증거·readiness**다. R-04 actor/delivery 권한과 실제 kill switch, R-05 영속 worker/복구, 폴백·모델 합성·조직·원장·지원은 후속이다. 현재 관측은 제한된 best-effort 운영 근거이며 전체 플랫폼 무결함·모든 제공자 성공·성능 SLA·영속 복구·자동 광고 동의의 인증이 아니다.
