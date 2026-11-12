import gzip
import json

from agent_market.collector import cap_changes


OLD = [{'name': 'get_recent_earthquakes', 'description': 'List upcoming USGS earthquake feed above a magnitude'},
       {'name': 'get_status', 'description': 'Service status'}]
NEW = [{'name': 'get_recent_earthquakes', 'description': 'Recent earthquakes'}]


def test_summary_counts_lost_words_and_tools():
    line = cap_changes.summary({'id': 7, 'kind': 'mcp'}, OLD, NEW, {'added': [], 'removed': ['get_status'], 'changed': ['get_recent_earthquakes']})
    assert line['tools_before'] == 2 and line['tools_after'] == 1
    assert line['removed'] == 1 and line['changed'] == 1
    for word in ('usgs', 'feed', 'upcoming', 'magnitude', 'status'):
        assert word in line['lost_top']
    assert 'earthquakes' not in line['lost_top'] and 'recent' not in line['lost_top']
    assert line['words_lost'] == len(line['lost_top'])


def test_no_change_writes_nothing(tmp_path):
    assert cap_changes.record({'id': 1}, OLD, OLD, {'added': [], 'removed': [], 'changed': []}, directory=tmp_path) is None
    assert cap_changes.record({'id': 1}, OLD, OLD, None, directory=tmp_path) is None
    assert not list(tmp_path.glob('cap-changes-*'))


def test_secrets_and_personal_strings_never_listed():
    tool = {'name': 'lookup', 'description': (
        'Contact admin@example.com or see https://example.com/docs?token=abc. Key sk-live4f9a8b7c6d5e '
        'ghp_1234abcd5678efgh hash 0123456789abcdef0123 user42account99x weather forecast'),
        'tags': ['AKIA1234567890ABCD', 'eyJhbGciOiJIUzI1NiJ9']}
    words = set(cap_changes.tool_words([tool]))
    assert {'weather', 'forecast', 'lookup', 'contact', 'hash', 'key'} <= words
    assert words <= {'weather', 'forecast', 'lookup', 'contact', 'hash', 'key', 'see'}, words
    for bad in ('admin', 'example', 'com', 'docs', 'token', 'abc', 'live4f9a8b7c6d5e', 'ghp', '1234abcd5678efgh',
                '0123456789abcdef0123', 'abcdef0123', 'user42account99x', 'akia1234567890abcd', 'jhb', 'gci'):
        assert bad not in words, bad
    line = cap_changes.summary({'id': 2, 'kind': 'mcp'}, [tool], [], {'added': [], 'removed': ['lookup'], 'changed': []})
    assert not any('@' in w or '/' in w or w.startswith(('sk', 'ghp', 'akia', 'eyj')) and any(c.isdigit() for c in w)
                   for w in line['lost_top'])


def test_record_appends_dated_line_and_never_raises(tmp_path, monkeypatch):
    line = cap_changes.record({'id': 3, 'kind': 'a2a'}, OLD, NEW, {'added': [], 'removed': ['get_status'], 'changed': []},
                              directory=tmp_path)
    files = list(tmp_path.glob('cap-changes-????-??-??.jsonl'))
    assert len(files) == 1 and json.loads(files[0].read_text().splitlines()[0])['id'] == 3
    assert line['kind'] == 'a2a'
    monkeypatch.setattr(cap_changes, 'summary', lambda *a: 1 / 0)
    assert cap_changes.record({'id': 4}, OLD, NEW, {'removed': ['x']}, directory=tmp_path) is None


def test_maintain_writes_day_sizes_once_and_compresses_old_files(tmp_path):
    old = tmp_path / 'cap-changes-2026-10-01.jsonl'
    old.write_text('{"id": 1}\n{"id": 2}\n')
    recent = tmp_path / 'cap-changes-2026-11-11.jsonl'
    recent.write_text('{"id": 3}\n')
    today = tmp_path / 'cap-changes-2026-11-12.jsonl'
    today.write_text('{"id": 4}\n')
    cap_changes.maintain(tmp_path, '2026-11-12')
    cap_changes.maintain(tmp_path, '2026-11-12')
    sizes = [json.loads(line) for line in (tmp_path / cap_changes.SIZES).read_text().splitlines()]
    assert sorted(s['day'] for s in sizes) == ['2026-10-01', '2026-11-11']
    assert {s['day']: s['lines'] for s in sizes} == {'2026-10-01': 2, '2026-11-11': 1}
    assert not old.exists() and gzip.open(str(old) + '.gz').read() == b'{"id": 1}\n{"id": 2}\n'
    assert recent.exists() and today.exists()


def test_default_directory_follows_project_root(tmp_path, monkeypatch):
    import importlib
    monkeypatch.setenv('AGENTCON_PROJECT_ROOT', str(tmp_path))
    fresh = importlib.reload(cap_changes)  # conftest points default_directory at tmp for every test
    assert fresh.default_directory() == tmp_path / 'logs/collector'


def test_both_surveys_record_the_change():
    import inspect
    from agent_market.collector import a2a, capabilities
    assert 'cap_changes.record(r, old, tools, changes)' in inspect.getsource(capabilities.CapabilityProber._record_usage)
    assert 'cap_changes.record(r, old, card["skills"], changes)' in inspect.getsource(a2a)
