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
# A release folder has no gateway-data of its own; services run from the repository root (launchd WorkingDirectory),
# so the ledger is shared by the scripts and every service role.
DIR = Path(os.environ.get('PROVIDER_BUDGET_DIR') or ((ROOT if (ROOT / 'gateway-data').is_dir() else Path.cwd())
                                                    / 'gateway-data/provider-budget'))
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
# PM 11-14 06:4x (decision 3): public-data institutions with stated rate limits that the agents' own per-host pacing
# keeps (agent_market/fallback_agents/limits.py) take more substitute tests a day; the domain total stays DAILY_TOTAL.
SHARE_OVERRIDE = {('substitute_tests', d): 30 for d in ('gleif.org', 'sec.gov', 'nist.gov', 'cisa.gov', 'wikipedia.org',
                                                         'wikidata.org', 'wiktionary.org')}
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
        if used + n > SHARE_OVERRIDE.get((system, name), SHARE[system]):
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


# GitHub's unauthenticated REST allowance is 60 core calls an hour per IP, and every system on this Mac shares it
# (PM 11-14: the fallback watch found it used up). An hourly ledger splits it; /rate_limit is free and not counted.
GITHUB_HOST = 'api.github.com'
GITHUB_HOURLY = 60
GITHUB_FLOOR = 5          # below this many left (GitHub's own count), every system stops until the hour resets
GITHUB_SHARE = {
    'fallback_live': 50,     # live answers of the own GitHub agents (their per-process limiter also stops at 50)
    'necklace_retest': 8,
    'role_tests': 5,
    'substitute_tests': 5,
    'pearl_batch': 2,
    'adhoc': 2,
    'gate': GITHUB_HOURLY - GITHUB_FLOOR,   # whatever is left
}


def hour(now=None):
    return datetime.fromtimestamp(time.time() if now is None else now, KST).strftime('%Y%m%d%H')


def github_reserve(system, n=1, now=None, directory=None):
    """Count N GitHub core calls of SYSTEM in this hour if the shared allowance allows them. Returns (ok, reason)."""
    if system not in GITHUB_SHARE:
        raise ValueError(f'unknown system {system!r}; add it to provider_budget.GITHUB_SHARE')
    now = time.time() if now is None else now
    with _ledger('github-' + hour(now), directory) as data:
        entry = data.setdefault('github', {'total': 0, 'by': {}, 'refused': {}})
        paused = entry.get('paused_until')
        why = None
        if paused and now < paused:
            why = 'github_floor'
        elif entry['total'] + n > GITHUB_HOURLY - GITHUB_FLOOR:
            why = 'github_hourly_total'
        elif entry['by'].get(system, 0) + n > GITHUB_SHARE[system]:
            why = 'system_share'
        if why:
            entry['refused'][system] = entry['refused'].get(system, 0) + n
            return False, why
        entry['total'] += n
        entry['by'][system] = entry['by'].get(system, 0) + n
        return True, 'ok'


def github_observe(headers, system=None, now=None, directory=None):
    """Record GitHub's own remaining count from a response; under GITHUB_FLOOR every system stops until the reset."""
    try:
        remaining = int((headers or {}).get('x-ratelimit-remaining'))
        reset = int((headers or {}).get('x-ratelimit-reset'))
    except (TypeError, ValueError):
        return None
    now = time.time() if now is None else now
    with _ledger('github-' + hour(now), directory) as data:
        entry = data.setdefault('github', {'total': 0, 'by': {}, 'refused': {}})
        entry['remaining'] = {'left': remaining, 'reset': reset, 'seen_by': system,
                              'at': datetime.fromtimestamp(now, KST).strftime('%H:%M:%S')}
        if remaining < GITHUB_FLOOR:
            entry['paused_until'] = max(entry.get('paused_until') or 0, min(reset, now + 3600))
    return remaining


def github_summary(hours=1, now=None, directory=None):
    """Calls by system over the last HOURS hours (the hourly board line: who uses the shared allowance most)."""
    now = time.time() if now is None else now
    by, refused, total, last = {}, {}, 0, None
    for back in range(hours):
        with _ledger('github-' + hour(now - back * 3600), directory) as data:
            entry = data.get('github') or {}
        total += entry.get('total', 0)
        for k, v in (entry.get('by') or {}).items():
            by[k] = by.get(k, 0) + v
        for k, v in (entry.get('refused') or {}).items():
            refused[k] = refused.get(k, 0) + v
        last = last or entry.get('remaining')
    return {'hours': hours, 'total': total, 'by': dict(sorted(by.items(), key=lambda kv: -kv[1])),
            'refused': refused, 'github_remaining': last}


def status(day=None, directory=None):
    with _ledger(day or today(), directory) as data:
        return json.loads(json.dumps(data))


def main(argv=None):
    import argparse
    parser = argparse.ArgumentParser(description='Show the shared outside-call budget of a day.')
    parser.add_argument('--day', default=None, help='YYYYMMDD (KST), default today')
    parser.add_argument('--top', type=int, default=20)
    parser.add_argument('--github', type=int, default=0, metavar='HOURS', help='GitHub calls by system over HOURS hours')
    args = parser.parse_args(argv)
    if args.github:
        print(json.dumps(github_summary(args.github), ensure_ascii=False, indent=1))
        return
    data = status(args.day)
    rows = sorted(data['domains'].items(), key=lambda kv: -kv[1]['total'])[:args.top]
    print(json.dumps({'day': args.day or today(), 'limit': DAILY_TOTAL, 'domains': len(data['domains']),
                      'paused': sorted(d for d, e in data['domains'].items() if e.get('paused')),
                      'top': {d: e for d, e in rows}}, ensure_ascii=False, indent=1))


if __name__ == '__main__':
    main()
