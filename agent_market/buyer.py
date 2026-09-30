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
from .payments import sign_payment, sign_request


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
        return self.buy_at(f"{base_url}/services/{service}", text)

    def buy_at(self, url: str, text: str, expected_pay_to: str | None = None) -> dict:
        first = self.http.post(url, json={"input": text})
        if first.status_code != 402:
            if first.status_code >= 400:
                raise BuyerError(f"{first.status_code}: {first.text}")
            return first.json()

        req = first.json()["payment"]
        if expected_pay_to and req["pay_to"].lower() != expected_pay_to.lower():
            raise BuyerError("판매자가 브로커에 등록된 것과 다른 지갑으로 결제를 요구합니다.")
        self._check_terms(req)
        return self._paid_post(url, {"input": text}, req)

    def hire(self, broker_url: str, task: str, text: str, category: str | None = None, max_price: int | None = None, judge=None) -> dict:
        """브로커로 적합한 에이전트를 찾아(수수료 결제) 작업을 맡긴다.

        task: 브로커에게 알리는 작업 설명 (분류·매칭용), text: 판매 에이전트에게 보낼 실제 입력.
        judge: 결과를 받아 1~5 별점을 돌려주는 함수(선택). 없으면 성공/실패만 평가한다.
        실패한 후보는 평판에 반영하고 다음 후보로 넘어간다.
        """
        request = {"task": task, "top_k": 3}
        if category:
            request["category"] = category
        if max_price is not None:
            request["max_price"] = max_price
        quote_resp = self.http.post(f"{broker_url}/match", json=request)
        if quote_resp.status_code != 402:
            raise BuyerError(f"매칭 실패 {quote_resp.status_code}: {quote_resp.text}")
        quote = quote_resp.json()
        cheapest = min(c["price"] for c in quote["candidates"])
        # 수수료와 최소 한 번의 서비스 대금을 모두 낼 수 있을 때만 진행한다.
        self._check_terms(quote["payment"], extra=cheapest)
        match = self._paid_post(broker_url + quote["accept"]["endpoint"], quote["accept"]["body"], quote["payment"])

        errors = []
        for candidate in match["candidates"]:
            try:
                result = self.buy_at(candidate["endpoint"], text, expected_pay_to=candidate["pay_to"])
            except (BuyerError, httpx.HTTPError) as exc:
                errors.append(f"{candidate['agent_name']}: {exc}")
                self._feedback(broker_url, match["match_id"], candidate, success=False, rating=None)
                continue
            rating = judge(result["output"]) if judge else None
            self._feedback(broker_url, match["match_id"], candidate, success=True, rating=rating)
            return {**result, "match_id": match["match_id"], "agent": candidate}
        raise BuyerError("모든 후보가 실패했습니다: " + "; ".join(errors))

    def _paid_post(self, url: str, body_obj: dict, req: dict) -> dict:
        tx_hash = self._pay(req["token"], req["pay_to"], req["amount"])
        self.spent += req["amount"]
        body = json.dumps(body_obj).encode()
        for _ in range(self.confirm_attempts):
            resp = self.http.post(
                url,
                content=body,
                headers={"content-type": "application/json", "X-Payment-Tx": tx_hash, "X-Payment-Signature": sign_payment(self.config.private_key, tx_hash, body)},
            )
            if resp.status_code == 402 and resp.json().get("retryable"):
                time.sleep(self.confirm_interval)
                continue
            if resp.status_code >= 400:
                raise BuyerError(f"{resp.status_code}: {resp.text} (결제 tx: {tx_hash})")
            return resp.json()
        raise BuyerError(f"결제 확인 대기 시간 초과 (결제 tx: {tx_hash})")

    def _feedback(self, broker_url: str, match_id: str, candidate: dict, success: bool, rating: int | None) -> None:
        body = json.dumps({"match_id": match_id, "agent_id": candidate["agent_id"], "service": candidate["service"], "success": success, "rating": rating}).encode()
        sig = sign_request(self.config.private_key, "agent-broker-feedback", match_id, body)
        resp = self.http.post(f"{broker_url}/match/feedback", content=body, headers={"content-type": "application/json", "X-Signature": sig})
        if resp.status_code >= 400:
            print(f"[경고] 평가 전송 실패 {resp.status_code}: {resp.text}", file=sys.stderr)

    def _check_terms(self, req: dict, extra: int = 0) -> None:
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
        if self.spent + amount + extra > self.config.budget:
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
