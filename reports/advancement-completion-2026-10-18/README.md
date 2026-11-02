# 현재 설계 잔여 작업의 제한 구현·검증 보고서

2026-10-18 · v1.34 소스 묶음 · **제한 소스 범위의 격리 검증 완료 · 사용자 재시작 대기**

이번 묶음은 N01–N12에서 독립적으로 구현할 수 있는 고객 인증, private 실행 생명주기·릴리스, 제공자 control proof, 평가 관리, 제품 계약 연결, 모의 원장·지원·준비 조회를 제한된 profile로 연결했다. 최신 사용자 요청인 공개 **About** 화면도 포함한다. N01–N12 전체의 운영 완료나 제품 v2.0 출시를 선언하는 보고서가 아니다.

## 구현한 범위와 남은 경계

- **N01 — 인증 운영 수용·G0:** 기존 실제 관리자 세션으로 v1.33의 빈 workspace 목록과 생성 제어를 읽기 확인했다. 객체 생성·실제 실행은 하지 않았다. 이번 묶음의 실제 인증 운영 수용, 전체 G0 exit, hosted CI와 외부 호스팅 수용은 별도다. [읽기 확인](authenticated-readonly.json).
- **N02 — 고객 인증·조직 권한:** Google OIDC·GitHub OAuth 로그인은 **공개 프론트엔드만** 제공한다. 코드·state·PKCE·토큰/사용자 검증은 서버에서 수행하며 어드민은 기존 개별 staff 세션을 유지한다. 고객의 명시적 `viewer`/`runner` workspace 링크, 짧은 목적별 BFF 권한, 로그아웃·철회 경계를 구현했다. 실제 IdP 설정·로그인 수용, 고객 owner/초대·가입·탈퇴와 전체 개인정보 생명주기는 미완료다. [계약](../../docs/CUSTOMER_IDENTITY.md).
- **N03 — private 생명주기:** 만료 미사용 ticket 정리, 서명 tombstone, 오래된 확정 출력의 논리 보존 정리, quota 보강과 unknown 검토 메모를 구현했다. 메모는 실행 certainty를 바꾸거나 재전송하지 않는다. 키 회전·암호화·backup 잔존 정책과 복원된 비활성 namespace의 현재 소유자 증명은 별도다. [계약](../../docs/WORKSPACE_LIFECYCLE.md).
- **N04 — 불변 릴리스·SDK2:** 성공한 private 시험에 고정된 **수동 trigger 한 개와 읽기 전용 literal MCP 한 호출**의 별도 release/deployment, 고객용 code/PKCE·BFF·run/status capability와 ZIP을 구현했다. 저장 JSON 자체는 비실행 자료다. 기존 공개 SDK1.0·어드민1.1·literal1.2·connected1.3과 권한을 혼합하지 않는다. 실제 IdP·별도 HTTPS 호스팅 수용은 별도다. [계약](../../docs/WORKSPACE_RELEASE_V2.md).
- **N05 — 제공자 증명:** 현재 staff owner가 명시 승인하는 고정 HTTPS challenge, 한 번의 검증·CAS·철회·generation 바인딩을 구현했다. 이는 관측 시점의 endpoint control이며 법적 소유권·품질·상업 권리가 아니다. 실제 제공자 검증, 이전·분쟁·주기적 재검증 정책은 남는다. [계약](../../docs/PROVIDER_CLAIMS.md).
- **N06 — 평가 관리:** scoped `wpr_` 실행 전 할당, 고정 rubric·dataset/source 참조, 구분된 실행자·검토자·조정자, 실제 계정별 disclosure·점수·불일치 대사를 구현했다. 현재 membership/revision·provider generation·control epoch를 다시 확인한다. 실제 독립성·전문 자격·별도 출처 검증 adapter는 기본 미설정이며, 합성 자료·계정 분리·hash만으로 expert/holdout 증거를 만들지 않는다. [계약](../../docs/WORKFLOW_QUALITY_REVIEW.md).
- **N07 — 폴백·자동화 운영:** 기존 news/docs의 제한 shadow/canary, 최대 한 번 대체와 전송 후 unknown 재실행 금지, canonical 예약/이벤트 기반을 재사용했다. 실제 승인 cohort·G1 운영 수용은 수행하지 않았다. canonical 자동화의 fallback·결과 전달 금지와 별도 전달 grant 경계도 유지한다.
- **N08 — 전체 Store/PostgreSQL:** source-bound 누락/소유 범위 감사와 **private 36개 테이블의 합성 scalar·제약 리허설**을 추가했다. 전체 Store 애플리케이션 repository, 검색/권한 parity, 대표 부하·DR/HA·실제 이전과 rollback은 남는다. `open_store`의 PostgreSQL 애플리케이션 backend 거부는 유지된다. [누락 범위](../../docs/APPLICATION_STORE_MIGRATION_READINESS.md).
- **N09 — 제품·flow 확대:** 정확한 현재 schema·승인·실행/계약 증거를 갖춘 `products.compare.v2` 한 호출을 private 저장·시험·실제 보존 출력의 계약 검증에 연결했다. 값·단위·통화·시간·부분/누락을 명시하며 winner·FX·사실 정확도를 추론하지 않는다. 이 profile의 release/SDK·공개 게시·fallback은 거부한다. 일반 typed DAG·분기·장기 A2A/MCP 상태 계약은 별도다. [계약](../../docs/WORKSPACE_PRODUCT_COMPOSER.md).
- **N10 — 모의 원장:** 명시 승인된 논리 operation과 별도 event ID, 자산별 정수 double entry, 부분/unknown 대사와 한 번의 전액 역분개를 구현했다. 기존 metrics의 자동 청구 전환, 실제 돈·지급·자동 7:3 배분은 없다. [계약](../../docs/SHADOW_LEDGER.md).
- **N11 — 지원:** 허용된 로컬 안내와 제한된 private draft 필드의 결정적 JSON patch 제안, 별도 검토·CAS 적용을 구현했다. 모델·임의 명령·workflow 실행·게시를 하지 않는다. 실제 AI 지원·자체 공급자, 지원 인력·업무 성과와 관찰 cohort는 별도다. [계약](../../docs/WORKFLOW_SUPPORT.md).
- **N12 — 상용 준비:** 서명된 미검증 선언과 trusted server adapter의 실제 현재 증거를 구분하는 조회를 구현했다. 미설정·누락은 `not_ready`이며, 완비돼도 별도 검토가 필요하다. 실제 계약·결제·지급·광고·상용 Gate 자동 승격은 활성화하지 않는다. [계약](../../docs/COMMERCIAL_READINESS.md).

