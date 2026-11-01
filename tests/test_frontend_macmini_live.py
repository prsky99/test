"""Opt-in frontend journey with real Mac mini generation and isolated workspace data."""
import json
import os
from pathlib import Path
from urllib.parse import urlsplit

import httpx
import pytest
from playwright.sync_api import expect

from agent_market.customer_identity_service import COOKIE
from agent_market.workflow_model_proposer import OllamaGraphProposer
from agent_market.workspace_app_factory import AppFactory
from scripts.agentcon_config import read_local_model_settings
from tests.test_customer_typed_authoring import customer_flow  # noqa: F401
from tests.test_workspace_typed_release import typed_release_world  # noqa: F401
from tests.test_workspace_typed_flows import typed_world, routing  # noqa: F401
from tests.test_front_workflow_browser import browser  # noqa: F401
from tests.workspace_credit_helpers import save_with_credit

pytestmark = pytest.mark.skipif(os.environ.get('LIVE_MACMINI_FRONTEND_CHECK') != '1',
                               reason='Explicit opt-in required for a real local model request')
PROOF = Path(os.environ.get('LIVE_MODEL_BROWSER_REPORT_DIR','reports/frontend-model-check-2026-10-23'))


@pytest.mark.parametrize('count,width', [(2, 1440), (3, 390)])
def test_live_model_generated_graph_renders_saves_and_tests_without_ollama(customer_flow, browser, count, width):
    x = customer_flow
    before_agent_calls = len(x.w.calls)
    profile = read_local_model_settings('gateway-data/local-model.env')
    assert profile['LOCAL_OLLAMA_ENABLED'] == '0' and profile['WORKSPACE_MODEL_PROVIDER'] == 'openai'
    model_calls = []
    def record(request):
        assert str(request.url) == profile['WORKSPACE_MODEL_URL'].rstrip('/') + '/chat/completions'
        body = json.loads(request.content)
        assert body['model'] == profile['WORKSPACE_MODEL_NAME']
        assert body['chat_template_kwargs'] == {'enable_thinking': False}
        assert x.ws not in json.dumps(body) and x.s.raw not in json.dumps(body)
        model_calls.append({'model': body['model'], 'thinking': False})
    http = httpx.Client(trust_env=False, follow_redirects=False, event_hooks={'request': [record]})
    proposer = OllamaGraphProposer(profile['WORKSPACE_MODEL_URL'], profile['WORKSPACE_MODEL_NAME'], http,
                                   provider='openai', allow_http=profile['WORKSPACE_MODEL_ALLOW_HTTP']=='1')
    x.core.factory.model_source = AppFactory(x.w.core, model_proposer=proposer)
    context = browser.new_context(viewport={'width': width, 'height': 1000}, offline=True)
    context.add_cookies([{'name': COOKIE, 'value': x.s.raw, 'url': 'https://customer.test',
                         'secure': True, 'httpOnly': True, 'sameSite': 'Lax'}])
    page = context.new_page(); errors = []; api = []
    page.on('pageerror', lambda e: errors.append(str(e)))
    def handle(route):
        req = route.request; url = urlsplit(req.url)
        assert url.hostname == 'customer.test'
        result = x.client.request(req.method, url.path, headers=req.headers, content=req.post_data,
                                  follow_redirects=False)
        api.append({'method': req.method, 'path': url.path, 'status': result.status_code})
        route.fulfill(status=result.status_code, body=result.content,
                      headers={k:v for k,v in result.headers.items() if k not in
                               ('content-length','content-encoding','set-cookie','transfer-encoding')})
    context.route('**/*', handle)
    try:
        page.goto('https://customer.test/customer/organizations/'+x.ws+'/flows')
        expect(page.locator('#status')).to_have_text('Review a workflow or inspect retained tests.')
        page.get_by_text('Review and edit exact step inputs', exact=True).click()
        page.locator('#name').fill('Public documentation '+str(count)+' steps')
        page.locator('#objective').fill('Find public Python documentation using exactly '+str(count)+' steps')
        expect(page.locator('#model')).to_be_disabled()
        assert not model_calls
        PROOF.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(PROOF/f'workspace-{count}-before.png'), full_page=True)
        page.locator('#model-consent').check();page.locator('#model').click()
        expect(page.locator('#status')).to_have_text(
            'AI proposal ready. Review the steps and exact inputs before saving.', timeout=60000)
        expect(page.locator('#steps fieldset')).to_have_count(count, timeout=60000)
        proposal = json.loads(page.locator('#proposal').text_content())
        assert len(proposal['steps']) == count
        assert proposal['steps'][1]['bindings']['query']['node_id'] == proposal['steps'][0]['id']
        expect(page.locator('#model-consent')).not_to_be_checked()
        expect(page.locator('#save')).to_be_disabled()
        assert len(model_calls) == 1 and len(x.w.calls) == before_agent_calls
        page.screenshot(path=str(PROOF/f'workspace-{count}-model-review.png'), full_page=True)
        page.locator('#save-consent').check();save_with_credit(page)
        expect(page.locator('#history')).to_have_text('No retained tests for this workflow.')
        assert len(x.w.calls) == before_agent_calls
        flow = x.core.typed.listing(x.ws, x.actor)[0]
        assert flow['step_count'] == count
        expect(page.locator('#workflow-cards .card-strand i')).to_have_count(count)
        page.locator('#prepare').click()
        expect(page.locator('#test-review')).to_contain_text('prior_output_sharing')
        expect(page.locator('#run')).to_be_disabled()
        page.locator('#run-consent').check();page.locator('#run').click()
        expect(page.locator('#history')).to_have_text('Workflow succeeded', timeout=45000)
        assert len(x.w.calls) == before_agent_calls + count and len(model_calls) == 1
        assert not errors and not [item for item in api if item['status'] >= 400]
        assert not page.evaluate('()=>document.documentElement.scrollWidth>innerWidth+1')
        page.screenshot(path=str(PROOF/f'workspace-{count}-after-test.png'), full_page=True)
        (PROOF/f'workspace-{count}-live.json').write_text(json.dumps({'steps':count,'width':width,
            'model_calls':len(model_calls),'agent_calls':len(x.w.calls)-before_agent_calls,'agent_transport':'isolated synthetic MCP',
            'status':'passed','page_errors':errors,'private_production_data_used':False}, indent=2)+'\n')
    finally:
        context.close();http.close()
