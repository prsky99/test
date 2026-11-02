# Frontend report language fix and email inventory

Inspected 17 October 2026. Public frontend code was updated; the user's running
server was not restarted. Database inspection used read-only connections with
query-only mode. No stored report, visitor/contact record or email address was
changed, and no email was sent.

## Report display fix

The database contains 470 test reports. Of these, 273 have bilingual Pros/Cons
headings; 91 also include a Korean Workflow label. These labels came from stored
Markdown, so a literal-source language check alone did not detect the display issue.

The common report renderer now normalizes those labels into English and removes
redundant bilingual parentheses. It also handles the few Korean terms in existing
explanatory report text. Unknown Korean narrative text uses an explicit English
unavailable-text notice rather than an invented translation. Raw request/response
text is displayed using Unicode escapes where necessary, preserving decoded JSON
values and original evidence. The renderer works on a copy; the original report,
API evidence, timestamps, grades and outcome are preserved. Output escaping remains
in place for both Markdown and structured fields.

Verification:

- 44 API/browser regressions passed, including actual report loading, expanded
  Markdown/wire sections, legacy JSON-string lists, source-object preservation,
  unknown-text fallback and script/HTML injection probes.
- All 470 stored reports were checked against the display normalizer: 3,290 text
  fields, zero remaining Hangul, zero unavailable-text fallbacks for current data.
- 47 public frontend files passed the language/content checker, including embedded
  HTML parity. Inline JavaScript syntax checks passed.

Artifacts: `regression.xml`, `stored-report-language.json`, `verification.json`.

## Current frontend addresses

- **contact@agentconcierge.biz** — current official service contact. The active
  template contains ten occurrences across the footer, support/contact panel,
  privacy choices, accessibility notice, security-abuse guidance and submission
  error guidance. The Web Push sender also uses it as its service contact identity.
- **you@domain.com** — placeholder in the inquiry email field; not a service mailbox.
- **privacy@agentconcierge.biz** — only in the older
  `scripts/apply_frontend_legal_compliance.py` maintenance script, line 789.
- **accessibility@agentconcierge.biz** — only in that same older script, line 844.

The two role-specific addresses use the required `.biz` domain and remain only in
the maintenance script. The active frontend uses the general contact address above.
This inspection did not test mailbox existence, domain ownership or deliverability.

## Stored content addresses

The inventory additionally inspected 470 stored reports and 24,622 eligible public
catalog records (active, healthy/reachable, not quarantined). It covers the report
copy and wire text and catalog name, description, URL, details and usage guide after
existing public credential redaction. Visitor, contact, conversation, subscription
and marketing-permission tables were excluded.

There are **174 distinct address spellings** across all inspected scopes:

- Frontend source/maintenance: 4.
- Stored test reports: 27.
- Public catalog metadata: 147.

Scopes overlap, so these counts must not be added. There are 172 case-folded
spellings; neither count establishes a number of distinct real mailboxes.

Report/catalog matches include test inputs, disposable-address examples, third-party
support details and personal-looking strings. Their purpose, existence and owner
identity have not been verified. They are not a verified customer/marketing list.
Five matches inside URL credentials were excluded from email classification;
malformed numeric-domain examples were not treated as mailbox contacts.

`front.py` embeds a mirror of `extracted_html.txt`. Detailed physical source counts
include both copies and repeated examples; they are not unique UI placements.

[Complete address and origin inventory](email-inventory.json) contains every matched
address with source file/line or report/catalog record ID and field. A searchable
Canvas accompanies the inventory; it contains inline snapshot data and makes no
network requests. These artifacts are internal review materials, not public
frontend pages. Email addresses were investigated, not rewritten.
