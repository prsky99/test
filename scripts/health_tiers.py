"""Host tiers for the health schedule (11-14 사용자 결정 "등급별로 변경", PM): bulk hosts are hosts with 1,000 or more
active endpoints and no grade A. The health checker samples about 100 of them a day and checks the rest weekly; a
bulk host whose sampled checks in the last 24 hours all failed is marked suspect (not retired). A host that gains a
grade A leaves the list on the next run and returns to the normal rules.

Production read only, one connection; writes gateway-data/health/host-tiers.json atomically.
    .venv/bin/python -m scripts.health_tiers
"""
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'gateway-data/health/host-tiers.json'
BULK_ACTIVE = 1000


def compute(rows, checks):
    """ROWS: (host, active, grade_a); CHECKS: {host: (checks_24h, fails_24h)} -> the tiers document."""
    bulk = {host: {'active': active, 'grade_a': a} for host, active, a in rows if active >= BULK_ACTIVE and not a}
    suspect = sorted(host for host in bulk if checks.get(host, (0, 0))[0] and checks[host][0] == checks[host][1])
    for host in bulk:
        n, fails = checks.get(host, (0, 0))
        bulk[host].update(checks_24h=n, fails_24h=fails, suspect=host in suspect)
    return {'generated': time.strftime('%Y-%m-%dT%H:%M:%S%z'), 'rule': f'{BULK_ACTIVE}+ active and no grade A',
            'bulk_hosts': bulk, 'suspect': suspect}


def main():
    import psycopg
    dsn = (ROOT / 'gateway-data/postgres18/application.dsn').read_text().strip()
    with psycopg.connect(dsn, autocommit=True, options='-c default_transaction_read_only=on -c statement_timeout=60000') as c:
        rows = c.execute("""SELECT host, count(*), count(*) FILTER (WHERE eval_grade='A') FROM public.resources
            WHERE active=1 AND health_status<>'retired' AND host IS NOT NULL GROUP BY host HAVING count(*) >= %s""",
                         (BULK_ACTIVE,)).fetchall()
        hosts = [h for h, n, a in rows if not a]
        checks = {}
        if hosts:
            for host, n, fails in c.execute("""SELECT r.host, count(*), count(*) FILTER (WHERE h.outcome='fail')
                    FROM public.health_checks h JOIN public.resources r ON r.id=h.resource_id
                    WHERE r.host = ANY(%s) AND h.at > extract(epoch FROM now()) - 86400 GROUP BY r.host""", (hosts,)):
                checks[host] = (n, fails)
    doc = compute(rows, checks)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    tmp = OUT.with_suffix('.tmp')
    tmp.write_text(json.dumps(doc, indent=1))
    tmp.replace(OUT)
    print(f"{OUT.relative_to(ROOT)}: bulk {len(doc['bulk_hosts'])} hosts "
          f"({sum(v['active'] for v in doc['bulk_hosts'].values())} endpoints), suspect {doc['suspect']}")
    return 0


if __name__ == '__main__':
    sys.exit(main())
