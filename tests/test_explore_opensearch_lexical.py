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


class DocEngine(FakeEngine):
    """FakeEngine that keeps document ids, so updates and deletes can be counted."""
    def __init__(self, serving=None):
        super().__init__(serving)
        self.docs = {name: set(range(1, 101)) for name in self.indices}
        self.bulk_lines = []

    def call(self, method, path, body=None, ndjson=False):
        name = path.strip('/').split('/')[0]
        if path.endswith('/_bulk'):
            self.calls.append((method, path))
            lines = body.decode().strip().split('\n')
            self.bulk_lines.append(len(lines))
            docs, items, i = self.docs.setdefault(name, set()), [], 0
            while i < len(lines):
                action = json.loads(lines[i])
                if 'delete' in action:
                    rid = int(action['delete']['_id'])
                    items.append({'delete': {'status': 200 if rid in docs else 404}}); docs.discard(rid); i += 1
                else:
                    docs.add(int(action['index']['_id'])); items.append({'index': {'status': 201}}); i += 2
            self.indices[name] = len(docs)
            return {'errors': any(x['delete']['status'] == 404 for x in items if 'delete' in x), 'items': items}
        if method == 'PUT' and path.count('/') == 1:
            self.docs[name] = set()
        return super().call(method, path, body, ndjson)


def test_rounds_update_only_changed_listings_and_build_in_full_at_night(tmp_path, monkeypatch):
    import time as _time
    state = tmp_path / 'state.json'
    engine = DocEngine()
    day = _time.mktime((2026, 11, 15, 15, 0, 0, 0, 0, -1))
    first = sync.sync_rows(engine, lambda: rows(120), now=lambda: day, state_path=state)
    assert first['mode'] == 'full' and first['reason'] == 'no saved state' and engine.alias == [first['index']]
    # 3 listings change, 2 are gone, 1 is new: one small bulk into the serving index, no new index, no swap
    changed = [(i, f'n{i}', 'd', 'mcp', None, i not in (5, 6, 7), 1.0) for i in range(3, 121)] + [(121, 'new', 'd', 'mcp', None, True, 1.0)]
    puts = sum(1 for m, p in engine.calls if m == 'PUT' and p.count('/') == 1)
    second = sync.sync_rows(engine, lambda: changed, now=lambda: day + 600, state_path=state)
    assert second == {'index': first['index'], 'mode': 'update', 'count': 119, 'upserted': 4, 'deleted': 2}
    assert engine.alias == [first['index']] and sum(1 for m, p in engine.calls if m == 'PUT' and p.count('/') == 1) == puts
    assert sync.sync_rows(engine, lambda: changed, now=lambda: day + 1200, state_path=state)['upserted'] == 0
    # 03:20-03:45 once a night: a full build, then updates again
    night = _time.mktime((2026, 11, 16, 3, 25, 0, 0, 0, -1))
    assert sync.sync_rows(engine, lambda: changed, now=lambda: night, state_path=state)['reason'] == 'nightly'
    assert sync.sync_rows(engine, lambda: changed, now=lambda: night + 600, state_path=state)['mode'] == 'update'


def test_a_large_change_or_a_foreign_alias_builds_in_full(tmp_path):
    state = tmp_path / 'state.json'
    engine = DocEngine()
    sync.sync_rows(engine, lambda: rows(120), now=lambda: 0, state_path=state)
    moved = [(i, f'x{i}', 'd', 'mcp', None, True, 1.0) for i in range(1, 121)]
    out = sync.sync_rows(engine, lambda: moved, now=lambda: 600, state_path=state)
    assert out['mode'] == 'full' and out['reason'].startswith('update refused')
    engine.alias[:] = ['agentcon-lexical-someone-else']; engine.indices['agentcon-lexical-someone-else'] = 120
    engine.docs['agentcon-lexical-someone-else'] = set(range(1, 121))
    assert sync.sync_rows(engine, lambda: moved, now=lambda: 1200, state_path=state)['reason'] == 'serving index differs from the saved state'


def test_update_batches_never_split_an_index_action_from_its_document(tmp_path, monkeypatch):
    monkeypatch.setattr(sync, 'BATCH', 3)
    state = tmp_path / 'state.json'
    engine = DocEngine()
    sync.sync_rows(engine, lambda: rows(120), now=lambda: 0, state_path=state)
    engine.bulk_lines.clear()
    later = [(i, f'n{i}' + ('!' if i <= 7 else ''), 'd', 'mcp', None, True, 1.0) for i in range(1, 119)]
    out = sync.sync_rows(engine, lambda: later, now=lambda: 600, state_path=state)
    assert out == {'index': out['index'], 'mode': 'update', 'count': 118, 'upserted': 7, 'deleted': 2}
    assert engine.bulk_lines == [6, 6, 4]             # 3 ops a batch: 3 indexes, 3 indexes, 1 index + 2 deletes


def test_sql_source_reads_digests_first_and_only_changed_rows_in_full():
    """11-15: the first update round took 8.8 s, about 6 of them reading every listing's text."""
    executed = []

    class Cursor:
        def __init__(self, rows): self.rows = rows
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def __iter__(self): return iter(self.rows)
        def execute(self, sql, params=None): executed.append((sql, params))
        def fetchall(self): return [(7, 'n7', 'd', 'mcp', None, True, 1.0)]

    class Connection:
        def cursor(self, name=None):
            return Cursor([('7', 'abc'), ('8', 'def')])

    source = sync.SqlSource(Connection())
    assert source.digests() == {'7': 'abc', '8': 'def'}
    assert source.fetch(['7']) == [(7, 'n7', 'd', 'mcp', None, True, 1.0)] and executed[-1][1] == ([7],)
    assert source.fetch([]) == [] and len(executed) == 2
    assert 'md5(' in sync.DIGESTS and sync.CHANGED.endswith('WHERE r.id = ANY(%s)')
    assert sync.ELIGIBLE in sync.DIGESTS and sync.ELIGIBLE in sync.LISTINGS
