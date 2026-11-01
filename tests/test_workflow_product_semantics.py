"""Synthetic offline v2 fixtures, exact arithmetic and isolated evidence tests.

The factory below supplies machine-authored test data, not real product evidence.
"""
import asyncio
import copy
from datetime import datetime,timezone
from decimal import localcontext,Decimal
import hashlib
import json
import socket
import time

import pytest

from agent_market.capability_contracts import CONTRACTS,validate as validate_contract,run_test
from agent_market.capability_registry import Registry,canonical
from agent_market.collector import usage
from agent_market.workflow_product_semantics import (CONTRACT_ID,PROFILE,CONTRACT,INPUT_SCHEMA,OUTPUT_SCHEMA,
    ProductSemantics,validate,normalize,quantity,number,exact_tool)
from tests.test_fast_single_recommendation import catalog
from tests.test_managed_agent_gateway import managed
from tests.test_capability_registry import contract_fixture

V1_HASHES = {'news.search.v1': '9a1c8dc8e8dfdef4533101c3121b1251c0178b5c62b8952b6fab76ff3a0d3aaa', 'docs.search.v1': '476030ece54c7010427ad999d735f362c96b98e1e6cac82a0e0df3ffc14294c2', 'products.compare.v1': 'ab406b6d8b09b315469406be83417ff37274b5bf467d96ac199c5f9ccb76bfe8'}


def stamp(value):return datetime.fromtimestamp(value,timezone.utc).isoformat().replace('+00:00','Z')


def product_fixture(now=None):
    """Two fabricated products solely for disposable automated tests."""
    now=time.time() if now is None else now
    inputs={'query':'Synthetic portable products','language':'en','limit':2,'criteria':[
        {'criterion_id':'weight','dimension':'mass'},{'criterion_id':'capacity','dimension':'storage'},{'criterion_id':'length','dimension':'length'}]}
    items=[]
    for index in range(2):
        source='https://sources.example/product-'+str(index)
        values=[('1000','g'),('1','GB'),('1','in')] if index==0 else [('1','kg'),('1','GiB'),('2.54','cm')]
        measures=[{'criterion_id':criterion['criterion_id'],'dimension':criterion['dimension'],'status':'reported',
                   'quantity':{'value':value,'unit':unit},'source_url':source,'observed_at':stamp(now-60)}
                  for criterion,(value,unit) in zip(inputs['criteria'],values)]
        items.append({'identity':{'brand':'Synthetic brand','model':'Model '+str(index),'variant':'Test variant '+str(index),
                                  'identifier':{'scheme':'manufacturer_sku','value':'SYNTHETIC-'+str(index)}},
                      'name':'Synthetic product '+str(index),'url':source,'retrieved_at':stamp(now),
                      'measurements':measures,'price':{'status':'reported','amount':'10.00' if index==0 else '11.25','currency':'USD',
                      'basis':{'unit':'item','quantity':'1','pack_count':None},'source_url':source,'observed_at':stamp(now-60)}})
    return inputs,{'items':items,'partial':False},now


def product_tool():
    return {'name':'compare_products','description':'Compare reported public product evidence.',
            'inputSchema':copy.deepcopy(INPUT_SCHEMA),'outputSchema':copy.deepcopy(OUTPUT_SCHEMA),
            'annotations':{'readOnlyHint':True,'destructiveHint':False,'idempotentHint':True}}


def test_exact_quantities_keep_originals_and_do_not_rank_or_exchange():
    inputs,output,now=product_fixture();original=copy.deepcopy(output)
    validate_contract(CONTRACT_ID,inputs,output,now=now);normalized,pairs=normalize(inputs,output,now=now)
    assert output==original
    assert normalized[0]['measurements'][0]['original_quantity']=={'value':'1000','unit':'g'}
    assert pairs[0]['measurements'][0]['left_value']==pairs[0]['measurements'][0]['right_value']=='1'
    assert pairs[0]['measurements'][1]['left_value']=='1000000000'
    assert pairs[0]['measurements'][1]['right_value']=='1073741824'
    assert pairs[0]['measurements'][2]['left_value']==pairs[0]['measurements'][2]['right_value']=='0.0254'
    result=ProductSemantics().validate({'input':inputs,'output':output})
    assert result['origin']=='user_supplied' and result['partial'] is False
    assert all(value is False for value in result['claims'].values())
    assert result['normalized'][0]['price']==original['items'][0]['price']


