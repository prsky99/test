"""Monthly AI AD Coin sponsorship audit (plan v3, section 10, stop condition 4).

Reads organic recommendations with sponsorship off, on (circuit closed and live
sponsor holds created for each query) and off again, and fails if turning
sponsorship on changed the top results of any stable query. The report is saved
locally and recorded on the server; a failure opens the circuit there. The
circuit is restored to its earlier state when the audit passes.

  nice -n 10 .venv/bin/python -m scripts.ad_coin_sponsorship_audit --base http://127.0.0.1:8400

Needs AD_COIN_ADMIN_TOKEN. Sends at most 3 reads plus 2 sponsorship calls per
query, one second apart by default, over one reused connection.
"""
import argparse
import json
import os
import pathlib
import sys
import time

import httpx

from agent_market.ad_coin.audit import audit

QUERIES = [
    'summarize a pdf research paper', 'weather forecast for a city', 'convert currency rates without an api key',
    'translate english text to korean', 'search academic papers by topic', 'check website uptime',
    'crypto token price lookup', 'extract text from an image', 'company financial filings', 'news headlines today',
    'flight status by number', 'code review for a pull request', 'generate a chart from a table',
    'legal court records search', 'stock market premarket movers', 'transcribe an audio file',
    'google search trends for a keyword', 'package metadata from npm', 'country profile and statistics',
    'wallet address risk check',
]
API = '/api/ad-coin/v1'


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--base', default='http://127.0.0.1:8400')
    parser.add_argument('--surface', choices=('explore', 'chat'), default='explore')
    parser.add_argument('--queries', help='file with one query per line (default: 20 built-in queries)')
    parser.add_argument('--top', type=int, default=3)
    parser.add_argument('--pause', type=float, default=1.0)
    parser.add_argument('--out', default='')
    parser.add_argument('--no-record', action='store_true', help='do not send the report to the server')
    args = parser.parse_args(argv)
    token = os.environ.get('AD_COIN_ADMIN_TOKEN', '')
    if not token:
        print('Set AD_COIN_ADMIN_TOKEN.', file=sys.stderr)
        return 2
    queries = QUERIES if not args.queries else [line.strip() for line in open(args.queries) if line.strip()]
    admin = {'Authorization': 'Bearer ' + token}
    holds = []
    with httpx.Client(base_url=args.base, timeout=30.0, headers={'User-Agent': 'agentconcierge-ad-coin-audit/1'}) as http:
        def get(path, **kw):
            time.sleep(args.pause)
            response = http.get(path, **kw)
            response.raise_for_status()
            return response.json()

        def post(path, body, headers=admin):
            response = http.post(path, json=body, headers=headers)
            if response.status_code >= 400:
                raise RuntimeError('%s %s: %s' % (path, response.status_code, response.text[:200]))
            return response.json()

        status = get(API + '/status')
        was_open = bool(status['circuit']['open'])

        def fetch(query):
            if args.surface == 'explore':
                data = get('/api/explore', params={'q': query, 'limit': args.top})
                return [item['id'] for item in data.get('items') or [] if isinstance(item, dict)]
            time.sleep(args.pause)
            data = post('/chat', {'message': query}, headers={})['data']
            return [item['id'] for item in data.get('recommendations') or [] if isinstance(item, dict)]

        def set_sponsorship(on):
            post(API + '/admin/circuit', {'open': not on, 'reason': 'audit_off'} if not on else {'open': False})

        def activate(query, ids):
            if not ids:
                return False
            check = post(API + '/upgrade-check', {'recommendation_ids': ids})
            if not check.get('quote_request'):
                return False
            packet = post(API + '/quotes', check['quote_request'])
            for option in packet.get('funding_options', []):
                if option.get('type') == 'sponsored_run':
                    holds.append(option['reservation_id'])
                for item in option.get('items', []) if option.get('type') == 'coin_reward' else []:
                    holds.append(item['reservation_id'])
            return any(o.get('type') in ('sponsored_run', 'coin_reward') for o in packet.get('funding_options', []))

        report = audit(queries, fetch=fetch, set_sponsorship=set_sponsorship, activate=activate, top=args.top)
        report.update(base=args.base, surface=args.surface)
        for reservation in holds:
            try:
                post(API + '/declines', {'reservation_id': reservation})
            except RuntimeError:
                pass
        recorded = None
        if not args.no_record:
            recorded = post(API + '/admin/audits', {'report': report})
        if report['passed'] or report['inconclusive']:
            post(API + '/admin/circuit', {'open': True, 'reason': status['circuit']['reason'] or 'restored'}
                 if was_open else {'open': False})
    out = pathlib.Path(args.out or 'gateway-data/ad_coin_audits/audit-%s.json' % time.strftime('%Y%m%d-%H%M%S'))
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({**report, 'recorded': recorded}, indent=1, ensure_ascii=False))
    counts = report['counts']
    print('audit %s: same %d, changed %d, unstable %d, error %d -> %s' % (
        'PASSED' if report['passed'] else 'INCONCLUSIVE' if report['inconclusive'] else 'FAILED',
        counts['same'], counts['changed'], counts['unstable'], counts['error'], out))
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    sys.exit(main())
