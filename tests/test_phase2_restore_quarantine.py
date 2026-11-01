"""Restored signed records remain history and never revive private permissions."""
import json
import sqlite3

from agent_market.workflow_backup import quarantine, restored_inventory
from agent_market.workspace_reliability import SCHEMA as EVIDENCE_SCHEMA
from agent_market.reliability_evaluation import SCHEMA as EVALUATION_SCHEMA
from agent_market.reliability_routing import SCHEMA as ROUTING_SCHEMA
from agent_market.workspace_app_factory import SCHEMA as FACTORY_SCHEMA
from agent_market.workspace_support_outcomes import SCHEMA as SUPPORT_SCHEMA
from agent_market.workspace_machine_updates import SCHEMA as MACHINE_SCHEMA
from agent_market.workspace_machine_receiver import SCHEMA as RECEIVER_SCHEMA
from agent_market.reliability_research import SCHEMA as RESEARCH_SCHEMA
from agent_market.reliability_admission import SCHEMA as ADMISSION_SCHEMA
from agent_market.workspace_protocol_conformance import SCHEMA as PROTOCOL_SCHEMA
from agent_market.reliability_circuit import SCHEMA as CIRCUIT_SCHEMA


def test_restore_permanently_blocks_all_new_authority_without_rewriting_signed_history():
    db = sqlite3.connect(':memory:')
    try:
        for statement in EVIDENCE_SCHEMA + EVALUATION_SCHEMA + ROUTING_SCHEMA + FACTORY_SCHEMA + SUPPORT_SCHEMA + MACHINE_SCHEMA + RECEIVER_SCHEMA + RESEARCH_SCHEMA + ADMISSION_SCHEMA + PROTOCOL_SCHEMA + CIRCUIT_SCHEMA:
            db.execute(statement)
        payload = json.dumps({'id': 'policy', 'revision': 3})
        db.execute('INSERT INTO reliability_consents VALUES(?,?,?,?,?)', ('consent', 'ws', 'cohort', payload, 'signed'))
        db.execute('INSERT INTO reliability_sources VALUES(?,?,?,?,?)', ('source', 'ws', 'cohort', 'encrypted-bundle', 'signed'))
        db.execute('INSERT INTO reliability_eval_controls VALUES(?,?,?)', ('ws', payload, 'signed'))
        db.execute('INSERT INTO reliability_eval_plans VALUES(?,?,?,?)', ('ws', 3, payload, 'signed'))
        db.execute('INSERT INTO reliability_eval_jobs VALUES(?,?,?,?,?,?,?,?,?)', ('job', 'ws', 'logical', 'dispatched', 'host', 1, 2, payload, 'signed'))
        db.execute('INSERT INTO reliability_route_policies VALUES(?,?,?,?)', ('ws', 3, payload, 'signed'))
        db.execute('INSERT INTO workspace_factory_reviews VALUES(?,?,?,?)', ('review', 'ws', payload, 'signed'))
        db.execute('INSERT INTO workspace_sdk_policies VALUES(?,?,?,?,?)', ('ws', 'workspace-sdk-v2', 3, payload, 'signed'))
        db.execute('INSERT INTO workspace_support_cases VALUES(?,?,?,?,?)', ('case', 'ws', 3, payload, 'signed'))
        db.execute('INSERT INTO workspace_machine_subscriptions VALUES(?,?,?,?,?)', ('subscription', 'ws', 1, payload, 'signed'))
        db.execute('INSERT INTO workspace_machine_update_events VALUES(?,?,?,?,?,?,?,?)', ('event', 'ws', 'subscription', 'dedupe', 'dispatched', 1, payload, 'signed'))
        db.execute('INSERT INTO workspace_machine_receivers VALUES(?,?,?,?,?)', ('receiver', 'ws', 1, payload, 'signed'))
        db.execute('INSERT INTO workspace_machine_receiver_claims VALUES(?,?,?,?,?,?,?,?)', ('received', 'ws', 'target', 'nonce', 'dedupe', 1, payload, 'signed'))
        db.execute('INSERT INTO reliability_research_manifests VALUES(?,?,?,?,?,?)', ('manifest', 'ws', 'corpus', 1, payload, 'signed'))
        db.execute('INSERT INTO reliability_admission_policies VALUES(?,?,?,?)', ('ws', 3, payload, 'signed'))
        db.execute('INSERT INTO reliability_admissions VALUES(?,?,?,?,?,?,?)', ('admission', 'ws', 'logical-admission', 'snapshot', 'ticket', payload, 'signed'))
        db.execute('INSERT INTO workspace_protocol_reports VALUES(?,?,?,?,?,?)', ('report', 'ws', 'external-event', 1, payload, 'signed'))
        db.execute('INSERT INTO reliability_circuit_states VALUES(?,?,?,?,?,?)', ('ws', 7, 2, 1, payload, 'signed'))
        db.execute('INSERT INTO reliability_circuit_claims VALUES(?,?,?,?,?)', ('ws', 'eval:job', 7, payload, 'signed'))
        retained = ('reliability_consents', 'reliability_eval_controls', 'reliability_eval_plans', 'reliability_eval_jobs',
            'reliability_route_policies', 'workspace_factory_reviews', 'workspace_sdk_policies', 'workspace_support_cases',
            'workspace_machine_subscriptions', 'workspace_machine_update_events',
            'workspace_machine_receivers', 'workspace_machine_receiver_claims', 'reliability_research_manifests',
            'reliability_admission_policies', 'reliability_admissions', 'workspace_protocol_reports',
            'reliability_circuit_states', 'reliability_circuit_claims')
        before = {table: db.execute('SELECT * FROM '+table).fetchall() for table in retained}
        inventory = restored_inventory(db)
        for table in ('reliability_research_manifests', 'reliability_admission_policies', 'reliability_admissions', 'workspace_protocol_reports', 'reliability_circuit_states', 'reliability_circuit_claims'):
            item = inventory['items'][table]
            assert item['count'] == 1 and not item['truncated'] and item['review_action']
            assert 'payload' not in item['records'][0] and 'signature' not in item['records'][0]
        assert not inventory['automatic_reactivation']
        with db: quarantine(db)
        assert before == {table: db.execute('SELECT * FROM '+table).fetchall() for table in retained}
        assert not db.execute('SELECT id FROM reliability_sources').fetchall()
        expected = {
            'reliability_restore_blocks': {'consent'},
            'reliability_controls_restore_blocks': {'eval_control:ws:3', 'eval_plan:ws:3', 'eval_job:job', 'routing_policy:ws:3'},
            'workspace_expansion_restore_blocks': {'review', 'policy:3'},
            'workspace_support_restore_blocks': {'case'},
            'workspace_machine_update_restore_blocks': {'subscription', 'event'},
            'workspace_machine_receiver_restore_blocks': {'receiver'},
            'reliability_research_restore_blocks': {'manifest'},
            'reliability_admission_restore_blocks': {'ws:3', 'admission'},
            'workspace_protocol_restore_blocks': {'report'},
            'reliability_circuit_restore_blocks': {'circuit:ws:7:1', 'source:ws:eval:job'},
        }
        for table, values in expected.items():
            assert {row[0] for row in db.execute('SELECT * FROM '+table)} == values
        with db: quarantine(db)
        for table, values in expected.items():
            assert {row[0] for row in db.execute('SELECT * FROM '+table)} == values
    finally:
        db.close()


