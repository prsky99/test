# Workspace responsiveness and model comparison

2026-10-20. Scope: the existing private customer Workspace, its shared Pearl shell, typed studio, protected local ChatGPT evaluation adapter and the previously pending invoice-recommendation restart check. The public Workspace link stays closed. The operator owns server restarts.

## Implemented and isolated-tested

- A shared nonce-protected script shows an immediate nonblocking progress panel, source-button spinner and actual elapsed seconds. The outer studio action remains busy until rendering completes. Session/organization/credit/recovery/individual-task requests also use the shared feedback. No invented model stages or percentage are shown. Reduced motion remains supported.
- Short-lived reads use the existing frontend cache pattern of memory reuse plus in-flight deduplication, adapted to private pages: only typed flow lists/details, 10 seconds, at most 20 entries and 262,144 characters per entry. No private payload is placed in browser persistent storage, HTTP caches or a service worker. Authority, sessions/CSRF, credits, options, execution history, releases and downloads stay fresh. Writes, denied/failed requests, explicit Refresh, hidden tabs and page exit clear reuse; writes and AI/execution requests are never retried automatically. Server authority and current revision checks still gate every mutation.
- The AI objective and generation action come before the workflow library. New workflow and Browse actions share the heading. Saved workflows have name search and up to six matching cards, with the complete selector retained. The four explicit Design → Review/save → Test → Download stages remain. Light/dark, keyboard focus and 390-pixel mobile layouts are retained. The AI button is verified inside 1440×900 and 1920×780 first viewports.
- Consent fields are disabled during an in-flight action so a late prepare response cannot erase a choice made while processing. Optional read panels opened during an action are loaded after it finishes; this does not unlock an uncertain workflow or repeat a mutation.
- The local ChatGPT adapter accepts an explicitly selected supported model/effort and optional expected account. No fallback model is selected. Besides a full final response output, it handles completed output-item events when the final successful response has an empty output array. It still requires the exact model, a successful final completion, completed assistant content, bounded output and exact agreement with streamed deltas. Interrupted, duplicate, conflicting and wrong-account output is rejected. No shared website ChatGPT provider or pooled customer credentials were enabled.

## Current verification

- Final integrated isolated suite: **152 passed**, failure/skip 0 (`final-integrated.xml`). It includes actual application handlers, disposable accounts/DBs, browser interactions, credits/consent, role and cross-scope denial, private metadata/CSP, cache invalidation/bounds, ambiguous outcome protection and stream validation.
- Public frontend checker: **237 files, 0 violations**. Generated inline JavaScript and the common helper parse with Node. Scoped Ruff F/E9 passes.
- Bandit: three medium-severity, low-confidence B608 warnings on existing HTML string assembly. These strings are returned as HTML, not executed as SQL. Raw warnings are retained in `bandit.json`; no HIGH finding. This is a scoped code/security regression, not proof that all vulnerabilities are absent.
- The prior invoice fix is now live: public Chat returns HTTP200 in 3.346 seconds, `No currently active, relevant agent found.`, no unrelated recommendation. This closes that earlier restart item (`invoice-restart-check.json`).
- No operating server, PostgreSQL configuration, retired SQLite file, customer authority, external app consent or public Workspace switch was changed.

## Actual provider comparison

The same three public research goals were submitted through the current adapters: battery recycling (2 steps), accessible interfaces (3) and software supply chains (2). All used the same approved first-party Research Papers reference. Names, account/session identity, private workflow data and tokens were not included in provider prompts. ChatGPT used the previously authorized local account connection with an expected-account check. Raw credential material stays in the pre-existing Git-excluded owner-only location.

- GPT-5.6 Luna / low (requested Light): 7.868, 7.407, 8.648 seconds; mean **7.974s**; 3/3 valid.
- GPT-6.1 Sol / high: 9.166, 9.427, 6.921 seconds; mean **8.505s**; 3/3 valid.
- Installed local gemma3:1b: 3.145, 1.682, 1.246 seconds; mean **2.024s**; 3/3 valid.

Every final graph matched the requested step count, English inputs, approved resource/contract and explicit sequential title bindings. This establishes structural/advisory acceptance for these three goals, not general semantic accuracy, arbitrary workflow capability or a statistically reliable latency ranking. Only one run per goal/model was included in the final comparison; earlier ChatGPT parser-diagnostic requests are preserved separately and excluded from the final mean, not hidden as successful runs. No token consumption quantity was measured.

This is a comparison of current service adapters, not identical raw-model prompts: Gemma selects a compact search query and approved pairs, then the existing deterministic compiler constructs bindings; ChatGPT emits a full graph. The local path has no remote round trip. These differences explain why equal graph-validation rates cannot establish equal reasoning capability. For this bounded research workflow path, retaining the local default is supported by these observations; broader or more complex tasks require separate evaluation.

