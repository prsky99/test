"""Bounded read-only workflow storage observations; never run maintenance."""
import argparse
import json
from pathlib import Path
import sqlite3
import time
import os

PROFILE = 'workflow-storage-observation-v1'
SECONDS = .25
QUERIES = {
    'runs': """SELECT CASE WHEN status IN ('queued','running','succeeded','failed','cancelled')
        THEN status ELSE 'other' END AS state, COUNT(*) AS count,
        SUM(CASE WHEN execution_outcome='unknown' THEN 1 ELSE 0 END) AS unknown
        FROM workflow_runs GROUP BY state""",
    'result_outbox': """SELECT CASE WHEN status IN ('pending','claimed','dispatched','accepted','unknown','denied')
        THEN status ELSE 'other' END AS state, COUNT(*) AS count
        FROM workflow_result_outbox GROUP BY state""",
    'manual_deliveries': """SELECT CASE WHEN status IN ('pending','claimed','dispatched','accepted','unknown','denied')
        THEN status ELSE 'other' END AS state, COUNT(*) AS count
        FROM workflow_manual_deliveries GROUP BY state""",
}
PRAGMAS = {'page_size_bytes': 'PRAGMA page_size', 'page_count': 'PRAGMA page_count',
           'freelist_pages': 'PRAGMA freelist_count', 'journal_mode': 'PRAGMA journal_mode'}


def file_size(path):
    try:
        # Auxiliary files are optional. Never follow a separate symlink to inspect
        # another location or return any filesystem name in the response.
        if path.is_symlink() or not path.is_file():
            return {'present': False}
        return {'present': True, 'bytes': path.stat().st_size}
    except OSError:
        return {'present': False, 'unavailable': True}


def observe(db_path):
    started = time.monotonic()
    result = {'profile': PROFILE, 'sampled_at': time.time(), 'read_only': True,
              'available': False, 'sqlite': {}, 'workflow_counts': {},
              'coverage': {'complete': False, 'unavailable_sections': [],
                           'queue_counts_at_one_read_snapshot': False,
                           'file_sizes_are_transactional': False,
                           'lock_contention_measured': False},
              'actions': {'sql_writes': False, 'wal_checkpoint': False, 'vacuum': False,
                          'store_initialization': False, 'queue_recovery': False}}
    db = None
    try:
        path = Path(db_path).resolve(strict=True)
        if not path.is_file():
            raise ValueError('Unavailable storage.')
        result['files'] = {'database': file_size(path),
                           'wal': file_size(Path(str(path) + '-wal')),
                           'shared_memory': file_size(Path(str(path) + '-shm'))}
        db = sqlite3.connect(path.as_uri() + '?mode=ro', uri=True, timeout=.05)
        db.execute('PRAGMA query_only=ON')
        db.set_progress_handler(lambda: int(time.monotonic() - started >= SECONDS), 1000)
        db.execute('BEGIN')
        # Read the schema first to establish one deferred SQLite read snapshot.
        tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        for key, sql in PRAGMAS.items():
            if time.monotonic() - started >= SECONDS:
                result['coverage']['unavailable_sections'].append('allocation')
                break
            value = db.execute(sql).fetchone()[0]
            result['sqlite'][key] = value
        if all(key in result['sqlite'] for key in ('page_size_bytes', 'page_count', 'freelist_pages')):
            allocation = result['sqlite']
            allocation['allocated_bytes'] = allocation['page_size_bytes'] * allocation['page_count']
            allocation['free_page_bytes'] = allocation['page_size_bytes'] * allocation['freelist_pages']
        for key, sql in QUERIES.items():
            if time.monotonic() - started >= SECONDS:
                result['coverage']['unavailable_sections'].append(key)
                continue
            table = {'runs': 'workflow_runs', 'result_outbox': 'workflow_result_outbox',
                     'manual_deliveries': 'workflow_manual_deliveries'}[key]
            if table not in tables:
                result['coverage']['unavailable_sections'].append(key)
                continue
            try:
                rows = db.execute(sql).fetchall()
                groups = {row[0]: int(row[1]) for row in rows}
                result['workflow_counts'][key] = {'states': groups}
                if key == 'runs':
                    result['workflow_counts'][key]['unknown_outcomes'] = sum(int(row[2]) for row in rows)
            except sqlite3.DatabaseError:
                result['coverage']['unavailable_sections'].append(key)
        result['available'] = True
        result['coverage']['queue_counts_at_one_read_snapshot'] = True
        result['coverage']['complete'] = not result['coverage']['unavailable_sections']
    except (OSError, ValueError, TypeError, sqlite3.DatabaseError):
        result['coverage']['unavailable_sections'].append('database')
    finally:
        if db is not None:
            db.close()
    result['elapsed_ms'] = round((time.monotonic() - started) * 1000, 2)
    return result


def observe_store(store):
    """Observe native queue state without interpreting a backend as a filename."""
    if getattr(store, 'backend', 'sqlite') != 'postgresql':
        return observe(store._path)
    result = {'profile': PROFILE, 'backend': 'postgresql', 'sampled_at':time.time(),
        'read_only':True, 'available':False, 'workflow_counts':{},
        'coverage':{'complete':False,'unavailable_sections':[],
            'queue_counts_at_one_read_snapshot':True,'file_sizes_are_transactional':False,
            'lock_contention_measured':False},
        'actions':{'sql_writes':False,'wal_checkpoint':False,'vacuum':False,
            'store_initialization':False,'queue_recovery':False}}
    try:
        with store.tx(readonly=True) as db:
            size = store._execute('SELECT pg_database_size(current_database())').fetchone()[0]
            result['postgresql'] = {'database_bytes':size,
                'persistent_storage':'native','search_projection':'ephemeral-fts5'}
            for name, sql in QUERIES.items():
                result['workflow_counts'][name] = [dict(row) for row in db.execute(sql).fetchall()]
        result['available'] = result['coverage']['complete'] = True
    except sqlite3.Error:
        result['coverage']['unavailable_sections'] = ['native_storage']
    return result


def router_for(db_path, require_sadmin, *, store=None):
    from fastapi import APIRouter, Depends, HTTPException
    from fastapi.responses import JSONResponse
    from starlette.concurrency import run_in_threadpool
    from .gateway.admin_security import AdminRoute

    class StorageRoute(AdminRoute):
        def get_route_handler(self):
            handler = super().get_route_handler()

            async def secured(request):
                try:
                    return await handler(request)
                except HTTPException as exc:
                    exc.headers = {**(exc.headers or {}), 'Cache-Control': 'no-store', 'Pragma': 'no-cache'}
                    raise
            return secured

    router = APIRouter(route_class=StorageRoute)

    @router.get('/admin/api/workflows/storage', dependencies=[Depends(require_sadmin)])
    async def storage():
        data = await run_in_threadpool(observe_store, store) if store is not None else await run_in_threadpool(observe, db_path)
        return JSONResponse(data, headers={'Cache-Control': 'no-store', 'Pragma': 'no-cache'})

    return router


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db')
    args = parser.parse_args()
    backend=os.environ.get('APPLICATION_STORE_BACKEND','sqlite')
    if backend=='postgresql':
        from .application_runtime import open_runtime_storage
        storage=open_runtime_storage(None)
        try:result=observe_store(storage.store)
        finally:storage.close()
    elif backend=='sqlite':
        if not args.db:parser.error('--db is required for the SQLite backend.')
        result=observe(args.db)
    else:
        parser.error('Choose a supported application backend.')
    print(json.dumps(result, allow_nan=False))
    return 0 if result['available'] else 2


if __name__ == '__main__':
    raise SystemExit(main())
