# AX 불일치 수정 및 재시작 확인

검토·수정일: 2026-10-25 (Asia/Seoul)

## PostgreSQL 후속 검증 및 수정 반영 완료

임시 서버 초기화 대신 기존 PostgreSQL 18의 전용 Schema에서 실제 검사 8항목을 완료했다. 생성한 Schema는 모두 제거됐고 운영 테이블에는 쓰지 않았다. 실제 애플리케이션 Store 프로필 연결과 차단 조회도 읽기 전용으로 성공했다.

이 과정에서 Python list 파라미터가 공통 실행기에 거부되는 추가 오류를 발견해 scalar JSON 파라미터로 수정했다. 이 후속 수정은 Frontend·Admin의 `web-20261025-202033-b4d1`에서 반영과 정상 조회를 확인했다. 연구·SNS 근거와 검사 자료는 [후속 보고서](<저장소>/reports/ax-postgres-alternative-2026-10-25/README.md)에 있다.

## 재시작 후 최종 확인

사용자의 추가 재시작 이후 Frontend·Admin은 모두 `web-20261025-194831-2de0`으로 전환됐다. 수정 관련 파일 7개가 두 활성 패키지 모두 작업 소스와 일치하며, 두 서비스의 인증된 readiness는 ready=true다. Jobs·Execution의 PID 생존도 확인했다.

활성 패키지를 직접 import하는 격리 회귀 검사 **15개가 모두 통과**했다. 당시 수정의 Frontend·Admin 운영 반영은 확인 완료였다. 이후 위 PostgreSQL 후속 오류 수정이 추가됐다. 자료: post-restart-packages.json, post-restart-readiness.json, post-restart-controls.log.

당시 PostgreSQL 검사는 initdb 단계에서 막혔으나, 현재는 위 전용 Schema 대안으로 기능 검증을 완료했다. 당시 실패 기록은 post-restart-postgres.log에 남겼다.

## 운영 상태와 수정 반영 구분

사용자의 재시작 후 활성 Frontend·Admin은 `web-20261025-174552-d302`였다. 인증된 로컬 readiness 검사는 두 서비스 모두 ready=true였고, Jobs와 Execution도 기록된 PID가 살아 있었다. 확인 자료는 runtime-status.json과 readiness.json이다.

그러나 해당 활성 패키지에는 앞선 검토에서 발견한 코드가 그대로 있었다. 이번 수정은 작업 소스에 적용했다. 이 작업에서 운영 서버를 재시작하거나 배포하지 않았으므로 수정 이후 새 Frontend·Admin 패키지로 반영해야 한다. Jobs·Execution·Cloudflare Worker는 이번 변경의 활성화 대상이 아니다.

활성 패키지를 PYTHONPATH의 첫 위치에 둔 별도 격리 프로세스에서 이전 재현 검사도 다시 실행했다. 기존 네 결함과 자연어 안내 누락이 모두 그대로 재현됐다(진단 검사 5개 통과는 결함의 재현을 의미한다). 결과는 restarted-package-reproduction.log다. 현재 작업 소스와 활성 패키지의 반영 대기 파일 비교는 pending-deployment.json에 기록했다.

## 수정 내용

