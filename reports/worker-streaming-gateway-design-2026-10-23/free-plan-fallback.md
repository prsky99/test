# 무료 Workers 우선 사용과 기존 Gateway 복귀 설계

기준일: 2026년 10월 23일 · 최신 운영 설계 · 실제 플랜·Route·서비스 변경 없음

## 1. 운영 원칙

**Workers Free로 결과를 전달하고, 무료 한도에 가까워지거나 초과하면 새 요청을 기존 Gateway 서버의 중계 경로로 전환한다.** 사용자에게 원천 Provider 주소를 전달하지 않는 원칙은 두 경로에 동일하게 적용한다.

- 정상: `사용자 ↔ 우리 도메인의 Worker ↔ Provider`
- 복귀: `사용자 ↔ 우리 도메인의 기존 Origin Gateway ↔ Provider`
- Cloudflare Workers 유료 플랜으로 자동 전환하지 않는다. 이번 설계에 유료 플랜 등록이나 부가 서비스 자동 구매는 포함하지 않는다.
- Worker 경로에서는 기존 임대 서버의 본문 중계 비용을 줄인다. Origin 복귀 중에는 현재 방식의 서버 CPU·본문 egress 비용이 다시 발생한다.
- 경로 전환은 실행 전의 요청을 대상으로 한다. Provider가 이미 실행했거나 실행 여부가 불명확한 작업은 동일 실행 ID로 확인한다.

이 설계는 이전 문서의 ‘Edge 장애 시 작은 오류로 종료’ 원칙을 **검증된 Origin fallback 허용**으로 변경한다. 안전성·인증·원천 주소 보호가 빠진 임의 우회는 허용하지 않는다.

이것은 인프라 전달 경로의 fallback이다. 다른 Agent·Provider로 바꾸는 상품상의 유료 fallback과 구분한다. 기존 사용자가 허용받은 같은 작업을 같은 Provider에서 계속 수행하는 데 추가 구독을 요구하거나 Credit을 두 번 차감하지 않는다. 다른 Provider로 변경하는 기능에는 기존 자격·승인·중복 실행 정책을 그대로 적용한다.

## 2. 공식 무료 한도와 초기 운영 설정

Workers Free의 공식 일일 요청 한도는 **계정 기준 10만 회**, CPU 한도는 **요청당 10ms**다. 요청 한도는 UTC 00:00, 한국 시간 09:00에 초기화된다. 사이트용 Cloudflare Free·Pro와 Workers 구독은 구분한다.

Cloudflare 문서는 일일 한도를 넘을 때 Route의 다음 동작을 설명한다.

- `fail open`: Worker를 건너뛰어 Worker가 없는 상태의 Origin 처리로 진행한다.
- `fail closed`: Error 1027을 반환한다.

이번 설계는 **전용 Worker Route에 한해 fail open**을 사용한다. CPU 한도 초과의 Error 1102나 일반 crash까지 모두 자동 Origin 복구가 된다고 가정하지 않는다.

