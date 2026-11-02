"""Rebuildable per-listing capability text for the first Explore word check.

Every admission path requires the task words in the listing's name, description, or
an advertised tool's name or description. This text holds exactly those, so the first
word check need not scan full tool schemas and usage notes. A stored text is used only
while its source hash and derivation version match the current row; otherwise the
caller checks the full row text as before. Provision explicitly on a reviewed Store.

Version 2 adds the candidate ranking text, keyed by an MD5 the database computes over
the ranking columns (so ranking reads need not transfer tool JSON), and each advertised
tool's discovery schema support.
"""
import hashlib
import json
import threading
import time
from collections import OrderedDict

PROFILE = 'agentcon-capability-text-v2'
VERSION = 2  # raise when _advertised_tools or any derivation here changes
MAX_READ_BYTES = 32 * 1024 * 1024  # stored texts of one batch; a few listings carry very long tool lists
RANK_FIELDS = ('kind', 'name', 'description', 'usage_guide', 'usage_tools')
# The same length-framed digest in SQL and Python; length() counts characters, as len() does.
RANK_HASH_SQL = 'md5(' + "||".join(
    f"COALESCE(length(r.{f})::text||':'||r.{f},'-')||'|'" for f in RANK_FIELDS) + ')'
SOURCE_FIELDS = ('kind', 'name', 'description', 'category', 'cap_tool_names', 'usage_tools',
                 'usage_full_tools', 'usage_full_hash', 'usage_guide', 'details')
SEARCHABLE = ("active=1 AND health_status IN ('healthy','reachable') "
              "AND COALESCE(eval_security,'') NOT IN ('quarantine','review')")
# A stored text whose listing left the searchable set (alias t).
LEFT_SEARCHABLE = ('NOT EXISTS (SELECT 1 FROM resources r WHERE r.id=t.resource_id AND r.active=1 '
                   "AND r.health_status IN ('healthy','reachable') "
                   "AND COALESCE(r.eval_security,'') NOT IN ('quarantine','review'))")
PRUNE_LIMIT, PRUNE_BATCH = 2000, 200


def source_hash(resource):
    """Digest of every field the text and the full-text word check read."""
    values = []
    for name in SOURCE_FIELDS:
        value = resource.get(name)
        values.append(value if value is None or type(value) in (str, int, float, bool)
                      else json.dumps(value, sort_keys=True, ensure_ascii=True, default=str))
    return hashlib.sha256(json.dumps(values, ensure_ascii=True).encode()).hexdigest()


def rank_hash(resource):
    text = ''.join((f"{len(v)}:{v}" if isinstance(v, str) else '-') + '|'
                   for v in (resource.get(f) for f in RANK_FIELDS))
    return hashlib.md5(text.encode('utf-8', 'surrogatepass')).hexdigest()


def rank_text(resource):
    """The candidate coverage text exactly as a ranking-column row yields it; None if unstorable."""
    from .concierge.discovery import ranking_text, RANKING_COLUMNS
    value = ranking_text({'id': resource.get('id'), **{key: resource.get(key) for key in RANKING_COLUMNS}})
    return None if '\x00' in value else value


def tool_support(resource):
    """Discovery schema support per advertised MCP tool name; schemas are part of the source hash."""
    if resource.get('kind') != 'mcp':
        return {}
    from .concierge.selection import _advertised_tools
    from .concierge.execution_policy import discovery_schema_supported
    support = {}
    for tool in _advertised_tools(resource):
        name = tool.get('name')
        if isinstance(name, str) and name not in support:
            support[name] = bool(discovery_schema_supported(tool))
    return support


def build(resource):
    """Name, description and every advertised tool's name, id and description."""
    from .concierge.selection import _advertised_tools
    parts = [str(resource.get('name') or ''), str(resource.get('description') or '')]
    for tool in _advertised_tools(resource):
        parts.extend(str(tool.get(key) or '') for key in ('name', 'id', 'description'))
    # PostgreSQL text cannot hold NUL; a space keeps every word boundary the check relies on.
    return ' '.join(parts).lower().replace('_', ' ').replace('\x00', ' ')


