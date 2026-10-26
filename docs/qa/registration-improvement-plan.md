# 등록 기능 개선 방안

근거: `reports/등록 기능 테스트.md`(문제 13건). 사이트 서버(FastAPI)에 적용할 규칙과 예시 코드입니다. 화면(브라우저) 검사는 편의일 뿐입니다. 모든 검사는 서버에서 다시 합니다.

## 목표
| 항목 | 지금 | 목표 |
|---|---|---|
| 법적 동의 없이 등록 | 됨 | 400 |
| 에이전트가 아닌 URL 등록 | 됨(healthy·reachable) | 400과 이유 |
| 자기 도메인 등록 | 됨 | 400 |
| 문의 헤더 주입·같은 문의 반복 | 접수 | 400 / 429 |
| 없는 분류·카테고리·음수 가격 | 다른 값으로 바뀌어 저장 | 400과 허용 값 |
| 한 경로 위반으로 사이트 전체 차단 | 그렇다 | 해당 기능만 차단, `Retry-After` |

## 1. 에이전트 등록 (`/api/register`, `/api/register/inspect`)

### 1-1. 법적 동의 서버 검사 (문제 1)
```python
from datetime import datetime, timezone, timedelta

TOS_VERSION = PRIVACY_VERSION = "2026.1"

def check_consent(c: dict | None) -> None:
    if not isinstance(c, dict):
        raise HTTPException(400, "Agree to the Terms and Privacy Policy to list an agent.")
    if c.get("tos_version") != TOS_VERSION or c.get("privacy_version") != PRIVACY_VERSION:
        raise HTTPException(400, f"Review the current Terms ({TOS_VERSION}) and Privacy Policy ({PRIVACY_VERSION}).")
    try:
        at = datetime.fromisoformat(str(c.get("agreed_at")).replace("Z", "+00:00"))
    except ValueError:
        raise HTTPException(400, "Consent time is missing or invalid.")
    if abs(datetime.now(timezone.utc) - at) > timedelta(minutes=10):
        raise HTTPException(400, "Consent has expired. Review the Terms again and resubmit.")
```
- 동의 기록은 서버 시각, 요청 IP 해시, 버전과 함께 저장합니다. 클라이언트가 보낸 `agreed_at`은 검사에만 씁니다.
- 구형 `/agents/register`도 같은 함수를 통과하게 합니다. 아니면 경로를 닫고 410과 새 경로 안내를 돌려줍니다(문제 11).

### 1-2. 프로토콜 응답을 확인한 뒤에만 등록 (문제 2, 12)
URL이 도달 가능한지만으로 등록하지 않습니다. 종류마다 최소 응답을 확인합니다. 수집기의 기존 함수를 그대로 쓸 수 있습니다(`collector/health.py`, `collector/a2a.py`, `collector/capabilities.py`).

| 종류 | 통과 조건 | 실패 문구 |
|---|---|---|
| MCP | `initialize`가 JSON-RPC `result`와 `serverInfo`를 돌려주고, `tools/list`가 응답함 | "No MCP initialize response at this URL." |
| A2A | 카드 JSON에 `name`과 `skills`(1개 이상), 그리고 `url` 또는 `supportedInterfaces`가 있음 | "No valid A2A agent card at this URL." |
| x402 | 결제 없는 요청에 402와 `accepts`(scheme, network, amount, payTo)가 옴 | "No x402 payment challenge (HTTP 402) at this URL." |

- `inspect`의 `ok`는 위 조건을 통과했을 때만 `true`로 합니다. 통과하지 못하면 `ok:false`, `reason`, `checked`(시도한 단계)를 돌려줍니다.
- `inspect`는 찾은 값만 채웁니다. 설명이 없으면 "Example Domain MCP service endpoint" 같은 문장을 지어내지 말고 빈 값으로 둡니다. 카테고리도 근거가 없으면 비워 두고 사용자가 고르게 합니다.
- 등록 결과 문구는 상태에 따라 나눕니다.

  | 상태 | 문구 |
  |---|---|
  | `healthy` | Listed and verified. |
  | `reachable` | 등록하지 않음(위 조건 실패). 굳이 받는다면 "Listed, protocol check pending"과 `catalog_status:pending`으로 두고 공개 목록에서 뺍니다. |

