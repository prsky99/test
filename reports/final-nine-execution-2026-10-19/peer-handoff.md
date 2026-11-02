# Peer handoff — finite development candidate

This package covers the existing nine-step/42-requirement closeout and the
user-requested subscription-provider investigation. It is ready for review;
human acceptance and actual external-target acceptance are not supplied by the
assistant. See [per-step state](acceptance.json) and the final README for results.

## Review the changed behavior

1. Local ChatGPT reauthorization reuses the issued client, enforces expected
   subject/account/host and owner-only files, and preserves old credentials on
   rejected authorization. Its explicit local proposer receives current authority
   checks. Public startup remains Ollama and no ChatGPT inference was retried.
2. The regression runner checks native PostgreSQL dependencies before starting
   a large cohort. `--list` remains read-only and dependency-free. The mandatory
   selection includes current published frontend tests and provider/reconnect tests.
3. Legacy structural/UI assertions explicitly test the supported embedded
   fallback. Current published presentation has its own mandatory suite, plus
   real controlled example execution, current Chat/default A2A, output escaping,
   workflow/SDK, consent/revocation, and CSP coverage. No policy test was skipped.
4. Unavailable examples in the current design show the bounded server-provided
   reason as text and remain disabled. Both generation source and published asset
   are synchronized. No unsafe HTML handler or new network destination is added.
5. PostgreSQL catalog changes contain only source-line names and source hashes;
   the3473 SQL statements and223 table definitions retain their semantics.

## Reproduce safely

Use the project interpreter and the existing dependency files. Install
`requirements-storage-postgres.txt` before native checks. Use disposable
databases, owned Unix sockets, isolated browser routes and synthetic identities;
do not point regression fixtures at operating data or replace the user's server.

Run the existing CI entry point in four nonoverlapping shards, each with a
different output directory. Its content check and explicit module selection
must pass. Compare every pinned product source and current presentation asset
afterwards. Do not add old baseline counts or diagnostic reruns to unique totals.
Retain initial failure evidence and any late test-only source pin separately.

## Required real acceptance still awaiting targets

- Protected receiver/SDK deployment, independently held recovery credentials and
  physical Push delivery/click.
- Approved actual long-task A2A target and independent corpus/evaluator/qualifier,
  benchmark and trust custody.
- Designated PostgreSQL/HA/load/DR target with owners and RPO/RTO thresholds.
- An eligible selected payment sandbox account. Current pre-business eligibility
  remains unresolved; do not invent a country/entity or use live money.
- Hosted CI and human peer signoff.

ChatGPT inference remains on the user's hold. Gemini returned an unsupported
client, not a confirmed quota error. Claude native personal planning passed;
none of this installs hosted Gemini/Claude customer sign-in or pools credentials.

## Apply and roll back

The assistant did not restart, stop, or replace the project server. Python
changes require one user-controlled restart when the final candidate is ready.
Published static changes are read from disk and become visible on reload.
Keep Workspace navigation, advertising and real money disabled.

No operating data migration was performed. A rollback must restore a coherent
previous source/assets/catalog bundle and keep current operating data and grants
intact; never copy an old database or token backup over live state. Do not
automatically reauthorize or replay unknown external operations. The native CLI
profiles and installed test runtime are ignored private artifacts; use each
provider's normal disconnect/logout when the user decides to remove access.