def available(store):
    if getattr(store, 'backend', None) != 'postgresql':
        return False
    with store.tx(readonly=True):
        if store._execute("SELECT to_regclass('agentcon_search.capability_text_configuration')").fetchone()[0] is None:
            return False
        rows = store._execute('SELECT profile FROM agentcon_search.capability_text_configuration WHERE id=1').fetchall()
        return len(rows) == 1 and rows[0][0] == PROFILE


def install(store):
    """Create the empty projection; refresh() fills it."""
    with store.tx():
        if store._execute("SELECT to_regclass('agentcon_search.capability_text_configuration')").fetchone()[0] is not None:
            raise ValueError('capability_text_already_provisioned')
        store._execute('CREATE SCHEMA IF NOT EXISTS agentcon_search')
        store._execute('REVOKE ALL ON SCHEMA agentcon_search FROM PUBLIC')
        store._execute('CREATE TABLE agentcon_search.capability_text_configuration(id BIGINT PRIMARY KEY CHECK(id=1),profile TEXT NOT NULL)')
        store._execute('''CREATE TABLE agentcon_search.capability_text(resource_id BIGINT PRIMARY KEY,
            source_hash TEXT NOT NULL,version INTEGER NOT NULL,body TEXT NOT NULL,updated_at DOUBLE PRECISION NOT NULL,
            rank_hash TEXT,rank_text TEXT,tool_support TEXT)''')
        store._execute('INSERT INTO agentcon_search.capability_text_configuration VALUES(1,%s)', (PROFILE,))
    return {'profile': PROFILE}


def migrate(store):
    """Upgrade a version 1 projection in place; its rows become stale and are rewritten."""
    with store.tx():
        rows = store._execute('SELECT profile FROM agentcon_search.capability_text_configuration WHERE id=1').fetchall()
        if len(rows) != 1 or rows[0][0] not in ('agentcon-capability-text-v1', PROFILE):
            raise ValueError('capability_text_profile_unknown')
        store._execute('''ALTER TABLE agentcon_search.capability_text ADD COLUMN IF NOT EXISTS rank_hash TEXT,
            ADD COLUMN IF NOT EXISTS rank_text TEXT,ADD COLUMN IF NOT EXISTS tool_support TEXT''')
        store._execute('UPDATE agentcon_search.capability_text_configuration SET profile=%s WHERE id=1', (PROFILE,))
    return {'profile': PROFILE}


def stored(store, ids, *, texts=True):
    """{resource_id: (source_hash, version, body, tool_support)} for IDS; the caller holds a transaction.

    TEXTS=False reads only the hashes and versions a refresh compares."""
    if not ids:
        return {}
    columns = 'resource_id,source_hash,version,body,tool_support' if texts else 'resource_id,source_hash,version,NULL,NULL'
    rows = store._execute('SELECT ' + columns + ' FROM agentcon_search.capability_text '
                          'WHERE resource_id IN (SELECT value::bigint FROM jsonb_array_elements_text(%s::jsonb))',
                          (json.dumps([int(rid) for rid in ids]),), max_rows=len(ids), max_bytes=MAX_READ_BYTES).fetchall()
    return {row[0]: (row[1], row[2], row[3], row[4]) for row in rows}


_enabled = {'at': -1e9, 'value': False}


def _provisioned(store):
    """Re-check the projection at most every five minutes, inside the caller's transaction."""
    now = time.monotonic()
    if now - _enabled['at'] > 300:
        try:
            found = store._execute("SELECT to_regclass('agentcon_search.capability_text_configuration')").fetchone()[0]
            value = bool(found) and tuple(store._execute(
                'SELECT profile FROM agentcon_search.capability_text_configuration WHERE id=1').fetchone() or ()) == (PROFILE,)
        except Exception:
            value = False
        _enabled.update(at=now, value=bool(value))
    return _enabled['value']


