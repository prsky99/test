# Project guidance

## Public frontend content

These rules apply to the public Agent Concierge frontend, its source comments,
metadata, generated pages, and scripts that modify it. They do not require
translating backend/admin implementation comments or historical audit artifacts.

- Author all product copy and frontend source comments in English. Do not add
  literal Hangul to public frontend source. Keep non-English input aliases
  escaped; user input and language-support tests are not product copy.
- Use a modern, uncluttered frontend design and Lucide icons. Keep spacing,
  typography, rounded surfaces, and responsive layouts consistent with the
  existing theme. Prefer local SVG icons and preserve accessible labels,
  visible keyboard focus, light/dark themes, and reduced-motion preferences.
- Never publish private system configuration, deployment paths, runtime/model
  details, developer diagnostics, credentials, visitor profiles, or personal data.
  Public agent connection information and official service contacts may remain.
- Keep page titles, descriptions, social tags, agent metadata, and Home content
  consistent with the current product behavior whenever features change.
- Chat recommends up to three relevant agents or published workflows. For agents
  within each protocol scope, first place listings whose own name or leading
  description names the task (or small MCP servers whose few tools are the task)
  ahead of bundles where only one of many tools matches; within each tier, rank
  recent successful verification (test report or execution check), recent
  activity, then quality grade, without customer-tier priority. Automatic and Any
  searches order focused A2A, focused MCP, then bundled A2A and MCP. Explore uses
  the same order: exact name, task in the name or leading description sentence,
  then later mentions, across A2A and MCP. For workflows, require task capabilities and prefer focused steps
  over unrelated extras before freshness. Keep safety/relevance gates and newest
  replies first.
- Chat supports an explicit A2A, MCP, or x402 selection and protocol requests in
  the question. Apply quality ranking within the requested protocol; an explicit
  selector takes precedence. Automatic and Any searches prefer eligible A2A results, then fill remaining
  places with MCP. Exclude x402 unless the user or visiting agent explicitly
  selects or requests x402. Explicit A2A/MCP filters remain strict; retain
  the selected scope for follow-up details/alternatives. Keep recommendation protocol separate from delivery.
- Treat the frontend as a global English-first service. Align interactions with
  factual footer privacy, notification, accessibility, and service disclosures.
- Integrate optional task updates with the admin Visiting Agents menu. Require
  purpose-specific authorization and destination verification; never infer
  marketing permission from a visit, callback, or legacy notification flag.
- Browser notifications require native permission, a native PushSubscription, and
  confirmation by clicking the delivered test notification. Manual polling is
  explicitly separate. Declining pending verification deletes the request.
- Record optional marketing permission separately, unchecked by default, and expose
  eligibility only after destination verification. Support independent withdrawal
  and admin inspection/filtering; advertising delivery remains disabled.
- After development, run secure-coding checks and dynamic browser/API security
  regressions with isolated test data. Report actual scope and remaining limits.
- Do not display free/paid, payment, billing, pricing, fees, cost, plan upsells,
  provider amounts, or wallet details in Chat, its replies, or its detail view.
  Preserve accurate machine protocol fields needed by existing API clients;
  hide them from the product interface rather than falsifying provider facts.
- Keep visitor tokens in the session transport; do not display visitor identity,
  tokens, raw response JSON, stack traces, or implementation examples in Chat.
- Keep `agent_market/concierge/front.py`'s embedded `HTML` and
  `extracted_html.txt` synchronized. Preserve CSP, output escaping, input masking,
  and existing security boundaries when changing presentation.
- Run the public frontend content check and relevant browser/security regressions
  after changing frontend copy, metadata, or rendering.

## Server operation

- The user runs the development server directly in their terminal. Do not stop,
  restart, replace, or launch a competing project server unless explicitly asked.
  Use isolated test apps/databases and temporary ports for verification; explain
  when source changes require the user's server restart.
- Several workers deploy to the same managed slots. Before packaging, check
  `./agentcon status` and the newest directories in `gateway-data/services/releases`,
  and build the overlay on the release that is actually active, adding only your
  own reviewed files. After deploying, confirm the active slots and report any
  release you replaced. Never package the shared working tree directly.
