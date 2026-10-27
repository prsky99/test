# 결제 기능 개선 방안

근거: `reports/결제 기능 테스트.md`(개선 8건). 사이트 서버(x402 게이트웨이, MCP `call`·`credit`, 고객 크레딧)에 적용할 규칙과 예시 코드입니다.

## 목표
| 항목 | 지금 | 목표 |
|---|---|---|
| 결제 실패 이유 | 15가지 모두 같은 "Payment required" | 이유 코드로 구분(정상 결제 외 0건 동일 응답) |
| 실제 결제 성공 흐름 | 검증 안 됨 | 운영 지갑으로 정기 확인, 영수증 헤더 확인 |
| 카탈로그 active인데 게이트웨이 503 | 있음 | 0건(추천 제외, 상태 갱신) |
| 바깥으로 보이는 x402 버전 | v1·v2 섞임 | v2 하나(v1 요청도 받음) |
| 결제 경로 429 | `Retry-After` 없음 | `Retry-After`와 RateLimit 헤더, 결제 재요청은 별도 한도 |

## 1. 결제 실패 이유 알리기 (문제 1)

### 1-1. 검증 순서와 이유 코드
결제 헤더를 받으면 아래 순서로 검사합니다. 처음 실패한 단계의 코드를 `PAYMENT-REQUIRED`의 `error`와 본문 `error`에 넣습니다. 3번까지는 정산기(facilitator)를 부르지 않고 게이트웨이가 직접 판단합니다. 비용과 지연이 줄어듭니다.

| 순서 | 검사 | 코드 | HTTP |
|---|---|---|---|
| 1 | 헤더 크기 8KB 이하, base64 → JSON | `invalid_payload` | 400 |
| 2 | `x402Version`이 1 또는 2 | `invalid_x402_version` | 400 |
| 3 | `scheme`·`network`가 `accepts` 중 하나와 같음 | `invalid_scheme`, `invalid_network` | 402 |
| 4 | `authorization.to`가 `payTo`와 같음 | `invalid_exact_evm_payload_recipient_mismatch` | 402 |
| 5 | `authorization.value` ≥ `amount` | `invalid_exact_evm_payload_authorization_value` | 402 |
| 6 | `validAfter` ≤ 지금 < `validBefore`, 남은 시간 ≥ 6초 | `invalid_exact_evm_payload_authorization_valid_before` / `_valid_after` | 402 |
| 7 | EIP-712 서명 복원 주소가 `authorization.from`과 같음 | `invalid_exact_evm_payload_signature` | 402 |
| 8 | 같은 `nonce`가 처리 중이거나 처리된 적 없음 | `nonce_already_used` | 402 |
| 9 | facilitator `verify`: 잔액·허용 | `insufficient_funds` 등 facilitator 코드를 그대로 전달 | 402 |
| 10 | facilitator `settle` | `settle_failed`와 `transaction` | 402 |

```python
def payment_error(code: str, req: dict, status: int = 402) -> JSONResponse:
    body = {**req, "error": code}                      # req = 원래 결제 요구(PAYMENT-REQUIRED 내용)
    hdr = base64.b64encode(json.dumps(body).encode()).decode()
    return JSONResponse(body, status_code=status, headers={"PAYMENT-REQUIRED": hdr})
```
- 처음 요청(결제 헤더 없음)의 `error`는 지금처럼 `"Payment required"`로 둡니다.
- 서명 검증(7번)은 게이트웨이에서 `eth_account`로 할 수 있습니다. 도메인은 `accepts[].extra.name`·`version`, `chainId`, `asset`입니다.
- 지금 시험에서 쓴 15가지 입력을 회귀 시험으로 고정합니다. 기대 코드는 아래 표와 같습니다.

  | 입력 | 기대 코드 |
  |---|---|
  | 깨진 base64 / JSON 아님 / 빈 객체 | `invalid_payload` |
  | 버전 99 | `invalid_x402_version` |
  | `eip155:1` / `upto` | `invalid_network` / `invalid_scheme` |
  | 금액 1 / 다른 payTo | `…authorization_value` / `…recipient_mismatch` |
  | 만료 | `…valid_before` |
  | 0 서명 / 다른 chainId로 서명 | `…signature` |
  | 잔액 0 | `insufficient_funds` |
  | 재사용 | `nonce_already_used` |
  | 20KB 헤더 | `invalid_payload`(400) |

### 1-2. MCP 게이트웨이 `_payment`에도 같은 코드
MCP 유료 도구는 `isError:true` 결과의 `structuredContent.error`에 같은 코드를 넣습니다. 안내 문장은 지금처럼 유지합니다.

## 2. 실제 결제 성공 흐름 확인 (문제 2)
- **운영 시험 지갑:** 결제 전용 지갑을 따로 둡니다(USDC 1~2달러). 키는 서버 비밀값으로만 보관하고 저장소에는 넣지 않습니다.
- **하루 1번 확인 작업:** 운영자 소유의 0.001 USDC 시험 자원(또는 제공자 동의를 받은 자원 하나)에 실제로 결제합니다. 확인할 것:
  1. 결제 헤더를 붙인 요청이 200을 받습니다.
  2. `PAYMENT-RESPONSE` 헤더(base64 JSON)에 `success:true`, `transaction`, `network`, `payer`가 있습니다.
  3. 체인에서 `transaction`의 USDC 이동(금액·받는 주소)을 확인합니다. 저장소의 `chain.py`·`payments.py` 검증기를 그대로 쓸 수 있습니다.
  4. 같은 결제 헤더로 다시 요청하면 `nonce_already_used`가 나옵니다.
