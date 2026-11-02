# Customer organization completion verification

The N02 source implements customer-owned organizations, accepted exact-identity
invitations, owner/editor/viewer/runner authority, last-owner protection,
accepted-owner transfer, leave/archive, private draft editing/snapshots and
confirmed local account withdrawal. Customer identities never become staff.
The public portal is still disabled by the host's default feature gate.

- Final isolated bundle: **88 passed**, 0 failures/errors/skips, 17.63 seconds.
- Native Chromium uses offline reserved `customer.test` and isolated ASGI; Google
  and GitHub exchange/signature fixtures are synthetic. No operating database,
  server operation, live customer/provider identity or marketing delivery.
- Content policy: 74 files, 0 violations, including the new English page source.
- Static check: five Python modules, 0 High, 1 Medium, 3 Low, 0 scan errors. The
  Medium B608 is a static HTML/JavaScript page string with generated CSP nonce
  replacement, never a SQL statement. The three Low B105 results are fixed OAuth
  URL/protocol markers. Raw findings are preserved in `static.json`.
- The final native screenshots were inspected for responsive layout, native
  confirmation dialogs, text-node XSS handling and absence of horizontal mobile
  overflow. Two repeated capture cases are not added to the unique count.

See `verification.json` for exact source hashes, scope, evidence and remaining
limits, and `regression.xml` for the final bundle. `browser-final.xml` is an
additional two-case capture run of repeated cases; the final bundle also covers
those cases. Its earlier timestamp is not substituted for the latest full bundle.

Account withdrawal immediately revokes local authority and preserves signed
unknown execution evidence without retry. It retains a keyed subject tombstone,
signed audit/safety records and existing backups; it does not assert physical
backup/global erasure. Actual Google/GitHub registration and acceptance,
independent lost-identity recovery and storage/legal retention remain operating
requirements. The batch neither opens the customer portal nor changes staff
login.
