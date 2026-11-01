"""Read-only step 9 inventory. This tool cannot authorize or execute retirement.

Static references, intact packages and passing tests do not prove 30 days of
zero use, absence of customer deployments, or a successful operating restore.
Missing evidence is unknown, never zero. No database or request logs are read.
"""
import argparse
import ast
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re

from scripts.audit_admin_renewal_coverage import inspect as coverage_inventory

ROOT = Path(__file__).resolve().parents[1]
RELEASE = re.compile(r'[a-zA-Z0-9][a-zA-Z0-9_.-]{0,79}\Z')
SDK_MODULES = {'admin_workflow_webapp', 'admin_workflow_webapp_v12',
               'workflow_apps', 'workflow_apps_v12'}


def _json(path):
    if path.is_symlink() or path.stat().st_size > 4 * 1024 * 1024:
        raise ValueError('unsafe_or_oversized_metadata')
    return json.loads(path.read_text())


def release_inventory(root):
    """Verify referenced package files without Deployment(), launchctl or writes."""
    directory = root / 'gateway-data/services'
    result = {'status': 'unverified', 'slots': [], 'rollback_rehearsal': 'unverified'}
    try:
        state = _json(directory / 'state.json')
        admin = state['services']['admin']
        if admin['active'] not in ('a', 'b'):
            raise ValueError('invalid_slot')
        result['active'] = admin['active']
        result['phase'] = state.get('phase')
        for slot in ('a', 'b'):
            release = admin['slots'].get(slot)
            if not isinstance(release, str) or not RELEASE.fullmatch(release) or release in ('.', '..'):
                raise ValueError('invalid_release')
            package = directory / 'releases' / release
            if package.resolve() != package.absolute():
                raise ValueError('symlinked_package')
            manifest = _json(package / 'release.json')
            hashes = manifest['sha256']
            if manifest['release'] != release or not isinstance(hashes, dict) or not 1 <= len(hashes) <= 10000:
                raise ValueError('invalid_manifest')
            mismatches = 0
            for name, expected in hashes.items():
                relative = Path(name)
                path = package / relative
                if (relative.is_absolute() or '..' in relative.parts or
                        path.resolve() != path.absolute() or
                        not isinstance(expected, str) or not re.fullmatch(r'[0-9a-f]{64}', expected)):
                    raise ValueError('unsafe_manifest_entry')
                # Never read credential/dependency paths through a forged manifest.
                allowed = relative.parts and relative.parts[0] in ('agent_market', 'scripts', 'new')
                allowed |= name in ('service_entry.py', 'requirements.txt', 'pyproject.toml', 'extracted_html.txt')
                allowed &= (relative.suffix in ('.py', '.json', '.svg', '.js', '.md', '.css', '.html',
                                               '.txt', '.lock', '.png', '.zip', '.toml') and
                            (all(not part.startswith('.') and part != 'gateway-data' for part in relative.parts)
                             or name == 'new/.publication.lock' and path.stat().st_size == 0))
                if not allowed or not path.is_file() or path.stat().st_size > 16 * 1024 * 1024:
                    raise ValueError('unsupported_manifest_entry')
                mismatches += hashlib.sha256(path.read_bytes()).hexdigest() != expected
            result['slots'].append({'slot': slot, 'release': release,
                                    'files': len(hashes), 'mismatches': mismatches})
        result['distinct_packages'] = len({row['release'] for row in result['slots']}) == 2
        result['status'] = ('intact_packages_only' if result['distinct_packages'] and
                            all(row['mismatches'] == 0 for row in result['slots']) else 'not_intact')
        if state != _json(directory / 'state.json'):
            result['status'] = 'changed_during_check'
        elif state.get('phase') not in ('stable', 'retained'):
            result['status'] = 'transition_in_progress'
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        result['status'] = 'unverified'
        result['error'] = 'Incomplete, invalid or unreadable package evidence.'
    return result