[Workers 공식 한도·Route fail mode](https://developers.cloudflare.com/workers/platform/limits/) · [공식 요금](https://developers.cloudflare.com/workers/platform/pricing/)

초기 제안 설정:

- 일일 공식 요청 한도: 100,000회.
- 사전 Origin 전환 기준: 계정 요청량 추정 90,000회 또는 보수적으로 산정한 잔여 요청 부족. 90,000회는 Cloudflare 기본값이 아닌 우리 설정 제안이다.
- 여유분: 다른 Worker·Pages Functions·CORS·재연결·download·health probe와 관측 지연을 고려해 남긴다. 요청량을 정확히 90,000회에서 차단한다고 보장하지 않는다.
- CPU 적합성: 실제 입력·stream·서명 검증·오류를 포함한 runtime 시험에서 무료 한도 적합성을 확인한다. 일일 총 CPU 소진과 요청별 CPU 한도 초과를 구분한다.
- 자동 유료 전환: 사용하지 않음.

공유 계정의 다른 사용량과 악성·비정상 유입 때문에 사전 전환 추정치가 빗나갈 수 있다. 공식 한도 초과 시의 Route fail open과 Origin의 독립 검증이 최종 복귀 경로를 제공한다.

## 3. 도메인·Route·Origin Adapter

기존 제어 API는 Worker Route 밖에 둔다.

- `POST /api/gateway-execution/v1/runs`: 실행 승인·예약·전달 경로 선택.
- `GET /api/gateway-execution/v1/runs/{run_id}`: 상태·안전한 재접속 안내. 결과 본문을 포함하지 않는 기본 제어 조회.
- `agentconcierge.biz/api/edge-gateway/v1/*`: Worker 우선 Route. **fail open** 설정.
- `/api/origin-gateway/v1/*`: 기존 서버의 명시적 fallback 경로. Worker Route와 겹치지 않음.

Origin에는 `/api/edge-gateway/v1/*`와 `/api/origin-gateway/v1/*`를 같은 호환 Adapter로 받는 기능을 추가한다. 한도 초과로 Worker가 생략되어도 최초 URL·method·권한·body를 기존 서버가 올바르게 처리해야 한다. 현재 코드에는 이 신규 Adapter가 없으므로 Route 설정만으로 복귀가 완성되지는 않는다.

사전 전환 모드에서 제어 API는 SDK에 `/api/origin-gateway/v1/...` 경로를 발급한다. SDK는 같은 플랫폼의 발급받은 경로를 호출하므로 Worker를 불필요하게 거치지 않는다. 단순히 Worker 내부에서 Origin을 호출해 ‘복귀’하면 Worker 유입 요청 한도는 계속 소비하므로 별도의 우회 경로가 필요하다.

원천 URL로 302·307 redirect하지 않는다. Cookie·자격·Provider URL을 포함한 raw 응답도 전달하지 않는다. Browser DevTools에 보이는 실행 host는 두 모드에서 모두 `agentconcierge.biz`다. Provider 본문 내부의 모든 주소에 관한 사전 출력 계약 경계는 기존 설계와 같다.

## 4. 보안 경계를 보존한 fail open

Cloudflare는 보안이 Worker에만 있는 경우 fail closed를 권고한다. 이번 구조에서는 **Origin이 Worker 없이도 모든 필수 인증·승인·동시성·입력 policy·원천 주소 투영을 검증**하는 것을 fail open 활성화의 선행 조건으로 둔다.

- Worker 또는 Origin이 같은 platform 실행 Token을 검증한다. audience는 Worker 전용에서 **platform 실행 Gateway 공용 audience**로 정리하고 세부 실행·tenant·배포·scope를 검증한다.
- Token에는 허용된 두 platform 전달 경로와 fallback 권한을 묶고 Provider Endpoint·key는 넣지 않는다.
- 실행 준비에서 `allow_origin_fallback`은 두 backend의 기능·보안 계약을 확인한 경우에만 서버가 설정한다. 단순 Client header로 fallback 권한을 만들지 않는다.
- Origin은 ‘Worker를 통과했음’이라는 Client 지정 header를 믿지 않는다. HTTP method·body·입력 hash가 필요한 계약·배포 버전을 직접 검증한다.
- Worker와 Origin 모두 동일 DB의 원자적 실행 claim을 사용한다. 동시 두 경로가 도착해도 하나만 dispatch 권한을 갖는다.
- 관리용 내부 서비스 인증과 사용자용 실행 인증을 분리한다. 신규 우회 경로가 공개 내부 API나 무제한 proxy가 되지 않도록 한다.
- Origin을 직접 호출하는 상황에서도 같은 인증·rate limit·Provider 허용 목록·세입자 격리를 적용한다.

Origin 검증을 완료하기 전에는 이 Route를 fail open으로 배포하지 않는다. 적용 후에도 CORS·Origin 검사는 인증을 대신하지 않는다.

## 5. 전달 모드와 전환

### Worker 사용 가능

제어 API가 무료 잔여 요청과 CPU 적합성을 확인해 Worker 경로를 발급한다. Worker는 작은 원자적 claim을 확정한 뒤 Provider를 직접 호출한다. 결과는 Worker가 전달한다.

### 무료 한도 접근·소진

새 실행은 Origin 경로를 발급한다. 이미 발급된 Edge 경로가 일일 한도 초과 후 호출되면 Route의 fail open으로 Origin Adapter에 도달할 수 있다. Origin은 Token과 실행 상태를 검증한 뒤 동일 claim 절차를 수행한다.

진행 중인 stream은 강제로 Origin으로 옮기지 않는다. 정상 연결은 계속 처리하도록 하고 중단되면 기존 작업의 상태·재연결 가능성을 확인한다. 일일 한도 도달이 모든 기존 연결의 즉시 종료를 뜻한다고 가정하지 않는다.

### Worker CPU 한도·일반 오류

CPU 오류는 계정의 일일 요청 한도와 별개다. 오류가 반복되는 profile 또는 Worker 배포를 새 요청에서 제외하고 Origin으로 전환한다. Client의 오류 응답·timeout만으로 원천 실행이 시작되지 않았다고 판단하지 않는다.

SDK는 Worker 실패 후 제어 API에서 해당 실행을 확인한다. DB가 아직 `prepared`이고 claim·dispatch 권한이 발급되지 않았음을 원자적으로 확인할 수 있을 때만 Origin이 같은 실행을 시작할 수 있다. claim 이후에는 Provider의 idempotency·조회로 실행 상태를 먼저 조정한다.

### 무료 한도 초기화 후 복귀

한국 시간 09:00 이후 기존 서버 측 관리 작업이 계정의 일일 window 변경을 확인한다. 실제 Worker health probe와 소량 신규 실행의 CPU·오류 상태를 확인한 뒤 Worker 발급을 재개한다. health probe도 무료 요청을 사용한다.

일일 요청 소진 사유만 해제하며, CPU 부적합·보안 격리·관리자 고정·원천 장애 사유는 별도로 유지한다. 원인이 남아 있으면 Origin 모드를 계속 사용한다. Cloudflare가 hard-limit bypass를 자동 해제하는 시점과 우리 서비스의 사전 전환 상태 해제 시점을 구분한다.

이 문서의 관리 작업은 향후 구현할 운영 로직이다. 이번에 예약 작업이나 모니터링 자동화를 실제 등록하지 않았다.

## 6. 중복 실행·stream 중단 처리

두 backend의 공통 상태는 기존 설계의 `prepared → dispatch_reserved → running → succeeded / failed / outcome_unknown`을 사용한다. 실행 소유 backend와 attempt ID를 DB에 기록하고 lease 만료만으로 재실행하지 않는다.

- **실행 전:** 아무 backend도 claim하지 않았고 권한이 유효하면 원자적으로 Origin을 선택할 수 있다.
- **Worker claim 후:** Provider 호출 전후 crash를 Client 관측만으로 구분할 수 없다. Origin은 자동 재dispatch하지 않는다.
- **Provider 실행 중:** 같은 작업 ID로 상태·결과를 조회한다. 원천의 재연결을 지원하면 Origin이 기존 결과를 전달할 수 있다.
- **Provider idempotency 지원:** 동일한 원천 idempotency key로 계약에 따른 조회·안전한 재요청을 적용한다. 지원 확인 없이 exactly-once를 약속하지 않는다.
- **실행 여부 불명확:** `outcome_unknown`을 유지하고 조정한다. ‘무료 한도 초과’는 이미 시작한 업무를 다시 실행하는 허가가 아니다.
- **부분 파일·부분 SSE:** 이어받기가 지원되면 같은 artifact·task에서 재연결한다. 미지원이면 부분 결과를 구분하고 상태 확인으로 진행한다.

Worker에서 Origin으로 내부 위임하는 예외가 필요하면 **claim 이전에만** 수행하고 명시된 Origin 주소·자격을 사용한다. claim 이후 일반 실패 처리로 Origin에 같은 실행 POST를 보내는 구현은 금지한다.

## 7. ‘현재 상태로 복귀’의 정확한 지원 범위

현재 ManagedGateway는 제한된 동기 실행·결과 투영을 수행하고 공개 Workflow 경로에는 48,000 byte 노드 출력 제한이 있다. 기존 JSON 응답 API가 신규 SSE·대용량 파일·Range·지속 실행과 자동으로 같은 기능을 제공하지는 않는다.

무료 우선의 첫 적용 대상은 **현재 Origin에서도 실행 가능한 텍스트·도구·Workflow 범위**로 제한한다. Origin Adapter는 기존 검증·결과 투영을 재사용하고 필요하면 완료 결과를 platform terminal event로 감싼다. Origin에서는 결과가 완성된 뒤 한 번에 보일 수 있으며 이는 현재 처리 방식의 지연 특성을 따른다.

새 파일·대용량·Range·장기 작업은 Worker와 Origin 양쪽의 지원·권한·주소 보호·메모리 제한 검증을 완료한 후 활성화한다. 미지원 대형 파일을 기존 48KB 경로에 넣거나 제한을 무작정 해제하지 않는다.

Fallback 대상마다 기능 matrix를 서버에서 관리한다. `allow_origin_fallback=true`는 같은 입력·업무 의미·정산 정책으로 복구 가능한 경우에만 발급한다. 호환되지 않는 신규 기능은 무료 운영 초기 범위에서 제외해 ‘작동하는 기존 상태로 복귀’라는 약속을 지킨다.

## 8. 무료 플랜의 부가 서비스 병목 줄이기

이전 유료 Standard 전제의 정산 Queue를 무료 운영의 필수 경로에서 제거한다. v1은 기존 DB의 실행 시작 기록·outbox와 작은 callback·Provider 상태 조정으로 완료 이벤트를 관리한다. Worker의 `waitUntil()` 전송만을 수금의 유일한 근거로 쓰지 않는다.

현재 공식 Free Queue 한도는 하루 10,000 operations이며 일반적인 전달은 write·read·delete로 3 operations를 쓴다. 약 3,300개 메시지 수준에서 먼저 제약이 생길 수 있어 일 10만 Worker 요청을 처리하는 데 충분한 기본 정산 경로로 가정하지 않는다. 재시도·추가 event가 있으면 처리 가능한 실행 수는 더 줄어든다.

KV도 Free 쓰기 한도와 일관성 제약이 있으므로 실행마다 quota·lock·상태를 쓰지 않는다. 핵심 claim·잔액·배분·복귀 상태는 기존 transactional DB에 둔다. Free Queue·KV·Durable Objects를 향후 선택적으로 붙이면 각각의 한도·오류·복귀를 별도 검증한다.

[Cloudflare 부가 서비스 무료 제공량](https://developers.cloudflare.com/workers/platform/pricing/) · [waitUntil 수명](https://developers.cloudflare.com/workers/runtime-apis/context/#waituntil)

## 9. 관측·서버 용량·비용

제어 API가 발급한 Worker 요청 예약과 실제 관측을 기존 DB에서 합산한다. Cloudflare 계정 전체 사용량도 읽기 전용으로 대조한다. 집계 지연과 Worker가 실행되지 못한 요청을 고려해 추정량을 정확한 실시간 청구 카운터처럼 표시하지 않는다. 다른 Worker 사용량을 알 수 없거나 데이터가 오래되면 보수적으로 Origin을 선택한다.

계측: UTC 일일 window, 계정 요청 추정·여유분, Worker/Origin 실행 비중, 전환 사유, Worker CPU 오류, Origin 동시성·대기·실패, Origin 송신 byte, unknown 실행·정산 지연. 사용자 화면에는 내부 진단·개인정보·key를 표시하지 않는다.

현재 ManagedGateway의 bounded 동시 실행 자원은 Origin 복귀 시에도 유효하다. Edge 처리량 전체가 기존 서버 용량을 넘을 수 있으므로 tenant rate limit·bounded 동시성·대기/거절·공정한 admission을 설계한다. 용량 초과 요청은 작은 429·503과 재조회 안내로 제어하고 새로운 Provider 실행을 반복하지 않는다.

비용 경계:

`월 합계 = Workers Free 0달러 + 기존 서버·DB + Origin fallback의 실제 송신료 + Provider 실행·송신료 + 선택한 기타 서비스`

무료 Worker 한도 소진 후 기존 서버로 돌아가는 것은 서비스 가용성을 우선하는 선택이다. 전체 비용 0원이나 무제한 처리량의 보장은 하지 않는다. Origin 송신량·동시성 예산과 알림 기준을 관리 설정으로 두고 실측으로 조정한다. 예산 경보가 자동 유료 전환을 의미하지 않게 한다.

## 10. 구현 순서와 수용 시험

1. 기존 Origin의 제한·보안·주소 투영을 보존하는 신규 호환 Adapter와 공통 Token·claim을 구현한다.
2. Worker 우선·Origin 우선 정책, 외부 Worker Route를 거치지 않는 fallback 경로, 기존 DB의 모드·일일 window·outbox를 구현한다.
3. 격리된 Provider·테스트 DB에서 두 backend 동시 claim·부분 출력·timeout·재접속을 검증한다.
4. staging Route에서 무료 일일 한도 bypass를 모의·검증한다. 단순 애플리케이션 429 시험과 Cloudflare 플랫폼 fail open 시험을 구분하고 운영 계정 한도를 고의로 소진하지 않는다.
5. Origin 독립 검증과 경로 호환 시험이 통과한 뒤 전용 Route를 fail open으로 설정한다. Worker 무료 사용과 유료 부가 서비스 비활성 상태를 확인한다.
6. 한국 시간 09:00 이후 window 교체·health probe·소량 재개·별도 CPU 차단 유지·수동 고정 모드를 시험한다.

필수 통과 조건:

- 하루 임계값 이전에는 Worker가 직접 Provider를 호출하고 Origin은 본문을 받지 않는다.
- 사전 전환 이후 새 실행은 Worker Route 밖의 Origin 경로로 처리된다.
- Worker 미실행·일일 소진의 원래 요청을 Origin Adapter가 인증·claim 후 처리한다.
- Worker claim 후 CPU 오류·단절을 Origin에서 새 실행으로 자동 재시도하지 않는다.
- Worker와 Origin이 동시에 도착해도 Provider dispatch·사용량 확정·Credit 차감이 중복되지 않는다.
- 두 경로의 header·오류·metadata·파일·본문 계약에서 원천 연결 주소·key가 드러나지 않는다.
- 기존 경로에서 지원하지 않는 대용량·새 protocol은 무료 fallback 대상에 등록되지 않는다.
- 계정 집계 지연·다른 Worker 사용·09:00 리셋·stale ticket·로그/Queue 미사용·Origin 과부하를 시험한다.

현재 결과물은 설계 문서·계약·Canvas다. 실제 Workers 구독·Cloudflare Route·서버·SDK·예약 작업은 변경하지 않았다.
