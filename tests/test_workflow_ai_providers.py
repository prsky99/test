"""Bounded local planning and explicit account-authorized inference security."""
import base64
import copy
import json
import os
import time
from urllib.parse import parse_qs,urlsplit

import httpx
import pytest
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import rsa,padding

from agent_market.workflow_chatgpt import (AUTH,API,MODEL,SCOPES,LoginAttempt,
    ChatGPTGraphProposer,private_read,private_write,credentials,verify_identity)
from agent_market.workflow_model_proposer import compile_proposal,proposal_schema
from agent_market.workspace_app_factory import MODEL_PROFILE,MODEL_CONTRACTS,MODEL_OUTPUT_PROFILE
from agent_market.capability_contracts import CONTRACTS
from agent_market.workspace_access import WorkspaceInvalid,WorkspaceDenied


def envelope(objective='Find public documentation using exactly two steps'):
    return {'profile':MODEL_PROFILE,'objective':objective,
        'candidates':[{'resource_id':17,'contract_id':'docs.search.v1'}],
        'contracts':{key:{'input_schema':CONTRACTS[key]['input_schema'],'output_schema':CONTRACTS[key]['output_schema']} for key in MODEL_CONTRACTS},
        'limits':{'minimum_nodes':2,'maximum_nodes':10},'output_profile':MODEL_OUTPUT_PROFILE}


def graph():
    return compile_proposal(envelope(),{'query':'Public documentation','agents':envelope()['candidates']*2})


@pytest.mark.parametrize('count',[2,3,10])
def test_compiler_preserves_model_query_and_chains_only_approved_pairs(count):
    e=envelope(f'Find documentation in exactly {count} read-only steps')
    assert set(proposal_schema(e)['properties'])=={'query'}
    value=compile_proposal(e,{'query':'A model selected query'})
    assert len(value['nodes'])==count and value['nodes'][0]['input']['query']=='A model selected query'
    for index,node in enumerate(value['nodes'][1:],1):
        assert 'query' not in node['input'] and node['bindings']['query']=={'node_id':'step_'+str(index),'path':['items',0,'title']}
        assert node['after']==['step_'+str(index)] and node['input']['limit']==1


@pytest.mark.parametrize('mutation',['foreign','contract','extra','query','count','boolean'])
def test_compact_plan_cannot_invent_bindings_or_smuggle_private_input(mutation):
    e=envelope();plan={'query':'Public documentation','agents':copy.deepcopy(e['candidates']*2)}
    if mutation=='foreign':plan['agents'][0]['resource_id']=18
    if mutation=='contract':plan['agents'][0]['contract_id']='news.search.v1'
    if mutation=='extra':plan['agents'][0]['credential']='private'
    if mutation=='query':plan['query']='Bearer synthetic-private-token'
    if mutation=='count':plan['agents']*=6
    if mutation=='boolean':plan['agents'][0]['resource_id']=True
    with pytest.raises((WorkspaceInvalid,WorkspaceDenied)):compile_proposal(e,plan)


def b64(value):return base64.urlsafe_b64encode(value).decode().rstrip('=')


@pytest.fixture
def signing():
    key=rsa.generate_private_key(public_exponent=65537,key_size=2048)
    public=key.public_key().public_numbers()
    jwk={'kty':'RSA','alg':'RS256','kid':'synthetic','use':'sig',
         'n':b64(public.n.to_bytes(256,'big')),'e':b64(public.e.to_bytes(3,'big'))}
    def token(**changes):
        claims={'iss':AUTH,'aud':'oaiapp_synthetic','sub':'synthetic-subject','iat':time.time(),
            'exp':time.time()+3600,'nonce':'synthetic-nonce','email':'owner@example.test',**changes}
        raw=b64(json.dumps({'alg':'RS256','kid':'synthetic'}).encode())+'.'+b64(json.dumps(claims).encode())
        return raw+'.'+b64(key.sign(raw.encode(),padding.PKCS1v15(),hashes.SHA256()))
    return token,jwk


@pytest.mark.parametrize('change',[{'iss':'https://foreign.test'},{'aud':'other'},{'aud':[{}]},
    {'nonce':'other'},{'exp':1},{'sub':None}])
def test_openai_id_token_requires_signature_issuer_audience_nonce_and_expiry(signing,change):
    token,jwk=signing
    with httpx.Client(transport=httpx.MockTransport(lambda request:httpx.Response(200,json={'keys':[jwk]}))) as client:
        with pytest.raises(WorkspaceDenied):verify_identity(client,token(**change),'oaiapp_synthetic',nonce='synthetic-nonce')


