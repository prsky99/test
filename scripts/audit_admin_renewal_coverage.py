"""Read-only migration inventory; static reachability is not functional acceptance."""
import argparse
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GATEWAY = ROOT / 'agent_market/gateway'
NEW = GATEWAY / 'admin_next'
# Appendix B order: equivalent capabilities count, not removal of the original file.
GROUPS = [
 ('기반·운영', ['workspace-admin','workspace-operations'], 'migrated', '직원 멤버십·초안·저장본·별도 실행, 고객·조직·지원·사고 관리 이전; 운영 반영은 별도 확인'),
 ('실행·근거', ['workspace-flow','workspace-typed-evidence','workspace-evidence','workflow-quality'], 'migrated', '전문 관리 1차'),
 ('배포·릴리스', ['workspace-release','workspace-typed-release','workspace-machine-updates'], 'migrated', '전문 관리 2차; 운영 반영은 별도 확인'),
 ('원격 규격', ['workspace-remote-a2a','workspace-protocol-conformance'], 'migrated', '전문 관리 3차; 운영 반영은 별도 확인'),
 ('신뢰성·연구', ['workspace-reliability','workspace-reliability-controls','workspace-reliability-research','workspace-research-controls'], 'migrated', '전문 관리 4차; 운영 반영은 별도 확인'),
 ('성장·제품', ['workspace-growth','advancement','workspace-product'], 'migrated', '전문 관리 5차; 운영 반영은 별도 확인'),
 ('합의·신원', ['workspace-agreement','workspace-identity'], 'migrated', '전문 관리 6차; 운영 반영은 별도 확인'),
 ('크레딧', ['customer-credits'], 'migrated', '잔액·가입 동의·서명 이력과 검토된 정정; 원본에 별도 유료 플랜 설정은 없음'),
 ('개인정보', ['privacy-review'], 'migrated', '원본 개인정보 검토·완료 상태 고정·근거 보완·최신 조회 이전; 연락처 재동의는 별도 정책'),
]


def inspect():
    html = (GATEWAY/'dashboard.html').read_text()
    tabs = json.loads(re.search(r'const TABS = (\[.*?\]);', html).group(1))
    links = []
    for file in sorted(NEW.rglob('*.js')) + [NEW/'index.html']:
        if file.name == 'legacy.js':
            continue  # Unused fallback module, not loaded by the current area router.
        source = file.read_text()
        targets = set(re.findall(r"/admin/ui#([a-z_]+)", source))
        if file.name == 'system.js' and '/admin/ui#' in source:
            block = re.search(r'const links = (\[.*?\]);', source).group(1)
            targets.update(re.findall(r"\['[^']+', '([^']+)'\]", block))
        for target in sorted(targets):
            links.append({'source':str(file.relative_to(ROOT)), 'href':'/admin/ui#'+target,
                          'target_exists':target in tabs and f'data-panel="{target}"' in html})
    panels = []
    for group, names, status, note in GROUPS:
        for name in names:
            filename=name+'-admin.js' if name!='workspace-admin' else 'workspace-admin.js'
            # These two older names already end in "admin" or use a dedicated operations asset.
            if name=='workspace-operations':
                filename='workspace-operations-admin.js'
            path=GATEWAY/filename
            panels.append({'name':name,'group':group,'status':status,'note':note,'legacy_asset':str(path.relative_to(ROOT)),
                           'asset_exists':path.is_file(),'legacy_script_referenced':('/admin/assets/'+filename) in html,
                           'entry':'/admin/ui#'+('customer_credits' if name=='customer-credits' else 'needs' if name=='privacy-review' else 'workspace_operations' if name=='workspace-operations' else 'workspaces')})
    return {'scope':'Static source inventory for design appendices A/B; not authenticated runtime acceptance',
            'legacy_tabs':tabs,'legacy_shell':'/admin/ui','links':links,'panels':panels,
            'counts':{state:sum(p['status']==state for p in panels) for state in ('migrated','partial','legacy')},
            'invalid_links':[x for x in links if not x['target_exists']],
            'missing_assets':[x['name'] for x in panels if not x['asset_exists'] or not x['legacy_script_referenced']]}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path)
    args=parser.parse_args()
    report=inspect()
    if args.output:
        args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({'panels':len(report['panels']),'counts':report['counts'],'links':len(report['links']),
                      'invalid_links':report['invalid_links'],'missing_assets':report['missing_assets']},ensure_ascii=False))
    return int(bool(report['invalid_links'] or report['missing_assets']))

if __name__=='__main__':
    raise SystemExit(main())
