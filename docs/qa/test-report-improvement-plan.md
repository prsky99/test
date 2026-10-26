# 테스트 결과 보고서 개선 방안

근거: `reports/테스트 결과 보고서 품질 분석.md`(2,855건 분석, 문제 13건). 보고서를 만드는 쪽(사이트의 보고서 작성기)에 적용할 규칙입니다.

## 목표
- **정확성:** 보고서 판정이 측정 결과와 다르지 않아야 합니다. 상태 코드와 판정이 어긋나는 보고서 0건.
- **일관성:** 한 보고서 안에서 서로 다른 말을 하지 않아야 합니다. 자기모순 0건.
- **근거:** 측정하지 않은 내용은 쓰지 않습니다. 결제 전 x402 보고서에서 응답 품질 주장 0건.
- **비교 가능성:** 같은 종류의 에이전트끼리 숫자로 비교할 수 있어야 합니다.

## 1. 판정을 세 가지로 나누기 (문제 1)
`is_success`(0/1) 대신 `verdict`를 둡니다. `is_success`는 호환을 위해 `verdict == "pass"`로 계산해 남깁니다.

| verdict | 조건 | 화면 표시 |
|---|---|---|
| `pass` | 시험한 단계가 모두 규격대로 응답(2xx, 올바른 JSON-RPC 결과) | 통과 |
| `gated` | 401·403(인증 필요), 402(x402 결제 요구)이고, 응답 형식이 규격에 맞음 | 인증 필요 / 결제 필요 |
| `fail` | 5xx, 시간 초과, 연결 실패, 형식 오류(깨진 JSON, 필수 필드 없음), 그 밖의 4xx | 실패 |

```python
def verdict(kind, status, body_ok, timed_out):
    if timed_out or status is None or status >= 500:
        return "fail"
    if status in (401, 403):
        return "gated" if body_ok else "fail"
    if status == 402:
        return "gated" if kind == "x402" and body_ok else "fail"
    if 200 <= status < 300:
        return "pass" if body_ok else "fail"
    return "fail"
```

- x402 보고서의 402는 `gated`(정상)입니다.
- x402인데 결제 요구 없이 200이 오면 `pass`로 하되, `notes`에 `free_response`(무료 한도 등)를 남깁니다(문제 7).
- 화면에서는 보고서 판정과 현재 상태를 함께 보여 줍니다. 예: "보고서: 통과(10/25) · 현재: down". 현재 상태가 down·retired이면 맨 위에 경고를 띄웁니다.

## 2. 보고서 구조 고정 (문제 8, 10)
모든 보고서를 같은 필드로 만듭니다. 문장은 이 필드에서 자동으로 만들고, 사람이 쓰거나 LLM이 쓴 평가 문장은 넣지 않습니다.

```json
{
  "schema_version": 2,
  "kind": "a2a | mcp | x402",
  "test_method": "A2A_CARD | A2A_MESSAGE_SEND | MCP_TOOLS_LIST | MCP_TOOLS_CALL | X402_CHALLENGE",
  "steps": [{"name": "initialize", "status": 200, "latency_ms": 412, "ok": true}],
  "verdict": "pass | gated | fail",
  "grade": "A | B | C | D | null",
  "measured": { "…종류별 측정값(3장)…" },
  "declared_missing": ["protocolVersion"],
  "scope": {"executed": false, "paid": false, "credentials": false},
  "tags": ["mcp", "weather"],
  "provider_text": {"source": "catalog", "description": "…"},
  "generated_at": "2026-10-26T12:00:00Z",
  "legacy": false
}
```

- **test_method:** 위 5개 중 하나만 씁니다. 지금 쓰이는 122종은 아래 표로 바꿔 넣습니다. 가격 같은 값은 `measured`로 옮깁니다.

  | 지금 이름(예) | 바꿀 이름 |
  |---|---|
  | `A2A_AGENT_CARD_DISCOVERY`, `AGENT_CARD_INSPECTION`, `a2a_agent_card_inspection`, `A2A_CAPABILITIES_DISCOVERY` | `A2A_CARD` |
  | `A2A_JSONRPC_MESSAGE_SEND`, `A2A_ORCHESTRATION_INVOCATION`, `A2A_AUTH_INVOCATION` | `A2A_MESSAGE_SEND` |
  | `MCP_TOOLS_LIST`, `JSON_RPC_TOOLS_LIST`, `MCP_SSE_INITIALIZE`, `MCP_FAST_PROBE` | `MCP_TOOLS_LIST` |
  | `MCP_TOOLS_CALL`, `MCP_LIST_AND_CALL_TOOL`, `MCP_TOOL_INVOCATION` | `MCP_TOOLS_CALL` |
  | `HTTP_402_CHALLENGE`, `X402_CHALLENGE_VERIFY`, `x402 V2 Micro-payment ($…)` | `X402_CHALLENGE` |
  | `GET`, `POST` | 실제 시험 단계에 맞춰 위 중 하나 |

