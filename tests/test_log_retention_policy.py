"""Bounded logging, calendar retention and preservation of live console records."""
import datetime as dt
import logging
import os
from pathlib import Path
import pytest

from agent_market.log_retention import LOG_TIMEZONE, LogRetentionScheduler, expired_log_files
from agent_market.logger import DailySizeRotatingFileHandler, LoggingManager, MultiSourceDailyFileHandler, SourceLevelManager
from scripts.prune_runtime_logs import cleanup_runtime_logs


def test_retention_uses_seoul_calendar_and_never_follows_symlinks(tmp_path):
    root=tmp_path/'logs';root.mkdir()
    old=root/'health_2026-10-19.log';old.write_text('old')
    today=root/'health_2026-10-20.log.1';today.write_text('today')
    future=root/'health_2026-10-21.log';future.write_text('future')
    unrelated=root/'data.json';unrelated.write_text('preserved')
    outside=tmp_path/'outside';outside.mkdir();(outside/'private_2026-10-19.log').write_text('preserved')
    (root/'alias').symlink_to(outside,target_is_directory=True)
    (root/'link_2026-10-19.log').symlink_to(outside/'private_2026-10-19.log')
    utc=dt.datetime(2026,10,19,15,0,tzinfo=dt.timezone.utc)
    assert expired_log_files(root,now=utc)==[old]
    removed=LogRetentionScheduler(root).cleanup(utc)
    assert removed==[old] and today.exists() and future.exists() and unrelated.exists()
    assert (outside/'private_2026-10-19.log').exists()


def test_source_files_rotate_and_expired_handles_close(tmp_path):
    levels=SourceLevelManager()
    handler=MultiSourceDailyFileHandler(str(tmp_path),levels,include_all=False,max_bytes=300,backup_count=2)
    now=dt.datetime.now(LOG_TIMEZONE)
    try:
        for n in range(20):
            record=logging.LogRecord('agent_market.gateway.audit',logging.WARNING,__file__,1,'record %d %s',(n,'x'*90),None)
            handler.emit(record)
        files=list(tmp_path.rglob('*.log*'))
        assert len(files)==3 and all(f.stat().st_size<=300 for f in files)
        handles=list(handler._open_files.values())
        handler.close_before(now.date()+dt.timedelta(days=1))
        assert all(h.closed for h in handles) and not handler._open_files
    finally:handler.close()


def test_console_rolls_on_seoul_midnight_not_on_elapsed_24_hours(tmp_path,monkeypatch):
    from agent_market import logger
    day=[dt.datetime(2026,10,20,23,59,tzinfo=LOG_TIMEZONE)]
    monkeypatch.setattr(logger,'log_now',lambda:day[0])
    path=tmp_path/'console.log';handler=DailySizeRotatingFileHandler(path,maxBytes=10000,backupCount=2,encoding='utf8')
    try:
        r=logging.makeLogRecord({'msg':'previous day','levelno':logging.WARNING,'created':day[0].timestamp()});handler.handle(r)
        day[0]+=dt.timedelta(minutes=1)
        handler.handle(logging.makeLogRecord({'msg':'current day','levelno':logging.WARNING,'created':day[0].timestamp()}))
        handler.handle(r)
        assert path.read_text().strip()=='current day'
        assert Path(str(path)+'.1').read_text().strip()=='previous day'
    finally:handler.close()


