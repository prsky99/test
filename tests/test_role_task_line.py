"""The first line from role-task results reads only the four snapshot fields and never makes one up (PM 11-16 21:13)."""
from agent_market.concierge.role_task_line import agent_line, best, facts, line


def role(**kw):
    base = {'role': 'papers.search', 'tasks_run': 6, 'tasks_correct': 5, 'success_days': 2,
            'last_checked': '2026-11-18T09:12:00+0900'}
    base.update(kw)
    return base


def test_the_line_says_what_was_measured():
    assert line(role()) == 'Correct on 5 of 6 role tasks · checked on 2 different days · last checked 2026-11-18'
    assert line(role(tasks_run=1, tasks_correct=1, success_days=1)) == \
        'Correct on 1 of 1 role task · checked on 1 day · last checked 2026-11-18'
    assert line(role(tasks_correct=0, success_days=0)).startswith('Correct on 0 of 6 role tasks · checked on 0 different days')


def test_without_the_four_fields_nothing_is_shown_so_today_s_display_stays():
    old = {'role': 'papers.search', 'score': 91, 'verified_pearl': True, 'tested_at': '2026-11-16T09:12:00+0900'}
    assert line(old) is None and agent_line({'roles': [old]}) is None and agent_line(None) is None
    for bad in (role(tasks_run=0), role(tasks_correct=7), role(tasks_run='6'), role(tasks_run=True),
                role(success_days=-1), role(last_checked=None), role(last_checked='yesterday')):
        assert facts(bad) is None and line(bad) is None


def test_an_agent_speaks_for_its_best_role():
    a = role(role='news.search', tasks_correct=3, tasks_run=3, success_days=1)
    b = role(role='papers.search')
    assert best([a, b])['role'] == 'papers.search'
    assert agent_line({'roles': [a, {'role': 'x'}, b]}) == \
        'papers.search: Correct on 5 of 6 role tasks · checked on 2 different days · last checked 2026-11-18'
