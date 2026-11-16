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
    keyed = {'id': 4, 'kind': 'mcp', 'auth_required': True}                     # 11-15 mcp/36513: the gateway refuses it
    paid_route = {'id': 5, 'kind': 'x402', 'auth_required': True}               # x402 is paid per call, not refused
    assert not relayable(keyed) and relayable(paid_route)
    assert relayable_only([keyed, read]) == [read]


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


def test_cards_that_need_provider_authorization_are_not_connectable_for_a2a_and_mcp():
    """11-15 06:00 user_slo a2a/86992 (agent card 400 provider_auth_required) and 00:04 mcp/36513."""
    from agent_market.concierge.connections import public_agent
    for kind, available in (('a2a', False), ('mcp', False), ('x402', True)):
        card = public_agent({'id': 86992, 'kind': kind, 'name': 'Rooms', 'url': 'https://rooms.example.net/a2a',
                             'auth_required': True, 'tools': ['review'], 'category': 'dev_tools', 'description': 'd'},
                            create_connections=False)
        assert card['connection_available'] is available, kind
        assert (card.get('connection_reason') == 'provider_authorization') is (not available)


def _ocr(add, now, name, tool, description, read_only, seconds):
    spec = {'name': tool, 'description': description,
            'inputSchema': {'type': 'object', 'properties': {'image_url': {'type': 'string'}}, 'required': ['image_url']},
            'annotations': {'readOnlyHint': read_only}}
    return add(name, report_at=now - seconds, description=f'{name}: {description}', category='document_processing',
               usage_guide=json.dumps({'tools': [spec]}))


def test_capability_only_splits_the_met_requirement_from_the_subject():
    from agent_market.concierge.fast_chat import capability_only
    lead = {'task_fit': {'matched': ['ocr'], 'unknown': [], 'violated': []}, 'matched_terms': ['invoice', 'ocr']}
    assert capability_only(lead) == (['ocr'], ['invoice'])
    assert capability_only({**lead, 'matched_terms': ['ocr']}) == ([], [])          # nothing else was asked
    assert capability_only({**lead, 'task_fit': {'matched': ['pdf_input']}}) == ([], [])   # a condition, not a word
    assert capability_only({}) == ([], [])


def test_an_unrelayed_lead_is_replaced_by_a_relayed_tool_with_its_capability(catalog):
    """PM 11-16 02:2x: user_slo 02:07 'invoice ocr today' recommended InvoiceOracle invoice_ocr (mcp/56920), which the
    gateway does not relay, while relayed OCR tools exist (42449 ocr_image)."""
    _, front, client, add, now = catalog
    unrelayed = _ocr(add, now, 'Invoice Oracle', 'invoice_ocr',
                     'OCR extraction for scanned invoices, then store them in the archive', False, 1)
    relayed = _ocr(add, now, 'Doc Convert', 'ocr_image', 'OCR: extract the text of an image or scanned page', True, 300)
    search = front.concierge.rec.search

    def strict(task, *args, **kwargs):          # the production search requires 'invoice' as a subject word
        found = search(task, *args, **kwargs)
        return [item for item in found if item['id'] != relayed] if 'invoice' in str(task) else found
    front.concierge.rec.search = strict
    recs = ask(client, 'invoice ocr')['data']['recommendations']
    assert recs and recs[0]['id'] == relayed and unrelayed not in [r['id'] for r in recs]
    assert recs[0]['unverified'] == ['invoice']
    assert 'not confirmed (unverified): invoice' in recs[0]['reason']['text']


def test_with_nothing_relayed_a_listing_that_needs_provider_authorization_still_leaves():
    """PM 11-17 02:2x: user_slo 01:06 'send email json output' put mcp/431838 Kivel (send_email, auth_observed=1) first;
    the gateway refused it at initialize ("requires separate provider authorization"). Not one listing: every listing
    that needs the provider's own authorization, whether auth_required is True (ranking) or 1 (hybrid path)."""
    from agent_market.concierge.fast_chat import needs_provider_auth
    keyed_action = {'id': 431838, 'kind': 'mcp', 'tool_unlisted': True, 'auth_required': True}
    keyed_int = {'id': 36513, 'kind': 'mcp', 'auth_required': 1}
    keyed_a2a = {'id': 86992, 'kind': 'a2a', 'auth_required': 1}
    keyless_action = {'id': 7, 'kind': 'mcp', 'tool_unlisted': True, 'auth_required': False}
    unknown = {'id': 8, 'kind': 'mcp', 'tool_unlisted': True, 'auth_required': None}
    x402 = {'id': 9, 'kind': 'x402', 'auth_required': 1}
    assert [needs_provider_auth(i) for i in (keyed_action, keyed_int, keyed_a2a, keyless_action, unknown, x402)] == [
        True, True, True, False, False, False]
    assert not relayable(keyed_int) and not relayable(keyed_a2a) and relayable(x402)
    # nothing relayed: the documentation-link answer keeps keyless listings only
    assert relayable_only([keyed_action, keyless_action, keyed_int, unknown]) == [keyless_action, unknown]
    assert relayable_only([keyed_action, keyed_int]) == []
    assert relayable_only([keyed_int, x402]) == [x402]


def test_a_card_with_auth_required_1_is_not_connectable():
    from agent_market.concierge.connections import public_agent
    card = public_agent({'id': 36513, 'kind': 'mcp', 'name': 'OCR', 'url': 'https://ocr.example/mcp', 'auth_required': 1,
                         'tools': ['ocr'], 'category': 'dev_tools', 'description': 'd'}, create_connections=False)
    assert card['connection_available'] is False and card['connection_reason'] == 'provider_authorization'
