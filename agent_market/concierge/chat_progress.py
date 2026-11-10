"""Progress steps of one Chat answer, streamed to the visitor while it is being prepared.

A visitor who sees only a spinner feels the wait longer and less certain (Tan & Nov,
CHI 2026); each step names the work actually under way. The sink lives in a context
variable, so a request without a stream (and every other caller) pays nothing."""
import contextvars
import time

LABELS = {
    'review': 'Reading your request',
    'understand': 'Understanding the task and its conditions',
    'search': 'Searching active agents',
    'rephrase': 'Summarizing a long request to search again',
    'respell': 'Checking the spelling of the request',
    'narrow': 'Searching again with the capability the candidates share',
    'split': 'Matching each part of the request',
    'cover': 'Checking the matches cover the whole task',
    'workflows': 'Checking published workflows',
    'prepare': 'Preparing recommendations',
}
_sink = contextvars.ContextVar('chat_progress_sink', default=None)


def step(code):
    """Report that STEP has started; a no-op unless a stream is listening."""
    from .retrieval_metrics import mark
    mark(code)  # Server-Timing step durations for public requests (11-11)
    sink = _sink.get()
    if sink is not None:
        try:
            sink(code)
        except Exception:
            pass  # progress is advisory and never fails an answer


def listening(emit, function):
    """FUNCTION run with EMIT receiving {'type': 'progress', ...} events for each step."""
    started = time.monotonic()

    def sink(code):
        emit({'type': 'progress', 'step': code, 'label': LABELS.get(code, 'Working'),
              'elapsed_ms': int((time.monotonic() - started) * 1000)})

    def run(*args, **kwargs):
        token = _sink.set(sink)
        try:
            return function(*args, **kwargs)
        finally:
            _sink.reset(token)
    return run
