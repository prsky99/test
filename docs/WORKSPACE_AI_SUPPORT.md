# Reviewed private workflow guidance

`workspace_ai_support.py` optionally calls the configured internal planner with
only an explicitly entered public objective and the fixed approved help
documents from `workflow_support.py`. It does not send private draft content,
graph literals, workspace identifiers, credentials or provider responses.
The existing deterministic help/patch tool remains available without a model.

The current editable draft and saved snapshot are checked before the request,
and their complete authority/revision context is checked again after it. Every
model request needs a separate unchecked sharing consent. Editing the objective
or selection clears that consent. A model result can propose only bounded
English name/description changes and known source-document IDs. Unknown
documents, commands, URLs, additional patch paths and malformed JSON fail
closed. The response labels generated guidance as unverified and includes the
actual fixed source documents for review.

Generated changes become a signed review proposal. Applying it requires another
fresh consent and current revision checks. Neither generation nor application
executes agents, exports an app, publishes content or modifies global workflows.
Application changes one private draft revision. Current session/workspace
changes close the native administrator dialog and discard private UI state.

Requests use the configured server-side HTTP client, no redirects, an identity
content-encoding requirement, a 16 KiB response cap, a 4 KiB content field cap,
two concurrent slots and a ten-second network/read timeout with an elapsed-time
check. This is not an absolute process-kill deadline or a guarantee of model
accuracy. There is no operating-model quality or customer-outcome claim.

`first_party_guides.py` implements a separate read-only `docs.search.v1` help
agent over those fixed public documents, with actual MCP initialize/list/call
and resolvable source routes. Its router is explicitly opt-in and defaults off.
Serving it does not register, approve, grade or prioritize it in the catalog.
Production publication must pass the same current evidence and approval gates
as other agents. No public Workspace access menu or customer authentication
route is opened by either module.

## Private workflow graph suggestions

The private customer workflow studio can use an operator-configured local
Ollama service independently of discovery Chat. Configure
`WORKSPACE_MODEL_ENABLED=1`, `WORKSPACE_MODEL_URL` (default
`http://127.0.0.1:11434`), and `WORKSPACE_MODEL_NAME` (default `gemma3:1b`)
in the ignored operator environment. Restart the existing server in the user
terminal after changing startup settings. The feature remains disabled by
configuration unless explicitly enabled. It does not expose the public
Workspace navigation link.

The local planner receives only a freshly authorized public objective and
currently approved capability references. It chooses a bounded search query
and two to ten approved agent/contract pairs. A deterministic compiler builds
a sequential search chain: each later query reads the preceding first result's
title. This is a constrained search planner, not arbitrary workflow synthesis.
The reviewed editor displays the actual compiled definition. Suggestions never
save or execute automatically; save and test require separate fresh reviews.
Generation failures discard stale proposals without labeling an existing run
as unknown. Operator endpoints, model names and credentials are not rendered
in the customer interface.

The local request has a 45-second network/body bound and the proposal service
has a 60-second authority deadline, two concurrent slots and current
session/version/candidate checks. These are bounded requests rather than a
process-kill guarantee. Empty results or unsuitable search results can still
make a downstream title binding fail; successful schema validation is not a
claim of answer quality.

## Local ChatGPT account evaluation

`python -m agent_market.workflow_chatgpt_login --directory <private-directory>
--expected-email <authorized-test-account>` opens a five-minute loopback callback
listener, not another project server. Open the generated private authorization
URL in the browser. The identity assertion is verified using the fixed OpenAI
issuer/JWKS, issued client ID, state, PKCE and nonce; account matching for this
test does not merge customer identities. Callback codes and tokens are not
logged. Account credentials use owner-only files, locked atomic refresh-token
rotation and verified subject continuity.

