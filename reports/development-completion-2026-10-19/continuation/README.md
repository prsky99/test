# 개발 마감 후속 수정·검증

2026-10-19 · 원래 9단계/42개 요구 유지 · 실제 외부 수용 미완료

다른 수정이 끝났다는 사용자 답변에 따라 최종 검증 대기를 해제했다. 새 개선 항목이나 제공자를 임의로 추가하지 않았다. 소스 검토와 실제 환경 수용을 구분한다.

## 이번 수정

- PostgreSQL migration 리허설의 보고서 참조 무결성을 맞췄고, 전송 소비자 오류 때 row generator/cursor를 DB 종료 전에 닫도록 했다. 해당 검사49개 통과.
- 관리자 SDK1.1/1.2 ZIP에서 접근성 속성이 추가된 Run 버튼 때문에 입력/승인 UI가 삽입되지 않던 문제를 고쳤다. 버튼 prefix를 정확히 한 번 확인해 삽입하며 공개 기본 패키지는 바꾸지 않는다. 관련 검사67개 통과.
- NaN/Infinity 제공자 스키마가 불변 버전 해싱에서500을 일으키던 오류를 수정했다. 잘못된 원본을 구별하는 불투명 pin과 `schema_complete=false`를 남기며 빈 실행 스키마로 바꾸지 않는다. 공개 도구 목록은 비우고 `verified_callable=false`를 유지한다.
- 정적 HTML/CSS 설명 주석을 전송 시에만 줄였다. 원본 편집 anchor, `front.py`/`extracted_html.txt` 일치, Lucide 라이선스, nonce CSP와 `no-store`를 유지한다. 빈 카탈로그 측정은 gzip124,484bytes이며 기존125,000bytes 기준과2,000건 성능 fixture가 통과했다.
- 강화된 한 에이전트당 보고서 생성 제한과 충돌하던 과거 이력 fixture를 수정했다. 임시 PostgreSQL history seeding만 같은 트랜잭션에서 guard를 복구하며 운영 API/중복 방지 정책은 완화하지 않는다.
- cache v5, 실행 전 availability 차단, 별도 A2A session 호환 profile에 맞춰 오래된 시험 기대를 정정했다. 실행 전 거절 시 새 run이 생성되지 않는지 확인한다.
- SDK Chromium의 모의 callback bridge에 명시적인 HTML 형식과 탐색 완료 대기를 적용했다. 이는 실제 IdP 로그인을 대신하는 증거가 아니다.

## 검증 방법과 정확한 범위

1. [전체 기준](../final-candidate-2/results.json):306개 모듈, 고유5,554개 중5,541통과/13실패, 오류·skip0. 시작/종료1,015개 source hash 변경0.
2. 확인된 결함 수정 후 [API76개](defect-api.xml), [브라우저·native30개](defect-browser-native.xml) 중SDK1개 실패를 확인했고 [SDK 전체11개 재검사](sdk-bridge-fixed.xml)로 교체했다. [영향 검사632개](../final-candidate-3/impact.xml)도 통과했다. 서로 겹치는 숫자를 더하지 않는다.
3. [중복 없는 case별 최종 증거](../final-candidate-3/verification.json):고유5,554개 전부 통과, 실패/error/skip0. 이 중736개는 수정 후 재검사,4,818개는 변경 전 기준 결과를 유지한다. **최종 소스에서 전체를 한 번 더 실행한 결과로 표현하지 않는다.**
4. 공개 콘텐츠91개 파일 위반0, Ruff 치명 범주0. SQL catalog223개 테이블/3,472개 statement, `--check` 변경false. HTML mirror 일치.
5. [Bandit](../final-candidate-3/bandit.json):High0,Medium231,Low1,406,scan error0. 자동 경고는 입증된 취약점 건수가 아니다. 전체 경고가 해소됐거나 모두 수동 검토됐다는 의미도 아니다. 기존 [제한 보안 검토](../secure-coding-review.md)와 구분한다.

