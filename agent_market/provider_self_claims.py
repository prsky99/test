"""Provider self-service claims (docs/PROVIDER_SELF_CLAIM.md, PM decisions 11-15 11:0x).

A signed-in customer proves control of an agent's address with a one-use value:

- ``well_known``: ``https://<origin>/.well-known/agentvalcon-claim.json`` holds exactly
  ``{"profile": PROFILE, "claim": <claim id>, "nonce": <nonce>}``; a verified origin covers every active resource on it.
  Shared hosting origins (path tenants) cannot be claimed this way.
- ``protocol``: one resource proves it inside its own protocol: an MCP server puts ``agentvalcon-claim=<nonce>`` in its
  ``initialize`` instructions or ``_meta``; an A2A card lists ``{"uri": A2A_EXTENSION, "params": {"nonce": ...}}`` in
  ``capabilities.extensions``.

What a claim is and is not: control of that location at the check time. It never touches grades, ranks, tests or
recommendations, and it is shown only to the provider and to operators (no public badge, PM decision 3).

Storage lives in its own PostgreSQL schema (``SCHEMA``), never in the application's public schema: the application
store refuses to start when its catalog names a table that production does not have, and public triggers are checked
on every connection. Production processes never create these tables; they attach on first use and keep the feature
off (HTTP 409, empty lists) until operators create the schema (docs/PROVIDER_SELF_CLAIM.md 6, DB change procedure).
SQLite (tests, local runs) creates them in place.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import sqlite3
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import urlsplit

PROFILE = "agentvalcon-provider-claim-v1"
WELL_KNOWN = "/.well-known/agentvalcon-claim.json"
A2A_EXTENSION = "https://agentconcierge.biz/ext/provider-claim/v1"
MARKER = re.compile(r"agentvalcon-claim=([A-Za-z0-9_-]{20,128})")
SCHEMA = "provider_claims"
SCHEMA_VERSION = 1
USER_AGENT = ("AgentValCon-claim-check/1.0 (+https://agentconcierge.biz/; contact@agentconcierge.biz; "
              "provider-started ownership check, one request)")

PENDING_S = 24 * 3600          # PM decision 2
VALID_S = 30 * 86400
RECHECK_BEFORE_S = 3 * 86400
RETRY_S = 24 * 3600
LAPSE_AFTER = 2
MAX_LIVE_CLAIMS = 20           # per customer
MAX_CHECKS_A_DAY = 10          # user-started checks per customer
ORIGIN_GAP_S = 60.0            # at most one check a minute per origin
MAX_OPEN_CORRECTIONS = 5
# Outside git; the agent team appends, the admin panel reads. PROVIDER_CLAIMS_DATA points every role at one folder.
RECOMMENDATIONS = Path(os.environ.get("PROVIDER_CLAIMS_DATA", "gateway-data/provider-claims")) / "recommendations.jsonl"
RESPONSE_LIMIT = 4096
TIMEOUT_S = 8.0
BUDGET_SYSTEM = "provider_claims"
LIVE = ("pending", "checking", "verified")
FIELDS = ("name", "description", "category")

# Hosting platforms serve many customers under one origin (by path) or give each tenant a subdomain; the platform's
# own origin is never claimable by file (a tenant subdomain is). Operators can extend the list.
SHARED_ORIGINS = frozenset({"server.smithery.ai", "smithery.ai", "mcp.so", "glama.ai", "mcp.composio.dev",
                            "api.githubcopilot.com", "huggingface.co", "github.com", "gist.githubusercontent.com",
                            "raw.githubusercontent.com"})

DDL = (
    """CREATE TABLE IF NOT EXISTS provider_self_claims(id TEXT PRIMARY KEY, customer_id TEXT NOT NULL,
       method TEXT NOT NULL, origin TEXT NOT NULL, resource_id INTEGER, scope_key TEXT NOT NULL,
       nonce_hash TEXT NOT NULL, status TEXT NOT NULL, revision INTEGER NOT NULL, created REAL NOT NULL,
       expires REAL NOT NULL, verified_at REAL, next_check REAL, fail_count INTEGER NOT NULL DEFAULT 0,
       last_error TEXT)""",
    """CREATE UNIQUE INDEX IF NOT EXISTS provider_self_claims_live ON provider_self_claims(customer_id, scope_key)
       WHERE status IN ('pending','checking','verified')""",
    "CREATE INDEX IF NOT EXISTS provider_self_claims_origin ON provider_self_claims(origin, status)",
    "CREATE INDEX IF NOT EXISTS provider_self_claims_due ON provider_self_claims(status, next_check)",
    """CREATE TABLE IF NOT EXISTS provider_self_claim_checks(claim_id TEXT NOT NULL, customer_id TEXT NOT NULL,
       origin TEXT NOT NULL, at REAL NOT NULL, started_by TEXT NOT NULL, outcome TEXT NOT NULL, http_status INTEGER,
       ms INTEGER, PRIMARY KEY(claim_id, at))""",
    "CREATE INDEX IF NOT EXISTS provider_self_claim_checks_customer ON provider_self_claim_checks(customer_id, at)",
    "CREATE INDEX IF NOT EXISTS provider_self_claim_checks_origin ON provider_self_claim_checks(origin, at)",
    """CREATE TABLE IF NOT EXISTS provider_correction_requests(id TEXT PRIMARY KEY, claim_id TEXT NOT NULL,
       customer_id TEXT NOT NULL, resource_id INTEGER NOT NULL, field TEXT NOT NULL, proposed TEXT NOT NULL,
       evidence_url TEXT, status TEXT NOT NULL, created REAL NOT NULL, decided_at REAL, decided_by TEXT,
       decision_note TEXT)""",
    "CREATE INDEX IF NOT EXISTS provider_correction_requests_status ON provider_correction_requests(status, created)",
    "CREATE TABLE IF NOT EXISTS provider_claim_schema(id INTEGER PRIMARY KEY, version INTEGER NOT NULL)",
)

# Every statement the module runs, by name (the PostgreSQL pool runs only these; '?' becomes '%s').
SQL = {
    "schema_get": "SELECT version FROM provider_claim_schema WHERE id=1",
    "claim_insert": "INSERT INTO provider_self_claims(id,customer_id,method,origin,resource_id,scope_key,nonce_hash,"
                    "status,revision,created,expires,fail_count) VALUES(?,?,?,?,?,?,?,'pending',1,?,?,0)",
    "claim_get": "SELECT * FROM provider_self_claims WHERE id=? AND customer_id=?",
    "claim_get_any": "SELECT * FROM provider_self_claims WHERE id=?",
    "claim_live_for_scope": "SELECT * FROM provider_self_claims WHERE customer_id=? AND scope_key=? "
                            "AND status IN ('pending','checking','verified')",
    "claims_live_count": "SELECT count(*) AS n FROM provider_self_claims WHERE customer_id=? "
                         "AND status IN ('pending','checking','verified')",
    "claims_for_customer": "SELECT id,method,origin,resource_id,status,revision,created,expires,verified_at,"
                           "next_check,fail_count,last_error FROM provider_self_claims WHERE customer_id=? "
                           "ORDER BY created DESC LIMIT 100",
    "claims_verified_for_customer": "SELECT * FROM provider_self_claims WHERE customer_id=? AND status='verified' "
                                    "AND expires>?",
    "claim_transition": "UPDATE provider_self_claims SET status=?, revision=revision+1, last_error=? "
                        "WHERE id=? AND revision=? AND status=?",
    "claim_verified": "UPDATE provider_self_claims SET status='verified', revision=revision+1, verified_at=?, "
                      "expires=?, next_check=?, fail_count=0, last_error=NULL WHERE id=? AND revision=?",
    "claim_recheck_failed": "UPDATE provider_self_claims SET status=?, revision=revision+1, fail_count=?, "
                            "next_check=?, last_error=? WHERE id=? AND revision=?",
    "claims_due": "SELECT * FROM provider_self_claims WHERE status='verified' AND next_check<=? "
                  "ORDER BY next_check LIMIT ?",
    "claims_expire_pending": "UPDATE provider_self_claims SET status='expired', revision=revision+1 "
                             "WHERE status IN ('pending','checking') AND expires<=?",
    "check_insert": "INSERT INTO provider_self_claim_checks(claim_id,customer_id,origin,at,started_by,outcome,"
                    "http_status,ms) VALUES(?,?,?,?,?,?,?,?)",
    "checks_customer_since": "SELECT count(*) AS n FROM provider_self_claim_checks WHERE customer_id=? "
                             "AND started_by='user' AND at>?",
    "checks_origin_last": "SELECT max(at) AS at FROM provider_self_claim_checks WHERE origin=?",
    "correction_insert": "INSERT INTO provider_correction_requests(id,claim_id,customer_id,resource_id,field,"
                         "proposed,evidence_url,status,created) VALUES(?,?,?,?,?,?,?,'open',?)",
    "corrections_open_count": "SELECT count(*) AS n FROM provider_correction_requests WHERE customer_id=? "
                              "AND status IN ('open','held')",
    "corrections_for_resource": "SELECT id,field,proposed,evidence_url,status,created,decided_at,decision_note "
                                "FROM provider_correction_requests WHERE customer_id=? AND resource_id=? "
                                "ORDER BY created DESC LIMIT 50",
    "corrections_waiting": "SELECT * FROM provider_correction_requests WHERE status IN ('open','held') "
                           "ORDER BY created LIMIT ?",
    "correction_decide": "UPDATE provider_correction_requests SET status=?, decided_at=?, decided_by=?, "
                         "decision_note=? WHERE id=? AND status IN ('open','held')",
}


class ClaimError(Exception):
    def __init__(self, code: str, status: int = 400, detail: str = ""):
        super().__init__(detail or code)
        self.code, self.status = code, status


# ---------------------------------------------------------------- storage
class SqliteClaimDB:
    """Tests and local runs: one SQLite file or connection, tables created in place."""
    backend = "sqlite"

    def __init__(self, path=":memory:"):
        self._db = sqlite3.connect(str(path), check_same_thread=False, isolation_level=None)
        self._db.row_factory = sqlite3.Row
        self._lock = threading.RLock()
        with self._lock:
            for statement in DDL:
                self._db.execute(statement)
            self._db.execute("INSERT OR IGNORE INTO provider_claim_schema(id,version) VALUES(1,?)", (SCHEMA_VERSION,))

    def ready(self) -> bool:
        return True

    @contextmanager
    def tx(self):
        with self._lock:
            self._db.execute("BEGIN IMMEDIATE")
            try:
                yield self
                self._db.execute("COMMIT")
            except BaseException:
                self._db.execute("ROLLBACK")
                raise

    def run(self, name, args=()):
        return self._db.execute(SQL[name], args).rowcount

    def one(self, name, args=()):
        row = self._db.execute(SQL[name], args).fetchone()
        return dict(row) if row is not None else None

    def all(self, name, args=()):
        return [dict(r) for r in self._db.execute(SQL[name], args).fetchall()]


SQL_REGISTRY = Path(__file__).with_name("provider_self_claims_sql.json")


def sql_digests() -> dict:
    return {name: hashlib.sha256(" ".join(text.split()).encode()).hexdigest() for name, text in sorted(SQL.items())}


def registered_digests() -> dict:
    try:
        data = json.loads(SQL_REGISTRY.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data.get("statements") if isinstance(data, dict) and isinstance(data.get("statements"), dict) else {}


class PostgresClaimDB:
    """Production, inside SCHEMA (never public), on the application database.

    - No standing connection (connection budget: max_connections 48, application pools 45): every transaction or
      single read opens one connection, pins search_path and a 2-second statement limit, and closes it at the end.
      At most one is open per process at a time.
    - Only registered statements: each statement's digest must match agent_market/provider_self_claims_sql.json
      (checked again before every statement); a registry that does not match the code keeps the feature off. This is
      the claims schema's own list, like AI AD Coin's sql_registry.json, kept out of the application catalog whose
      start-up check would stop the frontend until the tables exist.
    - Attaches on first use. While the schema is missing (or of another version) the feature stays off and the check
      (one short connection) is repeated at most every 5 minutes, only when someone uses the feature."""
    backend = "postgres"
    RETRY_S = 300.0

    def __init__(self, factory, clock=time.monotonic):
        self.factory, self.clock = factory, clock
        self._lock = threading.RLock()
        self._ready, self._checked = False, None
        self._local = threading.local()

    def _open(self):
        connection = self.factory()
        try:
            connection.autocommit = True
            connection.execute("SET search_path TO " + SCHEMA)
            connection.execute("SET statement_timeout = 2000")
        except Exception:
            connection.close()
            raise
        return connection

    def ready(self) -> bool:
        if self._ready:
            return True
        now = self.clock()
        if self._checked is not None and now - self._checked < self.RETRY_S:
            return False
        self._checked = now
        if registered_digests() != sql_digests():
            return False
        try:
            row = self.one("schema_get")
            self._ready = row is not None and int(row["version"]) == SCHEMA_VERSION
        except Exception:
            self._ready = False
        return self._ready

    @contextmanager
    def tx(self):
        with self._lock:
            connection = self._open()
            try:
                with connection.transaction():
                    self._local.connection = connection
                    try:
                        yield self
                    finally:
                        self._local.connection = None
            finally:
                connection.close()

    def _execute(self, name, args, fetch):
        from psycopg.rows import dict_row
        text = SQL[name]
        if registered_digests().get(name) != hashlib.sha256(" ".join(text.split()).encode()).hexdigest():
            raise RuntimeError("unregistered_sql: " + name)
        with self._lock:
            current = getattr(self._local, "connection", None)
            connection = current or self._open()
            try:
                cursor = connection.cursor(row_factory=dict_row)
                cursor.execute(text.replace("?", "%s"), tuple(args))
                if fetch == "one":
                    row = cursor.fetchone()
                    return dict(row) if row is not None else None
                if fetch == "all":
                    return [dict(r) for r in cursor.fetchall()]
                return cursor.rowcount
            finally:
                if current is None:
                    connection.close()

    def run(self, name, args=()):
        return self._execute(name, args, "run")

    def one(self, name, args=()):
        return self._execute(name, args, "one")

    def all(self, name, args=()):
        return self._execute(name, args, "all")


def postgres_schema_statements() -> list[str]:
    """DDL for the operators' change (rehearsal first, user approval, DATABASE_OPERATIONS.md). Never run by the app."""
    # Run as the application's own database role (it then owns the schema); SET LOCAL ends with the transaction.
    out = ["CREATE SCHEMA IF NOT EXISTS " + SCHEMA, "SET LOCAL search_path TO " + SCHEMA]
    for statement in DDL:
        out.append(" ".join(statement.replace("REAL", "DOUBLE PRECISION").replace("INTEGER", "BIGINT").split()))
    out.append("INSERT INTO provider_claim_schema(id,version) VALUES(1,%d) ON CONFLICT(id) DO NOTHING" % SCHEMA_VERSION)
    return out


