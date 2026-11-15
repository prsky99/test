"""A required step with no usable outside member says so (PM 11-16 06:5x): on the necklace page, in /api/necklaces,
in the agent-facing texts (details, llms.txt, MCP tool and A2A skill descriptions). Computed from the judge's snapshot,
so the note disappears by itself once an outside member that passes our tests is attached."""
from agent_market.concierge import necklace_surface as ns
from tests.test_necklace_surface import NOW, necklace, snapshot  # noqa: F401 - fixture


def own_only(role='registry', **extra):
    return {'agent_id': 'sec-edgar', 'role': role, 'tool': 'find_sec_company', 'kind': 'agentcon', 'required': True,
            'pearl': False, 'standing': 'provisional', 'alternates': [], **extra}


def with_steps(entry, *pearls):
    return {**entry, 'pearls': list(entry['pearls'][:1]) + list(pearls)}


def test_counting_follows_the_snapshot():
    assert ns.usable_external(own_only()) == 0 and ns.external_pending(own_only())
    failing = own_only(alternates=[{'resource_id': 5, 'tool': 't', 'kind': 'external', 'standing': None}])
    assert ns.external_pending(failing)                      # an outside member that does not pass our tests now
    passing = own_only(alternates=[{'resource_id': 5, 'tool': 't', 'kind': 'external', 'standing': 'provisional'}])
    assert ns.usable_external(passing) == 1 and not ns.external_pending(passing)   # attached: the note goes away
    assert not ns.external_pending(own_only(required=False))                 # optional steps are not flagged
    assert ns.usable_external(own_only(external_usable=2)) == 2               # the judge's own count wins
    old = {'role': 'x', 'alternates': [{'kind': 'external'}]}                # a snapshot without standing
    assert ns.usable_external(old) == 2


def test_page_api_and_agent_texts_say_it(snapshot):  # noqa: F811
    entry = with_steps(snapshot['necklaces'][0], own_only())
    snap = {**snapshot, 'necklaces': [entry] + snapshot['necklaces'][1:]}
    status, page = ns.page(entry['slug'], snapshot=snap, now=NOW)
    assert status == 200 and page.count('<span class="necklace-external-pending">' + ns.EXTERNAL_PENDING + '</span>') == 1
    item = ns.public_item(entry, now=NOW)
    assert [p['external_pending'] for p in item['pearls']] == [False, True]
    assert item['pearls'][1]['external_usable'] == 0
    sentence = 'The registry step runs on our own agent; an external alternative is being added.'
    assert ns.pending_sentence(entry) == sentence
    assert sentence in ns.llms_section(snapshot=snap, now=NOW)
    assert sentence in ns.tools(snapshot=snap, now=NOW)[0]['description']
    assert sentence in ns.skills(snapshot=snap, now=NOW)[0]['description']
    text, _ = ns.details(entry['slug'], snapshot=snap, now=NOW)
    assert 'runs on our own agent; external alternative being added' in text


def test_nothing_is_said_when_every_step_has_an_outside_member(snapshot):  # noqa: F811
    entry = snapshot['necklaces'][0]
    status, page = ns.page(entry['slug'], snapshot=snapshot, now=NOW)
    assert 'necklace-external-pending' not in page and ns.pending_sentence(entry) == ''