def test_local_login_binds_state_pkce_issued_client_identity_scopes_and_one_use(signing):
    token,jwk=signing;seen=[]
    flow=LoginAttempt('http://127.0.0.1:14555/auth/callback','urn:uuid:00000000-0000-4000-8000-000000000000',expected_email='owner@example.test')
    args=parse_qs(urlsplit(flow.authorization_url()).query)
    assert args['client_id']==['dynamic_agent_client'] and args['code_challenge_method']==['S256']
    def handler(request):
        seen.append(request)
        if request.url.path.endswith('jwks.json'):return httpx.Response(200,json={'keys':[jwk]})
        form=parse_qs(request.content.decode());assert form['client_id']==['oaiapp_synthetic'] and 'client_secret' not in form
        assert form['redirect_uri']==[flow.redirect_uri] and form['resource']==[API]
        return httpx.Response(200,json={'token_type':'Bearer','scope':' '.join(SCOPES),'expires_in':3600,
            'access_token':'synthetic-access','refresh_token':'synthetic-refresh','id_token':token(nonce=flow.nonce)})
    query={'state':flow.state,'code':'synthetic-code','client_id':'oaiapp_synthetic'}
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(WorkspaceDenied):flow.complete(client,{**query,'state':'wrong'})
        assert not seen
        result=flow.complete(client,query);assert result['subject']=='synthetic-subject'
        with pytest.raises(WorkspaceDenied):flow.complete(client,query)
        assert len(seen)==2


def record():
    return {'profile':'workflow-chatgpt-local-v1','issuer':AUTH,'subject':'synthetic-subject','client_id':'oaiapp_synthetic',
        'ext_agent_host_id':'urn:uuid:00000000-0000-4000-8000-000000000000','scopes':list(SCOPES),
        'expires_at':time.time()+3600,'access_token':'synthetic-access','refresh_token':'synthetic-refresh','id_token':'synthetic-id'}


def test_credentials_are_owner_only_and_symlinks_are_rejected(tmp_path):
    path=tmp_path/'account.json';private_write(path,record());assert path.stat().st_mode&0o777==0o600
    path.chmod(0o644)
    with pytest.raises(WorkspaceDenied):private_read(path)
    link=tmp_path/'link.json';link.symlink_to(path)
    with pytest.raises((OSError,WorkspaceDenied)):private_read(link)


def inference(tmp_path,events,*,catalog=None):
    path=tmp_path/'account.json';private_write(path,record());seen=[]
    def handler(request):
        seen.append(request)
        assert request.headers['authorization']=='Bearer synthetic-access'
        if request.url.path.endswith('/models'):
            return httpx.Response(200,json={'models':catalog if catalog is not None else [{'slug':MODEL,'visibility':'list'}]})
        body=json.loads(request.content)
        assert body['model']==MODEL and body['reasoning']=={'effort':'medium'} and body['stream'] is True and body['store'] is False
        assert not set(body)&{'max_output_tokens','temperature','previous_response_id','tools'}
        assert 'synthetic-access' not in request.content.decode()
        return httpx.Response(200,headers={'Content-Type':'text/event-stream'},content=b''.join(b'data: '+json.dumps(item).encode()+b'\n\n' for item in events))
    return path,httpx.Client(transport=httpx.MockTransport(handler)),seen


def completed(model=MODEL):
    text=json.dumps(graph())
    return [{'type':'response.output_text.delta','delta':text},
        {'type':'response.completed','response':{'status':'completed','model':model,
            'output':[{'type':'message','content':[{'type':'output_text','text':text}]}]}}]


def test_exact_requested_chatgpt_model_medium_and_completed_stream_are_required(tmp_path):
    path,client,seen=inference(tmp_path,completed())
    with client:
        assert ChatGPTGraphProposer(str(path),client)(envelope())==graph()
    assert len(seen)==2


@pytest.mark.parametrize('mode',['wrong_model','interrupted','failed','incomplete','foreign_agent','missing_model'])
def test_inference_never_falls_back_or_accepts_partial_or_unapproved_output(tmp_path,mode):
    events=completed();catalog=None
    if mode=='wrong_model':events=completed('different-model')
    if mode=='interrupted':events=events[:1]
    if mode=='failed':events=[{'type':'response.failed'}]
    if mode=='incomplete':events=[{'type':'response.incomplete'}]
    if mode=='foreign_agent':
        value=graph();value['nodes'][0]['resource_id']=18
        events=[{'type':'response.completed','response':{'status':'completed','model':MODEL,
            'output':[{'type':'message','content':[{'type':'output_text','text':json.dumps(value)}]}]}}]
    if mode=='missing_model':catalog=[]
    path,client,seen=inference(tmp_path,events,catalog=catalog)
    with client:
        with pytest.raises((WorkspaceInvalid,WorkspaceDenied)):ChatGPTGraphProposer(str(path),client)(envelope())
    assert len(seen)==(1 if mode=='missing_model' else 2)


