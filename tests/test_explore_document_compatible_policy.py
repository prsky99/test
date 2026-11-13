"""11-13: a declared compatible previous policy hash keeps byte-identical documents usable while jobs rebuilds them."""
from agent_market import explore_document_reader as reader


def test_compatible_policy_reads_the_missing_ids_with_the_previous_hash(monkeypatch):
    monkeypatch.setattr(reader.documents, 'policy_hash', lambda: 'new')
    monkeypatch.setattr(reader, 'COMPATIBLE_POLICIES', {'new': ('old',)})
    calls = []

    def one(store, ids, policy):
        calls.append((tuple(ids), policy))
        return {rid: policy for rid in ids if (policy == 'new') == (rid % 2 == 0)}

    found = reader._each_policy(None, [1, 2, 3, 4], one)
    assert found == {1: 'old', 2: 'new', 3: 'old', 4: 'new'}
    assert calls == [((1, 2, 3, 4), 'new'), ((1, 3), 'old')]


def test_nothing_extra_when_every_document_is_current(monkeypatch):
    monkeypatch.setattr(reader.documents, 'policy_hash', lambda: 'new')
    monkeypatch.setattr(reader, 'COMPATIBLE_POLICIES', {'new': ('old',)})
    calls = []
    found = reader._each_policy(None, [1, 2], lambda store, ids, policy: calls.append(policy) or {rid: 1 for rid in ids})
    assert found == {1: 1, 2: 1} and calls == ['new']


def test_a_later_policy_change_ends_the_compatibility(monkeypatch):
    monkeypatch.setattr(reader.documents, 'policy_hash', lambda: 'newer')
    monkeypatch.setattr(reader, 'COMPATIBLE_POLICIES', {'new': ('old',)})
    assert reader.accepted_policies() == ('newer',)
    calls = []
    reader._each_policy(None, [1], lambda store, ids, policy: calls.append(policy) or {})
    assert calls == ['newer']
