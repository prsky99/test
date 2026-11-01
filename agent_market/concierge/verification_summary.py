"""Public aggregate checks with explicit time, scope and outcome boundaries."""
import time


def execution_summary(store, now=None):
    now = time.time() if now is None else now
    start = now - 86400
    native = getattr(store, 'public_execution_metrics', None)
    if callable(native):
        grouped, unique, hourly_rows = native(start, now)
    else:
        hourly_rows = None
        grouped = store.query('''SELECT CASE v.profile_version WHEN 'a2a-sync-v1' THEN 'a2a' WHEN 'mcp-stateless-v1' THEN 'mcp' WHEN 'x402-probe-v1' THEN 'x402' ELSE 'other' END kind,e.outcome,COUNT(*) n
        FROM capability_evidence e JOIN connection_versions v ON v.id=e.version_id
        WHERE e.scope='execution' AND e.finished>=? AND e.finished<=?
          AND e.started>0 AND e.started<=e.finished
          AND e.outcome IN ('succeeded','failed','unknown')
        GROUP BY kind,e.outcome''', (start, now))
    totals = {state: 0 for state in ('succeeded', 'failed', 'unknown')}
    protocols = {kind: dict(totals) for kind in ('a2a', 'mcp', 'x402')}
    for row in grouped:
        totals[row['outcome']] += row['n']
        if row['kind'] in protocols:
            protocols[row['kind']][row['outcome']] += row['n']
    if not callable(native):
        unique = store.query('''SELECT COUNT(DISTINCT v.resource_id) n
        FROM capability_evidence e JOIN connection_versions v ON v.id=e.version_id
        WHERE e.scope='execution' AND e.outcome='succeeded'
          AND e.finished>=? AND e.finished<=? AND e.started>0 AND e.started<=e.finished''', (start, now))[0]['n']
    hourly = [{'start': start + i * 3600, 'succeeded': 0, 'failed': 0, 'unknown': 0} for i in range(24)]
    if hourly_rows is None:
        hourly_rows = store.query('''SELECT MIN(23,CAST((finished-?)/3600 AS INTEGER)) bucket,
        e.outcome,COUNT(*) n FROM capability_evidence e
        JOIN connection_versions v ON v.id=e.version_id
        WHERE e.scope='execution' AND e.finished>=? AND e.finished<=?
          AND e.started>0 AND e.started<=e.finished AND e.outcome IN ('succeeded','failed','unknown')
        GROUP BY bucket,e.outcome''', (start, start, now))
    for row in hourly_rows:
        hourly[row['bucket']][row['outcome']] = row['n']
    completed = sum(totals.values())
    return {'period_start': start, 'period_end': now, 'timezone': 'UTC', 'scope': 'execution',
            'completed': completed, **totals, 'successful_resources': unique,
            'success_share_pct': round(100 * totals['succeeded'] / completed, 1) if completed else None,
            'by_protocol': protocols, 'bucket_seconds': 3600, 'hourly': hourly}
