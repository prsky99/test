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
- A 429 from a domain stops every system calling it for the rest of the day (until the next full hour on
  HOURLY_PAUSE_DOMAINS, GDELT).
- The ledger is one JSON file a day under gateway-data/provider-budget/, changed under an exclusive file lock, so the
  scripts and services that share this Mac see the same counts. Nothing here calls a provider or the database.
"""
import fcntl
import json
import logging
import os
import time
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlsplit

log = logging.getLogger(__name__)

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
    'reference_checks': 10,  # answer-key references of the data-quality score (fx rate, versions, feeds; PM F15 11-14)
    'provider_claims': 6,    # provider self-claim checks: one GET when a provider presses Verify, one per origin on
                             # the 30-day recheck (docs/PROVIDER_SELF_CLAIM.md, agent team 11-15)
    'fallback_watch': 30,    # hourly probe of each substitute that is a required slot's only usable member (24 a day per
                             # domain; agent team 02900b54, PM 11-16 06:4x). sec.gov's two (48) fit its declared total: 300.
    'cassettes': 20,         # agent team 11-16 (PM: agents.py split by 11-24): one recording of each approved
                             # substitute's gate inputs, contract inputs and role tasks. Asked for 80 a domain; a share
                             # above DAILY_TOTAL (60) would leave nothing for the necklace retest and the fallback watch on
                             # the commercial domains, so 20 (recording takes 2-4 days, well before 11-24). Ends by
                             # itself after CASSETTES_UNTIL (share_limit).
    'fingerprints': 6,       # pearl/necklace-member tools/list every 6 hours (4 a day + 2 for a manual refresh)
    'ad_blocklists': 4,      # AI AD Coin campaign review blocklist: no source (11-16 PM: every free list checked forbids
                             # commercial use or names no upstream), so agent offers wait for a person; domain age reads
                             # use 'ad_review_rdap' by RDAP server
    'ad_review_rdap': 10,    # AI AD Coin automatic review: domain age of an offer's endpoint, by RDAP server URL, so the
                             # daily E6 run ('lifecycle_rdap') cannot use up what a waiting advertiser needs (11-15)
    'lifecycle_rdap': 50,    # E6 domain expiry reads (docs/VERIFIED_REGISTRY.md): reserve with the RDAP server's
                             # own URL, so the count is per RDAP server (rdap.verisign.com -> verisign.com covers
                             # .com and .net together), not per looked-up domain; the IANA bootstrap file counts too
}
# PM 11-14 06:4x (decision 3): public-data institutions with stated rate limits that the agents' own per-host pacing
# keeps (agent_market/fallback_agents/limits.py) take more substitute tests a day; the domain total stays DAILY_TOTAL.
CASSETTES_UNTIL = '20261124'   # the ledger's day format (today(): YYYYMMDD, KST)
# The share grows with a declared domain's total (x10 on sec.gov, x16 on wikipedia.org); the recording needs about 80
# there, so its base is pinned to give 40 a day on sec.gov (two days, around the gates) and 66 on wikipedia.org.
CASSETTE_OVERRIDE = {('cassettes', 'sec.gov'): 4, ('cassettes', 'wikipedia.org'): 4}
SHARE_OVERRIDE = {('substitute_tests', d): 30 for d in ('gleif.org', 'sec.gov', 'nist.gov', 'cisa.gov', 'wikipedia.org',
                                                         'wikidata.org', 'wiktionary.org', 'gdeltproject.org',
                                                         'census.gov', 'npmjs.org')}
# PM 11-16 19:5x: one role test is 4 requests. On a domain whose total is small (a declared 100 a day gives 20) the
# scaled role_tests share (5 x 20 // 60 = 1) could never test a candidate, so the share is at least ROLE_TEST_MIN when
# the domain's day total allows it (the total itself, 20% of the published limit, is never exceeded).
ROLE_TEST_MIN = 4
# 11-15 (PM 13:52, agent team): GDELT DOC API news substitute; no published daily number, the API answers 'limit
# requests to one every 5 seconds', which the agent's host pacing keeps. The domain total stays DAILY_TOTAL.
# 11-15 (PM 14:25, agent team): Census Geocoder (geocoding.geo.census.gov, a public REST service) for the US-address
# substitute, one request a second; the domain total stays DAILY_TOTAL.
# 11-15 (PM 16:12, agent team ab205afc): registry.npmjs.org for package-releases, one read a package, cached 6 hours.
# PM 11-15 11:40 (necklace-100 plan, decision 5): commercial providers keep DAILY_TOTAL; a public-data institution
# whose own published rate limit was checked (source below, 11-15 by 운영·SRE) may take more, at most half of that
# limit, by registrable domain. Each system's share on such a domain grows by the same factor (total / DAILY_TOTAL).
# NVD and GLEIF are not listed: their pages did not show a number we could check (11-15).
# PM 11-16 06:5x (topic-evidence-brief launch): OpenAlex publishes its keyless allowance as money, not calls --
# "Without a key you get $0.10/day" (help.openalex.org/access/example-costs) and title/filter searches "cost the same
# $1 per 1,000 requests" (help.openalex.org/api/searching), so about 100 of our searches a day. The older "100,000 a
# day" no longer appears there (checked 11-16). Half of that, as for every declared domain (PM 11-15 11:40 decision 5).
DOMAIN_TOTAL = {'sec.gov': 600, 'arxiv.org': 600, 'met.no': 600, 'openalex.org': 50}
# Domains no path of ours may call: their day total is 0 and the ledger refuses every reserve.
CLOSED_DOMAINS = {
    # PM 11-16 18:0x: Nager.Date (date.nager.at, now nagerholidays.com) asks commercial users for sponsorship
    # (TRUTH_SOURCE_TERMS below).
    'nager.at': 'terms: commercial use needs active sponsorship (nagerholidays.com/legal/termsofservice)',
    'nagerholidays.com': 'terms: commercial use needs active sponsorship (nagerholidays.com/legal/termsofservice)',
    # PM 11-16 18:1x: the agent team's terms verdict 4835e5c3 put 34550 and 34807 at prohibits.
    'cutgpt.app': 'member 34550 prohibits (agent team terms verdict 4835e5c3, 11-16)',
    'openkrill.app': 'member 34807 prohibits (agent team terms verdict 4835e5c3, 11-16)',
    # PM 11-16 18:2x, until the ledger reads member_terms prohibits by itself (after r11): the same verdicts put
    # 143970 and 214764 (faceabot.com, the provider's terms cover all its tools-mcp endpoints) and 130453 at prohibits.
    'faceabot.com': 'members 143970, 214764 prohibits (agent team terms verdicts daebcd3b, 4835e5c3, 11-16)',
    'agentdiet.dev': 'member 130453 prohibits (agent team terms verdict 4835e5c3, 11-16)',
}
# Truth sources of our answer sets: terms and published limits, checked at the source (PM 11-16 07:5x, workflow
# gold_company_r5 used Wikidata to mark which companies have an English Wikipedia article). No daily number is
# published for these, so their day total stays DAILY_TOTAL.
TRUTH_SOURCE_TERMS = {
    'nager.at': {
        'status': 'prohibits',
        'license': 'code MIT (github.com/nager/Nager.Date); the hosted Web API has its own terms',
        'terms': 'The Web API can be used for private or non-profit projects; commercial use requires active '
                 'sponsorship; running a holiday portal of your own on its data is not allowed (terms of 2023-09-15)',
        'terms_url': 'https://nagerholidays.com/legal/termsofservice',
        'limits': 'no number published ("No Rate Limits" on https://nagerholidays.com/Api); date.nager.at redirects there',
        'decision': 'PM 11-16: not used while we earn money; gold_holidays and the holiday role task are on hold',
        'checked': '2026-11-16',
    },
    'wikidata.org': {
        'license': 'CC0 (structured data: main, Property, Lexeme, EntitySchema namespaces)',
        'license_url': 'https://www.wikidata.org/wiki/Wikidata:Licensing',
        'limits': 'query.wikidata.org: 60 s query deadline; 60 s of processing time each 60 s per user agent + IP; '
                  '30 error queries a minute; 5 parallel queries per IP; 429 with Retry-After; no daily cap stated',
        'limits_url': 'https://www.mediawiki.org/wiki/Wikidata_Query_Service/User_Manual',
        'user_agent': 'required (Wikimedia User-Agent policy); ours names AgentValCon and the contact mail',
        'checked': '2026-11-16',
    },
}
DOMAIN_LIMIT_SOURCE = {   # domain -> (published limit, its daily half, where it is published)
    'sec.gov': ('10 requests/second', 432000, 'https://www.sec.gov/os/accessing-edgar-data'),
    'arxiv.org': ('1 request every 3 seconds', 14400, 'https://info.arxiv.org/help/api/tou.html'),
    'met.no': ('total traffic below 20 requests/second', 864000, 'https://api.met.no/doc/TermsOfService'),
    'openalex.org': ('$0.10 a day without a key; searches $1 per 1,000', 50, 'https://help.openalex.org/access/example-costs/'),
}


# PM 11-15 17:16 (user: revenue is the mission; internal rules that block it are fixed): 60 a day is our default. Where
# a provider publishes its limit, our day total is SHARE_OF_DECLARED of it (never above the limit itself, never below
# the default, at most DECLARED_CAP). The limits come from the agent team's terms table: a member's
# "declared_limit": {"domain", "per_day" | "per_minute", "source", "quote"}. A 429 or Retry-After still pauses the
# domain for the day at once (note()).
SHARE_OF_DECLARED = 0.2
DECLARED_CAP = 1000
TERMS_PATH = Path(__file__).resolve().parent / 'necklaces' / 'member_terms.json'
_declared_cache = {'mtime': None, 'map': {}}


def declared(name, path=None):
    """{'per_day', 'per_minute'} a provider publishes for registrable domain NAME (the strictest of its members)."""
    path = Path(path or TERMS_PATH)
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return None
    if path != TERMS_PATH or _declared_cache['mtime'] != mtime:
        found = {}
        try:
            members = (json.loads(path.read_text(encoding='utf-8')).get('members') or {}).values()
        except (OSError, ValueError, AttributeError):
            members = []
        for row in members:
            limit = row.get('declared_limit') if isinstance(row, dict) else None
            if not isinstance(limit, dict) or not limit.get('domain') or not limit.get('source'):
                continue
            entry = found.setdefault(limit['domain'], {})
            for key in ('per_day', 'per_minute'):
                if isinstance(limit.get(key), int) and limit[key] > 0:
                    entry[key] = min(entry.get(key, limit[key]), limit[key])
        if path != TERMS_PATH:
            return found.get(name)
        _declared_cache.update(mtime=mtime, map=found)
    return _declared_cache['map'].get(name)


def published_per_day(name, path=None):
    limit = declared(name, path)
    if not limit:
        return None
    return limit.get('per_day') or (limit['per_minute'] * 1440 if limit.get('per_minute') else None)


def domain_total(name, path=None, day=None, directory=None):
    """Our tests' day total on NAME. PM 17:24: on a declared domain it is 20% of the published limit (at most
    DECLARED_CAP); on a day whose plan holds gate calls there, it rises to those holds, never above the limit."""
    if name in CLOSED_DOMAINS:
        return 0
    if name in DOMAIN_TOTAL:
        return DOMAIN_TOTAL[name]
    per_day = published_per_day(name, path)
    if not per_day:
        return DAILY_TOTAL
    total = min(int(per_day * SHARE_OF_DECLARED), DECLARED_CAP)
    held = sum((plan(day, directory).get(name) or {}).values()) if day else 0
    total = max(total, held)
    limit = declared(name, path) or {}
    return min(total, limit['per_day']) if limit.get('per_day') else total


LIVE_SHARE = 0.8   # PM 17:24: live necklace calls may use a declared provider up to 80% of its day limit


# PM 11-16 21:3x: GDELT answers 429 even to two hand calls a day, and a day-long pause would close Technology News
# (133018's GDELT version) and every necklace news slot until midnight. On these domains a 429 pauses until the next
# full hour instead; the hourly technology-news bundle (one call an hour) keeps the necklace_live count at or under
# LIVE_DAY_CAP. Every other domain keeps the day-long pause.
HOURLY_PAUSE_DOMAINS = {'gdeltproject.org'}
LIVE_DAY_CAP = {'gdeltproject.org': 24}


def _next_hour(now=None):
    now = time.time() if now is None else now
    return (int(now) // 3600 + 1) * 3600


def is_paused(entry, now=None):
    """True while ENTRY's 429 pause holds: all day, or until its 'until' (epoch seconds) on an hourly-pause domain."""
    paused = entry.get('paused')
    if not paused:
        return False
    until = paused.get('until') if isinstance(paused, dict) else None
    return until is None or (time.time() if now is None else now) < until


