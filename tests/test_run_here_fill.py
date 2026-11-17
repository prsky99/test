"""Run here arguments filled from the task only when certain (PM 11-16 08:2x B1, 검색과 RAG 08:4x review).

All placeholders or none, values from fixed forms or fixed lists, one value of a kind per task, at most 200 characters
on one line, never an e-mail address, and no added latency.
"""
import time

import pytest

from agent_market.concierge.connections import run_here
from agent_market.concierge.run_here_fill import fill, values


def tool(*required, name='t'):
    return {'name': name, 'inputSchema': {'required': list(required), 'properties': {r: {'type': 'string'} for r in required}}}


def placeholders(*names):
    return {n: '<' + n + '>' for n in names}


CERTAIN = [
    ('find an agent for current weather in Seoul', ('city',), {'city': 'Seoul'}),
    ('서울 날씨 알려줘', ('location',), {'location': 'Seoul'}),
    ('weather forecast for new york tomorrow', ('location',), {'location': 'New York'}),
    ('whois for agentconcierge.biz please', ('domain',), {'domain': 'agentconcierge.biz'}),
    ('summarize https://example.org/post/1', ('url',), {'url': 'https://example.org/post/1'}),
    ('geolocate 8.8.8.8', ('ip',), {'ip': '8.8.8.8'}),
    ('details of cve-2024-3094', ('cve_id',), {'cve_id': 'CVE-2024-3094'}),
    ('holidays on 2026-12-25', ('date',), {'date': '2026-12-25'}),
    ('exchange rate USD to KRW', ('from', 'to'), {'from': 'USD', 'to': 'KRW'}),
    ('convert eur/jpy now', ('base', 'target'), {'base': 'EUR', 'target': 'JPY'}),
    ('exchange rate usd to krw', ('from', 'to'), {'from': 'USD', 'to': 'KRW'}),   # lower case with money words
    ('stock quote for NVDA', ('symbol',), {'symbol': 'NVDA'}),
    ('bitcoin price', ('ids',), {'ids': 'bitcoin'}),
    ('price of ETH', ('symbol',), {'symbol': 'ETH'}),
    ('open issues of https://github.com/psf/requests', ('owner', 'repo'), {'owner': 'psf', 'repo': 'requests'}),
    ('stars of github.com/psf/requests', ('repository',), {'repository': 'psf/requests'}),
    ('citations for 10.1038/nature14539', ('doi',), {'doi': '10.1038/nature14539'}),
]


@pytest.mark.parametrize('task,required,expected', CERTAIN)
def test_a_certain_value_fills_the_placeholder(task, required, expected):
    assert fill(task, tool(*required), placeholders(*required)) == expected


UNCERTAIN = [
    ('weather in Seoul or Tokyo', ('city',)),                    # two cities: which one is not certain
    ('weather in a city', ('city',)),                            # no city
    ('weather in Springfield', ('city',)),                       # not on the list
    ('exchange rate for KRW', ('from', 'to')),                   # one currency, not a pair
    ('stock quote for apple', ('symbol',)),                      # a name, not a listed ticker
    ('weather in Seoul', ('city', 'units_system')),              # one placeholder stays: none filled
    ('send a note to me@example.com', ('domain',)),              # an e-mail address is never read as a domain
    ('translate this text into Korean', ('text',)),              # free text is never copied
    ('try to php before you go', ('from', 'to')),                # lower-case words that are also codes
    ('how to try in php', ('from', 'to')),
    ('usd to krw', ('from', 'to')),                              # lower case without money words
    ('try to php before you convert the file', ('from', 'to')),  # 'convert' is not a money word (files)
]


@pytest.mark.parametrize('task,required', UNCERTAIN)
def test_an_uncertain_value_leaves_every_placeholder(task, required):
    arguments = placeholders(*required)
    assert fill(task, tool(*required), arguments) == arguments


def test_enum_default_and_number_examples_are_kept_and_do_not_block_the_fill():
    arguments = {'city': '<city>', 'units': 'metric', 'days': 1}
    assert fill('weather in Paris', tool('city', 'units', 'days'), arguments) == {'city': 'Paris', 'units': 'metric', 'days': 1}


def test_a_value_with_a_line_break_or_over_200_characters_is_not_filled():
    long_url = 'https://example.org/' + 'a' * 300
    assert fill('read ' + long_url, tool('url'), placeholders('url')) == placeholders('url')
    assert 'url' not in values('see https://example.org/a\nb') or '\n' not in values('see https://example.org/a\nb')['url']