@pytest.mark.parametrize('dimension,value,unit,expected',[
    ('mass','1','mg','0.000001'),('length','1','ft','0.3048'),('duration','1.5','min','90'),
    ('storage','2','MB','2000000'),('storage','2','MiB','2097152'),('power','1.25','kW','1250'),
    ('energy','0.1','kWh','100'),('volume','100','mL','0.1'),('mass','0','g','0'),
    ('storage','999999999999.999999','GiB','1073741823999999998926.258176')])
def test_whitelisted_conversions_are_exact_even_with_hostile_decimal_context(dimension,value,unit,expected):
    with localcontext() as context:
        context.prec=2;context.Emax=2;context.Emin=-2
        assert quantity({'value':value,'unit':unit},dimension)['value']==expected


@pytest.mark.parametrize('value',[True,False,0,1.5,Decimal('1'),'NaN','Infinity','-0','-0.0','-1','+1','1e3','1E-3','01','00.1','.5','1.','1,000',' 1','1 ','١','1000000000000','1.0000000',''])
def test_decimal_input_is_plain_bounded_exact_string_only(value):
    with pytest.raises(ValueError):number(value)


@pytest.mark.parametrize('unit,dimension',[('lb','mass'),('g','length'),('m','duration'),('GB','mass'),('gb','storage'),('C','power')])
def test_unsupported_or_cross_dimension_units_never_coerce(unit,dimension):
    with pytest.raises(ValueError):quantity({'value':'1','unit':unit},dimension)


@pytest.mark.parametrize('fault',['missing_quantity','missing_source','missing_time','reported_null_price','missing_measurement_source',
                                  'missing_price_source','missing_measurement_value','missing_price_amount','missing_partial',
                                  'duplicate_criterion','duplicate_measure','duplicate_product','omitted_criterion','dimension','criterion',
                                  'future_retrieval','stale_retrieval','future_evidence','stale_evidence','invalid_utc','currency','price_basis_zero',
                                  'pack_without_count','item_with_pack_count','unknown_field','boolean_limit'])
def test_contradictory_incomplete_or_unbounded_evidence_is_rejected(fault):
    inputs,output,now=product_fixture();item=output['items'][0];m=item['measurements'][0];p=item['price']
    if fault=='missing_quantity':m['quantity']=None
    elif fault=='missing_source':m['source_url']=None
    elif fault=='missing_time':m['observed_at']=None
    elif fault=='reported_null_price':p['currency']=None
    elif fault.startswith('missing_measurement_'):
        m.update(status='missing',quantity=None,source_url=None,observed_at=None);output['partial']=True
        m['source_url' if fault.endswith('source') else 'quantity']=item['url'] if fault.endswith('source') else {'value':'1','unit':'kg'}
    elif fault.startswith('missing_price_'):
        p.update(status='missing',amount=None,currency=None,basis=None,source_url=None,observed_at=None);output['partial']=True
        p['source_url' if fault.endswith('source') else 'amount']=item['url'] if fault.endswith('source') else '1'
    elif fault=='missing_partial':m.update(status='missing',quantity=None,source_url=None,observed_at=None)
    elif fault=='duplicate_criterion':inputs['criteria'].append(copy.deepcopy(inputs['criteria'][0]))
    elif fault=='duplicate_measure':item['measurements'].append(copy.deepcopy(m))
    elif fault=='duplicate_product':output['items'][1]['identity']=copy.deepcopy(item['identity'])
    elif fault=='omitted_criterion':item['measurements'].pop()
    elif fault=='dimension':m['dimension']='length'
    elif fault=='criterion':m['criterion_id']='unknown'
    elif fault=='future_retrieval':item['retrieved_at']=stamp(now+10)
    elif fault=='stale_retrieval':item['retrieved_at']=stamp(now-86401)
    elif fault=='future_evidence':m['observed_at']=stamp(now+1)
    elif fault=='stale_evidence':m['observed_at']=stamp(now-86401)
    elif fault=='invalid_utc':m['observed_at']='2026-10-18T12:00:00'
    elif fault=='currency':p['currency']='BTC'
    elif fault=='price_basis_zero':p['basis']['quantity']='0'
    elif fault=='pack_without_count':p['basis']['unit']='pack'
    elif fault=='item_with_pack_count':p['basis']['pack_count']=2
    elif fault=='unknown_field':item['winner']=True
    elif fault=='boolean_limit':inputs['limit']=True
    with pytest.raises(ValueError):validate(inputs,output,now=now)


