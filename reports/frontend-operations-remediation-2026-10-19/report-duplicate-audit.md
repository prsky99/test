# Read-only report repetition audit

The 1,172 report rows reference 1,113 resource IDs. The difference of 59 is repeated resource references, not an established count of duplicated executions. There are 56 repeated-ID groups: 53 pairs and three triples, containing 115 rows.

None of the 1,172 records has `executed_at`, `execution_finished_at`, or `connection_version_id`. The scope is `legacy` for 423 rows and unset for 749. The database therefore cannot establish whether any two authored reports represent the same actual execution, or different actual executions.

Within every repeated-ID group, title, slug, publication time, test method, request, response, summary, content, and latency contain differences. No extra row has an identical full-content fingerprint after excluding title/slug/publication, or an identical combined method/request/response/outcome fingerprint. These comparisons show distinct stored documents; they do not prove that the claimed requests were dispatched.

The repeated groups contain:

- 40 groups with the same name/protocol but a mixture of numeric gateway and direct endpoint references.
- Seven same-name/protocol groups containing gateway references only.
- Eight groups with different names and a mixture of gateway/direct references.
- One same-name/protocol pair containing direct references only.

Only the final pair has two reports that both pass the current canonical subject check. The other groups contain either one trusted report (45 pairs and three triples), or none (seven pairs). Eleven extra rows share an identical stored protocol/name/endpoint tuple, but their contents differ and they still lack execution linkage. A direct URL and a numeric gateway URL are different stored tuples; this is not proof that they describe different providers.

Static-source comparison independently found 611 current slugs in historical seed/batch literals. All 611 methods and summaries match their static definitions. For 128 reports, both literal wire fields were available: all 128 response payloads and 120 combined request/response pairs match after JSON normalization. This establishes correspondence to authored source definitions, not a verified execution history. The audit parsed source and read database snapshots; it did not execute seed scripts.

The inspected creation boundary accepted a fresh row for each new slug. `Store.create_test_report` validated subject identity and measured evidence but had no content/execution idempotency key. The administrator POST called that method directly. Thus a retry with another slug could save the same authored content or measured evidence again. Conversely, the slug-less default used whole seconds, so unrelated submissions in the same second could collide. A slug conflict was not handled by the route's `ValueError`/`KeyError` handler. The parent task owns the subsequent Store/API correction; this note describes the boundary observed before that correction.

Deduplication should use recorded execution/evidence identity for measured reports and a canonical subject plus normalized document payload for historical imports. It should preserve independent, truthful historical records and must not delete reports merely because their resource IDs repeat. No production row, schema, process, or provider was changed by this audit.

Aggregate evidence is saved in `report-duplicate-audit.json` and `report-static-source-audit.json`. Neither contains report text, raw wire payloads, visitor data, credentials, or private connection targets.
