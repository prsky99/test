"""Exact source observations, eviction and context boundaries for public facts."""
import hashlib
import pytest
from agent_market.concierge import discovery_contracts as cache


def key(pair):
    return tuple(hashlib.sha256(v.encode()).hexdigest() if v is not None else None for v in pair)


def test_payload_requires_public_scope_and_actual_complete_bytes(monkeypatch):
    monkeypatch.setattr(cache, '_facts', cache.FactCache())
    pair=('[]','[{"name":"get_weather"}]')
    cache.remember_payload(key(pair),pair)
    assert cache.payload(key(pair)) is None
    @cache.contract_reads
    def request():
        assert cache.payload(key(pair)) is None
        cache.remember_payload(key(pair),pair)
        assert cache.payload(key(pair)) == pair
        changed=(pair[0],pair[1]+' ')
        assert cache.payload(key(changed)) is None
        with pytest.raises(ValueError):cache.remember_payload(key(changed),pair)
        assert cache.payload(key(changed)) is None
    request()
    assert cache.payload(key(pair)) is None


def test_null_and_empty_declarations_remain_distinct(monkeypatch):
    monkeypatch.setattr(cache, '_facts', cache.FactCache())
    @cache.contract_reads
    def request():
        for pair in ((None,None),('',None),('[]','[]')):
            cache.remember_payload(key(pair),pair)
            assert cache.payload(key(pair))==pair
        with pytest.raises(ValueError):cache.payload(('wrong','digest'))
    request()


def test_fact_cache_is_bounded_and_handles_replacement_and_eviction():
    facts=cache.FactCache(maximum=2,maximum_bytes=10)
    facts.put('a','12345',5);facts.put('b','12345',5)
    assert facts.get('a')=='12345'
    facts.put('c','12',2)
    assert facts.get('b') is None and facts.bytes==7
    facts.put('a','1',1)
    assert facts.bytes==3
    facts.put('large','x'*11,11)
    assert facts.get('large') is None and facts.bytes==3


def test_task_facts_use_every_current_field_and_expire_without_plaintext(monkeypatch):
    now=[10.0]
    facts=cache.TaskFacts(maximum=2,lifetime=2,clock=lambda:now[0])
    assert facts.fingerprint('task',{'value':'1'},None,None)!=facts.fingerprint('task',{'value':1},None,None)
    monkeypatch.setattr(cache,'_tasks',facts)
    calls=[]
    @cache.task_facts
    def pure(task,resource,*,terms=None,core=None):
        calls.append(1);return resource['allowed']
    @cache.contract_reads
    def request():
        row={'allowed':True,'name':'private-test-marker','revision':'same-claimed-revision'}
        assert pure('opaque-public-task',row)
        assert pure('opaque-public-task',row)
        assert len(calls)==1
        row['allowed']=False
        assert pure('opaque-public-task',row) is False
        assert len(calls)==2
        assert 'private-test-marker' not in repr(facts.values)
        assert 'opaque-public-task' not in repr(facts.values)
        now[0]=13
        assert pure('opaque-public-task',row) is False
        assert len(calls)==3
        for number in range(4):pure(str(number),row)
        assert len(facts.values)<=2
    request()
