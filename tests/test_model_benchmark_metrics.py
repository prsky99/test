"""Benchmark calculations distinguish protocol, application and semantic success."""
import json

import pytest

from scripts.benchmark_macmini_model import percentile, summary, quality, output_value, envelope, parsed_metrics
from agent_market.workflow_model_proposer import compile_proposal


def test_percentiles_use_documented_linear_interpolation():
    assert percentile([], .95) is None
    assert percentile([4], .95)==4
    assert percentile([1,2,3,4],.5)==2.5
    assert percentile([1,2,3,4],.95)==3.85


def test_transport_success_does_not_imply_native_or_quality_success():
    rows=[{'seconds':1,'transport_ok':True,'native_ok':False,'quality_pass':False},
          {'seconds':2,'transport_ok':True,'native_ok':True,'quality_pass':False},
          {'seconds':3,'transport_ok':True,'native_ok':True,'quality_pass':True}]
    result=summary(rows)
    assert (result['transport_ok'],result['native_ok'],result['quality_pass'])==(3,2,1)


def test_workflow_with_allowed_but_irrelevant_contract_fails_semantic_rubric():
    ctx=envelope('Find Python documentation using exactly two steps')
    # Retained old output must remain assessable after production starts rejecting it.
    definition={'nodes':[{'id':'step_1','resource_id':17,'contract_id':'docs.search.v1','input':{'query':'Python documentation'},'bindings':{}},
        {'id':'step_2','resource_id':23,'contract_id':'news.search.v1','input':{},
         'bindings':{'query':{'node_id':'step_1','path':['items',0,'title']}}}]}
    checks=quality({'feature':'workflow','steps':2,'context':ctx,'keywords':['python'],
                    'expected_contracts':['docs.search.v1']*2},definition)
    assert checks['approved_pairs'] and checks['declared_connections']
    assert not checks['contract_selection']


def test_load_intent_judging_applies_real_adapter_empty_protocol_normalization():
    case={'feature':'intent','text':'Find documentation'}
    result=output_value(case,json.dumps({'intent':'find','kind':'','search_query_en':'documentation','agent_name':''}),'model')
    assert result['kind'] is None and result['agent_name'] is None


@pytest.mark.parametrize('data',[
 {'answer':'Review the workflow.','documents':['known']},
 {'answer':'Review the workflow.','documents':['known','known'],'changes':{}},
 {'answer':'Review the workflow.','documents':['invented'],'changes':{}},
 {'answer':'Review the workflow.','documents':['known'],'changes':{'command':'execute'}},
])
def test_load_guidance_judging_rejects_same_required_fields_as_actual_api(data):
    with pytest.raises(ValueError):
        output_value({'feature':'guidance','allowed_docs':{'known'}},json.dumps(data),'model')


def test_metrics_parser_preserves_units_labels_and_ignores_help():
    value=parsed_metrics('# HELP x\nvllm_mlx_scheduler_running_requests 16\nvllm_mlx_metal_memory_bytes{kind="active"} 8000000000\nignored 2')
    assert value=={'vllm_mlx_scheduler_running_requests':16.,'vllm_mlx_metal_memory_bytes{kind="active"}':8000000000.}
