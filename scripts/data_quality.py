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

# Points of each data-quality item (methodology v1 reads these; change them here only).
WEIGHTS = {'accuracy': 25, 'freshness': 10, 'completeness': 10, 'clean': 10, 'consistency': 5}
EVIDENCE_WEIGHTS = {'arguments': 10, 'repeat': 10, 'latency': 10}
WRITING_WEIGHT = 10
LATENCY_STEPS = ((1000, 10), (2000, 8), (5000, 5), (10000, 2))   # ms -> points (of EVIDENCE_WEIGHTS['latency'])

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


# F02 (current-state review 11-14): a date counts only by what it states. Each role names the kind of time that
# measures its freshness; a retrieval or generation time ("Retrieved 2026-11-14") says nothing about the data, and a
# date with no label is not trusted (unconfirmed, 0 points). A clock is judged by its deviation from the actual time
# in the named time zone.
KIND_OF = {
    'news.search.v1': 'published', 'software.incident.v1': 'published', 'cve.record.v1': 'observed',
    'cve.exploited.v1': 'observed', 'fx.rate.v1': 'observed', 'crypto.price.v1': 'observed',
    'stock.quote.v1': 'observed', 'earthquake.feed.v1': 'observed', 'weather.forecast.v1': 'valid',
    'events.search.v1': 'valid', 'timezone.time.v1': 'clock',
}
LABELS = {   # a label in the 40 characters before a date names its kinds; a retrieval label overrides the rest
    'retrieved': r'retriev\w*|fetched|accessed|requested|queried|generated|response[_ ]time|server[_ ]time|cached',
    'published': r'publish\w*|posted|released|pub[_ ]?date|date[_ ]published|created|reported|date[_ ]added|disclosed',
    'observed': r'as[_ ]of|observed|last[_ ]?updated|updated|timestamp|refreshed|quote[_ ]time|rate[_ ]date|time|date|on|at',
    'valid': r'valid\w*|forecast[_ ]?(?:for|time|date)?|starts?|start[_ ]?date|from|on|time|date|when',
}
KEY_KIND = [   # structured answers: a key name says which time it is
    ('retrieved', re.compile(r'retriev|fetched|accessed|requested|generated|server_?time|cached', re.I)),
    ('published', re.compile(r'publish|posted|released|pub_?date|created|date_?added|reported|disclosed', re.I)),
    ('observed', re.compile(r'as_?of|observed|updated|timestamp|refreshed|quote_?time|^time$|^date$|^datetime$', re.I)),
    ('valid', re.compile(r'valid|forecast|start|^time$|^date$|^datetime$|when', re.I)),
]
TZ_NAME = re.compile(r'\b((?:Africa|America|Antarctica|Asia|Atlantic|Australia|Europe|Indian|Pacific)/[A-Za-z_]+(?:/[A-Za-z_]+)?|UTC)\b')


def _label_kinds(before):
    kinds = [kind for kind, pattern in LABELS.items() if re.search(r'\b(?:' + pattern + r')\W{0,12}$', before, re.I)]
    return ['retrieved'] if 'retrieved' in kinds else kinds


def labelled_dates(text, now=None):
    """[(kinds, datetime)] for every date in TEXT, named by the label just before it ([] when unlabelled)."""
    out = []
    for pattern in (ISO, LONG):
        for m in pattern.finditer(text or ''):
            found = dates_in(m.group(0), now)
            if found:
                out.append((_label_kinds((text or '')[max(0, m.start() - 40):m.start()]), found[0]))
    return out


def _keyed_dates(value, now, out, key=None):
    if isinstance(value, dict):
        for k, v in value.items():
            _keyed_dates(v, now, out, str(k))
    elif isinstance(value, list):
        for item in value[:200]:
            _keyed_dates(item, now, out, key)
    elif key is not None and isinstance(value, (str, int, float)) and not isinstance(value, bool):
        found = dates_in(str(value), now)
        if found:
            kinds = [kind for kind, pattern in KEY_KIND if pattern.search(key)]
            out.append((kinds, found[0]))


