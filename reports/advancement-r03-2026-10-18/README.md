# R-03 버전 계약·최신 증거·연결 준비 상태

2026-10-18 · 소스 구현/격리 검증 완료 · 다음 사용자 재시작 및 운영 확인 대기

R-03의 stable agent reference, 불변 binding/profile/full-schema 버전, 뉴스·문서 검색·제품 비교 계약, 실제 실행 증거·eligibility, 공개 검증 표시와 관리자 조회/명시적 계약 테스트를 구현했다. [구현 계약·DTO inventory](../../docs/CONNECTION_EVIDENCE.md), [설계서 v1.6](../../docs/PLATFORM_ADVANCEMENT_DESIGN.md).

## 적용한 동작

- 전체 MCP input/output schema를 별도 보존하고 호출 전 대조한다. compact hash가 같아도 전체 제약이 바뀌면 실제 도구 호출 없이 차단·격리한다. 주소·인증 변경도 확인하며 새 workflow snapshot은 내부 버전을 고정한다.
- `ag_` 참조는 DB에 영속 저장하고 기존 숫자 ID/게이트웨이 경로는 유지한다. 공개 projection에는 원본 주소·인증·private version/schema/binding hash를 추가하지 않는다.
- `news.search.v1`, `docs.search.v1`, `products.compare.v1`은 형식 외에도 UTC 시각·최신순·출처·중복·비공개 URL·비교 기준을 검증한다. 등록된 안전한 MCP 도구의 현재 버전을 superadmin이 승인하고 별도 실제 테스트를 실행한다. 승인·재승인·도구 교체를 성공 인증으로 취급하지 않는다. 제공자가 계약 형태를 반환해야 하며 임의 자동 정규화는 하지 않는다.
- 실제 실행과 기록/보고서 작성 시각을 분리한다. 최근 실행 성공을 추천에 반영하고 현재 버전의 최신 실패/unknown, 만료, 스키마 변경을 구분한다. 과거 보고서를 새로 작성한 것을 새 실행으로 올리지 않는다. legacy 기록은 기존 catalog 순위 호환만 유지하며 새 verified_callable 증거로 승격하지 않는다.
- 공개 Home·메타데이터·상세/Chat에는 고정된 영어 연결 검증 문구를 추가했다. 캐시의 검증 상태를 다시 확인하고 browser cached specification은 fresh detail 전까지 검증 대기로 표시한다. source HTML 두 파일은 동기화했다.
- 관리자 **오류 → 에이전트 버전·품질 증거**에서 중앙 dialog로 현재 버전·실행/기록 시각을 조회한다. 계약 승인과 실제 테스트는 명시적인 별도 동작이며 조회/새로고침이 제공자를 자동 호출하지 않는다.
- 기존 알림 승인 HMAC에는 full-schema hash도 포함했다. 신규 권한/동의·광고/결제·자동 폴백을 활성화하지 않았다. 공개 SDK 앱 JS와 공개/어드민 다운로드 builder는 R-02 snapshot과 동일하다.

## 검증 결과

통합 [1,033개 통과](final-v3-regression.log) 후 최종 승인/늦은 응답 보강의 [관련 보안·기능 223개 통과](final-security.log)를 확인했다. XML의 classname/name 중복을 제외하면 **고유 1,036개 통과, 실패·skip 0건**이다. 중간 223개 targeted, 13개 browser, 86개 edge, 182개 approval, 72개 API 등은 합산하지 않는다. [검증 JSON](verification.json), [집계](final-counts.json), [통합 XML](final-v3/regression.xml), [최종 경계 XML](final-security.xml).

통합 실행은 ISO 날짜 호환성 수정까지 포함한다. 이후 승인 교체/재승인 및 타임아웃 뒤 늦은 성공 증거 차단을 보강했고 영향받는 registry/managed gateway/admin/browser/observation 전체 경로를 최종 223개에서 다시 검증했다. 전체 통합을 마지막 세부 보강 뒤 한 번 더 수행했다고 주장하지 않는다.

검증 범위는 격리 DB/API/실제 Chromium/제어된 HTTP·TLS 제공자다. 실제 provider-step dispatch, 계약 API의 승인→실호출→결과 검증, URL/인증/전체 스키마 변경, 승인 도구 변경, 늦은 응답, 중복/분모, 만료/최신 실패, source/time semantic rejection, SQL/XSS/권한/SSRF·동의·CSP·영어 콘텐츠 및 기존 workflow/ZIP/SDK 경계를 포함한다. 전체 소스/모든 공급자의 무결함 인증이 아니다.

