"""Generation-only standby transport preserves validation and execution fences."""
import json

import httpx
import pytest

from agent_market.config import GatewayConfig
from agent_market.concierge.llm import LocalLLM
from agent_market.gateway.rag import RagEngine
from agent_market.local_generation import chat_post, chat_stream, endpoints
from agent_market.workflow_model_proposer import OllamaGraphProposer
from agent_market.workspace_access import WorkspaceDenied
from scripts.agentcon_config import ConfigError, read_local_model_fallback_settings
from tests.test_local_generation import MODEL, response
from tests.test_workspace_growth import growth  # noqa: F401
from tests.test_workspace_typed_flows import typed_world, routing, graph  # noqa: F401
from tests.test_workspace_model_proposal import request
from tests.test_workspace_ai_support import assistant, ask, tools  # noqa: F401

PRIMARY = 'http://192.168.0.24:8000/v1'
STANDBY = 'http://192.168.0.25:8000/v1'
PAYLOAD = {'model': MODEL, 'messages': [{'role': 'user', 'content': 'Public example'}]}


def post(client):
    return chat_post(client, PRIMARY, 'openai', PAYLOAD, fallback_endpoint=STANDBY, allow_http=True)


def test_healthy_primary_is_preferred_again_after_standby_use():
    calls = []
    primary_down = False
    def handle(message):
        calls.append(message.url.host)
        assert message.url.path == '/v1/chat/completions'
        assert json.loads(message.content)['model'] == MODEL
        if message.url.host == '192.168.0.24' and primary_down:
            raise httpx.ConnectError('Unavailable', request=message)
        return httpx.Response(200, json=response())
    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        assert post(client).status_code == 200
        primary_down = True
        assert post(client).status_code == 200
        primary_down = False
        assert post(client).status_code == 200
    assert calls == ['192.168.0.24', '192.168.0.24', '192.168.0.25', '192.168.0.24']


@pytest.mark.parametrize('status', [408, 425, 429, 500, 502, 503, 504])
def test_temporary_primary_error_switches_once_with_same_payload(status):
    calls = []
    def handle(message):
        calls.append((message.url.host, message.content))
        return httpx.Response(status if len(calls) == 1 else 200, json=response())
    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        assert post(client).status_code == 200
    assert [c[0] for c in calls] == ['192.168.0.24', '192.168.0.25']
    assert calls[0][1] == calls[1][1]


@pytest.mark.parametrize('status', [302, 400, 401, 403, 404, 422])
def test_redirect_authorization_and_contract_errors_are_not_retried(status):
    calls = []
    def handle(message):
        calls.append(message.url.host)
        return httpx.Response(status, headers={'Location': 'http://unapproved.example/'})
    with httpx.Client(transport=httpx.MockTransport(handle), follow_redirects=True) as client:
        assert post(client).status_code == status
    assert calls == ['192.168.0.24']


def test_both_hosts_failing_uses_existing_concierge_circuit_breaker():
    calls = []
    def handle(message):
        calls.append(message.url.host)
        raise httpx.ConnectTimeout('Unavailable', request=message)
    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        llm = LocalLLM(PRIMARY, MODEL, http=client, provider='openai', fallback_url=STANDBY, allow_http=True)
        assert llm.extract('Find public documentation') is None
        assert llm.status()['paused']
        assert llm.extract('Find public documentation') is None
    assert calls == ['192.168.0.24', '192.168.0.25']


def test_unapproved_model_response_is_rejected_without_replaying_public_input():
    calls = []
    def handle(message):
        calls.append(message.url.host)
        return httpx.Response(200, json=response() | {'model': 'unapproved-model'})
    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        llm = LocalLLM(PRIMARY, MODEL, http=client, provider='openai', fallback_url=STANDBY, allow_http=True)
        assert llm.extract('Find public documentation') is None
    assert calls == ['192.168.0.24']


def test_rag_uses_standby_without_switching_model_or_enabling_ollama():
    calls = []
    def handle(message):
        calls.append(str(message.url))
        return httpx.Response(503 if len(calls) == 1 else 200, json=response('Use the reviewed documentation.'))
    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        engine = RagEngine(generation_model=MODEL, http=client)
        engine.generation_url, engine.generation_fallback_url = PRIMARY, STANDBY
        engine.generation_provider, engine.generation_allow_http = 'openai', True
        result = engine.generate_rag_answer('public documentation', [{'name': 'Docs', 'kind': 'mcp'}], lang='en')
        assert result['answer'] == 'Use the reviewed documentation.'
    assert calls == [PRIMARY + '/chat/completions', STANDBY + '/chat/completions']