def test_run_here_fills_with_the_task_and_keeps_placeholders_without_it():
    forecast = tool('city', name='forecast')
    assert run_here(5, forecast) == {'tool': 'call', 'arguments': {'resource_id': 5, 'tool': 'forecast',
                                                                    'arguments': {'city': '<city>'}}}
    assert run_here(5, forecast, task='weather in Tokyo')['arguments']['arguments'] == {'city': 'Tokyo'}
    assert run_here(5, forecast, task='weather somewhere')['arguments']['arguments'] == {'city': '<city>'}


def test_filling_adds_no_noticeable_time():
    tasks = [task for task, _, _ in CERTAIN] + [task for task, _ in UNCERTAIN]
    started = time.perf_counter()
    for _ in range(50):
        for task in tasks:
            fill(task, tool('city', 'from', 'to'), placeholders('city', 'from', 'to'))
    per_task = (time.perf_counter() - started) / (50 * len(tasks))
    assert per_task < 0.001                                      # well under a millisecond per task


# PM 11-17 10:3x (plan 2): free-text search arguments take the task's search terms
ACADEMIC = {'name': 'academic_search', 'description': 'Queries OpenAlex and arXiv for peer-reviewed papers and preprints',
            'inputSchema': {'required': ['query'], 'properties': {'query': {'type': 'string'}}}}


@pytest.mark.parametrize('task,expected', [
    ('Find recent arXiv papers about retrieval augmented generation', 'retrieval augmented generation'),  # the tool says arxiv/papers
    ('search news about tesla earnings', 'news tesla earnings'),
    ('details of CVE-2024-3094 please', 'CVE-2024-3094'),          # a certain value is the search itself
    ('summarize https://example.org/post/1', 'https://example.org/post/1'),
])
def test_a_search_argument_takes_the_task(task, expected):
    assert fill(task, ACADEMIC, {'query': '<query>'}) == {'query': expected}


@pytest.mark.parametrize('task', [
    'find papers by Andrew Ng on deep learning',                 # two capitalised words: maybe a person
    'look up the person named Kim in our files',                 # a name cue
    'research Dr. Smith and his lab',
    'email john@example.com the arxiv results',                  # contact details
    'call 010-1234-5678 about the order',
    'news about +1 415 555 0100 spam calls',
    'weather at 221 Baker Street London',                        # a street address
    '강남대로 123 맛집 찾기',                         # a Korean road address
    'what is the weather',                                       # one generic word is not a search
])
def test_a_personal_or_empty_task_leaves_the_search_blank(task):
    assert fill(task, ACADEMIC, {'query': '<query>'}) == {'query': '<query>'}


def test_a_personal_task_fills_nothing_else_either():
    assert fill('weather in Seoul for John Smith', tool('city'), placeholders('city')) == placeholders('city')
    assert fill('weather in New York', tool('city'), placeholders('city')) == {'city': 'New York'}   # a city is not a name


def test_the_card_call_line_is_one_post_with_the_filled_arguments():
    from agent_market.concierge.fast_chat import FastConcierge
    item = {'id': 413095, 'kind': 'mcp', 'name': 'arXiv search', 'url': 'https://provider.example/mcp',
            'usage_endpoint': 'https://agentconcierge.biz/api/gateway/mcp/413095', 'tools_schema': [ACADEMIC],
            'active_checked_at': 1763337554}
    step = run_here(413095, ACADEMIC, task='Find recent arXiv papers about retrieval augmented generation')
    lines = FastConcierge._brief(item, first=True, step=step).splitlines()
    assert lines[1] == 'Run here: call {"resource_id":413095,"tool":"academic_search","arguments":{"query":"retrieval augmented generation"}}'
    assert lines[2] == 'Endpoint: https://agentconcierge.biz/api/gateway/mcp/413095'   # user_slo reads this line
    assert lines[3] == ('Call: one POST to the Endpoint, no session: {"jsonrpc":"2.0","id":1,"method":"tools/call",'
                        '"params":{"name":"academic_search","arguments":{"query":"retrieval augmented generation"}}}')
    later = FastConcierge._brief(item, first=False).splitlines()
    assert later[2] == ('Call: one POST to the Endpoint, no session: {"jsonrpc":"2.0","id":1,"method":"tools/call",'
                        '"params":{"name":"academic_search","arguments":{"query":"<query>"}}}')
    provider = FastConcierge._brief({**item, 'usage_endpoint': 'https://provider.example/mcp'}, first=False).splitlines()
    assert provider[2] == 'Call: initialize → tools/list → tools/call'    # not our gateway: the provider's own steps
