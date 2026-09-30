"""운영 점검용: 가상의 클라이언트 에이전트들이 실제 게이트웨이에 요청을 보내고 결과를 검증한다.

    python scripts/simulate_clients.py http://127.0.0.1:8200 --rounds 3

각 클라이언트는 새 지갑으로 요청에 서명한다. 테스트넷 USDC가 없으므로 유료 수락은 하지 않고,
무료 첫 소개·재방문 시 유료 견적·상태 조회·평가·지연시간·오류율을 측정한다.
"""

import argparse
import json
import statistics
import sys
import time

import httpx
from eth_account import Account

sys.path.insert(0, ".")
from agent_market.gateway.client import GatewayClient  # noqa: E402

TASKS = [
    ("web search API for recent news about a company", None),
    ("find email and linkedin contacts for people at a company (lead enrichment)", None),
    ("scrape a web page and extract its text content", None),
    ("ERC20 token balance for a wallet on Ethereum", None),
    ("smart money wallet tracking and DeFi analytics", None),
    ("latest crypto token price by symbol", None),
    ("call an LLM to summarize a long document", None),
    ("generate an image from a text prompt", None),
    ("twitter / X posts and sentiment for a keyword", None),
    ("forecast probability for a prediction market question", "prediction"),
]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("gateway")
    ap.add_argument("--rounds", type=int, default=2)
    args = ap.parse_args()

    http = httpx.Client(timeout=120.0)
    latencies, errors, outcomes = [], 0, []
    for rnd in range(args.rounds):
        for task, category in TASKS:
            acct = Account.create()
            client = GatewayClient(args.gateway, acct.key.hex(), http=http)
            for attempt in ("first", "repeat"):
                t0 = time.monotonic()
                try:
                    out = client.create_need(task, category=category)
                except httpx.HTTPError as exc:
                    errors += 1
                    print(f"ERROR {task[:40]}: {exc}")
                    continue
                latencies.append(time.monotonic() - t0)
                agent = out.get("agent") or {}
                offer = out.get("offer") or {}
                outcomes.append((attempt, out["status"], out["free_intro"]))
                print(f"[{rnd}:{attempt}] {out['category']:<16} {out['status']:<14} free={out['free_intro']!s:<5} "
                      f"{(agent.get('name') or ('fee ' + str(offer.get('fee'))) if offer else agent.get('name') or '-')[:60]}")
                if attempt == "first" and out["status"] == "active":
                    client.feedback(out["need_id"], success=True, rating=4)
                    st = client.status(out["need_id"])
                    assert st["current_agent"]["url"] == agent["url"], "status mismatch"
    firsts = [o for o in outcomes if o[0] == "first"]
    repeats = [o for o in outcomes if o[0] == "repeat"]
    summary = {
        "requests": len(latencies) + errors,
        "errors": errors,
        "latency_s": {"p50": round(statistics.median(latencies), 2), "max": round(max(latencies), 2)} if latencies else None,
        "first_requests_free_and_matched": sum(1 for o in firsts if o[2] and o[1] == "active"),
        "first_requests_watching": sum(1 for o in firsts if o[1] == "watching"),
        "repeat_requests_paid_quote": sum(1 for o in repeats if o[1] == "offer_pending"),
        "repeat_requests_wrongly_free": sum(1 for o in repeats if o[2]),
    }
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
