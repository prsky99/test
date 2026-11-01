"""Bounded asynchronous operational logging with Seoul calendar-day retention.

Keep failures, security events and service lifecycle messages. Routine collection,
health transitions and successful HTTP access are quiet by default. Source files
and the optional console file rotate at 5 MiB with two backups; no extra combined
copy is generated. Managed startup deletes logs older than today and repeats the
cleanup every five minutes. Legacy monthly archiving remains available explicitly.
"""

from __future__ import annotations

import atexit
import datetime
import glob
import logging
from logging.handlers import QueueHandler, QueueListener, RotatingFileHandler
import os
from pathlib import Path
import queue
import re
import shutil
import tarfile
import threading
import time
from typing import Any, Dict, Optional, Tuple

from .log_retention import LOG_TIMEZONE, LogRetentionScheduler, log_now


# 기본 경로 및 설정값
DEFAULT_LOG_DIR = os.environ.get("LOG_DIR", "logs")
DEFAULT_ARCHIVE_DIR = os.environ.get("LOG_ARCHIVE_DIR", os.path.join(DEFAULT_LOG_DIR, "archives"))
DEFAULT_LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO").upper()
DEFAULT_COMPRESS_MONTHS = int(os.environ.get("LOG_COMPRESS_MONTHS", "3"))

LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"
MAX_RECORD_CHARS = 16000


def log_time(timestamp):
    return datetime.datetime.fromtimestamp(timestamp, LOG_TIMEZONE).timetuple()


def operational_formatter():
    formatter = logging.Formatter(LOG_FORMAT, datefmt=DATE_FORMAT)
    formatter.converter = log_time
    return formatter


class DailySizeRotatingFileHandler(RotatingFileHandler):
    """Keep console segments bounded and roll at the Seoul calendar boundary."""
    def __init__(self, filename, **kwargs):
        super().__init__(filename, **kwargs)
        path = Path(filename)
        self._day = (datetime.datetime.fromtimestamp(path.stat().st_mtime, LOG_TIMEZONE).date()
                     if path.exists() else log_now().date())

    def emit(self, record):
        today = log_now().date()
        if datetime.datetime.fromtimestamp(record.created, LOG_TIMEZONE).date() < today:
            return
        if self._day != today:
            if Path(self.baseFilename).exists():
                self.doRollover()
            self._day = today
        super().emit(record)


def redact_log_message(value: str) -> str:
    """Remove transport credentials and query values before any managed output."""
    value = re.sub(r'(?i)(https?://)[^\s/@]+@', r'\1[redacted]@', value)
    value = re.sub(r'(?i)\b(Bearer|Basic)\s+[A-Za-z0-9._~+/=-]+', r'\1 [redacted]', value)
    value = re.sub(r'\b(?:vt_[A-Za-z0-9_-]+|tw_[a-f0-9]{32}\.[a-f0-9]{64})\b', '[redacted]', value)
    # Drop the remainder of a sensitive assignment/header line. This also
    # covers unquoted values and HTTP byte-tuple repr without parsing secrets.
    value = re.sub(r'''(?im)(\b(?:authorization|proxy-authorization|cookie|set-cookie|x-visitor-token|api[_-]?key|client_secret|access_token|refresh_token|password)\b["']?\s*[:=,]\s*)[^\r\n]*''', r'\1[redacted]', value)
    value = re.sub(r'(https?://[^\s?"\'<>]+|/[^\s?"\'<>]*)\?[^\s"\'<>]*', r'\1?[redacted]', value)
    return value


