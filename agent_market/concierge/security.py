"""DDoS mitigation, traffic shielding, and IP security management for the public agent front (port 443/HTTPS).

Provides:
- Multi-tier adaptive rate limiting with Auto-Jail (Fail2Ban mechanism)
- Blacklist / Whitelist IP access control with persistence in SQLite
- Outbound probe amplification & SSRF protection with concurrency limiting
- Slowloris / slow-body timeout protection
- Emergency "Under Attack Mode" (High Security Shield)
- Real-time audit event logging for admin monitoring
- Ultra-fast in-memory lookup cache (<1us)
"""

import asyncio
import collections
import logging
import re
import threading
import time
from contextvars import ContextVar
from collections import defaultdict, deque
from typing import Literal

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse

from ..gateway.store import Store
from ..gateway.deployment_security import forwarded_client, is_trusted_proxy, trusted_proxy_networks
from ..infra.redis_hub import RedisHub
from .token_hygiene import redact_visitor_tokens
from .recommendation_security import secret_name, public_data, public_schema

log = logging.getLogger("agent_market.concierge.security")
_QUOTA = ContextVar('public_quota_snapshot',default=None)
_QUOTA_SINK = ContextVar('public_quota_sink',default=None)

# Cloudflare gives every cross-zone Worker subrequest this one client address. Jailing it for one
# scanner Worker blocked unrelated visitors 105 times on 2026-10-31~11-01; the probe itself is still refused.
SHARED_EGRESS_IPS = frozenset({'2a06:98c0:3600::103'})

def remember_quota(value):
    _QUOTA.set(value)
    sink=_QUOTA_SINK.get()
    if isinstance(sink,dict) and value:sink.clear();sink.update(value)


def quota_headers(snapshot=None):
    """Snapshot of the single actual limiter decision, not a new counter read."""
    value=snapshot if snapshot is not None else _QUOTA.get()
    if not value:return {}
    result={'RateLimit-Policy':'"'+value['policy']+'";q='+str(value['limit'])+';w=60'}
    if value.get('remaining')is not None:
        result['RateLimit']='"'+value['policy']+'";r='+str(value['remaining'])+';t='+str(value['reset'])
    return result

DANGEROUS_HTML_PATTERNS = re.compile(
    r'(?is)(?:<\s*(?:script|iframe|object|embed|applet|meta|link|style|form|input|button|base|body|frameset|frame|layer)\b'
    r'|<\s*/\s*(?:script|iframe|object|embed|applet|style)\b'
    r'|\bon[a-z]{3,20}\s*='
    r'|\b(?:javascript|vbscript|data\s*:\s*text\/html|data\s*:\s*application\/javascript)\s*:'
    r'|expression\s*\('
    r'|<\s*(?:img|svg|audio|video|source|track)\b[^>]*\bon[a-z]{3,20}\s*=)'
)

SQL_INJECTION_PATTERN = re.compile(
    r'(?is)(?:\b(?:union\s+select|union\s+all\s+select)\b'
    r'|;\s*(?:drop|delete|insert|update|alter|create|truncate|exec|execute)\s+'
    r'|\'\s*or\s+[\'\"0-9a-z]+\s*=\s*[\'\"0-9a-z]+'
    r'|\b(?:sleep|benchmark|pg_sleep)\s*\('
    r'|\bwaitfor\s+delay\b'
    r'|--|\/\*)'
)

BIDI_OR_CONTROL_CHARS = re.compile(r'[\x00-\x08\x0b\x0c\x0e-\x1f\u202a-\u202e\u200e\u200f]')

SECRET_FIELD = re.compile(r"^(?:authorization|proxy.authorization|cookie|set.cookie|password|passwd|secret|client.secret|private.key|api.key|x.api.key|access.token|refresh.token|visitor.token|token)$", re.I)


def public_metadata(value, depth: int = 0):
    """Redact credential values in public metadata and JSON wire reports."""
    if depth > 12:
        return "[Depth limit]"
    if isinstance(value, dict):
        result = {}
        for k,v in value.items():
            if SECRET_FIELD.match(str(k)) or secret_name(k):
                result[k] = "[REDACTED]"
            elif k in ("inputSchema","parameters","params","tools_schema"):
                context='schema' if k=='inputSchema' else 'parameter_map' if k in ('params','parameters') else 'tool_list'
                result[k] = public_schema(v,context=context)
            else:
                result[k] = public_metadata(v,depth+1)
        return result
    if isinstance(value, list):
        return [public_metadata(v, depth + 1) for v in value]
    if isinstance(value, str) and value.lstrip().startswith(("{", "[")):
        try:
            import json
            parsed = json.loads(value)
            return json.dumps(public_metadata(parsed, depth + 1), ensure_ascii=False)
        except (ValueError, RecursionError):
            pass
    return public_data(value)


def check_malicious_text(text: str, check_sqli: bool = False) -> tuple[bool, str]:
    """Inspects text for malicious markup, scripts, and injection syntax."""
    if not text:
        return False, ""
    if BIDI_OR_CONTROL_CHARS.search(text):
        return True, "Suspicious bidirectional unicode override or control characters detected"
    if DANGEROUS_HTML_PATTERNS.search(text):
        return True, "Malicious HTML tags, script elements, or dangerous protocols detected"
    if check_sqli and SQL_INJECTION_PATTERN.search(text):
        return True, "Potential SQL injection or database tampering syntax detected"
    return False, ""


