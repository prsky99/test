"""Private result receipts in existing checkpoints; no schema changes or dispatch.

Worker results arrive as Origin ingress. Native execution reads the same signed
receipt locally instead of downloading the result back from the Worker. The
reserved er_ coordinates cannot overlap ordinary Workflow run checkpoints.
"""
from contextlib import contextmanager
from contextvars import ContextVar
import hashlib
import hmac
import re

from .auth import RUN, canonical, derived
from .config import EdgeError, parse
from .state import rows, transaction

RESULT = 'edge-result-transport-v1'
CONTEXT = 'edge-direct-context-v1'
PARENT = 'edge-parent-v1:'
_parent = ContextVar('edge_result_parent', default=None)
_collect = ContextVar('edge_result_collection', default=None)


@contextmanager
def collecting():
    # A per-request mutable set also reaches the authorized threadpool handler.
    value=set();token=_collect.set(value)
    try: yield value
    finally: _collect.reset(token)


def note_parent(run_id):
    value=_collect.get()
    if value is not None and len(value)<64 and type(run_id) is str and re.fullmatch(r'(?:wr|wpr|wtr)_[a-f0-9]{32}',run_id):
        value.add(run_id)


def sql(db, statement, values=()):
    native = getattr(db, '_store', None)
    return native._execute(statement.replace('?', '%s'), values) if native is not None else db.execute(statement, values)


def available(store):
    try:
        with transaction(store, readonly=True) as db:
            sql(db, 'SELECT run_id FROM workflow_checkpoints LIMIT 1').fetchone()
        return True
    except Exception:
        return False


def signature(service, value):
    return hmac.new(derived(service.config.key, RESULT), canonical(value).encode(), hashlib.sha256).hexdigest()


def read(service, run_id, coordinate):
    with transaction(service.store, readonly=True) as db:
        row = sql(db, 'SELECT payload,signature FROM workflow_checkpoints WHERE run_id=? AND node_id=?', (run_id, coordinate)).fetchone()
    if row is None:
        return None
    value = parse(row[0])
    if (type(value) is not dict or value.get('aud') != coordinate or value.get('run_id') != run_id
            or not hmac.compare_digest(str(row[1]), signature(service, value))):
        raise EdgeError('RESULT_INVALID', 409)
    return value


def write_once(service, run_id, coordinate, value):
    value = {**value, 'aud': coordinate, 'run_id': run_id}
    payload, proof = canonical(value), signature(service, value)
    with transaction(service.store) as db:
        sql(db, 'INSERT INTO workflow_checkpoints (run_id,node_id,payload,signature) VALUES (?,?,?,?) ON CONFLICT(run_id,node_id) DO NOTHING',
            (run_id, coordinate, payload, proof))
    stored = read(service, run_id, coordinate)
    if canonical(stored) != payload:
        raise EdgeError('OUTCOME_CONFLICT', 409)
    return stored


def store_result(service, run_id, attempt, wire, wire_hash):
    if (type(run_id) is not str or not RUN.fullmatch(run_id)
            or type(attempt) is not str or not re.fullmatch(r'ea_[a-f0-9]{32}', attempt)
            or type(wire) is not str or len(wire.encode()) > 65536
            or type(wire_hash) is not str or not re.fullmatch(r'[a-f0-9]{64}', wire_hash)
            or not hmac.compare_digest(hashlib.sha256(wire.encode()).hexdigest(), wire_hash)):
        raise EdgeError('INVALID_INPUT', 400)
    output = parse(wire)
    if type(output) is not dict:
        raise EdgeError('INVALID_INPUT', 400)
    with transaction(service.store, readonly=True) as db:
        found = rows(db, 'run', (run_id,))
    if not found or found[0]['attempt'] != attempt or found[0]['state'] not in ('dispatch_reserved', 'succeeded'):
        raise EdgeError('ATTEMPT_CHANGED', 409)
    write_once(service, run_id, RESULT, {'attempt': attempt, 'wire': wire, 'wire_hash': wire_hash})
    service.finish(run_id, attempt, 'succeeded', len(wire.encode()))
    return {'ok': True, 'run_id': run_id, 'wire_hash': wire_hash}


def load_result(service, run_id):
    value = read(service, run_id, RESULT)
    with transaction(service.store, readonly=True) as db:
        found = rows(db, 'run', (run_id,))
    if (not value or not found or found[0]['state'] != 'succeeded'
            or value.get('attempt') != found[0]['attempt']
            or hashlib.sha256(value['wire'].encode()).hexdigest() != value['wire_hash']):
        raise EdgeError('RESULT_UNAVAILABLE', 409)
    return {'output': parse(value['wire']), 'run_id': run_id, 'wire_hash': value['wire_hash'], 'backend':found[0]['backend']}


def consume(service, run_id):
    """At most one MCP finalization; a lost reply cannot create new dispatch."""
    value = {'aud': CONTEXT, 'run_id': run_id}
    with transaction(service.store) as db:
        return sql(db, 'INSERT INTO workflow_checkpoints (run_id,node_id,payload,signature) VALUES (?,?,?,?) ON CONFLICT(run_id,node_id) DO NOTHING',
            (run_id, CONTEXT, canonical(value), signature(service, value))).rowcount == 1


@contextmanager
def parent_scope(run_id, node_id):
    value = (run_id, node_id) if (type(run_id) is str and 1 <= len(run_id) <= 160
            and not RUN.fullmatch(run_id) and type(node_id) is str and 1 <= len(node_id) <= 160) else None
    token = _parent.set(value)
    try:
        yield
    finally:
        _parent.reset(token)


def link_parent(service, edge_run):
    parent = _parent.get()
    if parent is None:
        return
    run_id, node_id = parent
    coordinate = PARENT+hashlib.sha256((node_id+':'+edge_run).encode()).hexdigest()[:32]
    write_once(service, run_id, coordinate, {'node_id': node_id, 'edge_run_id': edge_run})


def parent_results(service, run_id):
    with transaction(service.store, readonly=True) as db:
        coordinates = sql(db, 'SELECT node_id FROM workflow_checkpoints WHERE run_id=? AND node_id LIKE ? LIMIT 400', (run_id, PARENT+'%')).fetchall()
    values=[]
    for row in coordinates:
        link=read(service, run_id, row[0])
        if not link or not RUN.fullmatch(str(link.get('edge_run_id', ''))):
            raise EdgeError('RESULT_INVALID', 409)
        try:
            values.append(load_result(service, link['edge_run_id']))
        except EdgeError as exc:
            if exc.code != 'RESULT_UNAVAILABLE':raise
    return values


def prune(service):
    """Remove only our orphan receipts after the Edge retention job prunes runs."""
    with transaction(service.store) as db:
        sql(db, '''DELETE FROM workflow_checkpoints WHERE run_id IN (
            SELECT c.run_id FROM workflow_checkpoints c WHERE c.node_id=?
            AND NOT EXISTS (SELECT 1 FROM edge_gateway_runs r WHERE r.id=c.run_id) LIMIT 100)
            AND node_id IN (?,?)''', (RESULT, RESULT, CONTEXT))