class ManagedLogFilter(logging.Filter):
    """Apply the same source limits and redaction before queueing all outputs."""

    def __init__(self, level_manager):
        super().__init__()
        self.level_manager = level_manager

    def filter(self, record):
        if record.name == 'uvicorn.access':
            # Uvicorn labels all responses INFO; retain failures at their severity.
            try:
                status = int(record.args[4])
            except (IndexError, KeyError, TypeError, ValueError):
                match = re.search(r'"\s+([1-5]\d\d)(?:\s|$)', record.getMessage())
                status = int(match[1]) if match else 0
            if status and status < 400:
                return False
            if status >= 400:
                record.levelno = logging.ERROR if status >= 500 else logging.WARNING
                record.levelname = logging.getLevelName(record.levelno)
        source = getattr(record, 'source', None) or resolve_source(record.name)
        if not self.level_manager.is_enabled_for(record.levelno, source):
            return False
        # HTTP wire diagnostics can contain credentials even when DEBUG is requested.
        if record.name.startswith(('httpcore', 'httpx')) and record.levelno < logging.WARNING:
            return False
        record.msg = redact_log_message(record.getMessage())
        if len(record.msg) > MAX_RECORD_CHARS:
            record.msg = record.msg[:MAX_RECORD_CHARS] + ' [log message truncated]'
        record.args = ()
        if record.exc_info:
            record.exc_text = redact_log_message(logging.Formatter().formatException(record.exc_info))[:MAX_RECORD_CHARS]
            record.exc_info = None
        return True


def resolve_source(logger_name: str) -> str:
    """로거 이름이나 모듈 경로로부터 소스(카테고리)명을 도출한다.
    
    규칙:
    - crawler: agent_market.gateway.crawler 등
    - health: agent_market.collector.health
    - collector: agent_market.collector.*
    - store: agent_market.gateway.store
    - concierge: agent_market.concierge.*
    - broker: agent_market.broker.*
    - gateway: agent_market.gateway.*
    - system: 그 외 최상위 및 외부 라이브러리(uvicorn, httpx 등)
    """
    if not logger_name:
        return "system"

    name_lower = logger_name.lower()
    if "crawler" in name_lower:
        return "crawler"
    if "health" in name_lower:
        return "health"
    if "store" in name_lower:
        return "store"
    if "concierge" in name_lower:
        return "concierge"
    if "collector" in name_lower:
        return "collector"
    if "gateway" in name_lower:
        return "gateway"
    if "broker" in name_lower:
        return "broker"

    parts = logger_name.split(".")
    if len(parts) >= 2 and parts[0] == "agent_market":
        return parts[1]
    return "system"


class SourceLevelManager:
    """전역 및 소스별 로그 레벨 관리자.
    
    평소에는 전체(INFO/DEBUG)를 기록하다가, 환경변수나 API를 통해 나중에
    에러(ERROR)만 기록되도록 손쉽게 변경할 수 있습니다.
    """

    def __init__(self, default_level: str | int = logging.INFO, *, quiet_sources=False):
        self._lock = threading.RLock()
        self._default_level = self._normalize_level(default_level)
        self._source_levels: Dict[str, int] = {}
        self._source_minimums = {source: logging.WARNING for source in ('collector','health','crawler')} if quiet_sources else {}
        self._load_env_overrides()

    @staticmethod
    def _normalize_level(level: str | int) -> int:
        if isinstance(level, int):
            return level
        lvl_name = str(level).strip().upper()
        return getattr(logging, lvl_name, logging.INFO)

    def _load_env_overrides(self) -> None:
        """환경변수 LOG_LEVEL_{SOURCE} 형태의 오버라이드 로드."""
        for key, val in os.environ.items():
            if key.startswith("LOG_LEVEL_") and len(key) > 10:
                source = key[10:].lower()
                self._source_levels[source] = self._normalize_level(val)

    def set_level(self, level: str | int, source: Optional[str] = None) -> None:
        """전역 또는 특정 소스의 로그 레벨 설정."""
        lvl_int = self._normalize_level(level)
        with self._lock:
            if source is None:
                self._default_level = lvl_int
            else:
                self._source_levels[source.lower()] = lvl_int

    def get_level(self, source: Optional[str] = None) -> int:
        """현재 설정된 로그 레벨 반환."""
        with self._lock:
            if source is not None:
                source_lower = source.lower()
                if source_lower in self._source_levels:
                    return self._source_levels[source_lower]
            return max(self._default_level, self._source_minimums.get(str(source or '').lower(), logging.NOTSET))

    def is_enabled_for(self, record_level: int, source: str) -> bool:
        """해당 레벨의 로그가 지정된 소스에 대해 기록되어야 하는지 판정."""
        threshold = self.get_level(source)
        return record_level >= threshold


