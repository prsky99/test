"""Produce v6.2 design contracts without changing preserved v6.1 contracts."""
from pathlib import Path
from copy import deepcopy
import hashlib
import json
import re

ROOT=Path(__file__).resolve().parents[2]
DOCS=ROOT/'docs'
BASE=ROOT/'reports/ad-coin-development-design-v6.1-2026-11-07/validation.json'
ID={'type':'string','format':'uuid'}
HASH={'type':'string','pattern':'^[0-9a-f]{64}$'}
TIME={'type':'string','format':'date-time'}
TEXT={'type':'string','minLength':1,'maxLength':128}
NULLTEXT={'type':['string','null'],'maxLength':512}
INT={'type':'integer','minimum':1}


def obj(fields, required=None):
    return {'type':'object','additionalProperties':False,'properties':fields,
            'required':list(fields) if required is None else required}


def ref(name):
    return {'$ref':'#/components/schemas/'+name}


def build(output=None):
    prior=json.loads(BASE.read_text())
    for name in ['docs/ad_coin_platform_p1.openapi.json','docs/ad_coin_platform_v6_1_spec.json']:
        assert hashlib.sha256((DOCS/name.split('/')[-1]).read_bytes()).hexdigest()==prior['sha256'][name], name
    api=deepcopy(json.loads((DOCS/'ad_coin_platform_p1.openapi.json').read_text()))
    spec=deepcopy(json.loads((DOCS/'ad_coin_platform_v6_1_spec.json').read_text()))
    api['info']['title']='AI AD Coin model P1 design contract v6.2'
    api['info']['version']='6.2.0-design'
    api['x-design-version']='v6.2'
    api['x-policy-version']='v6.1'
    api['x-parser-contract']={'reject_duplicate_json_members':True,'reject_unknown_fields':True,
        'reject_mixed_principals':True,'max_uncompressed_body_bytes':32768,
        'supported_request_media_types':['application/json'], 'body_read_is_bounded_while_streaming':True}
    s=api['components']['schemas']
    s['Capabilities']['properties'].update({'contract_version':{'const':'v6.2'},
        'adapter_profiles':{'type':'array','items':TEXT,'maxItems':0},
        'reporting_profile':{'const':'aiac_p1_reporting_v1'},
        'receipt_profile':{'const':'aiac_receipt_jws_v1'},
        'external_model_calls_enabled':{'const':False}})
    s['Capabilities']['required']=list(s['Capabilities']['properties'])
    s['PreferencesRequest']['properties'].update({
        'max_ads_per_day':{'type':'integer','minimum':0,'maximum':10},
        'max_ad_ms_per_day':{'type':'integer','minimum':0,'maximum':600000}})
    s['PreferencesRequest']['required']=list(s['PreferencesRequest']['properties'])
    s['PreferencesView']['properties'].update({
        'max_ads_per_day':{'type':'integer','minimum':0,'maximum':10},
        'max_ad_ms_per_day':{'type':'integer','minimum':0,'maximum':600000},
        'max_ads_per_campaign_day':{'type':'integer','minimum':0,'maximum':3}})
    s['PreferencesView']['required']=list(s['PreferencesView']['properties'])
    s['ExposureView']['properties'].update({'max_view_ms':{'type':'integer','minimum':15000,'maximum':30000},
                                           'quota_reservation_id':ID})
    s['ExposureView']['required']=list(s['ExposureView']['properties'])
    s['EvidenceRequest']['properties']['elapsed_claim_ms']['maximum']=30000
    s['CampaignView']['properties']['approval_status']={'enum':['unapproved','approved','invalidated']}
    s['CampaignView']['required'].append('approval_status')

    metric=obj({'name':{'enum':['valid_exposures','gross_ad_charge_atoms','user_rewards_atoms','unique_owners']},
                'state':{'enum':['measured','estimated','not_measured','suppressed','undefined']},
                'unit':{'enum':['count','atoms']},
                'value':{'type':['string','null'],'pattern':'^(0|[1-9][0-9]{0,77})$'},
                'reason_code':NULLTEXT})
    metric['allOf']=[{'if':{'properties':{'state':{'enum':['measured','estimated']}}},
                     'then':{'properties':{'value':{'type':'string'}}},
                     'else':{'properties':{'value':{'type':'null'},'reason_code':{'type':'string','minLength':1}}}},
                    {'if':{'properties':{'name':{'enum':['gross_ad_charge_atoms','user_rewards_atoms']}}},
                     'then':{'properties':{'unit':{'const':'atoms'}}},
                     'else':{'properties':{'unit':{'const':'count'}}}}]
    s['ReportMetric']=metric
    s['ReportingObligation']=obj({'id':ID,'period_start':TIME,'period_end':TIME,'timezone':{'const':'UTC'},
        'expected_at':TIME,'state':{'enum':['waiting','available','delayed','action_required']},
        'current_revision':{'type':['integer','null'],'minimum':1},
        'report_id':{'type':['string','null'],'format':'uuid'}})
    s['ReportingObligation']['allOf']=[{'if':{'properties':{'state':{'const':'available'}}},
        'then':{'properties':{'current_revision':{'type':'integer','minimum':1},'report_id':{'type':'string','format':'uuid'}}}}]
    s['ReportingStatus']=obj({'obligations':{'type':'array','maxItems':200,'items':ref('ReportingObligation')},
                              'next_cursor':NULLTEXT})
    s['ReportRevision']=obj({'id':ID,'obligation_id':ID,'revision':INT,'content_digest':HASH,
        'supersedes_revision':{'type':['integer','null'],'minimum':1},
        'generated_at':TIME,'data_through':TIME,'methodology_version':TEXT,
        'vendor_id':TEXT,'vendor_relationship':{'const':'first_party'},
        'complete':{'type':'boolean'},'timezone':{'const':'UTC'},
        'metrics':{'type':'array','maxItems':40,'items':ref('ReportMetric')}})
    s['ReportConsumptionRequest']=obj({'revision':INT,'state':{'enum':['received','missing','unreadable','content_mismatch']},
        'observed_digest':{'type':['string','null'],'pattern':'^[0-9a-f]{64}$'}})
    s['ReportConsumptionRequest']['allOf']=[{'if':{'properties':{'state':{'enum':['received','content_mismatch']}}},
        'then':{'properties':{'observed_digest':{'type':'string'}}}}]
    s['ReportConsumptionView']=obj({'id':ID,'report_id':ID,'revision':INT,
        'state':{'enum':['received','missing','unreadable','content_mismatch']},'recorded_at':TIME})
    s['ReceiptHeader']=obj({'typ':{'const':'aiac-receipt+jwt'},'alg':{'const':'EdDSA'},'kid':TEXT})
    s['ReceiptClaims']=obj({'receipt_id':ID,'offer_id':ID,'stage_key':{'const':'P1'},
        'asset_id':TEXT,'user_reward_atoms':{'type':'string','pattern':'^[1-9][0-9]{0,77}$'},'quote_hash':HASH,
        'policy_version':{'const':'v6.1'},'contract_version':{'const':'v6.2'},
        'iss':{'const':'ai-ad-coin/model'},'aud':{'const':'aiac-reward-receipt'},
        'iat':{'type':'integer','minimum':0}})
    receipt=s['ReceiptView']
    receipt['properties'].pop('signature')
    receipt['properties'].update({'key_id':NULLTEXT,
        'jws':{'type':['string','null'],'maxLength':4096,'pattern':'^[A-Za-z0-9_-]+\\.[A-Za-z0-9_-]+\\.[A-Za-z0-9_-]+$'},
        'issuer':{'const':'ai-ad-coin/model'},'audience':{'const':'aiac-reward-receipt'},
        'policy_version':{'const':'v6.1'},'contract_version':{'const':'v6.2'}})
    receipt['required']=list(receipt['properties'])
    receipt['allOf']=[{'if':{'properties':{'signature_state':{'const':'signed'}}},
        'then':{'properties':{'key_id':{'type':'string','minLength':1},'jws':{'type':'string','minLength':1}}},
        'else':{'properties':{'key_id':{'type':'null'},'jws':{'type':'null'}}}}]
    s['ReceiptKey']=obj({'kid':TEXT,'status':{'enum':['active','verify_only','revoked']},'not_before':TIME,
        'verify_until':TIME,'jwk':obj({'kty':{'const':'OKP'},'crv':{'const':'Ed25519'},'alg':{'const':'EdDSA'},
                                      'use':{'const':'sig'},'x':{'type':'string','pattern':'^[A-Za-z0-9_-]{43}$'}})})
    s['ReceiptKeySet']=obj({'issuer':{'const':'ai-ad-coin/model'},
                           'keys':{'type':'array','maxItems':20,'items':ref('ReceiptKey')}})
    s['Error']['properties']['error']['properties']['recovery']=obj({
        'action':{'enum':['reauthenticate','refresh_resource','poll_operation','wait','contact_support','do_not_retry']},
        'operation_id':{'type':['string','null'],'format':'uuid'},
        'retry_after_seconds':{'type':['integer','null'],'minimum':1}})
    recovery=s['Error']['properties']['error']['properties']['recovery']
    recovery['allOf']=[{'if':{'properties':{'action':{'const':'poll_operation'}}},
        'then':{'properties':{'operation_id':{'type':'string','format':'uuid'}}}}]
    s['Error']['properties']['error']['required'].append('recovery')

    added=[('get','/receipt-keys','getReceiptKeys',None,'ReceiptKeySet',['public']),
           ('get','/advertisers/{advertiser_id}/reporting-status','getReportingStatus',None,'ReportingStatus',['human']),
           ('get','/advertisers/{advertiser_id}/reports/{report_id}/revisions/{revision}','getReportRevision',None,'ReportRevision',['human']),
           ('post','/advertisers/{advertiser_id}/reports/{report_id}/consumption','recordReportConsumption',
            'ReportConsumptionRequest','ReportConsumptionView',['human'])]
    for method,path,op_id,req,resp,actors in added:
        params=[{'name':p,'in':'path','required':True,'schema':INT if p=='revision' else ID} for p in re.findall(r'{(\w+)}',path)]
        if method=='post':
            params.append({'name':'Idempotency-Key','in':'header','required':True,
                           'schema':{'type':'string','minLength':16,'maxLength':128}})
        if op_id=='getReportingStatus':
            params.extend([{'name':'limit','in':'query','schema':{'type':'integer','minimum':1,'maximum':200,'default':100}},
                           {'name':'cursor','in':'query','schema':{'type':'string','maxLength':512}}])
        op={'operationId':op_id,'parameters':params,'security':[] if actors==['public'] else
            [{'HumanSession':[],**({'Csrf':[]} if method=='post' else {})}],
            'x-principal-kinds':actors,'x-capabilities':[] if actors==['public'] else ['reports.read'],
            'x-human-only':actors==['human'],'x-fresh-action-required':False,
            'x-object-authorization':'public verification keys only' if actors==['public'] else 'server-bound advertiser membership and report scope',
            'x-idempotency-required':method=='post','x-authorization-on-replay':True,
            'responses':{'200':{'description':'Authorized contract data; acknowledgement is not payment.',
                'content':{'application/json':{'schema':ref(resp)}}},
                'default':{'description':'Safe structured error.','content':{'application/json':{'schema':ref('Error')}}}}}
        if req:op['requestBody']={'required':True,'content':{'application/json':{'schema':ref(req)}}}
        api['paths'][path]={method:op}
        spec['operation_catalog'].append({'id':op_id,'method':method.upper(),'path':path,'actors':actors,'fresh_action_required':False})
    # An ACK is a distinct write permission, even though it moves no money.
    api['paths']['/advertisers/{advertiser_id}/reports/{report_id}/consumption']['post']['x-capabilities']=['reports.acknowledge']
    api['paths']['/advertisers/{advertiser_id}/reports/{report_id}/consumption']['post']['x-semantic-checks']=[
        'received requires observed digest to equal the stored immutable revision',
        'consumption status never authorizes payment or reward']
    for item in api['paths'].values():
        for method,operation in item.items():
            operation['x-contract-version']='v6.2'
            if method!='get':
                operation['parameters'].append({'name':'X-AIAC-Contract','in':'header','required':True,
                    'schema':{'type':'string','const':'v6.2'},
                    'description':'Explicit contract pin, included in canonical request digests.'})
            operation['x-idempotency-retention']='economic event tombstones survive object deletion'
            for response in operation['responses'].values():
                response.setdefault('headers',{})['Cache-Control']={'schema':{'const':'no-store','type':'string'}}

    spec['profile']='ai-ad-coin-platform-design-v6.2'
    spec['policy_version']='v6.1'
    spec['decisions'] += [f'DEC-{n:02}' for n in range(8,14)]
    spec['documents']=[p.replace('ad_coin_platform_p1.openapi.json','ad_coin_platform_p1_v6_2.openapi.json') for p in spec['documents']]
    spec['documents'].append('AD_COIN_PLATFORM_DESIGN_UPGRADE.md')
    spec['reference_profile'].update({'max_ads_per_owner_day':10,'max_ad_ms_per_owner_day':600000,
                                     'max_active_view_ms':30000,'external_paid_model_calls_enabled':False})
    spec['money_guards']+=['dispatch_epoch_checked_at_commit','stale_lease_generation_cannot_write',
        'in_flight_unknown_effects_never_released_by_timeout','operating_costs_not_paid_from_reserve',
        'report_revisions_never_replay_awards']
    spec['protocol_adoption']={'external_adapters_enabled_in_R0':False,'stable_beta_distinguished':True,
        'exact_schema_and_auth_profile_required':True,'automatic_main_branch_upgrade':False,
        'transport_identity_grants_business_authority':False}
    spec['receipt_profile']={'format':'JWS compact','typ':'aiac-receipt+jwt','alg':'EdDSA','curve':'Ed25519',
        'issuer':'ai-ad-coin/model','audience':'aiac-reward-receipt','claims_schema':'ReceiptClaims',
        'header_schema':'ReceiptHeader',
        'remote_jku_x5u_allowed':False,'receipt_grants_consent_or_spend':False,
        'verify_payload_matches_display_fields':True,'issued_at_matches_iat_in_UTC_seconds':True}
    spec['reporting_profile']={'name':'aiac_p1_reporting_v1','adcp_conformance_claimed':False,
        'immutable_revisions':True,'obligations_from_schedule':True,'ack_is_payment':False,
        'missing_is_zero':False,'timezone':'UTC','R0_vendor_relationship':'first_party'}
    text=(DOCS/'AD_COIN_PLATFORM_DESIGN_UPGRADE.md').read_text()
    tests={}
    for ident,line in re.findall(r'^- \*\*(DES-\d{2}):\*\* (.+)$',text,re.M):
        policies=[]
        for n,tail in re.findall(r'PLAT-(\d{2})((?:·\d{2})*)',line):
            policies.extend('PLAT-'+p for p in [n,*re.findall(r'·(\d{2})',tail)])
        works=[]
        for n,tail in re.findall(r'WP-(\d{2})((?:·\d{2})*)',line):
            works.extend('WP-'+p for p in [n,*re.findall(r'·(\d{2})',tail)])
        tests[ident]={'policy_ids':policies,'work_packages':works,'status':'planned_not_executed'}
    spec['additional_design_acceptance']=tests
    spec['baseline_contracts_preserved']=['ad_coin_platform_p1.openapi.json','ad_coin_platform_v6_1_spec.json']
    output=Path(output) if output else DOCS
    (output/'ad_coin_platform_p1_v6_2.openapi.json').write_text(json.dumps(api,indent=2)+'\n')
    (output/'ad_coin_platform_v6_2_spec.json').write_text(json.dumps(spec,indent=2)+'\n')
    return api,spec


if __name__=='__main__':
    api,spec=build()
    print(json.dumps({'operations':len(spec['operation_catalog']),'schemas':len(api['components']['schemas']),
                      'decisions':len(spec['decisions']),'new_planned_tests':len(spec['additional_design_acceptance']),
                      'status':'design_only'}))
