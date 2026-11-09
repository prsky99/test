"""Rehearse a production database structure change on a disposable copy before it is run for real.

11-10 05:38: an AD Coin migration added 12 triggers to the public schema, the application's
attach check (_validate_native_invariants) refused every request, and the site answered 500 for
two minutes. The migration had only been tested on an empty database. This tool restores the
newest daily backup into a private PostgreSQL cluster, applies the change there, and attaches the
active frontend and jobs releases with their own code (schema profile, trigger invariants, a write
transaction, an Explore search). It never connects to the production database.

    .venv/bin/python -m scripts.db_change_rehearsal run --sql change.sql
    .venv/bin/python -m scripts.db_change_rehearsal run --command "python -m scripts.ad_coin_v2_migrate migrate --dsn-file {dsn_file} --key-file {key_file} --i-have-approval"
    .venv/bin/python -m scripts.db_change_rehearsal check --sql change.sql     # before the production run

`run` writes a JSON report under logs/ops/db-rehearsal/ and exits 1 when any check fails. A passed
run also records the change's digest; `check` exits 1 unless the same change passed within
PASS_HOURS against the releases that are active now, so a production run can be refused.
Data: --data minimal (default) restores the full schema and all data except the large tables;
--data full restores the whole backup (about 20 minutes on the production Mac).
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parent.parent
BIN = Path('/opt/homebrew/opt/postgresql@18/bin')
BACKUPS = ROOT / 'gateway-data/backups/daily'
REPORTS = ROOT / 'logs/ops/db-rehearsal'
STATE = ROOT / 'gateway-data/services/state.json'
RELEASES = ROOT / 'gateway-data/services/releases'
PASS_HOURS = 24
# --data minimal restores every table's data except these (50 MB or more on 11-10, about 8 GB together)
# and the tables whose foreign keys point at them; the rest is about 170 MB. Schema is always complete.
SKIP_DATA = ('public resources', 'agentcon_search embeddings', 'public vec_resources', 'public legacy_vector_jobs',
             'agentcon_search explore_documents', 'agentcon_search capability_text', 'public admin_health_daily',
             'public erc8004_tokens', 'public adoption_changes', 'public health_checks', 'public resources_fts',
             'public legacy_vector_provenance', 'public agent_test_reports', 'public resource_observation_owners',
             # foreign keys to skipped tables
             'public test_report_subject_claims', 'agentcon_search explore_document_queue')
# Copy-only control schemas tie a database to its original identity; a disposable copy drops them.
COPY_GATES = ('agent_migration_control', 'agent_restore_control')
PRODUCTION_MARKERS = ('55432', str(ROOT / 'gateway-data/postgres18'), 'application.dsn', 'agentcon_cutover_')

# Runs inside each release's own environment, with only that release on sys.path.
CHECK = r'''
import json, sys, time
import psycopg
socket, port, key_path = sys.argv[1], int(sys.argv[2]), sys.argv[3]
out = {}
began = time.monotonic()
try:
    from agent_market.storage_adapter import open_store
    connection = psycopg.connect(host=socket, port=port, dbname='postgres', user='postgres', autocommit=True)
    store = open_store('postgresql', connection=connection, workflow_key=open(key_path, 'rb').read(),
                       required_capabilities=('full_application', 'service_runtime'))
    out['attach'] = 'ok'  # profile, schema and trigger invariants (_verify_profile)
    with store.tx():
        pass
    out['write_transaction'] = 'ok'  # writer lock, deployment gates and invariants again
    from agent_market.concierge.front import get_front_explore
    result = get_front_explore(store, 'weather forecast', 'mcp', None, False, False, 5)
    out['explore'] = 'ok' if isinstance(result, dict) and 'items' in result else 'unexpected'
except Exception as error:
    out['error'] = type(error).__name__ + ': ' + str(getattr(error, 'code', '') or error)[:300]
out['ok'] = 'error' not in out and out.get('explore') == 'ok'
out['seconds'] = round(time.monotonic() - began, 2)
print(json.dumps(out))
'''


class RehearsalRefused(SystemExit):
    pass


def change_digest(sql=None, command=None):
    if sql:
        return 'sql:' + hashlib.sha256(Path(sql).read_bytes()).hexdigest()
    return 'command:' + hashlib.sha256(command.encode()).hexdigest()


def active_releases():
    services = json.loads(STATE.read_text())['services']
    front = services['frontend']
    slot = front['slots'][front['active']]
    return [slot['release'] if isinstance(slot, dict) else slot, services['jobs']['release']]


def newest_backup():
    for path in sorted(BACKUPS.glob('snapshot-*'), reverse=True):
        if (path / 'manifest.json').is_file() and (path / 'database.dump').is_file():
            return path
    raise RehearsalRefused('no_backup_found')


def refuse_production(command):
    hits = [marker for marker in PRODUCTION_MARKERS if marker in command]
    if hits:
        raise RehearsalRefused('command_names_production: ' + ', '.join(hits))


def _environment():
    return {k: v for k, v in os.environ.items() if not k.startswith('PG')}


def restore(backup, cluster, mode, port):
    dump = backup / 'database.dump'
    target = ['--host', cluster['socket'], '--port', str(port), '--username', 'postgres', '--dbname', 'postgres']
    common = [str(BIN / 'pg_restore'), '--exit-on-error', '--no-owner', '--no-acl']
    if mode == 'full':
        command = common + ['--jobs=2'] + target + [str(dump)]
    else:
        listing = subprocess.run([str(BIN / 'pg_restore'), '-l', str(dump)], capture_output=True, text=True, check=True).stdout
        keep = []
        for line in listing.splitlines():
            if any(f' TABLE DATA {name} ' in line for name in SKIP_DATA):
                continue
            keep.append(line)
        order = Path(cluster['root']) / 'restore.list'
        order.write_text('\n'.join(keep) + '\n')
        command = common + ['-L', str(order)] + target + [str(dump)]
    result = subprocess.run(command, env=_environment(), capture_output=True, timeout=3600)
    if result.returncode:
        return {'ok': False, 'stderr': result.stderr.decode(errors='replace')[-2000:]}
    gates = []
    for schema in COPY_GATES:
        dropped = subprocess.run([str(BIN / 'psql'), '-v', 'ON_ERROR_STOP=1', '-At', *target[:-2], '-d', 'postgres',
                                  '-c', f"SELECT 1 FROM pg_namespace WHERE nspname='{schema}'"],
                                 env=_environment(), capture_output=True, text=True)
        if dropped.stdout.strip() == '1':
            subprocess.run([str(BIN / 'psql'), '-v', 'ON_ERROR_STOP=1', *target[:-2], '-d', 'postgres',
                            '-c', f'DROP SCHEMA {schema} CASCADE'], env=_environment(), capture_output=True, check=True)
            gates.append(schema)
    return {'ok': True, 'mode': mode, 'copy_gates_dropped': gates}


def check_release(release, cluster, port, key_path):
    path = RELEASES / release
    python = path / '.venv' / 'bin' / 'python'
    if not python.exists():
        return {'ok': False, 'error': 'release_not_found'}
    env = {**_environment(), 'PYTHONPATH': str(path), 'PYTHONDONTWRITEBYTECODE': '1'}
    result = subprocess.run(['nice', '-n', '10', str(python), '-c', CHECK, cluster['socket'], str(port), str(key_path)],
                            cwd=str(path), env=env, capture_output=True, text=True, timeout=600)
    try:
        return json.loads(result.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        return {'ok': False, 'error': 'check_crashed', 'stderr': result.stderr[-1500:]}


def apply_change(cluster, port, sql=None, command=None, key_path=None):
    if sql:
        result = subprocess.run([str(BIN / 'psql'), '-v', 'ON_ERROR_STOP=1', '-1', '-h', cluster['socket'], '-p', str(port),
                                 '-U', 'postgres', '-d', 'postgres', '-f', str(Path(sql).resolve())],
                                env=_environment(), capture_output=True, text=True, timeout=1800)
    else:
        dsn_file = Path(cluster['root']) / 'rehearsal.dsn'
        descriptor = os.open(dsn_file, os.O_CREAT | os.O_WRONLY | os.O_TRUNC, 0o600)
        with os.fdopen(descriptor, 'w') as stream:
            stream.write(f"host={cluster['socket']} port={port} dbname=postgres user=postgres")
        text = command.format(dsn_file=dsn_file, key_file=key_path, socket=cluster['socket'], port=port)
        refuse_production(text)
        env = {**_environment(), 'PGHOST': cluster['socket'], 'PGPORT': str(port), 'PGUSER': 'postgres', 'PGDATABASE': 'postgres'}
        result = subprocess.run(shlex.split(text), cwd=str(ROOT), env=env, capture_output=True, text=True, timeout=3600)
    return {'ok': result.returncode == 0, 'returncode': result.returncode,
            'stdout': result.stdout[-1500:], 'stderr': result.stderr[-1500:]}


def run(sql=None, command=None, backup=None, releases=None, mode='minimal', report=None):
    from scripts.rehearse_storage_adapter_postgres import _private_cluster, PORT
    if command:
        refuse_production(command)
    backup = Path(backup) if backup else newest_backup()
    releases = releases or active_releases()
    began = time.time()
    result = {'started': began, 'backup': backup.name, 'releases': releases, 'data': mode,
              'change': change_digest(sql, command), 'production_connected': False}
    tools = {name: str(BIN / name) for name in ('initdb', 'pg_ctl')}
    with _private_cluster(tools) as cluster:
        key_path = Path(cluster['root']) / 'workflow.key'
        descriptor = os.open(key_path, os.O_CREAT | os.O_WRONLY | os.O_TRUNC, 0o600)
        with os.fdopen(descriptor, 'wb') as stream:
            stream.write((backup / 'workflow.key').read_bytes())
        result['restore'] = restore(backup, cluster, mode, PORT)
        if result['restore']['ok']:
            result['before'] = {release: check_release(release, cluster, PORT, key_path) for release in releases}
            if all(item.get('ok') for item in result['before'].values()):
                result['apply'] = apply_change(cluster, PORT, sql, command, key_path)
                if result['apply']['ok']:
                    result['after'] = {release: check_release(release, cluster, PORT, key_path) for release in releases}
    result['ok'] = bool(result.get('after')) and all(item.get('ok') for item in result['after'].values())
    result['verdict'] = ('passed' if result['ok'] else
                         'restore_failed' if not result['restore']['ok'] else
                         'copy_unusable_before_change' if not all(i.get('ok') for i in result['before'].values()) else
                         'change_failed' if not result['apply']['ok'] else 'application_refuses_changed_database')
    result['seconds'] = round(time.time() - began, 1)
    REPORTS.mkdir(parents=True, exist_ok=True)
    path = Path(report) if report else REPORTS / time.strftime('rehearsal-%Y%m%d-%H%M%S.json')
    path.write_text(json.dumps(result, indent=2) + '\n')
    if result['ok']:
        passed = REPORTS / 'passed.json'
        try:
            records = json.loads(passed.read_text())
        except (OSError, ValueError):
            records = {}
        records[result['change']] = {'at': time.time(), 'releases': releases, 'report': str(path)}
        passed.write_text(json.dumps(records, indent=2) + '\n')
    result['report'] = str(path)
    return result


def check(sql=None, command=None, now=None):
    """0 when this exact change passed a rehearsal within PASS_HOURS against the releases active now."""
    now = time.time() if now is None else now
    try:
        record = json.loads((REPORTS / 'passed.json').read_text()).get(change_digest(sql, command))
    except (OSError, ValueError):
        record = None
    if not record:
        return {'ok': False, 'reason': 'no_passed_rehearsal'}
    if now - record['at'] > PASS_HOURS * 3600:
        return {'ok': False, 'reason': 'rehearsal_older_than_%d_hours' % PASS_HOURS}
    if sorted(record['releases']) != sorted(active_releases()):
        return {'ok': False, 'reason': 'active_releases_changed', 'rehearsed': record['releases'], 'active': active_releases()}
    return {'ok': True, 'report': record['report']}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('action', choices=('run', 'check'))
    change = parser.add_mutually_exclusive_group(required=True)
    change.add_argument('--sql')
    change.add_argument('--command')
    parser.add_argument('--backup')
    parser.add_argument('--releases', help='comma separated; default: active frontend and jobs')
    parser.add_argument('--data', choices=('minimal', 'full'), default='minimal')
    parser.add_argument('--report')
    args = parser.parse_args(argv)
    if args.action == 'check':
        result = check(args.sql, args.command)
    else:
        result = run(args.sql, args.command, args.backup, args.releases.split(',') if args.releases else None,
                     args.data, args.report)
    print(json.dumps(result, indent=2))
    return 0 if result['ok'] else 1


if __name__ == '__main__':
    sys.path.insert(0, str(ROOT))
    raise SystemExit(main())
