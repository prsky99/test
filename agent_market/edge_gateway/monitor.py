"""Optional read-only Cloudflare observation; missing evidence selects Origin."""
from datetime import datetime, timezone
import hashlib
import hmac
import logging
import os
import re
import secrets
import stat
import threading

from ..concierge.http_security import bounded_client, OutboundBudget
from .auth import derived, service_mac
from .config import EdgeError, parse
from .service import day_at
from .state import execute, transaction

QUERY = '''query EdgeUsage($account: string, $start: string, $end: string, $window: string) {
  viewer { accounts(filter: {accountTag: $account}) {
    usage: workersInvocationsAdaptive(limit: 1, filter: {datetime_geq: $start, datetime_leq: $end}) {
      sum { requests }
    }
    worker: workersInvocationsAdaptive(limit: 100, filter: {
      datetime_geq: $window, datetime_leq: $end, scriptName: "agentconcierge-edge-gateway"}) {
      dimensions { status }
      sum { requests errors }
    }
  } }
}'''
RETRY_SECONDS = 5
log = logging.getLogger(__name__)
# 11-11 runtime block rule (PM decision). Any Worker error in the UTC day used to block Worker execution
# with no way back; it blocked from 10-31 while the Worker had 2 exceptions in 11 days (0 CPU limit
# hits). Now: trip on the last WINDOW_SECONDS only when errors reach both MIN_ERRORS and ERROR_RATE;
# after HALF_OPEN_AFTER a HALF_OPEN_SHARE of executions tries the Worker again, and a clean window with
# at least MIN_PROBE Worker invocations clears the block. Every switch is an audit row (actor edge-monitor).
WINDOW_SECONDS = 900
ERROR_RATE = 0.02
MIN_ERRORS = 5
HALF_OPEN_AFTER = 1800
HALF_OPEN_SHARE = 0.1
MIN_PROBE = 20


