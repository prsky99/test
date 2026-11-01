"""Native qualification parity on the parent's owned mock-only PostgreSQL fixture.

The approved_external and operating labels below are synthetic contract inputs.
They never establish real independent qualification or operating acceptance.
No address, DSN, signing material, model or external source is accepted.
"""
import base64
import secrets
import time


def run_reliability_completion_contracts(store, graph, staff, resource_id, session_token):
    import httpx
    from agent_market.capability_registry import digest
    from agent_market.gateway import admin_auth
    from agent_market.private_artifact_keys import ArtifactCipher, ArtifactKeys
    from agent_market.workspace_execution import NOTICE as RUN_NOTICE
    from agent_market.workspace_access import WorkspaceConflict
    from agent_market.workspace_reliability import (NOTICE, OPERATING_NOTICE, RETENTION_NOTICE,
        EvaluatorVerdict, OperatingEvidenceApproval, ReliabilityEvidence)
    from tests.test_mcp_proxy import MockRemoteMcp

    if (store.backend != 'postgresql' or store.workflow_key != b'k'*32
            or graph.access.store is not store or graph.execution.access is not graph.access
            or admin_auth.session_reference(session_token) != staff.session_ref):
        raise AssertionError('Use only the current parent-owned native synthetic fixture.')
    resource = store.resource(resource_id)
    if (resource['kind'] != 'mcp' or resource['source'] != 'mcp-registry'
            or resource['url'] not in ('https://typed-0.example/mcp', 'https://typed-1.example/mcp')
            or not isinstance(getattr(graph.execution.proxy, '_http', None), httpx.Client)
            or type(graph.execution.proxy._http._transport) not in (httpx.MockTransport, MockRemoteMcp)):
        raise AssertionError('Use only the fixed in-process native MCP fixture.')

    def require(value, label):
        if value is not True:
            raise AssertionError(label)
    def identity(prefix):
        return prefix+'_'+secrets.token_hex(16)
    def command(**fields):
        return {'command_id': identity('rec'), 'authorized': True, 'notice': NOTICE, **fields}

    workspace = graph.access.provision({'name': 'Native qualification contract fixture', 'owner_id': staff.user_id}, staff)['id']
    keys = ArtifactKeys({'profile': 'private-artifact-keys-v1', 'active_signing': 'completion-fixture',
        'active_encryption': 'completion-fixture', 'allow_legacy': True,
        'keys': [{'id': 'completion-fixture', 'key': base64.b64encode(b'C'*32).decode(),
                  'verify_until': time.time()+3600, 'revoked': False}]})
    core = ReliabilityEvidence(graph.access, graph.execution,
        cipher=ArtifactCipher('bounded-reliability-evidence-v1:sources', keys))
    def save(kind, spec):
        return core.save_object(workspace, command(object_id=identity('reo'), kind=kind, revision=0, spec=spec), staff)
    plan = save('plan', {'dataset_version': 'native-completion-fixture-v1', 'dataset_hash': '1'*64,
        'rubric_version': 'native-completion-fixture-v1', 'rubric_hash': '2'*64, 'minimum_samples': 2,
        'window_seconds': 3600, 'confidence': 'wilson-95-v1', 'environment': 'approved_external',
        'evaluator_version': 'native-completion-fixture-v1'})
    case = save('case', {'plan_id': plan['id'], 'plan_revision': 1, 'case_version': 'baseline-v1',
        'case_hash': '3'*64, 'category': 'baseline'})
    cohort = save('cohort', {'plan_id': plan['id'], 'plan_revision': 1, 'case_ids': [case['id']],
        'resource_id': resource_id, 'contract_id': 'docs.search.v1', 'purpose': 'independent-read-evaluation'})
    consent = core.authorize_cohort(workspace, command(consent_id=identity('ren'), cohort_id=cohort['id'],
        cohort_revision=1, retention_seconds=1800, notice=RETENTION_NOTICE), staff)
    arguments = {'query': 'documentation', 'language': 'en', 'limit': 2}
    draft = graph.access.save_draft(workspace, {'name': 'Native completion fixed read', 'description': '',
        'definition': {'nodes': [{'id': 'start', 'name': 'Manual', 'type': 'trigger', 'kind': 'trigger', 'data': {}},
            {'id': 'docs', 'name': 'Documentation', 'type': 'agent', 'kind': 'mcp', 'resource_id': resource_id,
             'data': {'tool': 'search_docs', 'input': arguments}}],
             'edges': [{'source': 'start', 'target': 'docs'}]}}, staff)
    snapshot = graph.access.create_snapshot(workspace, draft['id'], {'draft_revision': draft['revision']}, staff)
    for _ in range(2):
        prepared = graph.execution.prepare(workspace, draft['id'], snapshot['id'], {'snapshot_revision': snapshot['revision']}, staff)
        run = graph.execution.execute(workspace, draft['id'], snapshot['id'],
            {'ticket_id': prepared['ticket_id'], 'authorized': True, 'notice': RUN_NOTICE}, staff)
        require(run['status']=='succeeded', 'The owned native original read did not complete.')
        source = core.retain_source(workspace, command(source_id=identity('res'), consent_id=consent['id'],
            bundle={'input': arguments, 'output': run['output'], 'sources': [{'reference': 'native-completion-fixture'}]},
            notice=RETENTION_NOTICE), staff)
        core.observe(workspace, command(observation_id=identity('reb'), consent_id=consent['id'], case_id=case['id'],
            source_id=source['id'], run_ref=run['id'], logical_task_id=identity('ret')), staff)
    assessments = []
    def evaluator(binding, bundle):
        require(store._db.in_transaction is False, 'Independent verdict adapter was invoked inside a transaction.')
        assessments.append(digest(binding))
        return EvaluatorVerdict(digest(binding), 'native-completion-fixture-v1', '4'*64, '5'*64,
                                time.time()+300, binding['environment'], 'passed', 'verified')
    core.evaluator=evaluator
    require(core.get_agent_projection(workspace, resource_id, staff)['independent_qualified'] is False,
            'A missing local verdict was implicitly assessed on projection.')
    require(assessments==[], 'Projection caused a new judgment.')
    core.current_report(workspace, resource_id, staff)
    require(len(assessments)==2, 'Explicit report must prepare the two existing source verdicts.')
    with graph.access._tx(staff) as (db, _):
        require(core.current_projection_in_transaction(db, workspace, resource_id, staff)['independent_qualified'] is True,
                'Native local verdict cache did not qualify the retained fixture.')
    require(len(assessments)==2, 'Final transaction caused an extra judgment.')
    checks = {'native_completion_verdict_preparation_outside_transaction_and_pure_local_projection': True}
    def qualifier(binding):
        require(store._db.in_transaction is False, 'Operating qualifier was invoked inside a transaction.')
        return OperatingEvidenceApproval(digest(binding), '6'*64, '7'*64, min(time.time()+120, binding['expires']))
    core.operating_qualifier=qualifier
    request = {'resource_id': resource_id, 'revision': 0, 'authorized': True, 'notice': OPERATING_NOTICE}
    result=core.qualify_operating(workspace, request, staff)
    require(result['qualified_operating_evidence'] is True and result['revision']==1,
            'Native synthetic operating-qualification row did not round-trip.')
    require(core.get_agent_projection(workspace, resource_id, staff)['environment']=='operating',
            'Native signed qualification did not bind the exact source.')
    try:
        core.qualify_operating(workspace, request, staff)
    except WorkspaceConflict:
        pass
    else:
        raise AssertionError('A stale native qualification revision was accepted.')
    checks['native_completion_signed_synthetic_qualification_cas_and_current_source'] = True
    core.withdraw_operating(workspace, request | {'revision': 1}, staff)
    require(core.get_agent_projection(workspace, resource_id, staff)['qualified_operating_evidence'] is False,
            'Native qualification withdrawal did not revoke projection.')
    core.qualify_operating(workspace, request | {'revision': 2}, staff)
    rebuilt = ReliabilityEvidence(graph.access, graph.execution, evaluator=evaluator,
        cipher=core.cipher, operating_qualifier=qualifier)
    rebuilt.current_report(workspace, resource_id, staff)
    require(rebuilt.get_agent_projection(workspace, resource_id, staff)['qualified_operating_evidence'] is False,
            'Rebuilding the native plane reactivated old operating authority.')
    checks['native_completion_qualification_withdrawal_and_rebuilt_authority'] = True
    core.operating_qualifier=None
    require(core.operating_status(workspace, resource_id, staff)['configured'] is False,
            'Fixture qualifier remained enabled.')
    from agent_market.workspace_app_factory import AppFactory, MODEL_NOTICE, NOTICE as FACTORY_NOTICE
    shared=[]
    def proposer(envelope):
        require(store._db.in_transaction is False, 'Native model proposal ran inside a transaction.')
        require(set(envelope)=={'profile','objective','candidates','contracts','limits','output_profile'},
                'Native model received private context fields.')
        require(all(set(item)=={'resource_id','contract_id'} for item in envelope['candidates']),
                'Native model candidate metadata was not minimal.')
        shared.append(envelope['objective'])
        choices=[item for item in envelope['candidates'] if item['contract_id']=='docs.search.v1']
        require(bool(choices), 'Native approved model candidate is unavailable.')
        proposal_input = arguments | {'query': 'public documentation and references'}
        return {'nodes':[dict(choices[index%len(choices)], input=proposal_input) for index in range(2)]}
    factory=AppFactory(graph.typed_flows,model_proposer=proposer)
    review=factory.prepare_model_proposal(workspace, {'objective':'Search public documentation and references',
        'name':'Native advisory proposal', 'authorized':True, 'notice':MODEL_NOTICE,
        'data_attestation':'public_objective_without_personal_or_private_data'},staff)
    require(review['state']=='review_required' and review['agent_calls']==0 and len(shared)==1,
            'Native advisory proposal did not produce one separate unexecuted review.')
    saved=factory.commit(workspace, {'review_id':review['review_id'],'authorized':True,'notice':FACTORY_NOTICE},staff)
    require(saved['id'] is not None, 'Native advisory graph could not save a separate typed draft.')
    checks['native_completion_model_proposal_minimal_context_review_new_draft']=True
    return checks
