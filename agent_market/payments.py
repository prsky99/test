"""온체인 USDC 결제 검증.

구매 에이전트는 판매자 지갑으로 USDC를 전송한 뒤, 요청 헤더에 두 값을 넣는다.
  X-Payment-Tx:        결제 트랜잭션 해시
  X-Payment-Signature: payment_message(tx_hash, body)에 대한 송금 지갑의 서명(EIP-191)
서명은 "이 결제를 한 지갑이 이 요청을 보냈다"는 증명이다. 체인에 공개된 남의 tx 해시를
가로채 서비스를 받아가는 것을 막는다.
"""

import hashlib
from dataclasses import dataclass

from eth_account import Account
from eth_account.messages import encode_defunct

from .chain import RPC, normalize, transfers_in


class PaymentError(Exception):
    def __init__(self, message: str, status: int = 402, retryable: bool = False):
        super().__init__(message)
        self.status = status
        self.retryable = retryable  # 블록 포함/컨펌 대기 등 시간이 지나면 해결되는 경우


def request_message(purpose: str, subject: str, body: bytes) -> str:
    """서명 대상 문자열. purpose로 용도(결제/피드백)를 구분해 서명이 다른 곳에 재사용되지 않게 한다."""
    return f"{purpose}:{subject.lower()}:{hashlib.sha256(body).hexdigest()}"


def sign_request(private_key: str, purpose: str, subject: str, body: bytes) -> str:
    signed = Account.sign_message(encode_defunct(text=request_message(purpose, subject, body)), private_key=private_key)
    return "0x" + signed.signature.hex().removeprefix("0x")


def recover_signer(purpose: str, subject: str, body: bytes, signature: str) -> str:
    """서명한 지갑 주소(소문자)를 돌려준다. 서명 형식이 잘못되면 ValueError."""
    try:
        return normalize(Account.recover_message(encode_defunct(text=request_message(purpose, subject, body)), signature=signature))
    except Exception as exc:
        raise ValueError(f"서명을 해석할 수 없습니다: {exc}") from exc


def payment_message(tx_hash: str, body: bytes) -> str:
    return request_message("agent-market", tx_hash, body)


def sign_payment(private_key: str, tx_hash: str, body: bytes) -> str:
    return sign_request(private_key, "agent-market", tx_hash, body)


@dataclass
class VerifiedPayment:
    tx_hash: str
    payer: str
    amount: int


class PaymentVerifier:
    def __init__(self, rpc: RPC, token: str, pay_to: str, min_confirmations: int = 1):
        self.rpc = rpc
        self.token = token
        self.pay_to = normalize(pay_to)
        self.min_confirmations = min_confirmations

    def verify(self, tx_hash: str, signature: str, body: bytes, price: int) -> VerifiedPayment:
        if not tx_hash.startswith("0x") or len(tx_hash) != 66:
            raise PaymentError("잘못된 트랜잭션 해시 형식", 400)
        receipt = self.rpc.receipt(tx_hash)
        if receipt is None:
            raise PaymentError("트랜잭션이 아직 블록에 포함되지 않았습니다. 잠시 후 재시도하세요.", retryable=True)
        if int(receipt.get("status", "0x0"), 16) != 1:
            raise PaymentError("실패한 트랜잭션입니다.")
        confirmations = self.rpc.block_number() - int(receipt["blockNumber"], 16) + 1
        if confirmations < self.min_confirmations:
            raise PaymentError(f"컨펌 부족 ({confirmations}/{self.min_confirmations}). 잠시 후 재시도하세요.", retryable=True)

        paid = [(frm, amt) for frm, to, amt in transfers_in(receipt, self.token) if to == self.pay_to]
        if not paid:
            raise PaymentError("판매자 지갑으로의 USDC 전송이 없습니다.")
        payers = {frm for frm, _ in paid}
        if len(payers) != 1:
            raise PaymentError("한 트랜잭션에 여러 송금자가 있어 결제자를 특정할 수 없습니다.", 400)
        payer = payers.pop()
        amount = sum(amt for _, amt in paid)
        if amount < price:
            raise PaymentError(f"결제 금액 부족 ({amount} < {price})")

        try:
            signer = recover_signer("agent-market", tx_hash, body, signature)
        except ValueError as exc:
            raise PaymentError(f"결제 {exc}", 400) from exc
        if signer != payer:
            raise PaymentError("결제 서명자가 송금자와 다릅니다.", 403)
        return VerifiedPayment(tx_hash.lower(), payer, amount)
