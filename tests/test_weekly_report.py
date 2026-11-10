"""Weekly evidence report (11-10): issue building, Monday publishing, pages, Markdown and sitemap."""
import json
import time
from datetime import datetime, timezone

from agent_market.concierge import growth_pages as g
from agent_market.concierge import weekly_report as w
from tests.test_growth_pages import agent, client, write  # noqa: F401 (fixture)

CAPTURED = datetime(2026, 11, 9, 12, 39, tzinfo=timezone.utc)
END = CAPTURED.timestamp()


def snap(agents, captured=CAPTURED):
    return g.clean({'version': 1, 'captured_at': captured.isoformat(), 'tasks': [], 'catalog': agents})


def sample():
    recent = lambda days: END - days*86400
    return [agent(1, kind='mcp', verified_at=recent(1), last_check_at=recent(0.5), category='web_search'),
            agent(2, kind='mcp', verified_at=recent(9), last_check_at=recent(0.5), category='web_search'),  # older than the week
            agent(3, kind='a2a', verified_at=recent(2), last_check_at=recent(1), category='finance_crypto'),
            agent(4, kind='x402', last_check_at=recent(3), category='finance_crypto'),   # trial call only
            agent(5, kind='x402', last_check_at=recent(10), category='finance_crypto')]  # checked before the week


def test_issue_counts_lists_and_week_id(monkeypatch):
    monkeypatch.setattr(time, 'time', lambda: END + 600)
    issue = w.build(snap(sample()))
    assert issue['week'] == '2026-W45'  # the day before a Monday-morning snapshot names the week just ended
    assert w.issue_id(datetime(2026, 11, 16, 0, 30, tzinfo=timezone.utc)) == '2026-W46'
    assert issue['counts']['executed'] == 2 and issue['counts']['executed_by_kind'] == {'mcp': 1, 'a2a': 1, 'x402': 0}
    assert [a['id'] for a in issue['top']['mcp']] == [1] and [a['id'] for a in issue['top']['a2a']] == [3]
    assert issue['basis']['x402'] == 'trial' and [a['id'] for a in issue['top']['x402']] == [4]
    assert issue['categories'] == {'web_search': 2, 'finance_crypto': 3} and issue['changes'] is None


def test_changes_against_the_previous_issue(monkeypatch):
    monkeypatch.setattr(time, 'time', lambda: END + 600)
    previous = w.build(snap(sample()[:3]))
    previous['week'] = '2026-W44'
    issue = w.build(snap(sample()[1:]), previous)
    assert issue['previous'] == '2026-W44'
    assert issue['changes']['added'] == 2 and issue['changes']['removed'] == 1
    assert issue['changes']['by_category'] == {'finance_crypto': 2, 'web_search': -1}


def test_publish_writes_once_and_pages_render(client, monkeypatch):
    monkeypatch.setattr(time, 'time', lambda: END + 600)
    c, folder = client
    assert w.publish(folder/w.FOLDER, snap(sample())) == '2026-W45'
    assert w.publish(folder/w.FOLDER, snap(sample())) is None  # an issue is never rewritten
    page = c.get('/reports/weekly/2026-W45', headers={'Accept': 'text/html'})
    assert page.status_code == 200 and 'Execution check succeeded 08 Nov 2026' in page.text
    assert 'with a successful trial call and health check this week' in page.text and 'first issue' in page.text
    md = c.get('/reports/weekly', headers={'Accept': 'text/markdown'}).text
    assert md.startswith('# Weekly agent evidence') and '[2026-W45](https://agentconcierge.biz/reports/weekly/2026-W45)' in md
    assert c.get('/reports/weekly/2026-W01').status_code == 404 and c.get('/reports/weekly/latest').status_code == 404
    assert '/reports/weekly/2026-W45' in g.sitemap_paths()
    (folder/w.FOLDER/'2026-W46.json').write_text(json.dumps({'version': 1, 'week': 'other'}))
    assert c.get('/reports/weekly/2026-W46').status_code == 404  # a malformed file is not served


def test_jobs_publish_weekly_only_on_monday(tmp_path):
    import pytest
    TaskPagesRefresher = pytest.importorskip('agent_market.concierge.task_pages_job').TaskPagesRefresher  # jobs releases only
    out = tmp_path/'public-pages'/'task-pages.json'
    raw = {'version': 1, 'captured_at': CAPTURED.isoformat(), 'tasks': [], 'catalog': sample()}
    sunday = TaskPagesRefresher(None, out=out, clock=lambda: datetime(2026, 11, 15, 4, tzinfo=timezone.utc).timestamp(), categories=[])
    sunday.publish_weekly(raw)
    assert not (tmp_path/'public-pages'/'weekly').exists()
    monday = TaskPagesRefresher(None, out=out, clock=lambda: datetime(2026, 11, 15, 19, tzinfo=timezone.utc).timestamp(), categories=[])
    monday.publish_weekly(raw)  # 04:00 KST Monday
    assert (tmp_path/'public-pages'/'weekly'/'2026-W45.json').exists()
