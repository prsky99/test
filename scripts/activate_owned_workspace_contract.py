"""Review/apply one exact local research contract; never start a server or open navigation."""
import argparse
import asyncio
import json
from pathlib import Path
import sqlite3
import sys
import time

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from agent_market.capability_registry import Registry,digest,version_parts
from agent_market.owned_capability_adapter import profile,TOOL,CONTRACT

KEY='agentconcierge-owned:research-papers'


def reviewed(resource):
    if not resource or resource.get('key')!=KEY or resource.get('source')!='agentconcierge-owned' or resource.get('kind')!='mcp' or not resource.get('active'):
        raise ValueError('The exact active first-party connection is required.')
    adapter=profile(resource,CONTRACT,TOOL)
    if not adapter or resource.get('health_status')=='quarantined':raise ValueError('Review the local connection schema first.')
    parts=version_parts(resource)
    if not parts[3]:raise ValueError('The full current schema is required.')
    return {'resource_id':resource['id'],'version_id':'cv_'+digest([resource['id'],*parts[:3]])[:32],
        'contract_id':CONTRACT,'tool':TOOL,'adapter':adapter['id'],'local_execution':True,'public_navigation_changed':False}


def activate(store,expected_version,*,proxy=None):
    from agent_market.concierge.proxy import McpProxy
    from agent_market.capability_contracts import run_test
    from agent_market.gateway.admin_auth import record_audit
    rows=store.query('SELECT * FROM resources WHERE key=?',(KEY,))
    proof=reviewed(dict(rows[0]) if len(rows)==1 else None)
    if expected_version!=proof['version_id']:raise ValueError('The reviewed connection version changed.')
    registry=Registry(store);resource=store.resource(proof['resource_id'])
    def current():
        return reviewed(store.resource(proof['resource_id']))==proof
    registry.approve(resource,CONTRACT,TOOL,guard=current)
    proxy=proxy or McpProxy(store)
    async def runner(identity,**kwargs):
        if current() is not True:raise ValueError('The reviewed connection changed.')
        started=time.time()
        result=proxy.execute(identity,kwargs['tool'],kwargs['arguments'],public=True)
        finished=time.time()
        # This explicit operator check requires durable evidence. Optional proxy
        # analytics may be skipped under contention; never infer success from
        # contract metadata alone or manufacture a transport/protocol result.
        if all(result.get(key) is True for key in ('ok','hash_verified','transport_ok','protocol_valid')):
            registry.record(registry.current(resource),scope='execution',outcome='succeeded',
                started=started,finished=finished,dataset='operator-owned-contract-v1',guard=current)
        return {'execution_succeeded':result.get('ok') is True,'simulated':False,'output':result.get('result')}
    checked=asyncio.run(run_test(registry,resource,CONTRACT,{'query':'battery recycling','language':'en','limit':1},runner))
    projection=registry.projection(store.resource(proof['resource_id']))
    ready=projection.get('connection_readiness',{}).get('verified_callable') is True
    contract=any(c.get('id')==CONTRACT and c.get('verified') is True for c in projection.get('capability_contracts',[]))
    verified=checked['ok'] is True and ready and contract
    result={**proof,'verified':verified,'error_code':checked.get('reason') or (None if verified else 'CONNECTION_NOT_VERIFIED')}
    with store.tx() as db:
        record_audit(db,'local-operator','operator','OWNED_WORKSPACE_CONTRACT','Reviewed first-party documentation contract',
                     target='agent:'+str(proof['resource_id']),status='SUCCESS' if result['verified'] else 'FAILED',details=result)
    return result


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__,allow_abbrev=False)
    parser.add_argument('--db',required=True);parser.add_argument('--apply',action='store_true');parser.add_argument('--expected-version')
    args=parser.parse_args(argv)
    if args.apply and not args.expected_version:parser.error('--apply requires the exact inspected --expected-version')
    path=Path(args.db).resolve(strict=True)
    if args.apply:
        from agent_market.gateway.store import Store
        store=Store(str(path))
        try:result=activate(store,args.expected_version)
        finally:store._db.close()
    else:
        db=sqlite3.connect(path.as_uri()+'?mode=ro',uri=True);db.row_factory=sqlite3.Row
        try:rows=db.execute('SELECT * FROM resources WHERE key=?',(KEY,)).fetchall()
        finally:db.close()
        result=reviewed(dict(rows[0]) if len(rows)==1 else None)
    print(json.dumps(result,sort_keys=True))
    return 0 if not args.apply or result['verified'] else 1


if __name__=='__main__':raise SystemExit(main())
