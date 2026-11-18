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
    # PM 11-18: our own agent shows by its role, never by its internal id
    assert item['pearls'][1]['card'] is None and item['pearls'][1]['agent_id'] == 'AgentValCon agent (location)'
    assert item['pearls'][1]['kind'] == 'agentcon'
    snap = {**snapshot, 'necklaces': [entry] + snapshot['necklaces'][1:]}
    status, page = ns.page(entry['slug'], snapshot=snap, now=NOW)
    assert status == 200 and 'location · AgentValCon agent' in page and '/agent/None' not in page
    assert '/agent/own-geocode' not in page



RULES = {'verified_pearl': {'min_score': 85, 'successes_on_different_days': 2},
         'provisional': {'min_score': 70, 'within_days': 7, 'reports': 1, 'own_substitute': 'passed a 30-case held-out gate'}}


def test_the_provisional_note_states_the_bars_and_our_own_agent_is_named_apart(snapshot, monkeypatch):  # noqa: F811
    """PM 11-16 (workflow 17:3x): the outside provisional members scored 79.9-84.7, below the verified bar, so the note
    may not say they 'passed and await a second day'; our own fallback leading a step is said to be ours."""
    assert ns.provisional_note({'member_rules': RULES}) == (
        'Under verification: the agent answered our test for this step within the last 7 days with a score of at least '
        '70, below the verified-pearl bar (85 or more on 2 different days). When a verified pearl is available for the '
        'step, it takes the place.')
    assert ns.provisional_note({'member_rules': {}}) == ns.PROVISIONAL_NOTE and 'second check' not in ns.PROVISIONAL_NOTE
    entry = dict(snapshot['necklaces'][0])
    own = {**entry['pearls'][1], 'standing': 'provisional', 'kind': 'agentcon', 'resource_id': 'avc:wiki-grounding',
           'tool': 'answer_from_wikipedia'}
    entry['pearls'] = [dict(entry['pearls'][0]), own]
    snap = {**snapshot, 'member_rules': RULES, 'necklaces': [entry] + snapshot['necklaces'][1:]}
    monkeypatch.setattr(ns, 'substitute_checked', lambda pearl, path=None: True)
    status, page = ns.page(entry['slug'], snapshot=snap, now=NOW)
    text = page.replace('&#x27;', "'")
    own_line = ('AgentValCon agent, under verification: our own agent for this step, which passed a 30-case held-out '
                'gate; it leads until a verified pearl is available.')
    assert status == 200 and own_line in text and 'necklace-provisional-note' not in page   # no score words for ours
    assert ns.own_provisional_note({'member_rules': {}}) == ns.OWN_PROVISIONAL_NOTE
    monkeypatch.setattr(ns, 'substitute_checked', lambda pearl, path=None: False)     # revoked or no record
    status, page = ns.page(entry['slug'], snapshot=snap, now=NOW)
    text = page.replace('&#x27;', "'")
    assert ns.OWN_UNCHECKED_NOTE in text and 'passed our substitute check' not in text


def test_the_sources_sentence_follows_the_summary_where_one_is_kept(snapshot, monkeypatch):  # noqa: F811
    entry = dict(snapshot['necklaces'][0])
    kept = {entry['slug']: {'sources': 'What each step uses: Wikipedia only.'}}
    monkeypatch.setattr(ns, '_notes', lambda e: kept.get((e or {}).get('slug'), {}))
    assert ns.shown_summary(entry) == (entry.get('summary') or '') + ' What each step uses: Wikipedia only.'
    status, page = ns.page(entry['slug'], snapshot=snapshot, now=NOW)
    assert 'What each step uses: Wikipedia only.' in page
    # PM 22:33: the heading's lead is the summary alone; the sources sentence has its own top-level section
    import re
    assert 'What each step uses' not in re.search(r'<p class="lead">(.*?)</p>', page).group(1)
    assert '<h2 id="sourcesTitle">What each step uses</h2><p class="necklace-sources">What each step uses: Wikipedia only.</p>' in page
    assert 'What each step uses: Wikipedia only.' in ns.llms_section(snapshot=snapshot, now=NOW)
    assert ns.public_item(entry, now=NOW)['sources'] == 'What each step uses: Wikipedia only.'
    other = {**entry, 'slug': 'no-note'}
    assert ns.shown_summary(other) == (entry.get('summary') or '') and 'sources' not in ns.public_item(other, now=NOW)


