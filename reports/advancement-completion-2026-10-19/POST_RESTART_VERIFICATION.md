# Restart verification and subsequent source changes

2026-10-19 · 서버는 응답하지만 현재 디스크 소스 전체의 운영 반영은 확인되지 않았다.

고정된 GET 요청과 HTML 검사를 사용한 읽기 전용 점검은 **46/46 통과**했다. 상태 응답, 관리자 화면 파일 11개의 수용 SHA·CSP nonce, 관리자 초기화 표식, 비인증 접근 차단과 공개 Workspace 경로 비노출을 확인했다. 처음 표본은 브라우저용 `Accept: text/html`과 관리자 CSRF 헤더 정책의 기대값을 잘못 적용했다. 기존 표본을 보존하고 올바른 기대값으로 다시 확인했다. [확정 표본](post-restart-readonly-confirmed.json)

운영 포트의 PID는 38395, 시작 시각은 14:27:21이었다. 14:52의 공개 HTML에 포함된 `api` 함수 SHA는 이전 수용본과 일치하고 현재 소스와 달랐다. 현재 `front.py`의 수정 시각은 14:50이었다. 파일이 디스크에 반영된 것과 실행 중인 Python에 로드된 것은 구분해야 한다. 관리자 정적 파일 일치만으로 모든 Python 모듈의 최신 로드를 증명하지 않는다. [HTML 함수 대조](post-restart-served-front.json)

## 추가 변경 검증

현재 변경을 소스 사본·합성 DB·MockTransport로 검증했다. 관련 **15개 모듈의 고유 270개가 통과**했고 실패·오류·skip은 0건이다. 처음 267건 중 새 schema 검사의 응답 형식 기대값 1건이 실패했다. 실제로는 전송 전 HTTP 400으로 안전하게 차단됐으며, 현재 검사는 해당 응답과 외부 호출 불변을 확인한다. 수정된 모듈의 결과를 전체 교체했으며 이전 2,206건이나 반복 실행 건수는 더하지 않았다. 마지막 추가 availability 단언 3건도 같은 모듈의 기존 결과를 교체했다. [중복 제거 결과](post-restart-accepted-summary.json) · [최종 사례](post-restart-accepted-cases.json)

과거 보고서 검색에서 `health_status='quarantined'`만 설정된 대상이 목록에 다시 포함되는 문제를 격리 재현했다. 현재 SQL 후보 조건과 최신 resource 재조회에 모두 차단 조건이 적용됐으며 관련 3건이 통과했다. 실행 권한 우회는 관측되지 않았다. [독립 후속 검토](post-restart-security-followup.json)

새 schema 실패 이력 조회 SQL이 PostgreSQL 고정 카탈로그에 빠진 것도 확인했다. 카탈로그·생성기·137개 source manifest의 SHA를 확인한 후 생성 파일만 동기화했다. 새 쿼리 등록 및 **3,239 statements / 205 tables**의 정합성이 한 차례 통과했다. 이후 다른 소스가 다시 바뀌어 마지막 사본에서는 catalog source manifest의 재생성·정합성 점검이 다시 필요했다. 운영 DB를 변경하거나 PostgreSQL 운영 서버로 전환하지 않았다. [등록 차이 검토](post-restart-catalog-review.json) · [통과 기록](post-restart-delta-final/catalog.log) · [후속 불일치 기록](post-restart-delta-followup/catalog.log)

공개 콘텐츠는 **87개 파일, 위반 0건**이었다. 한글·Chat 상업 문구·삭제된 개인정보/개발 표시·메타데이터·embedded/extracted HTML 동기화를 검사했다. Chromium/API는 로딩 표시, 초기화, 검색과 보고서 이력, 게이트웨이, Test/Workflow, schema 실패 지속 차단을 격리 자료로 검증했다. 운영 포트·외부 연결은 회귀 프로세스의 네트워크 가드로 차단했다. [콘텐츠 기록](post-restart-delta-final/content.log)

Bandit의 선택 Python 9개 파일 원시 경고는 51건(High 0 / Medium 41 / Low 10)이다. 51건을 각각 소스와 대조했다. SQL 조합 40건은 고정 상수·허용 조합·별도 값 바인딩을 확인했고, 임시 경로 경고 1건은 파일 생성이 아닌 문자열 검사였다. 넓은 예외 처리 10건의 정리·진단 한계는 남겼다. 원시 경고를 삭제하거나 억제하지 않았고, 전체 안전 판정으로 확장하지 않았다. [원시 경고](post-restart-bandit.json) · [개별 정적 검토](post-restart-static-triage.json) · [선행 변경 검토](post-restart-delta-security-review.json)

## 현재 남은 확인

검증 이후에도 다른 작업의 프록시·schema 테스트·관리자 HTML 등의 수정이 관측됐다. 따라서 위 결과는 기록된 고정 사본의 영향 범위이며 **현재 전체 checkout의 최종 승인이나 전체 플랫폼 보안 인증이 아니다.** 새 뉴스 스키마 정비 CLI의 실제 운영 실행은 이 점검 범위에 포함하지 않았다.

다른 수정 마감 → 고정 카탈로그 재생성/정합성 → 최종 변경분 검증 → 사용자 터미널에서 재시작·새로고침 한 번 → 현재 응답 확인 순서로 묶는다. 개별 관리자로 인증한 실제 기능 수용, 실제 IdP·제공자·수신/Push·금융 대상의 수용은 별도다. 공개 Workspace·광고·실거래를 활성화하지 않았으며 운영 서버 시작/중지/재시작, 직접 운영 DB 접근, 실제 제공자 호출·발송 명령도 하지 않았다.

[구조화 결과](post-restart-verification.json) · [문서 반영 기록](post-restart-documentation.json)
