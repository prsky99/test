# Operating workflow products — v2 acceptance complete

The execution worker v2 is deployed. **Fallback is enabled and templates 41, 42
and 43 are published.** The same IDs were requalified; duplicate products were not
created. Earlier failed/unknown runs remain in their original history and were
not automatically replayed.

- **41 — Research Search API:** keyword/result-limit input to English research
  records with original source links and recorded retrieval times.
- **42 — Research Comparison Board:** two independently supplied topics to two
  source panels and a deterministic combined response.
- **43 — Source Bibliography API:** keyword input to real source references,
  preserving titles, links and retrieval times without invented authors/findings.

Open [Workflows / Template Hub](https://agentconcierge.biz/#workflows) and select a
product. Enter public English keywords and explicitly allow one verified
alternative before each run. Product downloads are executable static web apps
that use the Agent Concierge routing gateway.

## Actual operating acceptance

- Normal/shadow execution and **four controlled preflight-outage cases** passed
  with the actual configured delivery. Each case contains exactly one successful
  alternate attempt in the retained routing journal. Both directions of the
  comparison board were exercised. External providers were not shut down.
- Public API changed-input runs all succeeded: research search **3.0 s**, comparison
  **5.6 s**, bibliography **3.3 s**, returning **2 / 4 / 2** real English records.
  Timing is one observation, not a latency guarantee.
- Declared input application was checked in the owner's read-only node audit.
  Public responses correctly hide input logs. Missing sharing consent was rejected,
  and status without a run capability returned 404.
- The real **https://agentconcierge.biz** browser page showed all three choices,
  input controls and per-run consent. A clicked run reached **succeeded**, showed
  source records, cleared its in-memory capability and completed ZIP download.
  The observed cached-input execution duration was **1.4 s**.
- ZIPs for all three products were validated against their current definition.
  All three apps also ran under a **separate static browser origin**, making real
  HTTPS calls to agentconcierge.biz with CORS. They returned **2 / 4 / 2** rendered
  records, reset consent, and had no captured page exceptions or failed requests.
  Static hosting was emulated by the browser route; no customer server was deployed.
- **Owned research Edge dispatches since v2 qualification: 0.** Local first-party
  bindings remain on their validated local handlers. External providers retain
  their existing delivery policy. Uncertain dispatched requests are not silently
  repeated on Origin.

## Corrections made during operating verification

The initial owner CLI did not load the same optional Edge settings as the actual
worker. Native tests passed while public execution exposed first-party HTTP
re-entry through Edge. Those products were withdrawn immediately. The native Edge
entry now excludes first-party identities before ticket/packet creation, and the
CLI loads the service's delivery settings. The user deployed only the repaired
execution worker; other roles did not need another product-code deployment.

The CLI additionally handles PostgreSQL owner approval within its existing writer
transaction and validates worker identity with the real PID command, immutable
source and fresh heartbeat. A concurrent finance workbench change was retained:
the administrator source check pins router/auth/audit bootstrap and product/export
functions, while keeping the frozen release's whole-file integrity check. It does
not require unrelated finance wiring to match this product release. Its positive
and negative scope tests passed.

Affected Edge/local/product/operator regressions: **96 passed**; latest operator
subset after the scope adjustment: **12 passed**. These overlap and are not added
together. Earlier baseline and PostgreSQL/content checks are recorded in README.
No broad platform/security certification or zero-failure SLA is asserted.

## Current approval limits

Active routing covers every eligible **opted-in** request, at most **one alternative
per whole run**, and **1,000 admissions per template policy**. The current signed
approval expirations in **Asia/Seoul** are:

- 41: **2026-10-25 20:27:54 KST**
- 42: **2026-10-25 20:28:02 KST**
- 43: **2026-10-25 20:28:18 KST**

These are bounded validation approvals, not permanent uptime promises. Expired,
changed or withdrawn verification blocks publication/new protected execution.
There is no silent automatic approval extension; continued operation after the
window requires fresh qualification. Source coverage differs between Crossref
articles and arXiv preprints, and total network/CDN independence is not certified.
Source caches retain their original retrieval timestamps.

## Evidence

- `operating-v2-readiness.txt`: execution v2 and compatible other roles ready.
- `operating-v2-qualification.txt`, `operating-qualification.json`: same-ID normal
  and controlled-outage proof references.
- `operating-v2-final-state.json`: published/active state, four alternate attempt
  summaries, bounded policy and owned Edge dispatch count.
- `operating-public-verification.json`: all three changed-input API results and
  ZIP checks; run keys were never written to evidence files.
- `operating-browser-verification-https.json`: real public browser terminal success.
- `exported-customer-app-verification.json` (41),
  `exported-customer-app-42-verification.json`,
  `exported-customer-app-43-verification.json`: exported app/cross-origin results.
- The failed v1 public results, withdrawal and loading-only browser evidence remain
  preserved and are explicitly superseded by this acceptance, rather than erased.