`workflow_chatgpt.ChatGPTGraphProposer` is available for explicit local evaluation.
It checks the account's model catalog for exactly `gpt-6.1-sol`, requests
`reasoning.effort=medium`, `store=false` and streamed Responses, and accepts only
a completed response for that exact model. It rejects incomplete output,
unapproved agents and invalid typed graphs. There is no API-key or model fallback.
The hosted customer service does not load or share this personal credential.

A hosted ChatGPT integration requires an approved hosted client, registered HTTPS
redirects, per-customer credential isolation, revocation controls and an actual
account-authorized end-to-end acceptance test before it can be enabled.
OpenAI references: [local sign-in](https://developers.openai.com/siwc/token-sharing-open-source/sign-in),
[models and inference](https://developers.openai.com/siwc/token-sharing-open-source/models-and-inference),
[website integration](https://developers.openai.com/siwc/website).

Local acceptance update (2026-10-19): account authorization, verified identity,
required plan scopes and owner-only credential persistence passed against the
explicitly authorized account. The live account model catalog was 569,148 bytes;
it has a separate 2 MiB byte bound and projects only validated slug/visibility
fields. Unused catalog prompt metadata is discarded and never sent to inference.
Other identity/token responses retain their smaller existing bounds. A missing
stream media header is accepted only when strict SSE framing, a terminal
completed response, exact selected model and the approved typed definition all
validate; an explicit incorrect media type, partial stream or provider failure
still rejects the proposal. Diagnostics retain bounded machine error codes and
HTTP status rather than raw provider messages. Completed local OAuth callbacks
redirect to a code-free completion page with no-store and no-referrer headers.
These changes do not activate a hosted ChatGPT provider or alter the local
Ollama startup choice. See the current local retry report for inference results.

Reauthorization now reuses this local application's issued client and checks the
previous subject as well as the expected account. A malformed, insecure, foreign
host or foreign-account credential file cannot silently trigger a new client
registration. Explicitly installed local ChatGPT proposers receive the same
current-authority guard as Ollama before and during transport; this does not
install ChatGPT in the hosted startup configuration. The user's inference hold
remains in effect after the weekly quota failure.

## Gemini and Claude subscription research

See the [dated provider investigation](../reports/final-nine-execution-2026-10-19/providers/README.md).
Personal tests use unmodified official CLIs, isolated ignored profiles and only
a public research objective. They do not collect browser session tokens or
implement a customer-facing provider login. Local Ollama remains configured.

The official Claude CLI signed in and returned a valid compact two-step proposal
that passed the existing deterministic compiler. It did not save or execute a
customer workflow. Both the installed and an isolated current official Gemini
CLI reached an unsupported-client error after authentication. Quota exhaustion
was not confirmed. Neither provider is connected to hosted customer execution;
provider-specific service terms and approval boundaries still apply.


## Customer plan and Pearl workspace presentation

The customer studio now places natural-language AI generation before the retained workflow list. The reviewed definition drives the Pearl node strand; opening a node reveals its exact editable inputs and prior-result connections. No decorative node invents an executed task or a successful result. The shared presentation follows `new/design/workspace-auth/03-private-workflow-studio.png` and the published Pearl tokens, with local Lucide SVGs, keyboard focus, explicit loading states, light/dark preferences and a horizontally contained small-screen node strand. Sign-in, organizations, individual tasks and enrollment use the same customer shell. The public Workspace navigation release flag is unchanged.

Enrollment, saving, included downloads, post-download edits and credit history are documented in [Workspace credits](WORKSPACE_CREDITS.md). AI previews do not consume credits. A saved graph does, and its server-signed review fixes the quoted amount. A changed entitlement between review and save requires a fresh review. The user-authorized account acceptance on 2026-10-20 created ten real local-AI research workflows with 36 successful approved read-only agent steps, 26 verified result-to-input bindings and ten validated ZIP packages; the normal ledger changed 100,000 to 99,990. These are constrained search workflows, not a claim of arbitrary workflow synthesis or ten distinct agent providers. Separate browser generation produced an unsaved review without an additional credit deduction.
