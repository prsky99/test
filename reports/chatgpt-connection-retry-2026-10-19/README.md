# ChatGPT local connection retry — 2026-10-19

## Verified scope

The user explicitly authorized local testing of the designated account with
`gpt-6.1-sol`, reasoning `medium`, then approved basic identity/plan access and
owner-only local token persistence. Browser/native UI reached the real OpenAI
consent page; the resulting callback passed issuer/signature/audience/nonce,
state, PKCE, expected-account and granted-scope validation. No desktop/CLI auth
cache was copied. The dedicated credential file is ignored by Git and mode0600.
`connection-status.json` records only verification booleans and permission mode.

The existing project server was not restarted, stopped or replaced. The local
callback listener is separate and closed after its five-minute authorization
attempt. Public Workspace navigation and hosted ChatGPT inference stay disabled;
local Ollama remains the private workflow studio's configured provider.

## Real request observations and changes

- The first two planning attempts stopped before inference because the account
  catalog exceeded the original 512KiB bound. A read-only measurement confirmed
  569,148 bytes, nine models and the requested model/medium option.
- Catalog parsing now has a separate 2MiB cap, a 100-model limit, duplicate/slug
  checks, strict JSON parsing and a projection to slug/visibility only. It does
  not retain or forward large model prompt metadata. Identity/token parsing
  bounds remain separate.
- The next real inference requests returned HTTP200 without a Content-Type
  header. The adapter originally rejected them at that header boundary.
- A missing media header now still requires strict SSE framing, a completed
  terminal response for the exact requested model, bounded output and an
  approved typed graph. An explicit wrong media type, HTML, interrupted stream
  or provider failed/incomplete event rejects the proposal.
- The third original inference attempt reached a provider failure event; it
  was rejected, not reported as a completed graph. Safe HTTP trace metadata is
  recorded in `chatgpt-2.json` and `chatgpt-3.json`; provider text/tokens are absent.
- A separate minimal READY diagnostic was rejected by automatic approval review
  as outside the three authorized research requests. It was not executed.
  Additional diagnosis is limited to the user's separate approval, if granted.

`probe_live.py` uses only the three reviewed public research objectives and
approved Paper Finder/docs contract references. It writes new evidence files
for later attempts rather than overwriting earlier observations. It never
writes the operating database, silently changes models or falls back to API-key
usage. Authentication/catalog success alone is not inference acceptance.

## Validation

`combined-regression.xml`: 109 focused tests passed, zero failures/skips.
`provider-regression.xml`: 44 current provider/callback tests passed. Scoped
critical Ruff checks passed; `bandit.json` has zero findings. Public content
checks found zero violations in 93 files.

Provider regressions cover large catalogs, excess/duplicate/malformed records,
private credential handling and rotation, exact model/effort, strict/partial
stream handling, safe errors and a clean OAuth completion redirect. The callback
HTTP response is exercised with a synthetic socket and identity exchange;
production credentials are not used by isolated regressions. This is targeted
verification of the changed local adapter, not a platform-wide penetration test.

A later explicitly requested model-discovery test identified the actual provider
error as `subscription_sharing_usage_limit_exceeded`. The official usage screen
showed the weekly allowance exhausted; the user deferred further tests. See
[the model availability report](../chatgpt-model-selection-2026-10-19/README.md).
No generated ChatGPT workflow is counted as saved or successfully executed.

Official sources:
[registration](https://developers.openai.com/siwc/token-sharing-open-source/sign-in),
[models/inference](https://developers.openai.com/siwc/token-sharing-open-source/models-and-inference),
[errors/recovery](https://developers.openai.com/siwc/token-sharing-open-source/errors-and-recovery),
[hosted integration requirements](https://developers.openai.com/siwc/website).
