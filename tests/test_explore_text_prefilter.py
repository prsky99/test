"""Explore reads document texts first once a batch is mostly unadmittable (2026-11-04).

Only a current document's own text may rule a listing out, and only through the necessary
condition the admission check applies to that same text; everything else is read as before.
"""
import agent_market.application_store_resource_batches as batches
import agent_market.explore_document_reader as reader
import agent_market.postgres_capability_text as capability_text
from agent_market.concierge.hybrid_explore import _in_ranked_batches


def install(monkeypatch, texts, missing=()):
    calls = {'read': [], 'texts': [], 'resources': []}

    def read(store, ids):
        calls['read'].append(list(ids))
        return {rid: {'id': rid, '_capability_text': texts[rid]} for rid in ids if rid in texts and rid not in missing}

    def read_texts(store, ids):
        calls['texts'].append(list(ids))
        return {rid: texts[rid] for rid in ids if rid in texts and rid not in missing}

    def resources(store, ids, *a, **k):
        calls['resources'].append(list(ids))
        return [{'id': rid} for rid in ids]
    monkeypatch.setattr(reader, 'read', read)
    monkeypatch.setattr(reader, 'texts', read_texts)
    monkeypatch.setattr(batches, 'resources', resources)
    monkeypatch.setattr(capability_text, 'attach', lambda store, rows: rows)
    return calls


def keep(row, text):
    return 'weather' in text


def test_mostly_unmatched_batches_read_texts_first_and_skip_only_failing_documents(monkeypatch):
    texts = {rid: ('weather tool' if rid in (3, 7) else 'payments') for rid in range(1, 9)}
    calls = install(monkeypatch, texts, missing={8})
    ranked = [{'id': rid} for rid in range(1, 10)]  # 9 has no document at all
    rows = list(_in_ranked_batches(None, ranked, size=3, keep=keep))
    # First batch is read in full; later ones only after their texts.
    assert calls['read'][0] == [1, 2, 3]
    assert calls['texts'] == [[4, 5, 6], [7, 8, 9]]
    assert calls['read'][1:] == [[], [7, 8, 9]]
    # A failing document is never yielded; a listing without a current document still is.
    assert [row['id'] for row in rows] == [1, 2, 3, 7, 8, 9]


def test_batches_that_mostly_match_keep_the_single_read(monkeypatch):
    texts = {rid: 'weather' for rid in range(1, 7)}
    calls = install(monkeypatch, texts)
    rows = list(_in_ranked_batches(None, [{'id': rid} for rid in range(1, 7)], size=3, keep=keep))
    assert calls['texts'] == [] and [row['id'] for row in rows] == list(range(1, 7))


def test_without_a_condition_nothing_changes(monkeypatch):
    texts = {rid: 'payments' for rid in range(1, 7)}
    calls = install(monkeypatch, texts)
    rows = list(_in_ranked_batches(None, [{'id': rid} for rid in range(1, 7)], size=3))
    assert calls['texts'] == [] and len(rows) == 6
