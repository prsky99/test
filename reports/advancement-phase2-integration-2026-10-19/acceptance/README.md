# Isolated mounted administrator acceptance

This batch adds acceptance checks at the actual `dashboard_router` mount, using
named synthetic staff sessions, disposable SQLite state and intercepted Chromium
requests. It does not access the user's running server or an external provider.

- Seven API cases passed: thirteen private read routes across four member roles,
  nonmember and transport rejection, immediate membership/session withdrawal,
  SDK policy write/read/CAS/audit, current asset bytes/CSP nonce, and configuration
  remaining separate from operating acceptance.
- Two Chromium cases passed: the four real workspace buttons open native centered
  dialogs, retain them through an eleven-second virtual refresh, and clear private
  state after the current synthetic administrator session is revoked. Browser
  requests were GET only, with no unexpected origin or page error.
- Configured worker activation/deactivation and receiver activation/revocation use
  actual private APIs in Chromium. Each command requires fresh consent; receiver
  field edits clear prior consent. Default-OFF controls stay disabled, and neither
  form accepts addresses or keys or mounts an external inbox.
- Thirty existing operating-preparation and CI file-partition checks passed. The
  current runner selects both new modules exactly once across its four file shards.

The final focused selection passed 46 unique cases: seven API, nine Chromium and
thirty preparation/CI cases. Two targeted reruns are recorded separately and are
not added to that total. These development cases are not added to the historical
v1.38 test count or substituted for the final immutable batch closure. Their
JUnit results and source hashes are recorded in `acceptance.json`. CI source
readiness is not a hosted CI execution; no remote job was started or pushed.

Actual environment gates remain: a designated private staff workspace and its
acceptance receipt; a hosted CI run bound to the final source revision; registered
Google/GitHub applications and approved HTTPS SDK2/BFF origins; approved provider,
independent evaluator and purpose-verified receiver; actual HTTPS three-template
deployment acceptance; and representative storage/backup/restore/load evidence
with assigned owners and agreed RPO/RTO. Browser Push additionally requires the
native subscription and a click on the delivered test notification.

Public Workspace access, advertising, actual financial operations and commercial
release remain disabled. Missing actual targets are reported as missing, rather
than promoted from configuration or synthetic evidence.
