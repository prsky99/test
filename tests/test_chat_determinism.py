"""Chat answers do not change with model load, and request leads are not capabilities (2026-11-04).

The 1k Chat evaluation found every flaky verdict on the optional local-model rewrite/summary path
(a busy slot or a slow reply fell back to rules), and question-form requests losing their capability
to the word "there". See the stage 0 section of the 2026-11-04 accuracy plan in reports/.
"""
import json

import httpx
import pytest

from agent_market.concierge.llm import LocalLLM
from agent_market.concierge.selection import capability_terms

ORIGINAL = '\uc545\uc131 \uc870\ud56d \uac80\ud1a0'


def model_with(answers):
    calls = []

    def respond(request):
        calls.append(json.loads(request.content))
        answer = answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        content = json.dumps({'segments': [{'source': ORIGINAL, 'english': answer}]})
        return httpx.Response(200, json={'model': 'test', 'choices': [
            {'finish_reason': 'stop', 'message': {'role': 'assistant', 'content': content}}]})
    model = LocalLLM(url='http://127.0.0.1:8000', model='test', provider='openai', concurrency=1,
                     http=httpx.Client(transport=httpx.MockTransport(respond)))
    return model, calls


def test_a_handled_request_keeps_its_rewrite_while_the_model_is_busy():
    model, calls = model_with(['Contract review for unfavorable clauses'])
    assert model.rewrite_task(ORIGINAL) == 'Contract review for unfavorable clauses'
    assert model._slots.acquire(blocking=False)  # another request now holds the only slot
    try:
        assert model.rewrite_task(ORIGINAL) == 'Contract review for unfavorable clauses'
    finally:
        model._slots.release()
    assert len(calls) == 1


def test_failures_are_not_remembered_and_guards_run_before_the_cache():
    model, calls = model_with([httpx.ReadTimeout('slow'), 'Contract review for unfavorable clauses'])
    assert model.rewrite_task(ORIGINAL) is None
    model._broken_until = 0  # the failure pause has passed
    assert model.rewrite_task(ORIGINAL) == 'Contract review for unfavorable clauses'
    assert model.rewrite_task('token=private-value ' + ORIGINAL) is None
    assert len(calls) == 2


def test_the_cache_is_bounded(monkeypatch):
    from agent_market.concierge import llm
    monkeypatch.setattr(llm, 'TASK_CACHE_SIZE', 2)
    model, _ = model_with([])
    for n, text in enumerate((ORIGINAL, ORIGINAL + ' \ud558\ub098', ORIGINAL + ' \ub458')):
        model._bounded_task_answer = lambda *a, n=n: f'answer {n}'
        model._bounded_task_call('system', None, text, 1.0)
    assert len(model._task_cache) == 2 and ('system', ORIGINAL) not in model._task_cache


@pytest.mark.parametrize('task,terms', [
    ('Is there an agent or API that can track a flight in real time?', ['track', 'flight']),
    ('Is there an agent or API that can compare hotel prices in Rome?', ['compare', 'hotel']),
    ('Do you know of any tools that can send SMS reminders?', ['send', 'sms', 'reminders']),
    ('We are a small team building a travel startup. Doing this by hand takes hours every week, so we need an '
     'agent or API that can generate client code from a Swagger file. It should be reliable and reasonably cheap.',
     ['generate', 'client', 'code']),
    ('I run a newsroom tool and my current tooling keeps failing. I am looking for something that can compare '
     'two versions of a document, ideally without a long setup.', ['compare', 'two', 'versions', 'document']),
    # Unchanged: no lead, or a lead that is the whole request.
    ('research papers about battery recycling', ['papers']),
    ('Book a flight', ['book', 'flight']),
])
def test_request_leads_are_not_capabilities(task, terms):
    assert capability_terms(task) == terms
