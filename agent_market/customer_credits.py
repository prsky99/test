"""Nonmonetary customer credits, explicit enrollment and atomic workflow entitlements."""

import hashlib
import json
import re
import secrets
import time

from .customer_identity import CustomerActor
from .workspace_access import (
    WorkspaceDenied,
    WorkspaceConflict,
    WorkspaceInvalid,
    _canonical,
    _rows,
    _identity,
)
from .private_artifact_keys import ArtifactSigner

WELCOME_CREDITS = 100
VERSION = "workspace-free-2026-11-10-v3"
# Preserve verified enrollment under the previous one-time grant policy.
LEGACY_ACCEPTANCES = frozenset({
    ("workspace-free-2026-10-20-v1", "c42935fbe9c8e31e48654c25c27deb4f0bd7a9ecf0bebb9bb464ed39386a449d"),
    # v2 (2026-10-24) before the points exchange sentence was added; still a valid enrollment.
    ("workspace-free-2026-10-24-v2", "29ef63d133d0641d8f5d9b0b2e12c59c7ff4a95c19b1f03a52fd69a0e4578594"),
})
TERMS = f"""The workspace is intended for adults aged 18 or over who can legally accept these terms. Free workspace enrollment gives this signed-in account {WELCOME_CREDITS} credits once, not monthly. Paid plans, payments, automatic billing, paid conversion and credit top-ups are coming soon. Enrollment currently requires no card and creates no charges. Future paid features will require separate terms and explicit authorization before any charge. One credit saves a new workflow and includes downloads of that workflow revision. Changes saved before its first download share that credit; saving a changed workflow after download uses one new credit. Repeated downloads of the same saved revision do not use credits. AI suggestions, rejected saves and failed transactions do not use credits. Testing and releasing remain subject to service safety limits and successful verification; a credit does not guarantee an agent result or availability. Credits have no cash value, are not transferable and currently have no scheduled expiry. Points earned through activity can be exchanged for credits at 10 points for 1 credit, up to 10 credits at a time and 50 credits a month; exchanged credits work like other credits and cannot be turned back into points. Closing enrollment stops new saves and downloads, without erasing retained workflows or restoring previously used credits. Rejoining does not repeat the welcome grant. You may request correction of an erroneous deduction at contact@agentconcierge.biz. Material changes require a new notice and cannot authorize future payments. Your mandatory consumer rights remain unaffected."""
PRIVACY = """Account identifiers, sign-in sessions, saved workflows, agreement records and credit history are used to provide and secure the workspace. AI generation shares only your separately authorized public objective and approved capability references with the suggestion service. Do not submit personal, confidential or sensitive information. Each agent test has its own input-sharing review. Enrollment does not authorize advertising or model training. You can close enrollment here or delete your account in Your organizations. Workspace credit and agreement records are kept while the account exists, then removed within 90 days after account deletion. Other security records follow the service Privacy notice; contact contact@agentconcierge.biz for access, correction, deletion or questions. Read the service Privacy notice for storage, retention and your rights."""
DIGEST = hashlib.sha256((VERSION + "\n" + TERMS + "\n" + PRIVACY).encode()).hexdigest()
SCHEMA = (
    "CREATE TABLE IF NOT EXISTS customer_credit_restore_blocks(customer_id TEXT PRIMARY KEY)",
    """CREATE TABLE IF NOT EXISTS customer_credit_accounts(customer_id TEXT PRIMARY KEY,status TEXT NOT NULL,balance INTEGER NOT NULL CHECK(balance>=0),revision INTEGER NOT NULL,payload TEXT NOT NULL,signature TEXT NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS customer_credit_events(id INTEGER PRIMARY KEY,customer_id TEXT NOT NULL,event_key TEXT NOT NULL,delta INTEGER NOT NULL,balance INTEGER NOT NULL,created REAL NOT NULL,payload TEXT NOT NULL,signature TEXT NOT NULL,UNIQUE(customer_id,event_key))""",
    """CREATE TABLE IF NOT EXISTS customer_credit_acceptances(id INTEGER PRIMARY KEY,customer_id TEXT NOT NULL,version TEXT NOT NULL,digest TEXT NOT NULL,session_ref TEXT NOT NULL,created REAL NOT NULL,payload TEXT NOT NULL,signature TEXT NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS customer_credit_bundles(id TEXT PRIMARY KEY,customer_id TEXT NOT NULL,workspace_id TEXT NOT NULL,downloaded INTEGER NOT NULL DEFAULT 0,signature TEXT NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS customer_credit_artifacts(workspace_id TEXT NOT NULL,artifact_id TEXT NOT NULL,revision INTEGER NOT NULL,bundle_id TEXT NOT NULL,signature TEXT NOT NULL,PRIMARY KEY(workspace_id,artifact_id,revision))""",
    "CREATE INDEX IF NOT EXISTS customer_credit_events_customer ON customer_credit_events(customer_id,id)",
)


