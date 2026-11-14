"""PM 11-14: Chat and find_agents do not recommend a tool the gateway will not relay while a relayed one is admitted
(user_slo 06:04: mcp/36882 translate_file, an action tool, was the only recommendation)."""
# ruff: noqa: F401,F811 -- reuse the isolated catalog fixture
import json

from agent_market.concierge.fast_chat import relayable, relayable_only
from tests.test_fast_single_recommendation import catalog, ask


def test_relayable_only_keeps_relayed_choices_and_the_honest_answer_when_none_is():
    action = {'id': 1, 'kind': 'mcp', 'tool_unlisted': True}
    read = {'id': 2, 'kind': 'mcp'}
    agent = {'id': 3, 'kind': 'a2a'}
    assert not relayable(action) and relayable(read) and relayable(agent)
    assert relayable_only([action, read, agent]) == [read, agent]
    assert relayable_only([action]) == [action]          # nothing relayed: the documentation-link answer stays


def _translator(add, now, name, tool, read_only, seconds):
    spec = {'name': tool, 'description': f'{tool.replace("_", " ").capitalize()} into another language',
            'inputSchema': {'type': 'object', 'properties': {'text': {'type': 'string'}, 'target_lang': {'type': 'string'}},
                            'required': ['text', 'target_lang']},
            'annotations': {'readOnlyHint': read_only}}
    return add(name, report_at=now - seconds, description=f'{name}: translate text into another language.',
               category='language_translation', usage_guide=json.dumps({'tools': [spec]}))


def test_an_unrelayed_translator_is_not_recommended_beside_a_relayed_one(catalog):
    _, _, client, add, now = catalog
    action = _translator(add, now, 'File Translator', 'translate_file', False, 1)
    read = _translator(add, now, 'Text Translator', 'translate_text', True, 300)
    ids = [item['id'] for item in ask(client, 'translate text into french')['data']['recommendations']]
    assert read in ids and action not in ids


def _shipping(add, now, name, tool, description, read_only, seconds):
    spec = {'name': tool, 'description': description,
            'inputSchema': {'type': 'object', 'properties': {'tracking_number': {'type': 'string'}},
                            'required': ['tracking_number']},
            'annotations': {'readOnlyHint': read_only}}
    return add(name, report_at=now - seconds, description=f'{name}: {description}', category='commerce',
               usage_guide=json.dumps({'tools': [spec]}))


def test_a_trait_word_is_dropped_to_find_a_relayed_choice_and_marked_unverified(catalog):
    """PM 11-14 10:3x decision (c): user_slo 'shipping tracking bulk' found only an action tool."""
    from agent_market.concierge.fast_chat import without_traits
    assert without_traits('shipping tracking bulk 953') == ('shipping tracking 953', ['bulk'])
    assert without_traits('crypto price json output') == ('crypto price', ['json output'])
    assert without_traits('translate pdf for free') == ('translate pdf for free', [])   # input and price stay
    _, front, client, add, now = catalog
    action = _shipping(add, now, 'Bulk Fulfilment', 'bulk_shipping_tracking',
                       'Track shipping parcels in bulk and buy labels', False, 1)
    read = _shipping(add, now, 'Parcel Tracker', 'track_shipping', 'Track shipping parcels by tracking number', True, 300)
    search = front.concierge.rec.search

    def strict(task, *args, **kwargs):          # the production search requires 'bulk' as a capability word
        found = search(task, *args, **kwargs)
        return [item for item in found if item['id'] != read] if 'bulk' in str(task) else found
    front.concierge.rec.search = strict
    body = ask(client, 'shipping tracking bulk')
    recs = body['data']['recommendations']
    assert recs and recs[0]['id'] == read and action not in [r['id'] for r in recs]
    assert recs[0]['unverified'] == ['bulk']
    assert 'not confirmed (unverified): bulk' in recs[0]['reason']['text']
