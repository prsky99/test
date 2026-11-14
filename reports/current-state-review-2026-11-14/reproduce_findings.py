"""Repeat the local audit counterexamples without network, signing keys or operating writes."""
import datetime
import json
from pathlib import Path
import tempfile
import time

from agent_market.necklaces import runner
from agent_market.necklaces.service import Refused, check_input
from scripts import data_quality as DQ, report_v2 as V
from tests.test_necklaces_runner import caller_from, necklace


def main():
    result = {'scope': 'isolated local mocks and temporary files; no network or operating DB'}
    definition = necklace()
    definition['budget_ms']['total'] = 1000
    start = time.monotonic()
    run = runner.Runner(caller_from({1: 'CVE-2021-23337', 3: 'listed in CISA KEV'}, delay=1.25)).run(definition, {'q': 'lodash'})
    result['deadline'] = {'budget_ms': 1000, 'elapsed_ms': round((time.monotonic() - start) * 1000), 'accepted_success': run['ok']}
    result['schema'] = []
    for name, rule, value in [('integer_minimum', {'type': 'integer', 'minimum': 1, 'maximum': 10}, -1),
                              ('number_finite', {'type': 'number'}, float('nan')),
                              ('array_type', {'type': 'array', 'items': {'type': 'string'}}, 'not-an-array')]:
        try:
            check_input({'type': 'object', 'properties': {'x': rule}, 'required': ['x'], 'additionalProperties': False}, {'x': value})
            accepted = True
        except Refused:
            accepted = False
        result['schema'].append({'case': name, 'accepted': accepted})
    now = datetime.datetime(2026, 11, 14, 13, 0).timestamp()
    result['data_freshness'] = {
        'stale_clock_points': DQ.freshness('timezone.time.v1', 'Local time is 00:00', now)[0],
        'old_news_new_retrieval_points': DQ.freshness('news.search.v1', 'Article published 2020-01-01. Retrieved 2026-11-14.', now)[0],
        'missing_expected_fields_points': DQ.completeness('', {'irrelevant': 'value'})[0],
    }
    with tempfile.TemporaryDirectory(prefix='current-state-audit-') as tmp:
        original_out, original_sign = V.OUT, V.sign_version
        V.OUT = Path(tmp)
        V.sign_version = lambda *args: None
        try:
            folder = V.version_dir(1, 'weather.forecast.v1')
            folder.mkdir(parents=True)
            for index, version in enumerate([
                {'tool': 'forecast', 'outcome': 'succeeded', 'tested': now - 86400, 'tool_fingerprint': 'old-contract', 'data_quality': {'accuracy': {'points': 0}}},
                {'tool': 'forecast', 'outcome': 'succeeded', 'tested': now, 'tool_fingerprint': 'new-contract', 'data_quality': {'accuracy': {'points': 25}}},
            ]):
                (folder / f'qualification-{index}.json').write_text(json.dumps(version))
            result['repeat_qualification'] = {'counted_success_days': V.success_days(1, 'weather.forecast.v1', 'forecast', now),
                                              'prior_accuracy_points': 0, 'contracts_different': True}
            ts = int(time.time())
            base = {'id': 2, 'role': 'weather.forecast', 'tool': 'forecast', 'outcome': 'failed', 'host': 'audit.example',
                    'arguments': {'city': 'Seoul'}, 'latency_ms': 1}
            first = V.save_version({**base, 'started': ts + 0.1, 'reason': 'first distinct attempt'})
            second = V.save_version({**base, 'started': ts + 0.2, 'reason': 'second distinct attempt'})
            files = list(V.version_dir(2, V.canonical(base['role'])).glob('*.json'))
            result['report_version_collision'] = {'versions_returned': [first['version'], second['version']], 'persisted_files': len(files)}
        finally:
            V.OUT, V.sign_version = original_out, original_sign
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
