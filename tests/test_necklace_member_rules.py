"""Methodology paragraph on necklace members (PM 11-15 16:03): numbers come from the judge's snapshot member_rules
(workflow f9ba1876), which carries gate_rules.REPORT_SCORE, report_v2.CONFIRM_DAYS and members.PROVISIONAL, so the
page never keeps its own copy. A rule with missing or null numbers is left out."""
from agent_market.concierge import necklace_surface as ns

RULES = {'verified_pearl': {'min_score': 85, 'successes_on_different_days': 2},
         'provisional': {'min_score': 70, 'within_days': 7, 'reports': 1, 'own_substitute': 'passed a 30-case held-out gate'}}


def test_paragraph_uses_the_snapshot_numbers():
    text = ns.member_rules_text({'member_rules': RULES})
    assert 'at least 85 in our test reports on 2 different days' in text
    assert 'at least 70 in a test report within the last 7 days, or our own substitute that passed a 30-case held-out gate' in text
    assert text.endswith('its page says which kind leads each step.')


def test_null_numbers_drop_their_sentence_and_markup_stays_text():
    unread = {**RULES, 'verified_pearl': {'min_score': None, 'successes_on_different_days': None}}
    text = ns.member_rules_text({'member_rules': unread})
    assert 'verified pearl when' not in text and 'at least 70' in text
    assert ns.member_rules_text({'member_rules': {'verified_pearl': {}, 'provisional': {}}}) is None
    assert ns.member_rules_text({}) is None
    odd = {**RULES, 'provisional': {**RULES['provisional'], 'own_substitute': '<b>x</b>'}}
    assert '&lt;b&gt;x&lt;/b&gt;' in ns.member_rules_text({'member_rules': odd})


def test_comparison_names_the_number_of_steps():
    value = {'cases': 26, 'measured_at': '2026-11-17', 'slots': 3,
             'with': {'calls': 1, 'tokens': 1800, 'seconds': 2.4, 'accuracy': 0.96},
             'without': {'calls': 7, 'tokens': 9400, 'seconds': 11.2, 'accuracy': 0.81}}
    assert 'against an agent calling the same 3 agents itself' in ns.comparison_line({'comparison': value})


def test_page_says_the_real_number_of_agents():
    from tests.test_necklace_surface import NOW, necklace
    entry = necklace('trip-brief')
    snap = {'schema': ns.SCHEMA, 'necklaces': [entry], 'events': []}
    status, page = ns.page('trip-brief', snapshot=snap, now=NOW)
    assert 'This necklace joins 2 agents in one call.' in page            # two required members, no more is claimed
    snap['necklaces'][0] = {**entry, 'comparison': {'slots': 3}}
    assert 'This necklace joins 3 agents in one call.' in ns.page('trip-brief', snapshot=snap, now=NOW)[1]
    assert ns.steps_sentence({'pearls': [{'required': True}]}) == ''