def postgres_rollback_statements() -> list[str]:
    return ["DROP SCHEMA IF EXISTS " + SCHEMA + " CASCADE"]


# ---------------------------------------------------------------- helpers
def _hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def origin_of(url: str) -> str | None:
    parts = urlsplit(str(url or ""))
    if parts.scheme != "https" or not parts.hostname or parts.username or parts.password:
        return None
    host = parts.hostname.lower().rstrip(".")
    return "https://" + host + (f":{parts.port}" if parts.port not in (None, 443) else "")


def shared_origin(origin: str) -> bool:
    """True for a hosting platform's own origin, never for a tenant's subdomain on it."""
    from .provider_budget import SHARED_SUFFIXES
    host = urlsplit(origin).hostname or ""
    return host in SHARED_ORIGINS or host in SHARED_SUFFIXES


def _no_duplicates(pairs):
    out = {}
    for key, value in pairs:
        if key in out:
            raise ValueError("duplicate key")
        out[key] = value
    return out


def a2a_card_url(url: str) -> str:
    """The card to read for an A2A resource: its own URL when it is a card, else the origin's well-known card."""
    if url.rstrip("/").endswith((".well-known/agent-card.json", ".well-known/agent.json")):
        return url
    return origin_of(url) + "/.well-known/agent-card.json"