def _clock(text, structured, args, now):
    """(points, rule, stated time) for a clock answer: the stated time against the actual time in the named zone."""
    import zoneinfo
    names = [str(v) for v in (args or {}).values() if isinstance(v, str)] + TZ_NAME.findall(text or '')
    zone = next((n for n in names if TZ_NAME.fullmatch(n)), None)
    if zone is None:
        return 0, 'a clock time of now in the named zone (zone not stated: unconfirmed)', None
    try:
        actual = dt.datetime.fromtimestamp(now, zoneinfo.ZoneInfo(zone))
    except Exception:
        return 0, 'a clock time of now in the named zone (unknown zone: unconfirmed)', None
    stamps = []
    for m in ISO.finditer(text or ''):
        if m[4] is not None:
            stamps.append((int(m[4]), int(m[5])))
    if not stamps:
        stamps = [(int(m[1]), int(m[2])) for m in CLOCK.finditer(text or '')]
    if not stamps:
        return 0, 'a clock time of now (no time stated)', None
    minutes = actual.hour * 60 + actual.minute
    best = min(min(abs(h * 60 + mi - minutes), 1440 - abs(h * 60 + mi - minutes)) for h, mi in stamps)
    limit = FRESHNESS['timezone.time.v1'][1]
    return (WEIGHTS['freshness'] if best <= limit else 0), f'clock within {limit} minutes of {zone}', f'{best} min off'


def freshness(role, text, now=None, structured=None, args=None):
    """(points of 10, rule, newest data time or None). Only times of the role's own kind count."""
    rule = FRESHNESS.get(role)
    if rule is None:
        return WEIGHTS['freshness'], 'fixed facts', None
    now = now or time.time()
    now_dt = dt.datetime.fromtimestamp(now)
    if rule[0] == 'now':
        return _clock(text, structured, args, now)
    kind = KIND_OF.get(role)
    data = structured
    if data is None:
        try:
            data = json.loads(text) if text and text.lstrip()[:1] in '{[' else None
        except ValueError:
            data = None
    if data is not None:
        keyed = []
        _keyed_dates(data, now, keyed)
        dates = [d for kinds, d in keyed if kind in kinds and kinds[0] != 'retrieved']
    else:
        dates = [d for kinds, d in labelled_dates(text, now) if kind in kinds]
    if not dates:
        return 0, f'{kind} time not stated (unconfirmed)', None
    newest = max(dates)
    if any(d > now_dt + dt.timedelta(days=1) for d in dates) and rule[0] != 'future':
        return 0, f'{kind} time in the future', newest.isoformat(timespec='minutes')
    if rule[0] == 'future':
        ok = any(d.date() >= now_dt.date() for d in dates)
        return (WEIGHTS['freshness'] if ok else 0), f'{kind} time today or later', newest.isoformat(timespec='minutes')
    days = rule[1] + (2 if now_dt.weekday() in (0, 6) and role in ('fx.rate.v1', 'stock.quote.v1') else 0)  # weekend close
    ok = (now_dt - newest).total_seconds() <= days * 86400
    return (WEIGHTS['freshness'] if ok else 0), f'{kind} time within {days} days', newest.isoformat(timespec='minutes')


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


