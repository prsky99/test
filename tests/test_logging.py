"""소스별 일별 로깅 및 월별 압축 보관 시스템 테스트."""

import datetime
import logging
import os
from pathlib import Path
import shutil
import tarfile
import time

import pytest

from agent_market.logger import (
    LogArchiver,
    LogArchiveScheduler,
    LoggingManager,
    MultiSourceDailyFileHandler,
    SourceLevelManager,
    resolve_source,
    setup_logging,
    shutdown_logging,
)


def test_resolve_source():
    """로거 이름에 따른 소스 분류 정확도 검증."""
    assert resolve_source("agent_market.gateway.crawler") == "crawler"
    assert resolve_source("agent_market.collector.health") == "health"
    assert resolve_source("agent_market.collector.capabilities") == "collector"
    assert resolve_source("agent_market.collector.auth") == "collector"
    assert resolve_source("agent_market.collector.server") == "collector"
    assert resolve_source("agent_market.gateway.store") == "store"
    assert resolve_source("agent_market.gateway.server") == "gateway"
    assert resolve_source("agent_market.gateway.dashboard") == "gateway"
    assert resolve_source("agent_market.concierge.llm") == "concierge"
    assert resolve_source("agent_market.broker.discovery") == "broker"
    assert resolve_source("uvicorn.error") == "system"
    assert resolve_source("") == "system"


def test_multi_source_daily_file_handler(tmp_path):
    """소스별/년/월 디렉토리 구조 및 일별 파일 생성 검증."""
    log_dir = tmp_path / "test_logs"
    lvl_mgr = SourceLevelManager(default_level="INFO")
    handler = MultiSourceDailyFileHandler(str(log_dir), lvl_mgr, include_all=True)

    logger_crawler = logging.getLogger("agent_market.gateway.crawler")
    logger_crawler.setLevel(logging.DEBUG)
    logger_crawler.addHandler(handler)
    logger_crawler.propagate = False

    logger_health = logging.getLogger("agent_market.collector.health")
    logger_health.setLevel(logging.DEBUG)
    logger_health.addHandler(handler)
    logger_health.propagate = False

    try:
        now = datetime.datetime.now()
        y_str = f"{now.year:04d}"
        m_str = f"{now.month:02d}"
        d_str = now.strftime("%Y-%m-%d")

        logger_crawler.info("Crawler starting pass")
        logger_health.warning("Health check warning")

        handler.flush()

        # 1. 크롤러 파일 확인: {log_dir}/crawler/{YYYY}/{MM}/crawler_{YYYY-MM-DD}.log
        crawler_file = log_dir / "crawler" / y_str / m_str / f"crawler_{d_str}.log"
        assert crawler_file.exists(), f"Crawler log file not found at {crawler_file}"
        crawler_content = crawler_file.read_text(encoding="utf-8")
        assert "Crawler starting pass" in crawler_content
        assert "Health check" not in crawler_content

        # 2. 헬스 파일 확인: {log_dir}/health/{YYYY}/{MM}/health_{YYYY-MM-DD}.log
        health_file = log_dir / "health" / y_str / m_str / f"health_{d_str}.log"
        assert health_file.exists(), f"Health log file not found at {health_file}"
        health_content = health_file.read_text(encoding="utf-8")
        assert "Health check warning" in health_content
        assert "Crawler starting" not in health_content

        # 3. 전체 통합 파일(all) 확인: {log_dir}/all/{YYYY}/{MM}/all_{YYYY-MM-DD}.log
        all_file = log_dir / "all" / y_str / m_str / f"all_{d_str}.log"
        assert all_file.exists()
        all_content = all_file.read_text(encoding="utf-8")
        assert "Crawler starting pass" in all_content
        assert "Health check warning" in all_content

    finally:
        handler.close()
        logger_crawler.removeHandler(handler)
        logger_health.removeHandler(handler)
        logger_crawler.propagate = True
        logger_health.propagate = True


