"""Replace only the unchanged legacy news definition, preserving its ID and history.

Default is read-only dry run. Apply requires recent successful content-bearing
execution proof in a separate SQLite database and a durable private row backup.
"""
import argparse
import copy
import datetime
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import stat
import sys
import time
import uuid

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from agent_market.concierge.execution_policy import ExecutionDenied, admit, admit_tool
from agent_market.concierge.report_evidence import canonical_endpoint
from agent_market.workflow_templates import VERSION, definitions, bind_resources
from agent_market.workflows import public_template

SEED_KEY = VERSION + ':daily-tech-research'
OLD_URL = 'https://agent-pulse-seven.vercel.app/mcp'


class ReplacementError(ValueError):
    """Fixed operator-facing codes, without provider data or credentials."""


def packed(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)


def digest(value):
    return hashlib.sha256(packed(value).encode()).hexdigest()


class Database:
    def __init__(self, path, *, readonly=True):
        self.connection = sqlite3.connect(Path(path).resolve().as_uri()+
            ('?mode=ro' if readonly else '?mode=rw'), uri=True, timeout=2)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute('PRAGMA busy_timeout=2000')
        if readonly:
            self.connection.execute('PRAGMA query_only=ON')
            self.connection.execute('BEGIN')

    def query(self, sql, parameters=()):
        return self.connection.execute(sql, parameters).fetchall()

    def resource(self, rid):
        rows = self.query('SELECT * FROM resources WHERE id=?', (rid,))
        return dict(rows[0]) if rows else None

    def close(self):
        self.connection.close()


def legacy_definition():
    recipe = definitions()[0]
    recipe['description'] = 'Retrieve recent technology news and AI research with source links and publication dates.'
    fields = {'title':'title','summary':'body','url':'url','source':'source.name','published_at':'source.publishedAt'}
    for node, kind in zip(recipe['nodes'][1:], ('NEWS', 'RESEARCH')):
        if kind == 'RESEARCH':
            node['name'] = 'Recent AI Research'
        node['data'] = {'resource_ref':{'kind':'mcp','url':OLD_URL}, 'action':'get_latest_signals',
            'input':{'topic':'technology','type':kind,'limit':3},
            'output_select':{'path':'structuredContent.signals','fields':fields,'limit':3,'max_text':3200}}
    return recipe


def graph_without_local_ids(workflow):
    graph = copy.deepcopy({'nodes':workflow['nodes'], 'edges':workflow['edges']})
    for node in graph['nodes']:
        node.pop('resource_id', None)
        node.get('data', {}).pop('resource_id', None)
    return graph


def stored_workflow(db):
    rows = db.query('''SELECT w.* FROM agent_workflows w JOIN workflow_seed_registry s
        ON s.workflow_id=w.id WHERE s.seed_key=?''', (SEED_KEY,))
    if len(rows) != 1:
        raise ReplacementError('news_seed_missing_or_ambiguous')
    result = dict(rows[0])
    graph = json.loads(result['steps'])
    if not isinstance(graph, dict) or not isinstance(graph.get('nodes'), list):
        raise ReplacementError('unsupported_stored_graph')
    result.update(nodes=graph['nodes'], edges=graph.get('edges', []))
    return result


