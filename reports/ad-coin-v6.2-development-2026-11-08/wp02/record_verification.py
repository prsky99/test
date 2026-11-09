"""Record current WP-02 evidence without modifying prior-stage results."""
from pathlib import Path
import hashlib
import json
import subprocess
import sys
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))


def main():
    from agent_market.ad_coin.sql_registry import check, shape
    from agent_market.ad_coin.v2.schema import statements
    from agent_market.ad_coin.v2.sql import all_statements

    cases = list(ET.parse(OUT/'regression.xml').getroot().iter('testcase'))
    assert len(cases) == 78
    assert all(all(case.find(tag) is None for tag in ('failure', 'error', 'skipped')) for case in cases)
    counts = {}
    for case in cases:
        name = case.get('classname')
        counts[name] = counts.get(name, 0) + 1
    dynamic = json.loads((OUT/'http-security/dynamic-security.json').read_text())['summary']
    assert dynamic['checks'] == dynamic['passed'] == 219 and dynamic['failed'] == 0
    findings = json.loads((OUT/'secure-coding.json').read_text())
    assert findings == []
    baseline = json.loads(subprocess.run(
        ['git', 'show', 'HEAD:agent_market/ad_coin/sql_registry.json'], cwd=ROOT,
        check=True, capture_output=True, text=True, timeout=10).stdout)
    current = json.loads((ROOT/'agent_market/ad_coin/sql_registry.json').read_text())
    assert {r['sql'] for r in baseline['statements']} <= {r['sql'] for r in current['statements']}
    catalog = tuple(all_statements())
    for statement in catalog:
        check(statement)
    assert not any('sqlite' in statement.lower() or 'aiac_uint' in statement for statement in catalog)
    files = [*sorted((ROOT/'agent_market/ad_coin/v2').glob('*.py')),
        ROOT/'agent_market/ad_coin/v2/p1_contract.json', ROOT/'agent_market/ad_coin/sql_registry.json',
        ROOT/'scripts/ad_coin_sql_registry.py', ROOT/'tests/test_ad_coin_v2_persistence.py',
        ROOT/'docs/AD_COIN.md', ROOT/'docs/AD_COIN_V6_2_DETAILED_DESIGN.md',
        ROOT/'docs/AD_COIN_PLATFORM_DATA_API.md', ROOT/'docs/AD_COIN_PLATFORM_IMPLEMENTATION_PLAN.md',
        ROOT/'docs/AD_COIN_ARCHITECTURE.md', ROOT/'docs/ad_coin_v6_2_detail/02-storage-transactions.md',
        OUT.parent/'PROGRESS.md', OUT/'regression.xml', OUT/'regression.log',
        OUT/'http-security/dynamic-security.json', OUT/'secure-coding.json', Path(__file__)]
    report = {
        'profile': 'ai-ad-coin-v6.2-wp02-model-foundation', 'date_kst': '2026-11-08',
        'postgres_only': True, 'model_only': True, 'v2_tables': sum(s.startswith('CREATE TABLE') for s in statements()),
        'unit_regression': {'passed': len(cases), 'failed': 0, 'skipped': 0, 'by_file': counts,
                            'deselected': ['legacy v1 SQLite import test']},
        'legacy_v1_HTTP_security': dynamic, 'v2_HTTP_or_browser_tested': False,
        'static_security': {'tool': 'Ruff S rules', 'findings': len(findings), 'scope': 'ad_coin/api.py and v2'},
        'sql_catalog': {'legacy_preserved': len(baseline['statements']),
                        'v2_shapes': len({shape(s) for s in catalog}), 'total': len(current['statements'])},
        'R0_complete': False, 'v2_router_mounted': False, 'real_value_activated': False,
        'deployment_or_user_server_restart': False, 'production_DB_access': False,
        'superseded_evidence': ['sqlite.xml', 'persistence.xml'],
        'remaining': ['credential/session/membership adapters', 'advertiser campaign/review/approval handlers',
            'delivery eligibility/evidence/budget/attention integration', '29 v2 HTTP handlers and user interfaces',
            'receipt signing and report workers', 'least-privilege DB roles and recovery/load/release gates',
            'actual funding, custody, chain, redemption and external payment'],
        'sha256': {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in files},
    }
    (OUT/'verification.json').write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n')
    print(json.dumps({'passed':len(cases), 'http_passed':dynamic['passed'],
                      'postgres_only':True, 'R0_complete':False}))


if __name__ == '__main__':
    main()
