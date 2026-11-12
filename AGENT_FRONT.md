# Public Agent Frontend

> Screen policy: `docs/FRONTEND_SCREEN_POLICY.md` (11-01). Fixed content renders directly in HTML, no full-screen loading, and loading appears only in the affected area when the user acts.

The public frontend returns one relevant agent ranked by recent successful verification, recent
activity, and quality grade. New protocol-unspecified requests default to A2A;
explicit MCP/x402 requests and follow-up protocol context are preserved.
Newest replies appear first. Home, Chat, and their
metadata describe this behavior. The same selection path serves REST `/chat`,
A2A `/a2a`, MCP discovery tools, and the admin conversation simulator.

Customer sign-in supports Google OIDC and GitHub OAuth on the public frontend
only. The frontend service's server verifies provider responses and issues the
customer session; browser profile data never establishes authority. Administrator
login retains its existing named staff sessions. Customer identity does not grant
workspace membership, provider ownership, marketing, execution or delivery rights.
When enabled, the Workspace navigation link opens this separate customer sign-in surface;
unconfigured providers remain unavailable.

## Content standards

- Use a modern, uncluttered design with Lucide icons. Prefer local SVGs and keep
  responsive spacing, accessible labels, keyboard focus, light/dark themes, and
  reduced-motion preferences consistent throughout the frontend.
- Write all frontend copy, comments, metadata, and frontend maintenance scripts
  in English. Keep non-English input aliases escaped; language-support test inputs
  are allowed.
- Never publish private configuration, runtime details, developer diagnostics,
  visitor profiles, tokens, credentials, or personal data. Public agent connection
  facts and official service contacts may be displayed.
- Keep Home and page descriptions, social tags, and agent metadata current when
  changing features.
- Do not display commercial terms or amounts in Chat, recommendation prose, or
  Calling details. Preserve truthful machine protocol fields for API compatibility.
- Keep Chat concise: one agent, protocol, endpoint, representative tool, quality
  grade, test report evidence, and recent activity confirmation. The detail drawer
  provides essential connection and input information. Hide raw JSON and session
  controls from Chat.

Persistent guidance: [AGENTS.md](AGENTS.md) and
[public frontend rule](.cursor/rules/public-frontend-content.mdc).

## Selection

1. Match the task using the local FTS index and tool descriptions. A local alias
   dictionary supports common Korean task terms without generating output copy.
2. Require a public HTTP(S) endpoint with successful health, test, or usage evidence
   within the last 24 hours. Exclude failing, quarantined, security-review, and
   grade-F candidates, including unresolved recent failures.
3. Prefer candidates with a successful test report or recorded execution check,
   newest successful verification first. Fall back to recent health evidence only
   when no successfully tested relevant candidate is available.
4. Prefer recent successful activity, then grades A, B, C, D, and unrated.
   Use the newer evidence if report and evaluation grades differ.
5. Resolve ties using quality score, success rate,
   observed latency, relevance, and stable resource ID.

Explicit A2A, MCP or x402 preferences filter candidates before recency ranking. A
structured selector takes priority over protocol mentions in the question. Commercial
attributes, customer history and popularity do not determine ranking. Existing
discovery arguments remain accepted for transport compatibility. An irrelevant or unverified candidate is never substituted to fill
an empty result: return `status: no_match` with an empty array instead. Explicit
session, contact, and notification commands remain separate from discovery.

### 게이트웨이가 중계하지 않는 도구 (11-12, PM 결정 (나-1)(다))
- `connection_available`은 "우리 게이트웨이로 그 과제의 도구를 실제로 쓸 수 있음"을 뜻한다.
  - 추천한 도구가 게이트웨이 tools/list에 없으면 False다. 메일 보내기(`send_email`·`email_send`) 같은 작업형 도구는 `safe_registered_tool`에 걸려 게이트웨이가 내놓지 않는다.
  - 판정: `gateway_exposure`가 이런 항목에 `tool_unlisted`를 붙이고, `connections._public_agent`가 False로 둔다.
- 이런 추천의 카드에는 `connection_note`가 붙는다. 답 텍스트에는 `Connection:` 줄이 들어간다(영어 공개 문구).
  - 문장: "This tool performs an action, so the Agent Concierge gateway does not relay it. Connect through the provider's own documentation: <website 또는 repository>"
  - 출처 URL이 없으면 "Connect through the provider (<이름>) directly."로 끝난다.