## 최신 공개 About 변경

About은 List Your Agent 다음에 배치하고, Home은 접근 가능한 Agent Concierge 브랜드 링크로 유지했다. 서비스의 현재 가치·증거의 한계와 장래 비전을 영어로 구분하며 기존 Chat·Explore·Workflows·등록·법적 고지 fragment에 연결한다. page metadata·sitemap·LLM 안내·AboutPage JSON-LD를 맞췄다. 로컬 Lucide, 명암·모바일·키보드, HTML/extracted 동기화와 nonce/CSP 경계를 유지했다.

독립 검토에서 About 변경의 구체적인 제품 차단 문제는 발견하지 못했다. 초기 자동 screenshot에는 기존 cookie 거절 후 acknowledgement가 남아 hero가 가려져 있었다. 원본은 보존하고 기존 acknowledgement를 닫은 별도 검토 이미지를 추가했다. 제품 보안 결함 수정이나 테스트 수 증가로 계산하지 않는다. [초기 독립 검토](about-independent-review-initial.json), [초기 소스](about/source-checks.json). 용량 조치 후 [최종 독립 검토](about-independent-review-final.json), [최종 화면 검토](about/visual-review-final.json), [desktop](about/about-final-desktop-light.png), [mobile](about/about-final-mobile-dark.png)를 따로 보존했다.

## 회귀 근거와 현재 집계 상태

첫 동결 **106모듈** 실행은 **2,601 통과 / 23 실패 / 오류 0 / skip 0**였다. 23개는 세 quality-review 모듈에 집중됐다. 격리 harness가 필수 정적 자료인 `docs/workflow-evaluation-cases.json`을 복사하지 않아 19개가 rubric 로딩에서 직접 막히고 나머지 API/browser 4개도 같은 선행 조건에서 막혔다. 이는 제품 소스 결함 수정으로 처리하지 않았으며, 원래 실패 XML과 독립 원인 분석을 보존했다. 필수 자료를 포함한 별도 동결 입력에서 해당23개 전부 통과했다. 제품 코드를 수정하거나 원래 실패를 삭제하지 않았다. [원본 106모듈 결과](affected/regression.xml), [원인 분석](main-failure-review.json).

- **공개·About 영향 37모듈:** 429통과/1실패(전체430). 추가된 문서의 gzip126,292bytes가 기존125,000bytes 제한을 넘었다. 원래 한도를 유지하고 About의 중복 copy/정적 CSS·마크업만 줄였다. [선택](about-selected-regression.json), [원본](about-affected/regression.xml).
- **최종 About·성능·메뉴·메타·보안 8모듈:** 84통과/실패·오류·skip0, 46.37초. 실제 합성2000-resource 첫 문서는124,583gzip bytes로 기존 제한 이내다. 모든5개 실행 script와 비HTML Python 함수 AST는37모듈 실행 소스와 동일하다. [최종 결과](about-size-final/regression.xml), [용량](about/size-final.json), [정적 delta](about/optimization-source-checks.json).
- **필수 rubric 자료를 포함한 quality 3모듈:** 23통과/실패·오류·skip0. 최초 실패23개와 case ID가 일치한다. [선택 범위](quality-recovered-selected.json), [실행 XML](quality-recovered/regression.xml).
- 개별 core/API/browser·보안 시험 결과는 각 XML에 남아 있다. [도구·평가 69-case 범위](tools-quality-owned-final.xml), [신원 검토](identity-store-owned-review.json), [SDK2 범위](sdk2-final.xml) 등은 위 회귀와 겹치므로 통과 수를 더하지 않는다. private product sticky header의 세 시험도 기존 시험의 재실행이다. [표현 변경 근거](presentation-delta.json).

