"""Revenue funnel, one line a day (revenue review 2026-11-15 sections 3.1 and 5.1, PM 11-15 10:57).

    .venv/bin/python -m scripts.revenue_funnel           # count now, append to logs/ops/revenue-funnel.jsonl, print it

Counts only, through scripts.prod_ro_sql (one read-only connection, every statement checked first):
  clients        identified agent clients (agent_visitors, our 'admin-test' channel left out), by channel; every
                 client row is created with a visitor credential, so this is also 'clients that got one' (rows of
                 drive-bys that barely talked are pruned after a while)
  reidentified   clients identified again after the first request (they sent the credential or an issued A2A
                 context back): last_seen later than first_seen
  returning      clients seen again on another day by that credential (visit_days >= 2). A LOWER BOUND (PM 11-15
                 11:5x): a client without the credential cannot be followed across days, because the fingerprint
                 salt changes every UTC day (concierge/memory.py) and is kept that way
  new_24h        clients first seen in the last 24 hours; active_24h: seen in the last 24 hours
  owners         provider ownership verified: owner claims by host (shown, hidden) and provider control claims
  applications   advertiser applications (AD Coin v2 audit 'advertiser_applied'); advertisers: active accounts
  quotes / paid  USDC paid bookings quoted, and received (confirmed, served, review, refund_due, refunded)
  usdc_received  the amount of the received bookings, in USDC (refunds are counted apart, not subtracted)
Advertiser applications, advertisers, quotes, payments and USDC are each split external / internal by the rule of
deploy/ops/adcoin-demand-counts.sql (PM 11-15 11:06): internal is our house advertiser account or the platform
script principal. Revenue is judged on the external numbers only; internal ones are kept, never dropped.
Every count also has its last-24-hours part where the table has a time. No row, name or address is read.
registry_clients: distinct clients of the verified MCP registry (/registry/verified/, E7) on the last full UTC day, from
the frontend's traffic files (logs/service-frontend/traffic/<day>.<pid>.json, 'distinct' registry|<class>, our own
'internal' left out). Each process salts its own digests, so the sum over processes is an upper bound.
"""
import io
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOG = ROOT / 'logs/ops/revenue-funnel.jsonl'
RECEIVED = "('confirmed','served','review','refund_due','refunded')"   # scripts/ad_coin_paid_reconcile.RECEIVED
DAY = 'extract(epoch from now()) - 86400'
HOUSE = "'8087756b-11c5-52aa-892d-a5ce4e01ee7c'"      # our house advertiser (deploy/ops/adcoin-demand-counts.sql)
PLATFORM = "'00b5f2da-301b-5c5c-8dfa-6ea4ba186b37'"   # the platform script principal (same file)

SQL = f"""
SELECT 'clients', count(*), count(*) FILTER (WHERE visit_days >= 2), count(*) FILTER (WHERE first_seen >= {DAY}),
       count(*) FILTER (WHERE last_seen >= {DAY}), count(*) FILTER (WHERE last_seen > first_seen + 1)
  FROM public.agent_visitors WHERE channel IS DISTINCT FROM 'admin-test';
SELECT 'channel', coalesce(channel, 'none'), count(*) FROM public.agent_visitors
 WHERE channel IS DISTINCT FROM 'admin-test' GROUP BY 2 ORDER BY 2;
SELECT 'owners', count(*) FILTER (WHERE verified_at IS NOT NULL AND NOT coalesce(hidden, false)),
       count(*) FILTER (WHERE verified_at IS NOT NULL AND coalesce(hidden, false)),
       count(*) FILTER (WHERE verified_at >= {DAY})
  FROM agentcon_owner.resource_owner_claims;
SELECT 'control', count(*) FILTER (WHERE verified IS NOT NULL AND revoked IS NULL),
       count(*) FILTER (WHERE verified >= {DAY})
  FROM public.provider_control_claims;
SELECT 'applications', CASE WHEN actor_principal_id = {PLATFORM} OR target_id = {HOUSE} THEN 'internal' ELSE 'external' END,
       count(*), count(*) FILTER (WHERE timestamp_ms >= ({DAY}) * 1000)
  FROM ad_coin_v2.adc2_audit_log WHERE event_type = 'advertiser_applied' GROUP BY 2;
SELECT 'advertisers', CASE WHEN id = {HOUSE} THEN 'internal' ELSE 'external' END, count(*)
  FROM ad_coin_v2.adc2_advertisers WHERE status = 'active' GROUP BY 2;
SELECT 'bookings', CASE WHEN advertiser_id = {HOUSE} THEN 'internal' ELSE 'external' END,
       count(*), count(*) FILTER (WHERE quoted_ms >= ({DAY}) * 1000),
       count(*) FILTER (WHERE state IN {RECEIVED}),
       count(*) FILTER (WHERE state IN {RECEIVED} AND confirmed_ms >= ({DAY}) * 1000),
       coalesce(sum(amount_units) FILTER (WHERE state IN {RECEIVED}), 0),
       count(*) FILTER (WHERE state = 'refunded')
  FROM ad_coin_v2.adc2_paid_bookings GROUP BY 2
"""

