"""Finite read-only capabilities and their reviewed public data sources.

SPECS are listed publicly; ADMIN_SPECS run only from administrator tools, because a
source with a small shared limit must not look like a public service failure.
"""
from copy import deepcopy


def obj(properties):
    return {'type': 'object', 'properties': properties, 'required': list(properties),
            'additionalProperties': False}


def text(maximum=500):
    return {'type': 'string', 'maxLength': maximum}


def array(item):
    return {'type': 'array', 'items': item, 'maxItems': 10}


QUERY = {'type': 'string', 'minLength': 2, 'maxLength': 160}
LIMIT = {'type': 'integer', 'minimum': 1, 'maximum': 5}
COUNTRY = {'type': 'string', 'minLength': 2, 'maxLength': 2}
PACKAGE = {'type': 'string', 'minLength': 1, 'maxLength': 160}
VERSION = {'type': 'string', 'minLength': 1, 'maxLength': 80}
INDICATORS = {'SP.POP.TOTL': ('Population', 'people'),
              'NY.GDP.MKTP.CD': ('GDP', 'current USD'),
              'SP.DYN.LE00.IN': ('Life expectancy at birth', 'years')}


SPECS = {
    'technology-news': {
        'name': 'Technology News', 'tool': 'search_technology_news',
        'description': 'Find recent Hacker News stories matching public technology keywords.',
        'source_name': 'Hacker News Search by Algolia', 'source_url': 'https://hn.algolia.com/api',
        'ttl': 60, 'max_stale': 900,
        'input': obj({'query': QUERY, 'limit': LIMIT}),
        'data': obj({'query': text(160), 'items': array(obj({'title': text(), 'url': text(2000),
            'published_at': text(40), 'source': text(100)})), 'partial': {'type': 'boolean'}}),
        'example': {'query': 'artificial intelligence', 'limit': 3}},
    'research-papers': {
        'name': 'Research Papers', 'tool': 'search_research_papers',
        'description': 'Search Crossref bibliographic records with DOI source links.',
        'source_name': 'Crossref', 'source_url': 'https://www.crossref.org/documentation/retrieve-metadata/rest-api/',
        'ttl': 300, 'max_stale': 3600,
        'input': obj({'query': {**QUERY, 'maxLength': 500}, 'limit': LIMIT}),
        'data': obj({'query': text(500), 'items': array(obj({'title': text(), 'url': text(2000),
            'doi': text(250), 'publisher': text(), 'publication_date': text(40)})),
            'partial': {'type': 'boolean'}}),
        'example': {'query': 'artificial intelligence', 'limit': 3}},
    'country-profile': {
        'name': 'Country Profile', 'tool': 'get_country_profile',
        'description': 'Retrieve a country name, capital and region from the World Bank.',
        'source_name': 'World Bank', 'source_url': 'https://data.worldbank.org/',
        'ttl': 86400, 'max_stale': 604800,
        'input': obj({'country_code': COUNTRY}),
        'data': obj({'country_code': COUNTRY, 'name': text(), 'capital': text(),
                     'region': text(), 'income_group': text(), 'url': text(2000)}),
        'example': {'country_code': 'US'}},
    'package-metadata': {
        'name': 'Package Metadata', 'tool': 'get_package_metadata',
        'description': 'Retrieve the current npm package version and public description.',
        'source_name': 'npm public registry', 'source_url': 'https://registry.npmjs.org/',
        'ttl': 120, 'max_stale': 3600,
        'input': obj({'package': PACKAGE}),
        'data': obj({'package': PACKAGE, 'version': VERSION, 'description': text(),
                     'url': text(2000), 'license': text(100)}),
        'example': {'package': 'express'}},
    'economic-indicators': {
        'name': 'Economic Indicators', 'tool': 'get_economic_indicators',
        'description': 'Retrieve the latest available World Bank annual indicator observations.',
        'source_name': 'World Bank World Development Indicators', 'source_url': 'https://data.worldbank.org/',
        'ttl': 3600, 'max_stale': 604800,
        'input': obj({'country_code': COUNTRY, 'indicator': {'enum': list(INDICATORS)}, 'limit': LIMIT}),
        'data': obj({'country_code': COUNTRY, 'indicator': text(100), 'indicator_name': text(),
            'unit': text(100), 'items': array(obj({'year': {'type': 'integer', 'minimum': 1960, 'maximum': 2200},
                'value': {'type': 'number'}, 'url': text(2000)})), 'partial': {'type': 'boolean'}}),
        'example': {'country_code': 'US', 'indicator': 'SP.POP.TOTL', 'limit': 3}},
    'package-advisories': {
        'name': 'Package Security Advisories', 'tool': 'check_package_advisories',
        'description': 'Query published OSV advisories for an exact npm package version.',
        'source_name': 'OSV', 'source_url': 'https://osv.dev/',
        'ttl': 300, 'max_stale': 3600,
        'category': 'security',
        'input': obj({'package': PACKAGE, 'version': VERSION, 'limit': LIMIT}),
        'data': obj({'package': PACKAGE, 'version': VERSION,
            'items': array(obj({'id': text(128), 'summary': text(), 'url': text(2000), 'modified_at': text(40)})),
            'returned_matches': {'type': 'integer', 'minimum': 0}, 'partial': {'type': 'boolean'},
            'scope': text()}),
        'example': {'package': 'express', 'version': '4.17.1', 'limit': 3}},
    'github-issues': {
        'name': 'GitHub Issues and Pull Requests', 'tool': 'search_github_issues',
        'description': 'Search public GitHub issues and pull requests by keywords, with an optional repository, type and state.',
        'source_name': 'GitHub Search API', 'source_url': 'https://docs.github.com/en/rest/search/search#search-issues-and-pull-requests',
        # Unauthenticated search allows ten requests a minute: answers stay fresh for ten
        # minutes and the same query may use an explicitly aged cache for up to six hours.
        'ttl': 600, 'max_stale': 21600,
        'category': 'dev_tools',
        'input': {'type': 'object', 'additionalProperties': False, 'required': ['query', 'limit'],
                  'properties': {'query': QUERY, 'limit': LIMIT,
                                 'repository': {'type': 'string', 'minLength': 3, 'maxLength': 140},
                                 'type': {'enum': ['any', 'issue', 'pull_request']},
                                 'state': {'enum': ['any', 'open', 'closed']}}},
        'data': obj({'query': text(160), 'items': array(obj({'title': text(), 'url': text(2000),
            'repository': text(140), 'number': {'type': 'integer', 'minimum': 1},
            'type': {'enum': ['issue', 'pull_request']}, 'state': text(20), 'updated_at': text(40),
            'comments': {'type': 'integer', 'minimum': 0}, 'labels': array(text(50))})),
            'total_count': {'type': 'integer', 'minimum': 0}, 'partial': {'type': 'boolean'}}),
        'example': {'query': 'memory leak', 'limit': 3}},
}

ADMIN_SPECS = {}
ALL_SPECS = {**SPECS, **ADMIN_SPECS}


def tool_spec(agent_id):
    spec = ALL_SPECS[agent_id]
    envelope = obj({'agent': {'const': agent_id},
        'source': obj({'name': text(100), 'url': text(2000)}),
        'retrieved_at': text(40),
        'cache': obj({'status': {'enum': ['live', 'fresh_cache', 'stale_cache']},
                      'age_seconds': {'type': 'integer', 'minimum': 0}}),
        'data': spec['data']})
    return deepcopy({'name': spec['tool'], 'description': spec['description'],
        'inputSchema': spec['input'], 'outputSchema': envelope,
        'annotations': {'readOnlyHint': True, 'destructiveHint': False,
                        'idempotentHint': True, 'openWorldHint': True}})
