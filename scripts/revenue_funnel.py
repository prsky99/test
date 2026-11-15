"""Revenue funnel, one line a day (revenue review 2026-11-15 sections 3.1 and 5.1, PM 11-15 10:57).

    .venv/bin/python -m scripts.revenue_funnel           # count now, append to logs/ops/revenue-funnel.jsonl, print it

Counts only, through scripts.prod_ro_sql (one read-only connection, every statement checked first):
  clients        identified agent clients (agent_visitors, our 'admin-test' channel left out), by channel
  returning      clients seen on two or more different days (visit_days >= 2)
  new_24h        clients first seen in the last 24 hours; active_24h: seen in the last 24 hours
  owners         provider ownership verified: owner claims by host (shown, hidden) and provider control claims
  applications   advertiser applications (AD Coin v2 audit 'advertiser_applied'); advertisers: active accounts
  quotes / paid  USDC paid bookings quoted, and received (confirmed, served, review, refund_due, refunded)
  usdc_received  the amount of the received bookings, in USDC (refunds are counted apart, not subtracted)
Every count also has its last-24-hours part where the table has a time. No row, name or address is read.
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

SQL = f"""
SELECT 'clients', count(*), count(*) FILTER (WHERE visit_days >= 2), count(*) FILTER (WHERE first_seen >= {DAY}),
       count(*) FILTER (WHERE last_seen >= {DAY})
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
SELECT 'applications', count(*), count(*) FILTER (WHERE timestamp_ms >= ({DAY}) * 1000)
  FROM ad_coin_v2.adc2_audit_log WHERE event_type = 'advertiser_applied';
SELECT 'advertisers', count(*) FILTER (WHERE status = 'active') FROM ad_coin_v2.adc2_advertisers;
SELECT 'bookings', count(*), count(*) FILTER (WHERE quoted_ms >= ({DAY}) * 1000),
       count(*) FILTER (WHERE state IN {RECEIVED}),
       count(*) FILTER (WHERE state IN {RECEIVED} AND confirmed_ms >= ({DAY}) * 1000),
       coalesce(sum(amount_units) FILTER (WHERE state IN {RECEIVED}), 0),
       count(*) FILTER (WHERE state = 'refunded')
  FROM ad_coin_v2.adc2_paid_bookings
"""

UNITS = 1_000_000   # agent_market.ad_coin.v2.paid_bookings.USDC_UNITS


def parse(lines):
    """The prod_ro_sql output ('|'-separated rows, each led by its key) as one record."""
    rows = [line.split('|') for line in lines if line.strip()]
    first = {row[0]: [int(value) for value in row[1:]] for row in rows if row[0] != 'channel'}
    channels = {row[1]: int(row[2]) for row in rows if row[0] == 'channel'}
    clients, returning, new, active = first['clients']
    shown, hidden, owners_new = first['owners']
    control, control_new = first['control']
    applied, applied_new = first['applications']
    quotes, quotes_new, paid, paid_new, units, refunded = first['bookings']
    return {'clients': clients, 'clients_by_channel': channels, 'returning': returning, 'new_24h': new,
            'active_24h': active, 'owners': shown + control, 'owner_hosts': shown, 'owner_hosts_hidden': hidden,
            'control_claims': control, 'owners_24h': owners_new + control_new,
            'applications': applied, 'applications_24h': applied_new, 'advertisers_active': first['advertisers'][0],
            'quotes': quotes, 'quotes_24h': quotes_new, 'paid': paid, 'paid_24h': paid_new,
            'usdc_received': units / UNITS, 'refunded': refunded}


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
    """The board text (Korean, for the site owner)."""
    return (f"식별 클라이언트 {record['clients']}(24시간 새로 {record['new_24h']}·활동 {record['active_24h']}) → "
            f"서로 다른 날 2번 이상 {record['returning']} → 제공자 소유 확인 {record['owners']} → "
            f"광고주 신청 {record['applications']}(활성 광고주 {record['advertisers_active']}) → "
            f"견적 {record['quotes']} → 결제 {record['paid']} → 수령 {record['usdc_received']:.2f} USDC"
            f" | 24시간: 신청 {record['applications_24h']}·견적 {record['quotes_24h']}·결제 {record['paid_24h']}")


def main(argv=None, clock=time.time, run=None, log=LOG):
    record = {'at': time.strftime('%Y-%m-%d %H:%M', time.localtime(clock())), **count(run)}
    Path(log).parent.mkdir(parents=True, exist_ok=True)
    with open(log, 'a') as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + '\n')
    print(json.dumps(record, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    sys.exit(main())
