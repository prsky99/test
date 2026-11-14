"""Real source adapters with bounded public networking and truthful cache ages."""
from collections import OrderedDict
from contextlib import nullcontext
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
import html
import json
import math
import re
import threading
import time
from urllib.parse import quote, urlsplit, urlunsplit

from ..concierge.execution_policy import validate_arguments
from ..concierge.http_security import bounded_client, outbound_operation
from ..concierge.recommendation_security import usable_endpoint
from .catalog import ALL_SPECS as SPECS, INDICATORS, tool_spec

PACKAGE_PATTERN = r'(?:@[a-z0-9][a-z0-9._-]*/)?[a-z0-9][a-z0-9._-]*'
REPOSITORY_PATTERN = r'[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})/[A-Za-z0-9._-]{1,100}'
# Search qualifiers ("user:x", "repo:y") in free text would change the source query.
GITHUB_QUALIFIER = re.compile(r'(?<!\S)[A-Za-z-]+:\S*')
VERSION_PATTERN = r'[0-9]+\.[0-9]+\.[0-9]+(?:-[A-Za-z0-9.-]+)?(?:\+[A-Za-z0-9.-]+)?'


# OSV record id prefix -> its database and license (https://google.github.io/osv.dev/data/, checked 11-14).
# Only databases whose license allows reuse in this service; Chainguard/Wolfi (CC-BY-NC-ND 4.0) is absent on purpose.
OSV_SOURCES = {
    'GHSA': 'GitHub Advisory Database (CC BY 4.0)',
    'MAL': 'OpenSSF Malicious Packages (Apache-2.0)',
    'PYSEC': 'PyPI Advisory Database (CC BY 4.0)',
    'GO': 'Go Vulnerability Database (CC BY 4.0)',
    'RUSTSEC': 'Rust Advisory Database (CC0 1.0)',
    'GSD': 'Global Security Database (CC0 1.0)',
    'OSV': 'OSS-Fuzz (CC BY 4.0)',
    'PSF': 'Python Software Foundation Database (CC BY 4.0)',
}


class DataUnavailable(ValueError):
    """A source failed without exposing its raw response or network details."""


@dataclass
class Entry:
    output: dict
    monotonic_at: float


def clean(value, maximum=500):
    if type(value) is not str:
        return ''
    value = html.unescape(re.sub(r'<[^>]*>', '', value))
    return ' '.join(''.join(c for c in value if ord(c) >= 32 and ord(c) != 127).split())[:maximum]


def public_link(value):
    if type(value) is not str or len(value) > 2000:
        return None
    parsed = urlsplit(value)
    if parsed.scheme != 'https' or not usable_endpoint(value):
        return None
    # Preserve the destination while keeping international source URLs safe for
    # English presentation and avoiding literal non-Latin text in results.
    return urlunsplit((parsed.scheme, parsed.netloc.encode('idna').decode('ascii'),
        quote(parsed.path, safe='/%:@'), quote(parsed.query, safe='=&%:+,/?'), quote(parsed.fragment, safe='%')))


