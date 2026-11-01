"""Bounded pending work retains authority checks and cannot bypass admission."""
from concurrent.futures import ThreadPoolExecutor
import threading
import time
import pytest
from agent_market import workspace_app_factory as module
from agent_market.workspace_access import WorkspaceConflict
from tests.test_workspace_growth import growth
from tests.test_workspace_typed_flows import typed_world, routing
from tests.test_workspace_model_proposal import request,response


def test_queue_is_bounded_and_permission_is_checked_when_pending_work_starts(growth,monkeypatch):
    g=growth;started=threading.Event();release=threading.Event();calls=[]
    def proposer(ctx):
        calls.append(ctx);started.set();release.wait(3)
        return response(ctx)
    g.factory.model_proposer=proposer
    slots=threading.BoundedSemaphore(2)
    with ThreadPoolExecutor(max_workers=1) as queue,ThreadPoolExecutor(max_workers=2) as callers:
        monkeypatch.setattr(module,'_proposal_pool',queue);monkeypatch.setattr(module,'_proposal_slots',slots)
        first=callers.submit(g.factory.prepare_model_proposal,g.w.ws,request(),g.w.actor)
        try:
            assert started.wait(2)
            second=callers.submit(g.factory.prepare_model_proposal,g.w.ws,request(),g.w.actor)
            deadline=time.monotonic()+2
            while slots._value and time.monotonic()<deadline:time.sleep(.005)
            assert slots._value==0
            with pytest.raises(WorkspaceConflict):g.factory.prepare_model_proposal(g.w.ws,request(),g.w.actor)
            with g.w.store.tx() as db:db.execute('UPDATE workspace_memberships SET revision=revision+1 WHERE workspace_id=?',(g.w.ws,))
        finally:release.set()
        with pytest.raises(WorkspaceConflict):first.result(timeout=3)
        with pytest.raises(WorkspaceConflict):second.result(timeout=3)
        assert len(calls)==1 and slots._value==2
    assert not g.w.calls and not g.w.store.query('SELECT id FROM workspace_factory_reviews')
