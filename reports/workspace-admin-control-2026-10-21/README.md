# Workspace administration — implementation and verification

Date: 2026-10-21 · WAC-1.0 · source and isolated acceptance complete; user restart and operating read-only smoke verified.

## Delivered

- **Integrated administrator menu:** overview/ingestion health, customers/access, organizations/workflows, AI/business events, credit reconciliation, support cases, reviewed commands, incidents and audit. Existing specialist menus remain connected rather than replaced with a second credit ledger.
- **Individual staff boundary:** configured machine credentials are not workspace sessions. Operators retain a read-only ceiling and cannot read case bodies. Support mutations require admin/superadmin; approval and private disclosure inspection require current superadmin authority. Private prompt/output content is excluded from ordinary read models.
- **Transactional events:** existing auth, organization/draft/runtime audit, signed credits, generation and execution completion paths emit bounded metadata after explicit migration. Required business events share the business transaction. The signed outbox, fenced projection, unique source keys, cursors and completeness state support restart and replay without duplicate effects. The common best-effort journal remains separate from financial evidence.
- **AI/workflow monitoring:** generation request/confirmed completion/unknown, authenticated provider category, observed duration, authoritative single/typed runs, node states, releases/deployments and common observation links where available. Unobserved cache hits and recipient download completion are not invented. Download marking records the saved revision's entitlement, not a verified client receipt.
- **Credit controls:** signed source reconciliation, request/review/approval, exactly-once adjustment through the existing credit core, current revision, reason, signature and audit. Restore-review balances cannot be cleared through ordinary edits. Pending commands expire after 24 hours and can be cancelled. Session revocation and account restriction are explicit single-customer commands. Self-review needs a separate acknowledgment and a login within ten minutes, and is labelled in audit.
- **Support:** English Pearl/Lucide customer inbox at `/customer/support`, assignment/priority, internal notes versus visible replies, reopening and workflow/credit context. Existing inquiry/privacy/cancellation requests can be linked after explicit relationship verification; original request states and advertising/notification permissions do not change.
- **Scoped sharing:** an organization owner can share one current draft revision for 15 minutes and withdraw access. Maximum API duration is one hour. Inspection checks current link, expiry, object revision, binding and superadmin authority; no administrator membership is inserted.
- **Privacy/recovery:** session changes clear admin dialogs; refused customer access clears inbox content. Restored pending commands/outbox and disclosures are quarantined. General events expire after 30 days, anonymous auth events after seven days, and closed case messages after 90 days. Deleted-account feature data is pruned after 90 days and is not rediscovered by backfill. Maintenance requires the host worker to run.
- **Commerce remains coming soon:** no paid subscription, automatic billing, top-up, real payment or advertising send is activated. Customer credits, TEST_UNIT, sandbox payments and provider settlement remain separate. No automatic refunds or blind provider retries are introduced.

## Operating migration and seed

The additive PostgreSQL migration is applied (`operating-migration.log`). It creates only the new `workspace_admin_*` namespace and indexes. Existing customer, balance, ledger, agreement, membership, execution authority, provider configuration and public Workspace exposure settings were not rewritten.

`operating-seed.json` records **265 retained source rows projected**, zero quarantined outbox rows, caught-up retained-source cursors and an empty outbox at capture time. These are historical records, not 265 new customer actions or reconstructed past logins. Independent read-only validation found **28 signed credit/organization records with zero invalid signatures/fields** and **237 unsigned legacy runtime audit rows** (`operating-source-integrity.json`). New projection signatures do not retroactively authenticate those unsigned original records.

The existing overview remains readable after migration (`operating-before-restart.json`). The server was not stopped/restarted, and no real-customer mutation journey was performed. New Python routes and the script nonce allowlist still require the user's terminal restart. The root-key file keeps its legacy filename; these operations use PostgreSQL and do not open the retired SQLite database.

## Verification