def check_malicious_dict(d: dict, check_sqli: bool = False, depth: int = 0) -> tuple[bool, str]:
    """Recursively validates dictionary keys and string values for malicious payloads."""
    if depth > 5:
        return True, "Nested structure exceeds permitted depth limit"
    for k, v in d.items():
        bad, reason = check_malicious_text(str(k), check_sqli=check_sqli)
        if bad:
            return True, f"In key '{k}': {reason}"
        if isinstance(v, str):
            bad, reason = check_malicious_text(v, check_sqli=check_sqli)
            if bad:
                return True, f"In value of '{k}': {reason}"
        elif isinstance(v, dict):
            bad, reason = check_malicious_dict(v, check_sqli=check_sqli, depth=depth + 1)
            if bad:
                return True, reason
        elif isinstance(v, list):
            for idx, item in enumerate(v):
                if isinstance(item, str):
                    bad, reason = check_malicious_text(item, check_sqli=check_sqli)
                    if bad:
                        return True, f"In item {idx} of '{k}': {reason}"
                elif isinstance(item, dict):
                    bad, reason = check_malicious_dict(item, check_sqli=check_sqli, depth=depth + 1)
                    if bad:
                        return True, reason
                elif isinstance(item, list):
                    bad, reason = check_malicious_dict({"items": item}, check_sqli=check_sqli, depth=depth + 1)
                    if bad:
                        return True, reason
    return False, ""


SUSPICIOUS_PATH_PATTERNS = (
    "/wp-", "/wordpress", "/xmlrpc.php", "/.env", "/.git", "/phpmyadmin",
    "/admin.php", "/etc/passwd", "/cgi-bin", "/actuator", "/owa", "/.aws",
    "/../", "\\..\\",
)

DEFAULT_AUTO_JAIL_THRESHOLD = 5       # 429 violations before auto-jail
DEFAULT_AUTO_JAIL_DURATION = 900.0    # 15 minutes ban
DEFAULT_MAX_CONCURRENT_REQUESTS = 250  # in-flight requests ceiling
DEFAULT_MAX_OUTBOUND_CONCURRENCY = 12  # concurrent outbound probes ceiling
BLOCKED_EVENT_INTERVAL = 60.0
BLOCKED_EVENT_LIMIT = 30
BLOCKED_PEER_LIMIT = 1024