def strict_json(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError('Duplicate field')
            result[key] = value
        return result
    return json.loads(raw, object_pairs_hook=pairs,
                      parse_constant=lambda _: (_ for _ in ()).throw(ValueError('Non-finite number')))


class DataAgents:
    """No registration, background refresh, model, or operating configuration reads."""
    def __init__(self, *, http=None, clock=time.monotonic, utc_now=None, translator=None):
        self.http, self.clock = http, clock
        self.translator = translator
        self.utc_now = utc_now or (lambda: datetime.now(timezone.utc))
        self.entries = OrderedDict()
        self.failed_until = OrderedDict()
        self.lock = threading.RLock()
        self.stripes = tuple(threading.Lock() for _ in range(16))
        self.slots = threading.BoundedSemaphore(4)

    def execute(self, agent_id, arguments):
        # Include coalescing waits, source retrieval and presentation in one
        # budget shorter than the public gateway's eight-second deadline.
        with outbound_operation(6) as budget:
            return self._execute_bounded(agent_id, arguments, budget)

    def _execute_bounded(self, agent_id, arguments, budget):
        if agent_id not in SPECS:
            raise ValueError('Choose an available data agent.')
        spec = tool_spec(agent_id)
        validate_arguments(spec, arguments)
        # Published schemas stay within the gateway's offline schema profile.
        # These finite, trusted identifier rules run here before any networking.
        if ('country_code' in arguments and not re.fullmatch(r'[A-Z]{2}', arguments['country_code'])
                or 'package' in arguments and not re.fullmatch(PACKAGE_PATTERN, arguments['package'])
                or 'version' in arguments and not re.fullmatch(VERSION_PATTERN, arguments['version'])
                or 'repository' in arguments and not re.fullmatch(REPOSITORY_PATTERN, arguments['repository'])):
            raise ValueError('Use a valid country code, package name, exact version or owner/repository.')
        if agent_id == 'github-issues':
            # One cache entry per meaning: case, spacing and default filters do not change the answer.
            arguments = {key: value for key, value in arguments.items() if value != 'any'}
            arguments['query'] = ' '.join(arguments['query'].split()).casefold()
            if 'repository' in arguments:
                arguments['repository'] = arguments['repository'].casefold()
        if agent_id in ('technology-news', 'research-papers', 'github-issues'):
            query = arguments['query']
            if (any(ord(c) < 32 for c in query) or re.search(
                    r'https?://|<[^>]*>|\b(?:Bearer|Basic)\s|\b(?:api[_-]?key|token|password)\s*[:=]|'
                    r'[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}|/(?:Users|home)/', query, re.I)):
                raise ValueError('Use public search keywords.')
        key = (agent_id, json.dumps(arguments, sort_keys=True, allow_nan=False))
        stripe = self.stripes[hash(key) % len(self.stripes)]
        if not stripe.acquire(timeout=min(5.5, budget.remaining())):
            raise DataUnavailable('The data source is busy. Try again shortly.')
        try:
            with self.lock:
                entry = self.entries.get(key)
                if entry:
                    self.entries.move_to_end(key)
                cooling = self.failed_until.get(key, 0) > self.clock()
            age = max(0, self.clock() - entry.monotonic_at) if entry else None
            if entry and age <= SPECS[agent_id]['ttl']:
                return self._cached(entry, age, 'fresh_cache')
            if cooling:
                return self._stale_or_fail(agent_id, entry, age)
            acquired = self.slots.acquire(blocking=False)
            if not acquired:
                return self._stale_or_fail(agent_id, entry, age)
            try:
                # One source request per capability; no hidden fallback or retry.
                with outbound_operation(min(5, budget.remaining())):
                    data = self._fetch(agent_id, arguments)
                from .english import normalize
                data = normalize(data, self.translator)
                output = {'agent': agent_id,
                    'source': {'name': SPECS[agent_id]['source_name'], 'url': SPECS[agent_id]['source_url']},
                    'retrieved_at': self.utc_now().isoformat().replace('+00:00', 'Z'),
                    'cache': {'status': 'live', 'age_seconds': 0}, 'data': data}
                validate_arguments({'inputSchema': spec['outputSchema']}, output)
                entry = Entry(deepcopy(output), self.clock())
                with self.lock:
                    self.entries[key] = entry
                    self.entries.move_to_end(key)
                    self.failed_until.pop(key, None)
                    while len(self.entries) > 512:
                        self.entries.popitem(last=False)
                return output
            except Exception:
                with self.lock:
                    self.failed_until[key] = self.clock() + 15
                    self.failed_until.move_to_end(key)
                    while len(self.failed_until) > 128:
                        self.failed_until.popitem(last=False)
                return self._stale_or_fail(agent_id, entry, age)
            finally:
                self.slots.release()
        finally:
            stripe.release()

    @staticmethod
    def _cached(entry, age, status):
        result = deepcopy(entry.output)
        result['cache'] = {'status': status, 'age_seconds': int(age)}
        return result

    def _stale_or_fail(self, agent_id, entry, age):
        if entry and age <= SPECS[agent_id]['max_stale']:
            return self._cached(entry, age, 'stale_cache')
        raise DataUnavailable('Current source data is unavailable. No replacement data was generated.')

    def _request(self, method, url, **kwargs):
        # All callers below construct URLs from fixed origins and bounded IDs.
        parsed = urlsplit(url)
        if (parsed.scheme != 'https' or parsed.port not in (None, 443) or parsed.username or parsed.password
                or parsed.query or parsed.fragment or parsed.hostname not in (
                    'hn.algolia.com', 'api.crossref.org', 'api.worldbank.org', 'registry.npmjs.org', 'api.osv.dev',
                    'api.github.com')
                or method != ('POST' if parsed.hostname == 'api.osv.dev' else 'GET')):
            raise DataUnavailable('Source unavailable.')
        github = parsed.hostname == 'api.github.com'
        client = bounded_client(self.http, timeout=4, limit=524288,
            headers={'User-Agent': 'AgentConcierge-DataAgents/1.0 (+https://agentconcierge.biz)',
                     'Accept': 'application/vnd.github+json' if github else 'application/json',
                     **({'X-GitHub-Api-Version': '2022-11-28'} if github else {})})
        try:
            from .source_limits import CROSSREF, GITHUB_SEARCH
            pacer = CROSSREF if parsed.hostname == 'api.crossref.org' else GITHUB_SEARCH if github else None
            with outbound_operation(4.9) as source_budget:
                with pacer.slot(source_budget) if pacer else nullcontext():
                    response = client.request(method, url, timeout=4, **kwargs)
                    if pacer:pacer.observed(response)
                    if response.status_code != 200 or 'application/json' not in response.headers.get('content-type', '').lower():
                        raise DataUnavailable('Source unavailable.')
                    return strict_json(response.content)
        finally:
            client.close()

    def _fetch(self, agent_id, args):
        return getattr(self, '_' + agent_id.replace('-', '_'))(args)

    def _technology_news(self, args):
        raw = self._request('GET', 'https://hn.algolia.com/api/v1/search_by_date',
            params={'query': args['query'], 'tags': 'story', 'hitsPerPage': args['limit']})
        if type(raw.get('hits')) is not list:
            raise ValueError('Invalid source')
        items, seen = [], set()
        for hit in raw['hits'][:10]:
            identity = str(hit.get('objectID', ''))
            link = 'https://news.ycombinator.com/item?id=' + identity if re.fullmatch(r'[0-9]{1,20}', identity) else None
            link = public_link(hit.get('url')) or link
            title, published = clean(hit.get('title')), clean(hit.get('created_at'), 40)
            if link and title and published and link not in seen:
                at = datetime.fromisoformat(published.replace('Z', '+00:00'))
                if at.tzinfo is None or at > self.utc_now():
                    continue
                items.append({'title': title, 'url': link, 'published_at': at.astimezone(timezone.utc).isoformat().replace('+00:00', 'Z'),
                              'source': 'Hacker News'})
                seen.add(link)
        items.sort(key=lambda row: row['published_at'], reverse=True)
        return {'query': args['query'], 'items': items[:args['limit']],
                'partial': len(items) < len(raw['hits'])}

    def _github_issues(self, args):
        terms = ' '.join(GITHUB_QUALIFIER.sub(' ', args['query']).split())[:160]
        if len(terms) < 2:
            raise ValueError('Use public search keywords.')
        query = [terms]
        if args.get('repository'):
            query.append('repo:' + args['repository'])
        if args.get('type') in ('issue', 'pull_request'):
            query.append('is:issue' if args['type'] == 'issue' else 'is:pr')
        if args.get('state') in ('open', 'closed'):
            query.append('state:' + args['state'])
        raw = self._request('GET', 'https://api.github.com/search/issues', params={
            'q': ' '.join(query), 'per_page': args['limit'], 'sort': 'updated', 'order': 'desc'})
        rows = raw.get('items')
        if type(rows) is not list or type(raw.get('total_count')) is not int:
            raise ValueError('Invalid source')
        items, seen = [], set()
        for row in rows[:10]:
            url = public_link(row.get('html_url'))
            repository = re.fullmatch(r'https://api\.github\.com/repos/(' + REPOSITORY_PATTERN + ')', str(row.get('repository_url') or ''))
            number, title = row.get('number'), clean(row.get('title'))
            if (not url or not url.startswith('https://github.com/') or not repository or type(number) is not int
                    or number < 1 or not title or url in seen):
                continue
            labels = [clean(label.get('name'), 50) for label in (row.get('labels') or [])[:10] if isinstance(label, dict)]
            comments = row.get('comments')
            # Author logins and bodies are omitted: titles, states and links identify the work.
            items.append({'title': title, 'url': url, 'repository': repository.group(1), 'number': number,
                'type': 'pull_request' if isinstance(row.get('pull_request'), dict) else 'issue',
                'state': clean(row.get('state'), 20), 'updated_at': clean(row.get('updated_at'), 40),
                'comments': comments if type(comments) is int and comments >= 0 else 0,
                'labels': [label for label in labels if label][:5]})
            seen.add(url)
        return {'query': args['query'], 'items': items[:args['limit']], 'total_count': raw['total_count'],
                'partial': bool(raw.get('incomplete_results')) or len(items) < min(len(rows), args['limit'])}

    def _research_papers(self, args):
        raw = self._request('GET', 'https://api.crossref.org/works', params={
            'query.bibliographic': args['query'], 'rows': args['limit'],
            'select': 'DOI,title,published,URL,publisher'})
        rows = raw['message']['items']
        if type(rows) is not list:
            raise ValueError('Invalid source')
        items, seen = [], set()
        for row in rows[:10]:
            doi = clean(row.get('DOI'), 250)
            titles = row.get('title', [])
            title = clean(titles[0]) if type(titles) is list and titles else ''
            if not re.fullmatch(r'10\.[0-9]{4,9}/\S{1,230}', doi) or not title or doi.lower() in seen:
                continue
            date = row.get('published', {}).get('date-parts', [[]])[0]
            published = '-'.join(str(value).zfill(2) for value in date[:3]) if type(date) is list and all(type(x) is int for x in date) else ''
            items.append({'title': title, 'url': 'https://doi.org/' + quote(doi, safe='/'),
                'doi': doi, 'publisher': clean(row.get('publisher')), 'publication_date': published})
            seen.add(doi.lower())
        return {'query': args['query'], 'items': items[:args['limit']], 'partial': len(items) < len(rows)}

    def _country_profile(self, args):
        raw = self._request('GET', 'https://api.worldbank.org/v2/country/' + args['country_code'],
                            params={'format': 'json'})
        row = raw[1][0]
        if row['iso2Code'] != args['country_code'] or row.get('region', {}).get('id') == 'NA':
            raise ValueError('Country not available')
        return {'country_code': row['iso2Code'], 'name': clean(row['name']),
            'capital': clean(row.get('capitalCity')), 'region': clean(row['region']['value']),
            'income_group': clean(row['incomeLevel']['value']),
            'url': 'https://data.worldbank.org/country/' + args['country_code']}

    def _package_metadata(self, args):
        raw = self._request('GET', 'https://registry.npmjs.org/' + quote(args['package'], safe='') + '/latest')
        if (raw.get('name') != args['package'] or type(raw.get('version')) is not str
                or not re.fullmatch(VERSION_PATTERN, raw['version'])):
            raise ValueError('Package mismatch')
        license_value = raw.get('license')
        return {'package': raw['name'], 'version': raw['version'], 'description': clean(raw.get('description')),
            'url': 'https://www.npmjs.com/package/' + quote(raw['name'], safe='@/'),
            'license': clean(license_value if type(license_value) is str else '', 100)}

    def _economic_indicators(self, args):
        year = self.utc_now().year
        # The canonical country path reuses the provider's public cache. Dynamic
        # period/MRNEV filters unnecessarily force slower origin computation.
        raw = self._request('GET', 'https://api.worldbank.org/v2/country/' + args['country_code'].lower()
                            + '/indicator/' + args['indicator'], params={'format': 'json'})
        rows = raw[1]
        if type(rows) is not list:
            raise ValueError('Indicator unavailable')
        items = []
        for row in rows[:100]:
            if (row['country']['id'] != args['country_code'] or row['indicator']['id'] != args['indicator']):
                raise ValueError('Indicator mismatch')
            value = row.get('value')
            if type(value) not in (int, float) or not math.isfinite(value):
                continue
            at = int(row['date'])
            if not 1960 <= at <= year:
                raise ValueError('Invalid observation year')
            items.append({'year': at, 'value': value,
                'url': 'https://data.worldbank.org/indicator/' + args['indicator'] + '?locations=' + args['country_code']})
        items.sort(key=lambda row: row['year'], reverse=True)
        if not items:
            raise ValueError('No recent observations')
        return {'country_code': args['country_code'], 'indicator': args['indicator'],
            'indicator_name': INDICATORS[args['indicator']][0], 'unit': INDICATORS[args['indicator']][1],
            'items': items[:args['limit']], 'partial': len(items) < min(args['limit'], len(rows))}

    def _package_advisories(self, args):
        raw = self._request('POST', 'https://api.osv.dev/v1/query', json={
            'package': {'name': args['package'], 'ecosystem': 'npm'}, 'version': args['version']})
        rows = raw.get('vulns', [])
        if type(rows) is not list or set(raw) - {'vulns', 'next_page_token'}:
            raise ValueError('Invalid advisory response')
        items, excluded = [], 0
        for row in rows[:100]:
            identity = row['id']
            if type(identity) is not str or not re.fullmatch(r'[A-Za-z0-9._-]{1,128}', identity):
                raise ValueError('Invalid advisory')
            # OSV merges many databases with different licenses (one is non-commercial: Chainguard/Wolfi,
            # CC-BY-NC-ND). Only records from databases whose license allows our reuse are returned, each
            # with its database and license; anything else is dropped and counted (PM 11-14).
            source = OSV_SOURCES.get(identity.split('-', 1)[0])
            if not source:
                excluded += 1
                continue
            items.append({'id': identity, 'summary': clean(row.get('summary') or row.get('details')),
                          'url': 'https://osv.dev/vulnerability/' + identity,
                          'modified_at': clean(row.get('modified'), 40), 'source': source})
        items.sort(key=lambda row: row['modified_at'], reverse=True)
        return {'package': args['package'], 'version': args['version'], 'items': items[:args['limit']],
            'returned_matches': len(items), 'excluded_matches': excluded,
            'partial': bool(raw.get('next_page_token')) or len(items) > args['limit'] or excluded > 0,
            'scope': 'Published advisories for this exact version at retrieval time, from databases whose license '
                     'allows reuse. Absence is not a security guarantee.'}
