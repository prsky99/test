"""Record commercial model implementation evidence without replacing earlier runs."""
from pathlib import Path
import hashlib
import json
import subprocess
import sys
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))


def results(path):
    cases = list(ET.parse(path).getroot().iter('testcase'))
    assert all(all(case.find(tag) is None for tag in ('failure', 'error', 'skipped')) for case in cases)
    return {(case.get('classname'), case.get('name')) for case in cases}


def main():
    from agent_market.ad_coin.sql_registry import check, shape
    from agent_market.ad_coin.v2.commercial import READS, WRITES
    from agent_market.ad_coin.v2.schema import VERSION, statements
    from agent_market.ad_coin.v2.sql import all_statements
    cases, followup = results(OUT/'regression.xml'), results(OUT/'http-final.xml')
    assert len(cases) == 120 and len(followup) == 3 and followup <= cases
    counts = {}
    for module, _ in cases:
        counts[module] = counts.get(module, 0) + 1
    legacy = json.loads((OUT/'legacy-http-security/dynamic-security.json').read_text())['summary']
    assert legacy['checks'] == legacy['passed'] == 219 and legacy['failed'] == 0
    findings = json.loads((OUT/'secure-coding.json').read_text())
    assert findings == []
    baseline = json.loads(subprocess.run(
        ['git', 'show', 'HEAD:agent_market/ad_coin/sql_registry.json'], cwd=ROOT,
        check=True, capture_output=True, text=True, timeout=10).stdout)
    current = json.loads((ROOT/'agent_market/ad_coin/sql_registry.json').read_text())
    assert {row['sql'] for row in baseline['statements']} <= {row['sql'] for row in current['statements']}
    for statement in all_statements():
        check(statement)
        assert 'sqlite' not in statement.lower()
    files = [*sorted((ROOT/'agent_market/ad_coin/v2').glob('*.py')),
        ROOT/'agent_market/ad_coin/v2/p1_contract.json', ROOT/'agent_market/ad_coin/sql_registry.json',
        ROOT/'tests/test_ad_coin_v2_commercial.py', ROOT/'scripts/ad_coin_sql_registry.py',
        ROOT/'docs/AD_COIN.md', ROOT/'docs/AD_COIN_PLATFORM_IMPLEMENTATION_PLAN.md',
        ROOT/'docs/ad_coin_v6_2_detail/02-storage-transactions.md',
        ROOT/'docs/ad_coin_v6_2_detail/03-api-handlers.md', OUT.parent/'PROGRESS.md',
        OUT/'regression.xml', OUT/'regression.log', OUT/'http-final.xml', OUT/'http-final.log',
        OUT/'secure-coding.json', OUT/'legacy-http-security/dynamic-security.json', Path(__file__)]
    report = {
        'profile': 'ai-ad-coin-v6.2-wp03-commercial-model', 'date_kst': '2026-11-08',
        'postgres_only': True, 'model_schema_version': VERSION,
        'model_tables': sum(s.startswith('CREATE TABLE') for s in statements()),
        'implemented_partial_router_operations': sorted(READS | WRITES),
        'challenge_actions_implemented': ['approve_campaign'],
        'regression': {'passed': len(cases), 'failed': 0, 'skipped': 0, 'by_file': counts,
                       'deselected': ['legacy v1 SQLite import test']},
        'final_http_followup': {'passed': len(followup), 'subset_of_regression': True},
        'actual_localhost_v2_HTTP_flow': 'test_live_localhost_http_complete_commercial_flow',
        'authentication_fixture_limits': 'Server-created model principals/CSRF/TLS evidence; no actual IdP, token verification or certificate handshake tested.',
        'legacy_v1_HTTP_security': legacy,
        'static_security': {'tool': 'Ruff S', 'findings': len(findings), 'scope': 'ad_coin/api.py and v2'},
        'sql_catalog': {'legacy_preserved': len(baseline['statements']),
                        'v2_shapes': len({shape(s) for s in all_statements()}), 'total': len(current['statements'])},
        'R0_complete': False, 'WP03_release_complete': False, 'production_router_mounted': False,
        'user_server_restart_or_deployment': False, 'production_DB_access': False,
        'real_funding_or_chain_or_external_messages': False, 'UI_or_browser_tested': False,
        'remaining': ['real session/SSO/reviewer credential and TLS adapter', 'organization/agent binding onboarding and advertiser UI',
            '20 remaining operations and other human challenge purposes', 'P1 consent/evidence/funded reward integration',
            'receipt/report and dispatch workers', 'least-privilege DB roles, key management, recovery, rate-limit and performance release gates'],
        'sha256': {str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest() for path in files},
    }
    (OUT/'verification.json').write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n')
    print(json.dumps({'regression_passed':len(cases), 'router_operations':len(READS | WRITES),
                      'legacy_HTTP_passed':legacy['passed'], 'R0_complete':False}))


if __name__ == '__main__':
    main()
