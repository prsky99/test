"""Legacy social consumers on owned SQLite and Unix PostgreSQL fixtures only."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time

from scripts.rehearse_storage_adapter_postgres import _driver, _tools, _private_cluster

PROFILE = 'application-sns-postgres-contracts-v1'


def _contracts(connect):
    from agent_market.application_store_postgres import ApplicationStoreError
    from agent_market.gateway.store import Store
    from agent_market.gateway import sns
    from agent_market.storage_adapter import open_store
    connection = connect(); native = open_store('postgresql', connection=connection, initialize=True, workflow_key=b's'*32)
    sqlite = Store(); stores = (native, sqlite); checks = {}

    def equal(label, values):
        if values[0] != values[1]: raise AssertionError(label)
        checks[label] = True

    try:
        for index, name in enumerate(('ASCII Search', 'É resource', 'C:\\path', "SQL' value", 'Other', 'Last')):
            record = {'key':'sns:'+str(index),'kind':('mcp','a2a','x402')[index%3],'source':'synthetic-sns',
                'url':'https://synthetic.invalid/'+str(index),'name':name,'description':'Synthetic public source',
                'category':'research','networks':[],'details':{}}
            for store in stores:
                rid = store.upsert_resource(record, now=7200.9 + index*3600)
                values = (90000+index,95,'A','ok',json.dumps({'strong':['Synthetic definition']}),
                    json.dumps({'at':90000+index,'ok':True,'sample_output':'Synthetic response'}),
                    90000+index,json.dumps({'added':['synthetic_tool']}),rid)
                query = 'UPDATE resources SET eval_at=?,eval_score=?,eval_grade=?,eval_security=?,eval_info=?,trial_info=?,usage_updated_at=?,usage_changes=? WHERE id=?'
                with store.tx() as db:
                    if store is native: store._execute(query.replace('?', '%s'), values)
                    else: db.execute(query, values)
        for store in stores:
            for index, body in enumerate(('ASCII search #source', 'É uppercase', 'C:\\path', "SQL' value")):
                value = sns.create_post(store,body,'Synthetic writer','developer','synthetic-writer','mcp',
                    rating=4,resource_id=1,handle='synthetic')
                assert value['key'] == 'p:'+str(index+1)
            with store.tx() as db:
                if store is native: store._execute('UPDATE sns_posts SET created=10000+id')
                else: db.execute('UPDATE sns_posts SET created=10000+id')
            sns.toggle_like(store,'p:1','synthetic-reader')
            sns.create_post(store,'Synthetic reply','Synthetic writer','user','synthetic-writer',parent_key='p:1')
        checks['native_generated_post_identity_and_like_write'] = True
        # The exact current source methods execute every finite query shape.
        with native.tx(readonly=True):
            for protocol in (None,'mcp'):
                for count in range(9):
                    terms=['synthetic']*count
                    for rid in (None,1):
                        for method in (sns._evaluations,sns._trials,sns._usage_changes):
                            equal(method.__name__+':'+str((protocol,count,rid)),
                                [method(store._db,protocol,terms,20,rid) for store in stores])
                    for role in (None,'developer'):
                        equal('stored:'+str((protocol,count,role)),
                            [sns._stored(store._db,protocol,role,terms,20) for store in stores])
                equal('discovery:'+str(protocol), [sns._discoveries(store._db,protocol,[],20,100000) for store in stores])
                equal('feedback:'+str(protocol), [sns._feedback(store._db,protocol,[],20) for store in stores])
            for term in ('ascii','é','c:\\path',"SQL' value",'%','_', 'é upper'):
                equal('search_like:'+term, [sns._stored(store._db,None,None,sns._terms(term),20) for store in stores])
            equal('named_resource_list_deduplicates_and_preserves_projection',
                [sns._resources_by_id(store._db,[1,2,3,3,4]) for store in stores])
            equal('named_engagement_likes_replies_and_ownership',
                [sns._engagement(store._db,['p:1','p:2','synthetic-key'], 'synthetic-reader') for store in stores])
            equal('named_engagement_without_client',
                [sns._engagement(store._db,['p:1','p:2'],None) for store in stores])
            # Sidebar time windows are old enough that wall-clock skew cannot
            # cross a fixture boundary; empty community data is deterministic.
            original = sns.community_notes; sns.community_notes = lambda: ()
            try: equal('sidebar_numeric_json_and_boolean_aggregates', [sns.sidebar(store._db) for store in stores])
            finally: sns.community_notes = original
        for name,call in (
            ('oversize_ids',lambda:native._db.sns_resources_by_id([1]*4097)),
            ('boolean_id',lambda:native._db.sns_resources_by_id([True])),
            ('injection_key_is_bound',lambda:native._db.sns_engagement(["p:1') OR 1=1 --"],None))):
            if name=='injection_key_is_bound':
                assert len(call())==1
            else:
                try:call()
                except ApplicationStoreError:pass
                else:raise AssertionError(name)
            checks[name]=True
        # Legacy writers without observation_context may retain valid JSON whose
        # at value is not numeric. Such values must never become trial evidence
        # or trigger a native cast, even when their string looks like an epoch.
        invalid_ids = set()
        for index, value in enumerate(('1', str(time.time()), 'legacy', True, False, {}, [], None)):
            for store in stores:
                rid = store.upsert_resource({'key':'sns-invalid-at:'+str(index),'kind':'mcp','source':'synthetic-sns',
                    'url':'https://synthetic.invalid/legacy-at/'+str(index),'name':'Legacy timestamp',
                    'description':'Synthetic legacy timestamp boundary','category':'research','networks':[],'details':{}})
                store.record_usage(rid, [], 'synthetic-empty-tools', {}, None,
                    {'at':value,'ok':True,'sample_output':'Not current numeric evidence'})
                if value is None:
                    # Historical retained null; record_usage otherwise treats
                    # an absent/null supplied time as its current clock.
                    with store.tx() as db:
                        payload=json.dumps({'at':None,'ok':True})
                        if store is native:store._execute('UPDATE resources SET trial_info=%s WHERE id=%s',(payload,rid))
                        else:db.execute('UPDATE resources SET trial_info=? WHERE id=?',(payload,rid))
                invalid_ids.add(rid)
            with native.tx(readonly=True):
                posts = [sns._trials(store._db,None,[],100) for store in stores]
                equal('legacy_non_numeric_trial_at_excluded:'+str(index), posts)
                assert not any(post['resource']['id'] in invalid_ids for post in posts[0])
                original = sns.community_notes; sns.community_notes = lambda: ()
                try: sides = [sns.sidebar(store._db) for store in stores]
                finally: sns.community_notes = original
                equal('legacy_non_numeric_activity_at_excluded:'+str(index), sides)
                assert sides[0]['activity_24h']['trials'] == sides[0]['mood']['mcp']['trials_7d'] == 0
        at = time.time()
        for store in stores:
            rid = store.upsert_resource({'key':'sns-current-numeric-at','kind':'mcp','source':'synthetic-sns',
                'url':'https://synthetic.invalid/current-at','name':'Numeric timestamp',
                'description':'Current numeric timestamp control','category':'research','networks':[],'details':{}})
            store.record_usage(rid, [], 'synthetic-empty-tools', {}, None, {'at':at,'ok':True})
        with native.tx(readonly=True):
            equal('normalized_numeric_trial_at_remains_visible', [sns._trials(store._db,None,[],100) for store in stores])
            original = sns.community_notes; sns.community_notes = lambda: ()
            try: sides = [sns.sidebar(store._db) for store in stores]
            finally: sns.community_notes = original
            equal('normalized_numeric_activity_control', sides)
            assert sides[0]['activity_24h']['trials'] == sides[0]['mood']['mcp']['trials_7d'] == 1
        return {'checks':checks,'provider_calls':0,'operating_actions':0}
    finally:
        native.close();connection.close();sqlite._db.close()


def _worker():
    from scripts import rehearse_application_store_postgres as application
    application._contracts = _contracts
    application._worker()


def rehearse():
    driver = _driver()
    with _private_cluster(_tools()) as cluster:
        environment = dict(cluster['environment']);environment['PYTHONDONTWRITEBYTECODE']='1'
        environment['PYTHONPATH']=str(Path(__file__).resolve().parents[1])+os.pathsep+str(Path(driver.__file__).resolve().parent.parent)
        result=subprocess.run([sys.executable,'-B','-c','from scripts.rehearse_application_sns_postgres import _worker;_worker()'],
            input=json.dumps({'root':cluster['root'],'socket':cluster['socket']}),env=environment,
            text=True,capture_output=True,timeout=120)
        if result.returncode:raise RuntimeError('Synthetic social contract failed: '+result.stderr[-4000:])
        value=json.loads(result.stdout)
    return {'profile':PROFILE,**value,'synthetic':True,'temporary_cluster_removed':True,'full_application_ready':False}


def main():
    parser=argparse.ArgumentParser(description=__doc__,allow_abbrev=False);parser.add_argument('--run',action='store_true')
    if not parser.parse_args().run:parser.error('--run is required')
    print(json.dumps(rehearse(),sort_keys=True,allow_nan=False))


if __name__=='__main__':main()