def test_log_level_filtering_and_error_only_mode(tmp_path):
    """현재는 전체 기록하고 나중에 에러만 기록되게 설정할 수 있는지 검증."""
    log_dir = tmp_path / "test_level_logs"
    lvl_mgr = SourceLevelManager(default_level="INFO")
    handler = MultiSourceDailyFileHandler(str(log_dir), lvl_mgr, include_all=False)

    test_logger = logging.getLogger("agent_market.gateway.test_level")
    test_logger.setLevel(logging.DEBUG)
    test_logger.addHandler(handler)
    test_logger.propagate = False

    now = datetime.datetime.now()
    log_file = log_dir / "gateway" / f"{now.year:04d}" / f"{now.month:02d}" / f"gateway_{now.strftime('%Y-%m-%d')}.log"

    try:
        # Phase 1: 기본 INFO 모드 (INFO, ERROR 모두 기록)
        test_logger.info("This is an info message")
        test_logger.error("This is an initial error message")
        handler.flush()

        content = log_file.read_text(encoding="utf-8")
        assert "This is an info message" in content
        assert "This is an initial error message" in content

        # Phase 2: 'ERROR'만 기록되도록 설정 변경
        lvl_mgr.set_level("ERROR")

        test_logger.info("This info message MUST BE FILTERED OUT")
        test_logger.warning("This warning message MUST ALSO BE FILTERED OUT")
        test_logger.error("This second error message MUST BE LOGGED")
        handler.flush()

        updated_content = log_file.read_text(encoding="utf-8")
        assert "This info message MUST BE FILTERED OUT" not in updated_content
        assert "This warning message MUST ALSO BE FILTERED OUT" not in updated_content
        assert "This second error message MUST BE LOGGED" in updated_content

        # Phase 3: 특정 소스만 개별 오버라이드 (예: crawler만 DEBUG 허용)
        lvl_mgr.set_level("DEBUG", source="crawler")
        assert lvl_mgr.get_level(source="crawler") == logging.DEBUG
        assert lvl_mgr.get_level(source="gateway") == logging.ERROR

    finally:
        handler.close()
        test_logger.removeHandler(handler)
        test_logger.propagate = True


def test_log_archiver_3_months_compression_and_cleanup(tmp_path):
    """3개월 전 생성된 로그에 대해 월별 압축 보관 및 해당 월 폴더 삭제 검증."""
    log_dir = tmp_path / "archive_test_logs"
    archive_dir = tmp_path / "archive_test_out"
    archiver = LogArchiver(str(log_dir), str(archive_dir), compress_months=3)

    # 기준일: 2026-10-16
    now = datetime.datetime(2026, 10, 16, 10, 0, 0)
    # 3개월 전: 2026년 7월 (압축 대상)
    # 4개월 전: 2026년 6월 (압축 대상)
    # 2개월 전: 2026년 8월 (보존 대상)
    # 현재 월: 2026년 10월 (보존 대상)

    def create_dummy_log(source: str, year: int, month: int, day: int, content: str):
        p = log_dir / source / f"{year:04d}" / f"{month:02d}"
        p.mkdir(parents=True, exist_ok=True)
        file_path = p / f"{source}_{year:04d}-{month:02d}-{day:02d}.log"
        file_path.write_text(content, encoding="utf-8")
        return file_path

    # 대상 파일들 생성
    # 1. 2026-06 (4개월 전): 압축 및 삭제 대상
    create_dummy_log("crawler", 2026, 6, 10, "Crawler June log line 1")
    create_dummy_log("crawler", 2026, 6, 20, "Crawler June log line 2")

    # 2. 2026-07 (3개월 전): 압축 및 삭제 대상
    create_dummy_log("crawler", 2026, 7, 5, "Crawler July log line 1")
    create_dummy_log("crawler", 2026, 7, 15, "Crawler July log line 2")
    create_dummy_log("health", 2026, 7, 1, "Health July log")

    # 3. 2026-08 (2개월 전): 아직 3개월 미만이므로 보존 대상
    create_dummy_log("crawler", 2026, 8, 1, "Crawler August log line")

    # 4. 2026-10 (현재 월): 활성 로그이므로 보존 대상
    create_dummy_log("crawler", 2026, 10, 16, "Crawler October today log")

    # 압축 대상 폴더 목록 확인
    targets = archiver.find_archivable_month_dirs(now)
    assert len(targets) == 3  # (crawler, 2026, 6), (crawler, 2026, 7), (health, 2026, 7)

    # 압축 및 정리 실행
    archived_files = archiver.run_archive_all(now)
    assert len(archived_files) == 3

    # 검증 1: 아카이브 파일 생성 확인
    expected_crawler_06 = archive_dir / "crawler" / "crawler_2026-06.tar.gz"
    expected_crawler_07 = archive_dir / "crawler" / "crawler_2026-07.tar.gz"
    expected_health_07 = archive_dir / "health" / "health_2026-07.tar.gz"

    assert expected_crawler_06.exists()
    assert expected_crawler_07.exists()
    assert expected_health_07.exists()

    # 검증 2: 압축 파일 내용 무결성 확인
    with tarfile.open(expected_crawler_07, "r:gz") as tar:
        names = tar.getnames()
        assert "crawler_2026-07-05.log" in names
        assert "crawler_2026-07-15.log" in names
        f = tar.extractfile("crawler_2026-07-05.log")
        assert f is not None
        assert "Crawler July log line 1" in f.read().decode("utf-8")

    # 검증 3: 압축 완료된 원본 폴더 삭제 확인
    assert not (log_dir / "crawler" / "2026" / "06").exists()
    assert not (log_dir / "crawler" / "2026" / "07").exists()
    assert not (log_dir / "health" / "2026" / "07").exists()

    # 검증 4: 3개월 이내 보존 대상 폴더는 온전히 유지됨 확인
    assert (log_dir / "crawler" / "2026" / "08" / "crawler_2026-08-01.log").exists()
    assert (log_dir / "crawler" / "2026" / "10" / "crawler_2026-10-16.log").exists()


