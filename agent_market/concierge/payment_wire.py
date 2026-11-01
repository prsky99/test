"""Bounded x402 challenge parsing; no signing, conversion or settlement."""
import base64
import binascii
import json
import math

MAX_BYTES = 32768


def _object(raw):
    if type(raw) is not bytes or not 1 <= len(raw) <= MAX_BYTES:
        raise ValueError('Invalid payment envelope.')
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError('Duplicate payment field.')
            result[key] = value
        return result
    def invalid(_):
        raise ValueError('Invalid payment number.')
    value = json.loads(raw.decode('utf-8'), object_pairs_hook=pairs, parse_constant=invalid)
    pending, count = [(value, 0)], 0
    while pending:
        item, depth = pending.pop(); count += 1
        if depth > 12 or count > 2048:
            raise ValueError('Payment envelope limit.')
        if type(item) is float and not math.isfinite(item):
            raise ValueError('Invalid payment number.')
        if type(item) is dict:
            pending.extend((v, depth + 1) for v in item.values())
        elif type(item) is list:
            pending.extend((v, depth + 1) for v in item)
    if type(value) is not dict:
        raise ValueError('Invalid payment object.')
    return value


def challenge_objects(response):
    """A present v2 header is authoritative, including when it is malformed."""
    values = response.headers.get_list('payment-required')
    try:
        if values:
            if len(values) != 1 or len(values[0]) > 4 * ((MAX_BYTES + 2) // 3):
                return []
            encoded = values[0].encode('ascii')
            raw = base64.b64decode(encoded, validate=True)
            if base64.b64encode(raw) != encoded:
                return []
            value = _object(raw)
            return [value] if value.get('x402Version') == 2 else []
        return [_object(response.content)]
    except (ValueError, TypeError, UnicodeError, RecursionError, binascii.Error):
        return []


class PaymentWireError(ValueError):
    def __init__(self, code='invalid_payload'):
        self.code = code
        super().__init__(code)


def _header_object(encoded):
    try:
        if type(encoded) is not str or len(encoded) > 4 * ((MAX_BYTES + 2) // 3):
            raise ValueError()
        wire = encoded.encode('ascii'); raw = base64.b64decode(wire, validate=True)
        if base64.b64encode(raw) != wire:
            raise ValueError()
        return _object(raw)
    except (ValueError,TypeError,UnicodeError,RecursionError,binascii.Error):
        raise PaymentWireError() from None


def payment_headers(payment):
    """Allow only bounded native proof headers; never convert signed payloads."""
    import re
    if payment is None or type(payment) is dict and not payment:
        return {}
    if type(payment) is not dict or set(payment)-{'tx_hash','signature','headers'}:
        raise PaymentWireError()
    supplied = payment.get('headers', {})
    if type(supplied) is not dict or len(supplied) > 2:
        raise PaymentWireError()
    result = {}
    for key, value in supplied.items():
        if type(key) is not str or type(value) is not str:
            raise PaymentWireError()
        name = key.lower()
        if name not in ('payment-signature','x-payment','x-payment-tx','x-payment-signature') or name in result:
            raise PaymentWireError()
        result[name] = value
    for field, name in (('tx_hash','x-payment-tx'),('signature','x-payment-signature')):
        if field in payment:
            if name in result or type(payment[field]) is not str:
                raise PaymentWireError()
            result[name] = payment[field]
    modes = int('payment-signature' in result)+int('x-payment' in result)+int(bool({'x-payment-tx','x-payment-signature'} & result.keys()))
    if modes != 1:
        raise PaymentWireError()
    if 'payment-signature' in result or 'x-payment' in result:
        header = 'payment-signature' if 'payment-signature' in result else 'x-payment'
        obj = _header_object(result[header]); version = 2 if header=='payment-signature' else 1
        if type(obj.get('x402Version')) is not int or obj['x402Version'] != version:
            raise PaymentWireError('invalid_x402_version')
        if type(obj.get('payload')) is not dict or (version==2 and type(obj.get('accepted')) is not dict):
            raise PaymentWireError()
    elif (set(result) != {'x-payment-tx','x-payment-signature'}
            or not re.fullmatch(r'0x[0-9a-fA-F]{64}',result['x-payment-tx'])
            or not re.fullmatch(r'0x[0-9a-fA-F]{130}',result['x-payment-signature'])):
        raise PaymentWireError()
    return result


def settlement_response(response):
    """Inspect a provider receipt without asserting chain confirmation."""
    import re
    headers=response.headers.get_list('payment-response')
    if not headers:
        return None
    if len(headers)!=1:
        raise PaymentWireError('invalid_payment_response')
    try:
        obj=_header_object(headers[0]); transaction=obj.get('transaction'); network=obj.get('network')
        if (type(obj.get('success')) is not bool or type(transaction) is not str
                or type(network) is not str or not re.fullmatch(r'[a-z0-9-]{3,8}:[A-Za-z0-9-]{1,128}',network)
                or transaction and not re.fullmatch(r'0x[0-9a-fA-F]{64}',transaction)
                or (obj['success'] or obj.get('errorReason')=='settlement_pending') and not transaction):
            raise ValueError()
        if obj['success'] and obj.get('errorReason'):
            raise ValueError()
        if 'amount' in obj and (type(obj['amount']) is not str or not re.fullmatch(r'0|[1-9][0-9]{0,77}',obj['amount'])):
            raise ValueError()
        selected={k:obj[k] for k in ('success','transaction','network','payer','errorReason','amount') if k in obj}
        if any(type(v) is not str or len(v)>256 for k,v in selected.items() if k!='success'):
            raise ValueError()
        return selected
    except (ValueError,TypeError):
        raise PaymentWireError('invalid_payment_response') from None


def validate_receipt_binding(receipt, proof_headers):
    """Compare reported v2 receipt fields, without asserting chain settlement."""
    if receipt is None or 'payment-signature' not in proof_headers:
        return
    payment = _header_object(proof_headers['payment-signature'])
    accepted = payment['accepted']
    if not accepted.get('network') or receipt['network'] != accepted['network']:
        raise PaymentWireError('invalid_payment_response')
    if 'amount' in receipt and receipt['amount'] != accepted.get('amount'):
        raise PaymentWireError('invalid_payment_response')
    authorization = payment['payload'].get('authorization')
    if 'payer' in receipt and isinstance(authorization, dict):
        payer = authorization.get('from')
        if not isinstance(payer, str) or receipt['payer'].lower() != payer.lower():
            raise PaymentWireError('invalid_payment_response')
