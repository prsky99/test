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


def test_the_b_and_c_bundle_reads_the_day15_documents():
    """11-16 B+C: 2,995 sampled documents byte-identical between 5d3d8f6a and this code's policy."""
    current = reader.documents.policy_hash()
    assert reader.accepted_policies() == (current, '5d3d8f6a1d61faac5da83354fa3ebff7a61702a5b89c83a2824d2d3327b9c54c')
