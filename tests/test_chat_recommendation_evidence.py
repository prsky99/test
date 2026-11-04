"""Five-point step 7: each Chat recommendation shows its recorded evidence one click from the card."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JS = (ROOT / 'new/en/assets/operating.js').read_text()


def _body(name):
    return JS.split('function ' + name + '(', 1)[1].split('\n}\n', 1)[0]


def test_card_includes_the_evidence_block():
    assert "chatWhy(item) + chatProof(item) +" in JS


def test_evidence_rows_and_unknown_come_from_the_served_fields():
    body = _body('chatProof')
    for field in ('health_checked_at', 'trial_call', 'selected_tool_check', 'ev.unknown'):
        assert field in body
    assert 'Unknown \\u2014 no record' in body and 'data-unknown' in body
    # One click: a closed <details> on the card, summary counts what is recorded.
    assert '<details class="chat-proof"><summary>' in body and ' of 3 recorded' in body
    # Values go through esc(); nothing from the server is set as markup.
    assert "esc(value)" in body


def test_trial_status_other_than_passed_or_failed_reads_unknown():
    body = _body('chatProof')
    assert 'if (trial.status !== "passed" && trial.status !== "failed") unknown.add("trial_call");' in body


def test_server_reason_text_is_preferred():
    assert 'const reason = served ? served : tool ?' in _body('chatWhy')


def test_iso_time_rejects_non_iso_values():
    body = _body('chatIsoTime')
    assert 'typeof value !== "string"' in body and '\\d{4}-\\d{2}-\\d{2}T' in body


def test_summary_meets_the_touch_target_and_side_panel_shows_it():
    css = (ROOT / 'new/en/assets/pearl-live.css').read_text()
    assert '.chat-proof>summary{display:flex;align-items:center;gap:6px;min-height:44px' in css
    ui = (ROOT / 'new/en/assets/pearl-ui.js').read_text()
    assert "['Last health check',chatIsoTime(item.evidence.health_checked_at)||'Unknown']" in ui
