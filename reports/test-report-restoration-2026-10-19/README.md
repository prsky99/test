# Historical test report restoration

The user authorized repairing the connections of the 739 previously pruned reports and restoring valid historical reports.

435 reports were restored: A2A 52, MCP 114, x402 269. Three restored documents were newer than an existing report for the same canonical provider and replaced the older document. The net addition is 432 subjects, taking the operational total from 422 to 854. The other 419 existing documents remain unchanged.

39 original documents were excluded as older duplicates. 265 remain in the original private backup: 249 have no independently established original endpoint, 13 original endpoints have no current catalog match, and three endpoints have ambiguous current catalog subjects. No arbitrary same-name, local-number, shared-host or protocol reassignment was used.

Identity provenance comes from direct endpoint metadata in an older database, statically read original authoring dictionaries, or an explicit subject endpoint field in retained report text with an unchanged subject name. Complete endpoint identity includes its path and query. Source scripts were not executed.

The restored records retain original dates, grades and outcomes. They have `evidence_scope=legacy`, no fabricated execution timestamps or connection version, and no new execution evidence. A restoration notice identifies historical evidence. Retired numerical gateway URLs were replaced with a non-clickable historical marker in affected stored text; the original documents remain in private backups. Current connection metadata binds each report to its proven current provider endpoint. No provider was called or re-tested.

The operation held a write transaction, revalidated the entire plan, checked the retired-writer fence, saved a durable 0600 backup in a 0700 directory, preserved report identity/creation triggers and used canonical subject reservations. Replacements keep reservations consistent. The original pruning backup was not changed. No application restart was needed or performed.

## Evidence

- `application.json`: operational result.
- `verification.json`: exact row comparisons, 854 valid report subjects, original execution boundaries, unchanged existing documents and guards.
- `postflight.json`: a repeat preflight proposes zero additional restorations.
- `resolution-manifest.json`: all 739 original report IDs classified, without report contents or credentials.
- `rehearsal.json`: the same operation on isolated relevant real-data tables, including a repeated-run check.
- `regressions.xml`: 160 passing recovery, duplicate, identity, evidence, admin read and session/browser security tests using isolated apps and data.
- `live-api-verification.json`: origin and public Explore both returned HTTP 200, 854 agents and 854 matched reports, with no estimated count or candidate-window limit.
- `secure-coding-review.json`: targeted manual/AST review. Bandit was unavailable; no Bandit pass is asserted. The public content checker reported zero violations across 92 files.

Current availability and successful execution were not established by this historical restoration. The 265 unresolved records require independent original subject evidence or catalog reconciliation before they can safely become public reports.
