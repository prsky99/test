"""One shared daily budget for our outside test calls, per registrable domain (PM 11-14, user request).

The pearl batch, the role task tests, the necklace retests and gate, and the self-made substitute tests each counted
their own calls, so nobody knew how often one provider was called in a day. They now ask this ledger first:

    from agent_market.provider_budget import reserve, note
    ok, why = reserve(url, 'necklace_retest')      # before the call; nothing is called when ok is False
    ...
    note(url, 'necklace_retest', response.status_code)  # after it; a 429 pauses the domain for every system today

Rules (deploy/PROVIDER_BUDGET.md)
- DAILY_TOTAL calls a registrable domain a day (KST), all systems together.
- Each system also has its own SHARE; the gate takes what is left of the total.
- A 429 from a domain stops every system calling it for the rest of the day.
- The ledger is one JSON file a day under gateway-data/provider-budget/, changed under an exclusive file lock, so the
  scripts and services that share this Mac see the same counts. Nothing here calls a provider or the database.
"""
import fcntl
import json
import os
import time
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
DIR = Path(os.environ.get('PROVIDER_BUDGET_DIR', ROOT / 'gateway-data/provider-budget'))
KST = timezone(timedelta(hours=9))
DAILY_TOTAL = 60
SHARE = {
    'necklace_retest': 35,   # daily retest of live necklaces: 30 answer-set runs + 3 contract tests + 2 spare
    'role_tests': 5,         # search team's role task tests (09:12)
    'substitute_tests': 5,   # self-made substitute agents' readiness tests
    'pearl_batch': 3,        # 02:30 report batch (its own earlier rule: 3 a provider a day)
    'gate': DAILY_TOTAL,     # necklace launch gate rounds: whatever is left of the total
    'adhoc': 2,              # one-off checks by a team (reproduce a failure)
}
# Hosting platforms give each tenant its own subdomain; the tenant, not the platform, is the provider.
SHARED_SUFFIXES = (
    'vercel.app', 'netlify.app', 'pages.dev', 'workers.dev', 'github.io', 'herokuapp.com', 'onrender.com', 'fly.dev',
    'railway.app', 'up.railway.app', 'deno.dev', 'replit.app', 'repl.co', 'azurewebsites.net', 'appspot.com',
    'run.app', 'cloudfunctions.net', 'web.app', 'firebaseapp.com', 'glitch.me', 'ngrok.app', 'ngrok-free.app',
    'modal.run', 'hf.space', 'lovable.app', 'smithery.ai', 'supabase.co', 'trycloudflare.com', 'koyeb.app',
    'amazonaws.com', 'cloudfront.net', 'azurecontainerapps.io', 'ondigitalocean.app',
)
TWO_LABEL_TLDS = ('co.uk', 'org.uk', 'ac.uk', 'com.au', 'net.au', 'org.au', 'co.jp', 'ne.jp', 'or.jp', 'co.kr',
                  'or.kr', 'go.kr', 'com.br', 'com.cn', 'com.tw', 'co.in', 'co.nz', 'com.sg', 'com.mx', 'co.za')


def domain(url):
    """The registrable domain of URL (lower case); a hosting tenant keeps its own subdomain."""
    host = (urlsplit(url if '//' in str(url) else '//' + str(url)).hostname or '').lower().rstrip('.')
    if not host or host.replace('.', '').isdigit() or ':' in host:
        return host
    labels = host.split('.')
    for suffix in sorted(SHARED_SUFFIXES, key=len, reverse=True):
        if host == suffix:
            return host
        if host.endswith('.' + suffix):
            keep = suffix.count('.') + 2
            return '.'.join(labels[-keep:])
    keep = 3 if '.'.join(labels[-2:]) in TWO_LABEL_TLDS else 2
    return '.'.join(labels[-keep:])


def today(now=None):
    return datetime.fromtimestamp(time.time() if now is None else now, KST).strftime('%Y%m%d')


@contextmanager
def _ledger(day, directory=None):
    folder = Path(directory or DIR)
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f'{day}.json'
    with open(folder / '.lock', 'a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            try:
                data = json.loads(path.read_text())
            except (OSError, ValueError):
                data = {}
            data.setdefault('domains', {})
            yield data
            tmp = path.with_suffix('.tmp')
            tmp.write_text(json.dumps(data, sort_keys=True))
            tmp.replace(path)
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def reserve(url, system, n=1, now=None, directory=None):
    """Count N calls of SYSTEM to URL's domain if today's limits allow them. Returns (ok, reason)."""
    if system not in SHARE:
        raise ValueError(f'unknown system {system!r}; add it to provider_budget.SHARE')
    name = domain(url)
    if not name:
        return False, 'no_domain'
    with _ledger(today(now), directory) as data:
        entry = data['domains'].setdefault(name, {'total': 0, 'by': {}})
        if entry.get('paused'):
            return False, 'paused_429'
        used = entry['by'].get(system, 0)
        if entry['total'] + n > DAILY_TOTAL:
            return False, 'domain_daily_total'
        if used + n > SHARE[system]:
            return False, 'system_share'
        entry['total'] += n
        entry['by'][system] = used + n
        return True, 'ok'


def note(url, system, status, now=None, directory=None):
    """Record a provider answer. A 429 pauses the domain for every system for the rest of the day."""
    if status != 429:
        return False
    name = domain(url)
    with _ledger(today(now), directory) as data:
        entry = data['domains'].setdefault(name, {'total': 0, 'by': {}})
        entry['paused'] = {'at': datetime.fromtimestamp(time.time() if now is None else now, KST).strftime('%H:%M:%S'),
                           'by': system}
    return True


def status(day=None, directory=None):
    with _ledger(day or today(), directory) as data:
        return json.loads(json.dumps(data))


def main(argv=None):
    import argparse
    parser = argparse.ArgumentParser(description='Show the shared outside-call budget of a day.')
    parser.add_argument('--day', default=None, help='YYYYMMDD (KST), default today')
    parser.add_argument('--top', type=int, default=20)
    args = parser.parse_args(argv)
    data = status(args.day)
    rows = sorted(data['domains'].items(), key=lambda kv: -kv[1]['total'])[:args.top]
    print(json.dumps({'day': args.day or today(), 'limit': DAILY_TOTAL, 'domains': len(data['domains']),
                      'paused': sorted(d for d, e in data['domains'].items() if e.get('paused')),
                      'top': {d: e for d, e in rows}}, ensure_ascii=False, indent=1))


if __name__ == '__main__':
    main()
