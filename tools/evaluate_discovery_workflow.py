"""Offline meaning/plan evaluation, without models, network or application DB.

This fixture runner measures semantic regressions, not live-provider quality or
production latency. Compare runs only with the same input and source hashes.
"""
import argparse
import hashlib
import json
from pathlib import Path
import time

from agent_market.capability_contracts import CONTRACTS
from agent_market.concierge.query_intent import interpret
from agent_market.concierge.workflow_discovery import relevance
from agent_market.workflow_goal_policy import validate_query
from agent_market.workflow_model_proposer import compile_proposal
from agent_market.workspace_access import WorkspaceInvalid
from agent_market.workspace_app_factory import MODEL_PROFILE, MODEL_OUTPUT_PROFILE, MODEL_CONTRACTS


def context(objective):
    return {'profile': MODEL_PROFILE, 'objective': objective,
            'candidates': [{'resource_id': 17, 'contract_id': 'docs.search.v1'},
                           {'resource_id': 23, 'contract_id': 'news.search.v1'}],
            'contracts': {key: {'input_schema': CONTRACTS[key]['input_schema'],
                                'output_schema': CONTRACTS[key]['output_schema']} for key in MODEL_CONTRACTS},
            'limits': {'minimum_nodes': 2, 'maximum_nodes': 10}, 'output_profile': MODEL_OUTPUT_PROFILE}


def assess(case):
    profile = case['profile']
    if profile == 'intent':
        value = interpret(case['input'])
        return (all(t.casefold() in value.positive.casefold() for t in case.get('preserve', []))
                and all(t.casefold() not in value.positive.casefold() for t in case.get('exclude', [])))
    if profile == 'template':
        return (relevance(case['template'], case['input']) > 0) == case['expected_match']
    if profile == 'topic':
        try: validate_query({'objective': case['input']}, case['query'])
        except WorkspaceInvalid: return case['expected'] == 'rejected'
        return case['expected'] == 'accepted'
    if profile == 'workflow':
        try: value = compile_proposal(context(case['input']), case['proposal'])
        except WorkspaceInvalid: return case['expected'] == 'rejected'
        if case['expected'] != 'accepted': return False
        nodes = value['nodes']
        if [n['contract_id'] for n in nodes] != case['contracts']:
            return False
        return not case.get('independent') or all(not n['after'] and not n['bindings'] for n in nodes)
    raise ValueError('Unknown evaluation profile.')


def run(cases):
    if type(cases) is not list or not 1 <= len(cases) <= 300:
        raise ValueError('Provide one to 300 synthetic cases.')
    rows = []
    for case in cases:
        if type(case) is not dict or type(case.get('name')) is not str or len(case['name']) > 120:
            raise ValueError('Each case needs a bounded name.')
        started = time.perf_counter()
        passed = assess(case)
        rows.append({'name': case['name'], 'profile': case['profile'], 'passed': passed,
                     'milliseconds': round((time.perf_counter()-started)*1000, 1)})
    return {'scope': 'offline_synthetic_meaning_and_plan_checks', 'production_slo_measured': False,
            'provider_calls': 0, 'model_calls': 0, 'cases': len(rows),
            'passed': sum(row['passed'] for row in rows), 'results': rows}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cases', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    raw = args.cases.read_bytes()
    if len(raw) > 1024*1024: raise ValueError('Evaluation input exceeds the bounded size.')
    payload = json.loads(raw)
    result = run(payload['cases'])
    result['input_sha256'] = hashlib.sha256(raw).hexdigest()
    root = Path(__file__).resolve().parents[1]
    files = ['concierge/query_intent.py', 'concierge/workflow_discovery.py',
             'workflow_goal_policy.py', 'workflow_goal_evaluation.py', 'workflow_model_proposer.py']
    result['source_sha256'] = {name: hashlib.sha256((root/'agent_market'/name).read_bytes()).hexdigest() for name in files}
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2)+'\n')
    print(json.dumps({key: result[key] for key in ('scope','cases','passed','provider_calls','model_calls')}))
    return 0 if result['passed'] == result['cases'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
