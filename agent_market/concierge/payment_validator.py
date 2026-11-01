"""x402 payment validation following Chapter 1 of the payment improvement plan.

Validates payment headers in the defined 10-stage order:
1. Header size <= 8KB, base64 -> JSON object (400 invalid_payload)
2. x402Version == 1 or 2 (400 invalid_x402_version)
3. Scheme == exact, network accepted (402 invalid_scheme, invalid_network)
4. authorization.to == payTo (402 invalid_exact_evm_payload_recipient_mismatch)
5. authorization.value >= amount (402 invalid_exact_evm_payload_authorization_value)
6. validAfter <= now < validBefore with >=6s remaining (402 invalid_exact_evm_payload_authorization_valid_before / _valid_after)
7. EIP-712 signature matches from address (402 invalid_exact_evm_payload_signature)
8. Nonce uniqueness (402 nonce_already_used)
The public gateway is probe-only: a well-formed proof is reported as not processed;
no balance is checked and nothing is settled.
"""
import base64
import binascii
import json
import time
from typing import Any
from fastapi.responses import JSONResponse

_USED_NONCES: set[str] = set()


def is_nonce_used(nonce: str) -> bool:
    if not nonce:
        return False
    norm = str(nonce).lower()
    return norm in _USED_NONCES


def mark_nonce_used(nonce: str) -> None:
    if nonce:
        _USED_NONCES.add(str(nonce).lower())


INSPECTION_INSTRUCTIONS=("This gateway only inspects provider payment requirements. Do not submit payment proofs here: "
    "it cannot accept, forward, or settle payments. Review the provider's own endpoint and terms separately.")


def inspection_notice(body):
    """Add truthful capability facts without changing the provider's native terms."""
    return {**body,'gateway_mode':'inspection_only','inspection_only':True,
            'payment_processed':False,'payment_accepted':False,'payment_forwarded':False,
            'settlement_performed':False,'instructions':INSPECTION_INSTRUCTIONS,
            'next_action':{'action':'review_provider_terms'}}


def payment_requirements_for(row: dict[str, Any] | None) -> dict[str, Any]:
    """The listing's recorded x402 terms only; never an invented amount or recipient."""
    if not isinstance(row, dict):
        row = {}
    gw_url = f"https://agentconcierge.biz/api/gateway/x402/{row['id']}" if row.get("id") else None
    accept = {"scheme": "exact", "network": "eip155:8453",
              "asset": "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",
              "maxTimeoutSeconds": 300, "extra": {"name": "USD Coin", "version": "2"}}
    if row.get("price_usdc"):
        accept["amount"] = str(row["price_usdc"])
    if row.get("pay_to"):
        accept["payTo"] = str(row["pay_to"])
    provider_url = str(row.get("url") or "") if isinstance(row, dict) else ""
    return inspection_notice({
        "x402Version": 2,
        "error": "Payment required",
        "gateway_mode": "inspection_only",
        "provider_url": provider_url,
        "resource": {"url": gw_url, "description": str(row.get("description") or "x402 listing")},
        # Without both recorded terms there is nothing an agent could correctly sign.
        "accepts": [accept] if "amount" in accept and "payTo" in accept else [],
    })


def payment_error(code: str, requirements: dict[str, Any], status: int = 402) -> JSONResponse:
    body = {**requirements, "error": code}
    try:
        hdr = base64.b64encode(json.dumps(body).encode("utf-8")).decode("ascii")
    except Exception:
        hdr = ""
    headers = {
        "PAYMENT-REQUIRED": hdr,
        "Cache-Control": "no-store",
        "Content-Type": "application/json"
    }
    return JSONResponse(body, status_code=status, headers=headers)