1. **차단 불변 조건**: FastConcierge의 첫 추천 및 details 재검증에서, 다른 후보가 없다는 이유로 전역 차단을 풀던 폴백을 제거했다. 후보가 없으면 no-match 또는 다른 프로토콜 재질의 안내를 제공한다. 실행 결과 전송의 Edge→Origin 폴백 정책은 이 추천 차단 정책과 별개다.
2. **수동 차단 상태 분리**: 기존 meta 저장소의 전용 키 `recommendation_circuit_controls_v1`에 리소스별 수동 open 상태와 관찰 재개 시각을 저장한다. 가짜 방문자의 실패 행을 새로 만들지 않는다. 성공 이력이 많은 리소스도 수동 차단되며 응답·Admin 표시가 실제 제외 상태를 사용한다.
3. **실패 이력 보존**: reset은 agent_outcomes를 삭제하지 않고 관찰 재개 시각을 갱신한다. 이전 성공·실패 행은 남고, 새 구간의 실패가 임계값에 도달하면 재차 차단된다. 과거 `__admin_cb_*` 행도 삭제하지 않고, 이전 수동 차단의 호환 상태로 읽는다. 명시적으로 reset하면 새 관찰 구간으로 넘어간다.
4. **저장소 일관성**: SQLite와 PostgreSQL 모두 같은 상태 모델을 사용한다. PostgreSQL은 전용 meta 행의 FOR UPDATE 잠금과 트랜잭션으로 동시 관리자 변경의 덮어쓰기를 방지한다. 신규 테이블·마이그레이션은 없다. SQL 카탈로그 생성기의 고정 JSON 경로 변환도 보완했다.
5. **정상 수요 보존**: image generation workflow, book a hotel workflow, unicorn 등 요청 문구만으로 합성 테스트로 분류하던 정규식을 제거했다. 저장된 관리자 테스트 채널의 출처가 있는 기록을 분리한다. 출처가 불명확한 기록은 실제 수요 분석에 남기는 방향으로 처리한다.
6. **분석 지표 정정**: 최근 제한된 기록 범위, 미해결·재확인 대상 수, 표시 수(최대 15), 카탈로그 재확인 예산(최대 20), 재확인 대기를 구분한다. 대기 중인 요청을 목록에서 잘라 총계를 줄이지 않는다. ‘현재 후보 존재’를 ‘업무 실행 성공’과 구분해 API와 Admin 문구에 반영한다. 정상 후보가 없는데 해결 버튼으로 요청을 비활성화하던 동작도 409 응답으로 막았다. 해결 반영은 요청 프로토콜을 유지하고 차단된 후보를 제외한다.
7. **작은 누락 보완**: cv/resume 단어 매칭을 양방향으로 보완하고, 교차 프로토콜 recovery hint를 자연어 답변에도 표시한다. 확인된 실행 증거가 있는 경우에만 Verified 문구를 붙인다. 관리자 차단·해제 조치는 기존 감사 기록에 남긴다.

## 연구와 SNS 확인, 적용 범위

