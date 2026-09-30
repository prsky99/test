"""게이트웨이 클라이언트: 에이전트가 게이트웨이에 작업을 알리고, 재소개 제안을 받아 수락/거절한다.

    python -m agent_market.gateway.client need http://gw:8200 "search the web for company contacts"
    python -m agent_market.gateway.client status http://gw:8200 <need_id>
    python -m agent_market.gateway.client accept http://gw:8200 <offer_id>     # 수수료 결제 (BUYER_PRIVATE_KEY)
"""

import argparse
import json
import sys

import httpx
from eth_account import Account

from ..buyer import BuyerAgent, BuyerError
from ..config import BuyerConfig
from ..payments import sign_request

NEED_PURPOSE = "agent-gateway-need"


class GatewayClient:
    def __init__(self, gateway_url: str, private_key: str, http: httpx.Client | None = None, buyer: BuyerAgent | None = None):
        self.url = gateway_url.rstrip("/")
        self.key = private_key
        self.address = Account.from_key(private_key).address
        self.http = http or httpx.Client(timeout=60.0)
        self.buyer = buyer  # 유료 제안 수락 시에만 필요 (예산·네트워크 검사 포함)

    def create_need(self, task: str, **options) -> dict:
        body = json.dumps({"task": task, **{k: v for k, v in options.items() if v is not None}}).encode()
        sig = sign_request(self.key, NEED_PURPOSE, self.address, body)
        resp = self.http.post(f"{self.url}/needs", content=body,
                              headers={"content-type": "application/json", "X-Client": self.address, "X-Signature": sig})
        resp.raise_for_status()
        return resp.json()

    def status(self, need_id: str) -> dict:
        resp = self.http.get(f"{self.url}/needs/{need_id}")
        resp.raise_for_status()
        return resp.json()

    def accept(self, offer: dict) -> dict:
        if self.buyer is None:
            raise BuyerError("수수료 결제에는 BuyerAgent(지갑·예산 설정)가 필요합니다.")
        req = offer["payment"]
        self.buyer._check_terms(req)
        return self.buyer._paid_post(f"{self.url}/offers/accept", {"offer_id": offer["offer_id"]}, req)

    def decline(self, offer: dict) -> None:
        self.http.post(f"{self.url}/offers/decline", json={"offer_id": offer["offer_id"], "need_id": offer["need_id"]}).raise_for_status()

    def feedback(self, need_id: str, success: bool, rating: int | None = None) -> None:
        self.http.post(f"{self.url}/needs/{need_id}/feedback", json={"success": success, "rating": rating}).raise_for_status()


def main() -> None:
    parser = argparse.ArgumentParser(description="에이전트 소개 게이트웨이 클라이언트")
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("need")
    p.add_argument("gateway")
    p.add_argument("task")
    p.add_argument("--category")
    p.add_argument("--max-price", type=int, help="USDC 최소 단위 (1 USDC = 1000000)")
    p.add_argument("--webhook")
    p = sub.add_parser("status")
    p.add_argument("gateway")
    p.add_argument("need_id")
    p = sub.add_parser("accept")
    p.add_argument("gateway")
    p.add_argument("need_id")
    args = parser.parse_args()

    config = BuyerConfig.from_env()
    client = GatewayClient(args.gateway, config.private_key, buyer=BuyerAgent(config))
    if args.cmd == "need":
        out = client.create_need(args.task, category=args.category, max_price=args.max_price, webhook=args.webhook)
    elif args.cmd == "status":
        out = client.status(args.need_id)
    else:
        offers = client.status(args.need_id)["pending_offers"]
        if not offers:
            sys.exit("대기 중인 제안이 없습니다.")
        out = client.accept(offers[0])
    print(json.dumps(out, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
