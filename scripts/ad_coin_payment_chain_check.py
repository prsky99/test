"""Check the USDC payment verifier against real chain data, read only (PM 11-14: payment flow on Base Sepolia).

  .venv/bin/python -m scripts.ad_coin_payment_chain_check [--out reports/ad-realign-2026-11-14/payment-chain-check.json]

We hold no wallet and send nothing. The script reads a recent real USDC transfer on Base Sepolia (testnet, no real
money) from the public RPC and runs paid_bookings.verify_transfer on its receipt, the code that confirms a paid
booking. Expected: exact amount to the right address confirms; one unit less or more is amount_mismatch; another
recipient or another token is payment_not_found. The same code reads Base mainnet with the mainnet USDC contract.
"""
import argparse
import json
import sys
import time

SEPOLIA_RPC = "https://sepolia.base.org"
SEPOLIA_CHAIN_ID = 84532
SEPOLIA_USDC = "0x036cbd53842c5426634e7929541ec2318f3dcf7e"     # Circle USDC on Base Sepolia


def find_transfer(rpc, token, *, span=20, tries=20):
    """A recent successful USDC Transfer log: (tx_hash, to, amount)."""
    from agent_market.chain import TRANSFER_TOPIC
    head = rpc.block_number()
    for i in range(tries):
        end = head - i * span
        logs = rpc.call("eth_getLogs", {"address": token, "topics": [TRANSFER_TOPIC],
                                        "fromBlock": hex(end - span), "toBlock": hex(end)})
        for log in reversed(logs or []):
            if len(log.get("topics", [])) == 3 and int(log.get("data", "0x0"), 16) > 0:
                return log["transactionHash"], "0x" + log["topics"][2][-40:], int(log["data"], 16)
    raise RuntimeError("no USDC transfer found in the recent blocks")


def run(rpc=None):
    from agent_market.ad_coin.v2.paid_bookings import verify_transfer
    from agent_market.chain import RPC
    rpc = rpc or RPC(SEPOLIA_RPC)
    chain = int(rpc.chain_id())
    tx, to, amount = find_transfer(rpc, SEPOLIA_USDC)
    other = "0x" + "1" * 40

    def check(name, expected, **kw):
        args = dict(token=SEPOLIA_USDC, pay_to=to, amount_units=amount, min_confirmations=1)
        args.update(kw)
        got, _payer = verify_transfer(rpc, tx, **args)
        return {"case": name, "expected": expected, "got": got, "passed": got == expected}
    cases = [check("exact amount to the receiving address", "confirmed"),
             check("one unit less", "amount_mismatch", amount_units=amount + 1),
             check("one unit more", "amount_mismatch", amount_units=amount - 1),
             check("another receiving address", "payment_not_found", pay_to=other),
             check("another token contract", "payment_not_found", token=other)]
    return {"generated_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "network": "Base Sepolia",
            "chain_id": chain, "chain_ok": chain == SEPOLIA_CHAIN_ID, "usdc": SEPOLIA_USDC, "tx_hash": tx,
            "amount_units": str(amount), "cases": cases,
            "all_passed": chain == SEPOLIA_CHAIN_ID and all(c["passed"] for c in cases)}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out")
    args = parser.parse_args(argv)
    result = run()
    text = json.dumps(result, indent=1)
    if args.out:
        with open(args.out, "w") as handle:
            handle.write(text)
    print(json.dumps({"all_passed": result["all_passed"], "tx_hash": result["tx_hash"],
                      "cases": [(c["case"], c["got"]) for c in result["cases"]]}))
    return 0 if result["all_passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