- **323 unique test cases passed**, zero unresolved failures or skips in the effective result set. Final integration has 301 passing cases; newer focused evidence supersedes affected cases and adds coverage. `verification-summary.json` deduplicates overlapping runs.
- **37 focused feature/lifecycle cases** cover atomic rollback, concurrent approval, restore blocks, signed source/projection tampering, key namespaces, anonymous auth failures, exact replay, request bounds, CSRF, cross-origin denial, customer IDOR, session revocation, disclosures and retention.
- **Four real Chromium journeys:** reviewed credit correction; safe customer messages/internal-note exclusion; full admin login/navigation/CSP, popup refresh and session clearing; explicit draft sharing/withdrawal and inbox removal after logout. Screenshots are included.
- **Native Unix PostgreSQL:** ten acceptance checks and sixteen authenticated GET routes pass in a disposable cluster. Concurrent approval has one effect; source links preserve original requests; restoration blocks pending replay.
- **1,001 synthetic customer rows, ten list samples:** actual timings are in `native-postgres.json`. This measures local metadata list queries, not operating concurrency, a production SLA or large-catalog throughput.
- **238 public frontend files, zero content violations.** New customer copy is English with private-page metadata, the existing theme and local icons. Public main embedded frontend HTML was not changed.
- New production modules/CLI pass Ruff F/E9 and the selected Ruff security scan has **zero findings**. Rendered customer scripts and administrator scripts pass Node syntax checks. No dependency was installed.

Initial helper assumptions and intermediate browser/SQL issues were fixed. Earlier XML/logs remain historical evidence; only the final files identified by `verification-summary.json` determine effective acceptance. Tests use synthetic identities and controlled model/provider data, not actual Google/GitHub customer account changes or live commerce. Secure-coding and scoped dynamic regressions are not a full independent penetration test, legal certification or proof that every possible vulnerability is excluded.

Parallel frontend work changed `TypedFlows._may_disable/disable` during closeout. A comparison with the earlier compiled functions confirmed that the integration recording hooks were unchanged, and the affected disable regression passed (`concurrent-change-recheck.xml`). It supersedes the earlier result for that same test and does not increase the unique count. The final 22-file fingerprint was stable after this check.

## Acceptance and maintenance

The user restarted the existing server at 13:20:02 KST. Twelve local HTTP checks passed: existing overview (200; cold 3.582s / warm 0.005s), admin page and new script (200), current script nonce/CSP agreement, individual-staff-only WAC API rejection for machine/anonymous access (401), cross-origin denial (403), support page (200), and unauthenticated customer API denial (401). All checked responses use no-store.

Read-only operating PostgreSQL verification confirms the correct migration/key binding, an empty projection outbox, a watermark age of 0.994s, all three retained-history sources caught up, and zero source-integrity review flags. No customer, credit, consent or support record was modified by these probes.

The operating individual-staff browser session was not exercised; authenticated navigation and reviewed mutations were verified in isolated Chromium/PostgreSQL acceptance. Open **워크스페이스 통합관리** using a current individual staff login for operator review. Machine access remains deliberately denied. Actual customer writes retain their normal approval requirements.

No traceback appeared after restart during this check. An existing external capability collector continues to log `ApplicationStoreError('invalid_parameters')` (28 occurrences in the observed restart window); this is outside the WAC change and is not evidence of healthy external collection. No WAC worker error was observed. See `operating-restart-smoke.json` for measured evidence.

`python -m scripts.workspace_admin_control --help` describes explicit `migrate`, `status`, `backfill`, `project`, `prune` and `quarantine` operations using private DSN/root-key files. It never launches a server or discovers arbitrary credentials. Key derivation matches the actual runtime namespace; an existing migration with a different binding is refused. There is no automatic restoration of credit or execution authority.

Primary evidence: `final-integration.xml`, `feature-final.xml`, `browser.xml`, `native-postgres.json`, `public-content.log`, `security-static.json`, `source-hashes.json`, `operating-migration.log`, `operating-seed.json` and `operating-source-integrity.json`.

## Restart source recheck

Two concurrently edited authoring/typed-flow modules differed from the prior closeout fingerprint. All **79 affected cases passed**, without failures or skips (`restart-affected-source.xml`), including model proposal, typed authoring/execution and enabled administration lifecycle recording. `restart-source-hashes.json` records the 22-file current implementation fingerprint. These results supersede overlapping earlier cases; the effective unique total is 323. No implementation file was modified during restart verification.
