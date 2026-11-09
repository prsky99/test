"""Contract checks and small accounting/state examples, not product security tests."""
from pathlib import Path
from copy import deepcopy
import hashlib
import json
import re
import runpy
import tempfile

from fastapi.openapi.models import OpenAPI
from jsonschema import Draft202012Validator, FormatChecker

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
checks = []


def check(name, condition):
    if not condition:
        raise AssertionError(name)
    checks.append(name)


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    docs = ROOT / 'docs'
    api = json.loads((docs/'ad_coin_platform_p1.openapi.json').read_text())
    spec = json.loads((docs/'ad_coin_platform_v6_1_spec.json').read_text())
    baseline = json.loads((ROOT/'reports/ad-coin-doc-refresh-2026-11-06/verification.json').read_text())
    inherited = json.loads((ROOT/'reports/ad-coin-design-v5-2026-11-06/validation.json').read_text())
    # Keep the standards-valid mTLS requirement: this installation's FastAPI enum is older.
    partial = deepcopy(api)
    check('OAS 3.1 mTLS declaration retained', partial['components']['securitySchemes'].pop('MutualTLS') == {'type': 'mutualTLS'})
    for item in partial['paths'].values():
        for operation in item.values():
            for requirement in operation['security']:
                requirement.pop('MutualTLS', None)
    OpenAPI.model_validate(partial)
    check('remaining document passes installed FastAPI OpenAPI structural model', True)
    for name, schema in api['components']['schemas'].items():
        Draft202012Validator.check_schema(schema)
        check('JSON Schema syntax: '+name, True)

    def walk(value):
        if isinstance(value, dict):
            if '$ref' in value:
                target = api
                check('local schema reference: '+value['$ref'], value['$ref'].startswith('#/'))
                for part in value['$ref'][2:].split('/'):
                    target = target[part]
            for child in value.values():
                walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)
    walk(api)
    ops = []
    for path, item in api['paths'].items():
        for method, operation in item.items():
            ops.append(operation['operationId'])
            placeholders = set(re.findall(r'{(\w+)}', path))
            check('path parameters: '+operation['operationId'], placeholders == {
                p['name'] for p in operation['parameters'] if p['in'] == 'path' and p['required']})
            if method != 'get':
                check('idempotency header: '+operation['operationId'], any(
                    p['name']=='Idempotency-Key' and p['required'] for p in operation['parameters']))
            if operation['x-human-only']:
                check('human authentication boundary: '+operation['operationId'], all(
                    'HumanSession' in sec and 'AgentKey' not in sec for sec in operation['security']))
                if method != 'get':
                    check('human write CSRF: '+operation['operationId'], all('Csrf' in sec for sec in operation['security']))
            if operation['x-principal-kinds'] == ['ops']:
                check('reviewer isolated authentication: '+operation['operationId'], operation['security']==[{'OpsService': [], 'MutualTLS': []}])
    check('unique and matching operation IDs', len(ops)==len(set(ops))==len(spec['operation_catalog']) and
          set(ops)=={op['id'] for op in spec['operation_catalog']})
    validators = {}
    for name in api['components']['schemas']:
        validators[name] = Draft202012Validator({'$ref': '#/components/schemas/'+name,
            'components': api['components']}, format_checker=FormatChecker())

    uid = '00000000-0000-4000-8000-000000000001'
    consent = {'fresh_action_id': uid, 'fresh_action_proof': 'a'*43, 'offer_id': uid, 'quote_hash': 'a'*64}
    check('valid typed consent request', not list(validators['ConsentRequest'].iter_errors(consent)))
    for name, value in [
        ('client actor', dict(consent, actor='human')),
        ('client accepted verdict', dict(consent, accepted=True)),
        ('missing fresh proof', {k:v for k,v in consent.items() if k!='fresh_action_proof'}),
        ('malformed offer ID', dict(consent, offer_id='another-user'))]:
        check('reject consent shape: '+name, bool(list(validators['ConsentRequest'].iter_errors(value))))
    wallet = {'id':uid,'asset_id':'model:aiac:v2','available_atoms':'1000000','locked_atoms':'0',
              'ownership':'user_owned','mode':'model'}
    check('valid atom-string wallet', not list(validators['WalletView'].iter_errors(wallet)))
    for bad in [True, 1.0, 1, '-1', '1.5', '1e6', '01']:
        check('reject noncanonical money: '+repr(bad), bool(list(validators['WalletView'].iter_errors(dict(wallet,available_atoms=bad)))))
    signed = {'id':uid,'kind':'p1_award','offer_id':uid,'stage_key':'P1','asset_id':'model:aiac:v2',
              'user_reward_atoms':'5','quote_hash':'a'*64,'issued_at':'2026-11-07T00:00:00Z',
              'signature_state':'signed','signature':None}
    check('signed receipt cannot have null signature', bool(list(validators['ReceiptView'].iter_errors(signed))))
    signed['signature']='opaque-test-signature'
    check('signed receipt schema accepts signature', not list(validators['ReceiptView'].iter_errors(signed)))
    evidence={'sequence':0,'nonce':'a'*43,'elapsed_claim_ms':15000,'visible':True,'foreground':True}
    check('evidence submission has no accepted verdict', bool(list(validators['EvidenceRequest'].iter_errors(dict(evidence,accepted=True)))))

    policies = re.findall(r'^\*\*(PLAT-\d{2}) ·', (docs/'AD_COIN_PLATFORM_POLICY.md').read_text(), re.M)
    check('all 38 current policies mapped', set(policies)==set(spec['policy_trace']) and len(policies)==38)
    for policy, trace in spec['policy_trace'].items():
        check('module/work/gate trace: '+policy, all(trace[k] for k in ('modules','work_packages','planned_gates')))
    check('all 28 planned product gates retained', len(spec['planned_gates'])==28)
    deps = spec['work_dependencies']; resolved=set()
    while len(resolved)<len(deps):
        ready={w for w, before in deps.items() if set(before)<=resolved}-resolved
        check('work dependency graph advances '+str(len(resolved)), bool(ready))
        resolved.update(ready)
    check('12 work packages form an acyclic graph', len(resolved)==12)
    for parent, state in spec['states'].items():
        check('all state transitions resolve: '+parent, all(to in state for transitions in state.values() for to in transitions.values()))
    state = spec['states']['offer_base_p1']; current='reserved'
    for event in ['consent','start','submit_completion','review','accept_and_post']:
        current=state[current][event]
    check('P1 state path reaches award through accepted evidence', current=='awarded')
    check('no direct award or pending-expiry transition', 'accept_and_post' not in state['reserved'] and
          'expire' not in state['evidence_pending'] and 'expire' not in state['review_pending'])
    check('awarded P1 is terminal', not state['awarded'])

    # Illustration: atoms, exact split and hold conservation; no DB/concurrency assertion.
    split=spec['reference_profile']['split_bps']
    for gross in [2,3,17,999,100000000,2**256-1]:
        parts={k:gross*bps//10000 for k,bps in split.items() if k!='platform'}
        parts['platform']=gross-sum(parts.values())
        check('integer split conservation '+str(gross), sum(parts.values())==gross and min(parts.values())>=0 and parts['user']>0)
    campaign=100; hold=20; available=campaign-hold; spent=10; hold-=spent
    check('base award preserves campaign plus beneficiaries', available+hold+spent==100)
    available+=hold; hold=0
    check('expired additional reward releases only remainder', available==90 and spent==10 and available+spent==100)
    original_window_committed=20-10; next_window_committed=0
    check('old-window release adds no current-window commitment', original_window_committed==10 and next_window_committed==0)

    documents=[docs/f for f in spec['documents'] if f.endswith('.md')]+[docs/'AD_COIN_PLATFORM_ROADMAP.md',OUT/'README.md']
    links=0
    for path in documents:
        check('document exists: '+str(path.relative_to(ROOT)), path.is_file())
        for target in re.findall(r'\[[^\]]*\]\(([^)]+)\)', path.read_text()):
            if target.startswith(('http://','https://','#','mailto:')):
                continue
            dest=(path.parent/target.split('#')[0]).resolve()
            if dest==OUT/'validation.json':
                continue
            check('local link: '+str(path.relative_to(ROOT))+' '+target, dest.exists()); links+=1
    generated=runpy.run_path(str(OUT/'build_contracts.py'))['build']
    with tempfile.TemporaryDirectory() as temp:
        temporary=Path(temp)
        (temporary/'AD_COIN_PLATFORM_ROADMAP.md').write_text((docs/'AD_COIN_PLATFORM_ROADMAP.md').read_text())
        generated.__globals__['DOCS']=temporary
        reproduced_api,reproduced_spec=generated()
    check('generated API and machine spec are reproducible', api==reproduced_api and spec==reproduced_spec)
    changed=[f for f,h in baseline['source_sha256'].items() if digest(ROOT/f)!=h]
    check('33 historical product/test/script sources unchanged', not changed)
    check('v5 asset machine specification preserved', digest(docs/'ad_coin_v5_spec.json')==inherited['sha256']['docs/ad_coin_v5_spec.json'])
    evidence_paths=documents+[docs/'ad_coin_platform_v6_1_spec.json',docs/'ad_coin_platform_p1.openapi.json',
                               OUT/'build_contracts.py',Path(__file__)]
    report={'profile':'ai-ad-coin-development-design-v6.1-validation','date_kst':'2026-11-07',
            'passed':True,'checks_count':len(checks),'checks':checks,'operations':len(ops),
            'schemas':len(validators),'policies':len(policies),'work_packages':len(resolved),'local_links_checked':links,
            'openapi_validation_scope':'Installed FastAPI structural model excludes unsupported mutualTLS enum; original OAS 3.1 mTLS shape and AND requirement checked separately. Local refs and JSON Schema syntax/selected payloads checked. Not a complete OpenAPI standards certification.',
            'product_tests_run':0,'product_acceptance_checks_passed':0,'real_value_enabled':False,
            'historical_source_changes':changed,
            'limits':['No product API/authentication execution','No PostgreSQL migration/concurrency tests',
                      'No browser/human attention proof','No contracts/chain/real reserves/legal clearance',
                      'No performance or market-effect measurement'],
            'sha256':{str(path.relative_to(ROOT)):digest(path) for path in evidence_paths}}
    (OUT/'validation.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({k:report[k] for k in ['passed','checks_count','operations','schemas','policies','work_packages',
                                          'local_links_checked','product_acceptance_checks_passed','historical_source_changes']}))


if __name__=='__main__':
    main()