# F03 (current-state review 11-14): completeness is the share of the role's required output found in the answer,
# times the share of non-blank values, times the items returned against the items asked for. The required fields
# follow the workflow contracts (agent_market/necklaces/contracts/<role>.json output_schema); a provider answers in its
# own words, so each field is found by the key names that mean it. A legitimate empty search (an empty list, no error)
# is complete; an empty or error answer is not. A role without required fields here is unconfirmed (0).
REQUIRED_OUTPUT = {
    'fx.rate.v1': ('from', 'to', 'rate'), 'crypto.price.v1': ('price',), 'stock.quote.v1': ('price',),
    'cve.record.v1': ('cve_id',), 'cve.exploited.v1': ('cve_id', 'kev'),
    'news.search.v1': ('items', 'title', 'url'), 'events.search.v1': ('items', 'title', 'date'),
    'package.advisories.v1': ('items', 'id'), 'papers.search.v1': ('items', 'title'),
    'software.incident.v1': ('items', 'title'), 'weather.forecast.v1': ('temperature',),
    'encyclopedia.summary.v1': ('title', 'summary'), 'country.indicator.v1': ('country', 'indicator', 'value'),
    'company.registry.v1': ('legal_name', 'identifiers'), 'website.ai_readiness.v1': ('domain', 'signals'),
    'timezone.time.v1': ('time',), 'geocode.address.v1': ('lat', 'lon'), 'earthquake.feed.v1': ('items', 'magnitude'),
    'ip.lookup.v1': ('ip', 'country'), 'airport.lookup.v1': ('code', 'name'), 'book.search.v1': ('items', 'title'),
    'dictionary.define.v1': ('definition',), 'domain.lookup.v1': ('domain',), 'github.repo.v1': ('name', 'stars'),
    'holiday.calendar.v1': ('items', 'date', 'name'), 'place.search.v1': ('items', 'name'),
    'sec.filings.v1': ('items', 'form', 'date'), 'translate.text.v1': ('translation',),
    'unit.convert.v1': ('value',), 'package.health.v1': ('name', 'version'), 'package.risk.v1': ('name',),
    'web.grounding.v1': ('answer', 'sources'),
}
FIELD_KEYS = {
    'from': r'^(?:from|base|source_?currency|base_?code)$', 'to': r'^(?:to|target|symbols?|quote_?currency|target_?code)$',
    'rate': r'rate|^value$|conversion|^result$|^price$', 'price': r'price|^usd$|^last$|^close$|^rate$|^value$|amount',
    'cve_id': r'^cve(?:_?id)?$|^id$', 'kev': r'kev|known_?exploited|exploited', 'title': r'title|^name$|headline',
    'url': r'url|link|href', 'date': r'date|^start|^time$|when', 'id': r'^id$|ghsa|^cve|identifier',
    'temperature': r'temp', 'summary': r'summary|extract|description|abstract', 'country': r'country|economy',
    'indicator': r'indicator|series', 'value': r'^value$|amount|^result$', 'legal_name': r'legal_?name|entity_?name|^name$',
    'identifiers': r'^lei$|identifier|^cik$|registration', 'domain': r'domain|host', 'signals': r'signal|checks?|score',
    'time': r'time|datetime', 'lat': r'^lat(?:itude)?$', 'lon': r'^(?:lon|lng|longitude)$', 'magnitude': r'^mag',
    'ip': r'^ip(?:_?address)?$|^query$', 'code': r'iata|icao|^code$', 'name': r'name', 'definition': r'definition|meaning',
    'stars': r'star', 'form': r'^form|filing_?type', 'translation': r'translat|^text$|^result$', 'version': r'version',
    'answer': r'answer|^text$|content', 'sources': r'sources|citations|references|links',
}
ERROR_KEY = re.compile(r'^(?:error|errors|err|exception|fault)$', re.I)
COUNT_ARGS = re.compile(r'^(?:limit|max_results|num_results|count|top_k|per_page|n)$', re.I)


def _keys(value, out, lists):
    if isinstance(value, dict):
        for k, v in value.items():
            out.add(str(k))
            if isinstance(v, list):
                lists.append(v)
            _keys(v, out, lists)
    elif isinstance(value, list):
        lists.append(value)
        for item in value[:200]:
            _keys(item, out, lists)


META_KEYS = re.compile(r'^(?:query|q|source|total|count|page|per_page|status|message|took|next|cursor|limit|offset)$', re.I)


def _empty_search(data):
    """An answer that says 'no results' and nothing else: an empty list, or only empty lists and counters."""
    if data == []:
        return True
    if not isinstance(data, dict) or not any(isinstance(v, list) for v in data.values()):
        return False
    for k, v in data.items():
        if isinstance(v, list):
            if v:
                return False
        elif not (META_KEYS.match(str(k)) and (v in (0, None, '') or isinstance(v, (str, int)))):
            return False
    return True


