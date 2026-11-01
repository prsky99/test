"""OpenAI-compatible local generation cannot change authority or use Ollama fallback."""
import copy
import json

import httpx
import pytest

from agent_market.concierge.llm import LocalLLM
from agent_market.gateway.rag import RagEngine, RagPipeline
from agent_market.local_generation import chat_request, completion, validate_endpoint
from agent_market.workflow_model_proposer import OllamaGraphProposer
from agent_market.workspace_access import WorkspaceConflict, WorkspaceDenied, WorkspaceInvalid
from scripts.agentcon_config import ConfigError, read_local_model_settings
from tests.test_workspace_ai_support import assistant, ask, tools  # noqa: F401
from tests.test_workspace_growth import growth  # noqa: F401
from tests.test_workspace_typed_flows import typed_world, routing  # noqa: F401
from tests.test_workspace_model_proposal import request

URL = 'http://192.168.0.25:8000/v1'
MODEL = 'gemma4-e4b-mlx'


def response(content='OK'):
    return {'model': MODEL, 'choices': [{'index': 0, 'finish_reason': 'stop',
            'message': {'role': 'assistant', 'content': content, 'reasoning_content': None}}]}


def test_protocol_mapping_turns_off_thinking_and_keeps_json_schema():
    schema = {'type': 'object', 'properties': {'ok': {'type': 'boolean'}}}
    original = {'model': MODEL, 'stream': False, 'think': False, 'format': schema,
                'messages': [{'role': 'user', 'content': 'Public objective'}],
                'options': {'num_predict': 300, 'temperature': 0}}
    saved = copy.deepcopy(original)
    url, body = chat_request(URL, 'openai', original)
    assert url == URL + '/chat/completions'
    assert body['chat_template_kwargs'] == {'enable_thinking': False}
    assert body['max_tokens'] == 300 and body['temperature'] == 0
    assert body['response_format']['json_schema']['schema'] == schema
    assert not {'think', 'options', 'keep_alive', 'format'} & set(body)
    assert original == saved
    assert chat_request(URL.removesuffix('/v1'), 'openai', original)[0] == url
    assert chat_request('http://127.0.0.1:11434', 'ollama', original) == ('http://127.0.0.1:11434/api/chat', original)


@pytest.mark.parametrize('change', ['model', 'length', 'tools', 'thinking', 'refusal', 'multiple'])
def test_incomplete_reasoning_or_tool_output_is_rejected(change):
    outer = response()
    if change == 'model': outer['model'] = 'other-model'
    elif change == 'length': outer['choices'][0]['finish_reason'] = 'length'
    elif change == 'tools': outer['choices'][0]['message']['tool_calls'] = [{'function': {'name': 'execute'}}]
    elif change == 'thinking': outer['choices'][0]['message']['reasoning_content'] = 'private reasoning'
    elif change == 'refusal': outer['choices'][0]['message']['refusal'] = 'refused'
    else: outer['choices'] *= 2
    with pytest.raises(ValueError): completion(outer, 'openai', MODEL)


def test_remote_http_requires_explicit_fixed_operator_configuration():
    with pytest.raises(ValueError): validate_endpoint(URL, 'openai')
    assert validate_endpoint(URL, 'openai', allow_http=True) == URL
    for endpoint in ('http://user:secret@host/v1', URL+'?key=secret', URL+'/chat/completions', URL+'#private'):
        with pytest.raises(ValueError): validate_endpoint(endpoint, 'openai', allow_http=True)


@pytest.mark.parametrize('revoke', [False, True])
def test_graph_proposal_uses_openai_but_preserves_review_and_authority(growth, revoke):
    g = growth
    calls = []
    def respond(message):
        assert str(message.url) == URL+'/chat/completions'
        body = json.loads(message.content); calls.append(body)
        context = json.loads(body['messages'][1]['content'])
        if revoke:
            with g.w.store.tx() as db:
                db.execute('UPDATE workspace_memberships SET revision=revision+1 WHERE workspace_id=?', (g.w.ws,))
        assert set(context)=={'public_objective','search_topic','language'}
        compact = {'query': 'Public Python documentation'}
        return httpx.Response(200, json=response(json.dumps(compact)))
    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        g.factory.model_proposer = OllamaGraphProposer(URL, MODEL, client, provider='openai', allow_http=True)
        if revoke:
            with pytest.raises((WorkspaceDenied, WorkspaceConflict)):
                g.factory.prepare_model_proposal(g.w.ws, request(), g.w.actor)
            assert not g.w.store.query('SELECT id FROM workspace_factory_reviews')
        else:
            review = g.factory.prepare_model_proposal(g.w.ws, request(), g.w.actor)
            assert len(review['definition']['nodes']) == 2 and not review['automatic_execution']
            assert review['agent_calls'] == 0 and review['model_calls'] == 1
        assert len(calls) == 1 and not g.w.calls
        assert calls[0]['chat_template_kwargs']['enable_thinking'] is False
        for value in (g.w.ws, g.w.raw, g.w.actor.session_ref):
            assert value not in json.dumps(calls)


