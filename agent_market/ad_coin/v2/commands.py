"""Database-only command idempotency and durable inbox/outbox fencing."""

from dataclasses import dataclass
import json
from uuid import uuid4

from .budgets import millis
from .contracts import ContractError, ParsedRequest, canonical_bytes, digest
from .identity import Principal, authorize
from .ledger import business_key, identifier


def _snapshot(value):
    encoded = canonical_bytes(value)
    if len(encoded) > 32768:
        raise ContractError("command_snapshot_too_large", 413)
    return encoded.decode("utf-8")


@dataclass(frozen=True)
class CommandResult:
    operation_id: str
    result_json: str
    replayed: bool

    @property
    def value(self):
        return json.loads(self.result_json)


class Commands:
    def __init__(self, store):
        self.store = store

    def run(self, principal_id, method, route, key, request_digest, action):
        """Only database commands belong in action; external effects go through the outbox."""
        principal_id, key = identifier(principal_id), business_key(key)
        if (
            method not in ("POST", "PUT", "PATCH", "DELETE")
            or type(route) is not str
            or not route.startswith("/")
            or len(route) > 240
        ):
            raise ContractError("invalid_command_scope")
        if (
            not 16 <= len(key) <= 128
            or any(not 33 <= ord(c) <= 126 for c in key)
            or type(request_digest) is not str
            or len(request_digest) != 64
            or any(c not in "0123456789abcdef" for c in request_digest)
        ):
            raise ContractError("invalid_command_digest")
        scope = digest(
            {
                "environment": "model",
                "principal": principal_id,
                "method": method,
                "route": route,
                "key": key,
            }
        )
        with self.store.atomic():
            self.store.lock("0:idempotency:" + scope)
            old = self.store.one("idem_get", (scope,))
            if old:
                if old["request_digest"] != request_digest or old["state"] != "done":
                    raise ContractError("idempotency_conflict", 409)
                return CommandResult(old["operation_id"], old["result_json"], True)
            operation_id = str(uuid4())
            self.store.execute("idem_insert", (scope, request_digest, operation_id))
            result = _snapshot(action(operation_id))
            self.store.execute("idem_finish", (result, scope))
            return CommandResult(operation_id, result, False)


@dataclass(frozen=True)
class Lease:
    id: str
    worker_id: str
    generation: int
    payload_json: str

    @property
    def payload(self):
        return json.loads(self.payload_json)


class Outbox:
    def __init__(self, store):
        self.store = store

    def enqueue(self, logical_key, payload, *, available_ms):
        logical_key, available_ms = business_key(logical_key), millis(available_ms)
        encoded, payload_hash = _snapshot(payload), digest(payload)
        with self.store.atomic():
            self.store.lock("1:outbox:" + digest(logical_key))
            old = self.store.one("outbox_get", (logical_key,))
            if old:
                if (
                    old["payload_hash"] != payload_hash
                    or old["available_ms"] != available_ms
                ):
                    raise ContractError("outbox_event_conflict", 409)
                return old["id"]
            event_id = str(uuid4())
            self.store.execute(
                "outbox_insert",
                (event_id, logical_key, payload_hash, encoded, available_ms),
            )
            return event_id

    def claim(self, worker_id, *, now_ms, lease_ms=15000, limit=50):
        worker_id, now_ms = identifier(worker_id), millis(now_ms)
        if (
            type(limit) is not int
            or not 1 <= limit <= 50
            or type(lease_ms) is not int
            or not 1 <= lease_ms <= 60000
        ):
            raise ContractError("invalid_lease_limits")
        millis(now_ms + lease_ms)
        claimed = []
        with self.store.atomic():
            rows = self.store.all("outbox_due", (now_ms, now_ms, limit), locked=True)
            for row in rows:
                updated = self.store.execute(
                    "outbox_claim",
                    (worker_id, now_ms + lease_ms, row["id"], row["generation"]),
                )
                if updated.rowcount == 1:
                    claimed.append(
                        Lease(
                            row["id"],
                            worker_id,
                            row["generation"] + 1,
                            row["payload_json"],
                        )
                    )
        return tuple(claimed)

    def complete(self, lease, *, now_ms):
        if not isinstance(lease, Lease):
            raise ContractError("invalid_lease")
        with self.store.atomic():
            row = self.store.execute(
                "outbox_finish",
                (lease.id, lease.worker_id, lease.generation, millis(now_ms)),
            )
            if row.rowcount != 1:
                raise ContractError("stale_worker_lease", 409)

    def check_lease(self, lease, *, now_ms):
        self.store._connection()
        if not isinstance(lease, Lease):
            raise ContractError("invalid_lease")
        row = self.store.one("outbox_lease_locked", (lease.id,))
        if (
            not row
            or row["state"] != "leased"
            or row["lease_owner"] != lease.worker_id
            or row["generation"] != lease.generation
            or row["lease_until_ms"] <= millis(now_ms)
        ):
            raise ContractError("stale_worker_lease", 409)

    def renew(self, lease, *, now_ms, lease_ms=15000):
        if (
            not isinstance(lease, Lease)
            or type(lease_ms) is not int
            or not 1 <= lease_ms <= 60000
        ):
            raise ContractError("invalid_lease")
        now_ms = millis(now_ms)
        end = millis(now_ms + lease_ms)
        with self.store.atomic():
            row = self.store.execute(
                "outbox_renew",
                (end, lease.id, lease.worker_id, lease.generation, now_ms),
            )
            if row.rowcount != 1:
                raise ContractError("stale_worker_lease", 409)


