"""The customer workspace portal is implemented but not publicly released."""
from fastapi.testclient import TestClient
import pytest

from agent_market.concierge.front import Front, HTML, create_front_app
from agent_market.workspace_platform import public_router_for
from tests.test_front_about import about_client


@pytest.mark.parametrize('path', [
    '/customer/sign-in', '/customer/workspaces', '/customer/organizations',
    '/api/customer-auth/options', '/api/customer-auth/session',
    '/api/customer-organizations', '/api/workspace-apps-v2/authorize',
])
def test_workspace_portal_is_closed_by_default_in_actual_front_app(about_client, path):
    response = about_client.get(path)
    assert response.status_code == 404
    assert 'Google' not in response.text and 'session_ref' not in response.text


def test_workspace_portal_not_advertised_and_disabled_router_never_constructs_components():
    assert 'Workspace access' not in HTML and 'href="/customer/sign-in"' not in HTML
    assert not public_router_for(None).routes
    with pytest.raises(ValueError):
        public_router_for(None, workspace_access_enabled='true')


def test_workspace_post_and_callback_cannot_be_used_on_closed_frontend(about_client):
    assert about_client.post('/api/customer-auth/begin', json={'provider': 'google'}).status_code == 404
    assert about_client.get('/api/customer-auth/callback?code=synthetic&state=synthetic').status_code == 404
    assert about_client.post('/api/customer-organizations', json={}).status_code == 404
