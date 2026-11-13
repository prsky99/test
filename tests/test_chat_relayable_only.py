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
