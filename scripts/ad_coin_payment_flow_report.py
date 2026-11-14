"""Write the payment flow result in the operations format (PM 11-14): logs/ops/payment-flow-tests/<UTC date>.json

  .venv/bin/python -m scripts.ad_coin_payment_flow_report

Runs tests/test_ad_coin_v2_payment_flow.py (the whole booking flow and every failure case, receipts simulated in a
throwaway database) and scripts.ad_coin_payment_chain_check (a real USDC receipt read on Base Sepolia, no wallet,
no transfer), then writes
  {"at", "network": "base-sepolia", "passed", "total", "includes_failure_cases", "failed": [...], ...}
It counts as passing only with total > 0, passed == total and all six failure cases present. Exit 1 otherwise.
"""
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "logs/ops/payment-flow-tests"
# the six failure cases the operations judgement requires (case-name fragments in the flow test results)
REQUIRED = {"underpaid": "underpaid", "overpaid": "overpaid", "other_token": "another token",
            "late_payment": "after the quote expired", "duplicate": "one transaction pays one booking",
            "sanctioned": "sanctions list"}


def flow_cases(python=None):
    target = tempfile.NamedTemporaryFile(suffix=".json", delete=False).name
    env = {**os.environ, "PAYMENT_FLOW_REPORT": target}
    run = subprocess.run([python or str(ROOT / ".venv-tests/bin/python"), "-m", "pytest", "-q", "-p", "no:cacheprovider",
                          "tests/test_ad_coin_v2_payment_flow.py"], cwd=ROOT, env=env, capture_output=True, text=True)
    try:
        cases = json.loads(Path(target).read_text())["cases"]
    except (OSError, ValueError, KeyError):
        cases = [{"case": "payment flow tests did not run", "passed": False, "got": run.stdout[-300:]}]
    finally:
        try:
            os.unlink(target)
        except OSError:
            pass
    return cases, run.returncode


def summarize(flow, chain, *, now=None):
    cases = [("flow: " + c["case"], c["passed"], c.get("got")) for c in flow]
    cases += [("base-sepolia: " + c["case"], c["passed"], c.get("got")) for c in chain.get("cases", [])]
    if not chain.get("chain_ok", False):
        cases.append(("base-sepolia: chain id", False, chain.get("chain_id")))
    names = " | ".join(c["case"] for c in flow)
    missing = [k for k, fragment in REQUIRED.items() if fragment not in names]
    failed = [{"name": name, "cause": str(got)[:200]} for name, ok, got in cases if not ok]
    failed += [{"name": "missing failure case: " + k, "cause": "not in the flow tests"} for k in missing]
    return {"at": time.strftime("%Y-%m-%d %H:%M", time.localtime(now)), "network": "base-sepolia",
            "passed": sum(1 for _, ok, _ in cases if ok), "total": len(cases),
            "includes_failure_cases": not missing, "failed": failed,
            "flow_receipts": "simulated (throwaway database)", "chain_tx": chain.get("tx_hash")}


def main(argv=None):
    from scripts.ad_coin_payment_chain_check import run as chain_run
    flow, _code = flow_cases()
    try:
        chain = chain_run()
    except Exception as error:  # noqa: BLE001 - recorded as a failure, never hidden
        chain = {"cases": [{"case": "read a real receipt", "passed": False, "got": type(error).__name__}], "chain_ok": False}
    result = summarize(flow, chain)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / (time.strftime("%Y-%m-%d") + ".json")).write_text(json.dumps(result, indent=1))
    ok = result["total"] > 0 and result["passed"] == result["total"] and result["includes_failure_cases"]
    print(json.dumps({"ok": ok, "passed": result["passed"], "total": result["total"],
                      "includes_failure_cases": result["includes_failure_cases"], "failed": result["failed"][:3]}))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