def test_graph_standby_returns_same_reviewed_graph_and_no_agent_execution(growth):
    g = growth
    calls = []
    context = []
    g.factory.model_proposer = lambda value: context.append(value) or graph(g.w)
    g.factory.prepare_model_proposal(g.w.ws, request(), g.w.actor)
    def handle(message):
        calls.append(message)
        return httpx.Response(503 if len(calls) == 1 else 200,
                              json=response(json.dumps(graph(g.w))))
    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        proposer = OllamaGraphProposer(PRIMARY, MODEL, client, provider='openai',
                                      allow_http=True, fallback_endpoint=STANDBY)
        assert proposer.propose(context[0]) == graph(g.w)
    assert [c.url.host for c in calls] == ['192.168.0.24', '192.168.0.25']
    assert calls[0].content == calls[1].content
    assert not g.w.calls


def test_standby_rechecks_guard_before_sending():
    calls, guards = [], []
    def handle(message):
        calls.append(message.url.host)
        return httpx.Response(503)
    def guard():
        guards.append(True)
        if len(guards) == 2:
            raise WorkspaceDenied()
    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        with pytest.raises(WorkspaceDenied), chat_stream(client, PRIMARY, 'openai', PAYLOAD,
                fallback_endpoint=STANDBY, allow_http=True, guard=guard):
            pytest.fail('Revoked authority exposed a result')
    assert calls == ['192.168.0.24'] and len(guards) == 2


def test_partial_response_failure_never_replays_on_standby():
    calls = []
    class BrokenStream(httpx.SyncByteStream):
        def __iter__(self):
            yield b'{'
            raise httpx.ReadError('Interrupted')
    def handle(message):
        calls.append(message.url.host)
        return httpx.Response(200, stream=BrokenStream())
    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        with pytest.raises(httpx.ReadError):
            post(client)
    assert calls == ['192.168.0.24']


def test_workspace_guidance_failover_keeps_private_draft_out_of_both_requests(tools):
    core, _ = assistant(tools)
    core.engine.http.close()
    calls = []
    def handle(message):
        calls.append(message)
        value = {'answer': 'Review the saved snapshot before applying a change.',
                 'documents': ['safe-change-review'], 'changes': {'name': 'Reviewed research task'}}
        return httpx.Response(503 if len(calls) == 1 else 200, json=response(json.dumps(value)))
    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        core.engine.http = client
        core.engine.generation_url, core.engine.generation_fallback_url = PRIMARY, STANDBY
        core.engine.generation_provider, core.engine.generation_allow_http = 'openai', True
        core.engine.generation_model = MODEL
        result = ask(tools, core)
        assert result['model_generated'] and not result['executed'] and not result['published']
    assert [c.url.host for c in calls] == ['192.168.0.24', '192.168.0.25']
    for message in calls:
        assert tools['draft']['id'] not in message.content.decode()


@pytest.mark.parametrize('value', ['http://name.example/v1?token=x', 'https://user:secret@example.test/v1',
                                   'file:///private/tmp/model', 'https://example.test/chat/completions'])
def test_standby_endpoint_cannot_add_credentials_or_unapproved_paths(value):
    with pytest.raises(ValueError):
        endpoints(PRIMARY, 'openai', value, allow_http=True)


def test_standby_requires_http_opt_in_and_duplicate_target_is_not_retried():
    with pytest.raises(ValueError):
        endpoints(PRIMARY, 'openai', STANDBY)
    assert endpoints(PRIMARY, 'openai', PRIMARY + '/', allow_http=True) == (PRIMARY,)


def test_standby_profile_and_environment_are_separate_from_retained_release_settings(tmp_path, monkeypatch):
    path = tmp_path / 'local-model-fallback.env'
    path.write_text('WORKSPACE_MODEL_FALLBACK_URL=' + STANDBY + '\n');path.chmod(0o600)
    assert read_local_model_fallback_settings(path) == {'WORKSPACE_MODEL_FALLBACK_URL': STANDBY}
    monkeypatch.setenv('WORKSPACE_MODEL_URL', PRIMARY)
    monkeypatch.setenv('WORKSPACE_MODEL_FALLBACK_URL', STANDBY)
    config = GatewayConfig.from_env()
    assert (config.workspace_model_url, config.workspace_model_fallback_url) == (PRIMARY, STANDBY)
    path.write_text('WORKSPACE_MODEL_URL=' + PRIMARY + '\n')
    with pytest.raises(ConfigError):
        read_local_model_fallback_settings(path)


def test_cli_loads_both_private_profiles_without_starting_a_service(tmp_path):
    from tests.test_agentcon_config import run_check
    main = tmp_path / 'settings.env';main.write_text('HOST=127.0.0.1\n');main.chmod(0o600)
    primary = tmp_path / 'local-model.env'
    primary.write_text('WORKSPACE_MODEL_ENABLED=1\nWORKSPACE_MODEL_PROVIDER=openai\n'
                       'WORKSPACE_MODEL_ALLOW_HTTP=1\nWORKSPACE_MODEL_URL=' + PRIMARY + '\n')
    primary.chmod(0o600)
    standby = tmp_path / 'local-model-fallback.env'
    standby.write_text('WORKSPACE_MODEL_FALLBACK_URL=' + STANDBY + '\n');standby.chmod(0o600)
    result = run_check(main)
    assert result.returncode == 0 and json.loads(result.stdout)['ok']