- **제공자가 실패했을 때(5xx·시간 초과):**
  - 정산 전이면 정산하지 않습니다.
  - 정산 후면 실패 기록과 환불(또는 크레딧 반환) 정책을 정해 응답에 적습니다. 예: `refund: "credit"`.
- 결과는 Status 화면과 `/api/feed/verified.json`에 "결제 경로 확인 시각"으로 남깁니다.

## 3. 카탈로그 상태와 게이트웨이 상태 맞추기 (문제 3)
- 게이트웨이가 503 `UNAVAILABLE`을 돌려준 항목은 즉시 `health_status=failing`으로 바꾸고 추천 후보에서 뺍니다. 15분 뒤 다시 확인합니다.
- 추천 응답과 상세 응답에 `gateway_ready: true/false`와 마지막 게이트웨이 확인 시각을 넣습니다.
- 회귀 확인: 122024처럼 `active`인데 503인 항목이 0건이어야 합니다.

## 4. 바깥으로는 x402 v2 하나로 (문제 4)
- 제공자가 v1(`X-PAYMENT`, `maxAmountRequired`, network `base`)이어도 게이트웨이는 v2로 바꿔 내보냅니다.

  | v1 | v2 |
  |---|---|
  | `maxAmountRequired` | `amount` |
  | `network: "base"` | `network: "eip155:8453"` |
  | 본문만 | `PAYMENT-REQUIRED` 헤더 + 본문 |
  | `resource`(문자열), `description` | `resource: {url, description, mimeType}` |

- 에이전트가 보낸 v2 결제는 게이트웨이가 제공자 버전(v1 `X-PAYMENT`)으로 바꿔 넘깁니다.
- 에이전트가 v1 `X-PAYMENT`를 보내도 받습니다(하위 호환).
- 카탈로그에 `upstream_x402_version`을 기록해 둡니다(운영 참고용).

## 5. 결제 경로 요청 한도 (문제 5)
- 429와 403(차단)에 `Retry-After`(초), `RateLimit-Limit`·`RateLimit-Remaining`·`RateLimit-Reset`을 넣습니다.
- 결제 헤더가 붙은 요청(결제 재요청)은 첫 402 요청과 따로 셉니다. 한 번 결제할 때 2번 부르게 되므로, 결제 재요청이 한도 때문에 막히지 않게 합니다.
- 기준: 같은 방문 토큰·IP·자원에 대해 첫 요청은 분당 30회, 결제 재요청은 분당 30회.
- 차단(Auto-jail)은 결제 경로 위반만으로 사이트 전체를 막지 않게 합니다. 등록 기능 개선 방안 4장과 같습니다.

## 6. `credit` 도구 예외 처리 (문제 6)
- 2026-10-27 00:08 UTC 무렵 `credit action=add` 요청에서 서버가 응답 없이 연결을 끊었습니다. 서버 로그를 확인합니다.
- `credit` 도구의 모든 분기를 예외 처리로 감쌉니다. 실패하면 JSON-RPC 오류(-32603)와 짧은 문구를 돌려줍니다.
- 허용하지 않는 `action`은 -32602 "Choose balance." 같은 문구로 거절하고, 음수 `amount`도 거절합니다.

## 7. 문구 정리 (문제 7)
| 지금 | 바꿀 문구 |
|---|---|
| "Insufficient available credits: Insufficient available credits: needed 1000, available 0" | "Insufficient credits: needed 1000 micro-USDC, available 0." |
| 없는 자원에 "The agent execution was refused or failed." | "Resource 999999999 was not found." |
| "Please provide your visitor_token or credit account with sufficient balance." | "This resource costs 1000 micro-USDC. Pay directly with x402 at <gateway url>, or use a customer account with credits (sign in at /customer/sign-in)." |

- 크레딧을 얻는 방법을 llms.txt의 Call 절에 한 줄로 적습니다. 공개 충전은 불가하고, 고객 계정 또는 x402 직접 결제를 쓴다는 내용입니다.

## 8. 공개 OpenAPI 정리 (문제 8)
- 다음 경로는 공개 `openapi.json`에서 뺍니다(FastAPI `include_in_schema=False`).
  - `/api/edge-gateway-internal/v1/*`
  - `/api/origin-gateway/*`
  - `/api/edge-gateway/v1/*`
- 고객 전용 경로(`/api/customer-*`)는 고객 문서에만 둡니다.

## 9. 적용 순서와 완료 기준
| 단계 | 내용 | 완료 기준 |
|---|---|---|
| 1 | 결제 실패 이유 코드(1장) | 회귀 15가지가 표의 기대 코드와 같음 |
| 2 | 실제 결제 확인 작업(2장) | 하루 1번 200 + `PAYMENT-RESPONSE` + 체인 확인 + 재사용 거절 |
| 3 | 카탈로그·게이트웨이 상태 일치(3장) | `active`인데 503인 항목 0건 |
| 4 | v2 통일(4장) | 표본 50개 모두 v2 헤더 |
| 5 | 한도 헤더·결제 재요청 별도 한도(5장) | 429에 `Retry-After`. 402 → 결제 재요청이 한도에 걸리지 않음 |
| 6 | `credit` 예외, 문구, OpenAPI(6~8장) | 연결 끊김 0건, 문구 표대로, 공개 스키마에 내부 경로 0개 |

### 회귀 시험
- `reports/결제 기능 테스트.md`의 시나리오를 그대로 다시 돌립니다.
- 잘못된 결제는 잔액 0인 일회용 키로 만들고, 요청은 7초 간격으로 보냅니다.
- 실제 결제 확인(2장)은 운영 시험 지갑으로만 합니다. 금액과 횟수를 정해 두고(예: 0.001 USDC, 하루 1회), 결과를 기록합니다.