def verified_bindings(proof):
    workflow = stored_workflow(proof)
    expected = definitions()[0]
    expected['id'] = workflow['id']
    expected = bind_resources(proof, expected)
    projected = public_template(expected)
    rows = proof.query("SELECT id,snapshot,finished FROM workflow_runs WHERE workflow_id=? AND status='succeeded' ORDER BY finished DESC LIMIT 1", (workflow['id'],))
    if not rows or not rows[0]['finished'] or not 0 <= time.time()-rows[0]['finished'] < 86400:
        raise ReplacementError('recent_successful_proof_required')
    run = dict(rows[0]);snapshot = json.loads(run['snapshot'])
    fields = ('nodes','edges','name','description','category','trigger_type')
    if not any(all(snapshot.get(key) == candidate.get(key) for key in fields)
               for candidate in (expected, projected)):
        raise ReplacementError('proof_definition_changed')
    outcomes = {row['node_id']:dict(row) for row in proof.query(
        'SELECT node_id,status,attempts,output FROM workflow_node_runs WHERE run_id=?', (run['id'],))}
    result = {}
    for node, reference in zip(snapshot['nodes'][1:], definitions()[0]['nodes'][1:]):
        outcome = outcomes.get(node['id'])
        if not outcome or outcome['status'] != 'succeeded' or outcome['attempts'] != 1:
            raise ReplacementError('actual_node_execution_required')
        output = json.loads(outcome['output'])
        items = output.get('items', []) if isinstance(output, dict) else []
        if (not 1 <= len(items) <= 3 or any(not isinstance(item,dict) or not item.get('title')
                or canonical_endpoint(item.get('url')) is None for item in items)):
            raise ReplacementError('source_backed_content_required')
        resource = proof.resource(node.get('resource_id') or node['data'].get('resource_id'))
        binding = snapshot.get('bindings', {}).get(node['id'], {})
        if (not resource or resource['url'] != reference['data']['resource_ref']['url'] or
                resource['usage_tools_hash'] != binding.get('usage_tools_hash') or
                hashlib.sha256(resource['url'].encode()).hexdigest() != binding.get('url_hash')):
            raise ReplacementError('proof_connection_changed')
        try:
            admit(resource, 'mcp', public=True)
            admit_tool(resource, reference['data']['action'], reference['data']['input'])
        except ExecutionDenied:
            # A changed or unverifiable pinned contract refuses the replacement, never executes.
            raise ReplacementError('proof_contract_not_admitted') from None
        result[node['id']] = {'key':resource['key'], 'url':resource['url'],
            'usage_tools_hash':resource['usage_tools_hash'], 'usage_full_hash':resource.get('usage_full_hash')}
    return {'bindings':result, 'run_id':run['id'], 'snapshot_digest':digest(snapshot)}


def plan(db, proof):
    current = stored_workflow(db);expected_old = legacy_definition();replacement = definitions()[0]
    for key in ('name','category','trigger_type','tags','is_active','is_template'):
        if current.get(key) != expected_old.get(key):
            raise ReplacementError('legacy_definition_was_edited')
    original = {key:value for key,value in current.items() if key not in ('nodes','edges')}
    # Already current is a no-op; never rotate IDs or overwrite a saved variation.
    rebound = copy.deepcopy(replacement)
    for node in rebound['nodes'][1:]:
        identity = proof['bindings'][node['id']]
        rows = db.query('SELECT * FROM resources WHERE key=?', (identity['key'],))
        if len(rows) != 1:
            raise ReplacementError('replacement_resource_missing')
        resource = dict(rows[0])
        if (resource['url'] != identity['url'] or resource['usage_tools_hash'] != identity['usage_tools_hash']
                or resource.get('usage_full_hash') != identity['usage_full_hash']):
            raise ReplacementError('replacement_connection_changed')
        admit(resource, 'mcp', public=True)
        admit_tool(resource, node['data']['action'], node['data']['input'])
        node['resource_id'] = node['data']['resource_id'] = resource['id']
    if graph_without_local_ids(current) != graph_without_local_ids(expected_old):
        if (current['nodes'] == rebound['nodes'] and current['edges'] == rebound['edges'] and
                current['description'] == replacement['description']):
            return {'eligible':False,'before':original,'replacement':rebound,'proof':proof}
        raise ReplacementError('legacy_graph_was_edited')
    if current['description'] != expected_old['description']:
        raise ReplacementError('legacy_definition_was_edited')
    for node in current['nodes'][1:]:
        resource = db.resource(node.get('resource_id') or node['data'].get('resource_id'))
        if not resource or resource['kind'] != 'mcp' or resource['url'] != OLD_URL:
            raise ReplacementError('legacy_binding_changed')
    return {'eligible':True,'before':original,'replacement':rebound,'proof':proof}


