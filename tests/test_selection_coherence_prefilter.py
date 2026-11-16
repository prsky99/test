"""The cheap coherence check in task_scope_matches only skips work; it never changes a decision."""
import random

from agent_market.concierge import selection
from agent_market.concierge.discovery import normalize_task
from agent_market.concierge.selection import _coherence_possible, search_terms, capability_terms, task_scope_matches

WORDS = ('treasury yield spread bond rate weather forecast translate translation speech text transcription audio '
         'invoice pdf extract stock price quote github issues news technology wallet ethereum flight hotel search '
         'polymarket kalshi company facts docs documentation unit convert miles km currency exchange forex').split()
FILLER = 'get list fetch returns data for the a of and with from via tool api service live latest'.split()
QUERIES = ('treasury yield spread', 'bond yield curve', 'weather forecast seoul', 'translate japanese to english',
           'speech to text transcription', 'pdf invoice extraction', 'stock price quote', 'github issues',
           'convert miles to km', 'forex exchange rate', 'ethereum wallet', 'technology news', 'api documentation',
           'flight and hotel search', 'polymarket odds', 'company facts')


def _phrase(rng, low, high):
    words = [rng.choice(WORDS + FILLER) for _ in range(rng.randint(low, high))]
    text = ' '.join(words)
    if rng.random() < .3:
        text = text.capitalize() + '. ' + ' '.join(rng.choice(WORDS + FILLER) for _ in range(rng.randint(2, 8)))
    if rng.random() < .15:
        text += ' (' + ' '.join(rng.choice(WORDS) for _ in range(3)) + ')'
    if rng.random() < .1:
        text += ' - ' + ' '.join(rng.choice(WORDS) for _ in range(3))
    return text


def _tool(rng, shared=None):
    if shared is not None:
        return dict(shared)
    name = '_'.join(rng.choice(WORDS + FILLER) for _ in range(rng.randint(1, 3)))
    return {'name': name, 'description': _phrase(rng, 0, 14) if rng.random() < .85 else ''}


def _listing(rng, shared_tools):
    tools = [_tool(rng) for _ in range(rng.choice((0, 1, 1, 2, 3, 4, 6, 12)))]
    if shared_tools and rng.random() < .4:
        tools += [_tool(rng, shared) for shared in shared_tools]
    if len(tools) >= 3 and rng.random() < .2:
        copied = _phrase(rng, 4, 10)
        for tool in tools[:3]:
            tool['description'] = copied
    return {'kind': rng.choice(('mcp', 'a2a')), 'name': _phrase(rng, 1, 4).title(),
            'description': _phrase(rng, 0, 20), 'usage_tools': '', 'usage_guide': '',
            'usage_full_tools': None, 'cap_languages': None, 'tools': tools}


def test_shortcut_never_changes_a_scope_decision(monkeypatch):
    rng = random.Random(20261104)
    shared_tools = [_tool(rng) for _ in range(20)]
    cases = [(query, _listing(rng, shared_tools)) for _ in range(250) for query in QUERIES]
    decided = []
    for query, resource in cases:
        normalized = normalize_task(query)
        terms = search_terms(normalized)
        core = capability_terms(normalized)
        tools = resource['tools']
        with monkeypatch.context() as patched:
            patched.setattr(selection, '_coherence_possible', lambda *args: True)
            expected = task_scope_matches(terms, resource, core, tools=tools)
        assert task_scope_matches(terms, resource, core, tools=tools) == expected, (query, resource)
        decided.append(expected)
    # The generated listings exercise both outcomes, so the comparison is not vacuous.
    assert any(decided) and not all(decided)


def test_gateway_family_without_the_task_is_rejected_before_tool_filtering(monkeypatch):
    shared = [{'name': f'polymarket_{word}', 'description': 'Prediction market spread between venues.'}
              for word in ('edges', 'kalshi_spread', 'fill_risk', 'arbitrage')]
    resource = {'kind': 'mcp', 'name': 'Linear', 'description': 'Linear issue tracker tools.',
                'tools': shared + [{'name': 'linear_list_issues', 'description': 'List Linear issues.'}]}
    core = ['treasury', 'yield', 'spread']
    assert not _coherence_possible(core, resource, resource['tools'])
    calls = []
    monkeypatch.setattr(selection, '_task_tools', lambda tools, terms=(): calls.append(1) or tools)
    assert not task_scope_matches(core, resource, core, tools=resource['tools'])
    assert calls == []


def test_listing_whose_own_tool_names_the_task_still_reaches_the_full_check():
    resource = {'kind': 'mcp', 'name': 'Treasury Fiscal', 'description': 'US Treasury fiscal data.',
                'tools': [{'name': 'treasury_yield_spread', 'description': 'Treasury yield spread by maturity.'}]}
    assert _coherence_possible(['treasury', 'yield', 'spread'], resource, resource['tools'])
