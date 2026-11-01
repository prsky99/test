"""RedisHub: Centralized Redis connectivity with Circuit Breaker and Local Fallback.

Provides high-performance distributed capabilities:
- Atomic sliding-window rate limiting via Lua script
- Distributed IP Auto-Jail and Blacklist synchronization
- Cache-Aside helpers with JSON serialization and TTL
- Zero-downtime circuit breaker for graceful in-memory fallback
"""

import json
import logging
import os
import secrets
import threading
import time
from typing import Any

log = logging.getLogger("agent_market.infra.redis_hub")

# Atomic Sliding Window Rate Limiting Lua Script
# KEYS[1]: rate limit key, e.g., 'a2a:rate:<route>:<ip>'
# ARGV[1]: current timestamp (float)
# ARGV[2]: sliding window size in seconds (float)
# ARGV[3]: maximum allowed requests (integer)
# ARGV[4]: unique member for this logical request
SLIDING_WINDOW_LUA = """
local key = KEYS[1]
local now = tonumber(ARGV[1])
local window = tonumber(ARGV[2])
local limit = tonumber(ARGV[3])
local member = ARGV[4]
local clear_before = now - window

redis.call('ZREMRANGEBYSCORE', key, '-inf', clear_before)
local current_requests = redis.call('ZCARD', key)

if current_requests < limit then
    redis.call('ZADD', key, now, member)
    redis.call('EXPIRE', key, math.ceil(window * 2))
    current_requests = current_requests + 1
    local first = redis.call('ZRANGE', key, 0, 0, 'WITHSCORES')
    local reset = window
    if #first > 0 then reset = math.max(1, math.ceil(tonumber(first[2]) + window - now)) end
    return {1, math.max(0, limit - current_requests), reset}
else
    local first = redis.call('ZRANGE', key, 0, 0, 'WITHSCORES')
    local reset = window
    if #first > 0 then reset = math.max(1, math.ceil(tonumber(first[2]) + window - now)) end
    return {0, 0, reset}
end
"""

# Atomic Auto-Jail Violation Tracker Lua Script
# KEYS[1]: violation set key, e.g., 'a2a:jail:violations:<ip>'
# ARGV[1]: current timestamp (float)
# ARGV[2]: window size in seconds (float)
# ARGV[3]: violation threshold (integer)
# ARGV[4]: unique member for this logical violation
VIOLATION_TRACKER_LUA = """
local key = KEYS[1]
local now = tonumber(ARGV[1])
local window = tonumber(ARGV[2])
local threshold = tonumber(ARGV[3])
local member = ARGV[4]
local clear_before = now - window

redis.call('ZREMRANGEBYSCORE', key, '-inf', clear_before)
redis.call('ZADD', key, now, member)
redis.call('EXPIRE', key, math.ceil(window * 2))
local count = redis.call('ZCARD', key)

if count >= threshold then
    return {1, count}
else
    return {0, count}
end
"""


