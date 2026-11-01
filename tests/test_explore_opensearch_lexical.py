"""OpenSearch lexical candidates are optional: PostgreSQL serves unless explicitly enabled, and on any failure."""
import io
import json
import os
import urllib.error

import pytest

from agent_market.concierge import opensearch_lexical as ol
from scripts import explore_opensearch_sync as sync

ON = ol.parse_settings(json.dumps({'mode': 'on', 'url': 'http://127.0.0.1:9200'}))
SHADOW = ol.parse_settings(json.dumps({'mode': 'shadow', 'url': 'http://localhost:9200', 'shadow_rate': 1}))


@pytest.mark.parametrize('raw', [
    'not json', '[]', '{"mode": "off", "url": "http://127.0.0.1:9200"}', '{"mode": "fast", "url": "http://127.0.0.1:9200"}',
    '{"mode": "on", "url": "http://10.0.0.5:9200"}', '{"mode": "on", "url": "https://127.0.0.1:9200"}',
    '{"mode": "on", "url": "http://user@127.0.0.1:9200"}', '{"mode": "on", "url": "http://127.0.0.1:9200/other"}',
    '{"mode": "on", "url": "http://127.0.0.1:9200", "index": "../x"}',
    '{"mode": "on", "url": "http://127.0.0.1:9200", "timeout_ms": 10}',
    '{"mode": "on", "url": "http://evil.example:9200"}'])
def test_only_a_valid_loopback_configuration_enables_opensearch(raw):
    assert ol.parse_settings(raw) is None


def test_valid_settings_point_at_the_alias_on_loopback():
    assert ON == {'mode': 'on', 'search': 'http://127.0.0.1:9200/agentcon-lexical/_search', 'timeout': 0.3, 'rate': 0.2}


def test_settings_file_must_be_owner_only(tmp_path, monkeypatch):
    monkeypatch.setenv('AGENTCON_PROJECT_ROOT', str(tmp_path))
    (tmp_path / 'gateway-data').mkdir()
    path = tmp_path / 'gateway-data' / 'explore-opensearch.json'
    path.write_text(json.dumps({'mode': 'on', 'url': 'http://127.0.0.1:9200'}))
    os.chmod(path, 0o644)
    assert ol._Settings().current() is None
    os.chmod(path, 0o600)
    assert ol._Settings().current()['mode'] == 'on'
    monkeypatch.delenv('AGENTCON_PROJECT_ROOT')
    assert ol._Settings().current() is None


def test_query_mirrors_the_postgres_predicate():
    every = ol.query_body(['weather', 'forecast'], ' ', 'mcp', None)
    must = every['query']['bool']['must'][0]['bool']['must']
    assert len(must) == 2 and every['query']['bool']['filter'] == [{'term': {'eligible': True}}, {'term': {'kind': 'mcp'}}]
    anyone = ol.query_body(['weather', 'forecast'], ' OR ', None, 'finance')
    assert anyone['query']['bool']['must'][0]['bool']['minimum_should_match'] == 1
    assert {'term': {'category': 'finance'}} in anyone['query']['bool']['filter'] and anyone['size'] == 300


def test_off_uses_postgres_only(monkeypatch):
    monkeypatch.setattr(ol._settings, 'current', lambda: None)
    def never(*a):
        raise AssertionError('OpenSearch must not be called when off')
    assert ol.lexical_ids(['a'], ' ', None, None, lambda: [1, 2], searcher=never) == [1, 2]


def test_on_serves_opensearch_and_falls_back_on_failure(monkeypatch):
    monkeypatch.setattr(ol, '_breaker', ol._Breaker())
    postgres_calls = []
    def postgres():
        postgres_calls.append(1); return [9]
    assert ol.lexical_ids(['a'], ' ', None, None, postgres, config=ON, searcher=lambda *a: [3, 4]) == [3, 4]
    assert postgres_calls == []
    def broken(*a):
        raise ol.Unavailable('timeout')
    assert ol.lexical_ids(['a'], ' ', None, None, postgres, config=ON, searcher=broken) == [9]
    # The pause skips OpenSearch entirely, so a slow engine costs one timeout, not one per search.
    seen = []
    assert ol.lexical_ids(['a'], ' ', None, None, postgres, config=ON, searcher=lambda *a: seen.append(1) or [5]) == [9]
    assert seen == []


