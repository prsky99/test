"""구매 에이전트: 다른 에이전트의 서비스를 찾아 USDC로 결제하고 결과를 받는다.

안전장치: 테스트넷이 기본이며, 메인넷은 ALLOW_MAINNET=1일 때만 결제한다.
1회 결제 상한(max_per_call)과 총 예산(budget)을 넘는 결제는 거부한다.
"""

import argparse
import json
import sys
import time

import httpx
from eth_account import Account

from .chain import RPC, encode_transfer
from .config import BuyerConfig
from .payments import sign_payment


class BuyerError(RuntimeError):
    pass


class BuyerAgent:
    def __init__(self, config: BuyerConfig, rpc: RPC | None = None, http: httpx.Client | None = None):
        self.config = config
        self.account = Account.from_key(config.private_key)
        self.rpc = rpc or RPC(config.network.rpc_url)
        self.http = http or httpx.Client(timeout=300.0)
        self.spent = 0
        self.confirm_attempts = 30
        self.confirm_interval = 2.0

    def discover(self, base_url: str) -> dict:
        resp = self.http.get(f"{base_url}/.well-known/agent.json")
        resp.raise_for_status()
        return resp.json()

    def buy(self, base_url: str, service: str, text: str) -> dict:
        body = json.dumps({"input": text}).encode()
        headers = {"content-type": "application/json"}
        url = f"{base_url}/services/{service}"
        first = self.http.post(url, content=body, headers=headers)
        if first.status_code != 402:
            first.raise_for_status()
            return first.json()

        req = first.json()["payment"]
        self._check_terms(req)
        tx_hash = self._pay(req["token"], req["pay_to"], req["amount"])
        self.spent += req["amount"]

        # 결제 직후엔 아직 블록에 포함되지 않았을 수 있으므로 잠시 재시도한다.
        for _ in range(self.confirm_attempts):
            resp = self.http.post(
                url,
                content=body,
                headers={**headers, "X-Payment-Tx": tx_hash, "X-Payment-Signature": sign_payment(self.config.private_key, tx_hash, body)},
            )
            if resp.status_code == 402 and resp.json().get("retryable"):
                time.sleep(self.confirm_interval)
                continue
            if resp.status_code >= 400:
                raise BuyerError(f"{resp.status_code}: {resp.text} (결제 tx: {tx_hash})")
            return resp.json()
        raise BuyerError(f"결제 확인 대기 시간 초과 (결제 tx: {tx_hash})")

    def _check_terms(self, req: dict) -> None:
        net = self.config.network
        if req["chain_id"] != net.chain_id or req["token"].lower() != net.token.lower():
            raise BuyerError(f"판매자가 요구한 네트워크/토큰이 설정과 다릅니다: {req['network']} {req['token']}")
        if not net.is_testnet and not self.config.allow_mainnet:
            raise BuyerError("메인넷 결제는 ALLOW_MAINNET=1일 때만 허용됩니다.")
        amount = req["amount"]
        if amount <= 0:
            raise BuyerError("잘못된 결제 금액")
        if amount > self.config.max_per_call:
            raise BuyerError(f"가격 {amount}이 1회 상한 {self.config.max_per_call}을 넘습니다.")
        if self.spent + amount > self.config.budget:
            raise BuyerError(f"총 예산 {self.config.budget}을 넘습니다 (이미 {self.spent} 사용).")

    def _pay(self, token: str, pay_to: str, amount: int) -> str:
        tx = {
            "from": self.account.address,
            "to": token,
            "data": encode_transfer(pay_to, amount),
            "value": 0,
            "chainId": self.config.network.chain_id,
            "nonce": self.rpc.nonce(self.account.address),
            "gasPrice": self.rpc.gas_price(),
        }
        tx["gas"] = self.rpc.estimate_gas({"from": tx["from"], "to": token, "data": tx["data"]})
        signed = self.account.sign_transaction({k: v for k, v in tx.items() if k != "from"})
        return self.rpc.send_raw(signed.raw_transaction)


def main() -> None:
    parser = argparse.ArgumentParser(description="다른 에이전트의 서비스를 USDC로 구매")
    parser.add_argument("seller_url")
    parser.add_argument("service", nargs="?", help="생략하면 서비스 목록만 출력")
    parser.add_argument("text", nargs="?", help="입력 텍스트 (생략하면 stdin)")
    args = parser.parse_args()

    agent = BuyerAgent(BuyerConfig.from_env())
    if not args.service:
        print(json.dumps(agent.discover(args.seller_url), ensure_ascii=False, indent=2))
        return
    text = args.text if args.text is not None else sys.stdin.read()
    try:
        result = agent.buy(args.seller_url, args.service, text)
    except BuyerError as exc:
        sys.exit(f"구매 실패: {exc}")
    print(result["output"])
    print(f"\n[결제 영수증] {json.dumps(result.get('receipt'), ensure_ascii=False)}", file=sys.stderr)


if __name__ == "__main__":
    main()
