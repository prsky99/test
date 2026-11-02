# Private workflow AI providers — 2026-10-19

## Outcome

Local Ollama planning is wired into the existing private customer workflow
studio. After the user restarted the existing server, computer-use tests signed
back in with the already authorized Google account, generated three proposals,
reviewed and saved them, and ran each exactly once against the approved real
Paper Finder connection (resource 34807, `docs.search.v1`, `search_papers`).
The account now has its previous ten samples plus these three AI samples.
The public Workspace navigation link remains hidden.

- AI 01 - Research Discovery: 2/2 steps succeeded; 8.822 seconds.
- AI 02 - Security Research: 2/2 steps succeeded; 7.554 seconds.
- AI 03 - Customer Support Research: 2/2 steps succeeded; 9.545 seconds.

`ui-ai-1.txt` through `ui-ai-3.txt` retain the actual browser states.
`local-ai-result.jpg` shows both successful steps of the third sample.
`audit_account.py` opens the operating database in read-only mode and selects
only this authorized workspace's three named samples. `account-lineage.json`
confirms 13 saved workflows, one successful retained run per AI sample and
6/6 input hashes matching the resolved literal/prior-output data. Each second
query differs from the first and equals the preceding result title. The second
search can return the same record because it searches that exact title; no
output transformation or quality improvement is inferred from that fact.

## Changes and cause

The previous private service had no configured graph proposer at startup.
The full nested-DAG request and short timeout also made the small local model
produce rejected or semantically unsuitable plans. The implementation now:

1. Loads an explicit opt-in Ollama proposer from trusted startup configuration,
   independently of discovery Chat or customer login providers.
2. Uses compact constrained JSON for the AI-selected query and approved agent
   pairs, then deterministically compiles a reviewed sequential search chain.
3. Preserves two-to-ten step support, approved-pair checks, output validation,
   bounded network handling and revalidation of session/version authority.
4. Gives local generation a 45-second request/body bound within the proposal
   service's 60-second authority window; no automatic retry or execution.
5. Synchronizes editor rows with the actual generated definition and clears
   stale proposals before generation. A rejected suggestion leaves manual
   review available and does not relabel an existing workflow as unknown.

The selected local runtime is `gemma3:1b`. Three standalone live planning checks
returned valid connected plans in 1.519, 1.196 and 1.380 seconds; see
`local-final-1.json` through `local-final-3.json`. These timings measure planning,
not the later agent workflow execution. Earlier diagnostic files preserve
rejected/full-DAG trials and are not counted as successful acceptance cases.

## ChatGPT status and approval boundary

A separate local OAuth callback CLI and account inference adapter are implemented.
They are deliberately not enabled as a shared hosted customer provider. The
adapter requires the exact account-visible `gpt-6.1-sol` model, reasoning
`medium`, a completed streamed Responses result and an approved typed graph.
There is no fallback to another model or API-key billing.

The actual official OpenAI login page did not advance after Google/email
Continue actions. The user confirmed the same behavior when operating it
manually. No consent was granted, no real token was issued or stored, and no
real ChatGPT inference is counted as passed. This is the remaining blocker for
the requested real-account test, separate from the completed local tests.
`chatgpt-sign-in.jpg` records the visible blocking page without credentials.
The temporary listener accepts callbacks for five minutes and then removes
its one-use authorization file. No project server was started or restarted.

The implemented security boundaries include one-use state/PKCE/nonce, fixed
issuer and JWKS signature validation, issued-client audience checking, limited
loopback callback lifetime, private owner-only files, atomic refresh-token
rotation and verified subject continuity. Hosted use still requires an approved
hosted client, registered HTTPS redirects and per-customer credential isolation;
owner test credentials must never serve other customers.

Official references reviewed:
[local account sign-in](https://developers.openai.com/siwc/token-sharing-open-source/sign-in),
[models and inference](https://developers.openai.com/siwc/token-sharing-open-source/models-and-inference),
[website integration](https://developers.openai.com/siwc/website).

## Verification

- `final-backend.xml`: 171 tests passed, zero failures/errors/skips. Covers
  local planning, proposal authorization, customer authoring, startup settings,
  hidden Workspace navigation, wiring, and ChatGPT protocol security.
- `browser-security.xml`: four isolated Chromium cases passed. Includes
  customer review/save/test flow, failed generation recovery, rendered editor
  synchronization, approved adapter usage and multi-step execution. These use
  isolated test data; real account actions above were performed with CUA.
- Scoped critical Ruff checks: passed.
- `bandit.json`: zero findings in the three model/login production modules.
- Public frontend content checker: 93 files, zero policy violations.
- Application PostgreSQL statement catalog: 3,473 statements / 223 tables;
  final `--check` passed unchanged. No native PostgreSQL service was tested here.

This is focused acceptance of the changed private AI generation and its
security boundaries, not a whole-platform penetration-test certification.
Only one already approved real agent is currently connected in these samples;
three workflows do not mean three distinct providers or arbitrary DAG synthesis.
The generated public research records are not independently graded for factual
accuracy. Hosted ChatGPT and real-account inference remain unverified as above.

## Later account connection retry

A subsequent user-authorized run completed account connection and investigated
real provider compatibility. This earlier report's login blocker is historical;
see [the retry report](../chatgpt-connection-retry-2026-10-19/README.md) for the
latest status. Local three-workflow acceptance above remains unchanged.
