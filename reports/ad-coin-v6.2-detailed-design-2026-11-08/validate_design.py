from pathlib import Path
import hashlib
import json
import re
import runpy

ROOT=Path(__file__).resolve().parents[2]
OUT=Path(__file__).resolve().parent


def main():
    catalog_path=ROOT/'docs/ad_coin_v6_2_detail/catalog.json'
    data=json.loads(catalog_path.read_text()); checks=[]
    def check(name,value):
        assert value,name
        checks.append(name)
    api_path=ROOT/'docs/ad_coin_platform_p1_v6_2.openapi.json'
    api=json.loads(api_path.read_text())
    operations={o['operationId']:(m.upper(),p,o)for p,ms in api['paths'].items()for m,o in ms.items()}
    check('29 operations all detailed',len(data['handlers'])==29 and {h['operation_id']for h in data['handlers']}==set(operations))
    check('unique API IDs',len({h['detail_id']for h in data['handlers']})==29)
    check('consecutive API IDs',{h['detail_id']for h in data['handlers']}=={f'API-{n:02}'for n in range(1,30)})
    source=json.loads((ROOT/'reports/ad-coin-design-upgrade-v6.2-2026-11-07/validation.json').read_text())
    check('OpenAPI unchanged from v6.2 design',hashlib.sha256(api_path.read_bytes()).hexdigest()==source['sha256'][str(api_path.relative_to(ROOT))])
    spec_path=ROOT/'docs/ad_coin_platform_v6_2_spec.json'
    check('v6.2 machine spec preserved',hashlib.sha256(spec_path.read_bytes()).hexdigest()==source['sha256'][str(spec_path.relative_to(ROOT))])
    for handler in data['handlers']:
        method,path,op=operations[handler['operation_id']]
        check('handler routing '+handler['operation_id'],handler['method']==method and handler['path']==path)
        check('handler authority '+handler['operation_id'],handler['principal_kinds']==op['x-principal-kinds']and handler['capabilities']==op['x-capabilities'])
        check('handler transaction '+handler['operation_id'],(handler['transaction_rule']=='read_only')==(method=='GET'))
    check('all core table names unique',len(data['core_entities'])==len({e['name']for e in data['core_entities']}))
    check('core tables include economic state',{'adc2_accounts','adc2_journals','adc2_postings','adc2_budget_holds','adc2_stage_awards','adc2_dispatch_intents','adc2_report_revisions'}<={e['name']for e in data['core_entities']})
    check('20 planned detailed scenarios',len(data['detailed_acceptance'])==20)
    for key,case in data['detailed_acceptance'].items():
        check('case trace '+key,bool(case['work_packages'])and set(case['work_packages'])<=set(data['work_dependencies'])and case['status']=='planned_not_executed')
    check('38 policies inherited',len(data['policy_trace'])==38)
    check('safety scope explicit',data['real_value_enabled']is False and data['schema_is_executable_migration']is False and data['product_acceptance_checks_passed']==0)
    files=[ROOT/'docs'/p for p in data['documents']]+[catalog_path,OUT/'README.md',OUT/'build_catalog.py',Path(__file__)]
    links=0
    for path in files:
        check('file exists '+str(path.relative_to(ROOT)),path.is_file())
        if path.suffix!='.md':continue
        check('no trailing whitespace '+path.name,all(line==line.rstrip()for line in path.read_text().splitlines()))
        for target in re.findall(r'\[[^\]]*\]\(([^)]+)\)',path.read_text()):
            if target.startswith(('https://','http://','#','mailto:')):continue
            resolved=(path.parent/target.split('#')[0]).resolve()
            if resolved==OUT/'validation.json':continue
            check('local link '+target,resolved.exists());links+=1
    baseline=json.loads((ROOT/'reports/ad-coin-doc-refresh-2026-11-06/verification.json').read_text())
    changes=[f for f,h in baseline['source_sha256'].items()if hashlib.sha256((ROOT/f).read_bytes()).hexdigest()!=h]
    reproduced=runpy.run_path(str(OUT/'build_catalog.py'))['build']()
    check('catalog reproducible',data==reproduced)
    report={'profile':'ai-ad-coin-v6.2-detailed-design-validation','date_kst':'2026-11-08','passed':True,
        'checks_count':len(checks),'checks':checks,'detailed_api_count':29,'core_entity_count':len(data['core_entities']),
        'planned_DTL':20,'local_links_checked':links,'historical_source_changes_at_design_time':changes,
        'product_tests_run':0,'product_acceptance_checks_passed':0,
        'scope':'Detailed document/API/authority/transaction mapping, links and preserved contract fingerprints. No database, authentication, concurrency, cryptography or runtime verification.',
        'sha256':{str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest()for p in files}}
    (OUT/'validation.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({k:report[k]for k in ['passed','checks_count','detailed_api_count','core_entity_count','planned_DTL','local_links_checked','historical_source_changes_at_design_time']}))


if __name__=='__main__':main()
