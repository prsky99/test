"""Synthetic public context shared by packaged quality calibration tools."""
from agent_market.capability_contracts import CONTRACTS
from agent_market.workspace_app_factory import MODEL_PROFILE, MODEL_OUTPUT_PROFILE, MODEL_CONTRACTS


def context(objective):
    return {'profile':MODEL_PROFILE,'objective':objective,
        'candidates':[{'resource_id':17,'contract_id':'docs.search.v1'}, {'resource_id':23,'contract_id':'news.search.v1'}],
        'contracts':{key:{'input_schema':CONTRACTS[key]['input_schema'],'output_schema':CONTRACTS[key]['output_schema']}for key in MODEL_CONTRACTS},
        'limits':{'minimum_nodes':2,'maximum_nodes':10},'output_profile':MODEL_OUTPUT_PROFILE}
