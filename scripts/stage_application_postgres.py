"""Copy an online SQLite snapshot to a fresh quarantined PostgreSQL application DB.

Never retires the operating SQLite DB, switches configuration or starts/stops a
web server. Private owned files and the existing typed migration contract are
required. The resulting snapshot is a rehearsal, not a current cutover baseline.
"""
import argparse
import json
import os
from pathlib import Path
import secrets
import sqlite3
import time

from agent_market.application_runtime import _private_bytes, _connect
from agent_market.application_store_migration import bulk_catalog_transfer, copy_application
from agent_market.credential_vault import CredentialVault
from agent_market.gateway.store import Store
from agent_market.storage_adapter import open_store


def private_write(path, content):
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os,'O_NOFOLLOW',0), 0o600)
    with os.fdopen(descriptor, 'w') as stream:
        stream.write(content)
        stream.flush()
        os.fsync(stream.fileno())


def stage(source_path, directory, dsn_file, workflow_key_file, resume_snapshot=None):
    directory = Path(directory)
    if directory.is_symlink() or not directory.is_dir() or directory.stat().st_uid != os.getuid() or directory.stat().st_mode & 0o077:
        raise ValueError('owned_private_stage_directory_required')
    source_path = Path(source_path)
    if source_path.is_symlink() or not source_path.is_file() or source_path.stat().st_uid != os.getuid():
        raise ValueError('owned_source_database_required')
    dsn = _private_bytes(str(dsn_file),16384).decode().strip()
    workflow_key = _private_bytes(str(workflow_key_file),32)
    operation = 'apm_' + secrets.token_hex(16)
    journal = directory / (operation+'.progress.jsonl')
    private_write(journal, '')
    started = time.monotonic()
    def progress(record):
        record = {**record,'elapsed_seconds':round(time.monotonic()-started,2)}
        with journal.open('a') as stream: stream.write(json.dumps(record)+'\n')
        if record.get('rows',0) >= 100000:
            print(json.dumps(record),flush=True)
    snapshot = Path(resume_snapshot) if resume_snapshot else directory / (operation+'.sqlite3')
    if resume_snapshot:
        if (snapshot.is_symlink() or not snapshot.is_file() or snapshot.resolve().parent != directory.resolve()
                or snapshot.stat().st_uid != os.getuid() or snapshot.stat().st_mode & 0o077):
            raise ValueError('owned_private_snapshot_required')
    else:
        private_write(snapshot, '')
    source = target = connection = None
    try:
        if not resume_snapshot:
            origin = sqlite3.connect(source_path.resolve().as_uri()+'?mode=ro',uri=True,timeout=5)
            backup = sqlite3.connect(snapshot)
            try:
                def backup_progress(status, remaining, pages):
                    if time.monotonic()-started > 300:
                        raise TimeoutError('snapshot_time_limit')
                origin.backup(backup,pages=8192,sleep=0.01,progress=backup_progress)
            finally:
                backup.close();origin.close()
        progress({'phase':'consistent-online-snapshot','rows':0})
        source = Store(str(snapshot))
        count = source.query('SELECT COUNT(*) AS n FROM platform_credentials')[0]['n']
        if count:
            key_path = str(source_path.resolve())+'.credentials-key'
            source._credential_vault = CredentialVault.from_key(_private_bytes(key_path,32))
        else:
            source._credential_vault = CredentialVault.from_key(secrets.token_bytes(32))
        connection = _connect(dsn)
        target = open_store('postgresql',connection=connection,initialize=not bool(resume_snapshot),workflow_key=workflow_key)
        progress({'phase':'native-schema-initialized','rows':0})
        with bulk_catalog_transfer(progress=progress):
            receipt = copy_application(source,target,operation_id=operation,
                source_workflow_key=workflow_key,source_vault=source._credential_vault)
        private_write(directory/(operation+'.receipt.json'),json.dumps(receipt,indent=2)+'\n')
        value = receipt['receipt']
        summary = {'operation_id':operation,'equal':value['summary']['equal'],
            'tables':len(value['summary']['tables']),'rows':value['summary']['rows'],
            'seconds':round(time.monotonic()-started,2),'operating_enabled':False,
            'source':'consistent-online-snapshot','requires_final_quiescent_copy':True}
        private_write(directory/'stage-summary.json',json.dumps(summary,indent=2)+'\n')
        return summary
    finally:
        if target is not None: target.close()
        if connection is not None: connection.close()
        if source is not None: source._db.close()


def main():
    parser=argparse.ArgumentParser(description=__doc__,allow_abbrev=False)
    parser.add_argument('--source',required=True)
    parser.add_argument('--directory',required=True)
    parser.add_argument('--dsn-file',required=True)
    parser.add_argument('--workflow-key-file',required=True)
    parser.add_argument('--resume-snapshot')
    args=parser.parse_args()
    print(json.dumps(stage(args.source,args.directory,args.dsn_file,args.workflow_key_file,args.resume_snapshot)),flush=True)


if __name__=='__main__':main()
