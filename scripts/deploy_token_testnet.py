"""Plan an AIADCoin.sol deployment without sending anything to a network.

This tool only prints a simulation plan. Any real deployment, testnet or mainnet,
needs the operator's explicit approval, an external audit for mainnet, and a
reviewed toolchain; this script refuses to do it.
"""

import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONTRACTS_DIR = ROOT / "agent_market/ad_coin/v2/contracts"
SOL_PATH = CONTRACTS_DIR / "AIADCoin.sol"
SPEC_PATH = CONTRACTS_DIR / "aiac_token_spec.json"

TESTNETS = {
    "base_sepolia": {"chain_id": 84532, "explorer": "https://sepolia.basescan.org"},
    "ethereum_sepolia": {"chain_id": 11155111, "explorer": "https://sepolia.etherscan.io"},
}


class DeploymentRefused(RuntimeError):
    pass


def _address(value, label):
    text = str(value).strip()
    if len(text) != 42 or not text.startswith("0x") or int(text[2:], 16) == 0:
        raise ValueError(f"{label} must be a non-zero 20-byte hex address")
    return text


def plan(network_name, owner_multisig, bridge_minter, reserve_feed):
    """A simulation plan. Nothing is signed or sent, and no record of a deployment is written."""
    if network_name not in TESTNETS:
        raise ValueError(f"Unknown network: {network_name}")
    source = SOL_PATH.read_text(encoding="utf-8")
    spec = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
    return {
        "status": "simulation_only_not_deployed",
        "network": network_name,
        "chain_id": TESTNETS[network_name]["chain_id"],
        "contract_name": "AIADCoin",
        "constructor": {
            "initialOwner": _address(owner_multisig, "owner multisig"),
            "initialMinter": _address(bridge_minter, "bridge minter"),
            "initialFeed": _address(reserve_feed, "reserve feed"),
        },
        "source_sha256": hashlib.sha256(source.encode("utf-8")).hexdigest(),
        "token_metadata": spec.get("token", {}),
        "required_before_any_real_deployment": [
            "operator approval for the target network",
            "compiled and tested with a reviewed Solidity toolchain",
            "owner is a deployed multisig contract",
            "external audit before mainnet",
            "legal opinion before any real-value use",
        ],
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description="Print a simulation plan for AIADCoin (never deploys).")
    parser.add_argument("--network", default="base_sepolia", choices=sorted(TESTNETS))
    parser.add_argument("--owner-multisig", required=True)
    parser.add_argument("--bridge-minter", required=True)
    parser.add_argument("--reserve-feed", required=True)
    parser.add_argument("--execute", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args.execute:
        raise DeploymentRefused("Real deployment is not available from this tool; it needs operator approval.")
    print(json.dumps(plan(args.network, args.owner_multisig, args.bridge_minter, args.reserve_feed), indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