def test_restore_blocks_sole_owner_recovery_and_sandbox_financial_authority_as_history():
    from agent_market.customer_recovery import SCHEMA as RECOVERY_SCHEMA
    from agent_market.stripe_sandbox import SCHEMA as STRIPE_SCHEMA
    db=sqlite3.connect(':memory:')
    try:
        for sql in (*RECOVERY_SCHEMA,*STRIPE_SCHEMA):
            db.execute(sql)
        db.execute('INSERT INTO customer_recovery_policies VALUES(?,?,?,?)',('ws',4,'synthetic-signed-policy','signature'))
        db.execute('INSERT INTO customer_recovery_requests VALUES(?,?,?,?,?,?,?)',
            ('request','ws','target','challenge',1,'synthetic-signed-request','signature'))
        db.execute('INSERT INTO stripe_sandbox_orders VALUES(?,?,?,?)',('order','ws','synthetic-order','signature'))
        db.execute('INSERT INTO stripe_sandbox_reservations VALUES(?,?,?)',('run','order','ws'))
        before={table:db.execute('SELECT * FROM '+table).fetchall() for table in
            ('customer_recovery_policies','customer_recovery_requests','stripe_sandbox_orders','stripe_sandbox_reservations')}
        inventory=restored_inventory(db)
        assert inventory['items']['customer_recovery_requests']['count']==1
        assert inventory['items']['stripe_sandbox_orders']['count']==1
        with db:
            quarantine(db)
        assert {row[0] for row in db.execute('SELECT * FROM customer_recovery_blocks')}=={'ws:4','request'}
        assert db.execute('SELECT * FROM stripe_sandbox_restore_blocks').fetchall()==[('order',)]
        assert before=={table:db.execute('SELECT * FROM '+table).fetchall() for table in before}
    finally:
        db.close()
