# Focused secure-coding and independent integration review

This review supplements the wider twelve-file Bandit report; it does not replace a full repository audit. The focused scanner ran from the isolated temporary tooling environment against `legacy_vector_index.py`, `observability.py`, `concierge/report_evidence.py`, and `scripts/import_test_reports.py`. There is no `safe_report_import.py` in this checkout; the reviewed import entrypoint is `import_test_reports.py`.

`bandit-queue-report-focused.json` records **six medium-severity B608 findings**, four low-confidence and two medium-confidence, with no scanner errors. No finding was suppressed and this is not a zero-findings claim.

## B608 manual triage

- `legacy_vector_index.py:251`: `_enqueue_body` interpolates a trigger column expression. Both callsites pass the fixed literal `NEW.resource_id`; the helper receives no request value.
- `legacy_vector_index.py:296`: generated trigger predicates and column names come from source constants and the immutable observation-field allowlist. Schema inspection selects only names already in that allowlist; it does not insert arbitrary discovered identifiers.
- `legacy_vector_index.py:491`: the selection SQL uses a fixed eligibility predicate and fixed selection body. Its only variable query shape is a bounded count of `?` placeholders. IDs, descriptor digests, and limits remain bound values.
- `legacy_vector_index.py:534` and `:545`: the new queue cleanup/claim SQL concatenates only a source-owned `clause` containing zero to fifty `?` placeholders. `_request` requires distinct positive integer IDs and a bounded integer limit. IDs, timestamps, and limits are passed separately as parameters. The query text contains no HTTP input, resource prose, endpoint URL, or caller-selected SQL identifier.
- `concierge/report_evidence.py:60`: trigger name and event text come from a fixed two-element local tuple. The helper accepts only a database handle; callers cannot supply trigger text, event names, or identifiers.

These six call paths do not expose an untrusted SQL interpolation route under the reviewed application boundaries. That conclusion depends on retaining the fixed allowlists and parameter binding; future callers must not pass external strings into the trigger builders or the build-time constant environment. Bandit reported no findings for the focused observability writer or canonical import CLI.

## Independent report and frontend integration review

The report path requires a matching resource ID, protocol, full endpoint, and supplied subject name. Managed gateway URLs additionally require subject name plus a matching current connection-version identifier; database-local ID paths alone are insufficient. Full endpoint comparison retains path and query distinctions and does not broaden to shared origins or resolve DNS.

Current measured status requires execution scope, finite ordered actual timestamps, the current connection version, and matching registry execution evidence. Publication time is separate. The ranking/public projection path checks latest, unexpired evidence, so a newer failed or unknown execution prevents an older report from becoming current verification. Resource/schema changes invalidate eligibility through the existing observation-generation triggers. Original historical report rows are retained; mismatched rows are withheld from public subject projection rather than rewritten or reassigned.

The canonical import CLI opens its dry-run destination with SQLite `mode=ro` and `query_only`, resolves a stable `subject_key` against each selected destination, checks name/protocol/endpoint, and refuses imported execution assertions. Writes require explicit `--apply`. The seven numeric-ID seed entrypoints now stop before constructing a Store. During this work, no such command was applied to an operating database.

Review found and escalated three integration issues: a history-only report badge's default A grade, cached report-filter totals after report removal, and a healthy-only Verified filter. The owning agents corrected those paths. Review also found that new named/f-string card predicates broke the existing PostgreSQL registry builder and left frontend SQL unregistered. That compatibility issue was repaired with bounded source-constant extraction, reviewed finite query regeneration, and registration/unknown-SQL tests.

## PostgreSQL compatibility limits

The SQL registry builder evaluates only bounded literal containers and already-reviewed names; f-strings permit a bare known string name with no conversion, formatting, attribute access, or function call. Unknown expressions are rejected. It does not evaluate Python code supplied by a request, expand the runtime SQL boundary, open a live database, or read deployment credentials. The generated catalog contains 3,088 approved statements for 199 tables at this review point; its check completed without a source difference.

New public summary queries use explicit native epoch and `LEAST`/`TRUNC` projections so PostgreSQL does not round an hourly bucket where SQLite truncates it. Fixed report-helper/card queries are registered; arbitrary runtime SQL remains rejected. Focused extraction, registration, and application boundary tests passed **39 tests**; the actual native PostgreSQL rehearsal was excluded from that command because its runtime driver is unavailable in this environment. No native cluster or production cutover was attempted.

The final focused report-binding, SQL-registry/readiness, and full operational-observability run passed **54 tests with no exclusions**. The native readiness unit specifically verifies that `execution_finished_at` exists as nullable `double precision` in expected report metadata and that an older schema without that column is rejected with `schema_profile_mismatch` using read-only introspection. Fresh native schema DDL includes the column; an existing native database is not silently upgraded. The final catalog check reported no source difference after the subject-before-LIMIT report-detail query was registered.

Raw-writer report identity triggers are **SQLite-only**. This work preserves native PostgreSQL startup and its strict application create-report validation, but does not claim equivalent protection for someone writing raw report rows directly to a PostgreSQL database. No unverified native trigger or migration was added. Native PostgreSQL execution still requires a dedicated rehearsal before deployment.

The formerly failing operational notification test passed after its fixture was updated to record actual registry execution evidence. Its authorization and destination/evidence checks were not relaxed. Earlier selective test results were transitional; the final integrated suite should include that test.

One non-authorizing listing limit remains: Explore examines bounded SQL candidates before final Python subject/version revalidation. Its total adjustment accounts for rejected visible items; a large number of stale managed-gateway report subjects outside that candidate window can still leave an approximate count or hide a later valid result. Cards continue to fail closed and do not promote stale evidence. This limit was reported to the owning agent and coordinator; it is distinct from the corrected single-item cache/count case.


## Parent final scan scope

The final parent scan covers fifteen selected Python files, including the bounded SQL-catalog builder and import CLI, and records High 0 / Medium 83 / Low 47 in `bandit-final.json`. It scans whole existing files rather than only this task’s changed lines. These findings are retained, not suppressed; the focused six-finding triage above is a narrower reviewed subset, not a claim that all remaining findings were resolved.
