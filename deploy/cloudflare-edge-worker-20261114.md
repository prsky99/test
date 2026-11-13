# 엣지 Worker 배포: 제공자 핸드셰이크 실패를 제공자 코드로 답하기 (2026-11-14, 운영·SRE)

- 요청: PM 11-14 04:5x. 11-13 05:42에 42798의 제공자가 429를 줬는데, 호출자는 우리 쪽 503(`edge_http_503`, gateway_unavailable)을 받았다.
- 사용자 승인: 아직 없다. Worker 배포는 PM을 거쳐 사용자 승인을 받은 뒤 **사용자가 실행한다**(Claude 세션의 권한 검사가 운영 Worker 배포를 거부한다).
- 비용: 0(무료 Workers, 새 바인딩·저장소 없음).

```bash
bash deploy/ops/run-edge-worker-deploy-20261114.sh
```

## 바뀌는 것 (b47872a5 + 810d933f)
운영 Worker는 `09da7f12-5b08-4708-9439-009d8e89910e`(533306aa, 11-14 02:19)이다. 그 뒤 Worker 폴더를 바꾼 커밋은 b47872a5·810d933f 두 개뿐이고, 스크립트가 배포 직전에 다시 확인한다.
- 810d933f(11-14 04시 추가, 실제 과제 a02·a07): A2A 제공자의 HTTP 402(결제 필요)는 `PROVIDER_AUTH_REQUIRED`(error.data provider_auth_required)로, 3xx(주소 이동)는 `PROVIDER_ENDPOINT_UNAVAILABLE`로 답한다. 지금은 둘 다 outcome_unknown이다. 리다이렉트는 여전히 따라가지 않는다. Origin이 이미 받는 완료 코드라 Origin 배포는 필요 없다.

| 경우 | 지금(09da7f12) | 배포 뒤 |
|---|---|---|
| Origin claim·prepare가 `PROVIDER_UNAVAILABLE`(502)로 답함 | 코드를 몰라 `UNAVAILABLE` 503으로 바꿈 → gateway_unavailable / control_unavailable | 실행 경로: `error.data` = provider_error, cause provider_unavailable, 재시도 안 함. 스트림 경로: HTTP 502 `PROVIDER_UNAVAILABLE` |
| Origin이 `PROVIDER_RATE_LIMITED`(502, Retry-After)로 답함 | 위와 같음 | provider_rate_limited, `retryable: true`, `retry_after_seconds`(제공자 값), 스트림 경로는 `Retry-After` 헤더 |
| Worker가 직접 받은 제공자 429(전송 중) | provider_rate_limited, 재시도 안 함 | provider_rate_limited, 재시도 가능, retry_after_seconds 60 |

- 다른 오류 코드와 응답 모양은 그대로다. `CODES`에 두 코드를 더하고, control 응답 상태로 502를 받아들이게 했다.
- Origin 쪽(frontend·jobs)과 배포 순서는 상관없다.
  - 새 Origin + 지금 Worker: 지금처럼 gateway_unavailable로 보인다.
  - 지금 Origin + 새 Worker: 새 코드가 오지 않으므로 지금과 같다.

## 스크립트가 하는 일 (멈추는 조건)
1. 시각을 본다. :55~:10이거나 20:45~21:59이면 멈춘다.
2. Worker 폴더가 810d933f와 같은지, 533306aa 이후 커밋이 b47872a5·810d933f 두 개뿐인지 본다.
3. `worker.test.mjs`를 돌린다. 11-14 04:28에 810d933f 기준으로 1~3단계를 zsh로 미리 돌려 94/94 통과했다.
4. 운영 Worker가 09da7f12인지 확인한 뒤 현황판 배포 잠금을 잡는다. 끝나면 trap으로 푼다.
5. 공개 주소에서 카드 별칭 두 개가 200인지 본다.

기록은 `logs/ops/edge-worker-deploy-20261114.log`에 남는다.

## 배포 뒤 확인 (운영·SRE)
- 24시간 동안 `edge_gateway_events`의 `error:public:edge_http_503` 수와 원인 분포를 본다. 제공자 실패는 `edge_http_502`나 `error.data.cause`(provider_unavailable·provider_rate_limited)로 옮겨 가야 한다.
- 오류 장부(`scripts/error_ledger.py`)가 `edge_http_502`를 따로 센다. 장부 규칙은 바꾸지 않아도 된다.

## 되돌리기
```bash
cd cloudflare/edge-gateway && ./npmw exec -- wrangler rollback 09da7f12-5b08-4708-9439-009d8e89910e --message 'rollback provider-code-worker-20261114-r1'
```