class MultiSourceDailyFileHandler(logging.Handler):
    """소스별 일별 분리 및 년/월 계층 디렉토리 파일 핸들러.
    
    경로 구조:
      {log_dir}/{source}/{YYYY}/{MM}/{source}_{YYYY-MM-DD}.log
      {log_dir}/all/{YYYY}/{MM}/all_{YYYY-MM-DD}.log (전체 통합)
    """

    def __init__(
        self,
        log_dir: str,
        level_manager: SourceLevelManager,
        include_all: bool = True,
        formatter: Optional[logging.Formatter] = None,
        max_bytes: int = 5 * 1024 * 1024,
        backup_count: int = 2,
        retention_days: Optional[int] = None,
    ):
        super().__init__()
        self.log_dir = Path(log_dir).resolve()
        self.level_manager = level_manager
        self.include_all = include_all
        self.max_bytes = max_bytes
        self.backup_count = backup_count
        if max_bytes < 1 or backup_count < 1:
            raise ValueError('Log size and backup count must be positive.')
        self.retention_days = retention_days
        if formatter is None:
            formatter = operational_formatter()
        self.setFormatter(formatter)

        self._lock = threading.RLock()
        # (source, date_str) -> file object
        self._open_files: Dict[Tuple[str, str], Any] = {}

    def _get_file_path(self, source: str, dt: datetime.date) -> Path:
        year_str = f"{dt.year:04d}"
        month_str = f"{dt.month:02d}"
        date_str = dt.strftime("%Y-%m-%d")

        folder = self.log_dir / source / year_str / month_str
        if not folder.resolve().is_relative_to(self.log_dir):
            raise ValueError('Log destinations must stay inside the log directory.')
        folder.mkdir(parents=True, exist_ok=True)
        return folder / f"{source}_{date_str}.log"

    def _get_file_handle(self, source: str, dt: datetime.date):
        date_str = dt.strftime("%Y-%m-%d")
        key = (source, date_str)

        handle = self._open_files.get(key)
        if handle is not None and not handle.closed:
            return handle

        # 날짜가 바뀌었으면 이전 날짜의 핸들 정리
        stale_keys = [k for k in self._open_files if k[0] == source and k[1] != date_str]
        for sk in stale_keys:
            old_h = self._open_files.pop(sk, None)
            if old_h and not old_h.closed:
                try:
                    old_h.flush()
                    old_h.close()
                except Exception:
                    pass

        file_path = self._get_file_path(source, dt)
        if file_path.is_symlink():
            raise ValueError('Log files cannot be symbolic links.')
        descriptor = os.open(file_path, os.O_WRONLY|os.O_APPEND|os.O_CREAT|getattr(os,'O_NOFOLLOW',0), 0o600)
        handle = os.fdopen(descriptor, "a", encoding="utf-8", buffering=1)
        self._open_files[key] = handle
        return handle

    def close_before(self, cutoff):
        with self._lock:
            for key in list(self._open_files):
                if datetime.date.fromisoformat(key[1]) < cutoff:
                    self._open_files.pop(key).close()

    def _write(self, source, dt, message):
        handle = self._get_file_handle(source, dt)
        size = handle.tell()
        if size and size + len(message.encode('utf-8')) > self.max_bytes:
            key = (source, dt.isoformat())
            self._open_files.pop(key).close()
            path = self._get_file_path(source, dt)
            for index in range(self.backup_count, 0, -1):
                target = Path(str(path)+'.'+str(index))
                previous = Path(str(path)+'.'+str(index-1)) if index > 1 else path
                if previous.exists():
                    previous.replace(target)
            handle = self._get_file_handle(source, dt)
        handle.write(message)
        handle.flush()

    def emit(self, record: logging.LogRecord) -> None:
        try:
            # 1. 소스 결정
            explicit_source = getattr(record, "source", None)
            source = explicit_source if explicit_source else resolve_source(record.name)
            if not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', str(source)):
                source = 'system'

            # 2. 레벨 필터링
            if not self.level_manager.is_enabled_for(record.levelno, source):
                return

            msg = self.format(record) + "\n"
            dt = datetime.datetime.fromtimestamp(record.created, LOG_TIMEZONE).date()
            if self.retention_days and dt < log_now().date()-datetime.timedelta(days=self.retention_days-1):
                return

            with self._lock:
                # 소스별 파일에 기록
                self._write(source, dt, msg)

                # 전체 통합 파일(all)에 기록 (선택 사항)
                if self.include_all and source != "all":
                    if self.level_manager.is_enabled_for(record.levelno, "all"):
                        self._write('all', dt, msg)
        except Exception:
            self.handleError(record)

    def flush(self) -> None:
        with self._lock:
            for handle in self._open_files.values():
                if handle and not handle.closed:
                    try:
                        handle.flush()
                    except Exception:
                        pass

    def close(self) -> None:
        with self._lock:
            for handle in self._open_files.values():
                if handle and not handle.closed:
                    try:
                        handle.flush()
                        handle.close()
                    except Exception:
                        pass
            self._open_files.clear()
        super().close()


