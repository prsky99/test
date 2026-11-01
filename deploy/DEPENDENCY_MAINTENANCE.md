# Dependency maintenance

The production profile uses PostgreSQL/pgvector and Python 3.11.18 or a later security patch in the same tested branch. Python's `sqlite3` standard-library module remains necessary for shared source contracts, isolated tests and migration/restore tooling. The optional `sqlite-vec` extension is excluded from production.

## Reviewed environments

- `requirements-runtime.lock`: complete production dependency versions and artifact hashes; excludes tests, browser automation, SQLite vectors and optional Claude integrations.
- `requirements-dev.lock`: production versions plus pytest, Playwright and the legacy vector parity tests.
- `requirements-anthropic-runtime.lock`: production plus the optional Claude seller/broker SDK. The local model runtime does not require this SDK.
- `requirements-build.lock`: pinned build tools for the existing `http-ece` package, and the native Psycopg C extension. These reviewed source builds avoid stale TLS libraries embedded in binary wheels.
- `requirements-security.lock`: audit and lock maintenance tools in a separate environment.

Do not resolve production dependencies from loose version ranges. Update reviewed direct pins, regenerate the complete locks, audit, then test before release preparation. `pycryptodome` remains on the compatible 3.x branch because `eth-keyfile` requires `<4`. Miniflare currently requires the compatible Undici 7.x line; its patched 7.30.1 release is selected instead of forcing an incompatible 8.x upgrade.

## Current Mac setup

The project-local Python/OpenSSL/SQLite and Node/npm toolchains are prepared from fixed upstream releases and verified SHA-256/SHA3/SHA-512 digests. The configuration is `deploy/runtime-versions.json`.

```sh
python scripts/prepare_secure_toolchain.py --build
```

This builds only inside `gateway-data/toolchains`; it does not change Homebrew, Conda, system Python, system Node or a running project server. The selected OpenSSL LTS branch is 3.5.9; libpq 18.6 is built against that patched library. Its trust bundle is certifi 2026.10.23. The CPython ensurepip bootstrap is separately updated so creating an ordinary future venv does not reinstall the old bundled pip/setuptools versions.

The reviewed production environment is `.venv`; test dependencies belong in `.venv-tests` and maintenance tools in `.venv-security`. To create a clean environment elsewhere, use the patched Python and install with hashes:

```sh
./gateway-data/toolchains/python-3.11.18/bin/python3.11 -m venv --without-pip .venv-new
.venv-security/bin/python -m pip --python .venv-new/bin/python install --require-hashes -r requirements-build.lock
PATH="$PWD/gateway-data/toolchains/libpq-18.6-openssl-3.5.9/bin:$PATH" .venv-new/bin/python -m pip install --no-cache-dir --require-hashes --no-build-isolation -r requirements-runtime.lock
.venv-new/bin/python -m pip uninstall --yes setuptools wheel packaging
.venv-new/bin/python -m pip check
```

Do not rename a venv without updating its activation and console script paths. The source build helper refuses to overwrite an incomplete toolchain directory; inspect a failed build before removing only its owned partial output.

## Verification commands

```sh
.venv/bin/python scripts/audit_dependency_profile.py --profile runtime
.venv/bin/python -m pip check
.venv-security/bin/python -m pip_audit --disable-pip --no-deps -r requirements-runtime.lock
.venv-security/bin/python -m pip_audit --disable-pip --no-deps -r requirements-dev.lock
./cloudflare/edge-gateway/npmw audit --ignore-scripts
./cloudflare/edge-gateway/npmw test
```

`npmw` always uses project-local Node 26.12.1 and npm 12.2.1. `.npmrc` refuses unsupported Node versions and disables package installation lifecycle scripts. No Worker deployment is performed by these commands.

For a development environment, install the hashed build tools followed by `requirements-dev.lock` with `--no-build-isolation`. Remove setuptools and wheel afterwards, but retain packaging because pytest uses it. The Claude integration can be installed with `requirements-anthropic-runtime.lock`; it is loaded only when that provider is explicitly instantiated without an injected client.

The PR/push workflow audits complete Python locks and npm dependencies, and exercises the Worker tests. It has no scheduled jobs, automatic deployment or automatic package installation into production.

## Releasing

Prepare a release only after verification:

```sh
./agentcon package RELEASE_NAME
```

Packaging checks that the copied runtime matches the production lock, preserves all requirement locks and records the private runtime inventory in `runtime-environment.json`. These files must never be exposed on public routes. Preparing a package does not restart a service.

After explicit operator approval, apply the same reviewed release independently to frontend, admin, jobs and execution. Preserve rollback release files. Stop disconnected previous web processes only after confirming that they serve no traffic and have no active requests. A worker replacement can pause new background work briefly. Never substitute a dependency installation for a controlled service rollout.

A zero advisory count means no matching known advisories at the audit time. It does not prove the absence of undisclosed vulnerabilities or malicious package releases. Re-review upstream advisories and provenance when updating locks.

`psycopg[c]` is intentionally used instead of `psycopg[binary]`: the otherwise current 3.3.6 binary package was observed to bundle OpenSSL 3.5.8. Native C builds require the reviewed `pg_config` on PATH. No PostgreSQL server or database is installed by the toolchain helper; it builds only client libraries and headers. Linux CI/images use current distribution libpq development packages for this compilation and must keep their OS security updates current.

On macOS, profile verification checks the actual loaded libpq and OpenSSL libraries and the CA bundle, not just Python distribution version strings. Do not delete a versioned toolchain directory while a retained release references it. The Dockerfile changes use distribution client development packages; no Docker image was built during the native Mac verification.