def attach(store, rows):
    """Add _capability_text to rows whose stored text matches their current source exactly.

    The caller holds a read transaction."""
    if not rows or getattr(store, 'backend', None) != 'postgresql' or not _provisioned(store):
        return rows
    try:
        found = stored(store, [row['id'] for row in rows])
    except Exception:
        return rows  # the full-text check remains correct without the projection
    for row in rows:
        fact = found.get(row['id'])
        if fact and fact[1] == VERSION and fact[0] == source_hash(row):
            row['_capability_text'] = fact[2]
            if fact[3]:
                row['_tool_support'] = json.loads(fact[3])
    return rows


# {resource_id: (observation generation, rank_hash)} whose MD5 the database confirmed. Computing
# RANK_HASH_SQL reads usage_guide and usage_tools in full: 65-290 ms per 600 candidates against
# 2-3 ms without it. The observation generation trigger bumps on every change to RANK_FIELDS (the
# same attestation explore_document_reader relies on), so an unchanged generation and stored hash
# would match again; only rows not confirmed at their current generation are hashed. There is no
# warm-up pass: hashing every listing read 185k rows of tool text and evicted the 849 MB vector
# index from shared_buffers (ANN 40 -> 420 ms), so rows are confirmed as searches reach them.
_confirmed = OrderedDict()
_confirmed_lock = threading.Lock()
CONFIRMED_MAX = 300_000


def _confirm(found):
    with _confirmed_lock:
        for rid, fact in found.items():
            _confirmed[rid] = fact
            _confirmed.move_to_end(rid)
        while len(_confirmed) > CONFIRMED_MAX:
            _confirmed.popitem(last=False)


def ranking_rows(store, ids):
    """Compact ranking rows whose stored ranking text matches the current columns exactly.

    The caller holds a read transaction; IDS without a current text are omitted."""
    if not ids or getattr(store, 'backend', None) != 'postgresql' or not _provisioned(store):
        return {}
    where = ('WHERE r.id IN (SELECT value::bigint FROM jsonb_array_elements_text(%s::jsonb)) '
             "AND r.active=1 AND r.health_status IN ('healthy','reachable') "
             "AND COALESCE(r.eval_security,'') NOT IN ('quarantine','review') "
             'AND c.version=%s AND c.rank_text IS NOT NULL')
    source = ('FROM resources r JOIN agentcon_search.capability_text c ON c.resource_id=r.id '
              'LEFT JOIN resource_observation_generations g ON g.resource_id=r.id ')
    try:
        rows = store._execute('SELECT r.id,r.kind,r.name,r.description,r.eval_score,c.rank_text,g.generation,c.rank_hash '
            + source + where, (json.dumps([int(rid) for rid in ids]), VERSION),
            max_rows=len(ids), max_bytes=MAX_READ_BYTES).fetchall()
        with _confirmed_lock:
            known = {row[0] for row in rows if row[6] is not None and _confirmed.get(row[0]) == (row[6], row[7])}
        unknown = [row[0] for row in rows if row[0] not in known]
        if unknown:
            # Hash only the rest. A row that changed between the two reads keeps its first-read
            # text only when both reads saw the same generation and hash.
            checked = {row[0]: (row[1], row[2]) for row in store._execute(
                'SELECT r.id,g.generation,c.rank_hash ' + source + where + ' AND c.rank_hash=' + RANK_HASH_SQL,
                (json.dumps(unknown), VERSION), max_rows=len(unknown)).fetchall()}
            _confirm({rid: fact for rid, fact in checked.items() if fact[0] is not None})
            known.update(row[0] for row in rows if row[0] in checked and checked[row[0]] == (row[6], row[7]))
    except Exception:
        return {}
    return {row[0]: {'id': row[0], 'kind': row[1], 'name': row[2], 'description': row[3],
                     'eval_score': row[4], '_rank_text': row[5]} for row in rows if row[0] in known}