def read_api_token(path):
    fd = os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_NONBLOCK', 0))
    with os.fdopen(fd, 'rb') as handle:
        info = os.fstat(handle.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_mode & 0o077 or info.st_uid != os.getuid():
            raise EdgeError('CONFIGURATION_INVALID')
        token = handle.read(257).decode('ascii').strip()
    if not re.fullmatch(r'[A-Za-z0-9_-]{20,256}', token):
        raise EdgeError('CONFIGURATION_INVALID')
    return token


class Monitor:
    def __init__(self, service, account, token, *, client=None):
        if not re.fullmatch(r'[a-fA-F0-9]{32}', account or ''):
            raise EdgeError('CONFIGURATION_INVALID')
        self.service, self.account, self.token, self.client = service, account, token, client
        self.stop = threading.Event()
        self.thread = None

    def refresh(self):
        current = self.service
        now = current.clock()
        start = day_at(now) + 'T00:00:00Z'
        end = datetime.fromtimestamp(now, timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
        window = datetime.fromtimestamp(now - WINDOW_SECONDS, timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
        client = self.client or bounded_client(allow_private=False, limit=262144, budget=OutboundBudget(10))
        try:
            response = client.post('https://api.cloudflare.com/client/v4/graphql',
                headers={'Authorization': 'Bearer ' + self.token, 'Accept-Encoding': 'identity'},
                json={'query': QUERY, 'variables': {'account': self.account, 'start': start, 'end': end, 'window': window}})
            if response.status_code != 200:
                raise EdgeError('OBSERVATION_UNAVAILABLE')
            data = parse(response.content)
            accounts = data.get('data', {}).get('viewer', {}).get('accounts', [])
            if data.get('errors') or len(accounts) != 1:
                raise EdgeError('OBSERVATION_UNAVAILABLE')
            account = accounts[0]
            if len(account.get('usage', [])) > 1 or len(account.get('worker', [])) >= 100:
                raise EdgeError('OBSERVATION_UNAVAILABLE')
            # Empty daily aggregation is valid for a day without recorded invocations.
            requests = account['usage'][0]['sum']['requests'] if account.get('usage') else 0
            if type(requests) is not int or requests < 0:
                raise EdgeError('OBSERVATION_UNAVAILABLE')
            sums = [row.get('sum', {}) for row in account.get('worker', [])]
            if any(type(s.get('errors')) is not int or type(s.get('requests')) is not int for s in sums):
                raise EdgeError('OBSERVATION_UNAVAILABLE')   # unreadable evidence: readiness lapses, no block
            errors, invoked = sum(s['errors'] for s in sums), sum(s['requests'] for s in sums)
            worker_error = errors >= MIN_ERRORS and errors >= ERROR_RATE * max(invoked, 1)
            transition = self.transition(current, now, worker_error, errors, invoked)
            healthy = False
            if requests < current.config.soft_limit and not worker_error:
                path = '/api/edge-gateway/v1/health'
                timestamp, identity, raw = str(int(now)), secrets.token_hex(16), b'{}'
                proof = client.post(current.config.origin + path, content=raw, headers={
                    'Content-Type': 'application/json', 'Accept-Encoding': 'identity', 'X-Edge-Time': timestamp,
                    'X-Edge-Nonce': identity,
                    'X-Edge-Signature': service_mac(current.config.key, 'POST', path, timestamp, identity, raw)})
                expected = hmac.new(derived(current.config.key, 'edge-health-v1'), proof.content, hashlib.sha256).hexdigest()
                if proof.status_code == 200 and hmac.compare_digest(proof.headers.get('x-edge-health-signature', ''), expected):
                    result = parse(proof.content)
                    healthy = result == {'backend': 'worker', 'nonce': identity, 'utc_day': day_at(now)}
            current.observe(requests, now, healthy=healthy)
            return {'observed': True, 'healthy': healthy, 'requests': requests, 'worker_runtime_blocked': worker_error,
                    'window_errors': errors, 'window_invocations': invoked, 'transition': transition}
        finally:
            if self.client is None:
                client.close()

    @staticmethod
    def transition(current, now, tripped, errors, invoked):
        """Apply the block rule once per observation; returns 'auto-block', 'auto-clear' or None."""
        from .state import rows
        reason = f'{errors} Worker errors in {invoked} invocations over {WINDOW_SECONDS // 60} minutes'
        with transaction(current.store) as db:
            policy = rows(db, 'policy')[0]
            last = rows(db, 'audit_monitor_last')
            auto = bool(last) and last[0]['action'] == 'auto-block'
            if tripped and (not policy['cpu_blocked'] or auto and now - last[0]['created'] >= HALF_OPEN_AFTER):
                # A new block, or a half-open probe that failed: (re)start the half-open timer.
                execute(db, 'block_cpu')
                execute(db, 'audit', (policy['revision'] + 1, 'auto-block', 'edge-monitor', reason[:300], now))
                log.warning('Edge Worker execution blocked: %s', reason)
                return 'auto-block'
            if (policy['cpu_blocked'] and auto and not tripped and invoked >= MIN_PROBE
                    and now - last[0]['created'] >= HALF_OPEN_AFTER + WINDOW_SECONDS):
                if execute(db, 'clear_block', (policy['revision'],)).rowcount == 1:
                    execute(db, 'audit', (policy['revision'] + 1, 'auto-clear', 'edge-monitor', reason[:300], now))
                    log.warning('Edge Worker execution block cleared after a clean half-open window: %s', reason)
                    return 'auto-clear'
        return None

    def start(self):
        if self.thread and self.thread.is_alive():
            return
        self.thread = threading.Thread(target=self.loop, name='edge-readonly-observer', daemon=True)
        self.thread.start()

    def loop(self):
        while not self.stop.is_set():
            try:
                try:
                    self.refresh()
                except Exception as first:
                    # One transient analytics/health miss (rate limit, 5xx, timeout) is retried
                    # once before readiness is withdrawn; freshness expiry still bounds it.
                    logging.getLogger(__name__).warning('Edge observation retry after %s', getattr(first, 'code', type(first).__name__))
                    if self.stop.wait(RETRY_SECONDS):
                        break
                    self.refresh()
            except Exception as error:
                logging.getLogger(__name__).warning('Edge observation failed: %s', getattr(error, 'code', type(error).__name__))
                # A repeated failed observation invalidates earlier readiness immediately.
                try:
                    with transaction(self.service.store) as db:
                        execute(db, 'health', ('', 0))
                except Exception:
                    logging.getLogger(__name__).warning('Edge readiness invalidation unavailable; freshness expiry remains enforced')
            self.stop.wait(60)

    def close(self):
        self.stop.set()
        if self.thread is not None:
            self.thread.join(12)


def start_for(front):
    service = getattr(front, 'edge_gateway', None)
    account = os.environ.get('AGENT_EDGE_CLOUDFLARE_ACCOUNT')
    path = os.environ.get('AGENT_EDGE_CLOUDFLARE_TOKEN_FILE')
    if service is None or not service.available or not service.config.worker_ready or not account or not path:
        return None
    try:
        monitor = Monitor(service, account, read_api_token(path))
        monitor.start()
        return monitor
    except (EdgeError, OSError, UnicodeError):
        return None