def live_reserve(url, now=None, directory=None, path=None, default_per_day=None):
    """Count one live necklace call to URL's domain. Refused once our calls of the day (tests and live together) would
    pass 80% of the day limit: the provider's published limit, else DEFAULT_PER_DAY when given (PM 17:32: the public
    run's own cap per undeclared domain, limits.DOMAIN_PER_DAY). The runner then moves the slot to its next member and
    records 'quota_exhausted' (not a failure). Without either limit the call is counted and allowed. One call holds the
    ledger's file lock: about 0.2-0.6 ms (11-15 17:1x, under load 16), exact across processes."""
    name = domain(url)
    if not name:
        return False, 'no_domain'
    per_day = published_per_day(name, path) or default_per_day
    with _ledger(today(now), directory) as data:
        entry = data['domains'].setdefault(name, {'total': 0, 'by': {}})
        if is_paused(entry, now):
            return False, 'paused_429'
        if per_day and entry['total'] + 1 > int(per_day * LIVE_SHARE):
            return False, 'quota_exhausted'
        if name in LIVE_DAY_CAP and entry['by'].get('necklace_live', 0) + 1 > LIVE_DAY_CAP[name]:
            return False, 'quota_exhausted'
        entry['total'] += 1
        entry['by']['necklace_live'] = entry['by'].get('necklace_live', 0) + 1
        return True, 'ok'


