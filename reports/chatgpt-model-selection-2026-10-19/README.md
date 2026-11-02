# ChatGPT model availability — 2026-10-19

The user requested current account-visible model discovery and real testing.
The authenticated official model catalog listed seven visible models:

- `gpt-6.1-sol`
- `gpt-6-astra`
- `gpt-6-sol`
- `gpt-6-luna`
- `gpt-5.6-sol`
- `gpt-5.6-terra`
- `gpt-5.6-luna`

These are catalog entries, not successful inference claims. `catalog.json`
records only model identifiers and an expected-test-account verification flag.

A single real public research workflow request using `gpt-6.1-sol` and reasoning
`medium` returned the explicit stream error
`subscription_sharing_usage_limit_exceeded` after HTTP200. It completed no
validated graph. See `inference-result.json`; no token or raw provider message
is stored in that report. No other model was invoked after this quota failure.

Computer-use inspection of the official ChatGPT Usage settings showed 70% of
the five-hour allowance remaining and 0% of the weekly allowance remaining.
Agent Concierge's plan access was enabled with a 100% app allowance. Credit
fallback for other apps was off. No usage, financial, permission or account
setting was changed, and no credits were purchased or enabled for this app.

The user explicitly deferred further tests until their allowance recovers.
No automatic retry, monitor or scheduled job was created. The previously
approved protected local connection remains available for later verification;
credentials must not be copied into reports or pooled for hosted customers.
The existing project server and local Ollama configuration remain unchanged.
No production source was changed during this model-discovery turn, so this
report does not claim a new full regression run or real inference success.

Resume only when the user requests further testing and usage is available.
Refresh the selected account's catalog, then perform a bounded real request
and require response.completed plus the existing model/typed-graph validation.
Do not rotate models or change billing to evade an account usage restriction.

Official recovery reference:
[ChatGPT plan usage errors](https://developers.openai.com/siwc/token-sharing-open-source/errors-and-recovery).

## Authorized resumption — 2026-10-20

The user reported restored allowance and explicitly resumed testing. Actual GPT-5.6 Luna/low and GPT-6.1 Sol/high public workflow proposals passed, three goals each; local gemma3:1b was compared on the same goals. This supersedes the operational deferral above without altering its historical quota observation. The protected local connection remains local. See [current test and Workspace report](../workspace-responsive-ai-2026-10-20/README.md).
