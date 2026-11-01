"""Application composition and support contracts in the owned native fixture only."""


def run_growth_contracts(store, graph, workspace, staff, resource_ids, flow, completed):
    from agent_market.workspace_access import WorkspaceDenied
    from agent_market.workspace_app_factory import AppFactory, NOTICE, SDK_NOTICE
    from agent_market.workspace_support_outcomes import SupportOutcomes, NOTICE as SUPPORT_NOTICE, WITHDRAW_NOTICE
    if (store.backend != 'postgresql' or store.workflow_key != b'k'*32
            or graph.access.store is not store or len(resource_ids) != 2
            or any(store.resource(rid)['url'] != 'https://typed-'+str(index)+'.example/mcp'
                   for index, rid in enumerate(resource_ids))):
        raise AssertionError('Only the owned native documentation fixture is accepted.')
    ws = workspace['id']; factory = AppFactory(graph.typed_flows, releases=graph.releases, typed_releases=graph.typed_releases)
    support = SupportOutcomes(graph.access, graph.execution, graph.typed_flows)
    preview = factory.prepare(ws, {'template_id': 'documentation_crosscheck', 'purpose': 'Current documentation',
        'resource_ids': resource_ids, 'name': 'Native reviewed app', 'from_utc': None, 'criteria': []}, staff)
    body = {'review_id': preview['review_id'], 'authorized': True, 'notice': NOTICE}
    saved = factory.commit(ws, body, staff); replay = factory.commit(ws, body, staff)
    if saved['id'] != replay['id'] or not replay['replayed'] or preview['provider_calls'] != 0:
        raise AssertionError('Native factory replay must preserve one private workflow without calling a provider.')
    policy = factory.configure_sdk(ws, {'sdk_profile': 'workspace-typed-sdk-v2', 'revision': 0,
        'accepting_runs': False, 'minimum_sdk_version': '2.1.0', 'sunset_seconds': 300,
        'authorized': True, 'notice': SDK_NOTICE}, staff)
    catalog = factory.catalog(ws, staff)
    if policy['accepting_runs'] or not any(p['revision'] == 1 for p in catalog['policies']):
        raise AssertionError('Native private SDK policy did not retain its signed revision.')
    body = {'source_kind': 'typed', 'subject_id': flow['id'], 'version_id': flow['version_id'],
        'run_id': completed['run']['id'], 'category': 'setup', 'resolution': 'resolved', 'iterations': 1,
        'revision': 0, 'authorized': True, 'notice': SUPPORT_NOTICE}
    observation = support.record(ws, body, staff)
    report = support.report(ws, staff)
    if not support.record(ws, body, staff)['replayed'] or report['logical_run_samples'] != 1 or report['business_outcome'] != 'unassessed':
        raise AssertionError('Native support report must be source-bound, deduplicated and unassessed.')
    support.withdraw(ws, {'case_id': observation['case_id'], 'revision': 1, 'authorized': True, 'notice': WITHDRAW_NOTICE}, staff)
    try:
        support.record(ws, body, staff)
    except WorkspaceDenied:
        pass
    else:
        raise AssertionError('A withdrawn native support observation was resurrected.')
    return {'native_factory_atomic_idempotent_private_save': True,
            'native_sdk_source_version_owner_policy_and_catalog': True,
            'native_support_retained_logical_run_dedupe_withdrawal_unassessed': True}