@pytest.mark.parametrize('change',[
    {'scopes':['openid']},{'scopes':[{}]},{'expires_at':'tomorrow'},
    {'expires_at':float('inf')},{'client_id':'other'},{'access_token':'bad\nheader'}])
def test_malformed_saved_credentials_never_reach_network(tmp_path,change):
    path=tmp_path/'account.json';value={**record(),**change}
    if change.get('expires_at')==float('inf'):
        # The strict reader rejects non-finite JSON before credential validation.
        path.write_text(json.dumps(value));path.chmod(0o600)
    else:private_write(path,value)
    calls=[]
    with httpx.Client(transport=httpx.MockTransport(lambda request:calls.append(request))) as client:
        with pytest.raises((WorkspaceDenied,ValueError)):credentials(client,path)
    assert not calls


def test_refresh_rotates_atomically_and_cannot_switch_verified_subject(tmp_path,signing):
    token,jwk=signing;path=tmp_path/'account.json'
    initial={**record(),'expires_at':time.time()-1};private_write(path,initial)
    wrong=[True];seen=[]
    def handler(request):
        seen.append(request)
        if request.url.path.endswith('jwks.json'):return httpx.Response(200,json={'keys':[jwk]})
        form=parse_qs(request.content.decode())
        assert form['grant_type']==['refresh_token'] and form['refresh_token']==['synthetic-refresh']
        return httpx.Response(200,json={'token_type':'Bearer','scope':' '.join(SCOPES),'expires_in':3600,
            'access_token':'rotated-access','refresh_token':'rotated-refresh',
            'id_token':token(sub='other-subject' if wrong[0] else 'synthetic-subject')})
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(WorkspaceDenied):credentials(client,path)
        assert private_read(path)==initial
        wrong[0]=False
        updated=credentials(client,path)
        assert updated['refresh_token']=='rotated-refresh' and updated['access_token']=='rotated-access'
        assert private_read(path)==updated and path.stat().st_mode&0o777==0o600
        before=len(seen);assert credentials(client,path)==updated and len(seen)==before


def test_local_ai_startup_is_opt_in_and_does_not_enable_public_workspace(monkeypatch):
    from agent_market.config import GatewayConfig
    for name in ('WORKSPACE_MODEL_ENABLED','WORKSPACE_MODEL_URL','WORKSPACE_MODEL_NAME',
                 'CUSTOMER_WORKSPACE_ACCESS_ENABLED','CUSTOMER_WORKSPACE_LINK_ENABLED'):
        monkeypatch.delenv(name,raising=False)
    config=GatewayConfig.from_env()
    assert not config.workspace_model_enabled and not config.customer_workspace_link
    monkeypatch.setenv('WORKSPACE_MODEL_ENABLED','1')
    monkeypatch.setenv('WORKSPACE_MODEL_NAME','gemma3:1b')
    config=GatewayConfig.from_env()
    assert config.workspace_model_enabled and config.workspace_model_name=='gemma3:1b'
    assert not config.customer_workspace_access and not config.customer_workspace_link
    monkeypatch.setenv('WORKSPACE_MODEL_ENABLED','true')
    with pytest.raises(ValueError):GatewayConfig.from_env()


def test_large_account_catalog_is_bounded_and_projects_only_model_identity_fields(tmp_path):
    path=tmp_path/'account.json';private_write(path,record());seen=[]
    def handler(request):
        seen.append(request)
        if request.url.path.endswith('/models'):
            return httpx.Response(200,json={'models':[{'slug':MODEL,'visibility':'list',
                'instructions':'Synthetic catalog metadata. '*24000}]})
        return httpx.Response(200,headers={'Content-Type':'text/event-stream'},content=b''.join(
            b'data: '+json.dumps(item).encode()+b'\n\n' for item in completed()))
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        assert ChatGPTGraphProposer(str(path),client)(envelope())==graph()
    assert len(seen)==2 and b'Synthetic catalog metadata' not in seen[1].content


