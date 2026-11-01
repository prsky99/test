"""Offline x402 v2 exact/EIP-3009 signature checks for one pinned test profile.

A valid EOA signature is not a verified payment. This module has no signing,
private-key, provider, RPC, broadcast, ledger or settlement adapter. Contract
wallets, Permit2 and other chains/assets are explicitly outside this profile.
"""
import base64
import binascii
import hashlib
import json
import math
import re
import time
from urllib.parse import urlsplit

from eth_account import Account
from eth_account.messages import encode_typed_data
from eth_keys.exceptions import BadSignature
from eth_utils import is_checksum_address, keccak, to_checksum_address
from eth_utils.exceptions import ValidationError

PROFILE = 'x402-v2-exact-eip3009-base-sepolia-usdc-v1'
NETWORK = 'eip155:84532'
CHAIN_ID = 84532
ASSET = '0x036CbD53842c5426634e7929541eC2318f3dCF7e'
DOMAIN_NAME = 'USDC'
DOMAIN_VERSION = '2'
MAX_BYTES = 8192
UINT256 = 2**256 - 1
SECP256K1_N = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEBAAEDCE6AF48A03BBFD25E8CD0364141
SOURCE_URL = 'https://github.com/x402-foundation/x402/blob/main/specs/schemes/exact/scheme_exact_evm.md'
AUTH_FIELDS = ('from', 'to', 'value', 'validAfter', 'validBefore', 'nonce')


class EIP3009Invalid(ValueError):
    def __init__(self, code='invalid_payment_envelope', *, error_code=None, stage=None):
        self.code = code
        self.error_code = error_code or {
            'unsupported_profile':'invalid_payment_requirements',
            'requirements_mismatch':'invalid_payment_requirements',
            'invalid_signature':'invalid_exact_evm_payload_signature',
            'sender_mismatch':'invalid_exact_evm_payload_signature',
        }.get(code,'invalid_payload')
        self.stage = stage or ('signature' if code in ('invalid_signature','sender_mismatch') else 'requirements' if code in ('unsupported_profile','requirements_mismatch') else 'format')
        super().__init__(code)


def _canonical(value):
    def bounded(current, depth=0):
        if depth > 8:
            raise EIP3009Invalid()
        if type(current) is dict:
            if len(current) > 16 or any(type(key) is not str or len(key) > 100 for key in current):
                raise EIP3009Invalid()
            for child in current.values(): bounded(child, depth+1)
        elif type(current) not in (str, int, bool, type(None)):
            raise EIP3009Invalid()
    try:
        bounded(value)
        raw = json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=True,allow_nan=False)
        if len(raw.encode()) > MAX_BYTES:
            raise EIP3009Invalid()
        return raw
    except (TypeError, ValueError, RecursionError, UnicodeError):
        raise EIP3009Invalid() from None


def _exact(value, fields):
    if type(value) is not dict or set(value) != set(fields):
        raise EIP3009Invalid()


def _address(value):
    if type(value) is not str or not re.fullmatch(r'0x[0-9a-fA-F]{40}',value):
        raise EIP3009Invalid('invalid_address')
    letters=value[2:]
    if (int(letters,16)==0 or letters not in (letters.lower(),letters.upper()) and not is_checksum_address(value)):
        raise EIP3009Invalid('invalid_address')
    return to_checksum_address(value)


def _uint(value, *, positive=False):
    if type(value) is not str or not re.fullmatch(r'0|[1-9][0-9]{0,77}',value):
        raise EIP3009Invalid('invalid_uint256')
    number=int(value)
    if number > UINT256 or positive and number==0:
        raise EIP3009Invalid('invalid_uint256')
    return number


def _nonce(value):
    if type(value) is not str or not re.fullmatch(r'0x[0-9a-fA-F]{64}',value):
        raise EIP3009Invalid('invalid_nonce')
    return value.lower()


def decode_payment_header(value):
    """Decode bounded standard Base64 JSON with duplicate/nonfinite rejection."""
    if type(value) is not str or not 1<=len(value)<=MAX_BYTES*2:
        raise EIP3009Invalid()
    def pairs(items):
        result={}
        for key,item in items:
            if key in result:raise EIP3009Invalid()
            result[key]=item
        return result
    try:
        raw=base64.b64decode(value.encode('ascii'),validate=True)
        if len(raw)>MAX_BYTES or base64.b64encode(raw).decode('ascii')!=value:
            raise EIP3009Invalid()
        parsed=json.loads(raw.decode('utf-8'),object_pairs_hook=pairs,
            parse_constant=lambda _: (_ for _ in ()).throw(EIP3009Invalid()))
        _canonical(parsed)
        if type(parsed) is not dict:raise EIP3009Invalid()
        return parsed
    except (ValueError,TypeError,UnicodeError,RecursionError,binascii.Error):
        raise EIP3009Invalid() from None


def _requirements(value):
    _exact(value,('scheme','network','amount','asset','payTo','maxTimeoutSeconds','extra'))
    if value['scheme']!='exact':
        raise EIP3009Invalid('unsupported_profile',error_code='invalid_scheme',stage='scheme')
    if value['network']!=NETWORK:
        raise EIP3009Invalid('unsupported_profile',error_code='invalid_network',stage='network')
    if (_address(value['asset'])!=ASSET or type(value['maxTimeoutSeconds']) is not int
            or not 1<=value['maxTimeoutSeconds']<=300):
        raise EIP3009Invalid('unsupported_profile')
    _uint(value['amount'],positive=True);_address(value['payTo'])
    extra=value['extra']
    if (type(extra) is not dict or set(extra) not in ({'name','version'},{'name','version','assetTransferMethod'})
            or extra.get('name')!=DOMAIN_NAME or extra.get('version')!=DOMAIN_VERSION
            or extra.get('assetTransferMethod','eip3009')!='eip3009'):
        raise EIP3009Invalid('unsupported_profile')


