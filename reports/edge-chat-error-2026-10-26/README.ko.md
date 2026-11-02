# Chat Edge 응답 오류 분석과 수정

## 확인된 사실과 진단 한계

- 운영 출력 원장에 2026-10-26 06:53:19 KST의 `error:chat:edge_error` 1건이 있다. 진단 초기 최근 24시간 Chat 관측은 Edge Origin 중계 47건과 오류 1건이었다.
- 같은 시각 전후 3분의 Cloudflare 집계는 요청 15건, Worker 런타임 오류 0건이다. `cloudflare-window.json`에 읽기 전용 조회 결과를 보존했다.
- 당시 배포 점검 보고서 `reports/strategy-design-2.1-development-2026-10-26/post-deploy/REPORT.ko.md`에 별도 채팅 진단 1회의 JSON 파싱 실패와 후속 HTTP 200 JSON 응답이 기록돼 있다. 점검 도구는 실패 당시 HTTP 상태와 Content-Type을 보존하지 않았다.
- 기존 Worker 소스에서 `error:chat:edge_error`는 HTTP 5xx 응답을 받는 경로에서 기록된다. Origin 중계 응답도 같은 사유로 집계했다. 따라서 이 기록을 Worker CPU 장애나 스트림 중단으로 단정할 수 없다.
- 현재 기록에는 해당 응답의 실제 5xx 상태와 본문이 없다. Cloudflare 또는 Origin 사이의 일시적인 비정상 응답 가능성이 있지만, 구체적인 502/503 등의 원인을 확정하지 않는다. 운영 Origin 로그에서도 해당 시각의 대응 애플리케이션 예외를 확인하지 못했다.

## 수정한 동작

1. Chat POST(`/chat`, `/`)에서 중간 서버의 HTML 등 비 JSON 5xx 응답을 받으면 원래 상태를 유지한 안전한 JSON 오류로 반환한다. 본문을 분석하거나 버퍼링하지 않고 취소한다. 이미 구조화된 서비스 오류와 `Retry-After`는 보존한다.
2. Origin 연결 예외는 개인정보·URL·예외 문자열을 포함하지 않는 JSON 503으로 반환한다. 실패한 POST는 자동 재전송하지 않아 대화나 실행이 중복 처리되는 것을 방지한다.
3. Origin HTTP 5xx, Edge HTTP 5xx, 연결 실패, 스트림 중단, 확인된 클라이언트 취소를 구분한다. HTTP 상태는 제한된 사유 코드에 포함한다.
4. 원래 계측에서 빠지던 부분 스트림 실패도 기록한다. 완료 시에만 성공을 기록하며, 요청당 관측 확정은 한 번이다. 전체 응답 완료를 기다리지 않고 청크를 즉시 전달한다.
5. 기존 서버가 새 관측 사유를 아직 지원하지 않으면 같은 관측 ID를 유지한 메타데이터만 기존 사유로 재전송한다. Provider나 Chat POST는 다시 호출하지 않는다.
6. Admin에 `응답·전달 오류 사유`를 추가하고 HTTP 상태·스트림 중단을 구분한다. 과거 `edge_error`는 `과거 응답 오류 · 상세 미수집`으로 표시하며 과거 데이터를 추정해 덮어쓰지 않는다.

과거 오류 이력 1건은 보존한다. 선택한 기간에서 벗어날 때까지 집계에 남는다. 새 원인 코드의 세부 표시는 Frontend·Admin 새 배포본 활성화 후 적용된다.

## 검증

- Worker 전체 82개 통과: `worker-full.log`.
- API·보안 93개 통과: `python-full.log`.
- 격리 Chromium 4개 통과: `browser.log`. 밝은 데스크톱·어두운 모바일의 사유 표시, 필터, 갱신 실패 보존, 짧은 Ticket 및 동일 저장 결과 복구를 확인했다.
- 공개 콘텐츠 294개 파일, 위반 0개: `content-check.log`.
- 변경한 Python 코드의 보안 검사: 기존 경고 1개, 새 경고 0개. 기존 관측 실패를 업무 실패로 전파하지 않는 `S110` 경고는 보존했다: `security-summary.json`.
- 실제 공개 Chat 합성 검색 1회: HTTP 200, JSON 정상, 추천 2개, `X-Execution-Delivery: edge`, Origin 결과 중계. 외부 Provider 업무 실행과 Workflow 실행은 요청하지 않았다: `live-chat-before.json`.

HTTP 오류·호환 관측과 기존 실제 첫 이벤트 전송은 workerd/Miniflare에서 확인했다. 신규 중간 스트림 단절·취소는 제어 가능한 표준 Fetch/Streams 하네스로 검사했다. Miniflare의 Node outboundService Origin 모의 스트림을 수동 완료 대기와 결합한 초기 검사에서는 하네스가 대기해 중단했다. 이 결과를 운영 실패나 통과로 집계하지 않았다. 첫 실행의 포트 권한 제한과 운영 가상환경의 pytest 부재는 격리 실행 권한과 기존 `.venv-tests`로 해결했다.

