"""Record bounded evidence and current fingerprints, never product secrets."""
from pathlib import Path
import hashlib
import json
import xml.etree.ElementTree as ET

ROOT=Path(__file__).resolve().parents[2]
OUT=Path(__file__).resolve().parent


def main():
    latest={};runs=[]
    for name in ('tests.xml','wp01-v2-contracts.xml'):
        cases=list(ET.parse(OUT/name).getroot().iter('testcase'))
        run={'file':name,'cases':len(cases),'failed':0,'skipped':0}
        for case in cases:
            failed=case.find('failure')is not None or case.find('error')is not None
            skipped=case.find('skipped')is not None
            run['failed']+=int(failed);run['skipped']+=int(skipped)
            latest[(case.get('classname'),case.get('name'))]={'passed':not(failed or skipped),'source':name}
        runs.append(run)
    dynamic=json.loads((OUT/'wp01-security/dynamic-security.json').read_text())['summary']
    findings=json.loads((OUT/'secure-coding.json').read_text())
    files=[ROOT/'agent_market/ad_coin/api.py',*sorted((ROOT/'agent_market/ad_coin/v2').glob('*.py')),
        ROOT/'agent_market/ad_coin/v2/p1_contract.json',ROOT/'tests/test_ad_coin.py',
        ROOT/'tests/test_ad_coin_authority.py',ROOT/'tests/test_ad_coin_v2_contracts.py',
        OUT/'tests.xml',OUT/'tests.log',OUT/'wp01-v2-contracts.xml',OUT/'wp01-postgres.xml',
        OUT/'secure-coding.json',OUT/'frontend-content.log',OUT/'wp01-security/dynamic-security.json',
        OUT/'PROGRESS.md',Path(__file__)]
    report={'profile':'ai-ad-coin-v6.2-development-increment','date_kst':'2026-11-08',
        'completed_scope':['v1_human_agent_authority_boundary','v2_contract_arithmetic_authority_primitives'],
        'R0_complete':False,'v2_router_mounted':False,'deployment_performed':False,
        'production_state_queried':False,'real_value_activated':False,'unit_runs':runs,
        'latest_unique_testcases':len(latest),'latest_unique_passed':sum(c['passed']for c in latest.values()),
        'dynamic_HTTP_security':dynamic,'static_security_findings':len(findings),
        'static_security_scope':'Ruff S rules on changed product API and v2 modules only.',
        'frontend_content_result':(OUT/'frontend-content.log').read_text().strip(),
        'remaining':['v2 persistence and financial/attention transactions','fresh-action/idempotency/outbox storage',
            'v2 transport authentication and epoch lookup','29 v2 handlers and reward/advertiser UI',
            'browser/PG concurrency and receipt-signing integration','full release/security/performance/real-value gates'],
        'sha256':{str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest()for p in files}}
    (OUT/'verification.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({k:report[k]for k in ['latest_unique_testcases','latest_unique_passed','static_security_findings','R0_complete']}))


if __name__=='__main__':main()
