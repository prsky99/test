"""F17 (review 11-14, PM): templates, necklaces in testing, verified necklaces and paused ones are told apart, and
nothing reads as verified while no necklace passed its gate."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_template_cards_carry_their_standing_and_default_to_template():
    source = (ROOT / 'new/live-assets/workflow-library.js').read_text()
    assert source == (ROOT / 'new/en/assets/workflow-library.js').read_text()
    for label in ("'Verified necklace'", "'In testing'", "'Paused'", "'Template'"):
        assert label in source, label
    assert "state==='verified'" in source and 'necklace gate' in source
    assert 'standingBadge(template),el(\'span\',\'wf-library-agent-count\'' in source      # on every card
    assert 'standingBadge(template),heading' in source                                    # and in the preview


def test_no_screen_calls_templates_verified():
    pages = [ROOT / 'agent_market/concierge/front.py', ROOT / 'extracted_html.txt'] + sorted((ROOT / 'new/en').glob('*.html'))
    for path in pages:
        assert 'Loading verified templates' not in path.read_text(encoding='utf-8'), path


def test_without_a_necklace_nothing_claims_one(monkeypatch, tmp_path):
    from agent_market.concierge import check_route, necklace_surface
    monkeypatch.setenv('AGENTCON_PROJECT_ROOT', str(tmp_path))       # no necklaces.json: nothing offered
    assert necklace_surface.listing()['necklaces'] == [] and necklace_surface.llms_section('https://x') == ''
    assert necklace_surface.tools() == [] and necklace_surface.skills('https://x') == []
    for tool in check_route.TOOLS:
        assert 'if' in tool['description'] and 'run the job to the end' not in tool['description'], tool['name']


def test_a_necklace_in_testing_shows_its_count_only_and_cannot_run(monkeypatch):
    from datetime import datetime, timezone
    from agent_market.concierge import necklace_surface as ns
    snap = {'schema': ns.SCHEMA, 'generated_at': '2026-11-17T00:00:00Z', 'necklaces': [
        {'slug': 'trip-brief', 'name': 'Trip brief', 'status': 'testing', 'template_id': 7, 'tests': {'passed': 9, 'total': 12},
         'pearls': [{'resource_id': 1}], 'gate_passed_at': '2026-11-16T00:00:00Z'},
        {'slug': 'bad-count', 'status': 'testing', 'tests': {'passed': 5, 'total': 3}}]}
    now = datetime(2026, 11, 17, tzinfo=timezone.utc)
    out = ns.listing(snapshot=snap, now=now)
    assert out['necklaces'] == [] and out['in_testing'] == [
        {'slug': 'trip-brief', 'name': 'Trip brief', 'status': 'testing', 'standing': 'In testing',
         'tests': {'passed': 9, 'total': 12}, 'note': ns.TESTING_NOTE, 'template_id': 7}]
    assert ns.tools(snapshot=snap, now=now) == [] and ns.skills('https://x', snapshot=snap, now=now) == []
    assert ns.page('trip-brief', snapshot=snap, now=now)[0] == 404 and 'verified' not in ns.TESTING_NOTE.replace('not verified', '')
