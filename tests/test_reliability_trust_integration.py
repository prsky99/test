"""Trust consumes the actual retained-evidence interface without execution on reads."""
from agent_market.reliability_trust import ReliabilityTrust
from tests.test_workspace_reliability import reliability, private_api, setup, sample, trusted, erase


def test_actual_evidence_projection_is_neutral_by_default_and_drops_after_retention_erasure(reliability):
    w = setup(reliability, environment='approved_external')
    source, _, _ = sample(w); sample(w); before = len(w.calls)
    trust = ReliabilityTrust(w.plane.access, evidence_source=w.plane.get_agent_projection)
    neutral, _ = trust.projection(w.ws['id'], w.rid, w.actor)
    assert neutral['state'] == 'evidence_pending'
    w.plane.evaluator = trusted
    w.plane.current_report(w.ws['id'], w.rid, w.actor)
    qualified, tag = trust.projection(w.ws['id'], w.rid, w.actor)
    assert qualified['state'] == 'last_verified' and qualified['logical_samples'] == 2
    assert qualified['contract_id'] == 'news.search.v1'
    assert qualified['contract_revision'] == 1 and not qualified['qualified_operating_evidence']
    erase(w, source['id'])
    withdrawn, changed = trust.projection(w.ws['id'], w.rid, w.actor)
    assert withdrawn['state'] == 'evidence_pending' and tag != changed
    assert len(w.calls) == before