class LogArchiver:
    """월별 로그 압축 보관 및 이전 폴더 삭제 관리자.
    
    매월 1일에 3개월 전 생성된 로그에 대해 월별 압축(.tar.gz)해서 보관하고,
    압축 및 무결성 검증이 완료된 해당 월 폴더는 안전하게 삭제합니다.
    """

    def __init__(self, log_dir: str, archive_dir: str, compress_months: int = 3):
        self.log_dir = Path(log_dir).resolve()
        self.archive_dir = Path(archive_dir).resolve()
        self.compress_months = max(1, compress_months)
        self.archive_dir.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def get_cutoff_year_month(now: Optional[datetime.datetime] = None, months_ago: int = 3) -> Tuple[int, int]:
        """기준 시각으로부터 months_ago개월 전의 (year, month)를 계산."""
        if now is None:
            now = datetime.datetime.now()
        y, m = now.year, now.month
        m -= months_ago
        while m < 1:
            m += 12
            y -= 1
        return y, m

    def find_archivable_month_dirs(self, now: Optional[datetime.datetime] = None) -> list[Tuple[str, int, int, Path]]:
        """압축 대상인 3개월 전 이하의 월 폴더 목록을 찾는다.
        반환: [(source, year, month, path), ...]
        """
        cutoff_year, cutoff_month = self.get_cutoff_year_month(now, self.compress_months)
        cutoff_key = cutoff_year * 100 + cutoff_month

        results = []
        if not self.log_dir.exists():
            return results

        # log_dir 아래 소스 디렉토리들 탐색 (archives 폴더는 제외)
        for source_dir in self.log_dir.iterdir():
            if not source_dir.is_dir() or source_dir.name in ("archives", ".git"):
                continue
            source = source_dir.name

            # {source}/{YYYY}
            for year_dir in source_dir.iterdir():
                if not year_dir.is_dir() or not year_dir.name.isdigit():
                    continue
                year = int(year_dir.name)

                # {source}/{YYYY}/{MM}
                for month_dir in year_dir.iterdir():
                    if not month_dir.is_dir() or not month_dir.name.isdigit():
                        continue
                    month = int(month_dir.name)

                    if (year * 100 + month) <= cutoff_key:
                        results.append((source, year, month, month_dir))

        # 오래된 순으로 정렬
        results.sort(key=lambda item: (item[1], item[2], item[0]))
        return results

    def compress_and_cleanup_month(self, source: str, year: int, month: int, month_dir: Path) -> Optional[Path]:
        """단일 월 폴더를 .tar.gz로 압축 보관하고 무결성 검증 후 해당 폴더를 삭제한다."""
        if not month_dir.exists() or not month_dir.is_dir():
            return None

        # 압축할 로그 파일 수집
        log_files = [f for f in month_dir.iterdir() if f.is_file() and not f.name.startswith(".")]
        if not log_files:
            # 빈 폴더는 압축 없이 바로 삭제
            try:
                shutil.rmtree(month_dir, ignore_errors=True)
                self._cleanup_empty_parent(month_dir.parent)
            except Exception:
                pass
            return None

        # 목적지 아카이브 디렉토리: {archive_dir}/{source}/
        target_archive_dir = self.archive_dir / source
        target_archive_dir.mkdir(parents=True, exist_ok=True)

        archive_name = f"{source}_{year:04d}-{month:02d}.tar.gz"
        archive_path = target_archive_dir / archive_name
        tmp_archive_path = target_archive_dir / f".{archive_name}.tmp"

        # 1. 임시 tar.gz 압축 파일 생성
        try:
            with tarfile.open(tmp_archive_path, "w:gz") as tar:
                for file_path in sorted(log_files):
                    # tar 내 아크명은 파일명만 깔끔하게 저장
                    tar.add(file_path, arcname=file_path.name)
        except Exception as exc:
            if tmp_archive_path.exists():
                try:
                    tmp_archive_path.unlink()
                except Exception:
                    pass
            logging.getLogger("agent_market.logger").error(
                "로그 압축 실패 (폴더 보존됨): %s/%04d-%02d -> %s", source, year, month, exc
            )
            return None

        # 2. 압축 파일 무결성(Integrity) 검증
        try:
            with tarfile.open(tmp_archive_path, "r:gz") as tar:
                members = tar.getmembers()
                member_names = {m.name for m in members}
                orig_names = {f.name for f in log_files}
                if orig_names != member_names:
                    raise ValueError(f"압축 파일 멤버 불일치: 원본 {len(orig_names)}개 vs 압축 {len(member_names)}개")
                # 멤버 내용 스트림 읽기 테스트
                for m in members:
                    if m.isfile():
                        f = tar.extractfile(m)
                        if f:
                            while f.read(1024 * 1024):
                                pass
        except Exception as exc:
            if tmp_archive_path.exists():
                try:
                    tmp_archive_path.unlink()
                except Exception:
                    pass
            logging.getLogger("agent_market.logger").error(
                "로그 압축 무결성 검증 실패 (원본 폴더 안전 보존): %s/%04d-%02d: %s", source, year, month, exc
            )
            return None

        # 3. 원자적으로 목적지 파일로 이동
        try:
            if archive_path.exists():
                archive_path.unlink()
            tmp_archive_path.replace(archive_path)
        except Exception as exc:
            logging.getLogger("agent_market.logger").error("압축 파일 이름 변경 실패: %s", exc)
            return None

        # 4. 검증 완료 후 원본 월 폴더 안전 삭제
        try:
            shutil.rmtree(month_dir)
            self._cleanup_empty_parent(month_dir.parent)
            logging.getLogger("agent_market.logger").info(
                "로그 백업 및 원본 정리 완료: %s/%04d-%02d -> %s", source, year, month, archive_path
            )
            return archive_path
        except Exception as exc:
            logging.getLogger("agent_market.logger").warning(
                "압축 완료 후 원본 폴더 삭제 중 오류: %s (수동 확인 필요)", exc
            )
            return archive_path

    @staticmethod
    def _cleanup_empty_parent(dir_path: Path) -> None:
        """폴더가 비어 있으면 상위 빈 폴더도 정리."""
        try:
            if dir_path.exists() and dir_path.is_dir() and not any(dir_path.iterdir()):
                dir_path.rmdir()
        except Exception:
            pass

    def run_archive_all(self, now: Optional[datetime.datetime] = None) -> list[Path]:
        """3개월 전 이상의 모든 월별 로그를 압축 및 정리."""
        archived_files = []
        targets = self.find_archivable_month_dirs(now)
        for source, year, month, month_dir in targets:
            # CPU/IO 과부하 방지: 각 월 처리 사이에 잠시 양보
            time.sleep(0.05)
            arch = self.compress_and_cleanup_month(source, year, month, month_dir)
            if arch:
                archived_files.append(arch)
        return archived_files


