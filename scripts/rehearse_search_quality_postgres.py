"""Run the same 300 synthetic tasks in a disposable PG18 owned schema.

Uses the existing reviewed local Unix-socket harness and schema escape guards.
Production GIN/HNSW indexes are intentionally excluded from this rehearsal.
"""
import argparse
import json
from pathlib import Path

from scripts import rehearse_b2a_retention_postgres as harness
from scripts.evaluate_search_workflow_quality import evaluate


def contracts(connect, store_factory):
    connection = connect()
    store = store_factory(connection, initialize=True, workflow_key=b'q'*32)
    try:
        result = evaluate(store)
        result['native_storage_used'] = True
        result['retrieval_backend'] = 'owned PostgreSQL rows with existing ephemeral FTS fallback'
        result['production_gin_hnsw_measured'] = False
        print(json.dumps({'native_tasks':result['unique_tasks'],'runs':result['runs'],'passed':result['passed']}),flush=True)
        if result['passed'] != result['runs']:
            raise AssertionError('Owned-schema quality acceptance did not pass.')
        return result
    finally:
        store.close()
        connection.close()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args=parser.parse_args()
    original=harness._contracts
    harness._contracts=contracts
    try: result=harness.schema_rehearsal()
    finally:harness._contracts=original
    args.output.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({'owned_schema_check_completed':True,'result_keys':list(result)}))
    return 0


if __name__=='__main__':raise SystemExit(main())
