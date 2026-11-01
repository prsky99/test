"""About content, discovery metadata and public security remain aligned."""
import ast
from html.parser import HTMLParser
from pathlib import Path
import re
import sqlite3

from fastapi.testclient import TestClient
import pytest

from agent_market.concierge.front import Front,HTML,clear_front_caches,create_front_app
from agent_market.gateway import admin_auth
from agent_market.gateway.store import Store
from agent_market.infra.redis_hub import RedisHub

TITLE='Agent Concierge — About Our Service & Vision'
pytestmark = pytest.mark.usefixtures('legacy_public_entry')

@pytest.fixture
def about_client(tmp_path,monkeypatch,legacy_public_entry):
    cache=RedisHub();cache._closed=True;monkeypatch.setattr(RedisHub,'get_instance',staticmethod(lambda:cache))
    path=tmp_path/'about-synthetic.sqlite3'
    with sqlite3.connect(path) as db:
        db.executescript(admin_auth.ADMIN_SCHEMA);admin_auth.create_admin_user(db,'sadmin','Synthetic-about-only-password','Synthetic owner','superadmin')
    clear_front_caches();store=Store(str(path));client=TestClient(create_front_app(Front(store,allow_private=True)),base_url='https://agentconcierge.biz')
    yield client
    client.close();store._db.close();clear_front_caches()


class Document(HTMLParser):
    def __init__(self,text):super().__init__();self.items=[];self.feed(text)
    def handle_starttag(self,tag,attrs):self.items.append((tag,dict(attrs)))


def about_source():return HTML.split('<section id="secAbout"',1)[1].split('  <!-- SECTION 1:',1)[0]


def test_about_navigation_order_and_brand_home_are_accessible(about_client):
    response=about_client.get('/',headers={'Accept':'text/html'});assert response.status_code==200
    html=response.text;tabs=re.findall(r'<button class="nav-tab(?: on)?" data-tab="([^"]+)"',html)
    assert tabs==['learn','explore','test','workflows','chat','register','about']
    document=Document(html);brand=next(attrs for tag,attrs in document.items if tag=='a' and attrs.get('class')=='brand-box')
    assert brand['href']=='#overview' and brand['aria-label']=='Agent Concierge Home'
    assert 'id="secOverview"' in html and 'id="homeRecommendationIntro"' in html
    assert 'data-tab="overview"' not in html


def test_about_metadata_discovery_and_home_guide_are_consistent(about_client):
    html=about_client.get('/',headers={'Accept':'text/html'}).text;document=Document(html)
    metas={attrs.get('name'):attrs.get('content') for tag,attrs in document.items if tag=='meta'}
    assert metas['page:about:title']==TITLE
    for key in ('description','keywords','target-action','how-to-use','capabilities','retention-hook'):assert metas['page:about:'+key]
    assert 'About' in metas['agent:menu-directory'] and 'logo' in metas['page:overview:home-access']
    assert 'Home:' not in metas['agent:menu-directory'] and 'page:overview:menu:home' not in metas
    assert 'A2A first, then MCP' in metas['description'] and 'Daily snapshot:' in metas['description']
    assert '"@type": "WebPage"' in html  # Initial document describes Home; navigation updates its graph.
    from agent_market.concierge.public_metadata import url
    sitemap=about_client.get('/sitemap.xml');assert sitemap.status_code==200 and url('about') in sitemap.text and url('overview') in sitemap.text
    for path in ('/llms.txt','/llms-full.txt'):
        response=about_client.get(path);assert response.status_code==200 and url('about') in response.text


def test_about_copy_is_english_static_no_private_details_or_unsupported_guarantees():
    section=about_source();document=Document(section)
    assert not re.search(r'[\uac00-\ud7a3]',section)
    assert all(not name.lower().startswith('on') for _,attrs in document.items for name in attrs)
    assert not re.search(r'(?i)(/Users/|/private/|localhost|127\.0\.0\.1|api[_ -]?key|bearer|99\.9|SDK\s*2|we are developing|guaranteed|revenue|\bCAC\b)',section)
    assert 'Our vision' in section and 'We envision' in section and 'not a guarantee' in section
    links=[attrs['href'] for tag,attrs in document.items if tag=='a']
    assert set(links)<={'#chat','#explore','#workflows','#register','#privacy','#tos','#accessibility','#learn'}
    assert {'#chat','#explore','#workflows','#register','#privacy','#tos','#accessibility'}<=set(links)
    svgs=[attrs for tag,attrs in document.items if tag=='svg'];assert len(svgs)>=3
    assert all('lucide' in attrs['class'] and attrs['aria-hidden']=='true' and attrs['focusable']=='false' for attrs in svgs)


def test_about_addition_preserves_embedded_html_and_csp(about_client):
    assert HTML==Path('extracted_html.txt').read_text()
    tree=ast.parse(Path('agent_market/concierge/front.py').read_text());node=next(n for n in tree.body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='HTML' for t in n.targets));assert ast.literal_eval(node.value)==HTML
    response=about_client.get('/',headers={'Accept':'text/html'});policy=response.headers['content-security-policy']
    assert "frame-ancestors 'none'" in policy and "object-src 'none'" in policy and "'unsafe-inline'" not in policy.split('script-src',1)[1].split(';',1)[0]
    assert response.headers['x-frame-options']=='DENY' and response.headers['x-content-type-options']=='nosniff'
    assert '/api/customer-auth/' not in about_source() and '/admin/' not in about_source()
