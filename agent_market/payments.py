"""온체인 USDC 결제 검증.

구매 에이전트는 판매자 지갑으로 USDC를 전송한 뒤, 요청 헤더에 두 값을 넣는다.
  X-Payment-Tx:        결제 트랜잭션 해시
  X-Payment-Signature: payment_message(tx_hash, body)에 대한 송금 지갑의 서명(EIP-191)
서명은 "이 결제를 한 지갑이 이 요청을 보냈다"는 증명이다. 체인에 공개된 남의 tx 해시를
가로채 서비스를 받아가는 것을 막는다.
"""

import hashlib
import re
from dataclasses import dataclass

try:
    from eth_account import Account
    from eth_account.messages import encode_defunct, encode_typed_data
except ImportError:
    Account = None
    encode_defunct = None
    encode_typed_data = None

from .chain import RPC, normalize, transfers_in


class PaymentError(Exception):
    def __init__(self, message: str, status: int = 402, retryable: bool = False, *,
                 error_code: str = "PAYMENT_VERIFICATION_FAILED", stage: str = "verification"):
        super().__init__(message)
        self.status = status
        self.error_code = error_code
        self.stage = stage
        self.retryable = retryable  # 블록 포함/컨펌 대기 등 시간이 지나면 해결되는 경우


def request_message(purpose: str, subject: str, body: bytes) -> str:
    """서명 대상 문자열. purpose로 용도(결제/피드백)를 구분해 서명이 다른 곳에 재사용되지 않게 한다."""
    return f"{purpose}:{subject.lower()}:{hashlib.sha256(body).hexdigest()}"


def payment_eip712_data(chain_id: int, verifying_contract: str, tx_hash: str, body: bytes, purpose: str = "agent-market") -> dict:
    return {
        "types": {
            "EIP712Domain": [
                {"name": "name", "type": "string"},
                {"name": "version", "type": "string"},
                {"name": "chainId", "type": "uint256"},
                {"name": "verifyingContract", "type": "address"},
            ],
            "PaymentProof": [
                {"name": "purpose", "type": "string"},
                {"name": "txHash", "type": "string"},
                {"name": "bodyHash", "type": "string"},
            ],
        },
        "primaryType": "PaymentProof",
        "domain": {
            "name": "AgentMarket",
            "version": "1",
            "chainId": chain_id,
            "verifyingContract": verifying_contract,
        },
        "message": {
            "purpose": purpose,
            "txHash": tx_hash.lower(),
            "bodyHash": hashlib.sha256(body).hexdigest(),
        },
    }


def sign_payment_eip712(private_key: str, chain_id: int, verifying_contract: str, tx_hash: str, body: bytes) -> str:
    data = payment_eip712_data(chain_id, verifying_contract, tx_hash, body)
    signed = Account.sign_message(encode_typed_data(full_message=data), private_key=private_key)
    return "0x" + signed.signature.hex().removeprefix("0x")


def sign_request(private_key: str, purpose: str, subject: str, body: bytes) -> str:
    signed = Account.sign_message(encode_defunct(text=request_message(purpose, subject, body)), private_key=private_key)
    return "0x" + signed.signature.hex().removeprefix("0x")


