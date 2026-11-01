"""Versioned informational contracts; validation never fetches external data."""
from datetime import datetime,timezone
from urllib.parse import urlsplit,urlunsplit

TEXT={'type':'string','minLength':1,'maxLength':2000}
URL={'type':'string','minLength':8,'maxLength':2000}


def object_schema(properties,required=None):
    return {'type':'object','properties':properties,'required':list(properties) if required is None else required,'additionalProperties':False}


INPUT=object_schema({'query':{'type':'string','minLength':1,'maxLength':500},
    'language':{'const':'en'},'limit':{'type':'integer','minimum':1,'maximum':10}},['query','language','limit'])
NEWS_ITEM=object_schema({'title':TEXT,'url':URL,'source':TEXT,'published_at':{'type':['string','null']},'retrieved_at':TEXT,'summary':TEXT})
DOC_ITEM=object_schema({'title':TEXT,'url':URL,'excerpt':TEXT,'version':TEXT,'retrieved_at':TEXT})
PRODUCT_ITEM=object_schema({'name':TEXT,'url':URL,'attributes':{'type':'object','minProperties':1,'maxProperties':20,'additionalProperties':TEXT},'retrieved_at':TEXT})
CONTRACTS={
    'news.search.v1':{'version':1,'side_effect_class':'read_only','input_schema':object_schema({**INPUT['properties'],'from_utc':TEXT}),
        'output_schema':object_schema({'items':{'type':'array','maxItems':10,'items':NEWS_ITEM},'partial':{'type':'boolean'}})},
    'docs.search.v1':{'version':1,'side_effect_class':'read_only','input_schema':INPUT,
        'output_schema':object_schema({'items':{'type':'array','maxItems':10,'items':DOC_ITEM},'partial':{'type':'boolean'}})},
    'products.compare.v1':{'version':1,'side_effect_class':'read_only','input_schema':object_schema({**INPUT['properties'],'criteria':{'type':'array','minItems':1,'maxItems':10,'uniqueItems':True,'items':TEXT}}),
        'output_schema':object_schema({'items':{'type':'array','maxItems':10,'items':PRODUCT_ITEM},'partial':{'type':'boolean'}})},
}

from .workflow_product_semantics import CONTRACT_ID as PRODUCT_V2, CONTRACT as PRODUCT_V2_CONTRACT
CONTRACTS[PRODUCT_V2] = PRODUCT_V2_CONTRACT


def utc(value):
    try:
        parsed=datetime.fromisoformat(value.replace('Z','+00:00'))
        if parsed.tzinfo is None or parsed.utcoffset().total_seconds()!=0:raise ValueError()
        return parsed.timestamp()
    except (ValueError,TypeError,AttributeError,OverflowError):raise ValueError('A UTC timestamp is required.') from None


def validate(contract_id,inputs,output=None,*,now=None):
    from .concierge.execution_policy import validate_arguments
    from .concierge.recommendation_security import usable_endpoint
    if contract_id not in CONTRACTS:raise ValueError('Unknown capability contract.')
    if contract_id==PRODUCT_V2:
        from .workflow_product_semantics import validate as product_validate
        return product_validate(inputs,output,now=now)
    contract=CONTRACTS[contract_id];now=now if now is not None else datetime.now(timezone.utc).timestamp()
    validate_arguments({'inputSchema':contract['input_schema']},inputs)
    from_utc=utc(inputs['from_utc']) if contract_id=='news.search.v1' else None
    if from_utc is not None and from_utc>now:raise ValueError('The requested period starts in the future.')
    if output is None:return
    validate_arguments({'inputSchema':contract['output_schema']},output)
    if len(output['items'])>inputs['limit']:raise ValueError('The result exceeds the requested limit.')
    seen=set();previous=float('inf');undated=False
    for item in output['items']:
        url=item['url'];parts=urlsplit(url)
        if parts.scheme!='https' or parts.username or parts.password or not usable_endpoint(url):raise ValueError('A public HTTPS source is required.')
        normalized=urlunsplit((parts.scheme,parts.netloc.lower(),parts.path,parts.query,''))
        if normalized in seen:raise ValueError('Duplicate source results are not allowed.')
        seen.add(normalized)
        retrieved=utc(item['retrieved_at'])
        if retrieved>now+5 or retrieved<now-86400:raise ValueError('Result retrieval is not recent.')
        if contract_id=='news.search.v1':
            published=item['published_at']
            if published is None:
                if not output['partial']:raise ValueError('Undated news requires a partial result.')
                undated=True
            else:
                at=utc(published)
                if undated or at>previous or at<from_utc or at>retrieved:raise ValueError('News must match the requested period and newest-first order.')
                previous=at
        if contract_id=='products.compare.v1' and not set(inputs['criteria']).issubset(item['attributes']):raise ValueError('Requested comparison criteria are missing.')


