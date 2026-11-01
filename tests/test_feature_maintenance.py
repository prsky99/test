"""Retention remains schedulable while a collection command is running."""
# ruff: noqa: F811 -- imported pytest fixture.
from threading import Event,Thread
from types import SimpleNamespace

from tests.test_fast_single_recommendation import catalog  # noqa: F401


def test_long_collection_does_not_starve_retention(catalog,monkeypatch):
    from agent_market import public_availability,service_host,model_contract_reverify,postgres_capability_text
    _,front,_,_,_=catalog
    entered,release,cleaned,stop=Event(),Event(),Event(),Event()
    class Idle:
        def __init__(self,*args,**kwargs):pass
        def due(self):return False
    monkeypatch.setattr(public_availability,'AvailabilityMonitor',Idle)
    monkeypatch.setattr(model_contract_reverify,'ContractReverifier',Idle)
    monkeypatch.setattr(postgres_capability_text,'Refresher',Idle)
    original=front.book.prune_conversations
    def purge():
        assert entered.wait(2)
        result=original();cleaned.set();return result
    monkeypatch.setattr(front.book,'prune_conversations',purge)
    claimed=[False]
    def claim():
        if not claimed[0]:claimed[0]=True;return {'fixture':True}
    control=SimpleNamespace(claim=claim,heartbeat=lambda *args:None)
    app=SimpleNamespace(state=SimpleNamespace(front=front))
    loop=service_host.BackgroundLoop(app,control,'jobs',stop)
    monkeypatch.setattr(loop,'heartbeat',lambda:None)
    def command(item):entered.set();assert release.wait(5)
    monkeypatch.setattr(loop,'command',command)
    thread=Thread(target=loop.run)
    try:
        thread.start()
        assert cleaned.wait(3) and entered.is_set() and not release.is_set()
    finally:
        stop.set();release.set();thread.join(3);loop.close()
    assert not thread.is_alive()