- 콘텐츠 **53개 파일 위반 0건** 및 embedded HTML 동기화.
- 기존 schema로 만든 SQLite의 보고서 작성 시각을 보존하고 실행 시각/version은 NULL로 유지하는 migration/reopen 검사. SQLite online backup 복원·stable reference·`integrity_check=ok` 확인. 운영 DB 복원 훈련은 아니다.
- 신규 연결 검증/관리자 dialog의 키보드·중앙 배치·새로고침 유지·fixed-label escaping과 초기 로딩 성능 회귀.
- 13개 모듈(기존 Store/collector/admin 전체 포함) 정적 점검은 **High 0·Medium 47·Low 40** 경고를 개별 검토했다. 고정 컬럼 migration SQL 경고도 포함하며 새 registry/contracts/observability 모듈 경고는 0건이다. 이전보다 넓은 범위이므로 단순 증감이나 전체 안전 인증으로 해석하지 않는다. [원본](bandit.json), [개별 검토](static-triage.json).

화면 근거: [관리자 현재 버전·증거](admin-connection-evidence.png), [공개 연결 검증](public-connection-verification.png).

## R-02 재시작 확인과 함께 보강한 문제

사용자 재시작 후 추적 테이블 생성과 관리자 API의 익명 접근 거절(403)을 확인했다. 정상 공개 뉴스 호출은 실제 완료·simulated=false였고 약 3,071ms가 걸렸다. 독립 read-only DB에서 동일 지원 참조의 업무·dispatch 1건을 확인했다. 그러나 최종 상태는 running으로 남았다. 관측 쓰기가 긴 카탈로그 Store reader lock에 밀려 생략될 수 있는 경로를 독립된 짧은 SQLite writer로 보강하고 재현 테스트를 추가했다. 실제 writer lock 경합에서는 여전히 best-effort 관측이 누락될 수 있다.

[운영 확인](restart-verification.json)에 이 한계를 그대로 기록했다. 도구 환경에 관리자 자격증명이 없어 운영 인증 조회는 우회하지 않았다. 운영 공격 probe, 원본 DB 파일 복사/복구, 수동 migration, 서버 중지/시작/교체는 하지 않았다. 정상 예제 호출은 일반 API 경로이며 기존 업무/접속 기록이 생길 수 있다.

## 중간 실패와 수정 근거

초기 full-schema drift 차단에 기존 quarantine 처리도 유지하도록 수정했다. 한 통합 실행은 새 무효화 trigger의 잘못된 기존 컬럼 참조로 실패해 해당 격리 pytest만 중단하고 수정했다. 다음 실행은 ISO 보고서 시각의 숫자 응답 호환 1건이 실패해 수정 후 35개 관련 추천/날짜 검사와 최종 통합을 통과했다. 중간 로그/XML은 보존한다. 모든 과거 실행이 성공했다고 주장하지 않는다.

## 배포와 남은 범위

**프론트엔드·어드민 서버를 다음에 사용자가 재시작해야 한다.** 정상 HTML GET만으로 현재 상태를 기록했다. 어드민 HTML은 요청 시 파일을 읽으므로 새 controls가 보여도 새 Python API·producer 반영 증거는 아니다. [배포 상태](deployment-status.json).

다음 운영 확인은 R-02 정상 완료 trace, R-03 현재 버전/새 실행 증거/준비 상태, 인증된 관리자 조회다. 그 뒤 권장 작업은 **R-04 caller/actor·배포별 delivery grant, 실제 invoke 중단 장치와 남은 G0 조건**이다. 전체 G0는 open이다.

전문가 검토 benchmark, 외부 source 사실 확인, 공급자별 정규화/의미 인증, 전수 외부 실호출, A2A stateful task/session, 장기 worker/복구·폴백·AI 합성·조직/원장·SLA는 이번 완료 범위가 아니다. 계약/evidence의 장기 보존·archive/capacity 정책도 별도다. 기존 gateway profile·공개 1.0/어드민 1.1 계약을 유지하며 광고·외부 알림·결제를 새로 활성화하지 않았다. GitHub hosted CI와 외부 서버에 다시 배포한 ZIP 실행은 이번에 확인하지 않았다.
