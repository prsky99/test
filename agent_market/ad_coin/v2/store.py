"""Registered-SQL transactions for an explicit PostgreSQL-only model namespace."""

from contextlib import contextmanager
import re
import threading

from ..db import PooledPostgresDatabase
from .contracts import ContractError, MAX_ATOMS, MODEL_ASSET
from .schema import SCHEMA, VERSION, statements
from .sql import SQL

_SIGNED = re.compile(r"-?(?:0|[1-9][0-9]{0,77})\Z")


def signed_atoms(value):
    if type(value) is not str or not _SIGNED.fullmatch(value) or value == "-0":
        raise ContractError("invalid_posting")
    number = int(value)
    if abs(number) > MAX_ATOMS:
        raise ContractError("invalid_posting")
    return number


class ModelStore:
    def __init__(self, database, backend):
        if backend != "postgres":
            raise ContractError("unsupported_backend")
        self.database, self.backend = database, backend
        self._local, self._ready = threading.local(), False

    @classmethod
    def postgres(cls, factory, maximum=6):
        """Every session works in its own schema (SCHEMA), never in the application's public schema.

        The application store refuses to start when the public schema holds triggers other than its
        own (2026-11-10 outage), so v2 tables, functions and triggers live in SCHEMA.
        """
        def scoped():
            connection = factory()
            if connection.autocommit is not True:
                connection.autocommit = True
            connection.execute("SET search_path TO " + SCHEMA)
            return connection

        return cls(
            PooledPostgresDatabase(scoped, maximum=maximum, require_migrated=False),
            "postgres",
        )

    def migrate_model(self):
        """Explicit additive migration. There is no real-value mode or legacy balance import."""
        if getattr(self._local, "connection", None) is not None:
            raise ContractError("migration_requires_separate_transaction", 409)
        self._ready = False
        with self.atomic(require_ready=False):
            self.lock("0:model_schema")
            for sql in statements():
                self._connection().execute(sql)
            self.execute("schema_insert")
            self.execute("schema_upgrade")
            row = self.one("schema_get")
            if dict(row) != {
                "id": 1,
                "version": VERSION,
                "environment": "model",
                "real_value": 0,
            }:
                raise ContractError("model_schema_mismatch", 503)
            self.execute("asset_insert")
        self._ready = True

    def attach(self):
        """Use a schema that an operator already migrated: read-only check, no DDL.

        Production processes never migrate; they attach on first use. A missing or different schema
        (wrong version, real value on) keeps the store closed, so requests answer 503.
        """
        if self._ready:
            return True
        try:
            with self.atomic(require_ready=False):
                row = self.one("schema_get")
        except Exception:
            return False
        if row is not None and dict(row) == {"id": 1, "version": VERSION, "environment": "model", "real_value": 0}:
            self._ready = True
        return self._ready

    @contextmanager
    def atomic(self, *, require_ready=True):
        if require_ready and not self._ready and not self.attach():
            raise ContractError("model_migration_required", 503)
        old = getattr(self._local, "connection", None)
        with self.database.transaction() as connection:
            self._local.connection = connection
            try:
                yield self
                if old is None and self._ready:
                    if self.one("pending_journal") or self.one("pending_idem"):
                        raise ContractError("incomplete_model_transaction", 409)
            finally:
                self._local.connection = old

    def _connection(self):
        connection = getattr(self._local, "connection", None)
        if connection is None:
            raise RuntimeError("write_transaction_required")
        return connection

    def execute(self, name, args=()):
        return self._connection().execute(SQL[name], args)

    def one(self, name, args=(), *, locked=False):
        key = name + "_locked" if locked else name
        if locked:
            self._connection()
        row = self.database.one(SQL[key], args)
        return dict(row) if row is not None else None

    def all(self, name, args=(), *, locked=False):
        key = name + "_locked" if locked else name
        if locked:
            self._connection()
        return [dict(row) for row in self.database.all(SQL[key], args)]

    def lock(self, *keys):
        self._connection()
        for key in sorted(set(keys)):
            if type(key) is not str or len(key) > 256:
                raise ContractError("invalid_lock_key")
            self.database.lock_key("adc2:" + key)

    def require_model(self, asset_id):
        if asset_id != MODEL_ASSET or not self._ready:
            raise ContractError("model_asset_required", 403)

    def close(self):
        self.database.close()