# One-day grants (dated, so they end by themselves). 11-15 PM 16:4x / workflow 9da8aa94: the package-risk-audit
# activity answer set needs 27 npm packages x (registry.npmjs.org 1 + api.github.com 1) once.
ONE_DAY = {'20261116': {('reference_checks', 'npmjs.org'): 30, ('reference_checks', 'github.com'): 30,
                        # agent team (PM 11-16 15:12): output adapter check, 10 read-only calls to each of two
                        # topic-evidence-brief members on the used holdout-r3 set, 15 s apart, before 21:00
                        ('adhoc', 'mosaiden.com'): 10, ('adhoc', 'onekivo.vercel.app'): 10,
                        # workflow 0555a3b5: topic-evidence-brief holdout-r3, one OpenAlex read a topic (39 topics)
                        ('reference_checks', 'openalex.org'): 60,    # PM 06:5x: all of the 50 (60 x 50 // 60)
                        # workflow gold_company_r5 (PM 11-16 07:4x, company gate restarts on a fresh set): up to 95
                        # SEC reads; 90 of the usual 100 went to holdout-r4, so 200 today (20 x 600 // 60), total 600
                        ('reference_checks', 'sec.gov'): 20,
                        # PM 11-16 12:3x: holdout-r5-wiki (wikipedia-summary re-gate with SEC upper-case company names)
                        # needs ~40 more reads after the 166 were spent; 13 x 1000 // 60 = 216. Wikipedia's total of
                        # 1000 comes from its declared 200 a minute (mediawiki.org/wiki/Wikimedia_APIs/Rate_limits, member_terms)
                        ('reference_checks', 'wikipedia.org'): 13},
            # workflow 3737c5aa: cve-incident-brief fix answer set, one GitHub advisory read a CVE. The day total of
            # 60 per domain stays (PM 16:25), so 50 of the 90 asked; the open-source records are read first.
            '20261117': {('reference_checks', 'github.com'): 50,
                         # PM 11-16 18:0x: mcp-registry own-substitute gate (30 cases). No request limit is published;
                         # the registry's aggregator guide asks clients to cache, avoid a full crawl per user request and
                         # back off (github.com/modelcontextprotocol/registry docs/modelcontextprotocol-io/registry-aggregators.mdx,
                         # read 11-16), so the day total stays the default 60 and the gate's 30 fits inside it.
                         ('substitute_tests', 'modelcontextprotocol.io'): 30,
                         # workflow cdccd97e: topic-evidence-brief holdout-r4, the 29 OpenAlex reads left of 41 topics
                         ('reference_checks', 'openalex.org'): 60,    # holdout-r4 rest and r5 (PM 06:5x)
                         # workflow 11-16 12:4x: three company sets on 11-17 read SEC (holdout-r6 for sec-company-profile,
                         # holdout-r7 for company v3, wikipedia-summary re-gate companies), 1-2 reads a company, 90-160
                         # in all; 20 x 600 // 60 = 200, inside sec.gov's checked total of 600
                         ('reference_checks', 'sec.gov'): 20,
                         # workflow 11-16 (PM 16:2x approved +60): 11-17 answer-set builds read Wikipedia about 220 times
                         # (article answers ~55, re-check full-text searches ~115, batch lookups). The share moves in
                         # steps of 16 here (x 1000 // 60), so 13 gives 216 (+50, inside the approval); the gate holds
                         # and substitute_tests (500) on wikipedia.org are unchanged, and 216 + 500 stays under 1000.
                         ('reference_checks', 'wikipedia.org'): 13},
            # PM 11-16 18:3x: topic v2 answer sets (holdout-r6 on 11-18, holdout-r7 on 11-19), one OpenAlex search a topic
            # in the builder's fixed order. 46 x 50 // 60 = 38 and 48 x 50 // 60 = 40; the gate keeps 12 and 10 in the
            # plan files for the papers step's own fallback (v1 live retests, v2 rounds). r6 short of 30 at 38 reads:
            # the v2 gate moves a day, no more reads.
            '20261118': {('reference_checks', 'openalex.org'): 46},
            '20261119': {('reference_checks', 'openalex.org'): 48}}
