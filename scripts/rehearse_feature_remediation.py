"""Isolated native storage checks for public observations and 90-day retention."""
import time


def contracts(connect,factory):
    from agent_market.concierge.memory import VisitorBook
    from agent_market.public_availability import projection
    connection=connect();store=factory(connection,workflow_key=b'f'*32);checks={}
    try:
        book=VisitorBook(store)
        visitor=book.create('rest','FeatureRetentionFixture/1','retention-fixture')
        message_id=book.add_message(visitor,'agent','rest','Expired question')
        assert isinstance(message_id,int) and message_id>0
        book.add_message(visitor,'agent','rest','Current question')
        with connection.transaction():
            connection.execute('UPDATE agent_messages SET at=%s WHERE visitor_id=%s AND text=%s',(time.time()-91*86400,visitor.id,'Expired question'))
        assert [row['text'] for row in book.messages(visitor.id)]==['Current question']
        result=book.prune_conversations()
        assert result['messages']==1
        assert book.by_id(visitor.id) is not None
        book.save_results(visitor,[{'id':1,'task':'expired context'}],1)
        book.save_last_tool(visitor,1,'forecast')
        book.remember_interest(visitor,'expired context','weather',None,None,[])
        with connection.transaction():
            connection.execute('UPDATE agent_interests SET updated=%s WHERE visitor_id=%s',(time.time()-91*86400,visitor.id))
            connection.execute('UPDATE agent_visitors SET last_seen=%s WHERE id=%s',(time.time()-91*86400,visitor.id))
        visitor=book.by_id(visitor.id)
        book.touch(visitor,'rest','FeatureRetentionFixture/1','retention-fixture')
        assert book.last_results(visitor.id)==([],0) and book.get_last_tool(visitor.id)==(None,None)
        assert book.interests(visitor.id)==[]
        checks['ninety_day_retention_deletes_only_expired_messages']=True
        from scripts.migrate_public_experience import migrate
        connection.execute('DROP TABLE public.public_availability_checks')
        assert not migrate(connection,apply=False)['ready']
        migrated=migrate(connection,apply=True)
        assert migrated['ready'] and migrated['table_created'] and migrated['existing_rows_modified']==0
        assert migrate(connection,apply=False)['ready']
        assert migrate(connection,apply=True)['table_created'] is False
        assert [row['text'] for row in book.messages(visitor.id)]==['Current question']
        checks['additive_schema_upgrade_and_concurrent_indexes_preserve_messages']=True
        assert projection(store)['availability']['availability_percent'] is None
        now=time.time()
        with store.tx() as db:
            db.execute('INSERT INTO public_availability_checks (checked_at,ok,status_code,latency_ms) VALUES (?,?,?,?)',(now-60,1,200,200.0))
            db.execute('INSERT INTO public_availability_checks (checked_at,ok,status_code,latency_ms) VALUES (?,?,?,?)',(now,0,503,500.0))
        observed=projection(store,now)
        import json
        json.dumps(observed,allow_nan=False)
        assert observed['status']=='degraded' and observed['availability']['availability_percent']==50
        checks['availability_is_observed_not_hardcoded']=True
        return {'checks':checks}
    finally:store.close()