장기 부하나 전체 Provider 실호출 검증을 포함하는 결과는 아니다.

## 운영 반영 완료

**사용자의 Frontend·Admin 교체와 Worker 배포 승인을 받아 운영 반영과 확인을 완료했다.** Frontend·Admin은 A/B 방식으로 교체했고 이전 슬롯을 보존했다. Jobs·Execution의 release와 PID는 그대로 유지했다. DB 구조와 기존 오류 이력은 변경하지 않았다.

`staged-releases.json`:

- Frontend: `edge-chat-observation-frontend-20261026-r1`. 현재 `frontend-layout-system-20261026-r2`에서 `output_monitor.py` 1개만 변경하고 나머지 1286개 파일 보존.
- Admin: `edge-chat-observation-admin-20261026-r1`. 현재 `dependency-security-20261026-r3`에서 같은 Python 파일과 Admin 화면 JS 2개만 변경하고 나머지 1284개 파일 보존.
- Jobs·Execution 교체, DB 스키마 변경, 새로운 Secret, Route 변경은 필요 없다.
- 현재 Worker 활성 소스의 Provider 호출·권한·결과 처리 부분은 모두 보존했다. 차이는 파일 하단 Chat 오류·관측 처리뿐이다: `worker.patch`, `worker-live.json`.
- 만료된 기존 OAuth는 이미 승인된 offline_access 연결로 갱신하고 계정·Zone·기존 활성 버전을 읽기 확인했다. 새로운 권한을 추가하지 않았다.

승인 후 완료한 웹 명령:

```bash
agentcon deploy frontend edge-chat-observation-frontend-20261026-r1
agentcon deploy admin edge-chat-observation-admin-20261026-r1
agentcon status
```

Worker는 `cloudflare-release.py upload --apply`, `deploy --apply`로 동일 계정에 배포했다. 기존 Secret을 상속하고 Route는 변경하지 않았다. 배포 직전 기존 활성 버전과 대조했다. 활성 Worker는 `abc28562-23b3-4b22-8167-3106edb9ce9e`이며 100% 반영됐다. 기존 버전은 `edf9cefa-7e8e-4358-8cdf-3238c547bd04`다.

### 운영 검증 결과

- 배포 후 운영 점검 15개 통과, 실패 0개: `live-verification.json`.
- Frontend·Admin의 목표 release와 private readiness 정상. `retained`는 이전 웹 슬롯을 보존한 정상 배포 상태다.
- Jobs PID 50757, Execution PID 49129 및 release 유지. 두 역할 heartbeat 정상.
- 실제 공개 Chat 합성 검색 1회: HTTP 200, JSON 정상, 추천 3개, Edge 전달과 Origin 중계 표시 확인. 약 3초의 소수 표본으로 장기 가용성 수치를 주장하지 않는다.
- 신규 PostgreSQL 모니터 집계 필드 확인. Admin 화면 JS가 배포본과 정확히 일치하고, 미인증 Admin API는 403, 공개 Admin 접근은 404.
- 실제 Worker 서명 검증 3개 통과: 상태 확인, 2바이트, 40KB 합성 결과. 외부 Provider 업무 실행은 0회: `live-synthetic-probes.json`.
- 활성 Worker 코드를 다시 읽어 검증된 소스와 SHA-256이 일치함을 확인: `worker-live.json`. 배포 전 소스와 버전은 `worker-live-before.*`에 보존.
- Worker 활성화 이후 확인 구간의 Chat 관측은 정상 Edge 중계 1건, 새 오류 0건: `post-deploy-chat-counts.json`. 과거 Chat 오류 1건은 원장에 그대로 있다. 장기 추적 결과로 확대하지 않는다.

실제 운영 Admin 개인 세션 로그인과 장애 주입은 수행하지 않았다. 새 오류 사유의 화면 렌더링은 앞선 격리 Chromium 검사로 확인했고, 운영에서는 자산·인증 경계·읽기 전용 집계를 확인했다. Admin 화면을 새로고침하면 새 사유 표시를 확인할 수 있다.

### 복구 자료

기존 Worker 버전은 `cloudflare-upload.json`의 `previous_versions`에, 기존 웹 슬롯은 `services-before-deploy.json`에 보존했다. 필요 시 Worker를 먼저 복구한 뒤 해당 웹 슬롯을 복구한다. 이는 참고 명령이며 이번 작업에서 실행하지 않았다.

```bash
.venv/bin/python reports/edge-chat-error-2026-10-26/cloudflare-release.py rollback --apply
agentcon rollback frontend
agentcon rollback admin
```

## 참고

Cloudflare 활성 코드 대조는 [공식 Worker 코드 조회 API](https://developers.cloudflare.com/api/resources/workers/subresources/scripts/subresources/content/methods/get/)를 사용했다. 정상화 판단은 외부 자료 자체가 아닌 운영 원장·실제 활성 코드·Cloudflare 집계·회귀 검사에 근거한다.