- [MCP-Zero 원문](https://arxiv.org/abs/2506.01056), [저자 구현](https://github.com/xfey/MCP-Zero): 도구 탐색과 필요한 기능의 명시적 요청·발견을 다룬다. 이번에는 strict protocol 유지 및 기계·자연어 recovery 안내를 함께 제공하는 근거로 참고했다.
- [ToolRet 원문](https://arxiv.org/abs/2503.01763), [ACL 논문](https://aclanthology.org/2025.findings-acl.1258.pdf): 도구 검색 품질은 일반 검색 점수나 단순 후보 존재와 구분해 평가할 필요가 있다. 이번 지표도 후보 발견과 실제 업무 성공을 분리했다.
- [Resilience4j 공식 CircuitBreaker 문서](https://resilience4j.readme.io/docs/circuitbreaker): 자동 상태와 강제 open 상태를 구분한다. 이번 구현은 별도의 추천 제어 상태와 관찰 구간을 두고 실행 이력을 보존하는 방식이다. 자동 half-open Provider 호출이나 주기적 재시도를 새로 추가하지 않았다.
- [ToolRet 연구자의 LinkedIn 게시물](https://www.linkedin.com/posts/zhaochun-ren-460491296_250301763-activity-7302809681989623810-wpDI): 연구 원문으로 연결되는 SNS 맥락을 확인했다.
- [Reddit: Provider 장애 시 분산 Circuit Breaker 논의](https://www.reddit.com/r/softwarearchitecture/comments/1p4625e/fallback_when_provider_down/), [Reddit: retry·DLQ와 Circuit Breaker 논의](https://www.reddit.com/r/softwarearchitecture/comments/1rv5igk/we_thought_retry_dlq_was_enough/): 프로세스 간 상태 공유와 실패 대상 재시도 문제를 참고했다. SNS 경험담은 성능·정확성 증명의 근거로 사용하지 않았다.

이 자료들은 설계 선택의 참고 자료다. 이번 수정의 효과는 아래 로컬 재현·회귀 검사로 평가하며, 논문으로 서비스의 미해결 0건이나 재방문 증가를 입증했다고 표현하지 않는다.

## 검증 자료

- `targeted-tests.log`: 85 passed. 최초 수정 후 추천·Admin·새 제어 회귀 검사.
- `security-and-integration.log`: 첫 통합 검사에서 169 passed / SQL 카탈로그 JSON 경로 변환 검사 1 failed. 이 실패를 보완했다.
- `final-control-tests.log`: 보완 후 새 제어·SQL 커버리지·consumer 검사 29 passed.
- `final-recommendation-tests.log`: 후속 추천·Admin 검사 70 passed.
- `browser-security-escalated.log`: 실제 Chromium의 기존 Admin CSP·XSS 검사 23 passed.
- `browser-controls-final.log`: 차단·해제 표시, 이력 수치 유지, 프로토콜 전달 및 task 속성 이스케이프의 실제 Chromium 검사 1 passed.
- `final-regression.log`: 수정 완료 소스에 대한 전체 대상 **279 passed / 0 failed**, 종료 코드 0. 실제 Chromium 검사 24개를 포함한다.
- `content-check-final.log`: 공개 Frontend 파일 273개 / 문구 정책 위반 0건.

브라우저 검사는 기존 프로젝트 서버 대신 격리 TestClient와 테스트 DB를 사용했다. API 보안 검사는 로그인 요구, 잘못된 리소스 ID·SQL 주입형 입력·비정상 숫자 거부를 포함한다. 브라우저에서는 기존 CSP를 유지한 채 조작하고 악성 task 문자열이 DOM 속성이나 SVG로 실행되지 않는지 확인했다. 전체 제품의 보안을 인증하는 범위는 아니다.

## 당시 PostgreSQL 실행 검사 제한 — 후속 대안으로 완료

`tests/test_recommendation_circuit_postgres.py`에 실제 PostgreSQL/SQLite 상태·이력 보존 및 동시 변경 비교 검사를 준비했다. 그러나 이 기기의 임시 PostgreSQL 14 초기화가 `could not create shared memory segment: No space left on device`로 실패했다. PostgreSQL 오류 설명상 디스크 부족과 구분되는 System V 공유 메모리 한도 문제다. 샌드박스 밖 재시도에서도 같았다.

따라서 이번 작업에서 **PostgreSQL 네이티브 실행 검사가 통과했다고 판단하지 않는다.** SQL 경로 변환과 로컬 기능·보안 검사는 완료하며, 실제 DB 동시성 검증은 이 환경 문제가 해소된 뒤 아래 명령으로 마무리해야 한다.

```
.venv/bin/python -m pytest -q tests/test_recommendation_circuit_postgres.py
```

기존 PostgreSQL 프로세스 종료, 시스템 공유 메모리 삭제, 운영 DB를 이용한 우회 검증은 하지 않았다. 실패 증거는 postgres-tests.log와 postgres-tests-escalated.log에 보관했다.

## 운영 반영 명령 — 사용자 실행 후 확인 완료

프로젝트의 서버 운용 규칙에 따라 사용자가 아래 명령으로 재시작했고, 위 최종 확인에서 새 릴리스 반영을 검증했다.

```
./agentcon restart frontend
./agentcon restart admin
```

두 서비스는 새 A/B 패키지를 사용해야 한다. 이번 변경에는 Jobs·Execution 재시작, DB 마이그레이션, Worker 배포가 필요하지 않다. 운영 반영 뒤에는 새 릴리스 readiness와 차단 상태 표시를 재확인한다. 재방문율 개선과 실제 Provider 업무 성공은 이후 운영 데이터로 별도 평가한다.