async def run_test(registry,resource,contract_id,inputs,runner):
    """Only a real approved execution creates contract evidence; fixtures do not."""
    import time
    from .capability_registry import digest
    version=registry.current(resource)
    if not version:raise ValueError('This connection has no supported contract profile.')
    rows=registry.store.query('SELECT tool,created FROM capability_approvals WHERE version_id=? AND contract_id=?',(version['id'],contract_id))
    if not rows:raise ValueError('Approve a tool for the current contract/version first.')
    if contract_id==PRODUCT_V2:
        from .workflow_product_semantics import registered_tool
        if not registered_tool(resource,rows[0]['tool']):raise ValueError('Exact v2 schemas and read-only annotations are required.')
        if registry.projection(resource,version=version).get('connection_readiness',{}).get('verified_callable') is not True:
            raise ValueError('A current real execution check is required before the explicit v2 contract test.')
    validate(contract_id,inputs)
    from .capability_adapter_dispatch import arguments as adapter_arguments, profile as adapter_profile, normalize, evidence_dataset
    adapter=adapter_profile(resource,contract_id,rows[0]['tool'])
    provider_input=adapter_arguments(resource,contract_id,rows[0]['tool'],inputs,expected=adapter)
    started=time.time();result=await runner(resource['id'],tool=rows[0]['tool'],arguments=provider_input,expected_version=version['id'])
    if contract_id==PRODUCT_V2 and not isinstance(result,dict):result={}
    finished=time.time();outcome='failed';code='UPSTREAM_PROTOCOL';artifact=None
    if result.get('execution_succeeded') is True and result.get('simulated') is False:
        if contract_id==PRODUCT_V2:
            raw=result.get('output');output=raw.get('structuredContent',raw) if isinstance(raw,dict) else raw
        else:
            output=result.get('output') or {};output=output.get('structuredContent',output)
        try:
            if contract_id==PRODUCT_V2 and not isinstance(output,dict):raise ValueError('A typed product result object is required.')
            output=normalize(resource,contract_id,rows[0]['tool'],inputs,output,expected=adapter)
            validate(contract_id,inputs,output,now=finished)
            current=registry.current(registry.store.resource(resource['id']))
            if not current or current['id']!=version['id']:raise ValueError('Connection changed during the test.')
            approval=registry.store.query('SELECT tool,created FROM capability_approvals WHERE version_id=? AND contract_id=?',(version['id'],contract_id))
            if not approval or tuple(approval[0])!=tuple(rows[0]):raise ValueError('Contract approval changed during the test.')
        except ValueError:code='UPSTREAM_PROTOCOL'
        else:outcome='succeeded';code=None;artifact=digest(output)
    registry.record(version,scope='contract',outcome=outcome,started=started,finished=finished,
        operation_ref=result.get('correlation_id'),contract_id=contract_id,code=code,artifact_hash=artifact,dataset=evidence_dataset(adapter) if adapter else 'explicit-contract-test-v1')
    return {'ok':outcome=='succeeded','contract_id':contract_id,'status':outcome,'reason':code,'recorded_at':finished}
