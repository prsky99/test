# Public Agent Frontend

> Screen policy: `docs/FRONTEND_SCREEN_POLICY.md` (11-01). Fixed content renders directly in HTML, no full-screen loading, and loading appears only in the affected area when the user acts.

The public frontend returns up to three relevant agents ranked by recent successful verification,
recent activity, and quality grade. New protocol-unspecified requests default to A2A;
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
- Keep Chat concise: up to three agents, each with protocol, endpoint, representative tool,
  quality grade, test report evidence, and recent activity confirmation. The detail drawer
  provides essential connection and input information. Hide raw JSON and session
  controls from Chat.

Persistent guidance: [AGENTS.md](AGENTS.md) and
[public frontend rule](.cursor/rules/public-frontend-content.mdc).

## Selection

1. Match the task with the hybrid catalog search: PostgreSQL with pgvector and OpenSearch in production
   (`concierge/opensearch_lexical.py`, `hybrid_explore.py`; SQLite FTS5 only in tests and local runs) over listing
   and tool descriptions. A local alias dictionary supports common Korean task terms without generating output copy.
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

### Order of the (at most three) results (`concierge/fast_chat.py`, `gateway_exposure.py`)
- `order_key`: listings with an access note (paid, key or account needed) and failing standing go after the others;
  for a task that names no place, listings serving any place come before region-limited ones; recent real successes
  first. The sort is stable.
- `subject_first`: when the first candidate never names the task's subject and another does, that one leads.
- `mentioned_only_last`: a listing whose description names the subject but none of whose tools does moves behind the
  candidates whose tools say it.
- `condition_first`: among candidates naming the subject, the one meeting more requested conditions (fewer violated,
  then fewer unknown) leads.
- A relayed alternative leads a tool the gateway does not relay (see below).
- Closeness check: the first result's chosen tool is compared with the task by a stronger embedding model in a
  worker, within a time budget. Below `CHOICE_CLOSENESS` (0.70) the answer offers the list as choices
  (`status: needs_choice`) instead of asserting it.

Explicit A2A, MCP or x402 preferences filter candidates before recency ranking. A
structured selector takes priority over protocol mentions in the question. Commercial
attributes, customer history and popularity do not determine ranking. Existing
discovery arguments remain accepted for transport compatibility. An irrelevant or unverified candidate is never substituted to fill
an empty result: return `status: no_match` with an empty array instead. Explicit
session, contact, and notification commands remain separate from discovery.

### Run here (11-12)
- MCP hosts (desktop apps, IDEs) cannot attach a new server in the middle of a conversation, so the `call` tool of
  our /mcp runs a recommended tool in the same session (anonymous, informational tools only, through the gateway).
- MCP recommendation cards the gateway relays carry two fields (`connections._public_agent`):
  - `run_here`: `{"tool":"call","arguments":{"resource_id":…,"tool":…,"arguments":{example required fields}}}`
  - `mcp_config`: `{"mcpServers":{"<name>":{"type":"http","url":"<gateway address>"}}}`
- The first item of the answer text carries `Run here: call {...}` and `MCP config: {...}` lines (find_agents and
  Chat alike, `fast_chat._brief`).
- Arguments the task makes certain are filled in (`concierge/run_here_fill.py`, 11-16): a city from a fixed list,
  a domain, URL, IP, CVE id, ISO date, DOI, listed ticker, coin, currency pair (upper-case codes, or lower case only
  with '/' or with money words such as rate or exchange) and a GitHub owner/repo. All placeholders are filled or
  none; a value is at most 200 characters on one line and never an e-mail address. Otherwise the placeholders stay.
  The card, the line and `continuation_plan.run_here` carry the same filled call.
