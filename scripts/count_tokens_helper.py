"""Count tokens of texts with Anthropic's messages.count_tokens (no charge; PM 11-17) for necklace_value_report.

Run by gateway-data/ops-llm-venv/bin/python (anthropic 2.7.0; nothing new installed). Reads a JSON list of texts on
stdin and prints a JSON list of token counts (the count of the text alone: a one-character message's count is
subtracted). At most MAX_CALLS calls a run, GAP_S apart; a 429 (rate limit) is never retried: that text and the rest
come back as null, and the caller counts them as characters / 4. The key is read from gateway-data/secrets/anthropic-api.key and never printed or logged; each call
adds one line to logs/ops/llm-usage.jsonl with usd 0. Exit 3 (nothing printed) when the key is missing or past
2026-12-01, so the caller falls back to its estimate.
"""
import json
import sys
import time
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
KEY = ROOT / "gateway-data/secrets/anthropic-api.key"
USAGE = ROOT / "logs/ops/llm-usage.jsonl"
MODEL = "claude-sonnet-5-5"
KEY_UNTIL = date(2026, 12, 1)
MAX_CALLS = 300          # per run, the baseline included (PM 11-17: count_tokens has a per-minute limit)
GAP_S = 0.25             # between calls


def main() -> int:
    if date.today() >= KEY_UNTIL or not KEY.exists():
        return 3
    try:
        import anthropic
    except ImportError:
        return 3
    texts = json.loads(sys.stdin.read() or "[]")
    client = anthropic.Anthropic(api_key=KEY.read_text(encoding="utf-8").strip(), max_retries=0)   # no SDK retry on 429

    calls = {"n": 0}

    def count(text: str) -> int:
        calls["n"] += 1
        n = client.messages.count_tokens(model=MODEL, messages=[{"role": "user", "content": text or "."}]).input_tokens
        with USAGE.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps({"at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                                 "purpose": "necklace_value_count_tokens", "model": MODEL, "outcome": "count_tokens",
                                 "usd": 0, "input": n, "output": 0, "cache_write": 0, "cache_read": 0}) + "\n")
        time.sleep(GAP_S)
        return n
    try:
        base = count(".")
    except Exception as exc:                       # noqa: BLE001 - the caller falls back; the key is never printed
        print(json.dumps({"error": type(exc).__name__}), file=sys.stderr)
        return 4
    out, stopped = [], None
    for text in texts:
        if stopped or calls["n"] >= MAX_CALLS:
            stopped = stopped or "call cap"
            out.append(None)
            continue
        try:
            out.append(max(0, count(text) - base + 1))
        except Exception as exc:                   # noqa: BLE001 - 429 or any error: no retry, the rest estimated
            stopped = "rate_limited" if getattr(exc, "status_code", None) == 429 else type(exc).__name__
            out.append(None)
    if stopped:
        print(json.dumps({"stopped": stopped, "counted": sum(x is not None for x in out)}), file=sys.stderr)
    print(json.dumps(out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
