"""브로커 에이전트: 작업이 필요한 에이전트와 그 작업을 파는 에이전트를 연결하고 USDC 수수료를 받는다.

흐름:
  1. 판매 에이전트: POST /agents/register {"url": ...}  → 브로커가 agent card를 가져와 등록
  2. 구매 에이전트: POST /match {"task": ..., "category"?: ..., "max_price"?: ...}
       → 브로커가 작업을 분류하고 후보를 순위화, 402 + 견적(후보 미리보기, 수수료) 응답
  3. 구매 에이전트가 브로커 지갑으로 수수료 전송 후
     POST /match/accept {"quote_id": ...} + X-Payment-Tx / X-Payment-Signature
       → 후보의 연락처(URL, 엔드포인트, 지갑) 공개
  4. 구매 에이전트는 판매 에이전트에게 직접 서비스 대금을 지불하고 작업을 받는다 (브로커는 돈을 맡지 않음)
  5. POST /match/feedback 으로 결과를 알리면 평판에 반영되어 다음 매칭 순위가 바뀐다
"""

import hmac
import json
import logging
import threading
import time
from collections import defaultdict, deque

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse

from ..chain import RPC
from ..config import BrokerConfig
from ..ledger import Ledger
from ..payments import PaymentError, PaymentVerifier, recover_signer
from .categories import CATEGORIES, match_fee
from .classifier import ClassificationError, ClaudeClassifier
from .discovery import CardFetcher, DiscoveryError
from .registry import Registry

log = logging.getLogger("agent_market.broker")

FEEDBACK_PURPOSE = "agent-broker-feedback"
MAX_TASK_CHARS = 4000
MAX_TOP_K = 5
CLASSIFY_PER_MINUTE = 20  # 무료인 /match 분류(Claude 호출 비용)를 남용하지 못하게 IP당 제한


class RateLimiter:
    def __init__(self, per_minute: int):
        self.per_minute = per_minute
        self._hits: dict[str, deque] = defaultdict(deque)
        self._lock = threading.Lock()

    def allow(self, key: str) -> bool:
        now = time.monotonic()
        with self._lock:
            hits = self._hits[key]
            while hits and now - hits[0] > 60:
                hits.popleft()
            if len(hits) >= self.per_minute:
                return False
            hits.append(now)
            return True


async def json_body(request: Request) -> tuple[bytes, dict]:
    body = await request.body()
    try:
        data = json.loads(body)
        if not isinstance(data, dict):
            raise ValueError
    except ValueError:
        raise HTTPException(400, "JSON 객체 body가 필요합니다.")
    return body, data