# GitHub's hourly reference_checks share on those days, in the night hours only (00-07 KST), when live answers are few.
ONE_NIGHT_GITHUB = {'20261116': {'reference_checks': 10}, '20261117': {'reference_checks': 10}, '20261118': {'reference_checks': 30}}
# PM 11-16 (가), from 11-18: the test family (every system but fallback_live) takes at most GITHUB_TEST_HOURLY calls an
# hour and GITHUB_TEST_DAILY a day, inside the shared 55, so live answers come first. Hours granted on purpose are
# outside both: the night grants above (11-18 00-07: workflow's N2 answer set, about 90 repo reads) and the gate hours
# below, where the gate may take its round (about 30 a round: N2 repo slot 11-19, cve fix slot 11-21, workflow 21:3x)
# and the other test systems wait; live answers still share what is left of the 55 in that hour.
GITHUB_TEST_FROM = '20261118'
GITHUB_TEST_HOURLY = 12
GITHUB_TEST_DAILY = 120
GATE_HOURS_GITHUB = {'2026111813': 30,                          # github-repo substitute gate 13:10
                     '2026111911': 32, '2026111916': 32,        # mcp-server-trust-check rounds 11:10, 16:10
                     '2026112108': 32, '2026112112': 32}        # cve-incident-brief v2 rounds 08:10, 12:10


