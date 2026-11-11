import asyncio
import logging

from agent_market.concierge import execution_errors as ee


def run(headers, caplog):
    async def app(scope, receive, send):
        ee.record_failure('ex_' + 'a' * 24, 7, 'mcp', 'INVALID_INPUT', stage='admission')
    with caplog.at_level(logging.WARNING, logger='agent_market.execution'):
        asyncio.run(ee.QAMark(app)({'type': 'http', 'headers': headers}, None, None))
    return [r.getMessage() for r in caplog.records if 'Execution failure' in r.getMessage()]


def test_measurement_header_marks_the_failure_line(caplog):
    lines = run([(b'x-agentcon-qa', b'real_task_score')], caplog)
    assert lines and lines[-1].endswith(' qa=real_task_score')


def test_no_or_unsafe_header_leaves_the_line_unchanged(caplog):
    for headers in ([], [(b'x-agentcon-qa', b'<script> x')], [(b'x-agentcon-qa', b'A' * 80)]):
        caplog.clear()
        lines = run(headers, caplog)
        assert lines and ' qa=' not in lines[-1]
    assert ee._QA.get() == ''
