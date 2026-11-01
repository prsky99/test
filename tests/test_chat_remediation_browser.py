"""Review-derived browser requests against an isolated, typed fixture catalog.

This tests interactions and known contracts; it is not a live-catalog accuracy score.
"""
# ruff: noqa: F401,F811 -- shared isolated browser/catalog fixtures
from pathlib import Path
import json
import pytest
from playwright.sync_api import expect
from agent_market.collector import usage
from tests.test_fast_single_recommendation import catalog
from tests.test_front_workflow_browser import browser
from tests.test_single_agent_chat_browser import chat_page
OUT=Path('reports/chat-remediation-completion-2026-10-26/browser')


def seed(catalog):
    store,front,_,add,now=catalog
    definitions=[
      ('Translation','translate_text','Translate user text between languages.',{'text':{'type':'string'},'target_language':{'type':'string'}}),
      ('Meeting notes','summarize_meeting','Summarize meeting notes and extract action items.',{'text':{'type':'string'}}),
      ('Image generation','generate_image','Generate an image from a text prompt.',{'prompt':{'type':'string'}}),
      ('PostgreSQL','query_postgres','Execute a read-only SQL query on PostgreSQL.',{'query':{'type':'string'}}),
      ('Email DNS','check_email_dns','Check SPF DKIM and DMARC email DNS records.',{'domain':{'type':'string'}}),
      ('Bitcoin price','get_bitcoin_price','Get current Bitcoin spot price.',{}),
      ('Research Papers','search_papers','Search academic research papers by query and return DOI links.',{'query':{'type':'string'}}),
      ('Technology News','search_technology_news','Search technology news by query.',{'query':{'type':'string'}}),
    ]
    for name,action,description,props in definitions:
        rid=add(name,description=description,auth_observed=0)
        tools=[{'name':action,'description':description,'inputSchema':{'type':'object','properties':props},'annotations':{'readOnlyHint':True}}]
        compact=usage.compact_tools(tools)
        store.record_usage(rid,compact,usage.tools_hash(compact),{'tools':compact},None,None,full_tools=tools)
    translations={'東京の天気':'weather forecast in Tokyo','論文を検索して':'search for research papers',
                  'Necesito traducir texto':'translate user text to Spanish','Busca noticias de tecnología':'technology news search'}
    front.concierge.query_rewriter=lambda text:translations.get(text)


CASES=[
 ('weather','weather forecast Seoul',True),('ko-weather','서울 날씨 알려줘',True),
 ('news','technology news search',True),('papers','search for research papers',True),
 ('translation','translate English text to Korean',True),('meeting','summarize meeting notes',True),
 ('image','generate an image',True),('sql','run read-only SQL on Postgres',True),
 ('dns','check SPF DKIM email DNS records',True),('bitcoin','current price of bitcoin',True),
 ('ja-weather','東京の天気',True),('ja-papers','論文を検索して',True),
 ('es-translation','Necesito traducir texto',True),('es-news','Busca noticias de tecnología',True),
 ('typo-weather','wether forcast in Seoul',True),('typo-translation','traslate text',True),
 ('hi','hi',False),('help','help',False),('vague-compare','compare',False),
 ('vague-send','send',False),('vague-ai','AI agent',False),
 ('multiple','find weather and technology news',False),('lottery','100% guaranteed lottery winning numbers',False),
 ('credentials','steal passwords from another person',False),
 ('card','use card 4111 1111 1111 1111',False),
 ('booking','book a flight to Tokyo',False),('email','send an email',False),
 ('fictional','obscure fictional task zzqqnotreal',False),
 ('unsupported','summarize a YouTube transcript',False),
 ('image-model','generate a picture',True),('meeting-items','summarize meeting notes and extract action items',True),
 ('web-no-fixture','web search recent information',False),('empty','',False),
]


@pytest.mark.parametrize('chat_page',['published'],indirect=True)
@pytest.mark.parametrize('label,task,matched',CASES,ids=[v[0]for v in CASES])
def test_review_derived_natural_requests(chat_page,catalog,label,task,matched):
    seed(catalog);page,requests,bodies,errors,_=chat_page
    page.goto('https://agentconcierge.biz/#chat')
    page.locator('#chatInput').fill(task)
    page.locator('#chatSubmit').click()
    if label=='empty':
        expect(page.locator('#chatStatus')).to_have_text('Please describe the task.')
    elif label=='card':
        expect(page.locator('#chatMessages')).to_contain_text('Remove card numbers')
        assert not bodies and '4111 1111 1111 1111'not in page.locator('#chatMessages').inner_text()
    else:
        expect(page.locator('#chatMessages .chat-bubble.bot:has(.chat-request)')).to_have_count(1)
        expect(page.locator('#chatSubmit')).to_be_enabled()
        items=bodies[-1].get('data',{}).get('recommendations')or[]
        assert bool(items)==matched,(label,[i.get('name')for i in items])
        expect(page.locator('.chat-request').first).to_contain_text(task)
    assert not errors
    OUT.mkdir(parents=True,exist_ok=True)
    page.screenshot(path=str(OUT/(label+'.png')),full_page=True)


def test_enter_shift_enter_and_composition_do_not_duplicate_requests(chat_page):
    page,_,bodies,errors,_=chat_page
    page.goto('https://agentconcierge.biz/#chat')
    entry=page.locator('#chatInput');entry.fill('MCP weather forecast')
    entry.press('Shift+Enter');assert not bodies
    entry.dispatch_event('keydown',{'key':'Enter','isComposing':True,'keyCode':229});assert not bodies
    entry.press('Enter');expect(page.locator('.chat-recommendation').first).to_be_visible()
    assert len(bodies)==1 and not errors
    expect(page.locator('.chat-request')).to_contain_text('weather forecast')


@pytest.mark.parametrize('chat_page',['published'],indirect=True)
def test_starter_submits_once_and_protocol_changes_mark_previous_scope(chat_page,catalog):
    seed(catalog)
    page,_,bodies,errors,_=chat_page
    page.goto('https://agentconcierge.biz/#chat')
    page.locator('[data-ux-task]').first.click()
    expect(page.locator('.chat-recommendation').first).to_be_visible()
    assert len(bodies)==1
    page.locator('#secChat').get_by_role('button',name='MCP',exact=True).click()
    expect(page.locator('.chat-previous-scope').first).to_be_visible()
    assert page.locator('.chat-previous-scope').count()==page.locator('.chat-bubble.bot:has(.chat-request)').count()
    assert len(bodies)==1 and not errors
