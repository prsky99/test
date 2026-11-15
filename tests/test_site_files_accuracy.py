"""website.ai_readiness accuracy against the site at grading time (ops 11-15 request): structured and text answers."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import data_quality as DQ  # noqa: E402
from agent_market.necklaces import role_tasks  # noqa: E402

ROBOTS = "User-agent: GPTBot\nDisallow: /\n\nUser-agent: *\nAllow: /\n"
TRUTH = {'robots': ROBOTS, 'robots_note': None, 'llms_txt': False, 'sitemap_xml': True}


def case():
    return next(c for c in role_tasks.load() if c['case_id'] == 'site-python')


def ours(gpt='blocked', llms=False):
    return json.dumps({'result': {'domain': 'python.org', 'signals': {
        'robots_txt': {'present': True}, 'ai_crawlers': {'GPTBot': gpt, 'ClaudeBot': 'allowed (by the * rule)'},
        'llms_txt': {'present': llms}, 'sitemap_xml': {'present': True}}}})


def test_the_case_asks_for_the_live_site_check_and_counts_one_fact(monkeypatch):
    c = case()
    assert c['expect']['dynamic'] == {'site_files': 'python.org'}
    monkeypatch.setattr(DQ, 'site_truth', lambda domain: TRUTH)
    DQ._CACHE.clear()
    points, source, reasons = DQ.accuracy(c, ours(), None, role_tasks=role_tasks)
    assert points == DQ.WEIGHTS['accuracy'] and 'live site_files' in source
    points, _, reasons = DQ.accuracy(c, ours(gpt='allowed'), None, role_tasks=role_tasks)
    assert points == 0 and 'site_files off the reference' in reasons


def test_structured_answers_use_the_agent_team_judge():
    assert DQ.site_files_match(TRUTH, ours(), 'python.org') is True
    assert DQ.site_files_match(TRUTH, ours(llms=True), 'python.org') is False


def test_text_answers_need_one_right_claim_and_no_wrong_one():
    good = "python.org robots.txt: GPTBot is blocked, ClaudeBot is allowed. No llms.txt was found; sitemap.xml is present."
    assert DQ.site_files_match(TRUTH, good, 'python.org') is True
    assert DQ.site_files_match(TRUTH, "GPTBot is allowed on python.org.", 'python.org') is False
    assert DQ.site_files_match(TRUTH, "python.org has an AI readiness score of 72.", 'python.org') is False
    assert DQ.site_files_match(TRUTH, "llms.txt: not found. CCBot allowed.", 'python.org') is True


def test_unreadable_robots_needs_the_answer_to_say_so():
    truth = {'robots': None, 'robots_note': 'could not read: timeout', 'llms_txt': None, 'sitemap_xml': None}
    assert DQ.site_files_match(truth, "robots.txt could not be read (timeout).", 'python.org') is True
    assert DQ.site_files_match(truth, "GPTBot allowed.", 'python.org') is False


def test_no_reference_when_the_grader_cannot_read(monkeypatch):
    def boom(domain):
        raise RuntimeError('budget')
    monkeypatch.setattr(DQ, 'site_truth', boom)
    DQ._CACHE.clear()
    assert DQ.reference('site_files', 'python.org') is None
    points, source, _ = DQ.accuracy(case(), ours(), None, role_tasks=role_tasks)
    assert points == 0 and 'live reference unavailable' in source


def test_our_own_ledger_refusal_is_no_reference_not_an_unreadable_site(monkeypatch):
    from agent_market.fallback_agents import gold_check
    monkeypatch.setattr(gold_check, 'site_truth', lambda domain: {
        'robots': None, 'robots_note': 'could not read: Shared test budget refused the call (domain_share).',
        'llms_txt': None, 'sitemap_xml': None})
    assert DQ.site_truth('python.org') is None
    DQ._CACHE.clear()
    monkeypatch.setattr(DQ, 'site_truth', lambda domain: None)
    points, source, _ = DQ.accuracy(case(), ours(), None, role_tasks=role_tasks)
    assert points == 0 and 'live reference unavailable' in source
