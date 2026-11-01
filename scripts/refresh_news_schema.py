"""Refresh one explicitly reviewed news output contract; default is read-only.

Apply requires fresh, repeated source-bearing execution proof and a private,
durable original-row backup. This does not create production execution evidence.
"""
import argparse
import json
import os
from pathlib import Path
import sqlite3
import sys
import time

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from agent_market.capability_registry import (canonical, digest, full_tools,
    known_schema_failure, version_parts)
from agent_market.collector.usage import compact_tools, tools_hash
from agent_market.gateway.rag import load_sqlite_vec
from agent_market.workflow_templates import NEWS_URL
from scripts.replace_news_workflow import (Database, ReplacementError, private_backup,
    verified_bindings)

# These pins authorize only the reviewed 2026-10-19 output-schema change.
BEFORE = '763e4bfc17ac240d7b30527befca7a7b72ba4621eff55c667e47e7ca27df554a'
APPROVED = 'a9248326cb1f0f0ab82a96d9248b85290f99717f13917a36d4bec43e9938758e'
COMPACT = 'fcf170dd7f78d3a29880e5dfcc1ac5369e0f3676e14cb64f3fff52740683249c'
MAX_AGE = 1800


def differences(before, after, path=()):
    if isinstance(before, dict) and isinstance(after, dict):
        paths = []
        for key in before.keys() | after.keys():
            if key not in before or key not in after:
                paths.append(path + (key,))
            else:
                paths.extend(differences(before[key], after[key], path + (key,)))
        return paths
    if isinstance(before, list) and isinstance(after, list) and len(before) == len(after):
        return [item for i, pair in enumerate(zip(before, after))
                for item in differences(*pair, path + (i,))]
    return [] if before == after else [path]


def schema(resource):
    normalized = full_tools(json.loads(resource['usage_full_tools']))
    if digest(normalized) != resource['usage_full_hash']:
        raise ReplacementError('stored_full_schema_hash_mismatch')
    stored_compact = json.loads(resource['usage_tools'])
    if (tools_hash(stored_compact) != COMPACT or resource['usage_tools_hash'] != COMPACT
            or sorted(compact_tools(normalized),key=lambda item:item['name']) != sorted(stored_compact,key=lambda item:item['name'])):
        raise ReplacementError('compact_input_schema_changed')
    return normalized


def reviewed_proof(proof):
    verified = verified_bindings(proof)
    identity = verified['bindings']['news']
    rows = proof.query('SELECT * FROM resources WHERE key=?', (identity['key'],))
    if len(rows) != 1:
        raise ReplacementError('proof_resource_ambiguous')
    resource = dict(rows[0]); normalized = schema(resource)
    if resource['url'] != NEWS_URL or resource['usage_full_hash'] != APPROVED:
        raise ReplacementError('reviewed_schema_pin_required')
    meta = proof.query("SELECT value FROM meta WHERE key='reviewed_news_schema_v1'")
    expected = {'resource_key':resource['key'], 'url':NEWS_URL, 'before_full_hash':BEFORE,
        'approved_full_hash':APPROVED, 'compact_hash':COMPACT,
        'input_annotations_names_unchanged':True, 'reviewed_output_schema_paths':8}
    if len(meta) != 1 or json.loads(meta[0]['value']) != expected:
        raise ReplacementError('explicit_schema_review_required')
    binding, contract, profile, _ = version_parts(resource)
    version = 'cv_' + digest([resource['id'],binding,contract,profile])[:32]
    runs = proof.query("""SELECT id,snapshot,finished FROM workflow_runs
        WHERE status='succeeded' AND digest=? ORDER BY finished DESC LIMIT 2""",
        (verified['snapshot_digest'],))
    if len(runs) != 2 or any(not row['finished'] or not 0 <= time.time()-row['finished'] < MAX_AGE for row in runs):
        raise ReplacementError('two_fresh_matching_workflow_runs_required')
    # Validate source content independently in both actual runs, not only the latest.
    from agent_market.concierge.report_evidence import canonical_endpoint
    for run in runs:
        snapshot = json.loads(run['snapshot'])
        if (digest(snapshot) != verified['snapshot_digest'] or
                snapshot.get('bindings',{}).get('news',{}).get('connection_version_id') != version):
            raise ReplacementError('workflow_contract_pin_changed')
        outcomes = proof.query("SELECT node_id,status,attempts,output FROM workflow_node_runs WHERE run_id=? AND node_id IN ('news','research')", (run['id'],))
        if len(outcomes) != 2:
            raise ReplacementError('both_actual_nodes_required')
        for outcome in outcomes:
            output = json.loads(outcome['output']);items = output.get('items', []) if isinstance(output,dict) else []
            if (outcome['status'] != 'succeeded' or outcome['attempts'] != 1 or not 1 <= len(items) <= 3
                    or any(not isinstance(item,dict) or not item.get('title') or canonical_endpoint(item.get('url')) is None for item in items)):
                raise ReplacementError('source_backed_content_required')
    successes = proof.query("""SELECT 1 FROM capability_evidence WHERE version_id=?
        AND scope='execution' AND outcome='succeeded' AND finished>=? LIMIT 2""",
        (version,time.time()-MAX_AGE))
    if len(successes) != 2 or known_schema_failure(proof,resource):
        raise ReplacementError('repeated_current_contract_execution_required')
    return {'identity':identity, 'tools':normalized, 'approved':expected,
            'proof_digest':digest(verified), 'observed_at':runs[0]['finished']}


