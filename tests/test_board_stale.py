"""Hand-off lines waiting for a day are found by when their text last changed, not by the board's mtime (PM 11-12)."""
from datetime import datetime

from scripts import board_stale, ops_auto

HEAD = '# 현황판\n## 넘기는 일\n| 보낸 팀 | 받는 팀 | 내용 | 상태 |\n|---|---|---|---|\n'
OLD = '| 운영·SRE | 검색과 RAG | 오래된 일 | 대기 |'
EDITED = '| 운영·SRE | 검색과 RAG | 오래된 일, 메모 더함 | 대기 |'
DONE = '| PM | AI AD Coin | 끝난 일 | 완료 |'


def _snap(history, stamp, rows):
    (history / f'status-board-{stamp}.md').write_text(HEAD + '\n'.join(rows) + '\n## 공지\n', encoding='utf-8')


def test_age_restarts_when_a_line_changes(tmp_path):
    history = tmp_path / 'history'
    history.mkdir()
    _snap(history, '20261111-080000', [OLD, DONE])
    _snap(history, '20261112-090000', [OLD, DONE, EDITED])
    board = tmp_path / 'board.md'
    board.write_text(HEAD + '\n'.join([OLD, EDITED, DONE, '| 성장·유통 | PM | 새 줄 | 대기 |']) + '\n## 공지\n', encoding='utf-8')
    now = datetime(2026, 11, 12, 10, 0).timestamp()
    found = board_stale.stale(24, board=board, history=history, now=now)
    assert list(found) == ['검색과 RAG'] and len(found['검색과 RAG']) == 1      # the edited line is 1 h old
    assert found['검색과 RAG'][0]['age_hours'] == 26.0
    assert board_stale.stale(0.5, board=board, history=history, now=now)['검색과 RAG'][1]['age_hours'] == 1.0


def test_ops_auto_posts_one_line_per_receiving_team_once_a_morning(monkeypatch, tmp_path):
    monkeypatch.setattr(ops_auto, 'STALE_STATE', tmp_path / 'state.json')
    monkeypatch.setattr(ops_auto, 'ACTIONS', tmp_path / 'actions.log')
    handed = []
    monkeypatch.setattr(ops_auto, 'board_handoff', lambda kind, text: handed.append((kind, ops_auto.TEAM[kind], text)))
    found = {'검색과 RAG': [{'from': '운영·SRE', 'age_hours': 32.4, 'text': 'jobs DB 5초'},
                         {'from': '검색과 RAG', 'age_hours': 26.1, 'text': '벡터 무효화'}],
             'AI AD Coin': [{'from': 'PM', 'age_hours': 26.4, 'text': 'Sponsored 전용 표시'}]}
    at = lambda h: (lambda: datetime(2026, 11, 13, h, 5).timestamp())   # noqa: E731
    assert ops_auto.stale_handoffs(clock=at(9), find=lambda hours: found) is None
    assert ops_auto.stale_handoffs(clock=at(10), find=lambda hours: found) == {'검색과 RAG': 2, 'AI AD Coin': 1}
    assert ops_auto.stale_handoffs(clock=at(11), find=lambda hours: found) is None
    assert [(k, team) for k, team, _ in handed] == [('stale|검색과 RAG', '검색과 RAG'), ('stale|AI AD Coin', 'AI AD Coin')]
    assert '대기 줄 2개(가장 오래된 것 32시간)' in handed[0][2] and '진행 중·완료·보류(이유)' in handed[0][2]