class Refresher:
    """Bounded jobs-role rounds; a full pass, then a rest until the next interval."""

    def __init__(self, store, *, interval=6 * 3600, batch=200, rounds=10, clock=time.monotonic):
        self.store, self.interval, self.batch, self.rounds, self.clock = store, interval, batch, rounds, clock
        self.after, self.rest_until, self.enabled, self.checked_at = 0, 0.0, False, None

    def due(self):
        # Until the projection is provisioned, look again every ten minutes.
        if not self.enabled and (self.checked_at is None or self.clock() - self.checked_at >= 600):
            self.checked_at = self.clock()
            try:
                self.enabled = available(self.store)
            except Exception:
                self.enabled = False
        return bool(self.enabled) and self.clock() >= self.rest_until

    def run(self):
        """Refresh up to rounds*batch searchable listings; returns counts."""
        from .application_store_resource_batches import resources
        from .concierge.discovery_contracts import contract_reads
        checked = written = 0

        @contract_reads
        def one(ids):
            nonlocal checked, written
            with self.store.tx(readonly=True):
                rows = resources(self.store, ids, 'active=1', (), allow_partial=True, hydrate_contracts=True)
                known = stored(self.store, ids, texts=False)
            values = []
            for row in rows:
                row = dict(row)
                digest = source_hash(row)
                fact = known.get(row['id'])
                checked += 1
                if fact and fact[0] == digest and fact[1] == VERSION:
                    continue
                support = tool_support(row)
                values.append((row['id'], digest, VERSION, build(row), time.time(), rank_hash(row), rank_text(row),
                               json.dumps(support, sort_keys=True) if support else None))
            if values:
                with self.store.tx():
                    with self.store._connection.cursor() as writer:
                        writer.executemany('''INSERT INTO agentcon_search.capability_text
                            (resource_id,source_hash,version,body,updated_at,rank_hash,rank_text,tool_support)
                            VALUES(%s,%s,%s,%s,%s,%s,%s,%s)
                            ON CONFLICT(resource_id) DO UPDATE SET source_hash=excluded.source_hash,version=excluded.version,
                            body=excluded.body,updated_at=excluded.updated_at,rank_hash=excluded.rank_hash,
                            rank_text=excluded.rank_text,tool_support=excluded.tool_support''', values)
                written += len(values)

        for _ in range(self.rounds):
            with self.store.tx(readonly=True):
                ids = [row[0] for row in self.store._execute(
                    'SELECT id FROM resources WHERE ' + SEARCHABLE + ' AND id > %s ORDER BY id LIMIT %s',
                    (self.after, self.batch), max_rows=self.batch).fetchall()]
            if not ids:
                # A full pass is complete; drop texts of listings that left the searchable set.
                # The scan runs in a read snapshot; the writer lock only covers a re-checked delete by id.
                with self.store.tx(readonly=True):
                    stale = [row[0] for row in self.store._execute(
                        'SELECT t.resource_id FROM agentcon_search.capability_text t WHERE ' + LEFT_SEARCHABLE
                        + ' ORDER BY t.resource_id LIMIT %s', (PRUNE_LIMIT,), max_rows=PRUNE_LIMIT).fetchall()]
                for start in range(0, len(stale), PRUNE_BATCH):
                    with self.store.tx():
                        self.store._execute(
                            'DELETE FROM agentcon_search.capability_text t WHERE t.resource_id IN '
                            '(SELECT jsonb_array_elements_text(%s::jsonb)::bigint) AND ' + LEFT_SEARCHABLE,
                            (json.dumps(stale[start:start + PRUNE_BATCH]),))
                self.after, self.rest_until = 0, self.clock() + self.interval
                break
            one(ids)
            self.after = ids[-1]
        return {'checked': checked, 'written': written}
