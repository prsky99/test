"""The hourly vector index record keeps counters and their change since the previous line (11-12 PM)."""
import json

from scripts.vector_index_usage import change, counters, last_line


def test_change_since_the_previous_line_and_a_counter_reset():
    before = counters([('embeddings_cosine_hnsw', 10, 100, 50, 1), ('embeddings_half_a2a', 5, 40, 10, 1)])
    after = counters([('embeddings_cosine_hnsw', 10, 160, 90, 1), ('embeddings_half_a2a', 2, 8, 2, 1)])
    delta = change(before, after)
    assert delta['embeddings_cosine_hnsw'] == {'scans': 0, 'hit': 60, 'read': 40, 'hit_rate': 60.0}
    assert delta['embeddings_half_a2a'] == {'scans': 2, 'hit': 8, 'read': 2, 'hit_rate': 80.0}  # reset: from zero
    assert change(None, after)['embeddings_half_a2a']['scans'] == 2


def test_last_line_skips_a_torn_line(tmp_path):
    path = tmp_path / 'usage.jsonl'
    path.write_text(json.dumps({'ts': 1}) + '\n{"ts": 2, "broken\n')
    assert last_line(path) == {'ts': 1} and last_line(tmp_path / 'missing.jsonl') is None