@pytest.mark.parametrize('url',['http://sources.example/product','https://127.0.0.1/a','https://localhost/a','https://example.internal/a',
                               'https://user:password@sources.example/a','https://sources.example/a?token=secret','https://sources.example/a#fragment',
                               'file:///private/data','https://2130706433/a','https://sources.example\\evil/a'])
def test_all_source_url_positions_are_lexical_only_and_reject_unsafe_addresses(url,monkeypatch):
    inputs,output,now=product_fixture()
    monkeypatch.setattr(socket,'getaddrinfo',lambda *a,**k:pytest.fail('no DNS permitted'))
    for position in ('item','measurement','price'):
        altered=copy.deepcopy(output);item=altered['items'][0]
        if position=='item':item['url']=url
        elif position=='measurement':item['measurements'][0]['source_url']=url
        else:item['price']['source_url']=url
        with pytest.raises(ValueError):validate(inputs,altered,now=now)


@pytest.mark.parametrize('change,expected',[('currency','currency_mismatch'),('basis','basis_mismatch'),('pack_count','basis_mismatch'),('missing','missing_evidence')])
def test_incompatible_or_missing_prices_are_explicit_without_fx_or_hidden_division(change,expected):
    inputs,output,now=product_fixture();p=output['items'][1]['price']
    if change=='currency':p['currency']='EUR'
    elif change=='basis':p['basis']['quantity']='2'
    elif change=='pack_count':
        for index,item in enumerate(output['items']):item['price']['basis'].update(unit='pack',pack_count=index+1)
    else:p.update(status='missing',amount=None,currency=None,basis=None,source_url=None,observed_at=None);output['partial']=True
    normalized,pairs=normalize(inputs,output,now=now)
    assert pairs[0]['price']['status']==expected
    assert pairs[0]['price']['left_amount'] is None and pairs[0]['price']['right_amount'] is None
    assert normalized[1]['price']==p


def test_missing_measurements_remain_partial_and_never_become_zero():
    inputs,output,now=product_fixture();m=output['items'][0]['measurements'][0]
    m.update(status='missing',quantity=None,source_url=None,observed_at=None);output['partial']=True
    normalized,pairs=normalize(inputs,output,now=now)
    assert normalized[0]['measurements'][0]['normalized_quantity'] is None
    assert pairs[0]['measurements'][0]['status']=='missing_evidence'
    assert pairs[0]['measurements'][0]['left_value'] is None


def test_offline_inspection_has_no_database_network_or_evidence_side_effects(managed,monkeypatch):
    store,_,_,_,_,calls,_=managed;before=store._db.total_changes
    monkeypatch.setattr(socket,'socket',lambda *a,**k:pytest.fail('no socket permitted'))
    inputs,output,_=product_fixture();core=ProductSemantics(object())
    options=core.options();assert options['live_enabled'] is False and options['compiler_enabled'] is False and options['fallback_enabled'] is False
    core.schema();core.validate({'input':inputs,'output':output})
    assert store._db.total_changes==before and not calls


def test_v1_contracts_remain_byte_equal_to_existing_schema_baseline():
    # Fixed hashes generated from the three previous immutable schema dictionaries.
    expected=V1_HASHES
    for name,expected_hash in expected.items():assert hashlib.sha256(canonical(CONTRACTS[name]).encode()).hexdigest()==expected_hash
    for name in expected:
        inputs,output,now=contract_fixture(name);validate_contract(name,inputs,output,now=now)


def install_v2(managed,*,spec=None):
    store,front,_,_,rid,calls,remote=managed;spec=product_tool() if spec is None else spec
    remote.tools=[spec];compact=usage.compact_tools(remote.tools)
    store.record_usage(rid,compact,usage.tools_hash(compact),{},None,{'ok':True},full_tools=remote.tools)
    return store,front,rid,calls,remote,Registry(store)


