"""Constrained model requests use only approved public context and need consent."""
import json
from types import SimpleNamespace

import httpx
import pytest

from agent_market.workspace_ai_support import WorkspaceAISupport, NOTICE
from agent_market.workspace_access import WorkspaceConflict, WorkspaceDenied, WorkspaceInvalid
from tests.test_advancement_tools import tools


def assistant(t, output=None, before=None):
    calls = []
    value = output or {'answer': 'Review the saved snapshot before applying a change.',
        'documents': ['safe-change-review'], 'changes': {'name': 'Reviewed research task'}}
    def respond(request):
        calls.append(json.loads(request.content))
        if before:
            before()
        content = value if isinstance(value, str) else json.dumps(value)
        return httpx.Response(200, json={'message': {'content': content}})
    engine = SimpleNamespace(ollama_url='http://planner.test', generation_model='synthetic-model',
        http=httpx.Client(transport=httpx.MockTransport(respond)))
    return WorkspaceAISupport(t['access'], engine), calls


def ask(t, core, **changes):
    return core.suggest(t['ws'], t['draft']['id'], t['snapshot']['id'],
        {'objective': 'Suggest a clearer draft name for a public news research workflow',
         'authorized': True, 'notice': NOTICE, **changes}, t['actors'][1])


def test_model_proposal_is_retained_but_requires_separate_patch_application(tools):
    t = tools; core, calls = assistant(t)
    value = ask(t, core)
    assert len(calls) == 1 and value['model_generated'] and not value['guidance_verified']
    assert value['proposal']['model_generated'] and not value['executed'] and not value['published']
    shared = json.loads(calls[0]['messages'][1]['content'])
    assert set(shared) == {'public_objective', 'documents'}
    assert t['draft']['id'] not in json.dumps(calls) and t['snapshot']['id'] not in json.dumps(calls)
    assert t['access'].draft(t['ws'], t['draft']['id'], t['actors'][1])['revision'] == 1


def test_no_consent_or_unconfigured_engine_never_calls_model(tools):
    t = tools; core, calls = assistant(t)
    with pytest.raises(WorkspaceInvalid): ask(t, core, authorized=False)
    with pytest.raises(WorkspaceDenied): ask(t, WorkspaceAISupport(t['access']))
    assert calls == []


@pytest.mark.parametrize('value', [
    {'answer': 'Review your task.', 'documents': ['untrusted'], 'changes': {}},
    {'answer': 'Run a command.', 'documents': ['safe-change-review'], 'changes': {'command': 'publish'}},
    {'answer': 'Read https://untrusted.example', 'documents': ['safe-change-review'], 'changes': {}},
    '{"answer":"one","answer":"two","documents":["safe-change-review"],"changes":{}}',
    {'answer': 'Review your task.', 'documents': ['safe-change-review'], 'changes': {'name': 'token=synthetic-private'}},
])
def test_model_cannot_supply_new_sources_paths_commands_or_secrets(tools, value):
    core, calls = assistant(tools, value)
    with pytest.raises(WorkspaceInvalid): ask(tools, core)
    assert len(calls) == 1
    assert tools['store']._db.execute('SELECT COUNT(*) FROM workspace_support_proposals').fetchone()[0] == 0


def test_member_aba_during_network_prevents_a_patch_or_guidance_result(tools):
    t = tools
    def change():
        with t['store']._db as db:
            db.execute('UPDATE workspace_memberships SET revision=revision+2 WHERE workspace_id=? AND user_id=1', (t['ws'],))
    core, calls = assistant(t, before=change)
    with pytest.raises(WorkspaceConflict): ask(t, core)
    assert len(calls) == 1 and t['store']._db.execute('SELECT COUNT(*) FROM workspace_support_proposals').fetchone()[0] == 0


def test_generated_guidance_cannot_become_provider_quality_evidence(tools):
    t = tools; core, calls = assistant(t, {'answer': 'Read the saved snapshot guidance.',
        'documents': ['private-snapshots'], 'changes': {}})
    result = ask(t, core)
    assert result['proposal'] is None and not result['guidance_verified']
    assert result['source_documents'][0]['id'] == 'private-snapshots'
