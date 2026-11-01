"""Explicit, transactional replacement of the hub after real execution verification."""
import json
import os
from pathlib import Path
import sqlite3
import time

from .collector import usage
from .gateway.rag import load_sqlite_vec
from .gateway.store import _graph_to_steps
from .workflow_templates import VERSION, definitions


def verified_recipes(proof_db):
    """Require recent successful executions of these exact graphs and schema pins."""
    with sqlite3.connect(Path(proof_db).resolve().as_uri() + '?mode=ro', uri=True) as db:
        db.row_factory = sqlite3.Row
        reviewed = {}
        for recipe in definitions():
            record = db.execute('SELECT workflow_id FROM workflow_seed_registry WHERE seed_key=?', (recipe['seed_key'],)).fetchone()
            if not record:
                raise ValueError('Missing verified recipe.')
            run = db.execute("SELECT * FROM workflow_runs WHERE workflow_id=? AND status='succeeded' ORDER BY finished DESC LIMIT 1", (record[0],)).fetchone()
            if not run or not run['finished'] or not 0 <= time.time() - run['finished'] < 86400:
                raise ValueError('Each recipe needs a successful execution within the last day.')
            snapshot = json.loads(run['snapshot'])
            actual = snapshot['nodes']
            expected = recipe['nodes']
            if snapshot['name'] != recipe['name'] or snapshot['edges'] != recipe['edges'] or len(actual) != len(expected):
                raise ValueError('Verification does not match the published graph.')
            executed = {row['node_id']: row for row in db.execute('SELECT * FROM workflow_node_runs WHERE run_id=?', (run['id'],))}
            for node, reference in zip(actual, expected):
                if any(node.get(k) != reference.get(k) for k in ('id', 'type', 'kind', 'name')):
                    raise ValueError('Verification node mismatch.')
                data = node.get('data', {})
                if any(data.get(k) != reference.get('data', {}).get(k) for k in ('action', 'input', 'output_select', 'resource_ref')):
                    raise ValueError('Verification input mismatch.')
                if node['type'] == 'trigger':
                    continue
                outcome = executed.get(node['id'])
                if not outcome or outcome['status'] != 'succeeded' or outcome['attempts'] != 1:
                    raise ValueError('Verification must include an actual successful call for every agent node.')
                resource = db.execute('SELECT * FROM resources WHERE id=?', (node.get('resource_id') or data.get('resource_id'),)).fetchone()
                endpoint = reference['data']['resource_ref']['url']
                tools = json.loads(resource['usage_tools']) if resource else []
                if not resource or resource['url'] != endpoint or resource['kind'] != 'mcp' or not resource['active']:
                    raise ValueError('Verification endpoint mismatch.')
                digest = usage.tools_hash(tools)
                binding = snapshot['bindings'].get(node['id'], {})
                tool = next((item for item in tools if item['name'] == data['action']), None)
                if digest != resource['usage_tools_hash'] or digest != binding.get('usage_tools_hash') or not tool or not usage.is_safe_tool(tool):
                    raise ValueError('The verified tool schema or read-only policy changed.')
                reviewed[endpoint] = {'tools': tools, 'digest': digest, 'verified_at': run['finished'], 'run_id': run['id']}
        return reviewed


def replace_templates(database, proof_db, backup_directory):
    """Delete hub definitions only; preserve runs, versions and non-template work."""
    reviewed = verified_recipes(proof_db)
    directory = Path(backup_directory)
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(directory, 0o700)
    database = Path(database).resolve()
    with sqlite3.connect(database.as_uri() + '?mode=rw', uri=True, timeout=10) as db:
        db.row_factory = sqlite3.Row
        # Resource updates fire persisted vector invalidation triggers. Initialize
        # this maintenance connection exactly as Store does, without migrating it.
        vector_loaded = load_sqlite_vec(db)
        if not vector_loaded and db.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='vec_resources'").fetchone():
            raise ValueError('The required SQLite vector extension is unavailable.')
        db.execute('BEGIN IMMEDIATE')
        old = [dict(row) for row in db.execute('SELECT * FROM agent_workflows WHERE is_template=1')]
        old_ids = [row['id'] for row in old]
        placeholders = ','.join('?' for _ in old_ids) or 'NULL'
        backup = {'version': VERSION, 'created': time.time(), 'templates': old, 'related': {}, 'resources': []}
        tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        for table in ('workflow_seed_registry', 'workflow_schedules', 'workflow_destinations', 'workflow_reviews'):
            if table in tables:
                backup['related'][table] = [dict(row) for row in db.execute(f'SELECT * FROM {table} WHERE workflow_id IN ({placeholders})', old_ids)]
        recipes = definitions()
        for recipe in recipes:
            for node in recipe['nodes'][1:]:
                endpoint = node['data']['resource_ref']['url']
                resource = db.execute("SELECT * FROM resources WHERE kind='mcp' AND url=? AND active=1 ORDER BY id DESC LIMIT 1", (endpoint,)).fetchone()
                if not resource:
                    raise ValueError('The verified endpoint is not registered and active in the target catalogue.')
                if resource['id'] not in [row['id'] for row in backup['resources']]:
                    backup['resources'].append(dict(resource))
                node['resource_id'] = node['data']['resource_id'] = resource['id']
        backup_path = directory / ('workflow-templates-' + str(time.time_ns()) + '.json')
        descriptor = os.open(backup_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, 'w') as handle:
            json.dump(backup, handle, ensure_ascii=True)
            handle.flush()
            os.fsync(handle.fileno())
        # Revoke future schedules and callbacks, retaining historical delivery records.
        for table in ('workflow_schedules', 'workflow_destinations', 'workflow_seed_registry'):
            if table in tables:
                db.execute(f'DELETE FROM {table} WHERE workflow_id IN ({placeholders})', old_ids)
        db.execute(f'DELETE FROM agent_workflows WHERE id IN ({placeholders})', old_ids)
        for resource in backup['resources']:
            proof = reviewed[resource['url']]
            db.execute('UPDATE resources SET usage_tools=?,usage_tools_hash=?,usage_updated_at=? WHERE id=?',
                       (json.dumps(proof['tools']), proof['digest'], proof['verified_at'], resource['id']))
        installed = []
        now = time.time()
        for recipe in recipes:
            packed = json.dumps({'nodes': recipe['nodes'], 'edges': recipe['edges'], 'steps': _graph_to_steps(recipe['nodes'], recipe['edges'])})
            cursor = db.execute('''INSERT INTO agent_workflows
                (name,description,category,trigger_type,steps,tags,is_active,is_template,author,rating_avg,created_at,updated_at)
                VALUES (?,?,?,?,?,?,1,1,?,0,?,?)''',
                (recipe['name'], recipe['description'], recipe['category'], 'manual', packed, recipe['tags'], recipe['author'], now, now))
            db.execute('INSERT OR REPLACE INTO workflow_seed_registry VALUES (?,?)', (recipe['seed_key'], cursor.lastrowid))
            installed.append({'id': cursor.lastrowid, 'name': recipe['name']})
        db.execute('INSERT OR REPLACE INTO meta VALUES (?,?)', ('workflow_hub_recipes_v1', json.dumps({'version': VERSION, 'at': now})))
        if db.execute('SELECT COUNT(*) FROM agent_workflows WHERE is_template=1').fetchone()[0] != 3:
            raise ValueError('Unexpected hub count; replacement rolled back.')
        db.commit()
    return {'deleted': len(old), 'installed': installed, 'backup': str(backup_path)}