def test_the_topic_sentence_names_wikipedia_and_unverified_paper_searches():
    note = ns.sources_note({'slug': 'topic-evidence-brief'})
    assert note and 'English Wikipedia' in note and 'not a web search' in note and 'both come from Wikipedia' in note
    # 11-16 terms verdict (4835e5c3): papers are a third-party search with OpenAlex, Crossref (ours) only as fallback
    assert 'OpenAlex' in note and 'third-party paper search agents' in note and 'neither is verified yet' in note
    assert 'Europe PMC' not in note and 'two indexes' not in note



def test_a_substitute_counts_as_checked_only_by_its_latest_passed_record(tmp_path):
    """PM 11-16: approvals.json substitutes; the latest record for the same resource_id and tool decides."""
    import json
    rows = [{'resource_id': 'avc:a', 'tool': 't', 'state': 'provisional', 'at': '2026-11-16T06:52+0900', 'gate_record': {'verdict': 'x'}},
            {'resource_id': 'avc:b', 'tool': 't', 'state': 'provisional', 'at': '2026-11-16T08:11+0900', 'gate_record': {'verdict': 'x'}},
            {'resource_id': 'avc:b', 'tool': 't', 'state': 'revoked', 'at': '2026-11-16T12:35+0900', 'gate_record': {'verdict': 'y'}},
            {'resource_id': 'avc:c', 'tool': 't', 'state': 'approved', 'at': '2026-11-15T08:50+0900', 'gate_record': {}},
            {'resource_id': 'avc:d', 'tool': 't', 'state': 'approved', 'at': '2026-11-15T08:50+0900', 'gate_record': {'verdict': 'z'}}]
    path = tmp_path / 'approvals.json'
    path.write_text(json.dumps({'approvals': [], 'substitutes': rows}))
    check = lambda rid: ns.substitute_checked({'resource_id': rid, 'tool': 't'}, path)   # noqa: E731
    assert check('avc:a') and check('avc:d')
    assert not check('avc:b')                      # revoked after passing: not said to have passed
    assert not check('avc:c') and not check('avc:x')   # no gate record, or no record at all
    assert not ns.substitute_checked({'resource_id': 'avc:a', 'tool': 't'}, tmp_path / 'missing.json')


def test_accuracy_scope_and_attribution_follow_the_kept_notes(snapshot, monkeypatch):  # noqa: F811
    """Agent team 11-16 (PM decision): a necklace whose accuracy was measured on part of what it answers says where, and
    a source whose terms require it (MET Norway) is credited with licence links wherever the necklace is described."""
    entry = dict(snapshot['necklaces'][0])
    notes = {entry['slug']: {'accuracy_scope': 'accuracy measured on US locations',
                             'attribution': {'text': 'Based on data from MET Norway.',
                                             'links': [{'label': 'CC BY 4.0', 'url': 'https://creativecommons.org/licenses/by/4.0/'},
                                                       {'label': 'NLOD 2.0', 'url': 'https://data.norge.no/nlod/en/2.0'}]}}}
    monkeypatch.setattr(ns, '_notes', lambda e: notes.get((e or {}).get('slug'), {}))
    comparison = {'cases': 30, 'measured_at': '2026-11-19', 'with': {'calls': 1, 'tokens': 900, 'seconds': 2.0, 'accuracy': 0.9},
                  'without': {'calls': 4, 'tokens': 3000, 'seconds': 5.0, 'accuracy': 0.5}}
    line = ns.comparison_line({**entry, 'comparison': comparison})
    assert '90% correct (accuracy measured on US locations), about 900 tokens' in line
    snap = {**snapshot, 'necklaces': [{**entry, 'comparison': comparison}] + snapshot['necklaces'][1:]}
    status, page = ns.page(entry['slug'], snapshot=snap, now=NOW)
    assert 'Based on data from MET Norway. Licence: <a href="https://creativecommons.org/licenses/by/4.0/" rel="license noopener">CC BY 4.0</a>' in page
    assert 'Based on data from MET Norway. Licence: CC BY 4.0 https://creativecommons.org/licenses/by/4.0/' in ns.llms_section(snapshot=snap, now=NOW)
    assert ns.public_item(entry, now=NOW)['attribution']['text'] == 'Based on data from MET Norway.'
    other = {**entry, 'slug': 'elsewhere'}
    assert '(accuracy measured' not in ns.comparison_line({**other, 'comparison': comparison}) and 'attribution' not in ns.public_item(other, now=NOW)