class LogArchiveScheduler(threading.Thread):
    """매월 1일(및 정기 점검 시) 3개월 전 로그를 백그라운드에서 안전하게 압축 및 정리하는 스케줄러."""

    def __init__(
        self,
        archiver: LogArchiver,
        check_interval_seconds: float = 3600.0,  # 1시간마다 점검
        run_on_start: bool = True,
    ):
        super().__init__(daemon=True, name="log-archive-scheduler")
        self.archiver = archiver
        self.check_interval = check_interval_seconds
        self.run_on_start = run_on_start
        self._stop_event = threading.Event()
        self._last_processed_month: Optional[Tuple[int, int]] = None

    def stop(self) -> None:
        self._stop_event.set()

    def run(self) -> None:
        if self.run_on_start:
            try:
                self.archiver.run_archive_all()
            except Exception as exc:
                logging.getLogger("agent_market.logger").error("초기 로그 백업 실행 중 예외: %s", exc)

        while not self._stop_event.wait(self.check_interval):
            now = datetime.datetime.now()
            # 매월 1일이거나 이전 처리 이력이 없는 경우 점검
            current_ym = (now.year, now.month)
            if now.day == 1 and self._last_processed_month != current_ym:
                try:
                    self.archiver.run_archive_all(now)
                    self._last_processed_month = current_ym
                except Exception as exc:
                    logging.getLogger("agent_market.logger").error("매월 1일 로그 백업 실행 중 예외: %s", exc)


