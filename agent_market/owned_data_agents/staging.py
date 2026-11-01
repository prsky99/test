"""Prepare five Testbench recipes and three graphs without applying anything."""
from copy import deepcopy
from urllib.parse import urlsplit

from ..concierge.recommendation_security import usable_endpoint
from ..workflow_templates import agent
from .catalog import SPECS, tool_spec
from .service import PREFIX

VERSION = 'owned-data-agents-staged-v1'
TEST_IDS = ('technology-news', 'research-papers', 'country-profile', 'package-metadata', 'github-issues')


def origin(value):
    parsed = urlsplit(value)
    if (parsed.scheme != 'https' or not usable_endpoint(value) or parsed.username or parsed.password
            or parsed.path not in ('', '/') or parsed.query or parsed.fragment):
        raise ValueError('Choose one public HTTPS agent origin.')
    return value.rstrip('/')


def recipes(base_url='https://agentconcierge.biz'):
    base_url = origin(base_url)
    return tuple((identity, SPECS[identity]['name'], SPECS[identity]['description'],
                  base_url + PREFIX + '/' + identity + '/mcp', SPECS[identity]['tool'],
                  deepcopy(SPECS[identity]['example'])) for identity in TEST_IDS)


def definitions(base_url='https://agentconcierge.biz'):
    base_url = origin(base_url)
    def node(identity, selected, arguments, index):
        return agent(identity, SPECS[selected]['name'], base_url + PREFIX + '/' + selected + '/mcp',
                     SPECS[selected]['tool'], arguments, {'path': 'content.0.text', 'max_text': 16000}, index)
    graphs = [
        ('technology-research', 'Daily Tech News & AI Research Digest',
         'Find recent technology stories and related research records with source links.', 'dev_tools', [
            node('news', 'technology-news', {'query': 'artificial intelligence', 'limit': 3}, 1),
            node('papers', 'research-papers', {
                'query': "{{$node['news'].output.structuredContent.data.query}}", 'limit': 3}, 2)]),
        ('country-indicators', 'Country & Economic Indicator Brief',
         'Resolve a country profile, then retrieve its latest available population observations.', 'data_utility', [
            node('country', 'country-profile', {'country_code': 'US'}, 1),
            node('indicators', 'economic-indicators', {
                'country_code': "{{$node['country'].output.structuredContent.data.country_code}}",
                'indicator': 'SP.POP.TOTL', 'limit': 3}, 2)]),
        ('package-security', 'Package Metadata & Advisory Review',
         'Resolve the current package version, then query matching published security advisories.', 'dev_tools', [
            node('package', 'package-metadata', {'package': 'express'}, 1),
            node('advisories', 'package-advisories', {
                'package': "{{$node['package'].output.structuredContent.data.package}}",
                'version': "{{$node['package'].output.structuredContent.data.version}}", 'limit': 3}, 2)])]
    result = []
    for key, name, description, category, nodes in graphs:
        trigger = {'id': 'start', 'type': 'trigger', 'kind': 'trigger', 'name': 'Manual Trigger',
                   'position': {'x': 60, 'y': 160}, 'data': {}}
        result.append({'seed_key': VERSION + ':' + key, 'name': name, 'description': description,
            'category': category, 'trigger_type': 'manual', 'tags': 'owned-data,read-only,' + key,
            'is_template': 1, 'is_active': 1, 'author': 'Agent Concierge',
            'nodes': [trigger, *nodes], 'edges': [
                {'id': 'start-first', 'source': 'start', 'target': nodes[0]['id']},
                {'id': 'first-second', 'source': nodes[0]['id'], 'target': nodes[1]['id']}]})
    return deepcopy(result)


def bundle(base_url='https://agentconcierge.biz'):
    """Return declarative data only. This is not an operating install command."""
    base_url = origin(base_url)
    return {'profile': VERSION, 'applied': False, 'requires_explicit_activation': True,
        'agents': [{'id': identity, 'name': spec['name'], 'kind': 'mcp',
            'url': base_url + PREFIX + '/' + identity + '/mcp', 'tools': [tool_spec(identity)]}
            for identity, spec in SPECS.items()],
        'testbench_recipes': [{'id': row[0], 'title': row[1], 'desc': row[2],
             'endpoint': row[3], 'tool': row[4], 'args': row[5]} for row in recipes(base_url)],
        'workflow_templates': definitions(base_url)}
