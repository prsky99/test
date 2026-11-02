# Owned local execution and timeout correction

2026-10-20. Scope: the four public Testbench examples, six owned data agents,
three published workflows and their downloadable web apps.

## Findings and corrections

- Public activation selected the owned examples/templates, but a fresh proxy or
  independent worker could still use the public MCP URL. All proxies now resolve
  the existing approved owned profile to an in-process dispatcher and shared local
  engine. Missing or altered bindings fail closed; there is no HTTP fallback to
  the public origin. Public data-source HTTPS remains necessary for current data.
- A newer catalog entry sharing an endpoint could replace an owned binding.
  Owned presets and template nodes now resolve exact first-party keys/source/URL.
- The source/coalescing budgets could exceed the public eight-second execution
  deadline. Agent work now uses a six-second budget, five-second absolute source
  sub-budget and four-second socket timeout. Optional English translation is one
  short local-loopback call; remote model endpoints are refused.
- SQLite's normal ten-second writer wait exceeded the old eight-second ownership
  lease. File SQLite now uses a twenty-second lease; memory/PostgreSQL retain
  eight seconds. Heartbeats retry after short busy samples. Claim, ownership and
  pulse sample time after acquiring the writer reservation, so an expired owner
  cannot be revived by a stale timestamp. Original run deadlines and monotonic
  fences remain enforced. Crash detection on file SQLite can consequently take
  up to twenty seconds, subject to the original run deadline.
- Optional owned call counters/quality-evidence writes could hold a completed
  response behind a catalog writer. These writes now use a short bounded wait
  and may be skipped, with a skip counter and bounded warning. No artificial
  verification evidence is created. Mandatory authority checks, dispatch records,
  checkpoints, workflow completion and delivery transactions are unchanged.
- Restarted operating verification exposed an additional transport boundary:
  the browser aborted the whole Testbench request after eight seconds, the same
  duration as the server's execution-only limit. Admission and response transit
  could therefore lose an otherwise completed response. The Testbench now waits
  up to twenty seconds for the HTTP response; the server's eight-second execution
  limit is unchanged and POSTs are never automatically retried. Public static
  assets were rebuilt and verified as served with `Cache-Control: no-store`.

## Verification evidence

- `final-regressions.xml` / `.log`: 308 passed, zero failures/skips, including
  integration, browser and security regressions. Tests use isolated databases and
  synthetic source fixtures. The final source hashes remained unchanged.
- `fresh-run-browser.xml` / `.log`: all four example buttons, three workflow
  buttons, three downloads and three downloaded apps. Each submission is checked
  using its newly returned run identifier and actual terminal status; an old
  success modal is not accepted as completion proof.
- `final-real-local-sources/verification.json`: all six agents, four Testbench
  executions and three two-agent workflows succeeded against real public data
  sources in an isolated activated frontend. Proxy public-origin MCP HTTP was
  forbidden during the acceptance. No fabricated fallback data was used.
- `final-lease-regressions.xml`: real nine-second SQLite writer contention after
  dispatch; one provider call, successful completion, unchanged absolute run
  deadline/fence. Also tests ownership/heartbeat expiration during writer waits.
- `test_owned_data_agents_local_execution.py`: fresh proxy and independent worker
  locality, exact binding selection, profile/schema tampering denial, source
  timeout, bounded optional bookkeeping under a real writer lock, timeout
  restoration and caller transaction preservation.
- `public-content.log`: 229 public frontend files checked, zero violations.
  `ruff.log`, `bandit.json`, `bandit-runtime.json`: scoped static checks.
  Ruff and both scoped Bandit scans reported zero findings.
- `postgres-catalog.log`: generated PostgreSQL statement catalog consistency.
  Native PostgreSQL operation was not tested in this task.
- `source-frozen.json`: final implementation/test source hashes.
  This baseline predates the operating transport follow-up; final transport
  source/artifact hashes are in `source-final-transport.json`.
- `transport-regressions.xml` / `.log`: 104 passed after the transport correction,
  including a completed response delayed 8.4 seconds with exactly one POST.
  Together with the baseline, there are 309 distinct passing cases. The repeated
  tests are not added to the unique total. `transport-content.log` again records
  229 files and zero violations; `transport-ruff.log` records zero findings.
- `restarted-operating-transport/verification.json`: final operating acceptance
  succeeded through the actual public domain: four Testbench executions, three
  newly submitted workflows, three ZIP downloads, three newly submitted runs
  from downloaded apps at a separate simulated customer origin, and the two
  additional agent endpoints. All six agents returned English source-backed
  results. There were zero browser script errors or timeouts in this final run.
  Source retrieval may use the explicitly labelled bounded real-data cache.

The real-source acceptance uses this reproducible command (choose a new output
directory):

```sh
.venv/bin/python -m scripts.verify_owned_agent_publication --live \
  --output reports/owned-local-execution-2026-10-20/another-live-check
```

## Operating deployment boundary

No project server was stopped, replaced or restarted by the coding agent.
The user restarted the server; the new process was verified. The additional
browser timeout correction was published as completed static assets and
confirmed on the operating public frontend without replacing the server.
`operating-bindings.json` records the earlier read-only selection check;
`restarted-operating-transport/verification.json` records final operating success.

The initial operating attempt in `restarted-operating/verification.json` remains
preserved as unsuccessful: its fourth Testbench response was cut off by the
original browser timeout. It is superseded by the final acceptance, not relabelled
as a success. The retained legacy embedded presentation also contains the same
source correction and will load it on the next ordinary server restart; the
default published frontend was the operating acceptance target.

Earlier timeout/unknown run records are preserved. They are not overwritten as
success or automatically replayed. Public source availability still affects data
retrieval: stale-cache use is explicitly labelled, and unavailable data returns a
bounded safe failure. No application can guarantee a third-party data source's
availability. Latin-script language detection remains heuristic for third-party
names/titles, while unsupported non-Latin prose is translated locally or omitted.
