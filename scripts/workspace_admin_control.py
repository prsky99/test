"""Explicit additive migration/worker maintenance; no server launch or restart."""
import argparse
import json


def identity_key_from_workflow_root(raw):
    """Mirror WorkflowRuntime -> CustomerIdentity namespaces, not the root key."""
    import hashlib,hmac
    from agent_market.customer_identity import PROFILE
    if type(raw) is not bytes or len(raw)!=32:raise ValueError('A stable workflow root key is required')
    runtime_key=hmac.new(raw,b'workflow-results-v1',hashlib.sha256).digest()
    return hmac.new(runtime_key,PROFILE.encode(),hashlib.sha256).digest()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=('migrate','project','backfill','prune','quarantine','status'))
    parser.add_argument('--dsn-file',required=True)
    parser.add_argument('--key-file',required=True)
    parser.add_argument('--limit',type=int,default=100)
    args=parser.parse_args()
    if not 1<=args.limit<=500: parser.error('limit must be between 1 and 500')
    from agent_market.application_runtime import open_runtime_storage,_private_bytes
    from agent_market.workspace_admin_events import VERSION,activate,migrate,drain,rows,transaction
    from agent_market.workspace_admin_worker import backfill,prune,quarantine
    key=identity_key_from_workflow_root(_private_bytes(args.key_file,32))
    runtime=open_runtime_storage(':memory:',values={
        'APPLICATION_STORE_BACKEND':'postgresql','APPLICATION_POSTGRES_DSN_FILE':args.dsn_file,
        'APPLICATION_WORKFLOW_KEY_FILE':args.key_file})
    try:
        store=runtime.store
        if args.action=='migrate': result={'ready':migrate(store,key)}
        else:
            if not activate(store,key): raise ValueError('Explicit workspace administration migration required')
            if args.action=='project': result=drain(store,args.limit)
            elif args.action=='backfill': result=backfill(store,args.limit)
            elif args.action=='prune': result=prune(store,args.limit)
            elif args.action=='quarantine': quarantine(store); result={'quarantined':True}
            else:
                with transaction(store,True) as db:
                    result={'outbox':rows(db,'pending_count'),'profile':VERSION}
        print(json.dumps(result,sort_keys=True))
    finally:
        runtime.close()


if __name__=='__main__':
    main()
