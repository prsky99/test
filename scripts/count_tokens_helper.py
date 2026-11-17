"""Count tokens of texts with Anthropic's messages.count_tokens (no charge; PM 11-17) for necklace_value_report.

Run by gateway-data/ops-llm-venv/bin/python (anthropic 2.7.0; nothing new installed). Reads a JSON list of texts on
stdin and prints a JSON list of token counts (the count of the text alone: a one-character message's count is
subtracted). The key is read from gateway-data/secrets/anthropic-api.key and never printed or logged; each call
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


def main() -> int:
    if date.today() >= KEY_UNTIL or not KEY.exists():
        return 3
    try:
        import anthropic
    except ImportError:
        return 3
    texts = json.loads(sys.stdin.read() or "[]")
    client = anthropic.Anthropic(api_key=KEY.read_text(encoding="utf-8").strip())

    def count(text: str) -> int:
        n = client.messages.count_tokens(model=MODEL, messages=[{"role": "user", "content": text or "."}]).input_tokens
        with USAGE.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps({"at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                                 "purpose": "necklace_value_count_tokens", "model": MODEL, "outcome": "count_tokens",
                                 "usd": 0, "input": n, "output": 0, "cache_write": 0, "cache_read": 0}) + "\n")
        time.sleep(0.2)
        return n
    try:
        base = count(".")
        out = [max(0, count(t) - base + 1) for t in texts]
    except Exception as exc:                       # noqa: BLE001 - the caller falls back; the key is never printed
        print(json.dumps({"error": type(exc).__name__}), file=sys.stderr)
        return 4
    print(json.dumps(out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
