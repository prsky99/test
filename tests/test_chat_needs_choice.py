"""11-05: a low-confidence Chat answer (status needs_choice) lets the visitor choose one of the options."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JS = (ROOT / 'new/en/assets/operating.js').read_text()


def _body(name):
    return JS.split('function ' + name + '(', 1)[1].split('\n}\n', 1)[0]


def test_needs_choice_shows_every_option_and_the_chooser():
    assert "const choosing = data?.data?.status === 'needs_choice' && cards.length > 1;" in JS
    assert "bubble.innerHTML = choosing ? cards.join('') : cards[0]" in JS
    assert 'if (choosing) chatChoice(bubble, choices);' in JS


def test_choosing_keeps_one_card_and_can_be_undone_without_running_anything():
    body = _body('chatChoice')
    for text in ('Choose this option', 'Say more', 'Change choice', "aria-pressed", "new CustomEvent('chat-choice'"):
        assert text in body
    assert 'cards.forEach((other, i) => { other.hidden = i !== index; });' in body
    # Text only: names reach the page through textContent and attributes, never markup; nothing is sent.
    assert 'innerHTML' not in body and 'fetch(' not in body and 'sendChat(' not in body


def test_side_panel_follows_the_choice_and_hidden_cards_stay_hidden():
    ui = (ROOT / 'new/en/assets/pearl-ui.js').read_text()
    assert "document.addEventListener('chat-choice'" in ui and 'chatDetails(bubble.__chatData,index)' in ui
    css = (ROOT / 'new/en/assets/pearl-live.css').read_text()
    assert '.chat-recommendation[hidden],.chat-choice [hidden],.chat-choose-btn[hidden]{display:none!important}' in css
    assert '#chatMessages .chat-choose-btn{min-height:44px!important}' in css