def completeness(text, structured=None, role=None, args=None):
    """(points of 10, blank fields, fields, detail) against the role's required output."""
    required = REQUIRED_OUTPUT.get(role)
    data = structured
    if data is None:
        try:
            data = json.loads(text) if text and text.lstrip()[:1] in '{[' else None
        except ValueError:
            data = None
    if not required:
        return 0, 0, None, 'no required output for this role (unconfirmed)'
    if data is None and not (text or '').strip():
        return 0, 0, 0, 'empty answer'
    if data is not None:
        keys, lists = set(), []
        _keys(data, keys, lists)
        if any(ERROR_KEY.match(k) for k in keys) and not any(v for v in lists):
            return 0, 0, 0, 'error answer'
        if 'items' in required and _empty_search(data):
            return WEIGHTS['completeness'], 0, 0, 'no results (a legitimate empty search)'
        fields = [f for f in required if f != 'items']
        found = [f for f in fields if any(re.search(FIELD_KEYS.get(f, '^' + f + '$'), k, re.I) for k in keys)]
        if 'items' in required:
            fields, found = ['items'] + fields, (['items'] if any(len(v) for v in lists) else []) + found
        leaves = []
        _leaves(data, leaves)
        blanks = sum(1 for v in leaves if v is None or (isinstance(v, str) and v.strip().lower() in ('', 'n/a', 'na', 'unknown', 'none', 'null', '-')))
        blank_share = blanks / max(1, len(leaves))
        asked = next((int(v) for k, v in (args or {}).items() if COUNT_ARGS.match(str(k)) and isinstance(v, int) and v > 0), None)
        got = max((len(v) for v in lists), default=0)
        count_share = min(1.0, got / asked) if asked and 'items' in required else 1.0
        share = len(found) / len(fields)
        points = round(WEIGHTS['completeness'] * share * (1 - blank_share) * count_share, 1)
        missing = [f for f in fields if f not in found]
        return points, blanks, len(fields), ('missing ' + ', '.join(missing)) if missing else 'required output present'
    # A text answer has no paths: the caller judges it by the role's own fact checks (report_v2.judge).
    return None, len(BLANK_TEXT.findall(text or '')), len([f for f in required if f != 'items']), 'text answer: role checks'


def clean_issues(text):
    return [name for name, pattern in UNCLEAN.items() if pattern.search(text or '')]


def _numbers(text):
    return [float(n.replace(',', '')) for n in re.findall(r'-?\d{1,3}(?:,\d{3})+(?:\.\d+)?|-?\d+(?:\.\d+)?', text or '')]


UA = 'AgentConcierge-Verification/1.0 contact@agentconcierge.biz'   # MET Norway requires a contact in the User-Agent
MET = 'https://api.met.no/weatherapi/locationforecast/2.0/compact?lat={lat}&lon={lon}'
# The source of an answer is never used to judge that same answer (PM 11-14: MET Norway is also a tested member).
SAME_SOURCE = {'temperature_c': re.compile(r'met\.no|met norway|norwegian meteorological', re.I)}


def _fetch_json(url):
    """One answer-key reference read, counted in the shared outside-call ledger as 'reference_checks' (PM F15 11-14),
    apart from users' own runs: no call when the share or the domain total is used up or the domain answered 429
    today (or GitHub's hourly allowance is low), and a 429 stops every system calling that domain for the day."""
    import httpx
    from urllib.parse import urlsplit
    from agent_market import provider_budget
    ok, _why = provider_budget.reserve(url, 'reference_checks')
    github = urlsplit(url).hostname == provider_budget.GITHUB_HOST
    if ok and github:
        ok, _why = provider_budget.github_reserve('reference_checks')
    if not ok:
        return None
    resp = httpx.get(url, timeout=10, headers={'User-Agent': UA})
    provider_budget.note(url, 'reference_checks', resp.status_code)
    if github:
        provider_budget.github_observe(resp.headers, 'reference_checks')
    return resp.json() if resp.status_code == 200 else None


def _met_temperature(url):
    """Air temperature now from MET Norway Locationforecast (CC BY 4.0 / NLOD, commercial use allowed), replacing
    Open-Meteo (its free tier is non-commercial; PM 11-14). Coordinates at 4 decimals; the Expires header is kept by
    the ten-minute cache, so the same point is not fetched again before it expires."""
    from urllib.parse import parse_qs, urlsplit
    query = parse_qs(urlsplit(url).query)
    lat = round(float(query.get('latitude', query.get('lat'))[0]), 4)
    lon = round(float(query.get('longitude', query.get('lon'))[0]), 4)
    data = _fetch_json(MET.format(lat=lat, lon=lon))
    return float(data['properties']['timeseries'][0]['data']['instant']['details']['air_temperature'])