def plan(destination, proof):
    rows = destination.query('SELECT * FROM resources WHERE key=?', (proof['identity']['key'],))
    if len(rows) != 1:
        raise ReplacementError('destination_resource_missing_or_ambiguous')
    resource = dict(rows[0]);old = schema(resource)
    if (resource['kind'] != 'mcp' or resource['url'] != NEWS_URL or resource['active'] != 1
            or resource['eval_security'] in ('quarantine','review')):
        raise ReplacementError('security_or_binding_review_required')
    if resource['usage_full_hash'] == APPROVED:
        return {'eligible':False,'before':resource,'proof':proof}
    if resource['usage_full_hash'] != BEFORE:
        raise ReplacementError('unreviewed_existing_contract')
    paths = differences(old, proof['tools'])
    if len(paths) != 8 or any(len(path) < 2 or path[1] != 'outputSchema' for path in paths):
        raise ReplacementError('only_eight_reviewed_output_changes_allowed')
    marked = known_schema_failure(destination,resource)
    if resource['health_status'] != 'healthy' and not (resource['health_status'] == 'quarantined' and marked):
        raise ReplacementError('unrelated_health_failure_not_overridden')
    # Keep all policy gates; only the proven schema-specific health quarantine is lifted.
    from agent_market.concierge.execution_policy import admit, admit_tool
    from agent_market.workflow_templates import NEWS_TOOL, definitions
    candidate = {**resource,'health_status':'healthy',
        'usage_full_tools':canonical(proof['tools']),'usage_full_hash':APPROVED}
    admit(candidate,'mcp',public=True)
    admit_tool(candidate,NEWS_TOOL,definitions()[0]['nodes'][1]['data']['input'])
    return {'eligible':True,'before':resource,'proof':proof,'schema_quarantine':bool(marked and resource['health_status']=='quarantined')}


def refresh_news_schema(database, proof_db, *, apply=False, backup_directory=None):
    if os.path.samefile(database,proof_db):
        raise ReplacementError('proof_and_destination_must_differ')
    if apply and not backup_directory:
        raise ReplacementError('private_backup_directory_required')
    source = Database(proof_db);destination = Database(database)
    try:
        proof = reviewed_proof(source);initial = plan(destination,proof)
        destination.close();destination = None;changed = 0
        if apply and initial['eligible']:
            destination = Database(database,readonly=False)
            if destination.query("SELECT 1 FROM sqlite_master WHERE name='vec_resources'") and not load_sqlite_vec(destination.connection):
                raise ReplacementError('required_vector_extension_unavailable')
            destination.connection.execute('BEGIN IMMEDIATE')
            fresh = plan(destination,proof)
            if digest(fresh) != digest(initial):
                raise ReplacementError('destination_changed_since_preflight')
            private_backup(backup_directory,{'format':'reviewed-news-schema-v1',**fresh})
            updates = {'usage_full_tools':canonical(proof['tools']), 'usage_full_hash':APPROVED,
                       'eval_at':None, 'health_status':'healthy'}
            result = destination.connection.execute("""UPDATE resources SET usage_full_tools=?,
                usage_full_hash=?,eval_at=NULL,health_status='healthy' WHERE id=? AND usage_full_hash=?""",
                (updates['usage_full_tools'],APPROVED,fresh['before']['id'],BEFORE))
            actual = destination.resource(fresh['before']['id'])
            if result.rowcount != 1 or actual != {**fresh['before'],**updates}:
                raise ReplacementError('unexpected_update_result')
            destination.connection.commit();changed = 1
        return {'mode':'apply' if apply else 'dry_run','eligible':int(initial['eligible']),
            'changed':changed,'backup_created':bool(changed),
            'schema_quarantine_cleared':bool(changed and initial.get('schema_quarantine')),
            'security_assessment_modified':False,'execution_evidence_modified':0,
            'workflow_definitions_modified':0,'reviewed_output_schema_paths':8}
    finally:
        if destination is not None:destination.close()
        source.close()


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db',required=True);parser.add_argument('--proof-db',required=True)
    parser.add_argument('--apply',action='store_true');parser.add_argument('--backup-dir')
    args=parser.parse_args(argv)
    try:
        result=refresh_news_schema(args.db,args.proof_db,apply=args.apply,backup_directory=args.backup_dir)
    except ReplacementError as exc:
        print('News schema refresh refused: '+str(exc),file=sys.stderr);return 1
    except (OSError,sqlite3.Error,ValueError,TypeError,KeyError):
        print('News schema refresh refused: database_backup_or_proof_error',file=sys.stderr);return 1
    print(json.dumps(result,sort_keys=True));return 0


if __name__=='__main__':
    raise SystemExit(main())