@pytest.mark.parametrize('change',['input','output','readonly','destructive','idempotent'])
def test_v2_approval_requires_exact_full_schemas_and_explicit_safety_annotations(managed,change):
    spec=product_tool()
    if change=='input':spec['inputSchema']['properties']['query']['maxLength']=501
    elif change=='output':spec.pop('outputSchema')
    elif change=='readonly':spec['annotations']['readOnlyHint']=False
    elif change=='destructive':spec['annotations']['destructiveHint']=True
    else:spec['annotations'].pop('idempotentHint')
    store,_,rid,calls,_,registry=install_v2(managed,spec=spec)
    with pytest.raises(ValueError):registry.approve(store.resource(rid),CONTRACT_ID,spec['name'])
    assert not calls and not store.query('SELECT 1 FROM capability_approvals WHERE contract_id=?',(CONTRACT_ID,))


def test_explicit_live_v2_test_requires_current_real_execution_then_records_only_real_result(managed):
    store,front,rid,calls,remote,registry=install_v2(managed);resource=store.resource(rid);registry.approve(resource,CONTRACT_ID,'compare_products')
    inputs,output,_=product_fixture();remote.call_result={'structuredContent':output}
    with pytest.raises(ValueError):asyncio.run(run_test(registry,resource,CONTRACT_ID,inputs,front.managed_gateway.execute))
    assert not calls
    first=asyncio.run(front.managed_gateway.execute(rid,tool='compare_products',arguments=inputs))
    assert first['execution_succeeded']
    assert not registry.projection(resource)['capability_contracts'][0]['verified']
    tested=asyncio.run(run_test(registry,resource,CONTRACT_ID,inputs,front.managed_gateway.execute))
    assert tested['ok'] and registry.projection(store.resource(rid))['capability_contracts'][0]['verified']
    evidence=store.query("SELECT * FROM capability_evidence WHERE contract_id=?",(CONTRACT_ID,))
    assert len(evidence)==1 and evidence[0]['dataset_version']=='explicit-contract-test-v1' and inputs['query'] not in json.dumps(dict(evidence[0]))


@pytest.mark.parametrize('fault',['simulated','invalid','schema_change','approval_change'])
def test_fake_or_changed_live_v2_result_cannot_create_success_evidence(managed,fault):
    store,front,rid,_,_,registry=install_v2(managed);resource=store.resource(rid);version=registry.approve(resource,CONTRACT_ID,'compare_products')
    started=time.time();registry.record(version,scope='execution',outcome='succeeded',started=started,finished=time.time())
    inputs,output,_=product_fixture()
    async def runner(*a,**k):
        if fault=='invalid':output['items'][0]['price']['currency']='BTC'
        elif fault=='schema_change':
            changed=product_tool();changed['outputSchema']['properties']['partial']={'const':True}
            compact=usage.compact_tools([changed]);store.record_usage(rid,compact,usage.tools_hash(compact),{},None,None,full_tools=[changed])
        elif fault=='approval_change':
            with store.tx() as db:db.execute('UPDATE capability_approvals SET created=created+1 WHERE version_id=? AND contract_id=?',(version['id'],CONTRACT_ID))
        return {'execution_succeeded':True,'simulated':fault=='simulated','output':output}
    result=asyncio.run(run_test(registry,resource,CONTRACT_ID,inputs,runner))
    assert result['ok'] is False
    assert not store.query("SELECT 1 FROM capability_evidence WHERE contract_id=? AND outcome='succeeded'",(CONTRACT_ID,))


@pytest.mark.parametrize('body',[{}, {'input':{},'output':None},{'input':{},'output':{},'execute':True}, {'input':{'query':float('nan')},'output':{}}])
def test_inspector_refusals_are_fixed_and_do_not_claim_live_admission(body):
    with pytest.raises(ValueError):ProductSemantics().validate(body)


@pytest.mark.parametrize('position',['measurement','price'])
def test_distinct_observation_instants_are_explicit_and_not_directly_comparable(position):
    inputs,output,now=product_fixture();item=output['items'][1]
    evidence=item['measurements'][0] if position=='measurement' else item['price'];evidence['observed_at']=stamp(now-61)
    _,pairs=normalize(inputs,output,now=now)
    row=pairs[0]['measurements'][0] if position=='measurement' else pairs[0]['price']
    assert row['status']=='observation_time_mismatch' and row['observation']['temporal_relation']=='different_instants'
    assert row['observation']['left_observed_at']!=row['observation']['right_observed_at']
    assert row['observation']['left_retrieved_at']==row['observation']['right_retrieved_at']
    assert row['left_value' if position=='measurement' else 'left_amount'] is None