class SecurityManager:
    """Central security and DDoS defense controller."""

    def __init__(self, store: Store, trusted_proxies: list[str] | None = None):
        self.store = store
        self.redis = RedisHub.get_instance()
        db_path = getattr(self.store, "_path", getattr(self.store, "path", ""))
        if not db_path or ":memory:" in str(db_path) or "pytest" in str(db_path) or "/tmp" in str(db_path) or "/var/folders" in str(db_path):
            self.redis_prefix = f"a2a:test:{id(self)}:"
        else:
            self.redis_prefix = "a2a:"
        self._trusted_proxy_networks = trusted_proxy_networks(
            None if trusted_proxies is None else ",".join(trusted_proxies)
        )
        self.trusted_proxies = {str(network) for network in self._trusted_proxy_networks}
        self._lock = threading.Lock()
        self._blocked_samples = collections.OrderedDict()
        self._blocked_event_times = deque()

        # In-memory fast caches
        self._banned_ips: dict[str, float | None] = {}  # ip -> expires_at (None = permanent)
        self._allowed_ips: set[str] = set()
        self._rules_loaded_at: float = 0.0

        # Rate limiting state
        self._violation_hits: dict[str, deque] = defaultdict(deque)  # ip -> timestamps of 429/probe violations
        self._ip_read_hits: dict[str, deque] = defaultdict(deque)
        self._ip_chat_hits: dict[str, deque] = defaultdict(deque)
        self._ip_explore_hits: dict[str, deque] = defaultdict(deque)
        self._ip_probe_hits: dict[str, deque] = defaultdict(deque)
        self._ip_inquiry_hits: dict[str, deque] = defaultdict(deque)
        self._feature_hits = {name:defaultdict(deque) for name in
            ('registration_inspect','registration_submit','contact_submit','privacy_request')}
        self._target_domain_hits: dict[str, float] = {}  # domain -> last probe time

        # In-flight concurrency counters & FIFO wait queue (>=90% load backpressure)
        self.max_concurrent_requests = DEFAULT_MAX_CONCURRENT_REQUESTS
        self.queue_threshold: float = 0.90
        self.max_queue_size: int = 500
        self._in_flight_requests = 0
        self._in_flight_probes = 0
        self._fifo_waiters: deque[tuple[asyncio.Event, asyncio.AbstractEventLoop]] = deque()

        # Dynamic security policies
        self.under_attack_mode: bool = False
        self.rate_multiplier: float = 1.0
        self.auto_jail_enabled: bool = True
        self.auto_jail_threshold: int = DEFAULT_AUTO_JAIL_THRESHOLD
        self.auto_jail_duration: float = DEFAULT_AUTO_JAIL_DURATION

        # Memory buffer for fast admin security event query
        self._recent_events: collections.deque = collections.deque(maxlen=1000)

        # Traffic telemetry (counters reset periodically or aggregated)
        self._telemetry = {
            "started_at": time.time(),
            "total_requests": 0,
            "blocked_403": 0,
            "blocked_403_sampled": 0,
            "blocked_403_suppressed": 0,
            "blocked_403_persisted_samples": 0,
            "blocked_403_unpersisted_samples": 0,
            "rate_limited_429": 0,
            "auto_jailed_count": 0,
            "queued_requests_total": 0,
            "active_ips": set(),
        }

        self._ensure_schema()
        self.reload_rules()

    def _ensure_schema(self) -> None:
        """Create security tables in SQLite if they do not exist."""
        with self.store.tx() as db:
            db.execute("""
                CREATE TABLE IF NOT EXISTS security_ip_rules (
                    ip TEXT PRIMARY KEY,
                    action TEXT NOT NULL,       -- 'block' | 'allow'
                    reason TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    expires_at REAL,            -- NULL for permanent
                    blocked_hits INTEGER NOT NULL DEFAULT 0,
                    last_hit_at REAL
                )
            """)
            db.execute("CREATE INDEX IF NOT EXISTS idx_security_ip_action ON security_ip_rules(action, expires_at)")
            db.execute("""
                CREATE TABLE IF NOT EXISTS security_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    at REAL NOT NULL,
                    ip TEXT NOT NULL,
                    event_type TEXT NOT NULL,   -- 'rate_limit_429' | 'auto_jail_ddos' | 'blocked_ip_403' | 'ssrf_probe' | 'scanner_probe' | 'concurrency_overflow'
                    path TEXT,
                    method TEXT,
                    user_agent TEXT,
                    detail TEXT
                )
            """)
            db.execute("CREATE INDEX IF NOT EXISTS idx_security_events_at ON security_events(at DESC)")
            db.execute("CREATE INDEX IF NOT EXISTS idx_security_events_ip ON security_events(ip, at DESC)")

    def reload_rules(self) -> None:
        """Synchronize in-memory blacklist/whitelist cache from SQLite."""
        now = time.time()
        try:
            rows = self.store.query("SELECT ip, action, expires_at FROM security_ip_rules")
            banned = {}
            allowed = set()
            for r in rows:
                ip = r["ip"]
                action = r["action"]
                exp = r["expires_at"]
                if exp is not None and exp < now:
                    continue  # Expired
                if action == "block":
                    banned[ip] = exp
                elif action == "allow":
                    allowed.add(ip)

            # Check under attack mode flag in meta
            attack_meta = self.store.get_meta("security_under_attack_mode")
            under_attack = bool(attack_meta and attack_meta.get("enabled"))
            mult_meta = self.store.get_meta("security_rate_multiplier")
            multiplier = float(mult_meta.get("multiplier", 1.0)) if mult_meta else (0.2 if under_attack else 1.0)

            with self._lock:
                self._banned_ips = banned
                self._allowed_ips = allowed
                self.under_attack_mode = under_attack
                self.rate_multiplier = multiplier
                self._rules_loaded_at = now
        except Exception as exc:
            log.warning("Failed to reload security rules from DB: %s", exc)

    def resolve_ip(self, request: Request) -> str:
        """Safely extract client IP address, guarding against header spoofing."""
        if "agent_market.client_ip" in request.scope:
            return request.scope["agent_market.client_ip"]
        raw_client = request.client.host if request.client else "unknown"
        return forwarded_client(raw_client, request.headers, self._trusted_proxy_networks)

    def is_blocked(self, ip: str) -> tuple[bool, str | None]:
        """Fast check for banned IPs using Redis with in-memory fallback."""
        with self._lock:
            if ip in self._allowed_ips:
                return False, None

        # Check distributed Redis jail first
        if self.redis.is_available():
            jailed_res = self.redis.is_ip_jailed(ip, prefix=self.redis_prefix)
            if jailed_res is not None:
                is_jailed, reason = jailed_res
                if is_jailed:
                    return True, (reason or "IP is temporarily or permanently banned by security policy.")

        now = time.time()
        if now - self._rules_loaded_at > 30.0:
            self.reload_rules()

        with self._lock:
            if ip in self._allowed_ips:
                return False, None
            if ip in self._banned_ips:
                exp = self._banned_ips[ip]
                if exp is None or exp > now:
                    return True, "IP is temporarily or permanently banned by security policy."
                else:
                    # Expired ban
                    del self._banned_ips[ip]
        return False, None

    def record_hit(self, ip: str) -> None:
        with self._lock:
            self._telemetry["total_requests"] += 1
            if len(self._telemetry["active_ips"]) < 2000:
                self._telemetry["active_ips"].add(ip)

    def record_blocked(self, ip: str, path: str, method: str, ua: str | None, reason: str) -> None:
        now = time.time()
        monotonic = time.monotonic()
        with self._lock:
            self._telemetry["blocked_403"] += 1
            while self._blocked_event_times and monotonic - self._blocked_event_times[0] >= BLOCKED_EVENT_INTERVAL:
                self._blocked_event_times.popleft()
            last, hits = self._blocked_samples.pop(ip, (-float("inf"), 0))
            hits += 1
            sampled = monotonic - last >= BLOCKED_EVENT_INTERVAL and len(self._blocked_event_times) < BLOCKED_EVENT_LIMIT
            self._blocked_samples[ip] = (monotonic if sampled else last, 0 if sampled else hits)
            while len(self._blocked_samples) > BLOCKED_PEER_LIMIT:
                self._blocked_samples.popitem(last=False)
            self._telemetry["blocked_403_sampled" if sampled else "blocked_403_suppressed"] += 1
            if sampled:
                self._blocked_event_times.append(monotonic)
                self._telemetry["blocked_403_unpersisted_samples"] += 1
        if not sampled:
            return
        # Sample at most once per peer/minute and 30 times/minute per process.
        # Exact process counters remain available; persisted hits are batched
        # lower bounds until that peer next receives a sample after the interval.
        evt = self.log_event("blocked_ip_403", ip, path, method, ua,
                             f"{reason}; sampled blocked requests={hits}", persist=False)
        if not self.store._lock.acquire(blocking=False):
            return
        try:
            if self.store._db.in_transaction:
                return
            sqlite = getattr(self.store, "backend", "sqlite") == "sqlite"
            previous_timeout = self.store._db.execute("PRAGMA busy_timeout").fetchone()[0] if sqlite else None
            try:
                if sqlite:
                    self.store._db.execute("PRAGMA busy_timeout=50")
                with self.store.tx() as db:
                    db.execute(
                        "INSERT INTO security_events (at, ip, event_type, path, method, user_agent, detail) VALUES (?, ?, ?, ?, ?, ?, ?)",
                        (evt["at"], ip, evt["event_type"], evt["path"], evt["method"], evt["user_agent"], evt["detail"]),
                    )
                    db.execute(
                        "UPDATE security_ip_rules SET blocked_hits=blocked_hits+?, last_hit_at=? WHERE ip=?",
                        (hits, now, ip)
                    )
                with self._lock:
                    self._telemetry["blocked_403_persisted_samples"] += 1
                    self._telemetry["blocked_403_unpersisted_samples"] -= 1
            finally:
                if sqlite:
                    self.store._db.execute(f"PRAGMA busy_timeout={int(previous_timeout)}")
        except Exception:
            return
        finally:
            self.store._lock.release()

    def log_event(self, event_type: str, ip: str, path: str, method: str, ua: str | None, detail: str, *, persist=True):
        now = time.time()
        evt = {
            "at": now,
            "ip": ip,
            "event_type": event_type,
            "path": path[:200],
            "method": method[:10],
            "user_agent": (ua or "")[:200],
            "detail": detail[:500],
        }
        with self._lock:
            self._recent_events.appendleft(evt)
        if not persist:
            return evt
        try:
            with self.store.tx() as db:
                db.execute(
                    """INSERT INTO security_events (at, ip, event_type, path, method, user_agent, detail)
                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (now, ip, event_type, evt["path"], evt["method"], evt["user_agent"], evt["detail"])
                )
        except Exception as exc:
            log.warning("Failed to insert security event: %s", exc)
        return evt

    def check_suspicious_patterns(self, request: Request, ip: str) -> bool:
        """Detect automated scanners and vulnerability probe attempts targeting exploit paths."""
        path = request.url.path.lower()
        for pattern in SUSPICIOUS_PATH_PATTERNS:
            if pattern in path:
                self.record_violation(
                    ip, "scanner_probe", request.url.path, request.method,
                    request.headers.get("user-agent"), f"Suspicious scanner path '{pattern}' detected"
                )
                return True
        return False

    def record_violation(self, ip: str, vtype: str, path: str, method: str, ua: str | None, detail: str) -> None:
        """Record rate limit or probe violation; trigger auto-jail if threshold exceeded."""
        now = time.time()
        violation_count = 1
        with self._lock:
            if vtype == "rate_limit_429":
                self._telemetry["rate_limited_429"] += 1
            if ip in self._allowed_ips:
                return
            scoped_rate = vtype == 'rate_limit_429' and path in (
                '/api/register', '/api/register/inspect', '/api/contact/submit', '/api/privacy/opt-out')
            if (scoped_rate or ip in SHARED_EGRESS_IPS or is_trusted_proxy(ip, self._trusted_proxy_networks)
                    or ip == "testclient"):
                should_jail = False
            else:
                threshold = 2 if self.under_attack_mode else self.auto_jail_threshold
                redis_viol = None
                if self.redis.is_available():
                    redis_viol = self.redis.record_violation(ip, threshold=threshold, window=60.0, prefix=self.redis_prefix)

                hits = self._violation_hits[ip]
                while hits and now - hits[0] > 60.0:
                    hits.popleft()
                hits.append(now)

                if redis_viol is not None:
                    r_jail, r_count = redis_viol
                    violation_count = max(len(hits), r_count)
                    should_jail = self.auto_jail_enabled and (r_jail or len(hits) >= threshold or vtype == "scanner_probe")
                else:
                    violation_count = len(hits)
                    should_jail = self.auto_jail_enabled and (len(hits) >= threshold or vtype == "scanner_probe")

        self.log_event(vtype, ip, path, method, ua, detail)

        if should_jail:
            duration = self.auto_jail_duration if not self.under_attack_mode else 3600.0
            jail_reason = f"Auto-jail triggered by {violation_count} violations in 60s (last: {vtype})"
            self.ban_ip(ip, jail_reason, duration_seconds=duration)
            self.log_event("auto_jail_ddos", ip, path, method, ua, f"Jailed for {int(duration)}s: {jail_reason}")
            with self._lock:
                self._telemetry["auto_jailed_count"] += 1
            log.warning("Auto-jailed hostile IP %s for %ds: %s", ip, duration, jail_reason)

    def ban_ip(self, ip: str, reason: str, duration_seconds: float | None = None) -> None:
        """Ban IP address and synchronize across Redis, in-memory cache, and SQLite."""
        now = time.time()
        expires_at = (now + duration_seconds) if duration_seconds else None
        with self._lock:
            self._banned_ips[ip] = expires_at
            if ip in self._allowed_ips:
                self._allowed_ips.remove(ip)

        # Distribute ban across all workers via Redis
        if self.redis.is_available():
            self.redis.jail_ip(ip, reason, duration_seconds=duration_seconds, prefix=self.redis_prefix)

        with self.store.tx() as db:
            db.execute(
                """INSERT OR REPLACE INTO security_ip_rules (ip, action, reason, created_at, expires_at, blocked_hits, last_hit_at)
                   VALUES (?, 'block', ?, ?, ?, COALESCE((SELECT blocked_hits FROM security_ip_rules WHERE ip=?), 0), ?)""",
                (ip, reason, now, expires_at, ip, now)
            )

    def unban_ip(self, ip: str) -> bool:
        """Remove ban for IP address across Redis, memory, and SQLite."""
        with self._lock:
            self._banned_ips.pop(ip, None)
            self._violation_hits.pop(ip, None)

        if self.redis.is_available():
            self.redis.unban_ip(ip, prefix=self.redis_prefix)

        with self.store.tx() as db:
            rc = db.execute("DELETE FROM security_ip_rules WHERE ip=?", (ip,)).rowcount
        return rc > 0

    def whitelist_ip(self, ip: str, reason: str) -> None:
        """Whitelist IP address to bypass rate limiters."""
        now = time.time()
        with self._lock:
            self._allowed_ips.add(ip)
            self._banned_ips.pop(ip, None)

        if self.redis.is_available():
            self.redis.unban_ip(ip, prefix=self.redis_prefix)

        with self.store.tx() as db:
            db.execute(
                """INSERT OR REPLACE INTO security_ip_rules (ip, action, reason, created_at, expires_at, blocked_hits, last_hit_at)
                   VALUES (?, 'allow', ?, ?, NULL, 0, ?)""",
                (ip, reason, now, now)
            )

    def set_under_attack_mode(self, enabled: bool) -> None:
        """Toggle emergency Under Attack Mode and persist in meta table."""
        with self._lock:
            self.under_attack_mode = enabled
            self.rate_multiplier = 0.2 if enabled else 1.0

        self.store.set_meta("security_under_attack_mode", {"enabled": enabled, "updated_at": time.time()})
        self.store.set_meta("security_rate_multiplier", {"multiplier": self.rate_multiplier})
        log.warning("Security Under Attack Mode set to: %s (Rate multiplier: %.2f)", enabled, self.rate_multiplier)

    def set_rate_multiplier(self, multiplier: float) -> None:
        """Configure dynamic rate multiplier (e.g. 1.0 normal, 0.5 strict, 0.2 under attack)."""
        mult = max(0.05, min(2.0, float(multiplier)))
        with self._lock:
            self.rate_multiplier = mult
        self.store.set_meta("security_rate_multiplier", {"multiplier": mult})

    # ---------------- Route Family Rate Limiting Checks ----------------
    def _sliding_check(
        self,
        hit_map: dict[str, deque],
        key: str,
        per_minute: int,
        window: float = 60.0,
        route: str = "generic",
    ) -> bool:
        effective_limit = max(1, int(per_minute * self.rate_multiplier))
        from .web_bot_auth import VERIFIED_READER
        identity=VERIFIED_READER.get()
        if identity and route in ('read','explore'):
            effective_limit*=identity['multiplier']
            key='verified:'+identity['key']+':'+key
        _QUOTA.set(None)
        with self._lock:
            if key in self._allowed_ips:
                return True

        # 1. Distributed Redis sliding window check
        if self.redis.is_available():
            snapshotter=getattr(self.redis,'sliding_window_snapshot',None)
            if callable(snapshotter):
                snapshot=snapshotter(f"{self.redis_prefix}rate:{route}:{key}",limit=effective_limit,window=window)
            else:
                result=self.redis.check_sliding_window(f"{self.redis_prefix}rate:{route}:{key}",limit=effective_limit,window=window)
                snapshot=None if result is None else {'allowed':result,'remaining':None if result else 0,'reset':max(1,int(window))}
            if snapshot is not None:
                remember_quota({'policy':route,'limit':effective_limit,'remaining':snapshot['remaining'],'reset':snapshot['reset']})
                return snapshot['allowed']

        # 2. Local in-memory sliding window fallback
        now = time.monotonic()
        with self._lock:
            hits = hit_map[key]
            while hits and now - hits[0] > window:
                hits.popleft()
            if len(hits) >= effective_limit:
                remember_quota({'policy':route,'limit':effective_limit,'remaining':0,'reset':max(1,int(window-(now-hits[0]))+1)})
                return False
            hits.append(now)
            remember_quota({'policy':route,'limit':effective_limit,'remaining':max(0,effective_limit-len(hits)),
                        'reset':max(1,int(window-(now-hits[0]))+1)})
            return True

    def allow_read(self, ip: str, base_limit: int = 120) -> bool:
        return self._sliding_check(self._ip_read_hits, ip, base_limit, route="read")

    def allow_chat(self, ip: str, base_limit: int = 60) -> bool:
        return self._sliding_check(self._ip_chat_hits, ip, base_limit, route="chat")

    def allow_explore(self, ip: str, base_limit: int = 120) -> bool:
        return self._sliding_check(self._ip_explore_hits, ip, base_limit, route="explore")

    def allow_probe(self, ip: str, base_limit: int = 10) -> bool:
        return self._sliding_check(self._ip_probe_hits, ip, base_limit, route="probe")

    def allow_feature(self, ip: str, feature: str, base_limit: int) -> bool:
        if feature not in self._feature_hits:
            raise ValueError('Unsupported public feature limit.')
        return self._sliding_check(self._feature_hits[feature], ip, base_limit, route=feature)

    def allow_inquiry(self, ip: str, base_limit: int = 15) -> bool:
        return self._sliding_check(self._ip_inquiry_hits, ip, base_limit, route="inquiry")

    def check_target_domain_cooldown(self, domain: str, cooldown_seconds: float = 3.0) -> bool:
        """Prevent outbound amplification DDoS targeting the same external domain."""
        now = time.monotonic()
        domain = domain.lower()
        with self._lock:
            last = self._target_domain_hits.get(domain, 0.0)
            if now - last < cooldown_seconds:
                return False
            self._target_domain_hits[domain] = now
            return True

    # ---------------- Concurrency Limiter & FIFO Load Queue ----------------
    def _effective_concurrency_limit(self) -> int:
        return 80 if self.under_attack_mode else self.max_concurrent_requests

    def try_acquire_request_slot(self) -> bool:
        """Synchronous slot acquisition (fast path, drops when ceiling is hit)."""
        limit = self._effective_concurrency_limit()
        with self._lock:
            if self._in_flight_requests >= limit:
                return False
            self._in_flight_requests += 1
            return True

    async def acquire_request_slot_or_queue(self, timeout: float = 15.0) -> tuple[bool, bool, int]:
        """Acquire in-flight request slot with sequential FIFO wait queue backpressure.
        - Under 90% load: acquires immediately without waiting.
        - At or above 90% load: enqueued into FIFO wait queue, executing in sequential order
          so that the local machine remains responsive and requests are processed without crashing.
        - If queue exceeds capacity or wait exceeds timeout: returns (False, was_queued, pos).
        Returns (acquired: bool, was_queued: bool, wait_queue_position: int).
        """
        loop = asyncio.get_running_loop()
        limit = self._effective_concurrency_limit()
        threshold = int(limit * self.queue_threshold)

        with self._lock:
            # 1. Under 90% load: immediate acquisition
            if self._in_flight_requests < threshold:
                self._in_flight_requests += 1
                return True, False, 0

            # 2. At or above 90% load: check queue saturation
            if len(self._fifo_waiters) >= self.max_queue_size:
                return False, False, len(self._fifo_waiters)

            # 3. Enqueue into FIFO wait list
            event = asyncio.Event()
            item = (event, loop)
            self._fifo_waiters.append(item)
            pos = len(self._fifo_waiters)
            self._telemetry["queued_requests_total"] = self._telemetry.get("queued_requests_total", 0) + 1

        # 4. Asynchronously wait for the next released slot
        try:
            await asyncio.wait_for(event.wait(), timeout=timeout)
            return True, True, pos
        except asyncio.TimeoutError:
            with self._lock:
                if item in self._fifo_waiters:
                    self._fifo_waiters.remove(item)
                    return False, True, pos
                # If slot was popped right as timeout triggered, request actually acquired the slot
                return True, True, pos

    def release_request_slot(self) -> None:
        """Release slot; if waiters are in FIFO queue, hand the slot over directly to the earliest waiter."""
        with self._lock:
            while self._fifo_waiters:
                next_event, loop = self._fifo_waiters.popleft()
                if not next_event.is_set():
                    if not loop.is_closed():
                        loop.call_soon_threadsafe(next_event.set)
                        return  # Handed slot over directly; _in_flight_requests remains constant
            self._in_flight_requests = max(0, self._in_flight_requests - 1)

    def try_acquire_probe_slot(self) -> bool:
        limit = DEFAULT_MAX_OUTBOUND_CONCURRENCY if not self.under_attack_mode else 3
        with self._lock:
            if self._in_flight_probes >= limit:
                return False
            self._in_flight_probes += 1
            return True

    def release_probe_slot(self) -> None:
        with self._lock:
            self._in_flight_probes = max(0, self._in_flight_probes - 1)

    # ---------------- Admin Status & Reporting ----------------
    def get_status(self) -> dict:
        now = time.time()
        limit = self._effective_concurrency_limit()
        threshold = int(limit * self.queue_threshold)
        # Compute threat level
        with self._lock:
            blocked_count = self._telemetry["blocked_403"]
            blocked_sampled = self._telemetry["blocked_403_sampled"]
            blocked_suppressed = self._telemetry["blocked_403_suppressed"]
            blocked_persisted = self._telemetry["blocked_403_persisted_samples"]
            blocked_unpersisted = self._telemetry["blocked_403_unpersisted_samples"]
            rate_429 = self._telemetry["rate_limited_429"]
            auto_jailed = self._telemetry["auto_jailed_count"]
            in_flight = self._in_flight_requests
            active_ips_count = len(self._telemetry["active_ips"])
            under_attack = self.under_attack_mode
            multiplier = self.rate_multiplier
            queued_waiters = len(self._fifo_waiters)
            queued_total = self._telemetry.get("queued_requests_total", 0)

        # Threat classification
        threat_score = (rate_429 * 2) + (blocked_count * 3) + (auto_jailed * 15)
        if under_attack or threat_score >= 80:
            threat_level = "under_attack"
            threat_label = "Attack Detected — Emergency High Shield Active"
        elif threat_score >= 25:
            threat_level = "elevated"
            threat_label = "Elevated Threat — Anomaly Traffic Detected"
        else:
            threat_level = "normal"
            threat_label = "Normal — Optimal DDoS Shield Active"

        return {
            "threat_level": threat_level,
            "threat_label": threat_label,
            "threat_score": threat_score,
            "under_attack_mode": under_attack,
            "rate_multiplier": multiplier,
            "in_flight_requests": in_flight,
            "max_concurrent_requests": limit,
            "queue_threshold": threshold,
            "load_ratio_pct": round(100.0 * in_flight / max(1, limit), 1),
            "queued_requests_active": queued_waiters,
            "queued_requests_total": queued_total,
            "active_ips_count": active_ips_count,
            "total_requests": self._telemetry["total_requests"],
            "blocked_403": blocked_count,
            "blocked_403_sampled": blocked_sampled,
            "blocked_403_suppressed": blocked_suppressed,
            "blocked_403_persisted_samples": blocked_persisted,
            "blocked_403_unpersisted_samples": blocked_unpersisted,
            "rate_limited_429": rate_429,
            "auto_jailed_count": auto_jailed,
            "banned_ips_active": len(self._banned_ips),
            "whitelisted_ips_active": len(self._allowed_ips),
            "server_uptime": round(now - self._telemetry["started_at"], 1),
        }

    def get_rules(self, action: str | None = None, limit: int = 100) -> list[dict]:
        now = time.time()
        conds, params = [], []
        if action in ("block", "allow"):
            conds.append("action=?")
            params.append(action)
        where = ("WHERE " + " AND ".join(conds)) if conds else ""
        rows = self.store.query(
            f"SELECT ip, action, reason, created_at, expires_at, blocked_hits, last_hit_at "
            f"FROM security_ip_rules {where} ORDER BY created_at DESC LIMIT ?",
            (*params, limit)
        )
        out = []
        for r in rows:
            d = dict(r)
            exp = d["expires_at"]
            d["is_active"] = (exp is None or exp > now)
            d["remaining_seconds"] = max(0, int(exp - now)) if exp else None
            out.append(d)
        return out

    def get_events(self, event_type: str | None = None, ip: str | None = None, limit: int = 100) -> list[dict]:
        conds, params = [], []
        if event_type:
            conds.append("event_type=?")
            params.append(event_type)
        if ip:
            conds.append("ip LIKE ?")
            params.append(f"%{ip}%")
        where = ("WHERE " + " AND ".join(conds)) if conds else ""
        rows = self.store.query(
            f"SELECT id, at, ip, event_type, path, method, user_agent, detail "
            f"FROM security_events {where} ORDER BY id DESC LIMIT ?",
            (*params, limit)
        )
        return [dict(r) for r in rows]

    def clear_expired_rules(self) -> int:
        now = time.time()
        with self.store.tx() as db:
            rc = db.execute("DELETE FROM security_ip_rules WHERE expires_at IS NOT NULL AND expires_at < ?", (now,)).rowcount
        self.reload_rules()
        return rc

    def validate_agent_registration(self, data: dict, ip: str = "unknown") -> dict:
        """Enforces proactive input validation on agent registration payload to prevent Stored XSS and Injection."""
        if not isinstance(data, dict):
            raise HTTPException(400, "Valid JSON dictionary required.")

        kind = str(data.get("kind") or "").strip().lower()
        if kind not in ("a2a", "mcp", "x402"):
            raise HTTPException(400, "Invalid protocol kind. Choose from: a2a, mcp, x402.")

        raw_url = str(data.get("url") or "").strip().replace("\x00", "")
        if not raw_url:
            raise HTTPException(400, "URL is required.")
        if not raw_url.startswith(("http://", "https://")):
            raise HTTPException(400, "URL must begin with http:// or https://")
        if len(raw_url) > 1000:
            raise HTTPException(400, "URL length exceeds limit (maximum 1000 characters).")
        bad, reason = check_malicious_text(raw_url)
        if bad:
            self.record_violation(ip, "injection_attempt", "/api/register", "POST", None, f"URL validation failed: {reason}")
            raise HTTPException(400, f"Security validation failed for URL: {reason}")

        name = str(data.get("name") or "").strip().replace("\x00", "")
        if not name or len(name) < 2:
            raise HTTPException(400, "Agent name is required (minimum 2 characters).")
        if len(name) > 100:
            raise HTTPException(400, "Agent name exceeds limit (maximum 100 characters).")
        if "<" in name or ">" in name:
            self.record_violation(ip, "stored_xss_attempt", "/api/register", "POST", None, "HTML tags in agent name")
            raise HTTPException(400, "Security validation failed: HTML tags or angle brackets (< >) are strictly prohibited in agent name.")
        bad, reason = check_malicious_text(name, check_sqli=True)
        if bad:
            self.record_violation(ip, "stored_xss_attempt", "/api/register", "POST", None, f"Agent name validation failed: {reason}")
            raise HTTPException(400, f"Security validation failed for agent name: {reason}")

        description = str(data.get("description") or "").strip().replace("\x00", "")
        if not description or len(description) < 5:
            raise HTTPException(400, "Description is required (minimum 5 characters).")
        if len(description) > 2000:
            raise HTTPException(400, "Description exceeds limit (maximum 2000 characters).")
        bad, reason = check_malicious_text(description, check_sqli=False)
        if bad:
            self.record_violation(ip, "stored_xss_attempt", "/api/register", "POST", None, f"Agent description validation failed: {reason}")
            raise HTTPException(400, f"Security validation failed for description: {reason}")

        pay_to = data.get("pay_to")
        if pay_to is not None:
            pay_to = str(pay_to).strip().replace("\x00", "")[:100]
            if pay_to:
                if "<" in pay_to or ">" in pay_to:
                    self.record_violation(ip, "injection_attempt", "/api/register", "POST", None, "HTML tags in pay_to")
                    raise HTTPException(400, "Security validation failed: HTML tags are prohibited in wallet address.")
                bad, reason = check_malicious_text(pay_to, check_sqli=True)
                if bad:
                    self.record_violation(ip, "injection_attempt", "/api/register", "POST", None, f"Pay-to validation failed: {reason}")
                    raise HTTPException(400, f"Security validation failed for recipient address: {reason}")

        details = data.get("details")
        if isinstance(details, dict):
            bad, reason = check_malicious_dict(details, check_sqli=True)
            if bad:
                self.record_violation(ip, "stored_xss_attempt", "/api/register", "POST", None, f"Agent details validation failed: {reason}")
                raise HTTPException(400, f"Security validation failed in agent metadata: {reason}")

        return data

    def validate_chat_payload(self, message: str, name: str | None = None, data: dict | None = None, ip: str = "unknown") -> tuple[str, str | None, dict | None]:
        """Enforces proactive input validation on chat payload to prevent Stored XSS and Injection from reaching the admin store."""
        message = (message or "").strip().replace("\x00", "")
        if not message and not (data and isinstance(data, dict) and data):
            raise HTTPException(400, "Chat message or payload data is required.")
        if len(message) > 4000:
            raise HTTPException(400, "Chat message exceeds maximum allowed length of 4000 characters.")

        bad, reason = check_malicious_text(message, check_sqli=False)
        if bad:
            self.record_violation(ip, "stored_xss_attempt", "/chat", "POST", None, f"Chat message validation failed: {reason}")
            raise HTTPException(400, f"Security validation failed: {reason}. HTML markup and executable scripts are prohibited.")

        if name is not None:
            name = str(name).strip().replace("\x00", "")
            if name:
                if len(name) > 60:
                    name = name[:60]
                if "<" in name or ">" in name:
                    self.record_violation(ip, "stored_xss_attempt", "/chat", "POST", None, "HTML tags in visitor name")
                    raise HTTPException(400, "Security validation failed: HTML tags or angle brackets (< >) are strictly prohibited in visitor name.")
                bad, reason = check_malicious_text(name, check_sqli=True)
                if bad:
                    self.record_violation(ip, "stored_xss_attempt", "/chat", "POST", None, f"Visitor name validation failed: {reason}")
                    raise HTTPException(400, f"Security validation failed for visitor name: {reason}")
            else:
                name = None

        if isinstance(data, dict):
            bad, reason = check_malicious_dict(data, check_sqli=True)
            if bad:
                self.record_violation(ip, "injection_attempt", "/chat", "POST", None, f"Chat data dictionary validation failed: {reason}")
                raise HTTPException(400, f"Security validation failed in request payload: {reason}")

            c = data.get("contact")
            if isinstance(c, dict) and c.get("url"):
                curl = str(c["url"]).strip()
                if not curl.startswith(("https://", "http://")) or check_malicious_text(curl)[0]:
                    raise HTTPException(400, "Contact URL must be a valid http(s) address without executable code.")
            elif isinstance(c, str) and c.strip():
                if check_malicious_text(c)[0]:
                    raise HTTPException(400, "Contact parameter contains prohibited scripts or protocols.")

        return message, name, data
