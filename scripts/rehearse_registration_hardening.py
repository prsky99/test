"""Registration and inquiry contracts against an owned PostgreSQL schema only."""
import json
import time
from unittest.mock import patch


def contracts(connect,factory):
    from agent_market.concierge.front import Front, submit_register_agent
    from agent_market.concierge.public_inquiries import record_inquiry
    from agent_market.concierge.registration_policy import PublicRequestError
    from tests.test_registration_hardening import listing,inquiry
    store=factory(connect(),workflow_key=b'r'*32)
    front=None
    checks={}
    try:
        front=Front(store)
        observed={'protocol_verified':True,'kind':'mcp','details':{'tools':['search_docs']},'status_code':200,'latency_ms':1}
        with patch('agent_market.concierge.registration_policy._resolve_addresses',return_value=['8.8.8.8']),patch('agent_market.concierge.front.inspect_register_url',return_value=observed):
            result=submit_register_agent(store,listing(),'fixture-ip')
            assert result['id'] and store.resource(result['id'])['health_status']=='healthy'
            with store.tx(readonly=True):
                receipt=store._execute("SELECT detail FROM security_events WHERE event_type='registration_consent'").fetchall()
            assert len(receipt)==1 and json.loads(receipt[0][0])['resource_id']==result['id']
            checks['atomic_private_consent']=True
            try:submit_register_agent(store,listing(),'fixture-ip')
            except PublicRequestError as error:assert error.status_code==409
            else:raise AssertionError('Duplicate accepted')
            checks['duplicate_rejected']=True
        receipt=record_inquiry(store,inquiry(),ip='fixture-ip',user_agent='IsolatedQA')
        duplicate=record_inquiry(store,inquiry(),ip='fixture-ip',user_agent='IsolatedQA')
        assert receipt['inquiry_id']==duplicate['inquiry_id'] and duplicate['duplicate']
        for index in range(4):record_inquiry(store,inquiry(subject='Question '+str(index)),ip='fixture-ip',user_agent='IsolatedQA')
        try:record_inquiry(store,inquiry(subject='Quota exceeded'),ip='fixture-ip',user_agent='IsolatedQA')
        except PublicRequestError as error:assert error.status_code==429
        else:raise AssertionError('Quota bypassed')
        checks['durable_dedup_and_email_quota']=True
        now=time.time()
        with store.tx() as db:
            store._execute('''INSERT INTO agent_task_watches(id,visitor_id,task,channel,state,created,expires,notice_version,authority,code_expires)
                VALUES (%s,%s,%s,'webhook','pending_verification',%s,%s,%s,1,%s)''',
                ('tw_native_registration_fixture','fixture-visitor','test',now-86401,now+86400,'fixture-notice',now+100))
        front.updates.maintain()
        assert not store.query('SELECT * FROM agent_task_watches WHERE id=?',('tw_native_registration_fixture',))
        checks['pending_deleted_at_creation_plus_24h']=True
        from scripts.cleanup_registration_qa import cleanup, RESOURCES
        from tempfile import TemporaryDirectory
        connection=store._connection
        with connection.transaction():
            for rid,(url,kind) in RESOURCES.items():
                connection.execute("""INSERT INTO resources(id,key,source,kind,url,name,description,category,networks,details,first_seen,last_seen)
                    VALUES(%s,%s,'manual',%s,%s,'QA TEST - please delete','Synthetic registration QA','dev_tools',',','{}',%s,%s)""",
                    (rid,'fixture:'+str(rid),kind,url,now,now))
        store.create_test_report({'resource_id':206598,'title':'Synthetic report','slug':'qa-cleanup-fixture'})
        connection.execute('ALTER TABLE test_report_subject_claims ADD CONSTRAINT qa_cleanup_fixture_fk FOREIGN KEY(report_id) REFERENCES agent_test_reports(id)')
        with TemporaryDirectory(prefix='registration-cleanup-fixture-') as directory:
            plan=cleanup(connection,backup_dir=directory)
            assert plan['matched']['resources']==5 and not plan['applied']
            cleaned=cleanup(connection,apply=True,backup_dir=directory)
            assert cleaned['deleted']['resources']==5
            assert connection.execute('SELECT COUNT(*) AS n FROM resources').fetchone()['n']==1
            again=cleanup(connection,apply=True,backup_dir=directory)
            assert not again['deleted']
        checks['cleanup_exact_ids_and_idempotency']=True
        return {'checks':checks}
    finally:
        if front:front.book.flush_hits()
        store.close()
