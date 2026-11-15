"""Public check of the agent offer after approval (PM 11-15): MCP, A2A and REST, with and without ads=none. Read-only.

Ads are always shown (user 11-15): an agent that sends ads=none still gets the offer; ad-free answers will be a paid
subscription later.

  .venv/bin/python -m scripts.ad_coin_house_offer_verify [--base https://agentconcierge.biz] [--advertiser AgentValCon]

For each surface: the answer carries one `sponsored` item labelled "Sponsored" from the advertiser (text starting
"Sponsored: "), the same request with ads=none carries it too (the old opt-out is ignored), and the organic results
(recommendation ids in order) are the same with and without the ads parameter (neutrality). Every request goes on a new connection and carries
X-Agentcon-QA, so nothing is counted as a view or a click. The region is wherever this machine is (Cloudflare's
country header); the advertiser must be booked there today in the task's category.
Writes logs/ops/house-offer-verify/<time>.json; exit 1 when any check fails.
"""
import argparse
import json
import sys
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "logs/ops/house-offer-verify"
TASK = "find recent research papers about retrieval augmented generation"   # docs_knowledge -> the research ads
QA = {"X-Agentcon-QA": "house_offer_verify"}


def _ids(items):
    return [str(i.get("id")) for i in items or [] if isinstance(i, dict)]


def mcp_parts(body):
    structured = ((body or {}).get("result") or {}).get("structuredContent") or {}
    return _ids(structured.get("recommendations")), structured.get("sponsored") or []


def a2a_parts(body):
    parts = ((body or {}).get("result") or {}).get("parts") or []
    data = next((p.get("data") for p in parts if isinstance(p, dict) and isinstance(p.get("data"), dict)), {}) or {}
    return _ids(data.get("recommendations")), data.get("sponsored") or []


def rest_parts(body):
    item = (body or {}).get("sponsored")
    return None, [item] if item else []


def judge(name, with_ad, without_ad, advertiser):
    """One surface: (organic ids, sponsored items) without and with an ads=none request (which must be ignored)."""
    organic_on, ads_on = with_ad
    organic_off, ads_off = without_ad
    item = ads_on[0] if len(ads_on) == 1 else {}
    checks = {"one_sponsored_item": len(ads_on) == 1,
              "labelled": item.get("label") == "Sponsored" and str(item.get("text", "")).startswith("Sponsored: "),
              "advertiser": item.get("advertiser") == advertiser and item.get("paid_by", advertiser) == advertiser,
              "facts_independent": (item.get("facts") or {}).get("independent") is True if name != "rest" else True,
              "ads_none_ignored": len(ads_off) == 1 and ads_off[0].get("advertiser") == item.get("advertiser")}
    if organic_on is not None:
        checks["organic_same_with_and_without_ad"] = organic_on == organic_off and bool(organic_on)
    return {"surface": name, "ok": all(checks.values()), "checks": checks,
            "organic": organic_on, "facts": item.get("facts")}


def run(base, advertiser, client_factory=None):
    import httpx
    make = client_factory or (lambda: httpx.Client(timeout=20))

    def call(method, path, **kw):
        with make() as client:
            started = time.monotonic()
            reply = client.request(method, base + path, headers={**QA, **kw.pop("headers", {})}, **kw)
            return reply.json(), round(time.monotonic() - started, 2)

    def mcp(extra):
        return call("POST", "/mcp", headers={"Accept": "application/json, text/event-stream"},
                    json={"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                          "params": {"name": "find_agents", "arguments": {"task": TASK, **extra}}})

    def a2a(extra):
        message = {"role": "user", "messageId": "verify-" + uuid.uuid4().hex,
                   "parts": [{"kind": "text", "text": TASK}] + ([{"kind": "data", "data": extra}] if extra else [])}
        return call("POST", "/a2a", json={"jsonrpc": "2.0", "id": 1, "method": "message/send",
                                         "params": {"message": message}})

    def rest(extra):
        return call("GET", "/api/ad-coin/v2/sponsored/offer", params={"category": "docs_knowledge", "surface": "rest", **extra})

    results, seconds = [], {}
    for name, fn, parse in (("mcp", mcp, mcp_parts), ("a2a", a2a, a2a_parts), ("rest", rest, rest_parts)):
        on, t_on = fn({})
        off, t_off = fn({"ads": "none"})
        seconds[name] = [t_on, t_off]
        results.append(judge(name, parse(on), parse(off), advertiser))
    return {"at": time.strftime("%Y-%m-%d %H:%M:%S"), "base": base, "advertiser": advertiser, "task": TASK,
            "ok": all(r["ok"] for r in results), "results": results, "seconds": seconds}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--base", default="https://agentconcierge.biz")
    parser.add_argument("--advertiser", default="AgentValCon")
    args = parser.parse_args(argv)
    result = run(args.base.rstrip("/"), args.advertiser)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / (time.strftime("%Y%m%d-%H%M%S") + ".json")).write_text(json.dumps(result, indent=1))
    print(json.dumps({"ok": result["ok"], "failed": [(r["surface"], [k for k, v in r["checks"].items() if not v])
                                                     for r in result["results"] if not r["ok"]]}))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