### 1-3. 자기 도메인과 게이트웨이 주소 거절 (문제 3)
```python
SELF_HOSTS = {"agentconcierge.biz", "www.agentconcierge.biz"}

def check_not_self(url: str) -> None:
    host = (urlsplit(url).hostname or "").lower().rstrip(".")
    if host in SELF_HOSTS or host.endswith(".agentconcierge.biz"):
        raise HTTPException(400, "Agent Concierge endpoints cannot be listed as providers.")
```
- 리다이렉트를 따라간 뒤의 최종 주소에도 같은 검사를 합니다.

### 1-4. 허용 목록 검사 (문제 7)
- `category`: 14개 정의(`broker/categories.py`)에 없으면 400을 돌려주고 `allowed` 목록을 함께 보냅니다. `other`로 바꿔 저장하지 않습니다.
- `price_usdc`: 0 이상의 정수만 받고, 상한(예: 100 USDC = 100,000,000)을 둡니다. 음수는 400입니다.
- `networks`: 지원 목록(`base`, `eip155:8453` 등)만 받습니다.
- `pay_to`: EVM이면 `^0x[0-9a-fA-F]{40}$`와 EIP-55 체크섬을 확인합니다.

### 1-5. 오류 문구를 원인별로 나누기 (문제 8)
`check_public_url`의 거절 이유를 하나로 뭉치지 말고 나눕니다.

| 원인 | 문구 |
|---|---|
| DNS 실패 | "The host could not be resolved." |
| 사설·내부 주소 | "Private or internal network addresses are not allowed." |
| 자격 증명 포함(`user:pass@`) | "Remove credentials from the URL." |
| 스킴 오류 | "URL must begin with http:// or https://" (지금과 같음) |

## 2. 문의 (`/api/contact/submit`)

### 2-1. 헤더 주입 차단 (문제 4)
```python
CTRL = re.compile(r"[\r\n\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")

def clean_line(field: str, value: str, max_len: int) -> str:
    if CTRL.search(value):
        raise HTTPException(400, f"{field} must be a single line.")
    return value.strip()[:max_len]
```
- `name`·`subject`·`email`·`category`에 적용합니다. `message`는 줄바꿈을 허용하되 제어 문자는 거절합니다.
- 메일을 보내는 곳에서도 `email.headerregistry` 또는 `email.message.EmailMessage`로 헤더를 만듭니다. 문자열을 직접 이어 붙이지 않습니다.
- 사용자 메일은 `Reply-To`에만 넣습니다. `From`·`To`·`Bcc`는 서버 설정값만 씁니다.

### 2-2. 저장형 XSS 방지 (문제 6)
- 저장은 원문 그대로 둘 수 있습니다. 대신 관리 화면(`gateway/dashboard.*`)에서 문의를 그릴 때 `textContent`나 이스케이프 함수만 씁니다. `innerHTML`로 직접 넣지 않습니다.
- 운영자 알림 메일은 텍스트 메일로 보냅니다. HTML 메일이라면 이스케이프합니다.
- 회귀 시험: `<script>alert(1)</script>` 문의를 넣고 관리 화면에서 실행되지 않는지 확인합니다.

### 2-3. 반복·남용 방지 (문제 5)
- 같은 `email + sha256(message)`는 10분 안에 한 번만 받습니다. 두 번째부터는 200과 처음 접수번호를 돌려줘 같은 건임을 알립니다.
- IP 기준 10분 5건, 메일 기준 하루 10건 한도를 두고, 넘으면 429와 `Retry-After`를 돌려줍니다.
- 공개 폼에는 Cloudflare Turnstile 토큰을 서버에서 확인하는 것을 검토합니다. 에이전트용 API 경로는 방문 토큰으로 대신합니다.

### 2-4. 분류 허용 목록 (문제 7)
화면의 분류 선택지(`inqCategory`의 option 값)만 받고, 그 밖의 값은 400입니다.

## 3. 개인정보 요청 (`/api/privacy/opt-out`) (문제 10)
- `request_type`을 필수로 하고, 허용 값(`ccpa_opt_out` 등)만 받습니다. 빈 요청은 400입니다.
- 같은 방문자나 IP의 같은 요청은 하루 한 건으로 묶습니다.