def create_app(
    config: BrokerConfig,
    verifier: PaymentVerifier | None = None,
    classifier=None,
    fetcher: CardFetcher | None = None,
    registry: Registry | None = None,
    ledger: Ledger | None = None,
) -> FastAPI:
    net = config.network
    verifier = verifier or PaymentVerifier(RPC(net.rpc_url), net.token, config.pay_to, config.min_confirmations)
    classifier = classifier or ClaudeClassifier()
    fetcher = fetcher or CardFetcher(allow_private=config.allow_private_urls, network={"chain_id": net.chain_id, "token": net.token})
    registry = registry or Registry(config.db_path)
    ledger = ledger or Ledger(config.db_path)
    classify_limit = RateLimiter(CLASSIFY_PER_MINUTE)
    app = FastAPI(title="Agent Broker")

    def fee_requirements(amount: int) -> dict:
        return {
            "scheme": "erc20-transfer",
            "network": net.name,
            "chain_id": net.chain_id,
            "token": net.token,
            "decimals": 6,
            "amount": amount,
            "pay_to": config.pay_to,
            "headers": ["X-Payment-Tx", "X-Payment-Signature"],
            "signature_message": "agent-market:{tx_hash}:{sha256(request_body)}",
        }

    @app.get("/.well-known/agent.json")
    def agent_card():
        return {
            "name": "agent-broker",
            "role": "broker",
            "description": "작업이 필요한 AI 에이전트와 그 작업을 파는 AI 에이전트를 연결합니다. 매칭 수수료는 USDC로 받습니다.",
            "categories": [{"id": c.id, "name": c.name, "description": c.description} for c in CATEGORIES.values()],
            "fee_policy": {"fee_bps": config.fee_bps, "min_fee": config.min_fee, "basis": "추천된 최상위 서비스 가격"},
            "endpoints": {"register": "/agents/register", "match": "/match", "accept": "/match/accept", "feedback": "/match/feedback"},
            "network": {"name": net.name, "chain_id": net.chain_id, "token": net.token},
        }

    @app.get("/categories")
    def categories():
        return [c.__dict__ for c in CATEGORIES.values()]

    @app.post("/agents/register")
    async def register(request: Request):
        _, data = await json_body(request)
        url = data.get("url")
        if not isinstance(url, str):
            raise HTTPException(400, '{"url": "<판매 에이전트 base URL>"} 형식이어야 합니다.')
        try:
            card = fetcher.fetch(url)
        except DiscoveryError as exc:
            raise HTTPException(422, str(exc))
        agent_id = registry.upsert_agent(url.rstrip("/"), card["name"], card["pay_to"], card["services"])
        log.info("registered %s (%s) with %d services", card["name"], agent_id, len(card["services"]))
        return {"agent_id": agent_id, "services": [{"name": s["name"], "category": s["category"], "price": s["price"]} for s in card["services"]]}

    @app.post("/match")
    async def match(request: Request):
        _, data = await json_body(request)
        task = data.get("task")
        if not isinstance(task, str) or not task.strip():
            raise HTTPException(400, '"task"(필요한 작업 설명)가 필요합니다.')
        if len(task) > MAX_TASK_CHARS:
            raise HTTPException(413, f"task는 {MAX_TASK_CHARS}자 이하로 적어 주세요.")
        max_price = data.get("max_price")
        if max_price is not None and (not isinstance(max_price, int) or max_price <= 0):
            raise HTTPException(400, "max_price는 USDC 최소 단위의 양의 정수입니다.")
        top_k = data.get("top_k", 3)
        if not isinstance(top_k, int) or not 1 <= top_k <= MAX_TOP_K:
            raise HTTPException(400, f"top_k는 1~{MAX_TOP_K} 사이여야 합니다.")

        category = data.get("category")
        summary = task.strip()[:200]
        if category is None:
            if not classify_limit.allow(request.client.host if request.client else "unknown"):
                raise HTTPException(429, "자동 분류 요청이 너무 많습니다. category를 직접 지정하거나 잠시 후 재시도하세요.")
            try:
                category, summary = classifier.classify(task)
            except ClassificationError as exc:
                raise HTTPException(422, str(exc))
            except Exception:
                log.exception("classification failed")
                raise HTTPException(502, "작업 분류에 실패했습니다. category를 직접 지정해 주세요.")
            if category is None:
                raise HTTPException(404, "이 작업에 맞는 카테고리가 없습니다.")
        elif category not in CATEGORIES:
            raise HTTPException(400, f"알 수 없는 category. 가능한 값: {', '.join(CATEGORIES)}")

        candidates = registry.find(category, max_price, top_k)
        if not candidates:
            # 후보가 없으면 수수료를 받지 않는다.
            return JSONResponse({"error": "조건에 맞는 에이전트가 없습니다.", "category": category}, status_code=404)
        fee = match_fee(candidates[0].price, config.fee_bps, config.min_fee)
        quote_id = registry.create_quote(category, summary, candidates, fee)
        return JSONResponse(
            {
                "quote_id": quote_id,
                "category": category,
                "task_summary": summary,
                "candidates": [c.preview() for c in candidates],
                "fee": fee,
                "payment": fee_requirements(fee),
                "accept": {"endpoint": "/match/accept", "body": {"quote_id": quote_id}},
            },
            status_code=402,
        )

    @app.post("/match/accept")
    async def accept(
        request: Request,
        x_payment_tx: str | None = Header(default=None),
        x_payment_signature: str | None = Header(default=None),
    ):
        body, data = await json_body(request)
        quote = registry.get_quote(str(data.get("quote_id", "")))
        if quote is None:
            raise HTTPException(404, "없는 견적입니다.")
        if not x_payment_tx or not x_payment_signature:
            return JSONResponse({"error": "payment required", "payment": fee_requirements(quote["fee"])}, status_code=402)
        try:
            payment = verifier.verify(x_payment_tx, x_payment_signature, body, quote["fee"])
        except PaymentError as exc:
            return JSONResponse(
                {"error": str(exc), "retryable": exc.retryable, "payment": fee_requirements(quote["fee"])}, status_code=exc.status
            )

        result = {"match_id": quote["quote_id"], "category": quote["category"], "candidates": quote["candidates"]}
        if quote["tx_hash"] == payment.tx_hash:  # 응답을 못 받은 결제자의 재요청: 같은 결과를 다시 준다
            return result
        if quote["payer"] is not None:
            return JSONResponse({"error": "이미 결제된 견적입니다."}, status_code=409)
        if not ledger.claim(payment.tx_hash, payment.payer, f"match:{quote['category']}", payment.amount):
            return JSONResponse({"error": "이미 사용된 결제입니다."}, status_code=409)
        if not registry.mark_paid(quote["quote_id"], payment.payer, payment.tx_hash):
            ledger.release(payment.tx_hash)  # 동시에 다른 결제가 먼저 들어온 경우, 이 결제는 다른 견적에 쓸 수 있게 풀어 준다
            return JSONResponse({"error": "이미 결제된 견적입니다."}, status_code=409)
        ledger.settle(payment.tx_hash)
        log.info("match %s paid by %s: fee %d", quote["quote_id"], payment.payer, payment.amount)
        return result

    @app.post("/match/feedback")
    async def feedback(request: Request, x_signature: str | None = Header(default=None)):
        body, data = await json_body(request)
        quote = registry.get_quote(str(data.get("match_id", "")))
        if quote is None or quote["payer"] is None:
            raise HTTPException(404, "결제된 매칭이 아닙니다.")
        if not x_signature:
            raise HTTPException(401, "매칭 결제 지갑의 X-Signature가 필요합니다.")
        try:
            signer = recover_signer(FEEDBACK_PURPOSE, quote["quote_id"], body, x_signature)
        except ValueError as exc:
            raise HTTPException(400, str(exc))
        if signer != quote["payer"]:
            raise HTTPException(403, "매칭 수수료를 낸 지갑만 평가할 수 있습니다.")

        agent_id, service, success, rating = data.get("agent_id"), data.get("service"), data.get("success"), data.get("rating")
        if not any(c["agent_id"] == agent_id and c["service"] == service for c in quote["candidates"]):
            raise HTTPException(400, "이 매칭에서 추천된 에이전트/서비스가 아닙니다.")
        if not isinstance(success, bool):
            raise HTTPException(400, "success(bool)가 필요합니다.")
        if rating is not None and (not isinstance(rating, int) or isinstance(rating, bool) or not 1 <= rating <= 5):
            raise HTTPException(400, "rating은 1~5 정수이거나 생략합니다.")
        if not registry.add_feedback(quote["quote_id"], agent_id, service, success, rating):
            raise HTTPException(409, "이미 평가했습니다.")
        return {"ok": True}

    @app.get("/stats")
    def stats(authorization: str | None = Header(default=None)):
        expected = f"Bearer {config.admin_token}" if config.admin_token else None
        if expected is None or authorization is None or not hmac.compare_digest(authorization, expected):
            raise HTTPException(401, "ADMIN_TOKEN 필요")
        return registry.stats()

    return app


def main() -> None:
    import os

    import uvicorn

    logging.basicConfig(level=logging.INFO)
    config = BrokerConfig.from_env()
    if not config.network.is_testnet:
        log.warning("메인넷(%s)에서 실제 USDC 수수료를 받습니다.", config.network.name)
    uvicorn.run(create_app(config), host=os.environ.get("HOST", "127.0.0.1"), port=int(os.environ.get("PORT", "8100")))


if __name__ == "__main__":
    main()
