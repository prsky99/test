# Explicit PostgreSQL archive source slice

The general caller-owned archive/provider/restore gate and the existing private
worker/archive regression selection passed **53 pytest cases**, zero failures,
errors or skips. This is the focused component run recorded in
[regressions.xml](regressions.xml); it is not added to the final affected suite.

Actual native fixture subchecks are separately recorded in
[operational_archive_contracts.json](operational_archive_contracts.json)
(35 general archive checks) and [native_contracts.json](native_contracts.json)
(27 private worker/archive checks). These nested subchecks are not extra pytest
cases. Both fixtures were removed and made no operating/provider calls.

[scope.json](scope.json) contains the exact component source hashes and operating
limits. [static.json](static.json) retains the initial four-module raw static
warnings; the later complete changed-source review is
[../security-review.json](../security-review.json) with its explicit Low subset
[../security-low-review.json](../security-low-review.json). Do not substitute a
nonexistent `archive/verification.json` or add historical warning/test counts.

The source API verifies caller-owned database identity, one-use purpose credentials,
mandatory authenticated archive encryption, fresh-target/no-overwrite ownership,
durable pending/failed/quarantined attachment gates and independent current-owner
reapproval. Approval opens inspection only; old execution/delivery/deployment/
customer/payment authority remains paused or permanently blocked. Unknown runs,
withdrawal evidence, vault ciphertext and held simulation balances are preserved.

Operating backup readiness, actual credential/key custody, RPO/RTO and HA remain
false/unaccepted. No operating DSN discovery, server/key/config change, live
backup, backend switch or automatic unquarantine was performed. See
[the source contract](../../../docs/EXPLICIT_POSTGRES_ARCHIVES.md).
