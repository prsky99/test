"""Generic JSON mapping across shapes, strict data types and failure boundaries."""
# ruff: noqa: F401,F811
import copy
import math

import pytest

from agent_market.workflow_transforms import PROFILE, TransformError, apply, review
from agent_market.concierge.execution_policy import ExecutionDenied
from tests.test_workflow_runtime import runtime, save, wait  # noqa: F401


def get(path):return {'op':'get','path':path}
def literal(value):return {'op':'const','value':value}
def obj(**fields):return {'op':'object','fields':fields}
def recipe(expression,source=None,target=None):
    return {'version':PROFILE,'input_schema':source or {'type':'object'},'output_schema':target or {'type':'object'},'expression':expression}


@pytest.mark.parametrize('op,value,expected',[
    ('integer','42',42),('number','42.5',42.5),('string',False,'false'),
    ('boolean','false',False),('boolean',True,True),('trim',' hello ','hello'),
    ('upper','Abc','ABC'),('lower','AbC','abc'),('utc','2026-10-24T09:00:00+09:00','2026-10-24T00:00:00Z'),
])
def test_strict_primitive_operations(op,value,expected):
    assert apply(recipe(obj(value={'op':op,'value':get('/source')})),{'source':value})=={'value':expected}


def test_nested_array_mapping_pointer_escapes_conditions_and_coalesce():
    expression=obj(records={'op':'map','value':get('/a~1b/~0items'),'item':obj(
        title={'op':'trim','value':get('/label')},
        enabled={'op':'choose','value':get('/state'),'equals':'ready','then':literal(True),'otherwise':literal(False)},
        count={'op':'integer','value':{'op':'coalesce','values':[get('/missing'),get('/n'),literal('0')]}})})
    value={'a/b':{'~items':[{'label':' One ','state':'ready','n':'2'},{'label':' Two ','state':'down','n':None}]}}
    before=copy.deepcopy(value)
    assert apply(recipe(expression),value)=={'records':[{'title':'One','enabled':True,'count':2},{'title':'Two','enabled':False,'count':0}]}
    assert value==before


def test_array_records_can_preserve_root_metadata_without_inventing_timestamps():
    expression=obj(items={'op':'map','value':get('/records'),'item':obj(
        title=get('/name'),retrieved_at={'op':'get_root','path':'/observed'})})
    value={'observed':'2026-10-24T00:00:00Z','records':[{'name':'One'},{'name':'Two'}]}
    output=apply(recipe(expression),value)
    assert all(v['retrieved_at']==value['observed'] for v in output['items'])
    assert [v['title'] for v in output['items']]==['One','Two']


def test_english_guard_rejects_untranslated_source_without_making_up_text():
    expression=obj(title={'op':'english','value':get('/title')})
    assert apply(recipe(expression),{'title':'Public research'})=={'title':'Public research'}
    with pytest.raises(TransformError):apply(recipe(expression),{'title':'\ud55c\uae00 \uc81c\ubaa9'})


def test_take_concat_and_explicit_missing_field_defaults():
    expression=obj(text={'op':'concat','values':[get('/name'),literal('report')],'separator':' '},
                   items={'op':'take','value':get('/items'),'limit':2},
                   flag={'op':'coalesce','values':[get('/missing'),get('/flag'),literal(True)]})
    assert apply(recipe(expression),{'name':'Current','items':[1,2,3],'flag':False})=={'text':'Current report','items':[1,2],'flag':False}


def test_parse_json_preserves_source_objects_without_format_repair():
    assert apply(recipe({'op':'parse_json','value':get('/text')}),{'text':'{"items":[{"count":2}]}'} )=={'items':[{'count':2}]}


@pytest.mark.parametrize('text',['{"x":1,"x":2}','{"x":NaN}','```json\n{"x":1}\n```','{"__proto__":{}}'])
def test_parse_json_rejects_duplicates_nonfinite_fences_and_reserved_fields(text):
    with pytest.raises(TransformError):apply(recipe({'op':'parse_json','value':get('/text')}),{'text':text})


@pytest.mark.parametrize('op,value',[
    ('integer','1.2'),('integer',True),('number','NaN'),('number',2**54),
    ('integer',2**53+1),('integer','9007199254740993'),('integer','1.00000000000000001'),
    ('boolean','yes'),('string',{'x':1}),('utc','2026-10-24T00:00:00'),
])
def test_lossy_or_ambiguous_conversions_fail(op,value):
    with pytest.raises(TransformError):apply(recipe(obj(value={'op':op,'value':get('/x')})),{'x':value})


@pytest.mark.parametrize('expression',[
    {'op':'eval','value':'__import__("os")'}, {'op':'http','url':'https://example.com'},
    {'op':'get','path':'/constructor'}, {'op':'get','path':'/bad~2path'},
    {'op':'get','path':'../secret'}, {'op':'now'}, {'op':'get','path':'','ignored':True},
    {'op':'map','value':get('/items'),'item':{'op':'get','path':'/prototype'}},
])
def test_untrusted_code_network_and_invalid_paths_are_rejected(expression):
    with pytest.raises(TransformError):review(recipe(obj(value=expression)))


def test_required_source_and_target_contracts_are_enforced():
    target={'type':'object','properties':{'count':{'type':'integer'}},'required':['count'],'additionalProperties':False}
    with pytest.raises(TransformError):apply(recipe(obj(count=get('/missing')),target=target),{})
    with pytest.raises(ExecutionDenied):apply(recipe(obj(count=literal('3')),target=target),{})
    with pytest.raises(ExecutionDenied):review(recipe(obj(value=get('/x')),source={'type':'object','patternProperties':{'.*':{}}}))


@pytest.mark.parametrize('value',[{'x':math.nan},{'x':[0]*101},{'x':'a'*33000}])
def test_size_complexity_and_nonfinite_limits(value):
    with pytest.raises(TransformError):apply(recipe(get('')),value)


def test_input_and_output_nodes_transform_data_in_actual_workflow(runtime):
    rt,_,_=runtime
    first={'id':'input','type':'input_transform','kind':'transform','name':'Input mapping','data':{
        'input':{'requested':'42'},'transform':recipe(obj(count={'op':'integer','value':get('/requested')}))}}
    second={'id':'output','type':'output_transform','kind':'transform','name':'Output mapping','data':{
        'input':{'upstream':"{{$node['input'].output}}"},'transform':recipe(obj(total=get('/upstream/count')))}}
    wf=save(rt.store,[first,second],[{'source':'input','target':'output'}])
    result=wait(rt,rt.submit(wf))
    assert result['status']=='succeeded'
    assert result['node_results'][0]['data']=={'count':42}
    assert result['node_results'][1]['data']=={'total':42}
    assert all(n['attempts']==0 for n in result['node_results'])
    assert not rt.store.query('SELECT * FROM workflow_execution_attempts WHERE run_id=?',(result['run_id'],))


def test_transform_failure_blocks_following_nodes_and_stays_private(runtime):
    from agent_market.workflows import public_template
    rt,_,_=runtime
    a={'id':'input','type':'input_transform','data':{'input':{},'transform':recipe(obj(missing=get('/required')))}}
    b={'id':'output','type':'output_transform','data':{'input':{},'transform':recipe(get(''))}}
    wf=save(rt.store,[a,b],[{'source':'input','target':'output'}],is_template=1)
    assert public_template(wf) is None
    result=wait(rt,rt.submit(wf))
    assert result['status']=='failed' and result['node_results'][1]['status']=='blocked'
