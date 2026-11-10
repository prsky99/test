#!/usr/bin/env python3
"""Small, capped Claude API helper for operations automation (11-10 user API key, $100 until 12-01).

Runs only from the separate ops virtualenv (gateway-data/ops-llm-venv, has the `anthropic` SDK); the
production services never import this. Every call:
- reads the key from gateway-data/secrets/anthropic-api.key (0600, git-ignored) and never prints it;
- refuses to run once today's estimated spend reaches DAILY_CAP_USD (returns None, callers fall back);
- caches the stable system prompt and logs tokens and estimated cost to logs/ops/llm-usage.jsonl.

`python scripts/ops_llm.py --spend` prints today's and the month's estimated spend.
"""
import json
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
KEY_FILE = ROOT / 'gateway-data/secrets/anthropic-api.key'
USAGE = ROOT / 'logs/ops/llm-usage.jsonl'
MODEL = 'claude-haiku-5-5'
DAILY_CAP_USD = 4.0
EXPIRES = '2026-12-01'
# USD per million tokens for claude-haiku-5-5 (prompts up to 100K tokens).
PRICE = {'input': 0.10, 'output': 0.50, 'cache_write': 0.125, 'cache_read': 0.01}


def _today():
    return datetime.now().strftime('%Y-%m-%d')


def spent(day_prefix, include_batches=False):
    """Estimated USD spent. The daily cap counts only small interactive calls; one-off batch jobs
    (purpose ending in _batch) have their own budget and are included only when asked."""
    total = 0.0
    if USAGE.is_file():
        for line in USAGE.read_text().splitlines():
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if not include_batches and str(row.get('purpose', '')).endswith('_batch'):
                continue
            if row.get('at', '').startswith(day_prefix):
                total += row.get('usd', 0.0)
    return round(total, 4)


def _cost(usage):
    return round((usage.input_tokens * PRICE['input']
                  + usage.output_tokens * PRICE['output']
                  + (usage.cache_creation_input_tokens or 0) * PRICE['cache_write']
                  + (usage.cache_read_input_tokens or 0) * PRICE['cache_read']) / 1_000_000, 6)


def ask(system, user, purpose, max_tokens=1200, effort='low'):
    """Return Claude's text answer, or None when the key is missing/expired, the cap is reached or the call fails."""
    if _today() >= EXPIRES or not KEY_FILE.is_file():
        return None
    if spent(_today()) >= DAILY_CAP_USD:
        return None
    import anthropic  # only available in the ops virtualenv
    client = anthropic.Anthropic(api_key=KEY_FILE.read_text().strip(), max_retries=2, timeout=60.0)
    try:
        response = client.messages.create(
            model=MODEL,
            max_tokens=max_tokens,
            output_config={'effort': effort},
            system=[{'type': 'text', 'text': system, 'cache_control': {'type': 'ephemeral'}}],
            messages=[{'role': 'user', 'content': user}],
        )
    except anthropic.APIStatusError as error:
        _log(purpose, None, f'api_status_{error.status_code}')
        return None
    except anthropic.APIConnectionError:
        _log(purpose, None, 'connection_error')
        return None
    _log(purpose, response.usage, response.stop_reason)
    if response.stop_reason == 'refusal':
        return None
    return ''.join(block.text for block in response.content if block.type == 'text').strip() or None


def _log(purpose, usage, outcome):
    USAGE.parent.mkdir(parents=True, exist_ok=True)
    row = {'at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'), 'purpose': purpose, 'model': MODEL,
           'outcome': outcome, 'usd': _cost(usage) if usage else 0.0}
    if usage:
        row.update(input=usage.input_tokens, output=usage.output_tokens,
                   cache_write=usage.cache_creation_input_tokens or 0, cache_read=usage.cache_read_input_tokens or 0)
    with USAGE.open('a') as fh:
        fh.write(json.dumps(row) + '\n')


if __name__ == '__main__':
    if '--spend' in sys.argv:
        print(json.dumps({'today_usd': spent(_today()), 'month_usd_all': spent(_today()[:7], include_batches=True),
                          'daily_cap_usd': DAILY_CAP_USD, 'expires': EXPIRES}))
    elif '--ping' in sys.argv:
        started = time.time()
        print(ask('Reply with one short Korean word.', 'ping', 'ping', max_tokens=50), round(time.time() - started, 2))
