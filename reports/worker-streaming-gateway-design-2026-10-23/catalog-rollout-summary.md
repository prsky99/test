> 후속 CPU/SSE 안정화가 적용되었습니다. 현재 버전·실측·남은 범위는 [최신 적용 기록](cpu-fix-summary.md)을 확인합니다. 아래는 최초 카탈로그 전환 시점 기록입니다.

# 카탈로그 Provider Edge 운영 반영

등록된 공개 Provider의 적격 요청을 개별 ID 추가 없이 Edge로 자동 라우팅하도록 배포했다. 완료 확인 시 preferred_backend=worker, routing_scope=catalog_policy이며 A2A·MCP·x402가 활성 상태다. 기존 CHS Backflow 개별 핀은 유지한다. 전체 카탈로그의 Provider를 개별 실측 완료했다는 표시는 하지 않는다.

## 실제 적용 범위

- `/api/gateway/a2a/*`: A2A 0.3 및 1.0 정보성 요청. JSON·SSE 응답, 완료 Task의 artifacts 및 agent status.message/history, typed data를 처리한다.
- `/api/gateway/mcp/*`: 공개 안전 도구의 tools/call 결과를 Worker에서 직접 전달한다. initialize/list 등의 가상 Gateway 메타데이터 API는 기존 계약을 유지한다.
- `/api/gateway/x402/*`: 결제·서명 없는 GET/POST probe. 실제 결제를 실행하지 않으며 유효한 402 challenge는 인증/결제 요구로 기록한다.
- `/api/test/execute` 및 기존 A2A Edge SDK. 공개 stateless Gateway는 다운로드 웹앱을 위한 CORS와 A2A/MCP protocol header preflight를 지원한다.
- 별도 Workspace/Workflow 서버 실행 API와 Jobs/Execution의 Provider 호출 경로는 기존 구성이다.

## 실행과 보안

요청마다 현재 활성·health·인증·가격·격리 정책과 capability version을 확인한다. MCP는 전체 등록 입력 Schema와 안전성을 검사하고 full/compact metadata의 일관성을 확인한다. Worker의 원격 full Schema 해시가 정확히 같으면 추가 비교 callback을 생략하고, 확정할 수 없으면 기존 HMAC 인증 서버 검증을 사용한다. 실제 Schema 불일치는 실행 전에 차단한다.

Provider의 알려진 실행 URL과 Origin을 플랫폼 주소로 투영하고 secret/token/session 필드를 제거한다. 브라우저 Authorization·Cookie·IP·MCP 세션을 Provider에 복사하지 않는다. 독립된 인용 URL은 유지한다. 임의 자연어·다른 표기·프레임 간 문자열까지 완전 은닉을 보장하는 프로필은 아니다.

MCP metadata와 실제 도구 결과는 최종적으로 Worker에서 직접 처리한다. 결과 본문을 제어 서버에 복사하지 않으며, 해시 비교를 확정할 수 없을 때만 Schema를 서버에서 확인한다. Origin으로 metadata 전체를 옮기는 실험은 통신·대기 증가와 CPU 목표 미충족을 확인해 제거했다.

## 운영 배포

- Worker: `77241c53-e1ea-4977-aae5-f608dd2ecfe1`, 100%.
- Frontend: `edge-catalog-frontend-20261023-193728`, a.
- Admin: `edge-catalog-admin-20261023-193728`, b. 리뉴얼 중 반영된 최신 Admin을 기준으로 별도 복제했다.
- Jobs·Execution의 Release와 PID는 최초 작업 전후 동일하다. 신규 DB 마이그레이션은 없다.
- 기존 배포본의 나머지 manifest 파일 1,149개/1,156개를 각각 보존했다. 효과 없던 실험 모듈만 후보 배포본에서 제거했다.
- 5개 Route 전부 request_limit_fail_open=true. 기존 encrypted Secret 이름과 무료 운영 설정을 유지했다. 설정 백업은 ignored owner-only 파일이며 보고서에 비밀값을 넣지 않았다.

## 검증

Echo86984(A2A1.0), Weather87654(A2A0.3 완료 Task), SiteKrs158466(MCP), x40210144(probe)의 실제 Worker 처리 기록을 확인했다. Gateway 및 Testbench 응답 바이트가 완료 기록과 일치하고 표본 공개 응답에서 Provider 호스트 노출이 없었다. x402의 PROVIDER_AUTH_REQUIRED는 결제를 실행하지 않은 정상적인 인증 요구 분류다. 세부 시점·버전·해시는 개별 live JSON에 보존했다.

최종 Python/API/Chromium 170개, workerd 29개 통과. Bandit 발견 0건, 공개 frontend 249개 파일의 content 정책 위반 0건. 운영에서 unsigned schema callback 차단, SDK cross-Origin prepare 차단, 공개 MCP CORS도 확인했다. Computer Use의 최종 화면 조회는 timeout으로 끝났고, 공식 API/CLI 상태를 검증 근거로 사용했다.

## 무료 운영과 남은 한계

무료 기준은 하루 100,000 Worker 요청, HTTP CPU 10ms다. Soft limit은 계정 관찰 요청 수+누적 로컬 예약 90,000으로 보수적으로 적용한다. 관찰·서명 health가 확인되지 않거나 runtime 오류가 관측되면 신규 실행을 Origin으로 보호한다. 완료 직전 health_unconfirmed에 따른 실제 Origin 선택과 정상 서명 health 확인 후 worker 회복을 확인했다. Runtime 오류 차단은 검증 후 운영자가 해제하며, 이미 실행권을 취득한 작업은 자동 재실행하지 않는다.

**CPU 10ms 상시 준수는 확인하지 못했다. 최종 MCP 표본은 14.8ms(원값14.767ms), 해당 관찰 구간 runtime 오류는 0건이다.** Cloudflare는 드문 초과에 일부 여유를 제공하지만 지속적으로 초과하면 실행을 종료할 수 있다고 설명한다. 현재의 성공 표본으로 지속 부하 안정성이나 모든 Provider의 CPU 적합성을 보장하지 않는다. 무료 플랜 유지와 신규 요청의 Origin 복귀가 보호 경계다. 실제 일일 한도를 고의로 소진하는 검증은 수행하지 않았다.

입력8KB, 메시지2,000자, 프레임/문자열16KB, 원천64KB, 출력48KB, 실행8초의 제한 프로필이다. 큰 MCP 계약·미지원 URL/프로필은 실행 전에 Origin으로 전달한다. 인증·위험 도구·격리·Schema 실패는 기존 정책으로 거부한다. 실행 후 예상 밖의 대용량/비표준 응답은 안전한 오류로 끝내며 중복 Origin 실행을 하지 않는다.

Worker 경로는 실제 결과 본문의 애플리케이션 서버 egress를 줄인다. 제어 메타데이터·기존 서버비·Provider 사용료는 별도이며 Origin 복귀 시 기존 결과 본문 네트워크 비용이 돌아온다. 유료 업그레이드나 추가 유료 저장소를 만들지 않았다.

공식 한도: [Cloudflare Workers limits](https://developers.cloudflare.com/workers/platform/limits/).

근거: `catalog-edge-validation.json`, `catalog-edge-cf-status.json`, `catalog-edge-policy.json`, `catalog-edge-post-services.json`, `catalog-edge-cpu.json`, `catalog-edge-live-*.json`, `catalog-edge-tests.xml`, `catalog-edge-worker-final-tests.log`.