UNITS = 1_000_000
TRAFFIC = ROOT / 'logs/service-frontend/traffic'


def registry_clients(clock=time.time, folder=None):
    """Distinct registry clients on the last full UTC day, by client class (upper bound: summed over processes)."""
    import datetime as _dt
    day = (_dt.datetime.fromtimestamp(clock(), _dt.timezone.utc) - _dt.timedelta(days=1)).strftime('%Y-%m-%d')
    by = {}
    for path in sorted(Path(folder or TRAFFIC).glob(day + '.*.json')):
        try:
            distinct = json.loads(path.read_text()).get('distinct') or {}
        except (OSError, ValueError):
            continue
        for key, value in distinct.items():
            entry, _, cls = key.partition('|')
            if entry == 'registry' and cls != 'internal' and isinstance(value, int):
                by[cls] = by.get(cls, 0) + value
    return {'day': day, 'total': sum(by.values()), 'by_class': by, 'basis': 'sum_over_processes_upper_bound'}   # agent_market.ad_coin.v2.paid_bookings.USDC_UNITS


def parse(lines):
    """The prod_ro_sql output ('|'-separated rows, each led by its key) as one record."""
    rows = [line.split('|') for line in lines if line.strip()]
    first = {row[0]: [int(value) for value in row[1:]] for row in rows
             if row[0] in ('clients', 'owners', 'control')}
    channels = {row[1]: int(row[2]) for row in rows if row[0] == 'channel'}
    split = {kind: {row[1]: [int(value) for value in row[2:]] for row in rows if row[0] == kind}
             for kind in ('applications', 'advertisers', 'bookings')}
    clients, returning, new, active, reidentified = first['clients']
    shown, hidden, owners_new = first['owners']
    control, control_new = first['control']
    record = {'clients': clients, 'clients_by_channel': channels, 'reidentified': reidentified,
              'returning': returning, 'returning_basis': 'credential_lower_bound', 'new_24h': new,
              'active_24h': active, 'owners': shown + control, 'owner_hosts': shown, 'owner_hosts_hidden': hidden,
              'control_claims': control, 'owners_24h': owners_new + control_new}
    for side in ('external', 'internal'):
        applied, applied_new = split['applications'].get(side, [0, 0])
        quotes, quotes_new, paid, paid_new, units, refunded = split['bookings'].get(side, [0, 0, 0, 0, 0, 0])
        record[side] = {'applications': applied, 'applications_24h': applied_new,
                        'advertisers_active': split['advertisers'].get(side, [0])[0],
                        'quotes': quotes, 'quotes_24h': quotes_new, 'paid': paid, 'paid_24h': paid_new,
                        'usdc_received': units / UNITS, 'refunded': refunded}
    return record


def count(run=None):
    """One read-only pass. Returns the record, or raises RuntimeError with prod_ro_sql's exit code."""
    if run is None:
        from scripts import prod_ro_sql
        run = prod_ro_sql.run
    out, err = io.StringIO(), io.StringIO()
    code = run(SQL, out=out, err=err)
    if code != 0:
        raise RuntimeError(f'prod_ro_sql exit {code}: {err.getvalue().strip()[:200]}')
    return parse(out.getvalue().splitlines())


def line(record):
    """The board text (Korean, for the site owner). The board keeps 150 characters (ops_auto.board_handoff), so the
    line carries the external funnel and the internal counts only; everything else is in the jsonl record."""
    ext, own = record['external'], record['internal']
    return (f"토큰 받은 클라이언트 {record['clients']}(새 {record['new_24h']}) → 다시 들고 옴 {record['reidentified']} → "
            f"토큰 재방문(하한) {record['returning']} → "
            f"소유 확인 {record['owners']} → 외부 신청 {ext['applications']} → 견적 {ext['quotes']} → "
            f"결제 {ext['paid']} → {ext['usdc_received']:.2f} USDC | 내부 신청 {own['applications']}·"
            f"견적 {own['quotes']}·결제 {own['paid']}")


def main(argv=None, clock=time.time, run=None, log=LOG):
    record = {'at': time.strftime('%Y-%m-%d %H:%M', time.localtime(clock())), **count(run),
              'registry_clients': registry_clients(clock)}
    Path(log).parent.mkdir(parents=True, exist_ok=True)
    with open(log, 'a') as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + '\n')
    print(json.dumps(record, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    sys.exit(main())
