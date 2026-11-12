"""Private test clusters left behind by a dead test are stopped, never deleted (PM 11-12).

11-12: two rehearsal clusters (/private/tmp/a2a-adapter-pg-*) had run since 11-11 11:25 with ppid 1 and no
clients, holding memory and the rehearsal port. The rehearsal stops such orphans when it starts and ops_auto
does it once a day; folders older than 7 days are only listed.
"""
import json
import os
import time

from scripts import ops_auto
from scripts import rehearse_storage_adapter_postgres as rehearsal

ROOT_A = '/private/tmp/a2a-adapter-pg-aaaa1111'
ROOT_B = '/private/tmp/a2a-adapter-pg-bbbb2222'
ROOT_C = '/private/tmp/a2a-adapter-pg-cccc3333'
PS = '\n'.join([
    f'  101     1 01-00:59:15 /opt/homebrew/opt/postgresql@18/bin/postgres -D {ROOT_A}/data -k {ROOT_A}/socket -p 55447',
    f'  102     1    02:10:00 /opt/homebrew/opt/postgresql@18/bin/postgres -D {ROOT_B}/data -k {ROOT_B}/socket',
    f'  103   900 01-02:00:00 /opt/homebrew/opt/postgresql@18/bin/postgres -D {ROOT_C}/data',
    f'  104     1    13:54:52 /opt/homebrew/opt/postgresql@18/bin/postgres -D {ROOT_C}/data',
    '  105     1 09-00:00:00 /opt/homebrew/opt/postgresql@18/bin/postgres -D /private/tmp/other-cluster/data',
    '  106     1 09-00:00:00 /opt/homebrew/opt/postgresql@18/bin/postgres -D gateway-data/postgres18/data',
])
ROOT_D = '/private/tmp/a2a-adapter-pg-dddd4444'


def test_only_old_parentless_idle_clusters_with_the_prefix_are_stopped():
    stopped = []
    result = rehearsal.stop_orphan_clusters(ps=lambda: PS, connections=lambda root: 1 if root == ROOT_C else 0,
                                            stop=lambda root: stopped.append(root) or True, folders=[])
    assert stopped == [ROOT_A]                                   # B is younger than 6 h, C has a client / a parent
    assert result['kept'] == [{'root': ROOT_C, 'clients': 1}]
    assert result['old_folders'] == []


def test_unknown_connections_keep_the_cluster_and_folders_are_only_listed(tmp_path):
    old, new = tmp_path / 'a2a-adapter-pg-old', tmp_path / 'a2a-adapter-pg-new'
    old.mkdir()
    new.mkdir()
    week = time.time() - 8 * 86400
    os.utime(old, (week, week))
    result = rehearsal.stop_orphan_clusters(ps=lambda: PS, connections=lambda root: None,
                                            stop=lambda root: (_ for _ in ()).throw(AssertionError('stopped')),
                                            folders=[old, new])
    assert result['stopped'] == [] and result['kept'][0]['clients'] is None
    assert result['old_folders'] == [str(old)]
    assert old.is_dir() and new.is_dir()                         # nothing is deleted


def test_a_cluster_another_process_still_names_is_kept():
    ps = '\n'.join([f'  201     1 02-00:00:00 /opt/homebrew/bin/postgres -D {ROOT_D}/data -k {ROOT_D}/socket',
                    f'  202   300    30:00 .venv/bin/python -m scripts.embeddings_kind_indexes migrate --dsn-file {ROOT_D}/rehearsal.dsn'])
    result = rehearsal.stop_orphan_clusters(ps=lambda: ps, connections=lambda root: 0,
                                            stop=lambda root: (_ for _ in ()).throw(AssertionError('stopped')), folders=[])
    assert result['kept'] == [{'root': ROOT_D, 'in_use': True}] and result['stopped'] == []


def test_etime_forms():
    assert rehearsal._etime_seconds('01-00:59:15') == 86400 + 3555
    assert rehearsal._etime_seconds('13:54:52') == 50092
    assert rehearsal._etime_seconds('37:43') == 2263


def test_ops_auto_runs_once_a_day_and_hands_off_only_with_findings(monkeypatch, tmp_path):
    monkeypatch.setattr(ops_auto, 'ORPHAN_STATE', tmp_path / 'state.json')
    monkeypatch.setattr(ops_auto, 'ACTIONS', tmp_path / 'actions.log')
    handed = []
    monkeypatch.setattr(ops_auto, 'board_handoff', lambda kind, text: handed.append((kind, text)))
    found = {'stopped': [{'root': ROOT_A}], 'kept': [], 'old_folders': [ROOT_B]}
    assert ops_auto.orphan_clusters(run=lambda: found) == {'stopped': 1, 'kept': 0, 'old_folders': 1}
    assert handed[0][0] == 'orphan_clusters'
    assert 'a2a-adapter-pg-aaaa1111' in handed[0][1] and '삭제는 사용자 결정' in handed[0][1]
    assert ops_auto.orphan_clusters(run=lambda: found) is None   # same day: nothing again
    assert len(handed) == 1
    (tmp_path / 'state.json').write_text(json.dumps({'day': '2000-01-01'}))
    assert ops_auto.orphan_clusters(run=lambda: {'stopped': [], 'kept': [], 'old_folders': []})['stopped'] == 0
    assert len(handed) == 1                                      # a clean day writes the actions log only
