"""Dependency-free client for the public, read-only Explore API."""
from __future__ import annotations

import json
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone

BASE_URL = 'https://agentconcierge.biz'
MCP_URL = BASE_URL + '/mcp'
USER_AGENT = 'agent-concierge-python/0.1.0'


@dataclass(frozen=True)
class Agent:
    id: int
    name: str
    protocol: str
    description: str
    quality_grade: str | None
    health_status: str | None
    last_health_check: str | None
    execution_checked_at: str | None
    trial_call_ok: bool
    auth_required: bool
    page_url: str
    raw: dict = field(repr=False, compare=False, default_factory=dict)

    def summary(self) -> str:
        if self.execution_checked_at:
            check = f'execution check succeeded {self.execution_checked_at}'
        elif self.trial_call_ok:
            check = f'trial call succeeded; health check {self.last_health_check}'
        else:
            check = f'health {self.health_status or "unknown"} at {self.last_health_check or "unknown"}'
        grade = f', grade {self.quality_grade}' if self.quality_grade else ''
        return f'{self.name} ({self.protocol.upper()}{grade}): {check}. {self.page_url}'


def _iso(value):
    try:
        return datetime.fromtimestamp(float(value), timezone.utc).isoformat(timespec='seconds') if value else None
    except (TypeError, ValueError, OverflowError):
        return None


def _agent(item: dict, base: str) -> Agent:
    readiness = item.get('connection_readiness') or {}
    executed = readiness.get('verified_at') if readiness.get('verified_callable') and readiness.get('evidence_scope') == 'execution' else None
    return Agent(id=int(item['id']), name=str(item.get('name') or ''), protocol=str(item.get('kind') or ''),
                 description=str(item.get('description') or ''), quality_grade=item.get('eval_grade'),
                 health_status=item.get('health_status'), last_health_check=_iso(item.get('last_check_at')),
                 execution_checked_at=_iso(executed), trial_call_ok=bool(item.get('trial_ok')),
                 auth_required=bool(item.get('auth_required')),
                 page_url=f'{base}/new/en/explore.html#explore?q=' + urllib.parse.quote(str(item.get('name') or '')), raw=item)


class AgentConcierge:
    """Read-only discovery. Nothing here calls the agents it finds."""

    def __init__(self, base_url: str = BASE_URL, timeout: float = 20.0, opener=None):
        self.base_url = base_url.rstrip('/')
        self.timeout = timeout
        self.opener = opener or urllib.request.urlopen

    def search(self, task: str, *, protocol: str | None = None, checked_only: bool = False,
               no_auth: bool = False, limit: int = 5) -> list[Agent]:
        if not task or not task.strip():
            raise ValueError('Describe the task, for example "weather forecast for Seoul".')
        if protocol not in (None, 'a2a', 'mcp', 'x402'):
            raise ValueError('protocol must be a2a, mcp or x402')
        params = {'q': task.strip()[:500], 'limit': str(max(1, min(int(limit), 45)))}
        if protocol:
            params['kind'] = protocol
        if checked_only:
            params['verified'] = '1'
        if no_auth:
            params['no_auth'] = '1'
        request = urllib.request.Request(f'{self.base_url}/api/explore?{urllib.parse.urlencode(params)}',
                                         headers={'User-Agent': USER_AGENT, 'Accept': 'application/json'})
        with self.opener(request, timeout=self.timeout) as response:
            body = json.load(response)
        return [_agent(item, self.base_url) for item in body.get('items') or [] if item.get('id')]


def search_agents(task: str, **options) -> list[Agent]:
    return AgentConcierge().search(task, **options)
