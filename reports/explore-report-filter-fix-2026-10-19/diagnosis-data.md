# Explore report filter: read-only data diagnosis

Observed on 2026-10-19 at 13:09–13:12 KST. This audit used SQLite URI `mode=ro`, `PRAGMA query_only=ON`, explicit read transactions and bounded queries. It did not instantiate the application store, start an app, modify either database, call provider endpoints, or run report scripts. Active catalog growth means the separate audit snapshots contain slightly different resource totals.

## Why the current filter returns zero

The active collector database has 1,172 reports. Every report URL is the managed gateway URL for its stored kind and local resource ID. All 1,172 lack a connection version, execution start, execution finish and evidence scope. No report URL canonically equals its linked resource's direct full endpoint. The actual Python `report_subject_matches` check therefore accepts **0** and rejects **1,172**. Hiding these unbound gateway records preserves the current evidence boundary.

Every stored resource ID exists, but only 969 have the same kind. Only 486 match the linked resource's kind and normalized name; these refer to 475 subjects, of which 468 currently satisfy the public live-resource condition. A matching local ID, kind and name does not identify the historical endpoint or version, so these 486 records must not be re-exposed on that basis alone.

Report protocol distribution is A2A 213, MCP 267 and x402 692. Dates mix numeric timestamps with ISO text; after normalization to KST, 126 were created today and 1,046 earlier. The daily counts are October 15: 161; October 16: 102; October 17: 381; October 18: 402; October 19: 126. These are record creation dates, not proven execution times.

## Narrow recovery evidence

The active catalog was streamed once using only resource ID, kind, name, full URL and stable key. Report names had 799 single-candidate, 98 multiple-candidate and 275 zero-candidate cases within the same protocol. None of the stored report URLs provided a matching direct endpoint.

Report bodies were read individually in memory, with a 128 KiB per-row limit. Wire columns were not loaded, and neither body text nor extracted URLs were saved or printed. Twelve A2A reports contain a full canonical endpoint matching exactly one current resource with the same normalized name and kind. Eleven require a different local resource ID; one retains its ID. All twelve subjects currently satisfy the live-resource condition. These are manual review candidates; a URL mention alone does not prove a measured execution.

The older gateway database contains 1,172 reports and 64,213 resources. All report slugs are nonempty and unique in both databases. All 1,172 old reports correspond uniquely to a current report by slug plus identical title, kind and normalized report name. Its report metadata also uses gateway URLs and has no connection-version column. Of its linked resource records, 1,025 exist, 147 are missing, and 427 match the report's kind and normalized name. The exact-name count is 426.

For the 427 matching old resources, the audit required a valid direct full endpoint, the same unique stable key in the current catalog, unchanged kind, normalized name and full canonical endpoint, and exactly one current resource for that full endpoint/name/kind subject. Two stable keys are absent and two refer to a changed subject, so they were excluded. **423 reports across 422 subjects pass these provenance checks**: x402 235, A2A 86 and MCP 102. Of these, 416 reports across 415 subjects currently satisfy the live-resource condition. Fourteen retain the current linked ID; 409 require a different ID.

The twelve body candidates and 423 cross-database candidates have no report IDs in common and no conflicting report associations. Their union is **435 reports across 433 subjects**; 428 reports across 426 subjects currently satisfy the live-resource condition. Numeric candidate IDs are stored separately without names, URLs or keys.

## Safe interpretation and limits

- Preserve the full endpoint, normalized name, protocol, stable-key and uniqueness checks during any proposed repair. Exclude absent keys, changed subjects and ambiguity.
- A repair based on old catalog linkage restores historical subject provenance. It does not manufacture the missing connection version, execution timestamps, measured evidence or a successful current verification. Do not label these records as newly verified.
- Keep unmatched reports hidden. A gateway URL and local ID/name match cannot resolve endpoint identity.
- Review a proposed repair in an isolated database and keep an explicit, reversible mapping before any separately authorized operational change. This audit made no operational changes.
- The older database's local link is supporting provenance; the report metadata itself no longer contains a direct endpoint. Body endpoint mentions also need review for whether they describe the actual subject. Neither evidence source proves execution.
- Only aggregate metrics and public numeric IDs were retained. No report content, wire payload, subject name, full URL, stable key, credential or personal data was saved or printed.

Machine-readable aggregates are in `diagnosis-data.json` and `cross-db-data.json`. The numeric review mappings are `candidate-ids.json` and `cross-db-candidate-ids.json`.