def share_limit(system, name, day=None, directory=None):
    if system == 'cassettes' and (day or today()).replace('-', '') > CASSETTES_UNTIL:
        return 0
    base = (ONE_DAY.get(day or '', {}).get((system, name)) or CASSETTE_OVERRIDE.get((system, name))
            or SHARE_OVERRIDE.get((system, name), SHARE[system]))
    total = domain_total(name, day=day, directory=directory)
    if system == 'gate':
        return total
    share = max(1, base * total // DAILY_TOTAL) if base else 0
    if system == 'role_tests' and total >= ROLE_TEST_MIN:
        share = max(share, ROLE_TEST_MIN)
    return share


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


# PM 11-15 16:03 (user: revenue first, gates do not wait): on a day plan, calls planned for a higher-priority use
# are kept for it. gate (necklace launch rounds and substitute gate rounds) > substitute_tests (approval work) >
# pearl and role tests, answer-key references and the rest > necklace_retest. A plan is
# <ledger dir>/plan-<day>.json {"holds": {domain: {system: calls}}}; a system may not take what a higher one still
# needs of its hold that day. With no plan the ledger behaves as before (first come, first served).
PRIORITY = {'gate': 0, 'substitute_tests': 1, 'necklace_retest': 3}
DEFAULT_PRIORITY = 2


def priority(system):
    return PRIORITY.get(system, DEFAULT_PRIORITY)


def plan(day=None, directory=None):
    path = Path(directory or DIR) / f'plan-{day or today()}.json'
    try:
        holds = json.loads(path.read_text()).get('holds') or {}
    except (OSError, ValueError, AttributeError):
        return {}
    return {d: {s: int(n) for s, n in (v or {}).items() if s in SHARE} for d, v in holds.items() if isinstance(v, dict)}


def held_for_others(entry, holds, system):
    """Calls on this domain still kept today for systems above SYSTEM (what they planned minus what they used)."""
    mine = priority(system)
    return sum(max(0, n - entry['by'].get(s, 0)) for s, n in holds.items() if priority(s) < mine)


def reserve(url, system, n=1, now=None, directory=None):
    """Count N calls of SYSTEM to URL's domain if today's limits allow them. Returns (ok, reason)."""
    if system not in SHARE:
        raise ValueError(f'unknown system {system!r}; add it to provider_budget.SHARE')
    name = domain(url)
    if not name:
        return False, 'no_domain'
    with _ledger(today(now), directory) as data:
        entry = data['domains'].setdefault(name, {'total': 0, 'by': {}})
        if is_paused(entry, now):
            return False, 'paused_429'
        used = entry['by'].get(system, 0)
        if entry['total'] + n > domain_total(name, day=today(now), directory=directory):
            return False, 'domain_daily_total'
        if entry['total'] + n + held_for_others(entry, plan(today(now), directory).get(name, {}), system) > domain_total(name, day=today(now), directory=directory):
            return False, 'held_for_higher_priority'
        if used + n > share_limit(system, name, today(now), directory):
            return False, 'system_share'
        entry['total'] += n
        entry['by'][system] = used + n
        return True, 'ok'


def release(url, system, n=1, day=None, directory=None):
    """Give back N calls of SYSTEM that reserve() counted but that never left our side (our relay's pace or slots,
    our edge full, our deadline): source review 11-16, the count ran down faster than the calls really made. Only
    what SYSTEM itself took that day is given back, never below zero. Returns the number given back."""
    name = domain(url)
    if not name or n <= 0:
        return 0
    with _ledger(day or today(), directory) as data:
        entry = data['domains'].get(name)
        if not entry:
            return 0
        back = min(n, entry['by'].get(system, 0), entry.get('total', 0))
        if back:
            entry['by'][system] -= back
            entry['total'] -= back
            entry['released'] = entry.get('released', 0) + back
        return back


# Hosts whose answers are ours (relay, edge, fallbacks): a 429 from them is our own pace, never a provider's.
OUR_DOMAINS = ('agentconcierge.biz',)
PROVIDER_HTTP = 'provider_http'      # the status came on a response from the provider's own host, called directly
PROVIDER_RPC = 'provider_rpc'        # our relay passed on the provider's own pause (JSON-RPC error with retry_after)


def pause_evidence(url, evidence):
    """(kept evidence, None) when a 429 may pause the domain, else (None, why). The ledger's gatekeeper (PM 11:5x,
    11-15): twice (11-14 05:11, 11-15 11:42) our relay's own 429 was written as a provider's and paused providers
    for every system for the day, so a pause now needs the caller to say where the 429 came from."""
    origin = evidence if isinstance(evidence, str) else (evidence or {}).get('origin')
    if domain(url) in OUR_DOMAINS:
        return None, 'our_host'
    if origin == PROVIDER_HTTP:
        return {'origin': PROVIDER_HTTP}, None
    if origin == PROVIDER_RPC and isinstance(evidence, dict):
        retry = evidence.get('retry_after')
        message = str(evidence.get('message') or '').strip()[:200]
        if isinstance(retry, (int, float)) and not isinstance(retry, bool) or message:
            return {'origin': PROVIDER_RPC, 'retry_after': retry, 'message': message}, None
    return None, 'no_evidence'


def note(url, system, status, now=None, directory=None, evidence=None):
    """Record a provider answer. A 429 pauses the domain for every system for the rest of the day, but only with
    evidence that the provider sent it (pause_evidence); a request without it is refused, recorded on the domain
    as pause_refused and logged, and the domain stays open. Returns True when the domain was paused."""
    if status != 429:
        return False
    name = domain(url)
    stamp = datetime.fromtimestamp(time.time() if now is None else now, KST).strftime('%H:%M:%S')
    kept, why = pause_evidence(url, evidence)
    with _ledger(today(now), directory) as data:
        entry = data['domains'].setdefault(name, {'total': 0, 'by': {}})
        if why:
            refused = entry.setdefault('pause_refused', {'count': 0})
            refused['count'] += 1
            refused['last'] = {'at': stamp, 'by': system, 'why': why}
        else:
            entry['paused'] = {'at': stamp, 'by': system, 'evidence': kept}
            if name in HOURLY_PAUSE_DOMAINS:
                entry['paused']['until'] = _next_hour(now)
    if why:
        log.warning('provider_budget: pause of %s by %s refused (%s)', name, system, why)
        return False
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
    'reference_checks': 2,
    'gate': GITHUB_HOURLY - GITHUB_FLOOR,   # whatever is left
}


