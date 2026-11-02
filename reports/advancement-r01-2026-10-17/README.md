# R-01 stabilization implementation and regression verification

Started 2026-10-17; finalized 2026-10-18 (Asia/Seoul). **R-01 source implementation verified; deployed restart/smoke and remote CI execution pending. R-02–R-10 are not complete.**

## Existing changes verified first

The supplied security fixes were retained: public output projection, sanitized registration/adaptation errors, Testbench history shape/origin checks, drawer class allowlists, canvas bounds, snapshot caches and Learn content alignment. The broad pre-change run had **786 passed / one failed** out of 787. That failure exposed a stale notification approval after the private provider URL changed behind a stable public gateway URL. The known initial-loading click race was independently reproduced by a new delayed-response browser test.

An earlier interrupted run failed to launch Chromium/bind temporary sockets inside the sandbox; those environment failures are not product vulnerability counts. The broad run was repeated with the permissions needed for isolated browser/TLS fixtures. No production server was operated.

## Implemented

- Initial Testbench refresh preserves an explicit recipe selection, pending callback and edited inputs. Old catalog loads cannot replace newer loads. Another recipe cannot dispatch while an execution is in flight. Result inspection uses the endpoint captured for that run.
- Shared failure taxonomy distinguishes input/authorization/policy/tool/schema/network/protocol/timeout/capacity cases. Managed results and protocol execution errors carry safe categories and independent opaque support references. Testbench retains actual HTTP errors and displays support references; workflows retain safe categories. No arbitrary provider prose becomes public diagnostics.
- Private structured diagnostic logging records only the reference, numeric public resource ID, protocol, fixed code/stage and exception class. Tests assert that credentials, arguments, private URLs and provider errors do not enter these records. This does not implement R-02's persistent operation/attempt registry, complete metrics or cross-process admin query interface.
- Notification approval fingerprints and queued delivery are bound to an internal HMAC of actual registered connection/protocol/auth state and capability hash. Private URL/guide/schema changes invalidate old approval/queued delivery. Irrelevant description/fetch-time changes do not. Legacy unbound pending deliveries are canceled rather than sent. The digest is not added to public notification content.
- Manual tool-input guidance distinguishes missing validated examples. Existing unsafe/authentication/schema/SSRF restrictions remain.
- `scripts/run_frontend_regressions.py` is the repeatable isolated feature/security and catalog-name corpus gate. `.github/workflows/frontend-regressions.yml` runs it on relevant PR/push/manual events, with read-only permissions, no persisted checkout credentials, no deployment secrets and SHA-pinned official Actions. Remote GitHub execution was not performed.

## Verification

- Final broad run: **835 passed**, 55 selected modules at that collection. Two later added edge cases, the final notification metadata-noise case and 23 startup/storage/logging cases give **861 unique passing cases** across the final successful XML files. No failures/errors/skips in that union. Repeated runs overlap; do not add their totals.
- Extra edge cases: 13 passed. Final notification binding: 104 passed. Startup/storage/logging: 23 passed. Coverage includes Home/Learn/Explore, listing/registration, Chat protocol/ranking/privacy, Testbench, workflows/ZIP/SDK, footer preferences/requests, verification/withdrawal, visitor admin linkage, malicious inputs, CSP/XSS, SSRF/TLS, quotas and timeout saturation. These controlled cases are not proof of every possible production input.
- Public content: **53 files, zero violations**. Embedded frontend HTML is synchronized. Syntax checks pass. CI YAML permissions/triggers/SHA pins validated locally; hosted Ubuntu job still needs its first run.
- Current catalog: **106,487 resources / 280,723 stored MCP tool definitions**, zero audit exceptions, no new conservative refusals relative to the audit comparison policy; **5,955 destructive variants refused**. This read-only audit made **zero provider calls**.
- Static scan: **High 0 / Medium 8 / Low 12**. Existing SQL-construction findings were reviewed for fixed fragments/parameter binding; existing optional parsing/discovery/cleanup findings were retained. The additional existing proxy warning reflects broader scan scope than the previous Medium 8 / Low 11 report. `static-triage.json` preserves every finding; no zero-finding claim is made.

## Deployment and remaining work

Both local and public normal pages returned HTTP 200, CSP, four available live examples and three workflow templates. The final HTML check still lacked the R-01 loading guard, so **the user must restart their terminal-run server**, then recheck deployed examples/workflows/downloads/notification admin previews. New-source verification was performed against isolated applications and temporary databases. No new-source live provider or independently hosted exported app run was made in this turn.

After this deployment checkpoint, R-02 remains the next development stage: durable logical operation/attempt IDs, event denominator definitions, cross-process administrator trace lookup, and distinct recommendation/execution/delivery metrics. R-03–R-10 and the complete G0 remain open. Full platform source certification, long-term capacity, every remote provider's availability and live commerce are outside this result.

No server start/stop/restart, security-rule changes, direct production database writes, notification/advertising delivery or financial actions were performed. Historical log review stored category counts only; aggregate/source logs overlap and their lines are not unique incidents. Existing log fixes were also exercised through isolated startup/storage/logging tests.

Evidence: `verification.json`, `input-snapshot.json`, `source-snapshot.json`, `before-regression.xml`, `race-before.log`, `final/regression.xml`, `extra-edge-cases.xml`, `final-notification-binding.xml`, `startup-storage-logging.xml`, `catalog-audit.json`, `bandit.json`, `static-triage.json`, `deployed-before.json`, `deployed-after-source.json`, `initialization-fixed.png`.

CI action provenance: [official checkout](https://github.com/actions/checkout), [official setup-python](https://github.com/actions/setup-python). Commit pins were resolved against their official repository tag refs; no external action source was copied into the application.
