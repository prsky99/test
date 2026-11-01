import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agent_market.first_party_corpus import ApprovedDocument,ApprovedCorpusAgent,router_for
from agent_market.capability_contracts import validate

CORPUS=(ApprovedDocument('Public API operations','https://docs.example/operations','revision-1',
    'The inventory API supports pagination with a continuation cursor. Every response includes its current revision.'),
    ApprovedDocument('Public event delivery','https://docs.example/events','revision-2',
    'Webhook events contain an event ID and an authenticated timestamp. Consumers deduplicate each event ID.'))


def test_business_retrieval_returns_exact_source_excerpt_and_empty_is_truthful():
    agent=ApprovedCorpusAgent(CORPUS)
    args={'query':'pagination continuation cursor','language':'en','limit':2}
    result=agent.search(args);validate('docs.search.v1',args,result)
    assert result['items'][0]['url']==CORPUS[0].url
    assert result['items'][0]['excerpt'] in CORPUS[0].text
    assert not agent.search(args|{'query':'unmatchedword'})['items']
    assert 'quality' not in str(agent.tools()).lower()


def test_mcp_business_task_is_executable_and_transport_remains_opt_in():
    assert not router_for().routes
    with pytest.raises(ValueError):router_for(CORPUS,enabled='false')
    app=FastAPI();app.include_router(router_for(CORPUS,enabled=True))
    with TestClient(app) as client:
        result=client.post('/api/document-search/mcp',json={'jsonrpc':'2.0','id':1,'method':'tools/call',
            'params':{'name':'search_approved_documents','arguments':{'query':'webhook deduplicate','language':'en','limit':1}}})
        assert result.json()['result']['structuredContent']['items'][0]['version']=='revision-2'


@pytest.mark.parametrize('url',['http://docs.example','https://127.0.0.1/private','file:///private'])
def test_unapproved_private_endpoints_are_rejected(url):
    with pytest.raises(ValueError):ApprovedDocument('Source',url,'v1','Public text')
