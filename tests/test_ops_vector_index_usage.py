"""ops_auto records vector index use once an hour (검색과 RAG 11-12, PM: 72 h of zero scans before a drop request)."""
import json
import subprocess
from datetime import datetime

from scripts import ops_auto


class Done:
    def __init__(self, code, out):
        self.returncode, self.stdout = code, out


def _setup(monkeypatch, tmp_path):
    monkeypatch.setattr(ops_auto, 'VECTOR_USAGE_STATE', tmp_path / 'state.json')
    monkeypatch.setattr(ops_auto, 'ACTIONS', tmp_path / 'actions.log')
    handed = []
    monkeypatch.setattr(ops_auto, 'board_handoff', lambda kind, text: handed.append((kind, text)))
    return handed


def test_once_per_clock_hour(monkeypatch, tmp_path):
    handed = _setup(monkeypatch, tmp_path)
    calls = []
    ok = json.dumps({'at': 'x', 'shared_graph_scans': 0, 'shared_graph_read': 0, 'kind_scans': {}})
    run = lambda: calls.append(1) or Done(0, ok + '\n')   # noqa: E731
    at = datetime(2026, 11, 12, 14, 5).timestamp()
    assert ops_auto.vector_index_usage(clock=lambda: at, run=run)['shared_graph_scans'] == 0
    assert ops_auto.vector_index_usage(clock=lambda: at + 600, run=run) is None       # same hour
    assert ops_auto.vector_index_usage(clock=lambda: at + 3600, run=run) is not None  # next hour
    assert len(calls) == 2 and handed == []


def test_a_failed_hour_is_handed_to_search_and_rag(monkeypatch, tmp_path):
    handed = _setup(monkeypatch, tmp_path)
    at = datetime(2026, 11, 12, 15, 1).timestamp()
    assert ops_auto.vector_index_usage(clock=lambda: at, run=lambda: Done(1, '')) == 'failed'

    def hung():
        raise subprocess.TimeoutExpired('x', 60)
    assert ops_auto.vector_index_usage(clock=lambda: at + 3600, run=hung) == 'failed'
    assert [kind for kind, _ in handed] == ['vector_index_usage'] * 2
    assert ops_auto.TEAM['vector_index_usage'] == '검색과 RAG'