- **grade:** `A`~`D` 한 글자만 씁니다. `Grade A`는 `A`로 바꿉니다.
- **tags:** 문자열이 아니라 배열로 둡니다.
- **input_wire:** 비우지 않습니다. 비어 있는 x402 80건은 `{"method":"GET","url":"<gateway url>"}`로 채웁니다.

## 3. 종류별 측정 항목과 문장 규칙

### 공통
- 장점과 단점은 측정값에서만 만듭니다. 측정하지 않은 성질(정확도, 신뢰성, 보안 수준)은 쓰지 않습니다.
- 다음 단어는 쓰지 않습니다(검수에서 걸러냄): production-grade, enterprise, robust, seamless, rigorous, state-of-the-art, ensures, accurate, reliable, real-time(측정 근거 없이).
- 숫자는 같은 종류 안의 순위와 함께 씁니다. 예: "응답 412ms(MCP 상위 25%)". 그래야 2,000건이 서로 다른 정보가 됩니다(문제 10).
- 설명이 이름과 같거나 10자 미만이면 "설명 없음"으로 처리합니다(문제 11).

### A2A
| 측정 | 출처 |
|---|---|
| 카드 응답 시간·상태 | GET 카드 |
| `protocolVersion` 선언 여부와 값 | 카드 원문 |
| 인터페이스(0.3 `url`, 1.0 `supportedInterfaces`) | 카드 원문 |
| 스킬 수, 예시(`examples`) 유무 | 카드 원문 |
| `message/send` 결과(실행했을 때) | JSON-RPC 응답 |

- **문제 3 해결:** 측정표의 Protocol 칸은 카드에 선언된 값만 씁니다. 선언이 없으면 "선언 없음"으로 쓰고, `declared_missing`에 `protocolVersion`을 넣습니다. 표와 단점이 같은 필드에서 나오므로 서로 어긋날 수 없습니다.

### MCP
| 측정 | 출처 |
|---|---|
| initialize 응답 시간, 협상 버전 | initialize |
| 도구 수, 설명이 있는 도구 수, 스키마가 있는 도구 수 | tools/list |
| readOnlyHint가 있는 도구 수 | tools/list |
| 읽기 전용 도구 호출 결과(했을 때) | tools/call |

- **문제 2 해결:**
  - "The provider published no description." 문장은 지웁니다.
  - 핸드셰이크에 설명이 없으면 "serverInfo에 설명 없음"이라고 측정표에만 적습니다.
  - 사람에게 보여 줄 설명은 `provider_text.description`(카탈로그 설명)을 씁니다.
- **문제 13 해결:**
  - 시험 클라이언트는 최신 버전(2025-11-25)을 먼저 요청하고, 서버가 낮은 버전으로 답하면 그 값을 기록합니다.
  - 측정표에는 "요청 2025-11-25 → 협상 2025-03-26"처럼 두 값을 함께 씁니다.

### x402 (결제 전까지만)
402 응답에서 다음 7개를 모두 측정표에 넣습니다. 빠지면 `declared_missing`에 넣고 단점으로 씁니다(문제 6).

| 항목 | 필드 |
|---|---|
| x402 버전 | `x402Version` |
| 결제 방식 | `accepts[].scheme` |
| 네트워크 | `accepts[].network` |
| 자산 | `accepts[].asset` |
| 금액 | `accepts[].amount`(USDC로 환산해 함께 표시) |
| 받는 주소 | `accepts[].payTo` |
| 제한 시간 | `accepts[].maxTimeoutSeconds` |
| 자원 설명 | `resource.description` 유무 |

- **문제 5 해결:** `scope.paid=false`이면 응답 내용에 대한 장점을 넣지 않습니다. 쓸 수 있는 장점은 다음과 같은 결제 조건 사실뿐입니다.
  - "결제 조건을 v2 형식으로 명확히 제시"
  - "가격 0.005 USDC(같은 분야 중앙값 0.01)"
- 단점에는 늘 "결제 후 응답은 확인하지 않음"을 씁니다.

