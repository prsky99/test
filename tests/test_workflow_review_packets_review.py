"""Durable minimization prevents sensitive context from becoming export proof."""
import json
import pytest

from agent_market.workflow_comparison import ComparisonError
from agent_market.workflow_composer import Composer
from agent_market.workflow_review_packets import ReviewPackets
from agent_market.workflow_typed_flow import PROFILE, NOTICE, validate_title
from tests.test_workflow_composer import save
from tests.test_workflow_fallback import routing
from tests.test_workflow_typed_flow import typed_routing, saved_typed
from tests.test_workflow_runtime import wait


@pytest.mark.parametrize('location,marker',[
    ('actual_query','token=synthetic-review-secret'),
    ('actual_query','password=synthetic-review-secret'),
    ('objective','token=synthetic-review-secret'),
    ('objective','password=synthetic-review-secret'),
])
def test_known_sensitive_context_cannot_be_exported_as_exact_verified_input(typed_routing,location,marker):
    rt,_,_,calls,*_=typed_routing
    if location=='objective':
        text='Python news and documentation '+marker
        assert validate_title(text)==text
        draft=Composer(rt).generate({'prompt':text,'flow':PROFILE},1)
        workflow=rt.store.get_workflow(save(rt,draft,flow_authority=True,flow_notice=NOTICE)['id'])
    else:
        workflow=saved_typed(rt)
        text='Python documentation '+marker
        assert validate_title(text)==text
        rt.typed_test_controls['title']=text
    result=wait(rt,rt.submit(workflow))
    # Current runtime minimization removes the known secret pattern before a
    # successful exact downstream input can be certified. Do not fabricate a
    # successful checkpoint merely to bypass that existing protection.
    assert result['status']=='failed',result
    assert calls==['primary.example']
    assert len(rt.typed_test_controls['seen'])==1
    if location=='objective':
        with pytest.raises(ComparisonError):
            ReviewPackets(rt).prepare({'run_id':result['run_id']})
    else:
        packet=ReviewPackets(rt).prepare({'run_id':result['run_id']})['packet']
        assert packet['context']['actual_documentation_query'] is None
        assert packet['context']['actual_query_status']=='unavailable'
        assert 'synthetic-review-secret' not in json.dumps(packet)
    assert calls==['primary.example']