Evidence: `chatgpt-local-tests.json`, `chatgpt-sol-high-tests.json`, `gemma3-local-tests.json`, `comparison.json`. Earlier stream failures and the successful captured-stream replay remain in separate diagnostic files. The captured raw stream contains only the public objective response and is held in an owner-only private diagnostic file, not this report.

Official schema references: [GPT-5.6 Luna](https://developers.openai.com/api/docs/models/gpt-5.6-luna), [GPT-6.1 Sol](https://developers.openai.com/api/docs/models/gpt-6.1-sol), [Responses streaming](https://developers.openai.com/api/docs/guides/streaming-responses). `low` and `high` are the actual request values; Light is not sent as an unsupported literal API effort.

## Real Workspace acceptance so far

CUA renewed the existing Google customer session after expiry, preserving unsaved inputs. The first Luna graph was entered unchanged into the existing exact-input editor, reviewed, explicitly saved and run in the requested account. This is local ChatGPT inference plus a real Workspace import/review; it is not a claim that the website's Generate button directly invokes a hosted ChatGPT integration.

The retained workflow is **ChatGPT Luna - Battery Recycling Research**. Save spent one credit (99,986 → **99,985**), with 30 workflows shown. Both research steps succeeded. The first source DOI was `10.4271/j2974_201504`; the second, searched via the declared prior-title binding, was `10.4271/j2974_201902`. No deployment/release permission or paid service was issued. The site button still uses the separately configured local model.

## Operating UI acceptance — completed

The operator restarted the server with the prepared source (8200 listener PID 65868). CUA confirmed the new rendering and immediate loading feedback in the actual signed-in studio. This supersedes the earlier restart-pending state.

Screenshots `studio-light.png`, `studio-dark.png`, `studio-mobile.png`, `studio-ai-progress.png` are from disposable isolated accounts. They are not evidence that the running process has loaded new Python rendering code.


### Actual post-restart observations

- Opening the studio immediately showed “Opening your workflow studio…” and elapsed seconds while account, credit and workflow controls were unavailable. The progress panel disappeared after completion. Clicking Generate, Save, Prepare and Run also showed the common status panel and source-button spinner immediately; processing consent controls were disabled.
- The existing website Generate button used the configured local `gemma3:1b` and produced the reviewed two-step Research Papers graph. The workflow **Local Gemma 3 - Battery Recycling Research** was saved and run successfully in the same customer account. Both this graph and the Luna graph exactly match their real model outputs. Read-only PostgreSQL verification confirmed each second-step input hash matches the preceding returned title. Results: Luna workflow 3.480s, Gemma workflow 6.461s. These execution times are separate from model-generation latency, and their initial queries/source cache states differ.
- Total task spending was **2 credits**, with a final observed balance **99,984** and **31 retained workflows**. No adjustment, top-up, new plan agreement, deployment grant or release was issued. The two source DOIs in the Gemma workflow were `10.4271/2012-01-0351` and `10.4271/j2984_201206`; the second result and title differed from the first. The Plan & credits page independently showed the same balance and two new debit records, with the enrollment form remaining hidden.
- Live name search returned the retained Luna workflow; a nonsense search showed explicit no-match guidance; clearing the search restored the cards. Re-reading the selected workflow completed without rerunning its agents or spending credits. The one-network-read-for-repeated-list-reads cache behavior is established by isolated request counters, not an unmeasured live performance claim.
- The library anchor initially cleared the Workflows navigation highlight. The shared asset now reapplies the selected studio navigation after the legacy hash handler has finished. The first microtask-based fix was still cleared in real Chrome; a task queued after the hash handlers corrected the ordering. The browser regression now waits for the settled frame before asserting the state. CUA confirmed exactly one active navigation item after the final asset refresh. This asset is read into each page and required refresh only, no additional server restart.
- The final shared-asset/settled-navigation change passed **48 affected tests**, failure/skip 0 (`navigation-affected-final.xml`). They overlap the earlier 152 unique integrated cases and are not added to that unique total. The final source hashes include this asset and the strengthened browser test. Node parses the final common helper; content checks still cover 237 files, zero violations.
- The public Workspace link remains hidden (`workspace_available:false`). Cookie-free access to the scoped studio correctly returns 401/no-store JSON with `script-src 'none'`. Nonce checks do not apply to that JSON rejection; the broader `unsafe-inline` marker in the initial header probe referred to another policy directive, not permission to execute script. Actual customer documents retain nonce-protected scripts and no-store/noindex metadata.

Evidence: `live-ai-loading.png`, `live-model-workspace-readback.json`, `post-restart-page-checks.json`, `unauthenticated-studio-check.json`, `comparison.json`, final test XML and source hashes. No task-specific operating activation or restart remains. Broader arbitrary planning and approved hosted ChatGPT registration are not represented as completed by these local tests. The website's local default and closed public navigation remain the existing choices.