def test_async_queue_logging_manager(tmp_path):
    """비동기 QueueHandler & QueueListener 파이프라인 전체 동작 검증."""
    log_dir = tmp_path / "async_logs"
    archive_dir = tmp_path / "async_archives"

    # 로깅 매니저 시작 (스케줄러는 테스트에서 수동 호출)
    mgr = LoggingManager(
        log_dir=str(log_dir),
        archive_dir=str(archive_dir),
        default_level="INFO",
        compress_months=3,
        log_to_console=False,
        auto_start_scheduler=False,
        quiet_sources=False,
    )
    mgr.start()

    crawler_log = logging.getLogger("agent_market.gateway.crawler")
    health_log = logging.getLogger("agent_market.collector.health")

    try:
        # 비동기 로그 기록
        for i in range(10):
            crawler_log.info("Batch async crawler message %d", i)
            health_log.info("Batch async health message %d", i)

        # 큐 리스너가 비동기 처리할 시간 잠시 대기
        time.sleep(0.3)

        now = datetime.datetime.now()
        crawler_file = log_dir / "crawler" / f"{now.year:04d}" / f"{now.month:02d}" / f"crawler_{now.strftime('%Y-%m-%d')}.log"
        health_file = log_dir / "health" / f"{now.year:04d}" / f"{now.month:02d}" / f"health_{now.strftime('%Y-%m-%d')}.log"

        assert crawler_file.exists()
        assert health_file.exists()

        crawler_text = crawler_file.read_text(encoding="utf-8")
        assert "Batch async crawler message 0" in crawler_text
        assert "Batch async crawler message 9" in crawler_text

    finally:
        mgr.stop()


def test_log_archive_scheduler_startup_and_stop(tmp_path):
    """LogArchiveScheduler 시작 시 자동 아카이빙 실행 및 stop 이벤트 안전 종료 검증."""
    log_dir = tmp_path / "sched_logs"
    archive_dir = tmp_path / "sched_archives"

    # 3개월 전 로그 파일 미리 생성
    old_folder = log_dir / "crawler" / "2026" / "05"
    old_folder.mkdir(parents=True, exist_ok=True)
    (old_folder / "crawler_2026-05-01.log").write_text("Old crawler log", encoding="utf-8")

    archiver = LogArchiver(str(log_dir), str(archive_dir), compress_months=3)
    # run_on_start=True로 스케줄러 기동
    scheduler = LogArchiveScheduler(archiver, check_interval_seconds=0.1, run_on_start=True)
    scheduler.start()

    time.sleep(0.3)
    scheduler.stop()
    scheduler.join(timeout=2.0)

    # 3개월 전 로그가 시작 시점에 자동으로 압축되고 원본 폴더는 삭제되었는지 확인
    archived_file = archive_dir / "crawler" / "crawler_2026-05.tar.gz"
    assert archived_file.exists()
    assert not old_folder.exists()