class RedisHub:
    """Centralized Redis connection manager with circuit breaker and fallback."""

    _instance: "RedisHub | None" = None
    _lock = threading.Lock()

    def __init__(
        self,
        host: str | None = None,
        port: int | None = None,
        db: int = 0,
        socket_timeout: float = 0.25,
        socket_connect_timeout: float = 0.25,
    ) -> None:
        self.host = host or os.environ.get("REDIS_HOST", "127.0.0.1")
        self.port = int(port or os.environ.get("REDIS_PORT", 6379))
        self.db = db
        self.socket_timeout = socket_timeout
        self.socket_connect_timeout = socket_connect_timeout

        self._client: Any = None
        self._sliding_script: Any = None
        self._violation_script: Any = None

        # Circuit breaker state
        self._is_alive: bool = False
        self._consecutive_failures: int = 0
        self._circuit_open_until: float = 0.0
        self._cooldown_seconds: float = 15.0
        self._state_lock = threading.RLock()
        self._probing = False
        self._probe_epoch = 0
        self._probe_client: Any = None
        self._reconnect_thread: threading.Thread | None = None
        self._closed = False

    @classmethod
    def get_instance(cls) -> "RedisHub":
        """Thread-safe singleton accessor."""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
                    cls._instance.initialize()
        return cls._instance

    @classmethod
    def reset_instance_for_testing(cls) -> None:
        """Reset singleton for unit tests."""
        with cls._lock:
            previous = cls._instance
            cls._instance = None
        if previous is not None:
            previous._close()

    @staticmethod
    def _close_client(client) -> None:
        if client is None:
            return
        try:
            client.close()
        except Exception:
            log.debug("RedisHub: Client close unavailable.")
        try:
            client.connection_pool.disconnect()
        except Exception:
            log.debug("RedisHub: Pool close unavailable.")

    def _close(self) -> None:
        with self._state_lock:
            self._closed = True
            self._probe_epoch += 1
            self._probing = False
            self._is_alive = False
            current, pending = self._client, self._probe_client
            self._client = self._probe_client = None
            self._sliding_script = self._violation_script = None
        self._close_client(current)
        if pending is not current:
            self._close_client(pending)

    def _reserve_probe(self):
        with self._state_lock:
            if self._closed or self._probing:
                return None
            self._probe_epoch += 1
            self._probing = True
            return self._probe_epoch

    def initialize(self) -> bool:
        """Perform one explicit probe; retry paths never run on request threads."""
        epoch = self._reserve_probe()
        return False if epoch is None else self._connect(epoch)

    def _connect(self, epoch) -> bool:
        candidate, previous, published = None, None, False
        try:
            import redis
            from redis.backoff import NoBackoff
            from redis.retry import Retry

            with self._state_lock:
                if self._closed or epoch != self._probe_epoch:
                    return False
            candidate = redis.Redis(
                host=self.host,
                port=self.port,
                db=self.db,
                socket_timeout=self.socket_timeout,
                socket_connect_timeout=self.socket_connect_timeout,
                decode_responses=True,
                retry=Retry(NoBackoff(), 0),
                retry_on_error=[],
            )
            with self._state_lock:
                if self._closed or epoch != self._probe_epoch:
                    return False
                self._probe_client = candidate
            candidate.ping()
            sliding = candidate.register_script(SLIDING_WINDOW_LUA)
            violation = candidate.register_script(VIOLATION_TRACKER_LUA)
            with self._state_lock:
                if self._closed or epoch != self._probe_epoch:
                    return False
                previous = self._client
                self._client = candidate
                self._sliding_script, self._violation_script = sliding, violation
                self._probe_client = None
                self._is_alive = True
                self._consecutive_failures = 0
                self._circuit_open_until = 0.0
                published = True
            log.info("RedisHub: Redis connection available.")
            return True
        except Exception:
            with self._state_lock:
                if not self._closed and epoch == self._probe_epoch:
                    self._is_alive = False
                    self._consecutive_failures += 1
                    self._circuit_open_until = time.monotonic() + self._cooldown_seconds
            log.warning("RedisHub: Connection unavailable; using local fallback.")
            return False
        finally:
            with self._state_lock:
                if epoch == self._probe_epoch:
                    self._probing = False
                    self._probe_client = None
            if not published:
                self._close_client(candidate)
            if previous is not candidate:
                self._close_client(previous)

    def is_available(self) -> bool:
        """Return immediately while one background worker probes after cooldown."""
        with self._state_lock:
            if self._closed:
                return False
            if self._is_alive:
                return True
            if self._probing or time.monotonic() < self._circuit_open_until:
                return False
            epoch = self._reserve_probe()
            worker = threading.Thread(target=self._connect, args=(epoch,), daemon=True,
                                      name='redis-hub-reconnect')
            self._reconnect_thread = worker
        try:
            worker.start()
        except RuntimeError:
            with self._state_lock:
                if epoch == self._probe_epoch:
                    self._probing = False
                    self._circuit_open_until = time.monotonic() + self._cooldown_seconds
        return False

    def mark_failure(self, exc: Exception, client=None) -> None:
        """Increment failure counter and trip circuit breaker if threshold reached."""
        with self._state_lock:
            if self._closed or client is not None and client is not self._client:
                return
            self._consecutive_failures += 1
            if self._consecutive_failures >= 3:
                self._is_alive = False
                self._circuit_open_until = time.monotonic() + self._cooldown_seconds
                log.warning("RedisHub: Circuit open; using local fallback.")

    def mark_success(self, client=None) -> None:
        """Reset failure counter upon successful response."""
        with self._state_lock:
            if self._closed or client is not None and client is not self._client:
                return
            self._consecutive_failures = 0
            self._is_alive = True

    def _operation(self):
        if not self.is_available():
            return None, None, None
        with self._state_lock:
            if self._closed or not self._is_alive:
                return None, None, None
            return self._client, self._sliding_script, self._violation_script

    @property
    def raw_client(self) -> Any:
        with self._state_lock:
            return self._client

    # ---------------------------------------------------------
    # Distributed Rate Limiting & Violation Tracking
    # ---------------------------------------------------------

    def check_sliding_window(self, key: str, limit: int, window: float = 60.0) -> bool | None:
        snapshot=self.sliding_window_snapshot(key,limit,window)
        return snapshot['allowed'] if snapshot is not None else None

    def sliding_window_snapshot(self, key: str, limit: int, window: float = 60.0):
        """One atomic admission decision includes its actual distributed remainder."""
        client, sliding, _ = self._operation()
        if client is None or sliding is None:return None
        try:
            result=sliding(keys=[key],args=[time.time(),window,limit,secrets.token_hex(16)])
            self.mark_success(client)
            if isinstance(result,(list,tuple)) and len(result)==3:
                return {'allowed':bool(result[0]),'remaining':max(0,int(result[1])),'reset':max(1,int(result[2]))}
            # Compatibility with an earlier registered script; never invent a remainder.
            return {'allowed':result==1,'remaining':None if result==1 else 0,'reset':max(1,int(window))}
        except Exception as exc:
            self.mark_failure(exc,client)
            return None

    def record_violation(
        self, ip: str, threshold: int = 5, window: float = 60.0, prefix: str = "a2a:"
    ) -> tuple[bool, int] | None:
        """Track rate-limiting or security violations in Redis.

        Returns:
            (should_jail: bool, current_violation_count: int) or None if unavailable.
        """
        client, _, violation = self._operation()
        if client is None or violation is None:
            return None

        key = f"{prefix}jail:violations:{ip}"
        now = time.time()
        try:
            res = violation(keys=[key], args=[now, window, threshold, secrets.token_hex(16)])
            self.mark_success(client)
            if isinstance(res, (list, tuple)) and len(res) >= 2:
                return bool(res[0] == 1), int(res[1])
            return False, 0
        except Exception as exc:
            self.mark_failure(exc, client)
            return None

    # ---------------------------------------------------------
    # IP Jail & Blacklist Management
    # ---------------------------------------------------------

    def is_ip_jailed(self, ip: str, prefix: str = "a2a:") -> tuple[bool, str | None] | None:
        """Check whether an IP is currently jailed (temporary or permanent).

        Returns:
            (is_blocked: bool, reason: str | None) or None if unavailable.
        """
        client, _, _ = self._operation()
        if client is None:
            return None

        try:
            # 1. Fast check for temporary jail key
            temp_key = f"{prefix}jail:temp:{ip}"
            temp_reason = client.get(temp_key)
            if temp_reason is not None:
                self.mark_success(client)
                return True, str(temp_reason)

            # 2. Check permanent banned hash
            banned_info = client.hget(f"{prefix}jail:banned", ip)
            if banned_info is not None:
                self.mark_success(client)
                reason = "Permanently blocked by security policy"
                try:
                    parsed = json.loads(banned_info)
                    if isinstance(parsed, dict) and "reason" in parsed:
                        reason = parsed["reason"]
                except Exception:
                    pass
                return True, reason

            self.mark_success(client)
            return False, None
        except Exception as exc:
            self.mark_failure(exc, client)
            return None

    def jail_ip(self, ip: str, reason: str, duration_seconds: float | None = None, prefix: str = "a2a:") -> bool:
        """Block an IP address across all workers."""
        client, _, _ = self._operation()
        if client is None:
            return False

        try:
            if duration_seconds and duration_seconds > 0:
                temp_key = f"{prefix}jail:temp:{ip}"
                client.set(temp_key, reason, ex=int(duration_seconds))
            else:
                data = json.dumps({"reason": reason, "created_at": time.time()})
                client.hset(f"{prefix}jail:banned", ip, data)
            self.mark_success(client)
            return True
        except Exception as exc:
            self.mark_failure(exc, client)
            return False

    def unban_ip(self, ip: str, prefix: str = "a2a:") -> bool:
        """Unban an IP from temporary and permanent lists."""
        client, _, _ = self._operation()
        if client is None:
            return False

        try:
            pipe = client.pipeline()
            pipe.delete(f"{prefix}jail:temp:{ip}")
            pipe.delete(f"{prefix}jail:violations:{ip}")
            pipe.hdel(f"{prefix}jail:banned", ip)
            pipe.execute()
            self.mark_success(client)
            return True
        except Exception as exc:
            self.mark_failure(exc, client)
            return False

    # ---------------------------------------------------------
    # High-Performance JSON Cache-Aside Helpers
    # ---------------------------------------------------------

    def get_json(self, key: str) -> Any | None:
        """Retrieve and parse JSON data from Redis cache."""
        client, _, _ = self._operation()
        if client is None:
            return None

        try:
            raw = client.get(key)
            if raw is None:
                return None
            self.mark_success(client)
            return json.loads(raw)
        except Exception as exc:
            self.mark_failure(exc, client)
            return None

    def set_json(self, key: str, value: Any, ttl_seconds: int = 60) -> bool:
        """Serialize and cache JSON data with an expiration TTL."""
        client, _, _ = self._operation()
        if client is None:
            return False

        try:
            serialized = json.dumps(value, ensure_ascii=False)
            client.set(key, serialized, ex=int(ttl_seconds))
            self.mark_success(client)
            return True
        except Exception as exc:
            self.mark_failure(exc, client)
            return False

    def delete_keys(self, *keys: str) -> int:
        """Delete specific keys from Redis."""
        client, _, _ = self._operation()
        if client is None or not keys:
            return 0

        try:
            count = client.delete(*keys)
            self.mark_success(client)
            return int(count)
        except Exception as exc:
            self.mark_failure(exc, client)
            return 0

    def delete_pattern(self, pattern: str) -> int:
        """Delete all keys matching pattern using SCAN to avoid blocking."""
        client, _, _ = self._operation()
        if client is None:
            return 0

        try:
            total_deleted = 0
            keys_batch = []
            for k in client.scan_iter(match=pattern, count=100):
                keys_batch.append(k)
                if len(keys_batch) >= 100:
                    total_deleted += client.delete(*keys_batch)
                    keys_batch.clear()
            if keys_batch:
                total_deleted += client.delete(*keys_batch)
            self.mark_success(client)
            return total_deleted
        except Exception as exc:
            self.mark_failure(exc, client)
            return 0
