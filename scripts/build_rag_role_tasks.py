"""Role tasks for the 15 roles without an answer set (PM 11-14): each expectation is fetched again from its public
source when this runs and written only if the source still confirms it.

Output: agent_market/necklaces/role_tasks/role-tasks-rag-v1.jsonl (same shape as role-tasks-v1.jsonl: case_id, role,
contract, task_type, input, expect, truth_sources[{name, url, checked_on}]). Public, non-personal inputs only.
Roles whose answer changes (earthquakes, the time of day, a scorecard) carry a `dynamic` expectation checked at test
time against the same source (scripts/data_quality.py).

    .venv/bin/python -m scripts.build_rag_role_tasks          # fetch, verify, write
"""
import json
import re
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'agent_market/necklaces/role_tasks/role-tasks-rag-v1.jsonl'
UA = {'User-Agent': 'AgentConcierge-Verification/1.0 (contact@agentconcierge.biz)'}


def get(url, kind='json'):
    resp = httpx.get(url, headers=UA, timeout=20, follow_redirects=True)
    resp.raise_for_status()
    return resp.json() if kind == 'json' else resp.text


def raw_has(url, *needles):
    text = get(url, 'text')
    return all(re.search(n, text, re.I) for n in needles)


# (case_id, role, input, expect, [(source name, url, verify(): bool)])
CASES = [
    ('airport-icn', 'airport.lookup.v1', {'code': 'ICN'}, {'must_include_all': ['Incheon']},
     [('Wikipedia: Incheon International Airport (IATA field)', 'https://en.wikipedia.org/w/index.php?title=Incheon_International_Airport&action=raw',
       lambda u: raw_has(u, r'IATA\s*=\s*ICN'))]),
    ('airport-lax', 'airport.lookup.v1', {'code': 'LAX'}, {'must_include_all': ['Los Angeles']},
     [('Wikipedia: Los Angeles International Airport (IATA field)', 'https://en.wikipedia.org/w/index.php?title=Los_Angeles_International_Airport&action=raw',
       lambda u: raw_has(u, r'IATA\s*=\s*LAX'))]),
    ('book-pride-prejudice', 'book.search.v1', {'query': 'Pride and Prejudice', 'title': 'Pride and Prejudice'},
     {'must_include_all': ['Austen']},
     [('Open Library search', 'https://openlibrary.org/search.json?title=pride+and+prejudice&limit=1',
       lambda u: any('Austen' in a for a in get(u)['docs'][0].get('author_name', [])))]),
    ('book-1984', 'book.search.v1', {'query': 'Nineteen Eighty-Four', 'title': 'Nineteen Eighty-Four'},
     {'must_include_all': ['Orwell']},
     [('Open Library search', 'https://openlibrary.org/search.json?title=nineteen+eighty-four&limit=1',
       lambda u: any('Orwell' in a for a in get(u)['docs'][0].get('author_name', [])))]),
    ('define-serendipity', 'dictionary.define.v1', {'word': 'serendipity'},
     {'must_include_all': ['serendipity'], 'must_include_any': ['chance', 'accident', 'luck', 'fortunate', 'unexpected']},
     [('Free Dictionary API', 'https://api.dictionaryapi.dev/api/v2/entries/en/serendipity',
       lambda u: re.search(r'chance|accident|luck|fortunate|unexpected', json.dumps(get(u)), re.I) is not None)]),
    ('domain-python-org', 'domain.lookup.v1', {'domain': 'python.org'},
     {'must_include_all': ['python.org'], 'must_include_any': ['1995', 'registrar', 'Registrar']},
     [('RDAP python.org', 'https://rdap.org/domain/python.org',
       lambda u: any(str(e.get('eventDate', '')).startswith('1995') for e in get(u).get('events', [])))]),
    ('quakes-m5-month', 'earthquake.feed.v1', {'min_magnitude': 5},
     {'must_include_any': ['mag', 'Mag', 'M5', 'M 5', 'magnitude'],
      'dynamic': {'usgs_places': 'https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/4.5_month.geojson'}},
     [('USGS 4.5+ month feed', 'https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/4.5_month.geojson',
       lambda u: any((f['properties'].get('mag') or 0) >= 5 for f in get(u)['features']))]),
    ('geocode-white-house', 'geocode.address.v1', {'address': '1600 Pennsylvania Avenue NW, Washington, DC'},
     {'must_include_all': ['38.89', '-77.03']},
     [('OpenStreetMap Nominatim', 'https://nominatim.openstreetmap.org/search?q=1600+Pennsylvania+Avenue+NW,+Washington,+DC&format=json&limit=1',
       lambda u: (lambda r: r['lat'].startswith('38.89') and r['lon'].startswith('-77.03'))(get(u)[0]))]),
    ('github-react-license', 'github.repo.v1', {'repo': 'facebook/react'}, {'must_include_all': ['MIT']},
     [('GitHub REST: facebook/react', 'https://api.github.com/repos/facebook/react',
       lambda u: get(u)['license']['spdx_id'] == 'MIT')]),
    ('holiday-us-2026', 'holiday.calendar.v1', {'country': 'US', 'year': 2026},
     {'must_include_all': ['Thanksgiving', '2026-11-26'], 'must_include_any': ['2026-07-03', '2026-07-04']},
     [('Nager.Date public holidays US 2026', 'https://date.nager.at/api/v3/PublicHolidays/2026/US',
       lambda u: (lambda d: '2026-11-26' in d and ('2026-07-03' in d or '2026-07-04' in d))({h['date'] for h in get(u)}))]),
    ('ip-google-dns', 'ip.lookup.v1', {'ip': '8.8.8.8'}, {'must_include_all': ['8.8.8.8'], 'must_include_any': ['Google', 'GOGL', '15169']},
     [('ARIN RDAP 8.8.8.8', 'https://rdap.arin.net/registry/ip/8.8.8.8', lambda u: 'GOGL' in json.dumps(get(u)))]),
    ('scorecard-react', 'package.risk.v1', {'repo': 'github.com/facebook/react', 'package': 'react', 'ecosystem': 'npm'},
     {'must_include_any': ['score', 'Score'],
      'dynamic': {'scorecard': 'https://api.securityscorecards.dev/projects/github.com/facebook/react', 'tolerance': 0.5}},
     [('OpenSSF Scorecard API', 'https://api.securityscorecards.dev/projects/github.com/facebook/react',
       lambda u: isinstance(get(u).get('score'), (int, float)))]),
    ('place-eiffel-tower', 'place.search.v1', {'query': 'Eiffel Tower'}, {'must_include_all': ['Paris']},
     [('OpenStreetMap Nominatim', 'https://nominatim.openstreetmap.org/search?q=Eiffel+Tower&format=json&limit=1',
       lambda u: 'Paris' in get(u)[0]['display_name'])]),
    ('sec-apple-filings', 'sec.filings.v1', {'ticker': 'AAPL', 'cik': '320193', 'company': 'Apple Inc'},
     {'must_include_any': ['10-K', '10-Q', '8-K'], 'alias_groups': [['Apple', '320193']], 'must_include_all': ['Apple']},
     [('SEC EDGAR submissions CIK 320193', 'https://data.sec.gov/submissions/CIK0000320193.json',
       lambda u: (lambda d: 'Apple' in d['name'] and '10-K' in d['filings']['recent']['form'])(get(u)))]),
    ('time-new-york', 'timezone.time.v1', {'timezone': 'America/New_York', 'city': 'New York'},
     {'dynamic': {'clock_tz': 'America/New_York', 'tolerance': 5}},
     [('IANA time zone database (via zoneinfo)', 'https://www.iana.org/time-zones',
       lambda u: __import__('zoneinfo').ZoneInfo('America/New_York') is not None)]),
    ('translate-good-morning-fr', 'translate.text.v1', {'text': 'Good morning', 'target': 'fr'},
     {'must_include_any': ['Bonjour', 'bonjour']},
     [('Wiktionary: good morning (translations)', 'https://en.wiktionary.org/w/index.php?title=good_morning&action=raw',
       lambda u: raw_has(u, r'bonjour'))]),
    ('convert-10-miles-km', 'unit.convert.v1', {'value': 10, 'from': 'mile', 'to': 'kilometer'},
     {'must_include_any': ['16.09', '16,09']},
     [('Wikipedia: Mile (international mile = 1.609344 km)', 'https://en.wikipedia.org/w/index.php?title=Mile&action=raw',
       lambda u: raw_has(u, r'1\.609344'))]),
]


