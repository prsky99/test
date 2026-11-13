"""Data quality of a role test answer (PM 11-14, reports/pearl-audit-2026-11-14/data-quality.md).

Data 60: accuracy 25 (an answer set or a public reference at the same time; no answer source -> 0), freshness 10
(per-role age rules; no time stamp -> 0), completeness 10 (null / N/A / empty share), cleanliness 10 (demo,
placeholder, error text, payment demand, cut answer or broken encoding fails the version), consistency 5 (a fixed
fact gives the same answer on another day). Evidence 30: arguments 10, successes on different days 10, latency 10.
Report text 10. Judged on the whole answer (up to 20 KB).
"""
import datetime as dt
import json
import re
import time

# Freshness per role: ('age', days) newest data time within N days; ('future',) a date today or later;
# ('now', minutes) a clock time of now. Roles not listed state fixed facts: freshness does not apply (full points).
FRESHNESS = {
    'news.search.v1': ('age', 7), 'software.incident.v1': ('age', 7),
    'fx.rate.v1': ('age', 2), 'crypto.price.v1': ('age', 2), 'stock.quote.v1': ('age', 2),
    'weather.forecast.v1': ('future',), 'events.search.v1': ('future',),
    'cve.exploited.v1': ('age', 1), 'cve.record.v1': ('age', 1),
    'earthquake.feed.v1': ('age', 30), 'timezone.time.v1': ('now', 5),
}
DYNAMIC_ROLES = set(FRESHNESS)          # answers change over time; consistency is about format, not equality

MONTHS = 'jan feb mar apr may jun jul aug sep oct nov dec'.split()
ISO = re.compile(r'\b((?:19|20)\d{2})-(\d{2})-(\d{2})(?:[T ](\d{2}):(\d{2}))?')
LONG = re.compile(r'\b(' + '|'.join(MONTHS) + r')[a-z]*\.? (\d{1,2}),? ((?:19|20)\d{2})\b', re.I)
EPOCH = re.compile(r'(?<![\d.])(1[6-9]\d{8}|1[6-9]\d{11})(?![\d.])')
CLOCK = re.compile(r'\b([01]?\d|2[0-3]):([0-5]\d)\b')

UNCLEAN = {
    'demo or placeholder': re.compile(r'\[demo\]|\bdemo (?:mode|data|response|backend)\b|\bsample (?:data|response|output)\b|'
                                      r'\bmock(?:ed)? (?:data|response)\b|\bplaceholder\b|lorem ipsum|\bexample\.(?:com|org)\b|'
                                      r'\bTODO\b|<your[_ -]', re.I),
    'error text': re.compile(r'^\W*(?:error|exception)\b|"error"\s*:\s*(?:"|\{)|\btraceback\b|internal server error|'
                             r'stack trace|\bundefined is not\b|\bnull pointer\b', re.I | re.M),
    'payment demand': re.compile(r'payment required|\bx402\b|upgrade (?:your )?plan|subscribe to (?:continue|access)|'
                                 r'api key (?:is )?required|insufficient (?:credits|balance)|purchase credits', re.I),
    'cut answer': re.compile(r'(?:\.\.\.|…)\s*$|\btruncated\b', re.I),
    'broken encoding': re.compile(r'�|Ã[©¨¼¶¤]|â€[™œ\x9d“”]'),
}
BLANK_TEXT = re.compile(r':\s*(?:null|""|\[\]|\{\}|"n/?a"|"unknown"|"none")\s*[,}]|\bN/A\b', re.I)


def dates_in(text, now=None):
    """Every data time stated in the answer (ISO dates, 'Nov 14, 2026', epoch seconds or milliseconds)."""
    found = []
    for m in ISO.finditer(text or ''):
        try:
            found.append(dt.datetime(int(m[1]), int(m[2]), int(m[3]), int(m[4] or 0), int(m[5] or 0)))
        except ValueError:
            pass
    for m in LONG.finditer(text or ''):
        try:
            found.append(dt.datetime(int(m[3]), MONTHS.index(m[1][:3].lower()) + 1, int(m[2])))
        except ValueError:
            pass
    for m in EPOCH.finditer(text or ''):
        value = int(m[1])
        value = value / 1000 if value > 10 ** 11 else value
        if 1.6e9 <= value <= (now or time.time()) + 400 * 86400:
            found.append(dt.datetime.fromtimestamp(value))
    return found


def freshness(role, text, now=None):
    """(points of 10, rule, newest data time or None)."""
    rule = FRESHNESS.get(role)
    if rule is None:
        return 10, 'fixed facts', None
    now_dt = dt.datetime.fromtimestamp(now or time.time())
    dates = dates_in(text, now)
    if rule[0] == 'now':
        clock = CLOCK.search(text or '')
        return (10 if clock else 0), 'a clock time of now', None
    if not dates:
        return 0, f'{rule[0]} {rule[1:]}', None
    newest = max(dates)
    if rule[0] == 'future':
        ok = any(d.date() >= now_dt.date() for d in dates)
        return (10 if ok else 0), 'today or later', newest.isoformat(timespec='minutes')
    days = rule[1] + (2 if now_dt.weekday() in (0, 6) and role in ('fx.rate.v1', 'stock.quote.v1') else 0)  # weekend close
    ok = (now_dt - newest).total_seconds() <= days * 86400 and newest <= now_dt + dt.timedelta(days=1)
    return (10 if ok else 0), f'within {days} days', newest.isoformat(timespec='minutes')