def test_ollama_disabled_blocks_embeddings_without_touching_index_or_network():
    def forbidden(request): raise AssertionError('Ollama must not receive any request')
    with httpx.Client(transport=httpx.MockTransport(forbidden)) as client:
        engine = RagEngine(http=client)
        engine.embeddings_enabled = False
        assert engine.embed_texts(['Public text']) is None
        assert engine.embed_query('Public text') is None
        assert engine.index_resources(None, [{'id': 1}]) == 0
        assert RagPipeline(engine).step(None) == {'type': 'disabled', 'count': 0, 'reason': 'embedding_provider_disabled'}


def test_concierge_openai_availability_and_extract_keep_existing_validation():
    calls = []
    def respond(message):
        calls.append(str(message.url))
        if message.method == 'GET': return httpx.Response(200, json={'data': [{'id': MODEL}]})
        body = json.loads(message.content)
        assert body['chat_template_kwargs'] == {'enable_thinking': False}
        return httpx.Response(200, json=response(json.dumps({'intent': 'find', 'task': 'public documentation',
            'search_query_en': 'documentation search', 'kind': '', 'agent_name': ''})))
    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        llm = LocalLLM(URL, MODEL, http=client, provider='openai')
        assert llm.available()
        assert llm.extract('Find public documentation')['intent'] == 'find'
        assert calls == [URL+'/models', URL+'/chat/completions']


def test_generation_profile_cannot_override_identity_or_database_settings(tmp_path):
    p = tmp_path/'local-model.env'
    p.write_text('WORKSPACE_MODEL_PROVIDER=openai\nLOCAL_OLLAMA_ENABLED=0\n'); p.chmod(0o600)
    assert read_local_model_settings(str(p))['LOCAL_OLLAMA_ENABLED'] == '0'
    p.write_text('ADMIN_TOKEN=not-allowed\n')
    with pytest.raises(ConfigError): read_local_model_settings(str(p))


def test_disabled_ollama_keeps_rag_generation_on_fixed_remote_model_without_fallback():
    calls = []
    def respond(message):
        calls.append(message)
        assert str(message.url) == URL+'/chat/completions'
        return httpx.Response(503)
    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        engine = RagEngine(generation_model=MODEL, http=client)
        engine.generation_url, engine.generation_provider, engine.embeddings_enabled = URL, 'openai', False
        result = engine.generate_rag_answer('public documentation', [{'name':'Public Docs','description':'Documentation','kind':'mcp'}], lang='en')
        assert result['answer'] and len(calls) == 1


def test_workspace_guidance_uses_remote_generation_but_shares_no_private_draft(tools):
    core, _ = assistant(tools)
    core.engine.http.close()
    calls = []
    def respond(message):
        assert str(message.url) == URL+'/chat/completions'
        body = json.loads(message.content); calls.append(body)
        shared = json.loads(body['messages'][1]['content'])
        assert set(shared) == {'public_objective', 'documents'}
        content = {'answer': 'Review the saved snapshot before applying a change.',
                   'documents': ['safe-change-review'], 'changes': {'name': 'Reviewed research task'}}
        return httpx.Response(200, json=response(json.dumps(content)))
    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        core.engine.http = client
        core.engine.generation_url, core.engine.generation_provider = URL, 'openai'
        core.engine.generation_allow_http, core.engine.generation_model = True, MODEL
        result = ask(tools, core)
        assert result['model_generated'] and not result['executed'] and not result['published']
        assert len(calls) == 1 and calls[0]['chat_template_kwargs'] == {'enable_thinking': False}
        assert tools['draft']['id'] not in json.dumps(calls)
