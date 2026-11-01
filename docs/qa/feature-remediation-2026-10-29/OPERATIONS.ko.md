# 남은 UX·API 개선 운영 안내

2026-10-29. 최초 네 서비스 r4 반영에 이어, 웹 두 서비스의 검색·화면 보완 r2까지 완료했습니다. 현재 웹은 experience-search 각 역할 r2이며 jobs·execution은 experience 각 역할 r4입니다. 실제 결과와 추가 정렬 보완의 상태는 reports/feature-remediation-2026-10-29/DEPLOYMENT.ko.md에 기록했습니다. 아래는 적용 절차의 참고 문서입니다.

## 90일 대화 보관

- 사용자 승인: 대화는 90일 보관 후 자동 삭제합니다. 기존 방문자별 최근 200개 메시지 상한도 유지합니다. 오래된 기존 대화도 대상입니다.
- 읽기 시점부터 90일이 지난 메시지는 반환하지 않습니다. jobs의 독립 유지관리 슬롯이 매시간 만료 메시지를 물리 삭제합니다. 한 번에 각 1,000개씩 처리하며 잔량이 있으면 10초 뒤 계속합니다. 실패 시 재시도합니다.
- 90일 만료 추천 관심사와 90일 동안 사용되지 않은 추천·도구 문맥도 정리합니다. 재방문 요청이 만료 문맥을 되살리지 않도록 touch 시점에도 초기화합니다.
- 워크스페이스 문서, 실행 증거, 목적별 알림 동의, 검증된 연락처 및 별도 결과 피드백은 이 메시지 삭제 작업의 대상이 아닙니다. 해당 기록의 독립 정책은 유지됩니다.
- 프론트엔드만 교체하면 자동 삭제 작업은 기동되지 않습니다. jobs 배포가 필요합니다. 어드민·execution도 동일한 저장 규칙과 SQL 카탈로그를 사용하도록 패키지를 정렬합니다.
- 운영 백업은 메시지 테이블의 실시간 삭제와 별도입니다. 복원 시 만료 정리가 먼저 수행되어야 하며, 보관 정책을 변경할 경우 백업 정책도 별도로 검토합니다.

## 실제 상태 JSON

`/status.json`의 availability는 jobs가 공개 상태 경로에 실제 요청한 성공률입니다. 30일 관측 창, 관측 개수, 최초·최근 관측 시각, 평균 응답 시간과 최근 실패 구간을 제공합니다. 무관측·3분 넘게 갱신되지 않은 상태는 unknown입니다. 처음부터 30일을 측정했다거나 SLA라고 표현하지 않습니다. 수집이 오래 걸려도 한 슬롯의 유지관리 작업이 따로 진행됩니다. 상태 경로 자체를 점검한 기록으로, 모든 기능의 성공을 보장하지 않습니다.

## 서명된 공개 조회: 선택적 Web Bot Auth

기본값은 신뢰 키 없음입니다. 일반 익명 조회는 계속 사용할 수 있습니다. 실제 협력 봇의 검증된 공개 키가 확보된 경우에만 아래 설정을 만듭니다. 요청자가 제출한 URL에서 키를 자동으로 가져오지 않습니다.

1. 제공자의 독립적인 공식 경로에서 HTTPS origin과 Ed25519 공개 JWK를 확인합니다. 운영자가 origin→공개 키 목록을 담은 JSON 파일을 만들고 권한을 0600으로 지정합니다. `kty=OKP`, `crv=Ed25519`, 32바이트 공개 키의 base64url `x`만 필요하며 비밀 키 `d`는 허용하지 않습니다. 키 회전 시 확인된 신·구 공개 키를 일시적으로 함께 둘 수 있습니다.
2. `gateway-data/web-bot-auth.env`를 0600으로 만들고 `WEB_BOT_TRUST_FILE=gateway-data/web-bot-trusted-keys.json`처럼 경로만 지정합니다. 이 파일은 선택 사항이며 구형 보존 릴리스는 읽지 않습니다. 이 문서는 실제 신뢰 키나 설정 파일을 생성하지 않습니다.
3. 이 구현은 RFC 9421 전체를 임의 해석하는 대신 제한된 프로필을 사용합니다. 서명은 authority·signature-agent를 반드시 포함해야 합니다. 권장 프로필은 method·path·query도 포함합니다. `created`, `expires`, JWK thumbprint `keyid`, `tag="web-bot-auth"`, 16~128자 nonce가 필수입니다. 최대 서명 수명은 5분이며 중복 헤더·서명·재사용 nonce는 상향 한도로 인정하지 않습니다.
4. Redis의 원자적 SET NX가 재생을 차단합니다. Redis를 사용할 수 없거나 서명을 검증하지 못하면 상향 한도를 부여하지 않습니다. 사칭 User-Agent만으로 인증되지 않습니다.
5. 검증된 GET/HEAD는 공개 read/explore 한도만 두 배로 받습니다. 워크스페이스 로그인, 실행, 결제, 등록 권한이나 Chat 전송 한도는 부여하지 않습니다. 응답은 `Web-Bot-Auth: verified`와 `no-store`입니다. 기본 한도는 동적 운영 제한에 따라 달라집니다.
6. 신뢰 파일 변경은 이를 읽는 웹 역할의 승인된 교체로 반영하고, 실제 서명 클라이언트와 함께 점검합니다. 현재 자동 테스트는 격리된 임시 키로 수행한 것이며 특정 외부 봇과 운영 상호운용을 인증한 것이 아닙니다.

