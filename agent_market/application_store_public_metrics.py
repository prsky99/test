"""Fixed native SQL for public aggregate metrics, without resource identities."""
import math


def _window(start, end):
    if any(type(v) not in (int, float) or not math.isfinite(v) or v < 0 for v in (start, end)) or start > end:
        from .application_store_postgres import ApplicationStoreError
        raise ApplicationStoreError('invalid_parameters')


def catalog(store, start, end):
    _window(start, end)
    with store.tx(readonly=True):
        grouped = store._execute('''SELECT kind,health_status AS status,COUNT(*) AS n,
            SUM(CASE WHEN last_check_at IS NOT NULL THEN 1 ELSE 0 END) AS checked,
            SUM(CASE WHEN first_seen>=%s AND first_seen<=%s THEN 1 ELSE 0 END) AS new_count
            FROM resources WHERE active=1 AND kind IN ('a2a','mcp','x402')
            GROUP BY kind,health_status''', (start, end)).fetchall()
        categories = store._execute('''SELECT category,COUNT(*) AS n FROM resources WHERE active=1
            AND kind IN ('a2a','mcp','x402') GROUP BY category''').fetchall()
    return grouped, categories


def execution(store, start, end):
    _window(start, end)
    with store.tx(readonly=True):
        grouped = store._execute('''SELECT CASE v.profile_version WHEN 'a2a-sync-v1' THEN 'a2a'
            WHEN 'mcp-stateless-v1' THEN 'mcp' WHEN 'x402-probe-v1' THEN 'x402' ELSE 'other' END kind,
            e.outcome,COUNT(*) n FROM capability_evidence e JOIN connection_versions v ON v.id=e.version_id
            WHERE e.scope='execution' AND e.finished>=%s AND e.finished<=%s
              AND e.started>0 AND e.started<=e.finished AND e.outcome IN ('succeeded','failed','unknown')
            GROUP BY kind,e.outcome''', (start, end)).fetchall()
        unique = store._execute('''SELECT COUNT(DISTINCT v.resource_id) n
            FROM capability_evidence e JOIN connection_versions v ON v.id=e.version_id
            WHERE e.scope='execution' AND e.outcome='succeeded' AND e.finished>=%s AND e.finished<=%s
              AND e.started>0 AND e.started<=e.finished''', (start, end)).fetchone()['n']
        hourly = store._execute('''SELECT LEAST(23,FLOOR((e.finished-%s)/3600)::bigint) bucket,
            e.outcome,COUNT(*) n FROM capability_evidence e JOIN connection_versions v ON v.id=e.version_id
            WHERE e.scope='execution' AND e.finished>=%s AND e.finished<=%s
              AND e.started>0 AND e.started<=e.finished AND e.outcome IN ('succeeded','failed','unknown')
            GROUP BY bucket,e.outcome''', (start, start, end)).fetchall()
    return grouped, unique, hourly
