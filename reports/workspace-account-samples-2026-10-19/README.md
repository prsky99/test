# Customer workflow samples — completed

**Ten private workflow samples were saved through Chrome in the Google-owned customer workspace. All ten real runs succeeded: 64 steps, including two ten-step chains.** The user-operated server restart and explicit read-only connection approval were received before the administrator actions. No further server restart is required for this completed checkpoint.

## Actual connection and execution

The administrator UI approved the current Paper Finder resource 34807, `search_papers`, for `docs.search.v1`. Its genuine public research test passed with the current reviewed adapter dataset. No synthetic approval, agent, contract evidence or customer workflow was inserted into the operating database through shell commands. Customer saves, whole-graph reviews, one-use execution consent and every actual workflow submission used the browser UI.

See [current contract evidence](live/current-contract-evidence.json) and [contract success screenshot](live/paper-contract-passed.jpg). The earlier [bounded public probe](live/paper-probe.json) is separate evidence and was not substituted for the actual administrator test.

## Retained samples

- **Sample 01 - Daily Technology Research** — 2 steps; succeeded; 6.781 seconds of retained runtime.
- **Sample 02 - Stock Market Research Context** — 3 steps; succeeded; 10.600 seconds of retained runtime.
- **Sample 03 - Security Advisory Research** — 4 steps; succeeded; 19.775 seconds of retained runtime.
- **Sample 04 - API Integration Research** — 5 steps; succeeded; 18.179 seconds of retained runtime.
- **Sample 05 - Competitive Product Research** — 6 steps; succeeded; 32.087 seconds of retained runtime.
- **Sample 06 - Ecommerce Operations Research** — 7 steps; succeeded; 29.110 seconds of retained runtime.
- **Sample 07 - Sustainability Research** — 8 steps; succeeded; 30.744 seconds of retained runtime.
- **Sample 08 - Learning Resource Research** — 9 steps; succeeded; 36.202 seconds of retained runtime.
- **Sample 09 - Product Launch Research** — 10 steps; succeeded; 56.251 seconds of retained runtime.
- **Sample 10 - Customer Support Research** — 10 steps; succeeded; 56.363 seconds of retained runtime.

Each workflow has exactly one retained run. All 64 persisted step input hashes match the exact literal input or public title projected from the prior UI-observed result. This is a read-only comparison against the dedicated typed journal; it does not decrypt private output or write the operating database. The graphs contain 54 prior-result connections.

The final sample requests two initial results, then sends the second title as the next query. Its next step returns one different result. This confirms input projection and a changed output, rather than inferring lineage only from a success label. A title search is not guaranteed to return the exact same paper and is not an independent factual-quality assessment. Fresh run consent is consumed and the run button returns to disabled after execution.

See [UI observations](live/account-ui-results.json), [saved workflow list](live/account-saved-workflows.json), [read-only lineage audit](live/account-lineage-audit.json), [audit script](audit_account_lineage.py), and [visible chained output](live/account-chained-output.jpg).

## Code and security boundaries

The reviewed `paper-docs-v1` adapter pins the exact native schema/annotations and implementation hash, requires ordinary current approval and real adapter-contract evidence, translates logical query/language/limit into native query/limit, and rejects native queries over 200 characters without truncation. Normalized output retains actual paper metadata and the provider observation time; it invents no abstract, freshness, source or quality grade. Partial-source notes remain partial.

Typed execution, exact input review, current evidence reads and the SQL catalog recognize the pinned adapter. Rejected output stops downstream calls and invalidates current contract readiness. Existing SSRF/TLS/schema/authority/no-spend controls and unknown-outcome replay barriers remain enforced. See [adapter design](../../docs/CAPABILITY_ADAPTERS.md).

## Verification

- **174 distinct relevant regression cases passed**, zero failures/errors/skips: 141 integrated API/Chromium cases in [final-regression.xml](final-regression.xml), plus 33 SQL boundary/catalog cases, including the disposable native PostgreSQL rehearsal, in [sql-boundaries.xml](sql-boundaries.xml). These automated tests use isolated data, separate from the ten actual account runs.
- Coverage includes ten-step chaining, output escaping, cross-scope/consent boundaries, changed implementation/schema/annotations, missing approval, old generic evidence, stale/future/inconsistent timestamps, mismatched query/count, unsafe source URLs and native length restrictions.
- Public content: **92 files, zero violations**. Critical Ruff: zero findings. Scoped Bandit: zero findings across the five changed backend modules — [bandit.json](bandit.json).
- Final SQL drift check: 3,472 statements / 223 tables. The semantic SQL change adds `dataset_version` to the contract-evidence read; table schemas are unchanged.
- The verified source checkpoint remains unchanged — [source.json](source.json). New adapter and ten-workflow modules are included in the required frontend regression selection.

## Scope and operating limits

**One genuine paper-index agent is reused across the graphs. This is not a test of ten distinct external providers.** The samples are research workflows, not live stock news feeds, generated summaries or autonomous marketing. Query limits, source availability/partial responses, the shared 60-second deadline and per-node bounds remain enforced. The longest observed successful run was 56.363 seconds; that observation is not a latency guarantee.

The shared administrator observation panel temporarily showed one lost record/write error during setup. This report does not claim complete platform-wide observation or a zero-error operating server; the dedicated retained run/step journal supplies the independently checked 64-step evidence above.

After a browser reload, the saved list still contained all ten samples; reopening the last sample restored its ten-step graph, successful retained history and ten result sections. Run consent was cleared and the execution button stayed disabled. See [reload verification](live/account-after-reload.json) and [saved sample screenshot](live/account-saved-ten-workflows.jpg).

All ten requested samples remain saved for customer review. The public Workspace link stays hidden. No release, deployment credential, delivery destination, marketing permission or payment was created. The user server was not restarted by this task. Machine-readable completion: [verification.json](verification.json).
