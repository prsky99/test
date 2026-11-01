# Owned-copy migration rehearsal — delivered named subset

2026-10-18 · v1.29 isolated subset verified; no operating import/backend switch.

[Delivered contract](CATALOG_COPY_CONTRACT.md) ·
[verification](../reports/advancement-catalog-copy-2026-10-18/README.md).

Reuse completed adapter, registry/observation ownership, fenced lexical artifacts
and read-only capture. Do not build another generic writer or queue.

1. Define an exact supported synthetic legacy schema/field-to-profile mapping and
   rejection manifest. Preserve stable IDs/keys/first-seen, distinguish old stored
   hashes from proposed strict hashes, and retain unknown/NULL distinctions.
   Unsupported auth/trial/history/authority/FTS/vector fields must be counted and
   gate completeness; no silent adoption or invented success.
2. Implement a fixed disposable owned-source/new-target rehearsal, with no CLI
   operating paths/DSN. Import only the declared bounded subset, preserve ID and
   reference integrity, initialize prospective revisions/owner clocks explicitly,
   and build actual fenced lexical artifacts. Keep eligibility/authority closed.
3. Exercise source quiescence/journal assumptions explicitly, compare two consistent
   captures plus private owner clocks, verify counts/content/invalidation/removed
   terms, and record incomplete/unsupported states as first-class outcomes.
4. Verify failure midway, target rollback/reopen, replay identity, writer exclusion,
   stale observation/materializer behavior and restoration without authority
   resurrection. Run actual SQLite/PostgreSQL contracts and affected security/API/
   browser/TLS regressions after one source freeze.
5. Update design and remaining work together. The result is an isolated migration
   rehearsal for a named supported subset, not whole-Store coverage or permission
   to connect production. Actual source/target/maintenance window, legacy writer
   integration, full search/auth/privacy/workflow/ledger, load/DR/HA and operator
   cutover/rollback acceptance remain explicit gates.

[Integration gates](CATALOG_CUTOVER_CONTRACT.md) ·
[delivered ownership/capture](CATALOG_OBSERVATION_CONTRACT.md) ·
[platform design](PLATFORM_ADVANCEMENT_DESIGN.md).

Next: [current collector generation guards](LEGACY_OBSERVATION_GUARDS_PLAN.md).
