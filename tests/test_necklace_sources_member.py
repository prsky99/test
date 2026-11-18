"""A member's standing in a necklace's sources sentence comes from the verify snapshot when the page is drawn (PM 11-17):
'a verified third-party agent' only while the snapshot marks that agent a verified pearl for that role."""
from agent_market.concierge import necklace_surface as ns

WTB = {'slug': 'website-trust-brief'}


def snap(verified):
    return {'agents': {'39800': {'roles': [{'role': 'dns.mail_auth.v1', 'verified_pearl': verified},
                                           {'role': 'other.role.v1', 'verified_pearl': True}]}}}


def test_the_sentence_reads_the_standing_from_the_snapshot(monkeypatch):
    monkeypatch.setattr(ns, '_notes', lambda entry: {'sources': 'Mail comes from DNS ({member:39800@dns.mail_auth.v1}).'})
    assert ns.sources_note(WTB, snap(True)) == 'Mail comes from DNS (a verified third-party agent).'
    assert ns.sources_note(WTB, snap(False)) == 'Mail comes from DNS (a third-party agent under verification).'
    assert ns.sources_note(WTB, {'agents': {}}) == 'Mail comes from DNS (a third-party agent under verification).'
    # verified for another role does not count
    monkeypatch.setattr(ns, '_notes', lambda entry: {'sources': '({member:39800@dns.records.v1})'})
    assert ns.sources_note(WTB, snap(True)) == '(a third-party agent under verification)'


def test_the_website_trust_sentence_has_no_fixed_standing_for_external_members():
    text = ns._notes(WTB).get('sources')
    assert '{member:52559@domain.lookup.v1}' in text and '{member:39800@dns.mail_auth.v1}' in text
    assert 'verified third-party' not in text and 'DKIM is not checked' in text
    rendered = ns.sources_note(WTB, {'agents': {}})
    # PM 21:33 (11-18): the sentence no longer claims our own lookups take over ("ours is under verification");
    # the fallbacks are drawn from approvals.json under the agents
    assert '{member:' not in rendered and rendered.count('under verification') >= 2 and 'when it fails' not in rendered
