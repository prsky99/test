"""A deferred workflow round names the application step that failed, never values or SQL (11-12)."""
from agent_market.service_host import _failing_step


def test_failing_step_is_the_deepest_application_frame():
    def inner():
        raise RuntimeError('statement_failed')
    try:
        inner()
    except RuntimeError as exc:
        step = _failing_step(exc)
    assert step == 'unknown'   # test frames are outside agent_market
    from agent_market import workflows
    class Boom(Exception):
        pass
    try:
        exec(compile('def run_due():\n    raise Boom("x")\nrun_due()', workflows.__file__, 'exec'), {'Boom': Boom})
    except Boom as exc:
        assert _failing_step(exc).startswith('workflows.py:') and _failing_step(exc).endswith(' run_due')