def source_inventory(root):
    routes, sdk, errors = [], [], []
    for folder in ('agent_market', 'scripts'):
        for file in sorted((root / folder).rglob('*.py')):
            relative = str(file.relative_to(root))
            try:
                tree = ast.parse(file.read_text())
            except (OSError, SyntaxError, UnicodeError):
                errors.append(relative)
                continue
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom):
                    modules = {node.module.rsplit('.', 1)[-1]} if node.module else {x.name for x in node.names}
                elif isinstance(node, ast.Import):
                    modules = {x.name.rsplit('.', 1)[-1] for x in node.names}
                else:
                    modules = set()
                for module in sorted(modules & SDK_MODULES):
                    sdk.append({'source': relative, 'line': node.lineno, 'module': module})
                if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                for decorator in node.decorator_list:
                    if (not isinstance(decorator, ast.Call) or not isinstance(decorator.func, ast.Attribute)
                            or decorator.func.attr not in ('get', 'post', 'put', 'patch', 'delete', 'head', 'options')
                            or not decorator.args or not isinstance(decorator.args[0], ast.Constant)):
                        continue
                    route = decorator.args[0].value
                    if isinstance(route, str) and route.startswith('/admin/api/') and not route.startswith('/admin/api/v2/'):
                        routes.append({'source': relative, 'line': node.lineno,
                                       'method': decorator.func.attr.upper(), 'template': route})
    references = []
    for file in sorted((root / 'agent_market/gateway/admin_next').rglob('*.js')):
        if file.name == 'legacy.js':
            continue  # Unloaded fallback module is not a current caller.
        try:
            source = file.read_text()
        except (OSError, UnicodeError):
            errors.append(str(file.relative_to(root)))
            continue
        count = len(re.findall(r'/admin/api/(?!v2/)', source))
        if count:
            references.append({'source': str(file.relative_to(root)), 'literal_occurrences': count})
    return {'legacy_route_definitions': routes, 'legacy_api_literal_references': references,
            'sdk_imports': sdk, 'parse_errors': errors,
            'limits': 'Static potential dependencies, not call counts or complete dynamic reachability.'}


def inspect_retirement(root=ROOT, *, coverage=None):
    root = Path(root).resolve()
    coverage = coverage_inventory() if coverage is None else coverage
    sources = source_inventory(root)
    packages = release_inventory(root)
    # Deliberately no --force, time-only gate, declaration-based approval or delete.
    common = ['continuous_30_day_usage_not_verified', 'restore_and_rollback_acceptance_not_verified']
    candidates = [
        {'id': 'legacy_shell_and_assets', 'blockers': common + ['existing_shell_links_and_source_dependencies']},
        {'id': 'legacy_admin_api', 'blockers': common + ['new_ui_still_references_legacy_api_including_auth']},
        {'id': 'admin_webapp_v1', 'blockers': common + ['sdk_consumers_and_deployment_inventory_require_review']},
        {'id': 'admin_webapp_v12', 'blockers': common + ['sdk_consumers_and_deployment_inventory_require_review']},
        {'id': 'old_sqlite_archives', 'blockers': common + ['archive_inventory_and_restoration_not_verified']},
    ]
    return {'checked_at': datetime.now(timezone.utc).isoformat(),
            'status': 'retention_required', 'decision': 'retain_all',
            'scope': 'Step 9 evidence inventory only; no retirement authorized.',
            'required_observation_days': 30, 'verified_continuous_observation_days': None,
            'eligible_for_removal': [], 'operating_mutations': 0,
            'coverage': {key: coverage[key] for key in ('counts', 'links', 'invalid_links', 'missing_assets')},
            'sources': sources, 'admin_packages': packages, 'candidates': candidates,
            'limitations': ['Request logs, customer deployments and database contents were not accessed.',
                           'Package hashes do not establish running-process health, a restore or a rollback rehearsal.',
                           'Elapsed calendar time and absence of sampled requests cannot prove zero use.',
                           'This inventory cannot approve future deletion; review complete evidence per target.']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, help='Optional new report file; existing files are not overwritten.')
    args = parser.parse_args()
    report = inspect_retirement()
    if args.output:
        with args.output.open('x') as stream:
            json.dump(report, stream, ensure_ascii=False, indent=2)
            stream.write('\n')
    print(json.dumps({'status': report['status'], 'eligible_for_removal': [],
                      'legacy_links': len(report['coverage']['links']),
                      'route_definitions': len(report['sources']['legacy_route_definitions']),
                      'new_ui_sources_with_legacy_api_literals': len(report['sources']['legacy_api_literal_references']),
                      'admin_packages': report['admin_packages']['status']}, ensure_ascii=False))
    # 2 means deferred, not deleted or fully accepted. Never emit success for a hold.
    return 2


if __name__ == '__main__':
    raise SystemExit(main())
