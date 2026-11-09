"""Build a design catalog; never runs product code or migrations."""
from pathlib import Path
import hashlib
import json
import re

ROOT=Path(__file__).resolve().parents[2]
DETAIL=ROOT/'docs/ad_coin_v6_2_detail'


def build():
    api_path=ROOT/'docs/ad_coin_platform_p1_v6_2.openapi.json'
    api=json.loads(api_path.read_text())
    spec=json.loads((ROOT/'docs/ad_coin_platform_v6_2_spec.json').read_text())
    handler_text=(DETAIL/'03-api-handlers.md').read_text()
    handler_headers=re.findall(r'^### (API-\d{2}) (\w+)$',handler_text,re.M)
    header_map={op:ident for ident,op in handler_headers}
    rules={'createHumanChallenge':'C01','setAdPreferences':'API-05','createCampaign':'TX-01',
        'requestReview':'TX-02','decideReview':'TX-02','approveCampaign':'TX-02','activateCampaign':'TX-03',
        'pauseCampaign':'API-13','requestOffer':'TX-04','declineOffer':'TX-05','approveOffer':'TX-06',
        'startExposure':'TX-07','submitEvidence':'TX-08','completeExposure':'TX-08','cancelExposure':'TX-08',
        'recordReportConsumption':'API-29'}
    handlers=[]
    for path,methods in api['paths'].items():
        for method,op in methods.items():
            ident=op['operationId']
            handlers.append({'detail_id':header_map[ident],'operation_id':ident,'method':method.upper(),'path':path,
                'request_schema':op.get('requestBody',{}).get('content',{}).get('application/json',{}).get('schema',{}).get('$ref'),
                'principal_kinds':op['x-principal-kinds'],'capabilities':op['x-capabilities'],
                'human_only':op['x-human-only'],'fresh_action_required':op['x-fresh-action-required'],
                'transaction_rule':rules.get(ident,'read_only'),'detail_document':'03-api-handlers.md'})
    storage=(DETAIL/'02-storage-transactions.md').read_text()
    entities=[{'name':'adc2_'+name,'key':name,'scope':'R0','required_definition':definition}
        for name,definition in re.findall(r'^- \*\*([a-z_]+):\*\* (.+)$',storage,re.M)]
    tests={}
    for ident,line in re.findall(r'^- \*\*(DTL-\d{2}):\*\* (.+)$',(DETAIL/'05-ui-operations-tests.md').read_text(),re.M):
        wp=[]
        for n,tail in re.findall(r'WP-(\d{2})((?:·\d{2})*)',line):wp.extend('WP-'+i for i in [n,*re.findall(r'·(\d{2})',tail)])
        tests[ident]={'work_packages':wp,'status':'planned_not_executed','scenario':line}
    documents=['AD_COIN_V6_2_DETAILED_DESIGN.md']+['ad_coin_v6_2_detail/'+n for n in
        ['01-domain-security.md','02-storage-transactions.md','03-api-handlers.md','04-workers-integrations.md','05-ui-operations-tests.md']]
    result={'profile':'ai-ad-coin-v6.2-detailed-design','date_kst':'2026-11-08','status':'design_only',
        'real_value_enabled':False,'policy_version':'v6.1','contract_version':'v6.2',
        'source_openapi_sha256':hashlib.sha256(api_path.read_bytes()).hexdigest(),
        'documents':documents,'handlers':handlers,'core_entities':entities,
        'transaction_rules':[f'TX-{n:02}'for n in range(1,10)],'common_rules':[f'C{n:02}'for n in range(5)],
        'workers':['W01','W02','W03','W04','W05','W06','W07'],
        'policy_trace':spec['policy_trace'],'work_dependencies':spec['work_dependencies'],
        'inherited_acceptance':{'GROW':28,'DES':10,'v5':43},'detailed_acceptance':tests,
        'reference_values':{'fresh_action_ttl_seconds':120,'heartbeat_interval_ms':1000,'max_heartbeat_gap_ms':3000,
            'startup_allowance_ms':10000,'max_view_ms':30000,'min_view_ms':15000,'evidence_ttl_seconds':600,
            'worker_lease_seconds':15,'worker_batch_size':50,'network_retry_limit':8,
            'report_expected_delay_minutes':15,'report_recovery_window_minutes':60},
        'first_release':'R0_model_p1','schema_is_executable_migration':False,
        'product_acceptance_checks_passed':0}
    (DETAIL/'catalog.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    return result


if __name__=='__main__':
    d=build();print(json.dumps({'handlers':len(d['handlers']),'core_entities':len(d['core_entities']),
        'new_planned_tests':len(d['detailed_acceptance'])}))