def test_quiet_defaults_keep_startup_errors_security_and_access_failures(tmp_path,monkeypatch):
    path=tmp_path/'console.log';monkeypatch.setenv('LOG_CONSOLE_FILE',str(path))
    manager=LoggingManager(log_dir=str(tmp_path/'logs'),archive_dir=str(tmp_path/'archive'),auto_start_scheduler=False)
    manager.start()
    try:
        for name in ('agent_market','agent_market.collector','agent_market.collector.health','agent_market.gateway.server','agent_market.concierge.security','uvicorn','uvicorn.access'):
            lg=logging.getLogger(name);lg.disabled=False;lg.propagate=True;lg.setLevel(logging.NOTSET)
        logging.getLogger('agent_market.collector').info('routine collection stats')
        logging.getLogger('agent_market.collector.health').info('routine health transition')
        logging.getLogger('agent_market.gateway.server').info('service listening')
        logging.getLogger('agent_market.concierge.security').warning('blocked request')
        logging.getLogger('agent_market.collector').error('collection failure')
        access=logging.getLogger('uvicorn.access')
        for code in [200,304,404,500]:access.info('%s - "%s %s HTTP/%s" %d','test','GET','/search?token=private-value','1.1',code)
        manager.set_level('ERROR')
        logging.getLogger('agent_market.collector').warning('global error threshold suppresses this')
    finally:manager.stop()
    text=path.read_text()
    assert 'routine'not in text and 'global error threshold'not in text
    assert 'service listening'in text and 'blocked request'in text and 'collection failure'in text
    assert '404'in text and '500'in text and '200'not in text and '304'not in text
    assert 'private-value'not in text
    assert not (tmp_path/'logs/all').exists()


def test_console_cleanup_keeps_today_multiline_evidence_and_live_inode(tmp_path):
    logs=tmp_path/'logs';logs.mkdir();active=logs/'agentcon.log'
    old='2026-10-19 23:00:00 INFO test: old\n'
    current='2026-10-20 00:00:00 ERROR test: today\nTraceback retained\n'
    active.write_text(old+current)
    daily=logs/'all/2026/10/all_2026-10-20.log';daily.parent.mkdir(parents=True);daily.write_text(current)
    stale=logs/'agentcon.log.1';stale.write_text(old);os.utime(stale,(1,1))
    (tmp_path/'gateway.log').write_text(old);os.utime(tmp_path/'gateway.log',(1,1))
    inode=active.stat().st_ino
    with active.open('a')as stream:
        result=cleanup_runtime_logs(tmp_path,day=dt.date(2026,10,20),apply=True)
        stream.write('2026-10-20 01:00:00 INFO test: still logging\n');stream.flush()
    assert result['today_console_records_preserved_in_daily_log']==1
    assert daily.read_text()==current and active.stat().st_ino==inode
    assert 'still logging'in active.read_text() and not stale.exists()


def test_cleanup_preserves_everything_when_today_copy_is_missing(tmp_path):
    logs=tmp_path/'logs';logs.mkdir();active=logs/'agentcon.log';active.write_text('2026-10-20 00:00:00 ERROR test: unique\n')
    daily=logs/'all/2026/10/all_2026-10-20.log';daily.parent.mkdir(parents=True);daily.write_text('')
    old=logs/'test_2026-10-19.log';old.write_text('old')
    with pytest.raises(RuntimeError):cleanup_runtime_logs(tmp_path,day=dt.date(2026,10,20),apply=True)
    assert 'unique'in active.read_text() and old.exists()


def test_log_files_reject_symlink_and_source_traversal(tmp_path):
    outside=tmp_path/'outside.log';outside.write_text('must remain unchanged')
    root=tmp_path/'logs'
    handler=MultiSourceDailyFileHandler(str(root),SourceLevelManager(),include_all=False)
    try:
        date=dt.datetime.now(LOG_TIMEZONE).date()
        path=handler._get_file_path('gateway',date)
        path.symlink_to(outside)
        with pytest.raises(ValueError):handler._get_file_handle('gateway',date)
        r=logging.makeLogRecord({'name':'test','levelno':logging.ERROR,'source':'../../outside','msg':'safe fallback'})
        handler.emit(r)
        assert outside.read_text()=='must remain unchanged'
        assert 'safe fallback'in handler._get_file_path('system',date).read_text()
    finally:handler.close()


def test_quiet_policy_preserves_explicit_debug_and_global_error_threshold(monkeypatch):
    monkeypatch.setenv('LOG_LEVEL_COLLECTOR','DEBUG')
    levels=SourceLevelManager('INFO',quiet_sources=True)
    assert levels.get_level('HEALTH')==logging.WARNING
    assert levels.get_level('collector')==logging.DEBUG
    levels.set_level('ERROR')
    assert levels.get_level('health')==logging.ERROR
    assert levels.get_level('collector')==logging.DEBUG
