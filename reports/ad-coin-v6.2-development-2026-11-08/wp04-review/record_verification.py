"""Record reviewed model changes and real failure/pass evidence; preserve earlier stages."""
from pathlib import Path
import hashlib
import json
import subprocess
import sys
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT))


def cases(path):
    return {(row.get('classname'),row.get('name')):row for row in ET.parse(path).getroot().iter('testcase')}


def main():
    from agent_market.ad_coin.sql_registry import check,shape
    from agent_market.ad_coin.v2.commercial import READS,WRITES
    from agent_market.ad_coin.v2.contracts import P1Contract
    from agent_market.ad_coin.v2.schema import VERSION,statements
    from agent_market.ad_coin.v2.sql import all_statements
    before, after = cases(OUT/'reproduced.xml'),cases(OUT/'accepted.xml')
    assert len(before)==8 and all(row.find('failure') is not None for row in before.values())
    assert len(after)==151 and before.keys() <= after.keys()
    assert all(all(row.find(tag) is None for tag in ('failure','error','skipped')) for row in after.values())
    assert READS|WRITES==P1Contract().operation_ids
    counts={}
    for module,_ in after:
        counts[module]=counts.get(module,0)+1
    old_http=json.loads((OUT/'legacy-http-security/dynamic-security.json').read_text())['summary']
    assert old_http['checks']==old_http['passed']==219 and old_http['failed']==0
    assert json.loads((OUT/'secure-coding.json').read_text())==[]
    baseline=json.loads(subprocess.run(['git','show','HEAD:agent_market/ad_coin/sql_registry.json'],
        cwd=ROOT,check=True,capture_output=True,text=True,timeout=10).stdout)
    legacy={row['sql'] for row in baseline['statements'] if 'adc2_' not in row['sql']}
    catalog=json.loads((ROOT/'agent_market/ad_coin/sql_registry.json').read_text())['statements']
    assert legacy <= {row['sql'] for row in catalog}
    for sql in all_statements():
        check(sql)
        assert 'sqlite' not in sql.lower()
    files=[*sorted((ROOT/'agent_market/ad_coin/v2').glob('*.py')),ROOT/'agent_market/ad_coin/v2/p1_contract.json',
        ROOT/'agent_market/ad_coin/sql_registry.json',ROOT/'tests/test_ad_coin_v2_review.py',
        ROOT/'tests/test_ad_coin_v2_p1.py',ROOT/'tests/test_ad_coin_v2_commercial.py',
        ROOT/'docs/AD_COIN.md',ROOT/'docs/AD_COIN_PLATFORM_IMPLEMENTATION_PLAN.md',
        ROOT/'docs/ad_coin_v6_2_detail/02-storage-transactions.md',ROOT/'docs/ad_coin_v6_2_detail/03-api-handlers.md',
        OUT.parent/'PROGRESS.md',OUT/'README.md',OUT/'reproduced.xml',OUT/'reproduced.log',
        OUT/'accepted.xml',OUT/'accepted.log',OUT/'secure-coding.json',OUT/'legacy-http-security/dynamic-security.json',Path(__file__)]
    report={'profile':'ai-ad-coin-v6.2-improvement-review','date_kst':'2026-11-08',
        'postgres_only':True,'model_only':True,'model_schema_version':VERSION,
        'tables':sum(s.startswith('CREATE TABLE') for s in statements()),'contract_operations':len(READS|WRITES),
        'review_scope':['evidence timing/prefix and independent reward verification','delivery eligibility and current guards/quota',
            'idempotency sequence/nonce responses','worker lease fencing and expiry','JWS model purpose/canonical profile',
            'report facts/late awards/manifests/digest','existing database constraints and campaign revision limits'],
        'reproduced_failures':len(before),'reproduced_cases_fixed':len(before.keys() & after.keys()),
        'accepted':{'passed':len(after),'failed':0,'skipped':0,'by_module':counts,
                    'deselected':['legacy v1 SQLite import test']},
        'legacy_v1_dynamic_HTTP':old_http,
        'actual_localhost_v2_test':'test_real_localhost_zero_time_reward_attack_is_rejected',
        'static_security':{'tool':'Ruff S','scope':'ad_coin/api.py and v2','findings':0},
        'sql':{'legacy_preserved':len(legacy),'v2_shapes':len({shape(sql) for sql in all_statements()}),'total':len(catalog)},
        'R0_complete':False,'WP04_complete':False,'production_authentication_verified':False,
        'browser_or_global_performance_tested':False,'production_DB_or_server_restart_or_deploy':False,
        'real_mint_or_funds_or_chain_or_external_messages':False,
        'limits':['in-process credentials and injected TLS evidence are model fixtures, not actual IdP or TLS handshake',
            'software visibility signals do not prove biological attention','UI/renderer accessibility and withdrawal notifications pending',
            'persistent credentials, role/RLS, rate limits, key operations and recovery/load/release gates pending',
            'manual review resolution, full reporting/dispatch/adapter acceptance and real value gates pending'],
        'sha256':{str(path.relative_to(ROOT)):hashlib.sha256(path.read_bytes()).hexdigest() for path in files}}
    (OUT/'verification.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({'reproduced_failures_fixed':len(before),'passed':len(after),
        'legacy_http_passed':old_http['passed'],'R0_complete':False}))


if __name__=='__main__':
    main()