def _typed(authorization):
    return encode_typed_data(domain_data={'name':DOMAIN_NAME,'version':DOMAIN_VERSION,
        'chainId':CHAIN_ID,'verifyingContract':ASSET},message_types={'TransferWithAuthorization':[
            {'name':name,'type':kind} for name,kind in zip(AUTH_FIELDS,
                ('address','address','uint256','uint256','uint256','bytes32'))]},
        message_data={name:(_uint(authorization[name]) if name in ('value','validAfter','validBefore') else authorization[name]) for name in AUTH_FIELDS})


def verify_authorization(payment, requirements, *, expected_from, expected_nonce, resource_url, now=None):
    """Recover a signature against independent, exact caller-pinned requirements.

    Resource metadata is compared locally; EIP-3009 does not sign the URL. No
    balance, token-domain, unused nonce, contract-wallet, simulation or finality
    check is invented. The result cannot authorize capture, execution or funds.
    """
    _canonical(payment)
    _exact(payment,('x402Version','resource','accepted','payload'))
    if type(payment['x402Version']) is not int or payment['x402Version']!=2:
        raise EIP3009Invalid('unsupported_profile',error_code='invalid_x402_version',stage='version')
    _canonical(requirements)
    _requirements(requirements)
    sender=_address(expected_from);nonce=_nonce(expected_nonce)
    if type(resource_url) is not str or len(resource_url)>2048:
        raise EIP3009Invalid('invalid_context')
    try:
        resource=urlsplit(resource_url)
        if (resource.scheme!='https' or not resource.hostname or resource.username is not None
                or resource.password is not None or resource.fragment or any(c.isspace() for c in resource_url)):
            raise ValueError()
    except ValueError:raise EIP3009Invalid('invalid_context') from None
    if (type(payment['resource']) is not dict or set(payment['resource'])-{'url','description','mimeType'}
            or payment['resource'].get('url')!=resource_url
            or any(type(v) is not str for v in payment['resource'].values())):
        raise EIP3009Invalid('requirements_mismatch')
    _requirements(payment['accepted'])
    if payment['accepted']!=requirements:
        raise EIP3009Invalid('requirements_mismatch')
    _exact(payment['payload'],('signature','authorization'))
    auth=payment['payload']['authorization'];_exact(auth,AUTH_FIELDS)
    if _address(auth['to'])!=_address(requirements['payTo']):
        raise EIP3009Invalid('authorization_mismatch',error_code='invalid_exact_evm_payload_recipient_mismatch',stage='recipient')
    if _uint(auth['value'],positive=True)!=_uint(requirements['amount'],positive=True):
        raise EIP3009Invalid('authorization_mismatch',error_code='invalid_exact_evm_payload_authorization_value_mismatch',stage='amount')
    if _address(auth['from'])!=sender or _nonce(auth['nonce'])!=nonce:
        raise EIP3009Invalid('authorization_mismatch',stage='binding')
    instant=time.time() if now is None else now
    if type(instant) not in (int,float) or not math.isfinite(instant) or instant<0:
        raise EIP3009Invalid('invalid_context')
    start,finish=_uint(auth['validAfter']),_uint(auth['validBefore'])
    if not start<instant:
        raise EIP3009Invalid('authorization_not_current',error_code='invalid_exact_evm_payload_authorization_valid_after',stage='validity')
    if not instant<finish:
        raise EIP3009Invalid('authorization_not_current',error_code='invalid_exact_evm_payload_authorization_valid_before',stage='validity')
    if finish>instant+requirements['maxTimeoutSeconds']:
        raise EIP3009Invalid('authorization_not_current',stage='validity')
    signature=payment['payload']['signature']
    if type(signature) is not str or not re.fullmatch(r'0x[0-9a-fA-F]{130}',signature):
        raise EIP3009Invalid('invalid_signature')
    signed=bytes.fromhex(signature[2:]);r=int.from_bytes(signed[:32],'big');s=int.from_bytes(signed[32:64],'big')
    if not 0<r<SECP256K1_N or not 0<s<=SECP256K1_N//2 or signed[64] not in (27,28):
        raise EIP3009Invalid('invalid_signature')
    try:
        typed=_typed(auth)
        recovered=Account.recover_message(typed,signature=signed)
    except (ValueError,TypeError,OverflowError,BadSignature,ValidationError):
        raise EIP3009Invalid('invalid_signature') from None
    if recovered!=sender:
        raise EIP3009Invalid('sender_mismatch')
    digest='0x'+keccak(b'\x19'+typed.version+typed.header+typed.body).hex()
    return {'profile':PROFILE,'network':NETWORK,'asset':ASSET,'scheme':'exact',
        'signature_valid':True,'authorization_binding_valid':True,'recovered_from':recovered,
        'authorization_digest':digest,'requirements_sha256':hashlib.sha256(_canonical(requirements).encode()).hexdigest(),
        'nonce_reference':hashlib.sha256((NETWORK+ASSET.lower()+sender.lower()+nonce).encode()).hexdigest(),
        'resource_matches':True,'resource_cryptographically_bound':False,
        'verified_payment':False,'settlement_authorized':False,'nonce_consumption_verified':False,
        'chain_domain_verified':False,'balance_verified':False,'simulation_verified':False,'finality_verified':False,
        'facilitator_supported':False,'rpc_calls':0,'broadcasts':0,'ledger_events':0,
        'status':'signature_valid_chain_checks_unperformed'}