def build(now=None):
    checked = time.strftime('%Y-%m-%dT%H:%M%z', time.localtime(now))
    rows, failures = [], []
    for case_id, role, case_input, expect, sources in CASES:
        ok, truth = True, []
        for name, url, verify in sources:
            try:
                good = bool(verify(url))
            except Exception as exc:          # a source down or changed: the case is not written
                good, name = False, f'{name} ({type(exc).__name__})'
            ok = ok and good
            truth.append({'name': name, 'url': url, 'checked_on': checked, 'confirmed': good})
            time.sleep(1)                     # be polite to every source
        row = {'case_id': case_id, 'contract': role, 'role': role, 'task_type': 'role_test', 'input': case_input,
               'expect': expect, 'truth_sources': truth, 'author': 'search-and-rag'}
        (rows if ok else failures).append(row)
    return rows, failures


def main():
    rows, failures = build()
    OUT.write_text(''.join(json.dumps(r, ensure_ascii=False, sort_keys=True) + '\n' for r in rows), encoding='utf-8')
    print(f'{len(rows)} cases written to {OUT.relative_to(ROOT)}; {len(failures)} not confirmed: '
          + ', '.join(f"{f['case_id']} ({[t['name'] for t in f['truth_sources'] if not t['confirmed']]})" for f in failures))
    return 0 if rows else 1


if __name__ == '__main__':
    sys.exit(main())
