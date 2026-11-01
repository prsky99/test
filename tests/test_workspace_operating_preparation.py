"""Configuration, sandbox and operating evidence have separate authority."""
from types import SimpleNamespace
import time

import pytest

from agent_market.workspace_operating_preparation import OperatingPreparation, ConfigurationCheck
from agent_market.workspace_access import WorkspaceConflict, WorkspaceDenied, WorkspaceInvalid
from tests.test_advancement_tools import tools


def test_missing_configuration_keeps_all_operating_and_launch_flags_off(tools):
    t=tools;core=OperatingPreparation(t['access'],t['readiness'])
    value=core.status(t['ws'],t['actors'][1])
    assert all(not item['configured'] for item in value['identity_providers'])
    assert all(item['state']=='missing_configuration' for item in value['configuration'])
    assert not value['operating_evidence_complete'] and not value['public_workspace_access_enabled']
    assert not value['payment_enabled'] and not value['commercial_enabled']


def test_only_typed_fresh_server_sources_report_configuration_without_operating_promotion(tools):
    t=tools;now=time.time()
    identity=SimpleNamespace(options=lambda:{'providers':[{'id':'google','configured':True,'secret':'synthetic-must-not-escape'}, {'id':'github','configured':False}]})
    sources={'sdk2':lambda ws,actor:ConfigurationCheck(ws,'sdk2',True,'sandbox',now,now+60),
             'payment':lambda ws,actor:{'configured':True,'environment':'operating'},
             'support':lambda ws,actor:ConfigurationCheck(ws,'support',True,'operating',now,now-1)}
    value=OperatingPreparation(t['access'],t['readiness'],identity=identity,sources=sources).status(t['ws'],t['actors'][1])
    assert value['identity_providers'][0]['configured'] and 'synthetic-must-not-escape' not in str(value)
    assert value['configuration'][0]['state']=='configured'
    assert all(not item['operating_verified'] for item in value['configuration'])
    assert not value['operating_evidence_complete'] and not value['configuration_is_operating_evidence']
    assert next(item for item in value['configuration'] if item['purpose']=='payment')['state']=='missing_configuration'


def test_membership_rechecked_after_config_source_returns(tools):
    t=tools
    def source(ws,actor):
        with t['store']._db as db:db.execute('UPDATE workspace_memberships SET revision=revision+1 WHERE workspace_id=? AND user_id=1',(ws,))
        return ConfigurationCheck(ws,'sdk2',True,'sandbox',time.time(),time.time()+60)
    core=OperatingPreparation(t['access'],t['readiness'],sources={'sdk2':source})
    with pytest.raises(WorkspaceConflict):core.status(t['ws'],t['actors'][1])


def test_source_errors_are_missing_not_raw_private_diagnostics(tools):
    t=tools
    def source(ws,actor):raise ValueError('synthetic-secret-must-not-escape')
    value=OperatingPreparation(t['access'],t['readiness'],sources={'sdk2':source}).status(t['ws'],t['actors'][1])
    assert 'synthetic-secret-must-not-escape' not in str(value)
    assert value['configuration'][0]['state']=='missing_configuration'
    with pytest.raises(WorkspaceInvalid):OperatingPreparation(t['access'],t['readiness'],sources={'unknown':source})
    with pytest.raises(WorkspaceDenied):OperatingPreparation(t['access'],t['readiness']).status(t['ws'],t['actors'][5])


def test_slow_later_callback_cannot_return_expired_configuration_or_operating_evidence(tools, monkeypatch):
    from agent_market.advancement_readiness import AdvancementReadiness, CurrentEvidence, CATEGORIES
    t=tools; current=[time.time()]; observed=current[0]
    monkeypatch.setattr('agent_market.workspace_operating_preparation.clock',lambda:current[0])
    monkeypatch.setattr('agent_market.advancement_readiness.clock',lambda:current[0])
    sources={category:lambda ws,actor,c=category:CurrentEvidence(ws,c,'synthetic_current','b'*64,
        observed,observed+60,'operating','c'*64) for category in CATEGORIES}
    readiness=AdvancementReadiness(t['access'],evidence_sources=sources)
    assert readiness.status(t['ws'],t['actors'][1])['required_current_evidence_complete']
    def later(ws,actor):
        current[0]+=120
        return ConfigurationCheck(ws,'payment',True,'sandbox',current[0],current[0]+60)
    core=OperatingPreparation(t['access'],readiness,sources={
        'sdk2':lambda ws,actor:ConfigurationCheck(ws,'sdk2',True,'sandbox',observed,observed+60),
        'payment':later})
    value=core.status(t['ws'],t['actors'][1])
    assert value['configuration'][0]['state']=='missing_configuration'
    assert value['configuration'][-1]['state']=='configured'
    assert not value['operating_evidence_complete']
    assert all(not check['verified'] for check in value['operating_evidence'])
    # The readiness reader itself also validates at response time rather than
    # retaining a positive result from before the final source returned.
    current[0]=observed
    def last(ws,actor):
        current[0]+=120
        return sources['identity'](ws,actor)
    readiness=AdvancementReadiness(t['access'],evidence_sources=sources|{'operations':last})
    assert not readiness.status(t['ws'],t['actors'][1])['required_current_evidence_complete']


@pytest.mark.parametrize('invalid',[10**1000,float('inf'),float('nan'),True])
def test_typed_source_nonfinite_or_oversized_integer_is_missing_instead_of_raising(tools,invalid):
    from agent_market.advancement_readiness import AdvancementReadiness, CurrentEvidence
    t=tools;now=time.time()
    readiness=AdvancementReadiness(t['access'],evidence_sources={
        'identity':lambda ws,actor:CurrentEvidence(ws,'identity','synthetic_current','a'*64,now,invalid,'operating','b'*64)})
    value=OperatingPreparation(t['access'],readiness,sources={
        'sdk2':lambda ws,actor:ConfigurationCheck(ws,'sdk2',True,'sandbox',now,invalid)}).status(t['ws'],t['actors'][1])
    assert value['configuration'][0]['state']=='missing_configuration'
    assert not value['operating_evidence_complete']