- When an offered necklace's phrases match the task (`concierge/necklace_lead.py`, `necklace_leads.json`), the
  answer's first line is "Free to run now: <necklace> … call tool `necklace_<slug>` with {...}" (A2A: `run necklace
  <slug> {...}`), with inputs from the task only when certain.
- `continuation_plan.run_here` holds the same value; `next_steps` still holds only the other lists to use next
  (follow_up_query and the safety-gate contract, test_b2a_retention).
- Example required fields (`example_arguments`)
  - The first enum value or the default, only when it is a short plain value and never a URL.
  - Otherwise a value by type (integer: minimum or 1; boolean: false), and failing that a `<field name>` placeholder.
  - The provider's free-text examples are not copied.
  - The tools/call example arguments in connect_steps use the same values.
- `gateway_ready` and `connection_available` mean the same: usable now through our gateway. The chosen tool must be in
  the gateway's list, and when the registration was read its readiness counts too. Action tools (01982678) are False
  for both and carry no `run_here`.
- The response boundary still hides every call address; the only address in examples and settings is the gateway's.

### Tools the gateway does not relay (11-12)
- `connection_available` means "the tool for this task can really be used through our gateway".
  - A recommended tool missing from the gateway's tools/list is False. Action tools such as sending mail (`send_email`,
    `email_send`) are held back by `safe_registered_tool`, so the gateway does not offer them.
  - `gateway_exposure` marks such items `tool_unlisted`, and `connections._public_agent` sets False.
- Such cards carry a `connection_note`, and the answer text a `Connection:` line (public English wording):
  - "This tool performs an action, so the AgentValCon gateway does not relay it. Connect through the provider's own
    documentation: <website or repository>"
  - Without a source URL it ends "Connect through the provider (<name>) directly."
- The provider's call address (binding) is always hidden; the response boundary (`project()`) still swaps it for the
  gateway address.
  - The URL in the note is `details.website`, else `details.repository`: https only, no query or `@`, never the binding.
- Ranking: when a relayed alternative exists for the same task, it comes first (11-11 `tool_unlisted` correction).
- Measurement: user_slo connect follows the connection path the answer gave; such recommendations stay as not
  connected (no samples are dropped).
- Quality: in the real task success rate, an action task answered with "connect directly" is not counted as a success.

### Price fields (11-12)

Every card that carries `price_usdc` also carries `price_status` (`agent_market/concierge/price_status.py`):
`free` (price 0 and no price stated in the listing's own name or description), `paid` (`price_usdc` per call
in micro-USDC) or `paid_or_unknown`. A listing whose own text states a price ("x402 $0.002/min", "0.01 USDC",
"pay-per-call") is answered with `price_usdc: null` and `paid_or_unknown`, never 0; an amount of zero is not a
price. The public Free badge, the agent detail page, Chat text and find_agents/search/explore cards use this
one rule. Collection still stores 0 for these listings; telling 0 from unknown there is a separate change.

## Request path and security

`FastConcierge` uses `QualityRecommender`, the catalog search and stored verification
records. The question path makes no live endpoint checks; background collectors keep the evidence current. It does
use embeddings (retrieval and the closeness check above), and when no listing matches words that no listing contains,
the local model respells or translates the task once for retrieval only (`concierge/chat_query_rewrite.py`: data, never
a choice of agent or an instruction). Report dates support numeric and ISO values, with records linked by resource ID
or URL.

Keep visitor tokens in transport and session storage. Preserve token hashing,
context binding, body and request limits, CSP (sha256 hashes on the shared public pages, nonces on signed-in
customer pages), public endpoint validation,
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

## Public surfaces beyond Chat (11-16)

- Pages people read: `/new/en/*.html` (the nine `live_pages` in `new/en-manifest.json`) assembled by
  `concierge/pearl_view.py` (bundled CSS and JS, first-screen CSS, `panels.js`); a release keeps each assembled page
  per process. Growth pages: `/connect`, `/agents/tasks`, `/agents/task/<slug>`, `/agents/best`, the per-category
  full lists `/agents/best/<category>/all[/<n>]`, `/agent/<id>`, `/agents/compare/<a>-vs-<b>`, `/reports/…`,
  `/methodology` (`growth_pages.py`, `growth_catalog.py`, from the daily task snapshot). x402, thin and duplicate agent
  pages are `noindex, follow` and left out of the sitemap; x402 rankings and comparisons are `noindex, nofollow`.
- Necklaces (`concierge/necklace_surface.py`): `/necklaces/<slug>`, `/api/necklaces`, MCP tool `necklace_<slug>`, A2A
  skill `necklace-<slug>`, the Home and Workflows card. Only offered necklaces appear. Numbers follow the display rules
  of 11-16: "Measured" only for what the test runs measured on the necklace; the direct path's calls, tokens and
  seconds are said to come from the same runs' records; its accuracy and estimated finding and merging costs are not
  shown; tokens always carry "(text length ÷ 4)". Requests: `/necklaces/request` (no contact details).
- Sponsored slot (`concierge/ad_slot.py`): MCP and A2A answers have no switch to turn it off; a booked offer follows the
  organic text as one line starting "Sponsored:".
- Sitemap and robots: `/sitemap.xml` is an index of `/sitemaps/pages.xml` and `/sitemaps/agents-N.xml`
  (`sitemap_parts.py`); robots.txt names the index and each part on its own `Sitemap:` line.
- Edge caching (`public_http_contract.py`): only responses that are the same bytes for everyone and set no cookie are
  shared. Growth pages: browser 5 min, edge 6 h (+1 day stale); noindex growth pages and the sitemap: edge 10 min
  (+1 h stale). `/customer/sign-in` carries nothing personal and is kept 5 min in the browser and 1 h at the edge
  (`customer_sign_in_cache.py`); signed-in pages and answers stay `no-store`.


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
Production runs under launchd as four roles (frontend, admin, jobs, execution) managed with `./agentcon`
(`deploy/DEPLOY.md`). Do not start a second server on this Mac and do not restart services outside `./agentcon` and
its deploy lock.

## Customer workspace access

The user requested direct development testing with the public Workspace link hidden on 2026-10-19. `CUSTOMER_WORKSPACE_ACCESS_ENABLED=1` enables the customer routes; the independent `CUSTOMER_WORKSPACE_LINK_ENABLED=0` keeps navigation and Home advertising hidden. Leave the link hidden until development is confirmed complete and the user authorizes its release. Both code defaults remain closed, and provider configuration alone does not open the portal. The existing registered Google and GitHub clients are used; first successful sign-in creates a provider-linked customer account, returning sign-in reuses it, and sign-out revokes the customer session and its BFF capabilities. No email-based account merging or staff membership is inferred. Existing staff administration stays separate. See the scoped launch report for isolated verification and the current real-account acceptance status.
