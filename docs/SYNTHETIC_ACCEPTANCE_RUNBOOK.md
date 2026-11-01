# Synthetic customer and PostgreSQL acceptance

This profile replaces real customers with synthetic identities and controlled
providers for the user's 2026-10-20 development acceptance scope. It does not
certify production capacity, hosted identity providers, physical Web Push,
independent reviewer custody, PostgreSQL HA or point-in-time recovery.

## Existing local PostgreSQL

Prerequisites: the project Python environment and requirements, `psycopg`, and
`pg_dump`/`pg_restore` compatible with the target PostgreSQL major version.
Use a PostgreSQL operator with `CREATEDB`. The user starts and manages the
existing PostgreSQL service. This command does not start or stop any service.

Run from the repository root, using a **new** report directory each time:

```sh
.venv/bin/python -m scripts.validate_postgres_acceptance --local --run \
  --workers 8 --operations 100 --output reports/local-pg-acceptance-001
```

`--local` explicitly selects `/tmp`, port 5432, the current OS user, and the
`postgres` maintenance database. The application data targets are always two
new random `ac_validation_…` databases. There is no existing application target
option. No production database is copied, dropped, renamed or reset.

The source and restore databases remain available for inspection. Their names
are recorded in the owner-only `result.json`. Failed attempts also retain their
created names. Remove only those exact fixture databases after review using
normal PostgreSQL administration. Never substitute a production database name.
The random synthetic signing key stays only in process memory, so these retained
fixtures are for inspection, not persistent customer login or service deployment.

## A different PostgreSQL server

1. Check out the same source version and install its requirements.
2. Install matching PostgreSQL client tools and configure a test-only operator
   with `CREATEDB`, an isolated server allocation, and a verified TLS hostname.
3. Copy `deploy/acceptance/postgres-connection.example.json` outside version
   control, replace the placeholders, and set file permissions to `0600`.
   An optional `password` field may be added to this private copy. Never put
   credentials in command arguments, source control or chat.
4. Unset inherited `PG*` environment settings and
   `AGENT_PRIVATE_ARTIFACT_KEYRING`. The runner deliberately rejects these so
   operating connection options and artifact keys cannot affect synthetic data.
5. Run:

```sh
.venv/bin/python -m scripts.validate_postgres_acceptance \
  --connection-file /private/path/postgres-test.json --run \
  --workers 8 --operations 100 --output reports/remote-pg-acceptance-001
```

Remote connections require `sslmode=verify-full`. Neither TLS hostname checking
nor certificate validation is bypassed. The supplied database is used only for
maintenance commands that create fresh databases. All application and restore
writes go to this run's newly created targets.

The report contains individual booleans, server version, workload size/latency,
backup hash, logical restore duration and explicit limits. A `synthetic.dump`
is stored with `0600` permissions and contains only this run's virtual data.
`completed: true` requires all checks to pass. On failure, inspect the private
report; the command intentionally does not print raw driver errors or secrets.

## Covered behavior and evidence

- Three customers complete controlled OAuth exchanges. No real Google/GitHub
  account or external provider is contacted.
- Organization invitation, editor permissions and unrelated-customer denial.
- Production application repositories, offline input review, one explicit MCP
  execution, replay deduplication and input-dependent retained output.
- SDK PKCE authorization, separate run consent, downloaded package without
  customer/bearer tokens, and release withdrawal before further dispatch.
- No administrator membership is created. Customer sessions are revoked before
  backup, and the restored database does not revive the revoked session.
- Real PostgreSQL transactions, rollback, reconnect, concurrent inserts/counter
  updates, one-winner claim and stale-fence rejection. The contention probes
  are synthetic SQL; their latency is not application capacity or an SLA.
- Logical custom-format dump into a second database and exact committed counts,
  application checkpoint and workflow output integrity. One intentional commit
  after the backup is absent, demonstrating the snapshot boundary. This is not
  WAL/PITR, a standby promotion, a full outage RTO or an operating RPO guarantee.

The broader customer/API/browser and real loopback TLS notification tests are
listed in `reports/synthetic-closeout-2026-10-20/test-selection.json`. Reproduce
them with the listed modules and `python -m pytest`; they use disposable stores
and controlled providers, not the running project service. Their Push permission,
subscription and click confirmations are synthetic browser fixtures. Their
recovery reviewers and A2A providers are controlled identities, not independent
external custodians or real long-task providers.

## Current explicit holds

ChatGPT inference remains on the user's quota hold. Gemini and Claude
subscription login/use is excluded; retain prior status records only. Payment
TEST/Connect onboarding, hosted CI and human peer approval are on user hold.
Workspace publication is a separate decision: its navigation remains hidden
until an explicit activation instruction. This runner never changes any of
these settings or the running project server.
