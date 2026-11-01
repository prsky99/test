"""Normal operation cannot flood managed console/files with HTTP wire secrets."""
import logging
from pathlib import Path
import pytest

from agent_market.logger import LoggingManager
from agent_market.logger import redact_log_message
from agent_market.gateway.dashboard import LogBuffer


def test_console_and_files_share_dynamic_source_limits_and_redaction(tmp_path,monkeypatch):
    output=tmp_path/'console.log';monkeypatch.setenv('LOG_CONSOLE_FILE',str(output))
    manager=LoggingManager(log_dir=str(tmp_path/'logs'),archive_dir=str(tmp_path/'archive'),auto_start_scheduler=False)
    manager.start()
    try:
        logging.getLogger('httpcore.connection').debug('Cookie: "debug-private-placeholder"')
        logging.getLogger('agent_market.gateway.audit').debug('hidden-debug-placeholder')
        logging.getLogger('agent_market.gateway.audit').info('GET /callback?code=private-code-placeholder')
        logging.getLogger('agent_market.gateway.audit').warning('Authorization: Bearer private-token-placeholder')
        manager.set_level('ERROR',source='gateway')
        logging.getLogger('agent_market.gateway.audit').warning('hidden-warning-placeholder')
        logging.getLogger('agent_market.gateway.audit').error('visible-error-placeholder')
    finally:manager.stop()
    text=output.read_text()
    files=''.join(p.read_text() for p in (tmp_path/'logs').rglob('*.log'))
    for value in ('debug-private-placeholder','hidden-debug-placeholder','private-code-placeholder','private-token-placeholder','hidden-warning-placeholder'):
        assert value not in text and value not in files
    assert 'visible-error-placeholder' in text and '[redacted]' in text


def test_rotating_console_bounds_disk_and_closes_handler(tmp_path,monkeypatch):
    output=tmp_path/'console.log';monkeypatch.setenv('LOG_CONSOLE_FILE',str(output))
    manager=LoggingManager(log_dir=str(tmp_path/'logs'),archive_dir=str(tmp_path/'archive'),auto_start_scheduler=False)
    manager.start()
    handler=manager._console_handler
    handler.maxBytes=1000;handler.backupCount=2
    try:
        for i in range(30):logging.getLogger('agent_market.gateway.rotation').warning('record %d %s',i,'x'*120)
    finally:manager.stop()
    outputs=list(tmp_path.glob('console.log*'))
    assert len(outputs)==3 and all(p.stat().st_size<1200 for p in outputs)
    assert handler.stream is None


@pytest.mark.parametrize('message', [
    'Cookie: session=review-private-placeholder',
    "[(b'set-cookie', b'session=review-private-placeholder')]",
    'https://user:review-private-placeholder@example.invalid/api',
    'access_token=review-private-placeholder',
    '{"api_key":"review-private-placeholder"}',
    '/callback?code=review-private-placeholder',
    'GET /?code=review-private-placeholder HTTP/1.1',
    'GET /a+b?code=review-private-placeholder HTTP/1.1',
])
def test_sensitive_log_representations_never_escape(message):
    assert 'review-private-placeholder' not in redact_log_message(message)


def test_admin_error_buffer_redacts_raw_exception_and_message():
    handler=LogBuffer()
    try:
        raise ValueError('access_token=review-private-placeholder')
    except ValueError:
        import sys
        record=logging.LogRecord('test',logging.ERROR,__file__,1,'Cookie: session=review-private-placeholder',(),sys.exc_info())
        handler.emit(record)
    assert 'review-private-placeholder' not in handler.records[-1]['message']