def test_equivalent_utc_spellings_are_the_same_observation_instant():
    inputs,output,now=product_fixture()
    for item in output['items'][1:]:
        for measure in item['measurements']:measure['observed_at']=measure['observed_at'].replace('Z','+00:00')
        item['price']['observed_at']=item['price']['observed_at'].replace('Z','+00:00')
    _,pairs=normalize(inputs,output,now=now)
    assert all(row['status']=='comparable' and row['observation']['temporal_relation']=='same_instant' for row in pairs[0]['measurements'])
    assert pairs[0]['price']['status']=='comparable'


@pytest.mark.parametrize('malformed',[None,[],['bad'],'bad',True,{'structuredContent':None},{'structuredContent':[]},{'structuredContent':'bad'}])
def test_malformed_live_v2_output_records_failed_evidence_instead_of_throwing_or_input_only_success(managed,malformed):
    store,_,rid,_,_,registry=install_v2(managed);resource=store.resource(rid);version=registry.approve(resource,CONTRACT_ID,'compare_products')
    started=time.time();registry.record(version,scope='execution',outcome='succeeded',started=started,finished=time.time())
    inputs,_,_=product_fixture()
    async def runner(*a,**k):return {'execution_succeeded':True,'simulated':False,'output':malformed}
    result=asyncio.run(run_test(registry,resource,CONTRACT_ID,inputs,runner))
    assert result['ok'] is False
    rows=store.query('SELECT outcome FROM capability_evidence WHERE contract_id=?',(CONTRACT_ID,))
    assert len(rows)==1 and rows[0]['outcome']=='failed'


@pytest.mark.parametrize('malformed',[None,[],'bad',True])
def test_nonobject_live_runner_result_is_failed_v2_evidence(managed,malformed):
    store,_,rid,_,_,registry=install_v2(managed);resource=store.resource(rid);version=registry.approve(resource,CONTRACT_ID,'compare_products')
    started=time.time();registry.record(version,scope='execution',outcome='succeeded',started=started,finished=time.time())
    inputs,_,_=product_fixture()
    async def runner(*a,**k):return malformed
    assert asyncio.run(run_test(registry,resource,CONTRACT_ID,inputs,runner))['ok'] is False


def test_missing_current_execution_evidence_cannot_be_replaced_by_simulation_or_expired_check(managed):
    store,_,rid,calls,_,registry=install_v2(managed);resource=store.resource(rid);version=registry.approve(resource,CONTRACT_ID,'compare_products')
    started=time.time()-90000;registry.record(version,scope='execution',outcome='succeeded',started=started,finished=started+1)
    inputs,_,_=product_fixture()
    async def forbidden(*a,**k):pytest.fail('No live contract invocation without current execution evidence')
    with pytest.raises(ValueError):asyncio.run(run_test(registry,resource,CONTRACT_ID,inputs,forbidden))
    assert not calls


def test_current_projection_does_not_accept_manually_inserted_loose_v2_schema_approval(managed):
    spec=product_tool();spec['outputSchema']={'type':'object'}
    store,_,rid,_,_,registry=install_v2(managed,spec=spec);resource=store.resource(rid);version=registry.current(resource);at=time.time()
    with store.tx() as db:db.execute('INSERT INTO capability_approvals VALUES (?,?,?,?)',(version['id'],CONTRACT_ID,'compare_products',at-1))
    registry.record(version,scope='execution',outcome='succeeded',started=at,finished=time.time())
    registry.record(version,scope='contract',contract_id=CONTRACT_ID,outcome='succeeded',started=at,finished=time.time())
    assert registry.projection(resource)['capability_contracts'][0]['verified'] is False