- 제공자의 호출 주소(바인딩)는 늘 숨긴다. 응답 경계의 `project()`가 게이트웨이 주소로 바꾸는 원칙은 그대로다.
  - 안내에 쓰는 URL은 `details.website`, 없으면 `details.repository`다.
  - https만 쓰고, 쿼리·`@`가 있거나 바인딩과 같은 주소는 쓰지 않는다.
- 순위: 같은 과제에 게이트웨이가 중계하는 대안이 있으면 그 대안이 앞선다(11-11 `tool_unlisted` 순위 보정).
- 측정: user_slo connect는 답이 준 연결 경로를 그대로 따른다. 이런 추천은 연결 미달로 남는다(표본 제외 없음).
- 품질: 실제 과제 성공률에서 '직접 연결 필요'로 답한 작업형 과제는 성공으로 세지 않는다.

### Price fields (11-12)

Every card that carries `price_usdc` also carries `price_status` (`agent_market/concierge/price_status.py`):
`free` (price 0 and no price stated in the listing's own name or description), `paid` (`price_usdc` per call
in micro-USDC) or `paid_or_unknown`. A listing whose own text states a price ("x402 $0.002/min", "0.01 USDC",
"pay-per-call") is answered with `price_usdc: null` and `paid_or_unknown`, never 0; an amount of zero is not a
price. The public Free badge, the agent detail page, Chat text and find_agents/search/explore cards use this
one rule. Collection still stores 0 for these listings; telling 0 from unknown there is a separate change.

## Request path and security

`FastConcierge` uses `QualityRecommender`, local search, and stored verification
records. The question path makes no generative-model, embedding, or live endpoint
check calls. Background collectors continue updating the evidence. Report dates
support numeric and ISO values, with records linked by resource ID or URL.

Keep visitor tokens in transport and session storage. Preserve token hashing,
context binding, body and request limits, CSP nonces, public endpoint validation,
HTML escaping, credential redaction, and session replay masking. Sensitive schema
values must not appear in browser responses; schema field names remain available
for connection compatibility.

`details 1` refreshes the selected agent's evidence, `more` returns one alternative,
and `failed 1` records the failure and selects at most one replacement. Existing
notification and verification commands remain supported.

## Verification

Run `python scripts/check_front_content.py` after frontend edits. It checks the
public source and maintenance scripts for literal Hangul, embedded HTML parity,
removed private/development presentation, Chat copy, and current Home metadata.
Use the browser content, single-agent recommendation, and frontend security tests
to verify rendered content, routing, safe connection details, and output escaping.

Earlier selection validation: [implementation verification](reports/single-agent-2026-10-17/README.md).


## Optional task updates and admin integration

Recommend before collecting contact details. Task authorization, destination review,
address ownership proof, and optional marketing permission are separate choices.
A native browser PushSubscription requires explicit permission and a click on the
actual encrypted test notification. Do not describe manual polling as browser
notifications or activate it as a silent fallback. HTTPS webhook/A2A inboxes require
a received verification code after destination review. Declining a pending request
physically removes it. Rejected browser permission removes known browser requests.

Recommendation protocol and delivery channel are independent. Watches expire after
90 days and can be paused, stopped, renewed or deleted from Notification Preferences.
Marketing is optional and unchecked; only a separately opted-in verified destination
may be marked eligible. This release records that permission and enables admin
inspection/filtering, while advertising delivery and legacy nurture sends are denied.
Marketing withdrawal is independent of task updates. Admins may remove permission,
but cannot grant or restore it. The Visiting Agents menu shows actual questions,
protocol, scoped watches, verification status, purpose-choice history and delivery state.

All public copy and footer policies must describe these actual behaviors. Keep
private destinations encrypted and out of conversation history, logs and public
listings. Verify both browser and API security with isolated data after development.
The user runs the server from their terminal: do not restart it during development.

## Customer workspace access

The user requested direct development testing with the public Workspace link hidden on 2026-10-19. `CUSTOMER_WORKSPACE_ACCESS_ENABLED=1` enables the customer routes; the independent `CUSTOMER_WORKSPACE_LINK_ENABLED=0` keeps navigation and Home advertising hidden. Leave the link hidden until development is confirmed complete and the user authorizes its release. Both code defaults remain closed, and provider configuration alone does not open the portal. The existing registered Google and GitHub clients are used; first successful sign-in creates a provider-linked customer account, returning sign-in reuses it, and sign-out revokes the customer session and its BFF capabilities. No email-based account merging or staff membership is inferred. Existing staff administration stays separate. See the scoped launch report for isolated verification and the current real-account acceptance status.
