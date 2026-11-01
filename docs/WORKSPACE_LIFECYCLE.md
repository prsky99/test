# Private workspace execution lifecycle

`workspace-private-lifecycle-v1` adds owner-controlled retention and review without replaying work or resurrecting authority. All operations require a current individual staff session and explicit, current workspace owner membership. Global administrator status alone does not confer content access.

The preview reports aggregate expired-unused tickets, old terminal outputs and retained unknown runs. One explicit maintenance operation processes at most50 unused expired tickets and50 old terminal outputs. Ticket removal first creates a signed tombstone binding the original ticket hash, workspace and expiration. Tickets with an accepted run are retained for exact replay certainty. The executor's pending-ticket quota counts active unused unexpired tickets; retaining used proof therefore does not permanently exhaust that quota. Separate pending/active-run and daily admission bounds still apply.

Terminal `succeeded`, `failed` and `denied` outputs older than seven days may be archived. A signed archive receipt preserves the output hash, original signed payload hash and terminal status; the retained run is updated atomically with an archived-output marker. Run/ticket metadata and idempotency remain. Unknown runs are never removed or automatically retried. This is incremental logical retention, not a claim that database files shrink or that all metadata has a finite lifetime. Physical compaction and operating retention require their separate maintenance controls.

Current owners may append bounded, revision-checked reconciliation notes to retained runs. A note records who reviewed the record, without changing execution certainty, claiming receipt at an external destination or triggering another send. An unknown outcome remains unknown. The UI can record notes for unknown records; only successful tests are eligible for a new executable release.

Restore review requires an already current active owner, a fresh session and the current signed snapshot/workspace/member revisions. It records explicit review and requires new grants. It never activates an old workspace membership, release, deployment, schedule or execution. An inactive historical backup-owner row is insufficient proof of current ownership. Establishing the current owner of an inactive restored namespace requires the independent recovery/provisioning process; this module deliberately refuses to infer that authority from old backup rows.

Disaster recovery consumes pending owner-review proposals, pauses memberships/customer links and revokes or blocks old sessions, tickets, app codes, app tokens and release/deployment authority. Signed replay metadata is retained. A later login or workspace activation must not revive old grants. This module creates no automatic background cleanup, no provider/model calls and no notifications or marketing deliveries.

The isolated regression scope includes signed ticket tombstones, atomic rollback when later archival fails, actual unknown-run retention, append-only note CAS, and refusal to derive restore authority from inactive memberships. The final completion report is authoritative for test counts, frozen sources and remaining operating limits.

Optional versioned signing, previous-key verification windows, revocation and
AES-256-GCM retained-output/backup encryption are documented in
[Private artifact keys](PRIVATE_ARTIFACT_KEYS.md). The archive hashes the original
persisted signed payload, including its ciphertext when present, then removes
the current encrypted envelope together with the output. Key rotation or a
current-owner review never activates old grants or proves ownership from a backup.
