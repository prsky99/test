"""Home and Workflows show why a necklace, the offered necklaces and the request link, only while one is offered
(PM 11-15 16:03: a necklace goes public the day it passes its gate, so the pages are ready before that day)."""
from agent_market.concierge import necklace_surface as ns
from tests.test_necklace_surface import NOW, snapshot  # noqa: F401 - fixture
from tests.test_pearl_frontend import client  # noqa: F401 - fixture


def test_card_lists_offered_necklaces_and_the_request_link(snapshot):  # noqa: F811
    card = ns.why_card(snapshot=snapshot, now=NOW)
    assert ns.WHY in card and 'href="/necklaces/trip-brief"' in card and 'href="/necklaces/request"' in card
    assert 'paper-digest' not in card and 'not-approved' not in card            # held or ungated: not listed
    empty = {**snapshot, 'necklaces': [e for e in snapshot['necklaces'] if e['slug'] != 'trip-brief']}
    assert ns.why_card(snapshot=empty, now=NOW) == ''


def test_pages_keep_the_empty_slot_until_a_necklace_is_offered(client, monkeypatch):  # noqa: F811
    for page in ('/new/en/index.html', '/new/en/workflows.html'):
        text = client.get(page).text
        assert ns.WHY_PLACEHOLDER in text and 'necklace-why-card' not in text, page
    monkeypatch.setattr(ns, 'why_card', lambda snapshot=None, now=None: '<section class="card necklace-why-card">x</section>')
    for page in ('/new/en/index.html', '/new/en/workflows.html'):
        text = client.get(page).text
        assert 'necklace-why-card' in text and ns.WHY_PLACEHOLDER not in text, page


def test_each_step_says_pearl_or_under_verification(snapshot):  # noqa: F811
    entry = dict(snapshot['necklaces'][0])
    entry['pearls'] = [dict(entry['pearls'][0]), {**entry['pearls'][1], 'pearl': False, 'standing': 'provisional'}]
    item = ns.public_item(entry, now=NOW)
    assert [p['standing'] for p in item['pearls']] == ['verified_pearl', 'provisional']
    assert [p['verified_pearl'] for p in item['pearls']] == [True, False]
    snap = {**snapshot, 'necklaces': [entry] + snapshot['necklaces'][1:]}
    assert ns.offered(entry, NOW)                                         # a pearl and a provisional member: offered
    status, page = ns.page(entry['slug'], snapshot=snap, now=NOW)
    assert status == 200 and 'Verified pearl</span>' in page and 'Under verification</span>' in page
    assert ns.provisional_note(snap) in page.replace('&#x27;', "'")
    status, page = ns.page('trip-brief', snapshot=snapshot, now=NOW)                 # both pearls: no note
    assert 'Under verification' not in page and 'necklace-provisional-note' not in page
    # an unknown value never reads as a pearl
    assert ns.member_status({'pearl': True, 'standing': 'gold'}) is None
    assert ns.member_status({'pearl': True, 'standing': None}) is None and ns.member_status({}) is None
    assert ns.member_status({'pearl': True}) == 'verified_pearl'                      # a snapshot without standing
    one = {**entry, 'pearls': [entry['pearls'][0], {**entry['pearls'][1], 'standing': None}]}
    assert not ns.offered(one, NOW)                                       # one member that answers: not offered
    assert ns.REASONS['members_unqualified'].startswith('Fewer than two')


def test_agentvalcon_lead_has_no_catalog_card(snapshot):  # noqa: F811
    entry = dict(snapshot['necklaces'][0])
    own = {'agent_id': 'own-geocode', 'role': 'location', 'tool': 'geocode', 'required': True, 'pearl': False,
           'standing': 'provisional', 'kind': 'agentcon', 'alternates': []}
    entry['pearls'] = [entry['pearls'][0], own]
    item = ns.public_item(entry, now=NOW)
    assert item['pearls'][1]['card'] is None and item['pearls'][1]['agent_id'] == 'own-geocode'
    assert item['pearls'][1]['kind'] == 'agentcon'
    snap = {**snapshot, 'necklaces': [entry] + snapshot['necklaces'][1:]}
    status, page = ns.page(entry['slug'], snapshot=snap, now=NOW)
    assert status == 200 and 'location · AgentValCon agent' in page and '/agent/None' not in page
    assert '/agent/own-geocode' not in page



RULES = {'verified_pearl': {'min_score': 85, 'successes_on_different_days': 2},
         'provisional': {'min_score': 70, 'within_days': 7, 'reports': 1}}


def test_the_provisional_note_states_the_bars_and_our_own_agent_is_named_apart(snapshot):  # noqa: F811
    """PM 11-16 (workflow 17:3x): the outside provisional members scored 79.9-84.7, below the verified bar, so the note
    may not say they 'passed and await a second day'; our own fallback leading a step is said to be ours."""
    assert ns.provisional_note({'member_rules': RULES}) == (
        'Under verification: the agent answered our test for this step within the last 7 days with a score of at least '
        '70, below the verified-pearl bar (85 or more on 2 different days). When a verified pearl is available for the '
        'step, it takes the place.')
    assert ns.provisional_note({'member_rules': {}}) == ns.PROVISIONAL_NOTE and 'second check' not in ns.PROVISIONAL_NOTE
    entry = dict(snapshot['necklaces'][0])
    own = {**entry['pearls'][1], 'standing': 'provisional', 'kind': 'agentcon', 'resource_id': None}
    entry['pearls'] = [dict(entry['pearls'][0]), own]
    snap = {**snapshot, 'member_rules': RULES, 'necklaces': [entry] + snapshot['necklaces'][1:]}
    status, page = ns.page(entry['slug'], snapshot=snap, now=NOW)
    text = page.replace('&#x27;', "'")
    assert status == 200 and ns.OWN_PROVISIONAL_NOTE in text and 'necklace-provisional-note' not in page


def test_the_sources_sentence_follows_the_summary_where_one_is_kept(snapshot, monkeypatch):  # noqa: F811
    entry = dict(snapshot['necklaces'][0])
    monkeypatch.setitem(ns._SOURCES, 'value', {entry['slug']: 'What each step uses: Wikipedia only.'})
    monkeypatch.setattr(ns, 'sources_note', lambda e: ns._SOURCES['value'].get((e or {}).get('slug')))
    assert ns.shown_summary(entry) == (entry.get('summary') or '') + ' What each step uses: Wikipedia only.'
    status, page = ns.page(entry['slug'], snapshot=snapshot, now=NOW)
    assert 'What each step uses: Wikipedia only.' in page
    assert 'What each step uses: Wikipedia only.' in ns.llms_section(snapshot=snapshot, now=NOW)
    assert ns.public_item(entry, now=NOW)['sources'] == 'What each step uses: Wikipedia only.'
    other = {**entry, 'slug': 'no-note'}
    assert ns.shown_summary(other) == (entry.get('summary') or '') and 'sources' not in ns.public_item(other, now=NOW)


def test_the_topic_sentence_names_wikipedia_and_two_paper_indexes():
    note = ns.sources_note({'slug': 'topic-evidence-brief'})
    assert note and 'English Wikipedia' in note and 'not a web search' in note and 'both come from Wikipedia' in note
    assert 'OpenAlex' in note and 'Europe PMC' in note
