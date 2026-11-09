"""Validate design contracts, not deployed APIs, cryptography or concurrency."""
from pathlib import Path
from copy import deepcopy
import hashlib
import json
import re
import runpy
import tempfile

from fastapi.openapi.models import OpenAPI
from jsonschema import Draft202012Validator, FormatChecker

ROOT=Path(__file__).resolve().parents[2]
OUT=Path(__file__).resolve().parent
CHECKS=[]


def check(name, ok):
    if not ok:raise AssertionError(name)
    CHECKS.append(name)


def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    docs=ROOT/'docs'
    api=json.loads((docs/'ad_coin_platform_p1_v6_2.openapi.json').read_text())
    spec=json.loads((docs/'ad_coin_platform_v6_2_spec.json').read_text())
    copy=deepcopy(api)
    check('original OAS mTLS scheme retained',copy['components']['securitySchemes'].pop('MutualTLS')=={'type':'mutualTLS'})
    for item in copy['paths'].values():
        for op in item.values():
            for sec in op['security']:sec.pop('MutualTLS',None)
    OpenAPI.model_validate(copy)
    check('partial installed FastAPI structural model',True)
    def walk(value):
        if isinstance(value,dict):
            if '$ref' in value:
                check('local ref '+value['$ref'],value['$ref'].startswith('#/'))
                target=api
                for token in value['$ref'][2:].split('/'):target=target[token]
            for part in value.values():walk(part)
        elif isinstance(value,list):
            for part in value:walk(part)
    walk(api)
    validators={}
    for name,schema in api['components']['schemas'].items():
        Draft202012Validator.check_schema(schema)
        validators[name]=Draft202012Validator({'$ref':'#/components/schemas/'+name,'components':api['components']},format_checker=FormatChecker())
        check('schema syntax '+name,True)
    seen=[]
    for path,item in api['paths'].items():
        for method,op in item.items():
            seen.append(op['operationId'])
            check('path refs '+op['operationId'],set(re.findall(r'{(\w+)}',path))=={
                p['name'] for p in op['parameters'] if p['in']=='path' and p['required']})
            if method!='get':
                check('idempotency '+op['operationId'],any(p['name']=='Idempotency-Key' and p['required'] for p in op['parameters']))
                check('explicit contract pin '+op['operationId'],any(p['name']=='X-AIAC-Contract' and p['required'] and p['schema']['const']=='v6.2' for p in op['parameters']))
            if op['x-human-only']:
                check('human auth '+op['operationId'],all('HumanSession'in s and 'AgentKey'not in s for s in op['security']))
                if method!='get':check('CSRF '+op['operationId'],all('Csrf'in s for s in op['security']))
            if op['x-principal-kinds']==['ops']:
                check('review mTLS AND token '+op['operationId'],op['security']==[{'OpsService':[],'MutualTLS':[]}])
    check('29 unique operations agree with registry',len(seen)==len(set(seen))==29 and set(seen)=={o['id'] for o in spec['operation_catalog']})
    check('ACK is a distinct nonpayment permission',api['paths']['/advertisers/{advertiser_id}/reports/{report_id}/consumption']['post']['x-capabilities']==['reports.acknowledge'])
    def valid(name,value):return not list(validators[name].iter_errors(value))
    metric={'name':'valid_exposures','state':'measured','unit':'count','value':'0','reason_code':None}
    check('measured zero remains valid',valid('ReportMetric',metric))
    check('unmeasured zero rejected',not valid('ReportMetric',dict(metric,state='not_measured',reason_code='not_collected')))
    check('unmeasured null with reason valid',valid('ReportMetric',dict(metric,state='not_measured',value=None,reason_code='not_collected')))
    check('suppressed value cannot leak',not valid('ReportMetric',dict(metric,state='suppressed',value='7',reason_code='privacy')))
    check('unavailable metric needs reason',not valid('ReportMetric',dict(metric,state='suppressed',value=None)))
    check('atomic reward uses atom unit',not valid('ReportMetric',dict(metric,name='user_rewards_atoms')))
    check('account count not silently named human reach',not valid('ReportMetric',dict(metric,name='unique_reach')))
    uid='00000000-0000-4000-8000-000000000001'
    obligation={'id':uid,'period_start':'2026-11-07T00:00:00Z','period_end':'2026-11-08T00:00:00Z','timezone':'UTC',
                'expected_at':'2026-11-08T00:01:00Z','state':'available','current_revision':None,'report_id':None}
    check('available report needs immutable revision link',not valid('ReportingObligation',obligation))
    check('waiting report does not invent zero report',valid('ReportingObligation',dict(obligation,state='waiting')))
    check('received ACK needs digest',not valid('ReportConsumptionRequest',{'revision':1,'state':'received','observed_digest':None}))
    check('missing ACK may have no digest',valid('ReportConsumptionRequest',{'revision':1,'state':'missing','observed_digest':None}))
    receipt={'id':uid,'kind':'p1_award','offer_id':uid,'stage_key':'P1','asset_id':'model:aiac:v2','user_reward_atoms':'1',
        'quote_hash':'a'*64,'issued_at':'2026-11-07T00:00:00Z','signature_state':'signed','key_id':None,'jws':None,
        'issuer':'ai-ad-coin/model','audience':'aiac-reward-receipt','policy_version':'v6.1','contract_version':'v6.2'}
    check('signed receipt cannot omit key and JWS',not valid('ReceiptView',receipt))
    check('pending receipt has no signature',valid('ReceiptView',dict(receipt,signature_state='pending')))
    check('pending cannot claim JWS',not valid('ReceiptView',dict(receipt,signature_state='pending',key_id='k',jws='e30.e30.fake')))
    header={'typ':'aiac-receipt+jwt','alg':'EdDSA','kid':'model-key-1'}
    check('typed receipt header valid',valid('ReceiptHeader',header))
    for value in [dict(header,alg='none'),dict(header,alg='HS256'),dict(header,jku='https://invalid.example/key'),dict(header,typ='JWT')]:
        check('reject header confusion '+str(value),not valid('ReceiptHeader',value))
    claims={'receipt_id':uid,'offer_id':uid,'stage_key':'P1','asset_id':'model:aiac:v2','user_reward_atoms':'1',
        'quote_hash':'a'*64,'policy_version':'v6.1','contract_version':'v6.2','iss':'ai-ad-coin/model','aud':'aiac-reward-receipt','iat':0}
    check('typed receipt claims valid',valid('ReceiptClaims',claims))
    check('receipt cannot be auth audience',not valid('ReceiptClaims',dict(claims,aud='spend')))
    jwk={'kid':'k','status':'active','not_before':'2026-11-07T00:00:00Z','verify_until':'2026-11-08T00:00:00Z',
         'jwk':{'kty':'OKP','crv':'Ed25519','alg':'EdDSA','use':'sig','x':'a'*43}}
    check('private JWK field rejected',not valid('ReceiptKey',dict(jwk,jwk=dict(jwk['jwk'],d='private'))))
    evidence={'sequence':0,'nonce':'a'*43,'elapsed_claim_ms':30001,'visible':True,'foreground':True}
    check('active view limit separate from submission TTL',not valid('EvidenceRequest',evidence))
    check('30 second shape accepted, not proof of viewing',valid('EvidenceRequest',dict(evidence,elapsed_claim_ms=30000)))
    prefs={'fresh_action_id':uid,'fresh_action_proof':'a'*43,'receive_offers':True,'context_fields':['task_category'],
           'max_offers_per_day':10,'max_ads_per_campaign_day':3,'max_ads_per_day':10,'max_ad_ms_per_day':600000}
    check('global plus campaign limits contract',valid('PreferencesRequest',prefs))
    check('global time cap enforced by schema',not valid('PreferencesRequest',dict(prefs,max_ad_ms_per_day=600001)))
    check('R0 external adapters and paid model calls off',spec['protocol_adoption']['external_adapters_enabled_in_R0'] is False and
          spec['reference_profile']['external_paid_model_calls_enabled'] is False)
    check('view and evidence deadlines differ',spec['reference_profile']['max_active_view_ms']<spec['reference_profile']['evidence_ttl_seconds']*1000)
    policy_ids=set(re.findall(r'^\*\*(PLAT-\d{2}) ·',(docs/'AD_COIN_PLATFORM_POLICY.md').read_text(),re.M))
    check('38 policy trace unchanged',len(policy_ids)==38 and policy_ids==set(spec['policy_trace']))
    for policy,trace in spec['policy_trace'].items():check('trace '+policy,all(trace[k] for k in ['modules','work_packages','planned_gates']))
    check('ten new design acceptance cases',set(spec['additional_design_acceptance'])=={f'DES-{n:02}'for n in range(1,11)})
    for ident,case in spec['additional_design_acceptance'].items():
        check('valid planned mappings '+ident,bool(case['policy_ids'])and set(case['policy_ids'])<=policy_ids and
              bool(case['work_packages'])and set(case['work_packages'])<=set(spec['work_dependencies'])and case['status']=='planned_not_executed')
    resolved=set()
    while len(resolved)<len(spec['work_dependencies']):
        ready={k for k,v in spec['work_dependencies'].items()if set(v)<=resolved}-resolved
        check('dependency progress '+str(len(resolved)),bool(ready));resolved.update(ready)
    check('GROW remains 28, work packages 12',len(spec['planned_gates'])==28 and len(resolved)==12)
    check('DEC decisions now 13',spec['decisions']==[f'DEC-{n:02}'for n in range(1,14)])
    sources=re.findall(r'^- \*\*(SRC-\d{2}):\*\*',(OUT/'README.md').read_text(),re.M)
    check('12 uniquely registered sources',len(sources)==len(set(sources))==12)
    paths=[docs/f for f in spec['documents']]+[docs/'AD_COIN_PLATFORM_ROADMAP.md',docs/'ad_coin_platform_v6_2_spec.json',
        docs/'AD_COIN.md',docs/'AD_COIN_V5_IMPLEMENTATION_PLAN.md',OUT/'README.md',OUT/'build_contracts.py',Path(__file__)]
    links=0
    for path in paths:
        check('file exists '+str(path.relative_to(ROOT)),path.exists())
        if path.suffix=='.md':
            for target in re.findall(r'\[[^\]]*\]\(([^)]+)\)',path.read_text()):
                if target.startswith(('https://','http://','#','mailto:')):continue
                resolved_link=(path.parent/target.split('#')[0]).resolve()
                if resolved_link==OUT/'validation.json':continue
                check('local link '+target,resolved_link.exists());links+=1
    generator=runpy.run_path(str(OUT/'build_contracts.py'))['build']
    with tempfile.TemporaryDirectory()as temp:second_api,second_spec=generator(temp)
    check('reproducible v6.2 contracts',api==second_api and spec==second_spec)
    previous=json.loads((ROOT/'reports/ad-coin-development-design-v6.1-2026-11-07/validation.json').read_text())
    for name in ['docs/ad_coin_platform_p1.openapi.json','docs/ad_coin_platform_v6_1_spec.json']:
        check('v6.1 contract preserved '+name,sha(ROOT/name)==previous['sha256'][name])
    v4=json.loads((ROOT/'reports/ad-coin-doc-refresh-2026-11-06/verification.json').read_text())
    changes=[f for f,h in v4['source_sha256'].items()if sha(ROOT/f)!=h]
    check('33 historical product/test/script sources unchanged',not changes)
    v5=json.loads((ROOT/'reports/ad-coin-design-v5-2026-11-06/validation.json').read_text())
    check('v5 asset spec preserved',sha(docs/'ad_coin_v5_spec.json')==v5['sha256']['docs/ad_coin_v5_spec.json'])
    report={'profile':'ai-ad-coin-design-upgrade-v6.2-validation','date_kst':'2026-11-07','passed':True,
        'checks_count':len(CHECKS),'checks':CHECKS,'operations':len(seen),'schemas':len(validators),'policies':len(policy_ids),
        'design_decisions':13,'work_packages':12,'planned_GROW':28,'planned_DES':10,'sources':len(sources),'local_links_checked':links,
        'product_acceptance_checks_passed':0,'product_tests_run':0,'historical_source_changes':changes,
        'scope':'JSON Schema syntax/selected payloads, references, contract/security annotations, trace, reproducibility and fingerprints. Partial FastAPI OAS model excludes unsupported mutualTLS enum; original mTLS AND condition checked separately. Not full OAS certification.',
        'limits':['No auth/browser/attention test','No PostgreSQL concurrency or worker fencing execution',
                  'No external retries or reports integration','No cryptographic JWS verification',
                  'No chain/reserves/legal/performance/market-effect test'],
        'sha256':{str(p.relative_to(ROOT)):sha(p)for p in paths}}
    (OUT/'validation.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({k:report[k]for k in ['passed','checks_count','operations','schemas','policies','design_decisions',
        'work_packages','planned_DES','sources','local_links_checked','product_acceptance_checks_passed','historical_source_changes']}))


if __name__=='__main__':main()
