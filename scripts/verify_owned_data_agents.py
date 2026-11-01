"""Run staged agents against real sources in a new disposable verification DB.

There is no --apply, operating DB argument, server launch or frontend mutation.
"""
import argparse
import hashlib
import json
from pathlib import Path
import time

from agent_market.owned_data_agents.catalog import SPECS
from agent_market.owned_data_agents.staging import bundle, TEST_IDS
from agent_market.owned_data_agents.verification import isolated_world, wait


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument('--live', action='store_true', required=True)
    parser.add_argument('--output', required=True, help='A new private report directory')
    args = parser.parse_args(argv)
    root = Path(args.output)
    root.mkdir(mode=0o700, parents=True, exist_ok=False)
    report = {'profile': 'owned-data-agents-live-verification-v1', 'applied': False,
              'operating_database_actions': 0, 'project_server_actions': 0,
              'source_transport': 'Actual verified public HTTPS',
              'mcp_transport': 'Isolated ASGI protocol handler; not an externally deployed MCP service',
              'agents': [], 'workflows': [], 'input_variants': [], 'completed': False}
    try:
        with isolated_world(root / 'isolated') as world:
            for identity, spec in SPECS.items():
                started = time.monotonic()
                rid = world.resources[identity]
                value = world.runtime.proxy.execute(rid, spec['tool'], spec['example'], public=True)
                ok = value.get('ok') is True
                report['agents'].append({'id': identity, 'ok': ok, 'testbench': identity in TEST_IDS,
                    'seconds': round(time.monotonic() - started, 3),
                    'output': value.get('result', {}).get('structuredContent'),
                    'error_code': value.get('error_code')})
            for workflow in world.workflows:
                run = wait(world.runtime, world.runtime.submit(workflow, source='verification',
                           actor='isolated-owned-data-verification', public=True))
                report['workflows'].append({'name': workflow['name'], 'status': run['status'],
                    'run_id': run['run_id'], 'nodes': run['node_results'],
                    'transfers': run.get('transfers', run.get('data_transfers', []))})
            variants = {
                'technology-news': {'query': 'quantum computing', 'limit': 3},
                'research-papers': {'query': 'quantum computing', 'limit': 3},
                'country-profile': {'country_code': 'GB'},
                'package-metadata': {'package': 'lodash'},
                'economic-indicators': {'country_code': 'GB', 'indicator': 'SP.POP.TOTL', 'limit': 3},
            }
            latest = next((row['output']['data']['version'] for row in report['agents']
                           if row['id'] == 'package-metadata' and row['ok']), None)
            if latest:
                variants['package-advisories'] = {'package': 'express', 'version': latest, 'limit': 3}
            else:
                report['input_variants'].append({'id': 'package-advisories', 'ok': False,
                    'source_results_changed': False, 'reason': 'The upstream package version was unavailable.'})
            for identity, arguments in variants.items():
                value = world.runtime.proxy.execute(world.resources[identity], SPECS[identity]['tool'], arguments, public=True)
                output = value.get('result', {}).get('structuredContent')
                original = next(row['output'] for row in report['agents'] if row['id'] == identity)
                before = original['data'].get('items', original['data']) if original else None
                after = output['data'].get('items', output['data']) if output else None
                report['input_variants'].append({'id': identity, 'arguments': arguments,
                    'ok': value.get('ok') is True, 'source_results_changed': before != after, 'output': output})
            report['completed'] = (all(row['ok'] for row in report['agents'])
                                   and all(row['status'] == 'succeeded' for row in report['workflows'])
                                   and all(row['ok'] and row['source_results_changed'] for row in report['input_variants']))
        staged = bundle()
        (root / 'staged-bundle.json').write_text(json.dumps(staged, indent=2))
        report['staged_bundle_sha256'] = hashlib.sha256((root / 'staged-bundle.json').read_bytes()).hexdigest()
    finally:
        (root / 'verification.json').write_text(json.dumps(report, indent=2))
    print(json.dumps({'completed': report['completed'], 'agents': len(report['agents']),
                      'workflows': len(report['workflows']), 'applied': False}))
    return 0 if report['completed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