_CACHE = {}


def reference(kind, url):
    """A public reference value at test time (cached ten minutes): fx rate, current temperature, latest version."""
    if kind == 'clock_tz':                  # the time of day now in that zone (IANA tz via zoneinfo), not fetched
        from zoneinfo import ZoneInfo
        return dt.datetime.now(ZoneInfo(url))
    key = (kind, url)
    if key in _CACHE and time.time() - _CACHE[key][0] < 600:
        return _CACHE[key][1]
    value = None
    try:
        data = None if kind == 'temperature_c' else _fetch_json(url)
        if kind == 'temperature_c':
            _CACHE[key] = (time.time(), _met_temperature(url))
            return _CACHE[key][1]
        if kind == 'rate':
            value = float(next(iter((data or {}).get('rates', {}).values())))
        elif kind == 'temperature_c':
            value = None   # fetched below from MET Norway, never from the URL written in the task
        elif kind == 'latest_version':
            value = str(data['version'])
        elif kind == 'usgs_places':        # places of M5+ events in the USGS month feed (earthquake.feed)
            value = [f['properties']['place'] for f in data['features'] if (f['properties'].get('mag') or 0) >= 5
                     and f['properties'].get('place')]
        elif kind == 'scorecard':
            value = float(data['score'])
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
    if kind == 'usgs_places':
        low = (text or '').lower()
        names = set()
        for place in ref:
            tail = place.split(' of ')[-1]
            names.update(part.strip().lower() for part in tail.split(',') if len(part.strip()) > 3)
        return any(name in low for name in names)
    if kind == 'clock_tz':
        tol = tolerance or 5
        minutes_now = ref.hour * 60 + ref.minute
        for m in CLOCK.finditer(text or ''):
            diff = abs(int(m[1]) * 60 + int(m[2]) - minutes_now)
            if min(diff, 1440 - diff) <= tol or min(abs(diff - 720), 1440 - abs(diff - 720)) <= tol and \
                    re.search(r'\b[ap]\.?m\b', text or '', re.I):
                return True
        return False
    if kind == 'scorecard':
        tol = tolerance or 0.5
        return any(abs(n - ref) <= tol for n in _numbers(text) if 0 <= n <= 10)
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
            if kind in SAME_SOURCE and SAME_SOURCE[kind].search(text or ''):
                return 0, f"answer set {case['case_id']} (not checked: the answer comes from the reference source itself)", reasons
            ok = dynamic_match(kind, reference(kind, url), text, case.get('input'), expect['dynamic'].get('tolerance'))
            checks.append((kind, url, ok))
        dynamic_ok = all(ok for _, _, ok in checks) if checks else None
        if checks and any(ok is None for _, _, ok in checks):
            return 0, f"answer set {case['case_id']} (live reference unavailable)", reasons
        if not static_keys and not checks:
            return 0, f"answer set {case['case_id']} (live-only expectation not checkable)", reasons
        good = passed and (dynamic_ok is not False)
        source = f"answer set {case['case_id']}" + (f" + live {', '.join(k for k, _, _ in checks)}" if checks else '')
        return (WEIGHTS['accuracy'] if good else 0), source, reasons + [f'{k} off the reference' for k, _, ok in checks if ok is False]
    if live:
        if live.get('terms_ok') is False:
            return 0, f"public reference suspended: {live.get('note')}", []
        if live_value is None:
            return 0, f"public reference {live['reference']} (unavailable)", []
        ok = any(abs(n - live_value) <= live['tolerance'] * live_value for n in _numbers(text) if n > 0)
        return (WEIGHTS['accuracy'] if ok else 0), f"public reference {live['reference']} = {live_value:g}", [] if ok else ['off the reference']
    return 0, 'none (no answer set or public reference yet)', []


def latency_points(ms):
    if ms is None:
        return 0
    return next((points for limit, points in LATENCY_STEPS if ms <= limit), 0)
