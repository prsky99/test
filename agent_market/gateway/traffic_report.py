"""Weekly public-traffic figures for the admin console (외부 유입 주간 지표).

The frontend writes anonymous daily counts to logs/service-frontend/traffic (concierge/traffic.py:
entry x client class, bot names, MCP client names; no IP, UA or body). The admin process has its own
LOG_DIR, so it reads the frontend's directory next to it. Counts only; nothing personal is stored.
"""
from collections import Counter
from datetime import datetime, timedelta, timezone
import os
from pathlib import Path

from ..concierge import traffic


def frontend_traffic_dir():
    """TRAFFIC_DIR, else <logs>/service-frontend/traffic beside this process's LOG_DIR."""
    explicit = os.environ.get('TRAFFIC_DIR')
    if explicit:
        return Path(explicit)
    log_dir = os.environ.get('LOG_DIR')
    if log_dir:
        return Path(log_dir).parent / 'service-frontend' / 'traffic'
    return Path('logs') / 'service-frontend' / 'traffic'


def weekly(root=None, days=7, today=None):
    root = Path(root) if root is not None else frontend_traffic_dir()
    days = max(1, min(int(days), 31))
    today = today or datetime.now(timezone.utc).date()
    available = root.is_dir()
    rows = traffic.summarize(root, days, today=today) if available else []
    names, bots = Counter(), Counter()
    if available:
        for offset in range(days):
            day = traffic.load_day(root, (today - timedelta(days=offset)).isoformat())
            names.update(day['mcp_clients'])
            bots.update({key.split('|')[0]: value for key, value in day['bots'].items()})
    total = lambda key: sum(row[key] for row in rows)
    internal, external = total('internal'), total('external')
    return {
        'available': available,
        'days': days,
        'timezone': 'UTC',
        'rows': rows,
        'totals': {
            # Distinct clients are counted per day (daily salt), so the weekly figure is a sum of daily counts.
            'agent_sessions': total('agent_clients'),
            'agent_requests': total('agent_requests'),
            'mcp_clients': total('mcp_clients'),
            'mcp_client_names': len(names),
            'ai_bot_non_google': total('ai_bot_non_google'),
            'ai_bot_google': total('ai_bot_google'),
            'human_visitors': total('human_visitors'),
            'human_pages': total('human_pages'),
            'internal': internal,
            'external': external,
            'internal_ratio': round(internal / (internal + external), 4) if internal + external else None,
        },
        'mcp_clients_top': [{'name': name, 'count': count} for name, count in names.most_common(10)],
        'bots_non_google_top': [{'name': name, 'count': count} for name, count in bots.most_common(30)
                                if not name.startswith('Google')][:10],
    }
