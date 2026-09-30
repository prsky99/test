"""지갑 도구: 새 지갑 생성(암호화된 keystore), 잔액 조회.

    python -m agent_market.wallet create wallets/gateway.json   # 비밀번호를 물어봄 (또는 WALLET_PASSWORD)
    python -m agent_market.wallet address wallets/gateway.json
    python -m agent_market.wallet balance 0x...                  # NETWORK 환경변수의 ETH/USDC 잔액

개인키는 평문으로 저장하지 않고 비밀번호로 암호화한 keystore(JSON)로만 저장한다.
실제 돈이 오가는 메인넷 지갑은 반드시 본인 PC에서 만들고, keystore와 비밀번호를 따로 백업할 것.
"""

import argparse
import getpass
import json
import os
import sys
from pathlib import Path

from eth_account import Account

from .chain import RPC
from .config import USDC_DECIMALS, NetworkConfig

BALANCE_OF = "0x70a08231"


def create(path: Path, password: str) -> str:
    if path.exists():
        raise FileExistsError(f"{path} 이미 존재합니다. 덮어쓰지 않습니다.")
    account = Account.create()
    keystore = Account.encrypt(account.key, password)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(keystore, f)
    return account.address


def address_of(path: Path) -> str:
    return "0x" + json.loads(path.read_text())["address"].removeprefix("0x")


def load_key(path: Path, password: str) -> str:
    return "0x" + Account.decrypt(json.loads(path.read_text()), password).hex().removeprefix("0x")


def balances(address: str, net: NetworkConfig, rpc: RPC | None = None) -> dict:
    rpc = rpc or RPC(net.rpc_url)
    eth = int(rpc.call("eth_getBalance", address, "latest"), 16)
    data = BALANCE_OF + address.lower().removeprefix("0x").rjust(64, "0")
    usdc = int(rpc.call("eth_call", {"to": net.token, "data": data}, "latest"), 16)
    return {"network": net.name, "address": address, "eth": eth / 1e18, "usdc": usdc / 10**USDC_DECIMALS}


def _password(confirm: bool) -> str:
    if pw := os.environ.get("WALLET_PASSWORD"):
        return pw
    pw = getpass.getpass("지갑 비밀번호: ")
    if confirm and pw != getpass.getpass("비밀번호 확인: "):
        sys.exit("비밀번호가 일치하지 않습니다.")
    if len(pw) < 12:
        sys.exit("비밀번호는 12자 이상이어야 합니다.")
    return pw


def main() -> None:
    parser = argparse.ArgumentParser(description="지갑 생성·조회")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("create").add_argument("path", type=Path)
    sub.add_parser("address").add_argument("path", type=Path)
    sub.add_parser("balance").add_argument("address")
    args = parser.parse_args()

    if args.cmd == "create":
        address = create(args.path, _password(confirm=True))
        print(address)
        print(f"keystore: {args.path} (권한 600). 비밀번호를 잃으면 복구할 수 없습니다. 백업하세요.", file=sys.stderr)
    elif args.cmd == "address":
        print(address_of(args.path))
    else:
        print(json.dumps(balances(args.address, NetworkConfig.from_env()), indent=2))


if __name__ == "__main__":
    main()