class Inbox:
    def __init__(self, store):
        self.store = store

    def run(self, source, audience, event_id, payload, action):
        source, audience, event_id = map(business_key, (source, audience, event_id))
        fingerprint = digest(payload)
        encoded = _snapshot(payload)
        with self.store.atomic():
            self.store.lock("0:inbox:" + digest([source, audience, event_id]))
            old = self.store.one("inbox_get", (source, audience, event_id))
            if old:
                if old["payload_hash"] != fingerprint:
                    raise ContractError("inbox_event_conflict", 409)
                return False
            self.store.execute(
                "inbox_insert", (source, audience, event_id, fingerprint, encoded)
            )
            action()
            return True


class AuthorityGuards:
    def __init__(self, store):
        self.store = store

    def provision(self, principal_id):
        principal_id = identifier(principal_id)
        with self.store.atomic():
            self.store.lock("0:authority:" + principal_id)
            self.store.execute("guard_insert", (principal_id,))

    def current(self, principal_id):
        principal_id = identifier(principal_id)
        self.store.lock("0:authority:" + principal_id)
        row = self.store.one("guard_get", (principal_id,), locked=True)
        if not row or row["status"] != "active":
            raise ContractError("authority_revoked", 403)
        return row["epoch"]

    def revoke(self, principal_id, expected_epoch):
        principal_id = identifier(principal_id)
        if type(expected_epoch) is not int or expected_epoch < 1:
            raise ContractError("invalid_authority_epoch")
        with self.store.atomic():
            self.store.lock("0:authority:" + principal_id)
            changed = self.store.execute("guard_revoke", (principal_id, expected_epoch))
            if changed.rowcount != 1:
                raise ContractError("authority_epoch_conflict", 409)


class AuthorizedCommands:
    """Recheck authority before every command or replay, within the same write transaction.

    The future transport must construct Principal from verified credentials. load_scope
    reads ownership from stored objects, not request claims, and must not take write
    locks. Business state/If-Match/fresh-action checks still belong inside action.
    """

    def __init__(self, store, contract):
        self.store, self.contract = store, contract
        self.guards, self.commands = AuthorityGuards(store), Commands(store)

    def run(self, principal, request, key, load_scope, action):
        if not isinstance(principal, Principal) or not isinstance(
            request, ParsedRequest
        ):
            raise ContractError("invalid_command_authority", 403)
        method, route_template, _ = self.contract._operations[request.operation_id]
        with self.store.atomic():
            epoch = self.guards.current(str(principal.id))
            authorize(
                self.contract,
                request.operation_id,
                principal,
                current_epoch=epoch,
                **load_scope(),
            )
            return self.commands.run(
                str(principal.id),
                method,
                route_template,
                key,
                request.idempotency_digest,
                action,
            )