공식 참고: [Cloudflare Web Bot Auth](https://developers.cloudflare.com/bots/reference/bot-verification/web-bot-auth/), [RFC 9421](https://www.rfc-editor.org/rfc/rfc9421.html).

## 브라우저 검색 도구

지원 브라우저의 `document.modelContext.registerTool`을 우선 사용하고 구형 API는 기능 감지로 대응합니다. search_agents는 공개 조회, recommend_agents는 세션 대화 기록이 발생하는 추천입니다. 실행·결제 도구는 등록하지 않습니다. 입력 크기, 선택 프로토콜, 중단 신호, 페이지 생명주기를 처리하며 방문 토큰은 세션 전송에만 둡니다. 미지원 브라우저의 기존 UI 사용에는 영향이 없습니다.

격리 Chromium의 등록·호출·취소·세션 검증에 이어, 운영 브라우저의 실제 WebMCP 도구 등록과 공개 검색 호출도 확인했습니다. 브라우저 자체 에이전트 제품 전체의 인증을 의미하지 않습니다. [Chrome 공식 API 안내](https://developer.chrome.com/docs/modern-web-guidance/guides/webmcp/agentic-javascript-tools)를 기준으로 구현했습니다.

## HTTP 계약 및 캐시

REST 오류를 RFC 9457 형식으로 통일하고 기존 클라이언트의 error_code 별칭은 보존합니다. JSON-RPC·x402 같은 프로토콜 고유 응답은 유지합니다. 실제 제한기의 단일 판정에서 남은 한도를 가져오며, Retry-After는 재시도 제한 응답에 제공합니다. 캐시 허용 공개 조회에만 30초 공유 캐시·ETag·304를 적용합니다. 쿠키·자격 증명·방문 토큰·서명 요청은 공유하지 않습니다. 캐시된 quota 헤더는 원본 응답 시점의 관측이며 실제 허용 여부는 원본 제한기가 판정합니다.

정적 파일의 기존 해시 버전·immutable 캐시·압축은 유지합니다. HTML은 요청별 CSP nonce가 있으므로 본문과 CSP가 어긋나는 단순 304 캐시로 바꾸지 않습니다. 실제 LCP·TTFB p75 달성 여부는 운영 반영 후 별도 관측해야 하며 격리 테스트 시간을 현장 성능으로 사용하지 않습니다.

## 최초 r4 적용 순서 (이력 — 다시 실행할 필요 없음)

현재 활성 qa7-repair 각 역할 r4를 기준으로 경험 개선 각 역할 r4 패키지를 만들었습니다. 이 네 후보는 사용자 승인으로 이미 운영에 적용했습니다. 먼저 아래 추가형 스키마 작업을 적용한 뒤 네 역할을 교체해야 합니다. 새 DB 초기화 명령을 실행하면 안 됩니다.

```bash
.venv/bin/python -m scripts.migrate_public_experience --check
.venv/bin/python -m scripts.migrate_public_experience --apply
.venv/bin/python -m scripts.migrate_public_experience --check
./agentcon deploy frontend experience-frontend-20261029-r4
./agentcon deploy admin experience-admin-20261029-r4
./agentcon worker-deploy jobs experience-jobs-20261029-r4
./agentcon worker-deploy execution experience-execution-20261029-r4
./agentcon status
```

첫 check는 테이블·인덱스가 없으면 ready=false와 종료 코드 1이 정상입니다. apply는 검토된 빈 상태 기록 테이블 1개와 CONCURRENTLY 인덱스 2개만 추가합니다. 기존 행·기존 테이블 구조는 변경하지 않습니다. 다른 스키마/잘못된 기존 인덱스는 자동으로 덮어쓰지 않습니다. 실패하면 배포를 진행하지 말고 결과를 검토합니다. 구형 서비스는 추가 테이블·인덱스와 함께 동작할 수 있게 기존 프로필을 유지합니다.

반영 후 확인: status의 네 활성 릴리스, 서비스 진입·Chat 추천/후속 지시어/피드백 사유/공개 공유·비교, Test 캐시 조회 시각, 상태 관측 증가, jobs의 유지관리 실패 로그, 만료 대화 재노출 여부입니다. HTML은 no-store이므로 기존 브라우저 탭은 한 번 다시 불러옵니다. 상태 성공률은 실제 관측이 쌓여야 나타납니다. 만료 대화 삭제는 정책에 따른 영구 변경이므로 롤백으로 되살아나지 않습니다.

jobs·execution 교체 시 신규 작업의 처리가 잠시 대기할 수 있습니다. 데이터베이스·모델 서버·프록시를 재시작할 필요는 없습니다. 이번 네 서비스 반영은 명시적 승인으로 진행했습니다. 이후 새 운영 교체는 저장소 규칙을 따릅니다.

## 최종 적용 상태

프론트엔드·어드민은 사용자 승인으로 `experience-search-frontend-20261029-r2`·`experience-search-admin-20261029-r2`까지 교체·실제 화면 검증을 완료했습니다. DB·jobs·execution의 추가 변경은 없었습니다. 현재 추가 실행이나 승인 요청은 없습니다. 이미 열어둔 탭에서는 한 번 새로고침하면 새 정렬 자산을 사용합니다. 상태만 확인하려면 `./agentcon status`를 사용합니다.