def test_shadow_serves_postgres_and_records_overlap(monkeypatch):
    shadow = ol._Shadow()
    monkeypatch.setattr(ol, '_shadow', shadow)
    submitted = []
    monkeypatch.setattr(shadow, 'submit', lambda *a: submitted.append(a))
    assert ol.lexical_ids(['a'], ' ', 'a2a', None, lambda: [1, 2, 3], config=SHADOW, sample=lambda: 0.0) == [1, 2, 3]
    assert submitted and submitted[0][5] == [1, 2, 3]
    row = shadow.compare(SHADOW, ['a'], ' ', 'a2a', None, [1, 2, 3], 0.05, searcher=lambda *a: [2, 3, 4])
    assert row['shared'] == 2 and row['jaccard'] == 0.5 and shadow.totals['compared'] == 1


def test_search_rejects_bad_responses():
    class Response(io.BytesIO):
        status = 200
        def __enter__(self): return self
        def __exit__(self, *a): return False
    good = lambda req, timeout: Response(json.dumps({'hits': {'hits': [{'_id': '7'}, {'_id': '9'}]}}).encode())
    assert ol.search(ON, ['a'], ' ', None, None, opener=good) == [7, 9]
    for payload in (b'{}', b'not json', json.dumps({'hits': {'hits': [{'_id': '-1'}]}}).encode()):
        with pytest.raises(ol.Unavailable):
            ol.search(ON, ['a'], ' ', None, None, opener=lambda req, timeout, p=payload: Response(p))


class FakeEngine:
    def __init__(self, serving=None):
        self.indices, self.alias, self.calls = {}, list(serving or []), []
        for name in self.alias:
            self.indices[name] = 100

    def call(self, method, path, body=None, ndjson=False):
        self.calls.append((method, path))
        name = path.strip('/').split('/')[0]
        if method == 'PUT' and path.count('/') == 1:
            self.indices[name] = 0; return {}
        if path.endswith('/_bulk'):
            self.indices[name] += body.count(b'\n') // 2; return {'errors': False}
        if path.endswith('/_count'):
            return {'count': self.indices[name]}
        if path == f'/_alias/{sync.ALIAS}':
            if not self.alias:
                raise urllib.error.HTTPError(path, 404, 'missing', {}, None)
            return {name: {} for name in self.alias}
        if path == '/_aliases':
            for action in body['actions']:
                if 'add' in action: self.alias.append(action['add']['index'])
                else: self.alias.remove(action['remove']['index'])
            return {}
        if method == 'DELETE':
            self.indices.pop(name, None); return {}
        return {}


def rows(n):
    return [(i, f'n{i}', 'd', 'mcp', None, True, 1.0) for i in range(1, n + 1)]


def test_rebuild_swaps_the_alias_and_removes_the_old_build():
    engine = FakeEngine(serving=['agentcon-lexical-old'])
    result = sync.rebuild(engine, rows(120), now=lambda: 0)
    assert result['count'] == 120 and engine.alias == [result['index']] and 'agentcon-lexical-old' not in engine.indices
    # The new index answers searches (warm-up) before the alias points at it.
    paths = [path for _, path in engine.calls]
    assert any(p.endswith('/_search') for p in paths[:paths.index('/_aliases')])


def test_index_keeps_ids_only_and_preloads_its_files():
    assert sync.MAPPINGS['_source'] == {'enabled': False}
    assert sync.MAPPINGS['properties']['kind']['doc_values'] is False
    assert 'tim' in sync.SETTINGS['store']['preload']


def test_rebuild_keeps_serving_index_when_the_new_build_is_short():
    engine = FakeEngine(serving=['agentcon-lexical-old'])
    with pytest.raises(RuntimeError):
        sync.rebuild(engine, rows(50), now=lambda: 0)
    assert engine.alias == ['agentcon-lexical-old'] and list(engine.indices) == ['agentcon-lexical-old']


def test_sync_refuses_a_non_loopback_engine():
    with pytest.raises(ValueError):
        sync.Client('http://10.1.2.3:9200')