@pytest.mark.parametrize('mode',['oversized','duplicate_model','duplicate_key','too_many','invalid_slug'])
def test_invalid_or_excessive_catalog_never_reaches_inference(tmp_path,mode):
    path=tmp_path/'account.json';private_write(path,record());seen=[]
    row={'slug':MODEL,'visibility':'list'}
    data=json.dumps({'models':[row]}).encode()
    if mode=='oversized':data=json.dumps({'models':[{**row,'instructions':'x'*2097152}]}).encode()
    if mode=='duplicate_model':data=json.dumps({'models':[row,row]}).encode()
    if mode=='duplicate_key':data=b'{"models":[],"models":[]}'
    if mode=='too_many':data=json.dumps({'models':[{'slug':'m'+str(i),'visibility':'list'} for i in range(101)]}).encode()
    if mode=='invalid_slug':data=json.dumps({'models':[{**row,'slug':'bad\nmodel'}]}).encode()
    def handler(request):
        seen.append(request);return httpx.Response(200,headers={'Content-Type':'application/json'},content=data)
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises((WorkspaceDenied,WorkspaceInvalid)):ChatGPTGraphProposer(str(path),client)(envelope())
    assert len(seen)==1


@pytest.mark.parametrize('mode',['absent_valid','absent_html','wrong_type','absent_interrupted'])
def test_missing_stream_media_type_still_requires_valid_sse_and_completed_graph(tmp_path,mode):
    path=tmp_path/'account.json';private_write(path,record())
    events=completed()
    if mode=='absent_interrupted':events=events[:1]
    body=b''.join(b'data: '+json.dumps(item).encode()+b'\n\n' for item in events)
    if mode=='absent_html':body=b'<html>unexpected provider page</html>\n'+body
    def handler(request):
        if request.url.path.endswith('/models'):
            return httpx.Response(200,json={'models':[{'slug':MODEL,'visibility':'list'}]})
        return httpx.Response(200,content=body,headers={'Content-Type':'text/html'} if mode=='wrong_type' else {})
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        adapter=ChatGPTGraphProposer(str(path),client)
        if mode=='absent_valid':assert adapter(envelope())==graph()
        else:
            with pytest.raises((WorkspaceDenied,WorkspaceInvalid)):adapter(envelope())


def test_stream_error_reports_only_a_bounded_code_without_echoing_provider_message(tmp_path):
    from agent_market.workflow_chatgpt import ChatGPTStreamRejected
    events=[{'type':'response.failed','response':{'error':{
        'code':'subscription_sharing_usage_unavailable','param':'reasoning.effort','message':'synthetic-secret-provider-message'}}}]
    path,client,seen=inference(tmp_path,events)
    with client:
        with pytest.raises(ChatGPTStreamRejected) as error:ChatGPTGraphProposer(str(path),client)(envelope())
    assert error.value.event_type=='response.failed'
    assert error.value.error_code=='subscription_sharing_usage_unavailable'
    assert error.value.error_param=='reasoning.effort'
    assert 'synthetic-secret' not in str(error.value) and 'message' not in vars(error.value)
    assert len(seen)==2


def test_local_callback_redirects_one_use_codes_to_clean_completion_page(tmp_path):
    import io
    from types import SimpleNamespace
    from agent_market.workflow_chatgpt_login import callback_handler
    class Socket:
        def __init__(self,path):
            self.input=io.BytesIO(('GET '+path+' HTTP/1.0\r\nHost: 127.0.0.1\r\n\r\n').encode());self.output=b''
        def makefile(self,*args):return self.input
        def sendall(self,value):self.output+=value
    class Pending:
        consumed=False
        def complete(self,client,query):
            assert query=={'state':'synthetic-state','code':'synthetic-one-use-code'}
            self.consumed=True;return record()
    pending=Pending();outcome={'complete':False,'shown':False}
    handler=callback_handler(tmp_path,lambda:pending,outcome);server=SimpleNamespace()
    callback=Socket('/auth/callback?state=synthetic-state&code=synthetic-one-use-code')
    handler(callback,('127.0.0.1',12345),server)
    assert callback.output.startswith(b'HTTP/1.0 303')
    assert b'Location: /auth/complete\r\n' in callback.output
    assert b'synthetic-one-use-code' not in callback.output and b'Cache-Control: no-store' in callback.output
    assert private_read(tmp_path/'credentials.json')['access_token']=='synthetic-access'
    assert (tmp_path/'credentials.json').stat().st_mode&0o777==0o600
    assert outcome=={'complete':True,'shown':False}
    completion=Socket('/auth/complete');handler(completion,('127.0.0.1',12345),server)
    assert b'200 OK' in completion.output and b'ChatGPT connection verified.' in completion.output
    assert b'no-referrer' in completion.output and b"default-src 'none'" in completion.output
    assert b'synthetic-' not in completion.output and b'Python/' not in completion.output
    assert outcome['shown']