def private_backup(directory, value):
    path = Path(directory).absolute();path.mkdir(mode=0o700, exist_ok=True)
    info = path.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o700:
        raise ReplacementError('private_backup_directory_required')
    directory_fd = os.open(path, os.O_RDONLY | getattr(os,'O_DIRECTORY',0) | getattr(os,'O_NOFOLLOW',0))
    try:
        actual = os.fstat(directory_fd)
        if (actual.st_dev,actual.st_ino) != (info.st_dev,info.st_ino):
            raise ReplacementError('backup_directory_changed')
        fd = os.open('news-workflow-'+uuid.uuid4().hex+'.json', os.O_CREAT|os.O_EXCL|os.O_WRONLY|getattr(os,'O_NOFOLLOW',0), 0o600, dir_fd=directory_fd)
        with os.fdopen(fd,'w') as stream:
            os.fchmod(stream.fileno(),0o600)
            json.dump({'format':'news-workflow-replacement-v1','created':time.time(),'before_digest':digest(value['before']),**value},stream)
            stream.flush();os.fsync(stream.fileno())
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)


def replace_news_workflow(database, proof_db, *, apply=False, backup_directory=None):
    if os.path.samefile(database, proof_db):
        raise ReplacementError('proof_and_destination_must_differ')
    if apply and not backup_directory:
        raise ReplacementError('private_backup_directory_required')
    source = Database(proof_db);destination = Database(database)
    try:
        proof = verified_bindings(source);initial = plan(destination,proof)
        destination.close();destination = None
        changed = 0
        if apply and initial['eligible']:
            destination = Database(database,readonly=False)
            destination.connection.execute('BEGIN IMMEDIATE')
            fresh = plan(destination,proof)
            if digest(fresh) != digest(initial):
                raise ReplacementError('destination_changed_since_preflight')
            private_backup(backup_directory,fresh)
            recipe = fresh['replacement']
            from agent_market.gateway.store import _graph_to_steps
            steps = packed({'nodes':recipe['nodes'],'edges':recipe['edges'],
                            'steps':_graph_to_steps(recipe['nodes'],recipe['edges'])})
            updated_at = time.time()
            result = destination.connection.execute('UPDATE agent_workflows SET steps=?,description=?,updated_at=? WHERE id=? AND steps=? AND updated_at=?',
                (steps,recipe['description'],updated_at,fresh['before']['id'],fresh['before']['steps'],fresh['before']['updated_at']))
            if result.rowcount != 1:
                raise ReplacementError('destination_changed_during_apply')
            actual = destination.query('SELECT * FROM agent_workflows WHERE id=?',(fresh['before']['id'],))
            expected = {**fresh['before'],'steps':steps,'description':recipe['description'],'updated_at':updated_at}
            if len(actual) != 1 or dict(actual[0]) != expected:
                raise ReplacementError('unexpected_update_result')
            destination.connection.commit();changed = 1
        return {'mode':'apply' if apply else 'dry_run','eligible':int(initial['eligible']),
                'changed':changed,'backup_created':bool(changed),'preserved_workflow_id':True,
                'preserved_seed_key':True,'historical_runs_modified':0,'resources_modified':0}
    finally:
        if destination is not None:destination.close()
        source.close()


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db',required=True);parser.add_argument('--proof-db',required=True)
    parser.add_argument('--apply',action='store_true');parser.add_argument('--backup-dir')
    args=parser.parse_args(argv)
    try:
        result=replace_news_workflow(args.db,args.proof_db,apply=args.apply,backup_directory=args.backup_dir)
    except ReplacementError as exc:
        print('News replacement refused: '+str(exc),file=sys.stderr);return 1
    except (OSError,sqlite3.Error,ValueError,TypeError,KeyError):
        print('News replacement refused: database_backup_or_proof_error',file=sys.stderr);return 1
    print(json.dumps(result,sort_keys=True));return 0


if __name__=='__main__':
    raise SystemExit(main())