def marker_nonce(value, depth=0) -> list[str]:
    """Nonces written as ``agentvalcon-claim=<nonce>`` anywhere in a string or nested structure."""
    if depth > 6:
        return []
    if isinstance(value, str):
        return MARKER.findall(value)
    if isinstance(value, dict):
        return [n for v in value.values() for n in marker_nonce(v, depth + 1)]
    if isinstance(value, list):
        return [n for v in value[:50] for n in marker_nonce(v, depth + 1)]
    return []


# ---------------------------------------------------------------- service
class ProviderSelfClaims:
    def __init__(self, db, resources, *, http=None, clock=time.time, reserve=None, reports_dir="exports/pearls/reports",
                 retest_file="exports/pearls/retest-queue.json", public_check=None,
                 recommendations_file=RECOMMENDATIONS):
        """``resources(rid)`` returns the catalog row (the application store's registered lookup); ``reserve(url)``
        asks the shared outside-call ledger; ``http`` is a client from broker.discovery.public_client."""
        self.db, self.resources, self.clock = db, resources, clock
        self._http = http
        self._reserve = reserve
        self.reports_dir, self.retest_file = Path(reports_dir), Path(retest_file)
        self.recommendations_file = Path(recommendations_file)
        self._public_check = public_check

    # -- plumbing
    def available(self) -> bool:
        try:
            return bool(self.db.ready())
        except Exception:
            return False

    def _need(self):
        if not self.available():
            raise ClaimError("provider_claims_not_available", 409)

    def http(self):
        if self._http is None:
            from .broker.discovery import public_client
            self._http = public_client(timeout=TIMEOUT_S, headers={"user-agent": USER_AGENT})
        return self._http

    def reserve(self, url: str, n: int = 1) -> bool:
        if self._reserve is not None:
            return bool(self._reserve(url, n))
        from .provider_budget import reserve
        ok, _why = reserve(url, BUDGET_SYSTEM, n=n)
        return ok

    def public(self, url: str) -> bool:
        if self._public_check is not None:
            return bool(self._public_check(url))
        from .broker.discovery import DiscoveryError, check_public_url
        try:
            check_public_url(url)
            return True
        except (DiscoveryError, ValueError):
            return False

    def _resource(self, resource_id) -> dict:
        if type(resource_id) is not int or not 0 < resource_id < 2 ** 63:
            raise ClaimError("invalid_resource")
        row = self.resources(resource_id)
        if not row or not row.get("active"):
            raise ClaimError("resource_not_found", 404)
        return dict(row)

    # -- prepare
    def prepare(self, customer_id: str, resource_id: int, method: str) -> dict:
        """A one-use value to publish. No outside request is made here."""
        self._need()
        if method not in ("well_known", "protocol"):
            raise ClaimError("invalid_method")
        resource = self._resource(resource_id)
        origin = origin_of(resource.get("url"))
        if origin is None:
            raise ClaimError("resource_not_public_https")
        if method == "well_known" and shared_origin(origin):
            raise ClaimError("shared_host_use_protocol")
        if method == "protocol" and resource.get("kind") not in ("mcp", "a2a"):
            raise ClaimError("protocol_needs_mcp_or_a2a")
        scope = origin if method == "well_known" else f"resource:{resource_id}"
        now = self.clock()
        nonce = secrets.token_urlsafe(32)
        claim_id = "pc_" + secrets.token_urlsafe(12)
        with self.db.tx() as db:
            db.run("claims_expire_pending", (now,))
            live = db.one("claim_live_for_scope", (customer_id, scope))
            if live and live["status"] == "verified":
                raise ClaimError("already_verified", 409)
            if live:  # a fresh value replaces an unused one
                db.run("claim_transition", ("expired", None, live["id"], live["revision"], live["status"]))
            elif (db.one("claims_live_count", (customer_id,)) or {}).get("n", 0) >= MAX_LIVE_CLAIMS:
                raise ClaimError("too_many_claims", 429)
            db.run("claim_insert", (claim_id, customer_id, method, origin,
                                    resource_id if method == "protocol" else None, scope, _hash(nonce), now,
                                    now + PENDING_S))
        return {"claim_id": claim_id, "method": method, "origin": origin, "expires": now + PENDING_S,
                "nonce": nonce, "instructions": self.instructions(method, claim_id, nonce, resource)}

    @staticmethod
    def instructions(method, claim_id, nonce, resource) -> dict:
        if method == "well_known":
            return {"publish_at": origin_of(resource["url"]) + WELL_KNOWN,
                    "content": {"profile": PROFILE, "claim": claim_id, "nonce": nonce},
                    "notes": "Serve exactly this JSON with HTTP 200, no redirect, at most 4 KiB."}
        if resource.get("kind") == "mcp":
            return {"publish_in": "the MCP initialize result (instructions or _meta)",
                    "text": "agentvalcon-claim=" + nonce,
                    "notes": "Do not put it in a tool description: tool descriptions are stored and shown publicly."}
        return {"publish_in": "the A2A agent card, capabilities.extensions",
                "content": {"uri": A2A_EXTENSION, "params": {"nonce": nonce}}}

    # -- verify
    def verify(self, customer_id: str, claim_id: str) -> dict:
        """One outside request, started by the provider. A failure leaves the claim pending (press again later)."""
        self._need()
        now = self.clock()
        with self.db.tx() as db:
            claim = db.one("claim_get", (claim_id, customer_id))
            if not claim:
                raise ClaimError("claim_not_found", 404)
            if claim["status"] != "pending" or claim["expires"] <= now:
                raise ClaimError("claim_not_pending", 409)
            if (db.one("checks_customer_since", (customer_id, now - 86400)) or {}).get("n", 0) >= MAX_CHECKS_A_DAY:
                raise ClaimError("too_many_checks", 429)
            last = (db.one("checks_origin_last", (claim["origin"],)) or {}).get("at")
            if last is not None and now - float(last) < ORIGIN_GAP_S:
                raise ClaimError("origin_checked_recently", 429)
            if db.run("claim_transition", ("checking", None, claim_id, claim["revision"], "pending")) != 1:
                raise ClaimError("claim_changed", 409)
        outcome, status_code, ms = self._check(claim)   # no database transaction is held during the request
        done = self.clock()
        with self.db.tx() as db:
            db.run("check_insert", (claim_id, customer_id, claim["origin"], done, "user", outcome, status_code, ms))
            if outcome == "verified":
                db.run("claim_verified", (done, done + VALID_S, done + VALID_S - RECHECK_BEFORE_S, claim_id,
                                          claim["revision"] + 1))
            else:
                db.run("claim_transition", ("pending", outcome, claim_id, claim["revision"] + 1, "checking"))
        return {"claim_id": claim_id, "status": "verified" if outcome == "verified" else "pending", "outcome": outcome}

    def _check(self, claim) -> tuple[str, int | None, int]:
        """(outcome, HTTP status, ms). Outcome 'verified' or a failure code; nothing else is kept."""
        started = time.monotonic()
        try:
            if claim["method"] == "well_known":
                result = self._check_well_known(claim)
            else:
                resource = self._resource(int(claim["resource_id"]))
                if origin_of(resource.get("url")) != claim["origin"]:
                    result = ("resource_moved", None)
                elif resource.get("kind") == "mcp":
                    result = self._check_mcp(claim, resource["url"])
                else:
                    result = self._check_a2a(claim, resource["url"])
        except ClaimError as exc:
            result = (exc.code, None)
        except Exception:
            result = ("request_failed", None)
        return result[0], result[1], int((time.monotonic() - started) * 1000)

    def _get(self, url, *, method="GET", body=None, headers=None, calls=1):
        if not self.public(url):
            raise ClaimError("not_public_address")
        if not self.reserve(url, calls):
            raise ClaimError("call_budget_refused")
        sent = {"accept": "application/json", "user-agent": USER_AGENT, **(headers or {})}
        with self.http().stream(method, url, json=body, headers=sent, timeout=TIMEOUT_S) as resp:
            raw = b""
            for chunk in resp.iter_bytes():
                raw += chunk
                if len(raw) > RESPONSE_LIMIT:
                    raise ClaimError("response_too_large")
            return resp, raw

    def _matches(self, claim, nonce) -> bool:
        return isinstance(nonce, str) and secrets.compare_digest(_hash(nonce), claim["nonce_hash"])

    def _check_well_known(self, claim):
        resp, raw = self._get(claim["origin"] + WELL_KNOWN)
        if resp.status_code != 200:
            return "http_status", resp.status_code
        try:
            body = json.loads(raw.decode("utf-8"), object_pairs_hook=_no_duplicates)
        except (ValueError, UnicodeDecodeError):
            return "invalid_body", resp.status_code
        if not isinstance(body, dict) or set(body) != {"profile", "claim", "nonce"}:
            return "invalid_body", resp.status_code
        if body["profile"] != PROFILE or body["claim"] != claim["id"] or not self._matches(claim, body["nonce"]):
            return "value_mismatch", resp.status_code
        return "verified", resp.status_code

    def _check_mcp(self, claim, url):
        init = {"jsonrpc": "2.0", "id": 1, "method": "initialize",
                "params": {"protocolVersion": "2025-06-18", "capabilities": {},
                           "clientInfo": {"name": "AgentValCon-claim-check", "version": "1.0"}}}
        resp, raw = self._get(url, method="POST", body=init, calls=1,
                              headers={"accept": "application/json, text/event-stream"})
        if resp.status_code != 200:
            return "http_status", resp.status_code
        text = raw.decode("utf-8", "replace")
        payloads = [line[5:].strip() for line in text.splitlines() if line.startswith("data:")] or [text]
        result = None
        for payload in payloads:
            try:
                data = json.loads(payload)
            except ValueError:
                continue
            if isinstance(data, dict) and isinstance(data.get("result"), dict):
                result = data["result"]
                break
        if result is None:
            return "invalid_body", resp.status_code
        found = marker_nonce(result.get("instructions")) + marker_nonce(result.get("_meta"))
        return ("verified" if any(self._matches(claim, n) for n in found) else "value_mismatch"), resp.status_code

    def _check_a2a(self, claim, url):
        resp, raw = self._get(a2a_card_url(url))
        if resp.status_code != 200:
            return "http_status", resp.status_code
        try:
            card = json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return "invalid_body", resp.status_code
        extensions = ((card.get("capabilities") or {}).get("extensions") or []) if isinstance(card, dict) else []
        for ext in extensions if isinstance(extensions, list) else []:
            if isinstance(ext, dict) and ext.get("uri") == A2A_EXTENSION and \
                    self._matches(claim, (ext.get("params") or {}).get("nonce")):
                return "verified", resp.status_code
        return "value_mismatch", resp.status_code

    # -- withdraw and list
    def withdraw(self, customer_id: str, claim_id: str) -> dict:
        self._need()
        with self.db.tx() as db:
            claim = db.one("claim_get", (claim_id, customer_id))
            if not claim:
                raise ClaimError("claim_not_found", 404)
            if claim["status"] not in LIVE or claim["status"] == "checking":
                raise ClaimError("claim_not_withdrawable", 409)
            if db.run("claim_transition", ("withdrawn", None, claim_id, claim["revision"], claim["status"])) != 1:
                raise ClaimError("claim_changed", 409)
        return {"claim_id": claim_id, "status": "withdrawn"}

    def claims(self, customer_id: str) -> dict:
        if not self.available():
            return {"available": False, "items": []}
        return {"available": True, "items": self.db.all("claims_for_customer", (customer_id,))}

    def covering_claim(self, customer_id: str, resource: dict) -> dict | None:
        """The customer's verified claim that covers this resource now (origin match is computed on every read, so a
        resource whose URL moved off the origin drops out at once)."""
        origin = origin_of(resource.get("url"))
        for claim in self.db.all("claims_verified_for_customer", (customer_id, self.clock())):
            if claim["method"] == "well_known" and claim["origin"] == origin:
                return claim
            if claim["method"] == "protocol" and claim["resource_id"] == resource["id"] and claim["origin"] == origin:
                return claim
        return None

    # -- benefits (read only)
    def benefits(self, customer_id: str, resource_id: int) -> dict:
        self._need()
        resource = self._resource(resource_id)
        claim = self.covering_claim(customer_id, resource)
        if claim is None:
            raise ClaimError("not_verified_for_resource", 403)
        trial = None
        try:
            info = json.loads(resource.get("trial_info") or "null")
            if isinstance(info, dict):
                trial = {k: info.get(k) for k in ("tool", "at", "ok", "error", "latency_ms") if k in info}
        except ValueError:
            trial = None
        return {"resource_id": resource_id, "claim_id": claim["id"], "claim_expires": claim["expires"],
                "health": {k: resource.get(k) for k in ("health_status", "last_check_at", "last_ok_at",
                                                        "last_status_code", "last_error", "consecutive_failures")},
                "capability_error": resource.get("cap_error"), "last_trial": trial,
                "test_reports": self.test_reports(resource_id), "retest_queue": self.retest_position(resource_id),
                "corrections": self.with_review(self.db.all("corrections_for_resource", (customer_id, resource_id))),
                "note": "Read only: grades, ranks and test results are never changed by a provider claim."}

    def test_reports(self, resource_id: int, limit: int = 10) -> list[dict]:
        folder = self.reports_dir / str(resource_id)
        files = sorted(folder.glob("*/*.json"), key=lambda p: p.name, reverse=True)[:limit] if folder.is_dir() else []
        out = []
        for path in files:
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            quality = data.get("quality") or {}
            out.append({"role": path.parent.name, "file": path.name, "outcome": data.get("outcome"),
                        "reason": data.get("reason"), "score": quality.get("score"),
                        "evaluator_version": data.get("evaluator_version"), "tested": data.get("tested")})
        return out

    def retest_position(self, resource_id: int) -> dict:
        """Position in the day's retest queue written by the report batch (never computed on a request; PM decision 4:
        position only, and no way to move up by paying)."""
        try:
            data = json.loads(self.retest_file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {"available": False}
        items = data.get("items") if isinstance(data, dict) else None
        if not isinstance(items, list):
            return {"available": False}
        positions = [i + 1 for i, item in enumerate(items) if isinstance(item, dict) and item.get("id") == resource_id]
        return {"available": True, "as_of": data.get("generated"), "queued": bool(positions),
                "position": positions[0] if positions else None, "of": len(items)}

    # -- corrections (reviewed by the agent team within 48 hours, PM decision 5; never applied automatically)
    def request_correction(self, customer_id: str, resource_id: int, field: str, proposed: str,
                           evidence_url: str | None = None) -> dict:
        self._need()
        resource = self._resource(resource_id)
        claim = self.covering_claim(customer_id, resource)
        if claim is None:
            raise ClaimError("not_verified_for_resource", 403)
        if field not in FIELDS:
            raise ClaimError("invalid_field")
        proposed = " ".join(str(proposed or "").split())
        if not 1 <= len(proposed) <= 1000:
            raise ClaimError("invalid_text")
        if evidence_url is not None and (not isinstance(evidence_url, str) or len(evidence_url) > 2000
                                         or origin_of(evidence_url) is None):
            raise ClaimError("invalid_evidence_url")
        request_id = "cr_" + secrets.token_urlsafe(12)
        with self.db.tx() as db:
            if (db.one("corrections_open_count", (customer_id,)) or {}).get("n", 0) >= MAX_OPEN_CORRECTIONS:
                raise ClaimError("too_many_open_corrections", 429)
            db.run("correction_insert", (request_id, claim["id"], customer_id, resource_id, field, proposed,
                                         evidence_url, self.clock()))
        return {"request_id": request_id, "status": "open"}

    def waiting_corrections(self, limit: int = 100) -> list[dict]:
        """For the admin review panel: open and held requests, each with the agent team's recommendation if any."""
        self._need()
        recs = self.recommendations()
        return [dict(row, recommendation=recs.get(row["id"])) for row in self.db.all("corrections_waiting", (limit,))]

    def recommendations(self) -> dict:
        """The agent team's latest recommendation per request (PM decision 11-15 11:2x). The file is outside git and
        outside the database; it is only ever read here and shown, never applied: a staff member records the decision
        in the admin panel."""
        out = {}
        try:
            lines = self.recommendations_file.read_text(encoding="utf-8").splitlines()
        except OSError:
            return out
        for raw in lines:
            try:
                row = json.loads(raw)
            except ValueError:
                continue
            if isinstance(row, dict) and isinstance(row.get("request_id"), str) and row.get("recommendation") in \
                    ("applied", "declined", "held"):
                out[row["request_id"]] = {k: row.get(k) for k in ("recommendation", "reason", "at", "by")}
        return out

    def with_review(self, rows: list[dict]) -> list[dict]:
        """The requester sees 'waiting', 'recommendation_ready' (reviewed within 48 h, the record not yet made) or
        'decided'; never the recommendation itself before a staff member records the decision."""
        recs = self.recommendations()
        out = []
        for row in rows:
            review = "decided" if row.get("status") in ("applied", "declined") else \
                ("recommendation_ready" if row.get("id") in recs else "waiting")
            out.append(dict(row, review=review))
        return out

    def decide_correction(self, request_id: str, status: str, by: str, note: str = "") -> bool:
        self._need()
        if status not in ("applied", "declined", "held"):
            raise ClaimError("invalid_decision")
        with self.db.tx() as db:
            return db.run("correction_decide", (status, self.clock(), by[:80], note[:500], request_id)) == 1

    # -- recheck (jobs)
    def recheck_due(self, limit: int = 20) -> dict:
        """Verified claims near expiry: one request each. Success extends 30 days; a failure retries after 24 h;
        LAPSE_AFTER failures in a row lapse the claim (benefits close, records stay)."""
        if not self.available():
            return {"available": False}
        now = self.clock()
        with self.db.tx() as db:
            db.run("claims_expire_pending", (now,))
        counts = {"verified": 0, "retry": 0, "lapsed": 0}
        for claim in self.db.all("claims_due", (now, limit)):
            outcome, status_code, ms = self._check(claim)
            done = self.clock()
            with self.db.tx() as db:
                current = db.one("claim_get_any", (claim["id"],))
                if not current or current["revision"] != claim["revision"] or current["status"] != "verified":
                    continue
                db.run("check_insert", (claim["id"], claim["customer_id"], claim["origin"], done, "recheck", outcome,
                                        status_code, ms))
                if outcome == "verified":
                    db.run("claim_verified", (done, done + VALID_S, done + VALID_S - RECHECK_BEFORE_S, claim["id"],
                                              claim["revision"]))
                    counts["verified"] += 1
                else:
                    fails = int(current["fail_count"] or 0) + 1
                    state = "lapsed" if fails >= LAPSE_AFTER else "verified"
                    db.run("claim_recheck_failed", (state, fails, done + RETRY_S, outcome, claim["id"],
                                                    claim["revision"]))
                    counts["lapsed" if state == "lapsed" else "retry"] += 1
        return {"available": True, **counts}


def main(argv=None) -> int:
    """python -m agent_market.provider_self_claims --write-sql-registry   (after changing SQL; reviewed in git)"""
    import argparse
    parser = argparse.ArgumentParser(description="Write the claims schema's registered SQL digests.")
    parser.add_argument("--write-sql-registry", action="store_true", required=True)
    parser.parse_args(argv)
    SQL_REGISTRY.write_text(json.dumps({"profile": "provider-claims-sql-v1", "statements": sql_digests()},
                                       indent=1, sort_keys=True) + "\n", encoding="utf-8")
    print(len(SQL), "statements")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
