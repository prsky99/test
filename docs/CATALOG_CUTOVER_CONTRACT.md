# Controlled catalog integration and cutover requirements

2026-10-18 · design and acceptance gates, not an operating migration tool.

The completed explicit registry/observation writers and fenced lexical index do
not intercept existing direct Store writes. A runtime switch or automatic dual
write would not establish complete ownership. Use the following sequence for a
concrete reviewed source and target before any operating integration.

1. Inventory and exclude all source writers or establish a durable, complete
   source journal boundary. Include registry pages, health, auth, survey/tool
   schemas, usage/trial, evaluations, current eligibility, schedules and direct
   admin SQL. Unsupported domains must block cutover, not disappear from counts.
2. Capture a consistent read-only source snapshot with schema/version/identity,
   supported field coverage and explicit completeness. The bounded capture pilot
   is not a full-catalog exporter. Preserve old IDs/keys/first-seen and immutable
   histories; use a separate prospective profile mapping for intentionally changed
   normalization. Refused/truncated/unknown source values need explicit treatment.
   Do not recompute a legacy hash and label it its original recorded value.
3. Import into a new owned disposable target first. Preserve stable identities
   and references; derive new private revisions and explicit index work only for
   supported mapped data. Existing successful evidence, approvals, destination
   verification, delivery/automation grants, deployment tokens, sessions and
   revocations must not gain new authority from copied data or a changed backend.
   Current eligibility should fail closed until validated by its proper owner.
4. Rebuild the declared model/corpus index under current revision/job fencing.
   Distinguish portable lexical membership from legacy FTS/BM25/vector/hybrid and
   public recommendation ranking. Reconcile identity, registry/observation values,
   owner high-water marks, counts, invalidation, immutable reference relationships,
   removed terms and unknown outcomes, with aggregate reports and explicit limits.
5. Verify pending source changes or a quiescent boundary, then run actual isolated
   ownership/race/failure/commit-uncertainty, restart, privacy/security, API/browser,
   load and restore rehearsals. Partial/empty reports, fixture counts or matching
   rows alone cannot approve a whole Store migration or operating readiness.
6. Prepare a concrete operator cutover record: source/target ownership, final
   verified boundary, excluded writers, supported subsystem list, app/backend
   compatibility, maintenance window, independent approvals and rollback point.
   Do not activate through an inherited DSN, implicit environment fallback or
   unreviewed write alias.
7. Rollback must fence target writers/workers first and reconcile any committed
   target observations, external effects and unknown outcomes. It must preserve
   revocation tombstones and quarantine authority, rather than restore stale
   cache success, original endpoint exposure or old grants from an earlier copy.
   Avoid replaying dispatched operations or materializing stale index artifacts.

Current source implementation does not perform this sequence against an operating
database. Public/auth/privacy/workflow/ledger and representative DR/HA remain
separate. v1.29 delivers the named [owned-copy subset rehearsal](CATALOG_COPY_CONTRACT.md).
All other domains remain visibly unsupported and require reviewed mapping and
operating integration before an operating target is considered.

[Observation/capture contract](CATALOG_OBSERVATION_CONTRACT.md) ·
[original legacy contract](CATALOG_WRITE_MIGRATION_CONTRACT.md) ·
[remaining work](REMAINING_WORK_BATCHES.md).