def _leaves(value, out):
    if isinstance(value, dict):
        if not value:
            out.append(None)
        for item in value.values():
            _leaves(item, out)
    elif isinstance(value, list):
        if not value:
            out.append(None)
        for item in value[:200]:
            _leaves(item, out)
    else:
        out.append(value)


def completeness(text, structured=None):
    """(points of 10, blank fields, fields): null, empty, N/A and unknown values lower the score by their share."""
    data = structured
    if data is None:
        try:
            data = json.loads(text) if text and text.lstrip()[:1] in '{[' else None
        except ValueError:
            data = None
    if data is not None:
        leaves = []
        _leaves(data, leaves)
        blanks = sum(1 for v in leaves if v is None or (isinstance(v, str) and v.strip().lower() in ('', 'n/a', 'na', 'unknown', 'none', 'null', '-')))
        total = max(1, len(leaves))
        return round(10 * (1 - blanks / total), 1), blanks, total
    blanks = len(BLANK_TEXT.findall(text or ''))
    return max(0, 10 - 2 * blanks), blanks, None


def clean_issues(text):
    return [name for name, pattern in UNCLEAN.items() if pattern.search(text or '')]


def _numbers(text):
    return [float(n.replace(',', '')) for n in re.findall(r'-?\d{1,3}(?:,\d{3})+(?:\.\d+)?|-?\d+(?:\.\d+)?', text or '')]


def _fetch_json(url):
    import httpx
    resp = httpx.get(url, timeout=10, headers={'User-Agent': 'AgentConcierge-Verification/1.0'})
    return resp.json() if resp.status_code == 200 else None


_CACHE = {}


def reference(kind, url):
    """A public reference value at test time (cached ten minutes): fx rate, current temperature, latest version."""
    key = (kind, url)
    if key in _CACHE and time.time() - _CACHE[key][0] < 600:
        return _CACHE[key][1]
    value = None
    try:
        data = _fetch_json(url)
        if kind == 'rate':
            value = float(next(iter((data or {}).get('rates', {}).values())))
        elif kind == 'temperature_c':
            value = float(data['current']['temperature_2m'])
        elif kind == 'latest_version':
            value = str(data['version'])
    except Exception:
        value = None
    _CACHE[key] = (time.time(), value)
    return value


def dynamic_match(kind, ref, text, case_input=None, tolerance=None):
    if ref is None:
        return None
    if kind == 'rate':
        amount = float((case_input or {}).get('amount') or 1)
        tol = tolerance or 0.02
        return any(abs(n - t) <= tol * t for n in _numbers(text) if n > 0 for t in (ref, ref * amount))
    if kind == 'temperature_c':
        tol = tolerance or 3
        temps = [float(m[1]) if (m[2] or 'c').lower() == 'c' else (float(m[1]) - 32) * 5 / 9
                 for m in re.finditer(r'(-?\d+(?:\.\d+)?)\s*°?\s*([CF])?\b', text or '') if '°' in m[0] or m[2]]
        temps += [float(m[1]) for m in re.finditer(r'"?temp(?:erature)?(?:_2m|_c)?"?\s*[:=]\s*(-?\d+(?:\.\d+)?)', text or '', re.I)]
        return any(abs(t - ref) <= tol for t in temps)
    if kind == 'latest_version':
        return ref in (text or '')
    return None


def accuracy(case, text, structured, live=None, live_value=None, role_tasks=None):
    """(points of 25, source, detail). Only an answer set or a same-time public reference can give points."""
    if case:
        expect = case.get('expect') or {}
        static_keys = [k for k in expect if k not in ('dynamic', 'published_within_days')]
        passed, reasons = role_tasks.score(case, text, structured) if role_tasks else (False, ['no scorer'])
        if expect.get('kev_date_added') and expect['kev_date_added'] not in (text or ''):
            passed, reasons = False, reasons + [f"KEV date {expect['kev_date_added']} missing"]
        checks = []
        for kind, url in (expect.get('dynamic') or {}).items():
            if kind == 'tolerance':
                continue
            ok = dynamic_match(kind, reference(kind, url), text, case.get('input'), expect['dynamic'].get('tolerance'))
            checks.append((kind, url, ok))
        dynamic_ok = all(ok for _, _, ok in checks) if checks else None
        if checks and any(ok is None for _, _, ok in checks):
            return 0, f"answer set {case['case_id']} (live reference unavailable)", reasons
        if not static_keys and not checks:
            return 0, f"answer set {case['case_id']} (live-only expectation not checkable)", reasons
        good = passed and (dynamic_ok is not False)
        source = f"answer set {case['case_id']}" + (f" + live {', '.join(k for k, _, _ in checks)}" if checks else '')
        return (25 if good else 0), source, reasons + [f'{k} off the reference' for k, _, ok in checks if ok is False]
    if live:
        if live_value is None:
            return 0, f"public reference {live['reference']} (unavailable)", []
        ok = any(abs(n - live_value) <= live['tolerance'] * live_value for n in _numbers(text) if n > 0)
        return (25 if ok else 0), f"public reference {live['reference']} = {live_value:g}", [] if ok else ['off the reference']
    return 0, 'none (no answer set or public reference yet)', []


def latency_points(ms):
    if ms is None:
        return 0
    return 10 if ms <= 1000 else 8 if ms <= 2000 else 5 if ms <= 5000 else 2 if ms <= 10000 else 0