def recover_signer(
    purpose: str,
    subject: str,
    body: bytes,
    signature: str,
    chain_id: int | None = None,
    token: str | None = None,
    expected_signer: str | None = None,
) -> str:
    """서명한 지갑 주소(소문자)를 돌려준다. EIP-191 및 EIP-712 모두 지원."""
    if expected_signer:
        target = normalize(expected_signer)
        if chain_id and token:
            try:
                data = payment_eip712_data(chain_id, token, subject, body, purpose=purpose)
                recovered = normalize(Account.recover_message(encode_typed_data(full_message=data), signature=signature))
                if recovered == target:
                    return recovered
            except Exception:
                pass
        try:
            recovered = normalize(Account.recover_message(encode_defunct(text=request_message(purpose, subject, body)), signature=signature))
            if recovered == target:
                return recovered
        except Exception:
            pass

    if chain_id and token:
        try:
            data = payment_eip712_data(chain_id, token, subject, body, purpose=purpose)
            return normalize(Account.recover_message(encode_typed_data(full_message=data), signature=signature))
        except Exception:
            pass
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
        if type(tx_hash) is not str or not re.fullmatch(r"0x[0-9a-fA-F]{64}",tx_hash):
            raise PaymentError("Invalid transaction hash.",400,error_code="INVALID_PAYMENT_TX",stage="format")
        if type(signature) is not str or not re.fullmatch(r"0x[0-9a-fA-F]{130}",signature):
            raise PaymentError("Invalid proof signature.",400,error_code="INVALID_PAYMENT_SIGNATURE",stage="format")
        signed = bytes.fromhex(signature[2:])
        order = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEBAAEDCE6AF48A03BBFD25E8CD0364141
        if (not 0 < int.from_bytes(signed[:32], 'big') < order
                or not 0 < int.from_bytes(signed[32:64], 'big') <= order // 2
                or signed[64] not in (0, 1, 27, 28)):
            raise PaymentError("Invalid proof signature.",400,error_code="INVALID_PAYMENT_SIGNATURE",stage="format")
        if type(body) is not bytes or len(body)>1024*1024 or type(price) is not int or not 0<=price<2**256:
            raise PaymentError("Invalid payment context.",400,error_code="INVALID_PAYMENT_CONTEXT",stage="context")
        try:
            receipt = self.rpc.receipt(tx_hash)
        except Exception:
            raise PaymentError("Payment verification is temporarily unavailable.",503,True,
                error_code="PAYMENT_VERIFICATION_UNAVAILABLE",stage="verification") from None
        if receipt is None:
            raise PaymentError("트랜잭션이 아직 블록에 포함되지 않았습니다. 잠시 후 재시도하세요.", retryable=True,error_code="PAYMENT_CONFIRMATION_PENDING",stage="confirmation")
        try:
            if type(receipt) is not dict or type(receipt.get('status')) is not str:
                raise ValueError()
            transaction_status = int(receipt['status'], 16)
            if transaction_status not in (0, 1):
                raise ValueError()
        except (ValueError, TypeError):
            raise PaymentError("Payment verification is temporarily unavailable.",503,True,
                error_code="PAYMENT_VERIFICATION_UNAVAILABLE",stage="verification") from None
        if transaction_status != 1:
            raise PaymentError("실패한 트랜잭션입니다.",error_code="PAYMENT_TX_FAILED",stage="transaction")
        try:
            confirmations = self.rpc.block_number() - int(receipt["blockNumber"], 16) + 1
        except Exception:
            raise PaymentError("Payment verification is temporarily unavailable.",503,True,
                error_code="PAYMENT_VERIFICATION_UNAVAILABLE",stage="verification") from None
        if confirmations < self.min_confirmations:
            raise PaymentError(f"컨펌 부족 ({confirmations}/{self.min_confirmations}). 잠시 후 재시도하세요.", retryable=True,error_code="PAYMENT_CONFIRMATION_PENDING",stage="confirmation")

        try:
            paid = [(frm, amt) for frm, to, amt in transfers_in(receipt, self.token) if to == self.pay_to]
        except (ValueError, TypeError, KeyError, AttributeError):
            raise PaymentError("Payment verification is temporarily unavailable.",503,True,
                error_code="PAYMENT_VERIFICATION_UNAVAILABLE",stage="verification") from None
        if not paid:
            raise PaymentError("판매자 지갑으로의 USDC 전송이 없습니다.",error_code="PAYMENT_RECIPIENT_MISMATCH",stage="recipient")
        payers = {frm for frm, _ in paid}
        if len(payers) != 1:
            raise PaymentError("한 트랜잭션에 여러 송금자가 있어 결제자를 특정할 수 없습니다.",400,error_code="AMBIGUOUS_PAYMENT_PAYER",stage="payer")
        payer = payers.pop()
        amount = sum(amt for _, amt in paid)
        if amount < price:
            raise PaymentError(f"결제 금액 부족 ({amount} < {price})",error_code="PAYMENT_AMOUNT_INSUFFICIENT",stage="amount")

        try:
            chain_id = None
            try:
                chain_id = self.rpc.chain_id()
            except Exception:
                pass
            signer = recover_signer("agent-market", tx_hash, body, signature, chain_id=chain_id, token=self.token, expected_signer=payer)
        except ValueError as exc:
            raise PaymentError("Invalid proof signature.",400,error_code="INVALID_PAYMENT_SIGNATURE",stage="signature") from None
        if signer != payer:
            raise PaymentError("결제 서명자가 송금자와 다릅니다.",403,error_code="PAYMENT_SIGNER_MISMATCH",stage="signature")
        return VerifiedPayment(tx_hash.lower(), payer, amount)