입력 동결은 기본 **671파일**, About 이후 **673파일**, quality의 필수 문서 자료까지 포함해 **674파일**이다. 파일 수는 기능 수나 전체 schema 보장치가 아니다. 각각의 source hash와 격리 조건을 보존했다. 최종674개 입력은 현재 작업 소스와 일치하며 동결 중 변경0이다. 기본 실행 이후의7개 파일 변경과 추가 About test2개/필수 rubric1개를 명시적으로 대조했다. case ID 중복을 제거한 검증 합집합은2,831개이며, 서로 다른 동결 입력의 delta를 조정한 수치다. 단일 전체 green 실행·전체 플랫폼 인증으로 표현하지 않는다. 초기24개 실패는 모두 대응하는 통과 재검증과 연결했다. [최종 수용](verification.json), [소스 대조](source-reconciliation.json), [최종 동결](accepted-source-snapshot.json). [기본](final-source-snapshot.json), [About](about-source-snapshot.json), [quality+자료](quality-recovered-source-snapshot.json).

## 보안·저장소·격리 검증의 범위

- Bandit 신규 Python **19모듈: High 0 / Medium 0 / Low 4**, 통합 **9모듈: High 0 / Medium 29 / Low 27**, scan error 0. raw finding은 제거하지 않았다. 통합 Medium 29개는 고정 SQL 조각·바인딩·경로 분류 등 개별 dataflow 근거를 기록했다. 이 수치는 무결점/전체 플랫폼 보안 인증이 아니다. 스캔은 기본 동결 소스에 바인딩되며 후속 About 표현 변경은 별도 소스·독립 검토와 영향 회귀로 추적한다. 최종 front.py 정적 결과도 기존 High0/Medium9/Low11 경고 유형·개수가 동일하며 기존 검토를 보존했다. [최종 delta](about-static-delta.json). [신규 raw](static-new-final.json), [통합 raw](static-integration-final.json), [개별 검토](security-static-review.json).
- 실제 disposable PostgreSQL Unix socket에서 private **36테이블**의 합성 scalar/제약 왕복, rollback·중복 private run 거부와 cluster 제거를 확인했다. catalog/FTS/vector·실제 애플리케이션 repository·부하·운영 DR는 이 시험 대상이 아니다. 운영 DSN 전환이나 full Store PostgreSQL 완료로 부르지 않는다. [리허설](private-postgres-schema-final.json).
- 최종 회귀는 격리 DB·고정 mock provider·routed Chromium과 필요한 임시 loopback TLS/Redis/PostgreSQL fixture를 사용한다. 공개 네트워크와 명명된 운영 포트는 최종 harness에서 허용하지 않았고 해당 실행의 차단 연결 계수는 0이다. 이는 **모든 초기 시도까지 네트워크/DB 효과가 0이었다는 주장과 다르다.** [기본 격리](snapshot-isolation.json), [최종 연결 기록](network-isolation.json).
- 초기 identity Chromium redirect 후속 요청이 route handler를 우회해 공개 `/customer/workspaces` GET을 시도/도달했는지와 그 logging/statistics 영향은 **불확실**하다. 실제 credential·IdP 작업이나 의도한 운영 변경은 없었으나 운영 DB write 0으로 단정하지 않는다. 이후 fixture는 명시적 offline context와 reserved host를 사용한다. 마지막 browser bridge는 API 검증된 303을 로컬 JS navigation으로 바꾸며, native 30x interception 검증으로 표시하지 않는다. 초기 XML과 이 한계를 보존했다. [신원 초기·최종 관측](identity-store-owned-review.json).

## 운영 수용과 후속 설계

이번 개발에서 사용자 서버를 재시작·대체하지 않았다. 이전 v1.33 관리자 읽기 확인은 현재 묶음의 실제 실행·고객 로그인·제공자 승인 수용과 다르다. 완료된 Python 소스 묶음의 반영에는 사용자가 터미널에서 서버를 재시작하고 탭을 새로고침하는1회 절차가 필요하다. 이후 현재 버전 인증 운영 수용을 별도로 확인한다.

남은 조건은 실제 Google/GitHub 설정·수용, 고객 owner/초대/탈퇴·전체 lifecycle, 실제 제공자/독립 검토자·자료, G0/G1 cohort와 hosted/별도 배포 수용, 전체 Store PostgreSQL 소스·parity·부하/DR/HA, 키/암호화/복원 소유권 정책, 계약·결제/지급·상용 Gate다. 합성 fixture·계정 수·회귀 통과 수로 그 근거를 대체하지 않는다.

[2차 고도화 문서](../../docs/PLATFORM_ADVANCEMENT_PHASE2_DESIGN.md)는 별도 **설계안**이다. reliability/evaluation/badge/routing/stateful/commerce의 후속 제안을 이번에 구현했다고 표시하지 않는다. 현재 제한 profile과 위 잔여 조건을 유지한 채 [남은 작업 계획](../../docs/REMAINING_WORK_BATCHES.md)을 갱신해 진행한다.