def test_selected_compact_metadata_must_match_full_v2_schema(managed):
    store,_,rid,calls,_,registry=install_v2(managed)
    resource=store.resource(rid);compact=json.loads(resource['usage_tools']);compact[0]['required'].remove('criteria')
    with store.tx() as db:db.execute('UPDATE resources SET usage_tools=?,usage_tools_hash=? WHERE id=?',(json.dumps(compact),usage.tools_hash(compact),rid))
    resource=store.resource(rid)
    with pytest.raises(ValueError):registry.approve(resource,CONTRACT_ID,'compare_products')
    version=registry.current(resource);at=time.time()
    with store.tx() as db:db.execute('INSERT INTO capability_approvals VALUES (?,?,?,?)',(version['id'],CONTRACT_ID,'compare_products',at-1))
    registry.record(version,scope='execution',outcome='succeeded',started=at,finished=time.time())
    registry.record(version,scope='contract',contract_id=CONTRACT_ID,outcome='succeeded',started=at,finished=time.time())
    assert registry.projection(resource)['capability_contracts'][0]['verified'] is False
    inputs,_,_=product_fixture()
    async def forbidden(*a,**k):pytest.fail('No call through contradictory selected metadata')
    with pytest.raises(ValueError):asyncio.run(run_test(registry,resource,CONTRACT_ID,inputs,forbidden))
    assert not calls


@pytest.mark.parametrize('url',['https://agentconcierge.biz/api/gateway/mcp/1',
                               'https://AGENTCONCIERGE.BIZ.:443/api/gateway/mcp/1',
                               'https://agentconcierge.biz/api/%67ateway/mcp/1'])
def test_platform_invocation_gateway_cannot_substitute_for_original_source(url):
    inputs,output,now=product_fixture();output['items'][0]['measurements'][0]['source_url']=url
    with pytest.raises(ValueError):validate(inputs,output,now=now)


def test_actual_gateway_sanitized_source_result_cannot_be_certified_as_original_evidence(managed):
    store,front,rid,_,remote,registry=install_v2(managed);resource=store.resource(rid);version=registry.approve(resource,CONTRACT_ID,'compare_products')
    started=time.time();registry.record(version,scope='execution',outcome='succeeded',started=started,finished=time.time())
    inputs,output,_=product_fixture();output['items'][0]['measurements'][0]['source_url']=resource['url']
    remote.call_result={'structuredContent':output}
    result=asyncio.run(run_test(registry,resource,CONTRACT_ID,inputs,front.managed_gateway.execute))
    assert result['ok'] is False
    assert store.query('SELECT outcome FROM capability_evidence WHERE contract_id=?',(CONTRACT_ID,))[0][0]=='failed'


def test_noninvocation_platform_source_path_is_not_relabelled_or_fetched():
    inputs,output,now=product_fixture();source='https://agentconcierge.biz/api/gateway-documentation/product'
    output['items'][0]['url']=source;validate(inputs,output,now=now)
    normalized,_=normalize(inputs,output,now=now)
    assert normalized[0]['url']==source


@pytest.mark.parametrize('url',['https://224.0.0.1/product','https://[ff02::1]/product'])
@pytest.mark.parametrize('position',['item','measurement','price'])
def test_multicast_is_not_a_public_evidence_source_and_is_never_resolved(url,position,monkeypatch):
    inputs,output,now=product_fixture();item=output['items'][0]
    if position=='item':item['url']=url
    elif position=='measurement':item['measurements'][0]['source_url']=url
    else:item['price']['source_url']=url
    monkeypatch.setattr(socket,'getaddrinfo',lambda *a,**k:pytest.fail('no DNS permitted'))
    with pytest.raises(ValueError):validate(inputs,output,now=now)


def test_exact_conversion_does_not_inherit_mutated_decimal_default_context(monkeypatch):
    from decimal import DefaultContext,ROUND_DOWN,Underflow
    monkeypatch.setattr(DefaultContext,'Emax',2);monkeypatch.setattr(DefaultContext,'Emin',-2)
    monkeypatch.setattr(DefaultContext,'rounding',ROUND_DOWN);monkeypatch.setattr(DefaultContext,'clamp',1)
    monkeypatch.setitem(DefaultContext.traps,Underflow,True)
    assert quantity({'value':'999999999999.999999','unit':'GiB'},'storage')['value']=='1073741823999999998926.258176'
    assert quantity({'value':'0.000001','unit':'mg'},'mass')['value']=='0.000000000001'