def validate_payment_submission(
    headers: Any,
    row: dict[str, Any] | None = None
) -> tuple[bool, str, int, dict[str, Any]]:
    """Validate payment submission headers against 10-stage rules.

    Returns: (is_valid, error_code, status_code, requirements)
    """
    reqs = payment_requirements_for(row)
    header_val = None
    header_name = None
    for name in ("payment-signature", "x-payment", "x-payment-signature"):
        val = headers.get(name) or headers.get(name.upper()) or headers.get(name.title())
        if val:
            header_val = val
            header_name = name.lower()
            break

    if not header_val:
        return False, "Payment required", 402, reqs

    # Stage 1: Header size <= 8192 bytes and valid base64 JSON
    if len(header_val) > 8192 or len(header_val) < 2:
        return False, "invalid_payload", 400, reqs

    try:
        wire = header_val.encode("ascii")
        raw = base64.b64decode(wire, validate=True)
        if base64.b64encode(raw) != wire:
            return False, "invalid_payload", 400, reqs
        obj = json.loads(raw.decode("utf-8"))
        if not isinstance(obj, dict) or not obj:
            return False, "invalid_payload", 400, reqs
    except (ValueError, TypeError, UnicodeError, binascii.Error):
        return False, "invalid_payload", 400, reqs

    # Stage 2: x402Version must be 1 or 2
    v = obj.get("x402Version")
    if v not in (1, 2):
        return False, "invalid_x402_version", 400, reqs

    # Stage 3: scheme & network
    accepted = obj.get("accepted") if isinstance(obj.get("accepted"), dict) else {}
    scheme = obj.get("scheme") or accepted.get("scheme") or "exact"
    network = obj.get("network") or accepted.get("network") or "eip155:8453"
    if scheme != "exact":
        return False, "invalid_scheme", 402, reqs
    if network not in ("eip155:8453", "base"):
        return False, "invalid_network", 402, reqs

    # Stage 4: Payload & Recipient
    payload = obj.get("payload") if isinstance(obj.get("payload"), dict) else {}
    auth = payload.get("authorization") if isinstance(payload.get("authorization"), dict) else {}
    if not auth:
        return False, "invalid_payload", 400, reqs

    target_accept = (reqs.get("accepts") or [{}])[0]
    expected_pay_to = target_accept.get("payTo", "")
    to_addr = auth.get("to")
    # Recipient and amount are compared only with the listing's recorded terms.
    if not to_addr or expected_pay_to and str(to_addr).lower() != expected_pay_to.lower():
        return False, "invalid_exact_evm_payload_recipient_mismatch", 402, reqs

    # Stage 5: Authorization value >= amount
    val = auth.get("value")
    try:
        val_int = int(val)
        if val_int <= 0 or "amount" in target_accept and val_int < int(target_accept["amount"]):
            return False, "invalid_exact_evm_payload_authorization_value", 402, reqs
    except (ValueError, TypeError):
        return False, "invalid_exact_evm_payload_authorization_value", 402, reqs

    # Stage 6: validAfter / validBefore
    now = int(time.time())
    valid_after = auth.get("validAfter")
    valid_before = auth.get("validBefore")
    try:
        if valid_after is not None and int(valid_after) > now:
            return False, "invalid_exact_evm_payload_authorization_valid_after", 402, reqs
        if valid_before is not None:
            vb = int(valid_before)
            if vb <= now or (vb - now) < 6:
                return False, "invalid_exact_evm_payload_authorization_valid_before", 402, reqs
    except (ValueError, TypeError):
        return False, "invalid_payload", 400, reqs

    # Stage 7: Signature format and recovery
    sig = payload.get("signature") or obj.get("signature")
    from_addr = auth.get("from")
    if not sig or not from_addr:
        return False, "invalid_exact_evm_payload_signature", 402, reqs

    sig_str = str(sig).lower().replace("0x", "")
    if not sig_str or set(sig_str) == {"0"} or len(sig_str) != 130:
        return False, "invalid_exact_evm_payload_signature", 402, reqs

    # Verify signature recovery if eth_account is available
    try:
        from eth_account import Account
        from eth_account.messages import encode_typed_data
        domain = {
            "name": accepted.get("extra", {}).get("name", "USD Coin"),
            "version": accepted.get("extra", {}).get("version", "2"),
            "chainId": 8453,
            "verifyingContract": accepted.get("asset", "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913")
        }
        types = {
            "TransferWithAuthorization": [
                {"name": "from", "type": "address"},
                {"name": "to", "type": "address"},
                {"name": "value", "type": "uint256"},
                {"name": "validAfter", "type": "uint256"},
                {"name": "validBefore", "type": "uint256"},
                {"name": "nonce", "type": "bytes32"}
            ]
        }
        message = {
            "from": from_addr,
            "to": to_addr,
            "value": val_int,
            "validAfter": int(valid_after or 0),
            "validBefore": int(valid_before or 0),
            "nonce": bytes.fromhex(str(auth.get("nonce", "")).replace("0x", "").zfill(64))
        }
        signable = encode_typed_data(domain_data=domain, message_types=types, message_data=message)
        recovered = Account.recover_message(signable, signature=sig)
        if recovered.lower() != str(from_addr).lower():
            return False, "invalid_exact_evm_payload_signature", 402, reqs
    except Exception:
        return False, "invalid_exact_evm_payload_signature", 402, reqs

    # Stage 8: Nonce reuse
    nonce = auth.get("nonce")
    if nonce and is_nonce_used(nonce):
        return False, "nonce_already_used", 402, reqs

    # The proof is well formed. This gateway never settles, so no balance or nonce is
    # consumed and no funds claim is made; the caller reports that payment is not processed.
    return True, "well_formed", 200, reqs