## 4. 요청 한도와 자동 차단 (문제 9)
| 지금 | 바꿀 것 |
|---|---|
| 아무 경로에서든 429가 60초에 5번 쌓이면 사이트 전체 403 | 차단을 기능 단위로 둡니다: `register`, `contact`, `chat`, `mcp`, `explore` 등 |
| 429·403에 다시 시도할 시각 없음 | `Retry-After`(초)와 `RateLimit-Limit`/`RateLimit-Remaining`/`RateLimit-Reset` 헤더 |
| 403 본문 "Auto-jail triggered…" | `{"error":"rate_limited","scope":"register","retry_after":60}` |

- 전체 차단은 명백한 공격 패턴에만 씁니다. 예: 사설 주소를 여러 번 넣는 SSRF 시도, 서명 위조.
- 공유 IP(NAT, 클라우드 프록시)를 고려해, 방문 토큰이 있으면 IP 대신 토큰 기준으로 셉니다.

## 5. 작업 알림 구독 (문제 13)
- `pending_verification` 상태는 24시간 안에 확인되지 않으면 자동으로 지웁니다. 지금은 만료가 약 90일 뒤입니다.
- 확인 코드를 보내는 webhook 요청도 `check_public_url`과 같은 검사를 거칩니다. 지금 사설 주소 거절은 동작합니다.

## 6. 언어 통일 (문제 11)
- 에이전트가 읽는 응답은 영어로 통일합니다(프로젝트 규칙).
- 지금 한국어로 답하는 곳:
  - `/agents/register`: `<에이전트 base URL>`, "사설/내부 주소는 등록할 수 없습니다."
  - `/needs`·`/sns/posts`: "X-Client(지갑 주소)와 X-Signature가 필요합니다."
  - `/offers/accept`: "없는 제안입니다."

## 7. 시험 데이터 정리
`reports/등록 기능 테스트.md`의 "시험으로 생긴 데이터" 표를 보고 지웁니다.
- 에이전트 등록: 206598, 206599, 206602, 206603, 206604. 이름이 "QA TEST - please delete"입니다.
- 문의 7건(`inq_IkQo…` 등), 개인정보 요청 3건(`prv_az6q…`, `prv_P6rs…`, `prv_b0Gw…`)
- 알림 구독 `tw_6a58…`(webhook, 인증 대기)

앞으로 시험 데이터는 이름이나 메일에 `qa+` 접두어를 붙이고, 관리 화면에 "QA 데이터 일괄 삭제"를 둡니다.

## 8. 적용 순서와 완료 기준
| 단계 | 내용 | 완료 기준(회귀 시험 결과) |
|---|---|---|
| 1 | 법적 동의 서버 검사(1-1), 문의 헤더 주입 차단(2-1) | 동의 없음·옛 버전·미래 시각 → 400. 제목에 `\r\n` → 400 |
| 2 | 프로토콜 확인 후 등록(1-2), 자기 도메인 거절(1-3) | example.com/org/net → 400과 이유. `agentconcierge.biz/mcp` → 400 |
| 3 | 문의 중복·한도(2-3), 관리 화면 이스케이프(2-2) | 같은 문의 2번째 → 같은 접수번호. 6번째 → 429. `<script>`가 실행되지 않음 |
| 4 | 허용 목록(1-4, 2-4, 3), 오류 문구(1-5), 언어(6) | 없는 값 → 400과 `allowed`. DNS 실패·자격 증명 문구가 따로 나옴 |
| 5 | 차단 범위·헤더(4), 대기 구독 정리(5) | `inspect` 한도 초과 뒤에도 `/chat`은 200. 429에 `Retry-After` |

### 회귀 시험
- `reports/등록 기능 테스트.md`의 시나리오를 그대로 다시 돌립니다.
- 요청은 3초 간격으로 보내고, 429가 오면 65초 쉬었다가 다시 보냅니다. 그래야 자동 차단에 걸리지 않습니다.
- 성공 경로 시험은 등록 1건, 문의 1건만 만들고 바로 정리합니다.
- 단위 시험으로 옮길 수 있는 것은 서버 저장소의 `tests/`에 넣습니다. 예: `check_consent`, `clean_line`, 허용 목록, 자기 도메인 검사.