## 4. 과거 보고서(legacy 582건) 처리 (문제 4)
1. `legacy=true`로 표시합니다. 화면 맨 위에 "과거 기록 · 다시 확인되지 않음 · 기록일 …" 배너를 붙입니다.
2. 평가 문장(장점·단점·요약·워크플로 추천)은 기본으로 숨기고 "원문 보기"로만 엽니다. 측정값(상태 코드, 응답 시간, 선언 내용)만 남깁니다.
3. 본문의 `[Retired gateway reference]`(251건)는 다음 둘 중 하나로 처리합니다.
   - 문장째 지웁니다.
   - 현재 연결 주소로 바꿉니다.
4. 추천 순위의 근거에서 과거 보고서를 뺍니다. "최근 성공한 시험 보고서"에는 `legacy=false`만 셉니다.
5. 같은 항목은 새 규칙으로 다시 시험합니다. 새 보고서가 생기면 과거 보고서는 기록 탭으로 내립니다.

## 5. 시험 깊이 늘리기 (문제 9)
지금은 A2A 89%가 카드 조회만, MCP 88%가 도구 목록만 시험합니다.
- **MCP:**
  - `readOnlyHint:true`이거나 이름이 get/search/list로 시작하는 도구 하나를 고릅니다.
  - 스키마의 필수 인자를 예시 값으로 채워 1번 호출합니다.
  - `MCP_TOOLS_CALL`로 기록합니다. 수집기의 `capabilities.py` 시험 호출 결과를 그대로 쓸 수 있습니다.
- **A2A:** 스킬의 `examples` 첫 문장(없으면 "What can you do?")으로 `message/send`를 1번 보냅니다. Message·Task 형식이 맞는지만 봅니다.
- **지켜야 할 것:**
  - 결제·자격 증명은 쓰지 않습니다.
  - 쓰기·삭제·전송 성격의 도구는 호출하지 않습니다.
  - 인증이 필요하면 `gated`로 끝냅니다.
- 실행 결과가 있으면 `execution_measured=true`로 기록합니다. 형식까지 맞으면 `execution_verified=true`로 기록합니다.

## 6. 중복 정리 (문제 12)
- 이름이 같은 항목 87개 중 엔드포인트가 같은 것은 하나로 묶고, 보고서도 합칩니다.
- 엔드포인트가 다르면 제목에 도메인을 붙입니다. 예: "wikipedia-intel (api.example.com) A2A Verification Report".

## 7. 게시 전 자동 검수
보고서를 공개하기 전에 아래 규칙으로 검사합니다. 하나라도 걸리면 공개하지 않고 작성기를 고칩니다.

| 규칙 | 확인 |
|---|---|
| R1 | `verdict`가 1장의 함수 결과와 같음 |
| R2 | 측정표에 있는 값이 `declared_missing`에 없음(표와 단점의 모순 없음) |
| R3 | 금지어(3장 공통) 없음 |
| R4 | `scope.paid=false`인데 응답 내용 장점 없음 |
| R5 | x402: 7개 항목이 측정표에 있거나 `declared_missing`에 있음 |
| R6 | `test_method`가 5개 목록 안에 있음, `grade`가 A~D 또는 null, `tags`가 배열 |
| R7 | `[Retired gateway reference]`, `[REDACTED]` 외의 비밀값(키·토큰 패턴) 없음 |
| R8 | MCP: "published no description" 문장 없음 |

## 8. 적용 순서와 완료 기준
| 단계 | 내용 | 완료 기준(공개 보고서 전체 기준) |
|---|---|---|
| 1 | 판정 3단계, 현재 상태 경고(1장) | 401·402인데 통과로 표시된 보고서 0건 |
| 2 | MCP 설명 문구, A2A 버전 표기(3장) | "설명 없음" 오기 0건, 버전 모순 0건(지금 1,363건, 111건) |
| 3 | 과거 보고서 배너·평가 문장 숨김·`[Retired…]` 정리(4장) | 배너 없는 legacy 0건, `[Retired…]` 0건(지금 251건) |
| 4 | x402 7개 항목·무료 응답 표시(3장) | payTo 누락 0건(지금 53건), 결제 전 응답 품질 주장 0건 |
| 5 | 형식 통일(2장), 검수 R1~R8(7장) | test_method 5종, grade 형식 1종, 태그 배열 100% |
| 6 | 시험 깊이(5장), 중복 정리(6장) | 실행 시험 비율 A2A·MCP 각 30% 이상(지금 1%, 4%) |

- **효과가 큰 단계:** 1~2단계는 작성기 템플릿만 고치면 되고, 다시 생성하면 약 2,700건이 한 번에 바로잡힙니다.
- **검증 방법:** 적용 후 `reports/테스트 결과 보고서 품질 분석.md`와 같은 방법으로 다시 집계합니다. 사이트 부담을 피하려고 1건씩 0.5초 간격으로 받습니다.
