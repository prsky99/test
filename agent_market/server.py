"""판매 에이전트: AI 작업을 팔고 USDC로 대가를 받는 HTTP 서버.

흐름 (HTTP 402 Payment Required):
  1. 구매 에이전트가 GET /.well-known/agent.json 으로 서비스·가격·결제 정보를 조회
  2. 결제 없이 POST /services/{name} → 402 응답에 결제 요구사항이 담겨 옴
  3. 구매 에이전트가 판매자 지갑으로 USDC 전송 후 X-Payment-Tx / X-Payment-Signature 헤더와 함께 재요청
  4. 서버가 온체인에서 결제를 검증하고 작업 결과를 돌려줌
"""

import hmac
import logging

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse

from .chain import RPC
from .config import SellerConfig
from .ledger import Ledger
from .payments import PaymentError, PaymentVerifier
from .services import SERVICES, ClaudeWorker, ServiceError

log = logging.getLogger("agent_market.server")


def create_app(config: SellerConfig, verifier: PaymentVerifier | None = None, worker=None, ledger: Ledger | None = None) -> FastAPI:
    net = config.network
    verifier = verifier or PaymentVerifier(RPC(net.rpc_url), net.token, config.pay_to, config.min_confirmations)
    worker = worker or ClaudeWorker()
    ledger = ledger or Ledger(config.db_path)
    app = FastAPI(title="Agent Market Seller")

    def requirements(name: str) -> dict:
        svc = SERVICES[name]
        return {
            "scheme": "erc20-transfer",
            "network": net.name,
            "chain_id": net.chain_id,
            "token": net.token,
            "decimals": 6,
            "amount": svc.price,
            "pay_to": config.pay_to,
            "headers": ["X-Payment-Tx", "X-Payment-Signature"],
            "signature_message": "agent-market:{tx_hash}:{sha256(request_body)}",
        }

    @app.get("/.well-known/agent.json")
    def agent_card():
        return {
            "name": "claude-worker",
            "description": "Claude가 요약·번역·코드리뷰를 수행하고 USDC로 결제받는 에이전트",
            "services": [
                {"name": s.name, "description": s.description, "endpoint": f"/services/{s.name}", "payment": requirements(s.name)}
                for s in SERVICES.values()
            ],
        }

    @app.post("/services/{name}")
    async def run_service(
        name: str,
        request: Request,
        x_payment_tx: str | None = Header(default=None),
        x_payment_signature: str | None = Header(default=None),
    ):
        svc = SERVICES.get(name)
        if svc is None:
            raise HTTPException(404, "없는 서비스")
        body = await request.body()
        if not x_payment_tx or not x_payment_signature:
            return JSONResponse({"error": "payment required", "payment": requirements(name)}, status_code=402)

        try:
            data = await request.json()
            text = data["input"]
            if not isinstance(text, str) or not text.strip():
                raise ValueError
        except Exception:
            raise HTTPException(400, 'body는 {"input": "<텍스트>"} 형식이어야 합니다.')
        if len(text) > svc.max_input_chars:
            raise HTTPException(413, f"입력이 너무 깁니다 (최대 {svc.max_input_chars}자).")

        try:
            payment = verifier.verify(x_payment_tx, x_payment_signature, body, svc.price)
        except PaymentError as exc:
            return JSONResponse({"error": str(exc), "retryable": exc.retryable, "payment": requirements(name)}, status_code=exc.status)

        if not ledger.claim(payment.tx_hash, payment.payer, name, payment.amount):
            return JSONResponse({"error": "이미 사용된 결제입니다."}, status_code=409)
        try:
            output = worker.run(svc, text)
        except ServiceError as exc:
            ledger.release(payment.tx_hash)
            return JSONResponse({"error": str(exc), "retry_with_same_payment": True}, status_code=422)
        except Exception:
            log.exception("service %s failed", name)
            ledger.release(payment.tx_hash)
            return JSONResponse({"error": "작업 실패. 같은 결제로 재시도할 수 있습니다.", "retry_with_same_payment": True}, status_code=502)
        ledger.settle(payment.tx_hash)
        log.info("sold %s to %s for %d (tx %s)", name, payment.payer, payment.amount, payment.tx_hash)
        return {"service": name, "output": output, "receipt": {"tx_hash": payment.tx_hash, "payer": payment.payer, "amount": payment.amount}}

    @app.get("/stats")
    def stats(authorization: str | None = Header(default=None)):
        expected = f"Bearer {config.admin_token}" if config.admin_token else None
        if expected is None or authorization is None or not hmac.compare_digest(authorization, expected):
            raise HTTPException(401, "ADMIN_TOKEN 필요")
        return ledger.stats()

    return app


def main() -> None:
    import os

    import uvicorn

    logging.basicConfig(level=logging.INFO)
    config = SellerConfig.from_env()
    if not config.network.is_testnet:
        log.warning("메인넷(%s)에서 실제 USDC를 받습니다.", config.network.name)
    uvicorn.run(create_app(config), host=os.environ.get("HOST", "127.0.0.1"), port=int(os.environ.get("PORT", "8000")))


if __name__ == "__main__":
    main()