class LoggingManager:
    """전체 로깅 시스템 오케스트레이터.
    
    비동기 큐, 핸들러, 리스너, 아카이버 및 스케줄러를 한 곳에서 관리합니다.
    """

    def __init__(
        self,
        log_dir: str = DEFAULT_LOG_DIR,
        archive_dir: str = DEFAULT_ARCHIVE_DIR,
        default_level: str | int = DEFAULT_LOG_LEVEL,
        compress_months: int = DEFAULT_COMPRESS_MONTHS,
        log_to_console: bool = True,
        auto_start_scheduler: bool = True,
        retention_days: int = 1,
        quiet_sources: bool = True,
    ):
        self.log_dir = log_dir
        self.archive_dir = archive_dir
        self.compress_months = compress_months
        self.log_to_console = log_to_console
        self.auto_start_scheduler = auto_start_scheduler
        if retention_days < 1:
            raise ValueError('Log retention days must be positive.')
        self.retention_days = retention_days

        self.level_manager = SourceLevelManager(default_level, quiet_sources=quiet_sources)
        self.archiver = LogArchiver(self.log_dir, self.archive_dir, self.compress_months)
        self.scheduler: Optional[LogRetentionScheduler] = None

        self._log_queue: queue.Queue = queue.Queue(maxsize=20000)
        self._queue_listener: Optional[QueueListener] = None
        self._queue_handler: Optional[QueueHandler] = None
        self._file_handler: Optional[MultiSourceDailyFileHandler] = None
        self._console_handler: Optional[logging.StreamHandler] = None
        self._is_active = False
        self._lock = threading.Lock()

    def start(self) -> None:
        with self._lock:
            if self._is_active:
                return

            formatter = operational_formatter()

            # 1. 소스별 일별 파일 핸들러 생성
            self._file_handler = MultiSourceDailyFileHandler(
                log_dir=self.log_dir,
                level_manager=self.level_manager,
                include_all=False,
                formatter=formatter,
                retention_days=self.retention_days,
            )

            handlers = [self._file_handler]

            # 2. 콘솔 스트림 핸들러 (옵션)
            if self.log_to_console:
                console_path = os.environ.get('LOG_CONSOLE_FILE', '').strip()
                if console_path:
                    path = Path(console_path)
                    path.parent.mkdir(parents=True, exist_ok=True)
                    self._console_handler = DailySizeRotatingFileHandler(path, maxBytes=5 * 1024 * 1024,
                                                                        backupCount=2, encoding='utf-8', delay=True)
                else:
                    self._console_handler = logging.StreamHandler()
                self._console_handler.setFormatter(formatter)
                handlers.append(self._console_handler)

            # 3. 비동기 큐 리스너 시작 (I/O 논블로킹 워커 스레드)
            self._queue_listener = QueueListener(self._log_queue, *handlers, respect_handler_level=False)
            self._queue_listener.start()

            # 4. 루트 로거에 QueueHandler 연결
            self._queue_handler = QueueHandler(self._log_queue)
            self._queue_handler.addFilter(ManagedLogFilter(self.level_manager))
            root_logger = logging.getLogger()
            root_logger.setLevel(logging.DEBUG)  # 모든 레코드를 큐로 수집하고 필터에서 제어
            root_logger.addHandler(self._queue_handler)

            # 5. 아카이버 스케줄러 시작
            if self.auto_start_scheduler:
                protected = [os.environ.get('LOG_CONSOLE_FILE','')] if os.environ.get('LOG_CONSOLE_FILE') else []
                protected.extend(str(p)+'.startup' for p in list(protected))
                self.scheduler = LogRetentionScheduler(self.log_dir, days=self.retention_days,
                    protected=protected, close_expired=self._file_handler.close_before)
                self.scheduler.start()

            self._is_active = True

            # 정상 종료 훅 등록
            atexit.register(self.stop)

    def stop(self) -> None:
        with self._lock:
            if not self._is_active:
                return

            if self.scheduler:
                self.scheduler.stop()
                self.scheduler = None

            root_logger = logging.getLogger()
            if self._queue_handler:
                try:
                    root_logger.removeHandler(self._queue_handler)
                except Exception:
                    pass
                self._queue_handler = None

            if self._queue_listener:
                try:
                    self._queue_listener.stop()
                except Exception:
                    pass
                self._queue_listener = None

            if self._file_handler:
                try:
                    self._file_handler.close()
                except Exception:
                    pass
                self._file_handler = None

            if self._console_handler:
                self._console_handler.close()
                self._console_handler = None

            self._is_active = False

    def set_level(self, level: str | int, source: Optional[str] = None) -> None:
        """로그 레벨 변경 (기본 INFO -> 에러만 기록 시 ERROR로 설정)."""
        self.level_manager.set_level(level, source=source)

    def get_level(self, source: Optional[str] = None) -> int:
        return self.level_manager.get_level(source=source)

    def archive_now(self, now: Optional[datetime.datetime] = None) -> list[Path]:
        """즉시 3개월 전 로그 압축 및 정리 실행."""
        return self.archiver.run_archive_all(now)