새 Medium B608 한 건은 임시 PostgreSQL history fixture의 INSERT다. 열 이름은 고정된 로컬 보고서 스키마의 행에서만 가져오고 값은 bind한다. 외부 요청 SQL이나 운영 DB에 적용하지 않는다. 새로운 경고를 숨기는 suppression은 추가하지 않았다.

보안 동적 범위에는 잘못된 스키마/JSON, 인증·CSRF·조직 경계, 공개 connection 비노출, XSS/CSP, 목적별 연락처·알림, SDK 동의·철회, workflow 제한과 unknown 보존의 기존 격리 API/Chromium 시나리오가 포함된다. 배포 프록시·실기기·실제 제공자의 전면 보안 인증이 아니다.

최종 source SHA: `8206e03a5eb823c60486fe0a62ac54457bd0f1b19ba644a95014902156ff6435` ([전체 manifest](../final-candidate-3/source-final.json)). 영향 검사 중 제품 소스 변경0이며, 독립 SDK 모듈의 bridge Content-Type 시험 수정만 별도11개 재검사로 확인했다.

## 계정 준비와 실제 수용 한계

[계정 상태 기록](provider-account-status.json)에 따라 기존 Google/GitHub 등록을 재사용한다. 중복 앱이나 새 키를 만들지 않았다. 보호된 실제 callback 수용은 아직 완료하지 않았다.

Stripe는 가입 화면에서 한국을 선택할 수 없었다. 사용자는 한국에서 창업을 준비하는 사업체 없는 개인이라고 답했다. 다른 국가/사업체를 임의 입력하지 않았고 개인정보 제출·계정 생성·키 발급·금전 이동0이다. 현재 [지원 지역](https://stripe.com/global)과 [다른 국가 계정 요건](https://support.stripe.com/questions/requirements-to-open-a-stripe-account-in-another-country?locale=en-GB)을 근거로 실제 가입 자격이 확인되지 않은 상태로 남긴다. 계정 생성만으로 나머지 독립 평가/기기/HA 수용 조건이 충족되는 것도 아니다.

기존 로컬 모델에는 공개 문서 목적과 합성 카탈로그만 사용해 [실제 HTTP 시험](actual-local-model.json)을 했다. cold 상태와 [빈 입력 preload 성공](local-model-preload.json) 후 모두2초 응답 제한을 넘겼다. 재시도 성공으로 꾸미거나 제한을 늘리지 않았고 검토/초안·업무 에이전트 실행·외부 모델 호출0이다. 응답 유실은 원격 취소 확인이 아니며 실제 모델 수용은 미완료다. [공식 preload 안내](https://docs.ollama.com/faq).

원래8개 외부 수용 묶음은 [42개 요구별 현황](../../../docs/development-completion-execution.json)에 유지한다:실제 비공개 IdP/HTTPS·독립 evaluator와 corpus·승인 A2A/모델·Push 장치와 수신처·독립 키 보관자·지정 HA/부하/DR·Stripe TEST·hosted CI/동료 signoff. 이 항목을 mock 결과나 임의 계정으로 완료 처리하지 않았다. 새 개발 목록을 만들지 않는다.

## 인계와 서버

[동료 검토 절차](../peer-handoff.md)는 지금부터 소스 검토에 사용할 수 있다. 원래 전체 개발/실제 수용 완료 선언은 보류한다. 프로젝트 서버 stop/start/restart0이며 사용자의 서버에 최신 Python 소스 반영을 확인하지 않았다. 최종 반영 시 사용자 터미널의 재시작/새로고침과 버전·관리자 확인이 필요하다. 공개 Workspace·광고·실거래·공개 trust는 닫힌 상태를 유지한다.

참고:실행 중 progress 문자와 별도 collection 출력을 연결한 임시 진단은 신뢰하지 않고 최종 JUnit으로 대체했다. storage inventory 등의 가짜 실패 매핑은 최종 결과에 포함하지 않는다. 외부 주소402 로그도 FakeRegistries 전송기의 응답으로 확인했으며 실제 upstream 통신으로 판정하지 않는다. 이전 candidate1 중단 결과와 중복/진단 실행은 최종 검사 수에 합산하지 않는다.
