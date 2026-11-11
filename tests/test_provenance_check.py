"""'출처 모름' board lines close only when the file is committed everywhere it runs (11-11 PM)."""
from scripts import provenance_check as pc


def test_close_lines_closes_clean_paths_and_keeps_dirty_ones():
    lines = ['| (출처 모름) | agent_market/a.py | 미커밋 변경 |',
             '| (출처 모름, 운영에 배포됨) | agent_market/b.py | 운영에만 있음 |',
             '| (출처 모름) | agent_market/c.py | 작업본에 미커밋 |',
             '| 검색과 RAG | (알림) agent_market/a.py | 다른 줄은 그대로 |']
    found = {'cap-jobs-r1': ['agent_market/b.py']}
    out, closed, still = pc.close_lines(list(lines), found, '11-12 06:30', matches=lambda path: path != 'agent_market/c.py')
    assert closed == ['agent_market/a.py'] and still == ['agent_market/b.py', 'agent_market/c.py']
    assert out[0].startswith('| ~~(출처 모름)~~ 운영·SRE 자동 | agent_market/a.py | **자동 닫음 11-12 06:30')
    assert out[1:] == lines[1:]


def test_uncommitted_names_files_whose_content_is_in_no_commit(tmp_path, monkeypatch):
    base = tmp_path / 'rel-1' / 'agent_market'
    base.mkdir(parents=True)
    (base / 'kept.py').write_text('x = 1\n')
    (base / 'local.py').write_text('x = 2\n')
    (base / '__pycache__').mkdir()
    (base / '__pycache__' / 'kept.cpython-312.pyc').write_bytes(b'\0')
    committed = set(pc.hashes([base / 'kept.py']))
    assert pc.uncommitted({'jobs': 'rel-1'}, committed, root=tmp_path) == {'rel-1': ['agent_market/local.py']}
