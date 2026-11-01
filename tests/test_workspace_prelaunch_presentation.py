"""All native customer documents preserve the nonce and private-page contract."""
from html.parser import HTMLParser
import re

import pytest
from starlette.datastructures import QueryParams

from agent_market.customer_identity_view import sign_in_page, workspaces_page
from agent_market.customer_organization_service import organizations_page
from agent_market.customer_credit_view import page_for as credits
from agent_market.customer_typed_authoring_view import page_for as studio
from agent_market.customer_authoring_view import page_for as task
from agent_market.customer_recovery_view import page as recovery
from agent_market.workspace_release_service import authorize_page

WS='ws_'+'a'*32


class Document(HTMLParser):
    def __init__(self,source):
        super().__init__();self.tags=[];self.feed(source)
    def handle_starttag(self,tag,attrs):
        self.tags.append((tag,dict(attrs)))


@pytest.mark.parametrize('render',[sign_in_page,workspaces_page,organizations_page,credits,lambda:studio(WS),lambda:task(WS),lambda:recovery(WS),lambda:authorize_page('wap_'+'b'*32,QueryParams({'origin':'https://app.example','redirect_uri':'https://app.example/bff/callback','challenge':'a'*43,'state':'review-state'}),typed=True)])
def test_every_customer_surface_has_private_metadata_and_nonce_protected_local_ui(render):
    response=render();source=response.body.decode();doc=Document(source)
    ids=[attrs['id'] for _,attrs in doc.tags if 'id' in attrs]
    assert len(ids)==len(set(ids))
    assert next(attrs for tag,attrs in doc.tags if tag=='html')['lang']=='en'
    assert not re.search('[\uac00-\ud7af]',source)
    assert response.headers['cache-control']=='no-store'
    assert response.headers['x-robots-tag']=='noindex,noarchive'
    policy=response.headers['content-security-policy']
    assert "default-src 'none'" in policy and "connect-src 'self'" in policy
    assert "frame-ancestors 'none'" in policy and 'unsafe-inline' not in policy
    for tag,attrs in doc.tags:
        assert not any(name.startswith('on') for name in attrs)
        if tag in ('script','style'):
            assert attrs.get('nonce') and "'nonce-"+attrs['nonce']+"'" in policy
        if tag=='script':assert 'src' not in attrs
    assert len([1 for tag,_ in doc.tags if tag=='main'])==1
    assert len([1 for tag,attrs in doc.tags if tag=='body' and 'workspace-pearl' in attrs.get('class','')])==1