def test_the_kept_notes_file_reads_strings_and_objects_and_rejects_odd_links():
    notes = ns._notes({'slug': 'weather-outdoor-brief'})
    assert notes['accuracy_scope'] == 'accuracy measured on US locations'
    assert [l['url'] for l in notes['attribution']['links']] == ['https://creativecommons.org/licenses/by/4.0/',
                                                                  'https://data.norge.no/nlod/en/2.0',
                                                                  'https://api.met.no/doc/License']
    assert ns.sources_note({'slug': 'topic-evidence-brief'}).startswith('What each step uses')


def test_the_provisional_note_with_a_one_day_rule(snapshot):  # noqa: F811
    one = {**RULES, 'verified_pearl': {'min_score': 85, 'successes_on_different_days': 1}}
    note = ns.provisional_note({'member_rules': one})
    assert '(85 or more on its role task). When a verified pearl is available for the step, it takes the place.' in note
    assert 'different days' not in note


def _with_preview(snapshot):
    live = next(e for e in snapshot['necklaces'] if e['slug'] == 'trip-brief')
    preview = {**live, 'slug': 'site-brief', 'name': 'Site brief', 'summary': 'One domain in one answer.',
               'status': 'preview', 'gate_passed_at': None, 'quality': {},
               'preview': {'gate_passed': False, 'note': ns.PREVIEW_NOTE}}
    return {**snapshot, 'necklaces': [*snapshot['necklaces'], preview]}


def test_a_preview_necklace_is_on_the_card_and_the_index_with_its_tag(snapshot):  # noqa: F811
    """PM 21:41 (11-18, user decision: one public necklace shows on home and status): previews after the open ones,
    tagged Preview, never a gate claim; /necklaces lists both with a run link; the sitemap has /necklaces."""
    snap = _with_preview(snapshot)
    assert [e['slug'] for e in ns.available(snap, NOW)] == ['trip-brief', 'site-brief']
    card = ns.why_card(snapshot=snap, now=NOW)
    assert 'href="/necklaces/site-brief">Site brief</a> <span class="necklace-preview-tag">Preview</span>' in card
    assert card.index('trip-brief') < card.index('site-brief') and 'href="/necklaces"' in card
    only = {**snap, 'necklaces': [e for e in snap['necklaces'] if e['slug'] != 'trip-brief']}
    assert 'site-brief' in ns.why_card(snapshot=only, now=NOW)                  # a preview alone still shows
    page = ns.index_page(snapshot=snap, now=NOW)
    for text in ('href="/necklaces/trip-brief"', 'href="/necklaces/site-brief#runTitle"', ns.PREVIEW_NOTE,
                 'One domain in one answer.', 'href="/necklaces/request"', '<link rel="canonical" href="https://agentconcierge.biz/necklaces">'):
        assert text in page, text
    assert 'passed the gate' not in page.split('site-brief')[1].split('</li>')[0]
    assert ns.sitemap_paths(snap, NOW)[0] == '/necklaces' and '/necklaces/site-brief' not in ns.sitemap_paths(snap, NOW)
    assert ns.sitemap_paths(only, NOW) == ['/necklaces']
    none = {**snap, 'necklaces': []}
    assert ns.sitemap_paths(none, NOW) == [] and 'No necklace can be run yet.' in ns.index_page(snapshot=none, now=NOW)


def test_the_index_route_answers(client):  # noqa: F811
    page = client.get('/necklaces', headers={'Accept': 'text/html'})
    assert page.status_code == 200 and '<h1>Necklaces</h1>' in page.text and 'Content-Security-Policy' in page.headers