POINTS_EXCHANGE_PREFIX = "points:"


class CreditRequired(WorkspaceDenied):
    """A current enrollment or available credit is required."""


class CustomerCredits:
    def __init__(self, identity):
        self.identity, self.store = identity, identity.store
        self.signer = ArtifactSigner(identity.key, "customer-workspace-credits-v1")
        with identity.tx() as db:
            for sql in SCHEMA:
                db.execute(sql)

    def _customer(self, db, actor):
        if getattr(actor, "token_ref", None) is not None:
            raise WorkspaceDenied()
        _identity(actor.customer_id, "cu")
        self.identity._session(db, actor.session_ref, actor.customer_id)
        return actor.customer_id

    def _account(self, db, customer):
        rows = _rows(
            db,
            "SELECT * FROM customer_credit_accounts WHERE customer_id=?",
            (customer,),
        )
        if not rows:
            return None
        row = rows[0]
        value = json.loads(row["payload"])
        if not self.signer.verify(value, row["signature"]) or any(
            value[k] != row[k] for k in ("customer_id", "status", "balance", "revision")
        ):
            raise WorkspaceConflict()
        aggregate = db.execute(
            "SELECT COUNT(*),COALESCE(SUM(delta),0) FROM customer_credit_events WHERE customer_id=?",
            (customer,),
        ).fetchone()
        if aggregate[0] != value["revision"] or aggregate[1] != value["balance"]:
            raise WorkspaceConflict()
        if db.execute(
            "SELECT 1 FROM customer_credit_restore_blocks WHERE customer_id=?",
            (customer,),
        ).fetchone():
            value = {**value, "status": "review_required"}
        return value

    def _post(
        self, db, customer, key, delta, action, actor_ref, *, status=None, detail=None
    ):
        old = self._account(db, customer)
        replay = _rows(
            db,
            "SELECT * FROM customer_credit_events WHERE customer_id=? AND event_key=?",
            (customer, key),
        )
        command = {
            "delta": delta,
            "action": action,
            "actor_ref": str(actor_ref),
            "status": status,
            "detail": detail,
        }
        if replay:
            event = json.loads(replay[0]["payload"])
            if (
                not self.signer.verify(event, replay[0]["signature"])
                or event["command"] != command
            ):
                raise WorkspaceConflict()
            return old
        balance = (old["balance"] if old else 0) + delta
        if type(delta) is not int or not 0 <= balance <= 1000000000:
            raise CreditRequired()
        value = {
            "customer_id": customer,
            "status": status or (old["status"] if old else "active"),
            "balance": balance,
            "revision": (old["revision"] if old else 0) + 1,
            "updated": time.time(),
        }
        event = {
            "customer_id": customer,
            "event_key": key,
            "delta": delta,
            "balance": balance,
            "created": value["updated"],
            "command": command,
        }
        db.execute(
            "INSERT INTO customer_credit_events(customer_id,event_key,delta,balance,created,payload,signature) VALUES(?,?,?,?,?,?,?)",
            (
                customer,
                key,
                delta,
                balance,
                event["created"],
                _canonical(event),
                self.signer.sign(event),
            ),
        )
        db.execute(
            "INSERT INTO customer_credit_accounts VALUES(?,?,?,?,?,?) ON CONFLICT(customer_id) DO UPDATE SET status=excluded.status,balance=excluded.balance,revision=excluded.revision,payload=excluded.payload,signature=excluded.signature",
            (
                customer,
                value["status"],
                balance,
                value["revision"],
                _canonical(value),
                self.signer.sign(value),
            ),
        )
        from .workspace_admin_events import emit
        emit(self.store, db, 'credit.' + action, customer=customer,
             event_key='credit:' + customer + ':' + hashlib.sha256(key.encode()).hexdigest(),
             outcome='succeeded')
        return value

    def prune(self):
        """Bounded removal of this feature's evidence after account deletion."""
        with self.identity.tx() as db:
            if not db.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='customer_account_deletions'"
            ).fetchone():
                return 0
            rows = db.execute(
                "SELECT d.customer_id FROM customer_account_deletions d JOIN customer_credit_accounts c ON c.customer_id=d.customer_id JOIN customer_identities i ON i.id=d.customer_id WHERE i.active=0 AND d.requested<? LIMIT 25",
                (time.time() - 90 * 86400,),
            ).fetchall()
            for (customer,) in rows:
                db.execute(
                    "DELETE FROM customer_credit_artifacts WHERE bundle_id IN (SELECT id FROM customer_credit_bundles WHERE customer_id=?)",
                    (customer,),
                )
                db.execute(
                    "DELETE FROM customer_credit_bundles WHERE customer_id=?",
                    (customer,),
                )
                db.execute(
                    "DELETE FROM customer_credit_acceptances WHERE customer_id=?",
                    (customer,),
                )
                db.execute(
                    "DELETE FROM customer_credit_events WHERE customer_id=?",
                    (customer,),
                )
                db.execute(
                    "DELETE FROM customer_credit_accounts WHERE customer_id=?",
                    (customer,),
                )
            return len(rows)

    def _accepted(self, db, customer):
        rows = _rows(
            db,
            "SELECT payload,signature FROM customer_credit_acceptances WHERE customer_id=? ORDER BY id DESC LIMIT 1",
            (customer,),
        )
        if not rows:
            return False
        value = json.loads(rows[0]["payload"])
        if not self.signer.verify(value, rows[0]["signature"]):
            raise WorkspaceConflict()
        accepted = (value.get("version"), value.get("digest"))
        return accepted == (VERSION, DIGEST) or accepted in LEGACY_ACCEPTANCES

    def status(self, actor):
        with self.identity.read_tx() as db:
            customer = self._customer(db, actor)
            account = self._account(db, customer)
            events = []
            for row in _rows(
                db,
                "SELECT * FROM customer_credit_events WHERE customer_id=? ORDER BY id DESC LIMIT 100",
                (customer,),
            ):
                event = json.loads(row["payload"])
                if not self.signer.verify(event, row["signature"]):
                    raise WorkspaceConflict()
                events.append(
                    {k: event[k] for k in ("delta", "balance", "created")}
                    | {"action": event["command"]["action"]}
                )
            return {
                "enrolled": bool(
                    account
                    and account["status"] == "active"
                    and self._accepted(db, customer)
                ),
                "status": account["status"] if account else "not_enrolled",
                "balance": account["balance"] if account else 0,
                "revision": account["revision"] if account else 0,
                "plan": "Free",
                "welcome_credits": WELCOME_CREDITS,
                "top_up_enabled": False,
                "paid_plans_enabled": False,
                "version": VERSION,
                "digest": DIGEST,
                "terms": TERMS,
                "privacy": PRIVACY,
                "history": events,
            }

    def enroll(self, body, actor):
        if (
            type(body) is not dict
            or any(
                body.get(k) is not True
                for k in ("terms_accepted", "privacy_acknowledged", "adult_authority")
            )
            or body
            != {
                "version": VERSION,
                "digest": DIGEST,
                "terms_accepted": True,
                "privacy_acknowledged": True,
                "adult_authority": True,
            }
        ):
            raise WorkspaceInvalid()
        with self.identity.tx() as db:
            customer = self._customer(db, actor)
            old = self._account(db, customer)
            if old and old["status"] in ("suspended", "review_required"):
                raise WorkspaceDenied()
            if old and old["status"] == "active" and self._accepted(db, customer):
                return {"enrolled": True, "replayed": True}
            evidence = {
                "customer_id": customer,
                "version": VERSION,
                "digest": DIGEST,
                "session_ref": actor.session_ref,
                "created": time.time(),
                "terms_accepted": True,
                "privacy_acknowledged": True,
                "adult_authority": True,
                "terms_text": TERMS,
                "privacy_text": PRIVACY,
            }
            db.execute(
                "INSERT INTO customer_credit_acceptances(customer_id,version,digest,session_ref,created,payload,signature) VALUES(?,?,?,?,?,?,?)",
                (
                    customer,
                    VERSION,
                    DIGEST,
                    actor.session_ref,
                    evidence["created"],
                    _canonical(evidence),
                    self.signer.sign(evidence),
                ),
            )
            self._post(
                db,
                customer,
                "welcome" if not old else "rejoin:" + str(old["revision"]),
                WELCOME_CREDITS if not old else 0,
                "free_enrollment",
                customer,
                status="active",
                detail={"version": VERSION, "digest": DIGEST},
            )
            return {"enrolled": True, "replayed": False}

    def close(self, body, actor):
        if (
            type(body) is not dict
            or set(body) != {"revision", "confirm"}
            or body["confirm"] != "CLOSE"
            or type(body["revision"]) is not int
        ):
            raise WorkspaceInvalid()
        with self.identity.tx() as db:
            customer = self._customer(db, actor)
            old = self._account(db, customer)
            if (
                not old
                or old["revision"] != body["revision"]
                or old["status"] != "active"
            ):
                raise WorkspaceConflict()
            self._post(
                db,
                customer,
                "close:" + str(old["revision"]),
                0,
                "enrollment_closed",
                customer,
                status="closed",
            )
            return {"enrolled": False}

    def require(self, db, actor):
        customer = self._customer(db, actor)
        account = self._account(db, customer)
        if (
            not account
            or account["status"] != "active"
            or not self._accepted(db, customer)
        ):
            raise CreditRequired()
        return customer, account

    def _scope(self, db, ws, actor, purpose):
        self.identity.authorize(
            db, CustomerActor(actor.customer_id, actor.session_ref), ws, purpose
        )

    def _bundle(self, row):
        value = {k: row[k] for k in ("id", "customer_id", "workspace_id", "downloaded")}
        if not self.signer.verify(value, row["signature"]):
            raise WorkspaceConflict()
        return value

    def quote(self, ws, parent, actor):
        with self.identity.read_tx() as db:
            return self.quote_in_transaction(db, ws, parent, actor)

    def quote_in_transaction(self, db, ws, parent, actor):
        customer, account = self.require(db, actor)
        self._scope(db, ws, actor, "read")
        rows = (
            _rows(
                db,
                """SELECT b.*,a.signature AS mapping_signature,a.artifact_id,a.revision,a.bundle_id FROM customer_credit_artifacts a JOIN customer_credit_bundles b ON b.id=a.bundle_id WHERE a.workspace_id=? AND a.artifact_id=? ORDER BY a.revision DESC LIMIT 1""",
                (ws, parent),
            )
            if parent
            else []
        )
        if rows:
            row = rows[0]
            mapping = {
                k: row[k]
                for k in ("workspace_id", "artifact_id", "revision", "bundle_id")
            }
            if not self.signer.verify(mapping, row["mapping_signature"]):
                raise WorkspaceConflict()
        bundle = self._bundle(rows[0]) if rows else None
        return (
            0
            if bundle and bundle["customer_id"] == customer and not bundle["downloaded"]
            else 1
        )

    def saved(self, db, ws, artifact, revision, actor, parent=None):
        customer, account = self.require(db, actor)
        quoted = self.quote_in_transaction(db, ws, parent, actor)
        self._scope(db, ws, actor, "edit")
        previous = []
        if parent:
            previous = _rows(
                db,
                """SELECT b.* FROM customer_credit_artifacts a JOIN customer_credit_bundles b ON b.id=a.bundle_id WHERE a.workspace_id=? AND a.artifact_id=? ORDER BY a.revision DESC LIMIT 1""",
                (ws, parent),
            )
        reuse = quoted == 0
        if reuse:
            bundle = previous[0]["id"]
        else:
            bundle = "cb_" + secrets.token_hex(16)
            self._post(
                db,
                customer,
                "save:" + artifact + ":" + str(revision),
                -1,
                "workflow_saved",
                customer,
                detail={"workspace": ws, "artifact": artifact, "revision": revision},
            )
            value = {
                "id": bundle,
                "customer_id": customer,
                "workspace_id": ws,
                "downloaded": 0,
            }
            db.execute(
                "INSERT INTO customer_credit_bundles VALUES(?,?,?,0,?)",
                (bundle, customer, ws, self.signer.sign(value)),
            )
        mapping = {
            "workspace_id": ws,
            "artifact_id": artifact,
            "revision": revision,
            "bundle_id": bundle,
        }
        db.execute(
            "INSERT INTO customer_credit_artifacts VALUES(?,?,?,?,?)",
            (ws, artifact, revision, bundle, self.signer.sign(mapping)),
        )

    def downloaded(self, ws, artifact, revision, actor):
        # Called only after a package has been built, before returning its bytes.
        with self.identity.tx() as db:
            self.require(db, actor)
            self._scope(db, ws, actor, "manage")
            rows = _rows(
                db,
                """SELECT b.*,a.signature AS mapping_signature,a.artifact_id,a.revision,a.bundle_id FROM customer_credit_artifacts a JOIN customer_credit_bundles b ON b.id=a.bundle_id WHERE a.workspace_id=? AND a.artifact_id=? AND a.revision=?""",
                (ws, artifact, revision),
            )
            if not rows:
                raise CreditRequired()
            row = rows[0]
            mapping = {
                k: row[k]
                for k in ("workspace_id", "artifact_id", "revision", "bundle_id")
            }
            if not self.signer.verify(mapping, row["mapping_signature"]):
                raise WorkspaceConflict()
            value = self._bundle(row)
            value["downloaded"] = 1
            db.execute(
                "UPDATE customer_credit_bundles SET downloaded=1,signature=? WHERE id=?",
                (self.signer.sign(value), row["id"]),
            )
            from .workspace_admin_events import emit
            emit(self.store, db, 'entitlement.download_marked', customer=actor.customer_id, workspace=ws,
                 object_id=artifact, event_key='package:' + ws + ':' + artifact + ':' + str(revision),
                 outcome='succeeded')

    def exchange_points(self, customer, credits, exchange_id):
        """Grant credits bought with activity points (AI AD Coin). The caller has already moved the
        points on the AD Coin ledger under the same exchange_id; a replay grants nothing twice.

        Only an enrolled, active account receives credits. Caps match the public terms and the AD
        Coin constants: at most MAX_CREDITS_PER_EXCHANGE at a time and MAX_CREDITS_PER_MONTH per
        UTC month.
        """
        from .ad_coin.v2.points import MAX_CREDITS_PER_EXCHANGE, MAX_CREDITS_PER_MONTH
        _identity(customer, "cu")
        if (type(credits) is not int or not 1 <= credits <= MAX_CREDITS_PER_EXCHANGE
                or not re.fullmatch(r"[a-f0-9]{32}", str(exchange_id))):
            raise WorkspaceInvalid()
        key = POINTS_EXCHANGE_PREFIX + exchange_id
        with self.identity.tx() as db:
            old = self._account(db, customer)
            if not old or old["status"] != "active" or not self._accepted(db, customer):
                raise CreditRequired()
            if db.execute("SELECT 1 FROM customer_credit_events WHERE customer_id=? AND event_key=?",
                          (customer, key)).fetchone():
                return self._post(db, customer, key, credits, "points_exchange", "ad_coin",
                                  detail={"exchange_id": exchange_id})
            import datetime
            now = datetime.datetime.now(datetime.timezone.utc)
            month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0).timestamp()
            used = db.execute(
                "SELECT COALESCE(SUM(delta),0) FROM customer_credit_events WHERE customer_id=? "
                "AND event_key LIKE ? AND created>=?",
                (customer, POINTS_EXCHANGE_PREFIX + "%", month_start),
            ).fetchone()[0]
            if used + credits > MAX_CREDITS_PER_MONTH:
                raise WorkspaceConflict()
            return self._post(db, customer, key, credits, "points_exchange", "ad_coin",
                              detail={"exchange_id": exchange_id})

    def admin_list(self, access, actor, q=""):
        if type(q) is not str or len(q) > 80:
            raise WorkspaceInvalid()
        with access._tx(actor) as (db, _):
            rows = _rows(
                db,
                "SELECT customer_id FROM customer_credit_accounts WHERE customer_id LIKE ? ORDER BY customer_id LIMIT 100",
                ("%" + q + "%",),
            )
            return [self._account(db, r["customer_id"]) for r in rows]

    def admin_change(self, access, customer, body, actor):
        with access._tx(actor, write=True, highest=True) as (db, _):
            return self.admin_change_in_transaction(db, customer, body, actor)

    def admin_change_in_transaction(self, db, customer, body, actor):
        """Called only inside an already-authorized highest-staff transaction."""
        _identity(customer, "cu")
        if (
            type(body) is not dict
            or set(body) != {"revision", "delta", "status", "reason", "request_id"}
            or type(body["delta"]) is not int
            or not -1000000 <= body["delta"] <= 1000000
            or type(body["revision"]) is not int
            or body["status"] not in ("active", "suspended", "closed")
            or type(body["reason"]) is not str
            or not 5 <= len(body["reason"]) <= 300
            or not re.fullmatch(r"[a-f0-9]{32}", str(body["request_id"]))
        ):
            raise WorkspaceInvalid()
        old = self._account(db, customer)
        if not old or old["status"] == "review_required":
            raise WorkspaceDenied()  # Staff cannot manufacture customer assent.
        key = "admin:" + body["request_id"]
        if (
            not db.execute(
                "SELECT 1 FROM customer_credit_events WHERE customer_id=? AND event_key=?",
                (customer, key),
            ).fetchone()
            and old["revision"] != body["revision"]
        ):
            raise WorkspaceConflict()
        return self._post(
            db, customer, key, body["delta"], "admin_adjustment", actor.user_id,
            status=body["status"], detail={"reason": body["reason"], "revision": body["revision"]},
        )
