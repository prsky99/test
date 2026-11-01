"""A shared Store cannot interleave workers between Explore card evidence reads."""
import copy
import queue
import threading
import time
from types import SimpleNamespace

import pytest

from agent_market.capability_registry import Registry
from agent_market.concierge import front as module
from tests.test_fast_single_recommendation import catalog  # noqa: F401


@pytest.fixture
def cards(catalog,monkeypatch):
    store,_,_,add,now=catalog
    ids=[add('Read batch '+str(index),report_at=now-10 if index==0 else None)for index in range(3)]
    module.clear_front_caches()
    monkeypatch.setattr(module.RedisHub,'get_instance',lambda:SimpleNamespace(is_available=lambda:False))
    try:yield store,ids
    finally:module.clear_front_caches()


def explore(store,report=False):
    return module.get_front_explore(store,'','mcp',None,False,False,45,has_report=report)


class Contender:
    """Try the actual lock from another thread at deterministic read boundaries."""
    def __init__(self,lock):
        self.lock=lock;self.requests=queue.Queue();self.results=queue.Queue();self.probes=0
        self.thread=threading.Thread(target=self.run,daemon=True);self.thread.start()

    def run(self):
        while self.requests.get():
            acquired=self.lock.acquire(blocking=False)
            if acquired:self.lock.release()
            self.results.put(acquired)

    def check(self):
        self.requests.put(True)
        assert self.results.get(timeout=2)is False,'Another worker acquired the Store lock inside the card batch.'
        self.probes+=1

    def close(self):
        self.requests.put(False);self.thread.join(timeout=2)
        assert not self.thread.is_alive()


@pytest.mark.parametrize('path',['fresh','memory','redis','report'])
def test_card_reads_and_boundaries_exclude_another_store_worker(cards,monkeypatch,path):
    store,ids=cards
    initial_versions=store.query('SELECT count(*) FROM connection_versions')[0][0]
    cached=explore(store)if path in('memory','redis')else None
    if path=='redis':
        module._front_explore_cache.clear()
        monkeypatch.setattr(module.RedisHub,'get_instance',lambda:SimpleNamespace(
            is_available=lambda:True,get_json=lambda _:copy.deepcopy(cached),
            set_json=lambda *args,**kwargs:None,delete_keys=lambda *args:None,
            delete_pattern=lambda *args:None))
    contender=Contender(store._lock);inside=[False];queries=[0]
    original_query=store.query;original_card=module._card_data;original_refresh=module.refresh_connection_states
    original_report=module._report_filtered_explore
    def query_checked(sql,params=()):
        result=original_query(sql,params)
        if inside[0]:contender.check();queries[0]+=1
        return result
    def bounded(function,*args,**kwargs):
        outer=inside[0];inside[0]=True
        try:
            contender.check();result=function(*args,**kwargs);contender.check();return result
        finally:inside[0]=outer
    def checked_refresh(*args,**kwargs):
        if inside[0]:return original_refresh(*args,**kwargs)
        return bounded(original_refresh,*args,**kwargs)
    monkeypatch.setattr(store,'query',query_checked)
    monkeypatch.setattr(module,'_card_data',lambda *args,**kwargs:bounded(original_card,*args,**kwargs))
    monkeypatch.setattr(module,'refresh_connection_states',checked_refresh)
    monkeypatch.setattr(module,'_report_filtered_explore',lambda *args,**kwargs:bounded(original_report,*args,**kwargs))
    try:
        result=explore(store,report=path=='report')
        assert {item['id']for item in result['items']}==({ids[0]}if path=='report'else set(ids))
        assert queries[0]>=5 and contender.probes>queries[0]
        if path=='fresh':
            # The unprojected cards require Registry.current() to enter Store.tx
            # and create identities while the same reentrant lock is held.
            assert store.query('SELECT count(*) FROM connection_versions')[0][0]>initial_versions
    finally:contender.close()


def test_memory_cached_success_is_rechecked_after_newer_failed_execution(cards):
    store,ids=cards;first=explore(store)
    original=next(item for item in first['items']if item['id']==ids[0])
    assert original['connection_readiness']['verified_callable']and original['report_grade']=='A'
    registry=Registry(store);now=time.time();registry.record(registry.current(ids[0]),scope='execution',
        outcome='failed',started=now,finished=now,code='SCHEMA_CHANGED')  # one transient error alone keeps readiness
    refreshed=next(item for item in explore(store)['items']if item['id']==ids[0])
    assert refreshed['connection_readiness']['verified_callable']is False
    assert refreshed['connection_readiness']['reason']=='latest_failure'
    assert refreshed['report_grade']is None and refreshed['report_score']is None
    assert refreshed['report_count']==1


@pytest.mark.parametrize('path',['fresh','memory','report'])
def test_failed_projection_releases_the_lock_for_another_worker(cards,monkeypatch,path):
    store,_=cards
    if path=='memory':explore(store)
    target='refresh_connection_states'if path=='memory'else'_report_filtered_explore'if path=='report'else'_card_data'
    def fail(*args,**kwargs):raise RuntimeError('isolated projection failure')
    monkeypatch.setattr(module,target,fail)
    with pytest.raises(RuntimeError,match='isolated projection failure'):explore(store,report=path=='report')
    acquired=[]
    def enter():
        value=store._lock.acquire(timeout=1);acquired.append(value)
        if value:store._lock.release()
    thread=threading.Thread(target=enter);thread.start();thread.join(timeout=2)
    assert acquired==[True]and not thread.is_alive()