@pytest.mark.parametrize('result',[False,None,1,'approved'])
def test_optional_approval_guard_requires_exact_true_and_rolls_back(result,managed):
    store,_,rid,calls,_,registry=install_v2(managed)
    with pytest.raises(PermissionError):registry.approve(store.resource(rid),CONTRACT_ID,'compare_products',guard=lambda:result)
    assert not store.query('SELECT 1 FROM capability_approvals WHERE contract_id=?',(CONTRACT_ID,))
    assert not store._db.in_transaction and not calls


def test_guarded_approval_holds_actual_writer_lock_across_guard_and_insert(managed,tmp_path):
    import sqlite3
    source,_,rid,calls,_,_=install_v2(managed);checks=[]
    from agent_market.gateway.store import Store
    path=str(tmp_path/'guarded-approval.sqlite3')
    with sqlite3.connect(path) as target:source._db.backup(target)
    store=Store(path);registry=Registry(store)
    def guard():
        assert store._db.in_transaction
        other=sqlite3.connect(store._path,timeout=.01)
        try:
            with pytest.raises(sqlite3.OperationalError,match='locked'):
                other.execute("INSERT INTO capability_approvals VALUES ('different','products.compare.v2','compare_products',0)")
        finally:other.close()
        checks.append('writer-held');return True
    version=registry.approve(store.resource(rid),CONTRACT_ID,'compare_products',guard=guard)
    assert checks==['writer-held'] and not store._db.in_transaction
    rows=store.query('SELECT version_id FROM capability_approvals WHERE contract_id=?',(CONTRACT_ID,))
    assert len(rows)==1 and rows[0]['version_id']==version['id'] and not calls
    store._db.close()


@pytest.mark.parametrize('fraction',['','1','12','123','1234','12345','123456'])
def test_v2_utc_precision_is_explicit_and_equivalent_offsets_match(fraction):
    from agent_market.workflow_product_semantics import utc_time
    base='2026-10-18T00:00:00'+('.'+fraction if fraction else '')
    assert utc_time(base+'Z')==utc_time(base+'+00:00')


@pytest.mark.parametrize('fraction',['1234560','123456001','123456999'])
@pytest.mark.parametrize('position',['retrieved','measurement','price'])
def test_submicrosecond_v2_evidence_is_rejected_in_every_time_position(fraction,position):
    now=datetime(2026,10,18,0,1,tzinfo=timezone.utc).timestamp()
    inputs,output,_=product_fixture(now);item=output['items'][0]
    bad='2026-10-18T00:00:00.'+fraction+'Z'
    if position=='retrieved':item['retrieved_at']=bad
    elif position=='measurement':item['measurements'][0]['observed_at']=bad
    else:item['price']['observed_at']=bad
    with pytest.raises(ValueError):validate(inputs,output,now=now)


@pytest.mark.parametrize('position',['measurement','price'])
def test_distinct_submicrosecond_declarations_never_produce_a_coeval_pair(position):
    from agent_market.capability_contracts import utc
    inputs,output,now=product_fixture()
    one='2026-10-18T00:00:00.123456001Z';two='2026-10-18T00:00:00.123456999Z'
    # This reproduces the inherited parser's precision loss without changing v1.
    assert utc(one)==utc(two)
    for item,value in zip(output['items'],(one,two)):
        item['retrieved_at']='2026-10-18T00:01:00Z'
        for measurement in item['measurements']:measurement['observed_at']='2026-10-18T00:00:00Z'
        item['price']['observed_at']='2026-10-18T00:00:00Z'
        (item['measurements'][0] if position=='measurement' else item['price'])['observed_at']=value
    with pytest.raises(ValueError):normalize(inputs,output,now=datetime(2026,10,18,0,1,tzinfo=timezone.utc).timestamp())


def test_distinct_supported_microsecond_instants_are_not_coeval():
    inputs,output,_=product_fixture()
    for index,item in enumerate(output['items']):
        item['retrieved_at']='2026-10-18T00:01:00Z'
        for measurement in item['measurements']:measurement['observed_at']='2026-10-18T00:00:00.12345'+str(index+6)+'Z'
        item['price']['observed_at']='2026-10-18T00:00:00.12345'+str(index+6)+'Z'
    _,pairs=normalize(inputs,output,now=datetime(2026,10,18,0,1,tzinfo=timezone.utc).timestamp())
    assert all(row['status']=='observation_time_mismatch' for row in pairs[0]['measurements'])
    assert pairs[0]['price']['status']=='observation_time_mismatch'
