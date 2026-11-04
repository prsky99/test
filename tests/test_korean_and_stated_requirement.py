"""Stage 1 (2026-11-04): other-language requests wait briefly for translation; a labelled
requirement in a long request leads the search."""
import json
import threading

import httpx

from agent_market.concierge import llm as llm_module
from agent_market.concierge.fast_chat import retrieval_text
from agent_market.concierge.llm import LocalLLM

KOREAN = '근처 카페 찾아줘'


def model(answer):
    def respond(request):
        content = json.dumps({'segments': [{'source': KOREAN, 'english': answer}]})
        return httpx.Response(200, json={'model': 'test', 'choices': [
            {'finish_reason': 'stop', 'message': {'role': 'assistant', 'content': content}}]})
    return LocalLLM(url='http://127.0.0.1:8000', model='test', provider='openai', concurrency=1,
                    http=httpx.Client(transport=httpx.MockTransport(respond)))


def test_a_translation_waits_for_a_busy_slot_but_a_typo_rewrite_does_not(monkeypatch):
    monkeypatch.setattr(llm_module, 'TRANSLATE_WAIT', 0.5)
    m = model('Find a nearby cafe')
    m._slots.acquire()  # another request holds the only slot ...
    threading.Timer(0.1, m._slots.release).start()  # ... and finishes shortly
    assert m.rewrite_task(KOREAN) == 'Find a nearby cafe'
    m._slots.acquire()
    try:
        assert m.rewrite_task('wheather in pariss') is None  # English keeps the no-wait path
    finally:
        m._slots.release()


def test_a_labelled_requirement_leads_and_the_original_stays_for_conditions():
    text = 'Context: a small online shop. Requirement: compose a short jingle. Nothing else is needed right now.'
    assert retrieval_text(text) == 'compose a short jingle for ' + text
    step = 'For a hobby project we want to automate one step: read recent messages in a Slack workspace. Please help.'
    assert retrieval_text(step).startswith('read recent messages in a Slack workspace for For a hobby project')
    # Short requests and requests without a label are unchanged.
    assert retrieval_text('Goal: find papers') == 'Goal: find papers'
    assert retrieval_text('weather forecast for Seoul') == 'weather forecast for Seoul'