def github_share(system, now=None):
    stamp = hour(now)
    night = ONE_NIGHT_GITHUB.get(stamp[:8], {}).get(system) if int(stamp[8:]) < 8 else None
    return night or GITHUB_SHARE[system]


def hour(now=None):
    return datetime.fromtimestamp(time.time() if now is None else now, KST).strftime('%Y%m%d%H')


def _test_calls(entry):
    return sum(v for k, v in (entry.get('by') or {}).items() if k != 'fallback_live')


def _github_test_rule(system, n, entry, now, directory=None):
    """None when SYSTEM's N calls fit the test-family rule (PM (가), from GITHUB_TEST_FROM), else the reason."""
    stamp = hour(now)
    if system == 'fallback_live' or stamp[:8] < GITHUB_TEST_FROM:
        return None
    gate_cap = GATE_HOURS_GITHUB.get(stamp)
    if gate_cap is not None:
        if system != 'gate':
            return 'github_gate_hour'
        return 'github_gate_hour_cap' if _test_calls(entry) + n > gate_cap else None
    if int(stamp[8:]) < 8 and ONE_NIGHT_GITHUB.get(stamp[:8], {}).get(system):
        return None                                           # a night grant: its own share is the limit
    if _test_calls(entry) + n > GITHUB_TEST_HOURLY:
        return 'github_test_hourly'
    used = 0
    for path in Path(directory or DIR).glob(f'github-{stamp[:8]}??.json'):
        other = path.stem[len('github-'):]
        if other == stamp or other in GATE_HOURS_GITHUB or (int(other[8:]) < 8 and ONE_NIGHT_GITHUB.get(other[:8])):
            continue
        try:
            used += _test_calls(json.loads(path.read_text()).get('github') or {})
        except (OSError, ValueError):
            continue
    return 'github_test_daily' if used + _test_calls(entry) + n > GITHUB_TEST_DAILY else None


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
        elif entry['by'].get(system, 0) + n > github_share(system, now):
            why = 'system_share'
        else:
            why = _github_test_rule(system, n, entry, now, directory)
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
                      'paused': sorted(d for d, e in data['domains'].items() if is_paused(e)),
                      'top': {d: e for d, e in rows}}, ensure_ascii=False, indent=1))


if __name__ == '__main__':
    main()
