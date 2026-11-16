"""Why a necklace, and its measured values, only where an offered necklace is (user instruction 11-15, plan 3.2).

The paragraph gives the reason in words and no number; a necklace's numbers come only from the judge's snapshot
(entry['comparison']: same cases, same day, against an agent calling the member tools itself), worse values included.
Nothing shows while no necklace is offered, so a missing necklace never looks present."""
from agent_market.concierge import necklace_surface as ns
from tests.test_necklace_surface import NOW, necklace, snapshot  # noqa: F401 - fixture

COMPARISON = {'cases': 26, 'measured_at': '2026-11-17',
              'with': {'calls': 1, 'tokens': 1800, 'seconds': 2.4, 'accuracy': 0.96},
              'without': {'calls': 7, 'tokens': 9400, 'seconds': 11.2, 'accuracy': 0.81}}
LINE = ('Measured in our gate runs on 26 cases (2026-11-17): one call, a median of 2.4 s per case, 96% correct, about '
        '1,800 tokens (text length \u00f7 4). From the same runs\' records (not a separate run), an agent calling the same '
        'agents itself would make 7 calls and handle about 9,400 tokens (text length \u00f7 4), taking about 11.2 s if it '
        'sent each step\'s calls at the same time. Finding the tools and merging the answers are not counted.')


def with_comparison(snap, value=COMPARISON):
    snap = {**snap, 'necklaces': [dict(e) for e in snap['necklaces']]}
    snap['necklaces'][0]['comparison'] = value
    return snap


def test_offered_page_says_why_and_shows_measured_values(snapshot):  # noqa: F811
    snap = with_comparison(snapshot)
    status, page = ns.page('trip-brief', snapshot=snap, now=NOW)
    assert status == 200 and '<p class="necklace-why">Why a necklace:' in page
    assert LINE.replace('→', '→') in page.replace('&#x27;', "'")
    shown = ns.public_item(snap['necklaces'][0], now=NOW)['comparison']
    assert shown['with'] == {**COMPARISON['with'], 'tokens_unit': 'text length / 4'}
    assert shown['without'] == {'calls': 7, 'tokens': 9400, 'seconds': 11.2, 'tokens_unit': 'text length / 4',
                                'source': "from the same runs' records, not a separate run"}
    assert shown['basis'] == ns.COMPARISON_BASIS and 'without_full' not in shown
    llms = ns.llms_section(snapshot=snap, now=NOW)
    assert ns.WHY in llms and LINE in llms
    tool = ns.tools(snapshot=snap, now=NOW)[0]['description']
    assert ns.WHY_SHORT in tool and LINE in tool
    assert ns.WHY_SHORT in ns.skills(snapshot=snap, now=NOW)[0]['description']


def test_no_number_without_a_measurement_and_worse_values_stay(snapshot):  # noqa: F811
    status, page = ns.page('trip-brief', snapshot=snapshot, now=NOW)
    assert 'necklace-why' in page and 'necklace-measured' not in page and 'Measured in' not in page
    worse = {**COMPARISON, 'with': {**COMPARISON['with'], 'seconds': 14.0, 'accuracy': 0.7}}
    assert 'a median of 14 s per case, 70% correct' in ns.comparison_line({'comparison': worse})   # worse stays
    for bad in ({**COMPARISON, 'cases': 0}, {**COMPARISON, 'measured_at': 'today'},
                {**COMPARISON, 'with': {**COMPARISON['with'], 'accuracy': 1.2}},
                {**COMPARISON, 'without': {'calls': 7}}, {**COMPARISON, 'with': {**COMPARISON['with'], 'tokens': '1800'}}):
        assert ns.comparison_line({'comparison': bad}) is None


def test_nothing_shows_while_no_necklace_is_offered(snapshot):  # noqa: F811
    held = with_comparison(snapshot)
    status, page = ns.page('paper-digest', snapshot=held, now=NOW)   # held: a page, but not offered
    assert status == 200 and 'necklace-why' not in page and 'Measured in' not in page
    empty = {**snapshot, 'necklaces': [e for e in snapshot['necklaces'] if e['slug'] != 'trip-brief']}
    assert ns.llms_section(snapshot=empty, now=NOW) == '' and ns.tools(snapshot=empty, now=NOW) == []
    assert ns.skills(snapshot=empty, now=NOW) == []
    for text in (ns.WHY, ns.WHY_SHORT):                       # plain reasons, no number, no instruction to the reader
        assert not any(ch.isdigit() for ch in text)
        assert not text.lower().startswith(('use ', 'always', 'you must', 'ignore'))


def test_unmeasured_and_estimated_numbers_never_reach_a_page_or_an_agent(snapshot):  # noqa: F811
    """PM 11-16 display rules: the direct path's accuracy was never run and the full value is estimated; neither is
    shown in any text or public item, while the snapshot keeps them."""
    full = {**COMPARISON, 'without': {**COMPARISON['without'], 'accuracy': 0.47},
            'without_full': {'calls': 9, 'tokens': 14200, 'seconds': 16.8, 'accuracy': 0.81,
                             'estimated': ['find_agents', 'tools_list']}}
    snap = with_comparison(snapshot, full)
    status, page = ns.page('trip-brief', snapshot=snap, now=NOW)
    texts = [page, ns.llms_section(snapshot=snap, now=NOW), ns.tools(snapshot=snap, now=NOW)[0]['description'],
             ns.skills(snapshot=snap, now=NOW)[0]['description'], ns.comparison_line({'comparison': full}),
             str(ns.public_item(snap['necklaces'][0], now=NOW))]
    for text in texts:
        for absent in ('47%', '0.47', '14,200', '14200', '16.8', 'Including finding', '(estimated)', '\u2192'):
            assert absent not in text, (absent, text[:200])
    assert 'Measured in our gate runs' in page and '(text length \u00f7 4)' in ns.comparison_line({'comparison': full})
    assert full['without_full']['tokens'] == 14200      # the judge's snapshot itself is unchanged