# 전역 인스턴스 (Singleton)
_GLOBAL_MANAGER: Optional[LoggingManager] = None
_GLOBAL_LOCK = threading.Lock()


def setup_logging(
    log_dir: str = DEFAULT_LOG_DIR,
    archive_dir: str = DEFAULT_ARCHIVE_DIR,
    default_level: str | int = DEFAULT_LOG_LEVEL,
    compress_months: int = DEFAULT_COMPRESS_MONTHS,
    log_to_console: bool = True,
    auto_start_scheduler: bool = True,
) -> LoggingManager:
    """전체 시스템의 비동기 소스별 로깅을 활성화한다."""
    global _GLOBAL_MANAGER
    with _GLOBAL_LOCK:
        if _GLOBAL_MANAGER is not None:
            return _GLOBAL_MANAGER

        manager = LoggingManager(
            log_dir=log_dir,
            archive_dir=archive_dir,
            default_level=default_level,
            compress_months=compress_months,
            log_to_console=log_to_console,
            auto_start_scheduler=auto_start_scheduler,
        )
        manager.start()
        _GLOBAL_MANAGER = manager
        return manager


def shutdown_logging() -> None:
    """로깅 시스템을 안전하게 종료한다."""
    global _GLOBAL_MANAGER
    with _GLOBAL_LOCK:
        if _GLOBAL_MANAGER is not None:
            _GLOBAL_MANAGER.stop()
            _GLOBAL_MANAGER = None


def get_logging_manager() -> Optional[LoggingManager]:
    """현재 활성화된 LoggingManager 반환."""
    return _GLOBAL_MANAGER


def set_log_level(level: str | int, source: Optional[str] = None) -> None:
    """로그 레벨 변경 함수 (전역 또는 특정 소스)."""
    if _GLOBAL_MANAGER is not None:
        _GLOBAL_MANAGER.set_level(level, source=source)
