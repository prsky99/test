"""Fixed public secp256k1 vector; no wallet generation, network or transaction."""
import base64
import copy
import json
import math

import pytest

from agent_market.workspace_x402_eip3009 import (ASSET, NETWORK, SECP256K1_N,
    EIP3009Invalid, decode_payment_header, verify_authorization)

FROM='0x7E5F4552091A69125d5DfCb7b8C2659029395Bdf'
TO='0x209693bc6afc0c5328ba36faf03c514ef312287c'
NONCE='0x'+'11'*32
NOW=2000000000
URL='https://resource.example.invalid/synthetic'
# Fixed public scalar-one test vector. No signing/private key API is exposed.
SIGNATURE='0x85ab6d5c4828860b7e8b749d97237ce72630345f71e8f87f1e61e40d953b1c1e0e9144b2e00ad990d0dda7e68fdf5010d1baa513d7b26be81fb3419c8a13543c1c'


def fixture():
    requirement={'scheme':'exact','network':NETWORK,'amount':'10000','asset':ASSET,
        'payTo':TO,'maxTimeoutSeconds':60,'extra':{'assetTransferMethod':'eip3009','name':'USDC','version':'2'}}
    payment={'x402Version':2,'resource':{'url':URL},'accepted':copy.deepcopy(requirement),
        'payload':{'signature':SIGNATURE,'authorization':{'from':FROM,'to':TO,'value':'10000',
            'validAfter':'1999999999','validBefore':'2000000060','nonce':NONCE}}}
    return payment,requirement


def verify(payment=None,requirement=None,**kwargs):
    initial,expected=fixture()
    return verify_authorization(initial if payment is None else payment,
        expected if requirement is None else requirement,
        **({'expected_from':FROM,'expected_nonce':NONCE,'resource_url':URL,'now':NOW}|kwargs))


def test_real_eip712_recovery_does_not_claim_payment_or_settlement(monkeypatch):
    def network(*args,**kwargs):pytest.fail('Offline verification attempted network I/O')
    monkeypatch.setattr('socket.socket.connect',network)
    value=verify()
    assert value['signature_valid'] and value['authorization_binding_valid']
    assert value['recovered_from']==FROM and len(value['authorization_digest'])==66
    for flag in ('verified_payment','settlement_authorized','nonce_consumption_verified',
        'chain_domain_verified','balance_verified','simulation_verified','finality_verified',
        'resource_cryptographically_bound','facilitator_supported'):
        assert value[flag] is False
    assert value['rpc_calls']==value['broadcasts']==value['ledger_events']==0
    assert value['status']=='signature_valid_chain_checks_unperformed'


def test_default_eip3009_method_without_extra_discriminator_remains_supported():
    payment,required=fixture()
    del payment['accepted']['extra']['assetTransferMethod'];del required['extra']['assetTransferMethod']
    assert verify(payment,required)['signature_valid']


@pytest.mark.parametrize('key,value', [('scheme','batch-settlement'),('network','eip155:8453'),
    ('asset','0x'+'22'*20),('amount','010000'),('amount',10000),('amount',True),
    ('amount','0'),('amount',str(2**256)),('maxTimeoutSeconds',True),('maxTimeoutSeconds',301)])
def test_requirements_profile_and_canonical_amount_fail_closed(key,value):
    payment,required=fixture();required[key]=value;payment['accepted']=copy.deepcopy(required)
    with pytest.raises(EIP3009Invalid):verify(payment,required)


@pytest.mark.parametrize('key,value',[('name','USD Coin'),('version','1'),('assetTransferMethod','permit2')])
def test_domain_and_transfer_method_are_pinned_not_taken_from_payload(key,value):
    payment,required=fixture();required['extra'][key]=value;payment['accepted']=copy.deepcopy(required)
    with pytest.raises(EIP3009Invalid,match='unsupported_profile'):verify(payment,required)


@pytest.mark.parametrize('key,value',[('amount','10001'),('payTo','0x'+'22'*20),('maxTimeoutSeconds',59)])
def test_payload_accepted_requirement_cannot_replace_independent_pin(key,value):
    payment,required=fixture();payment['accepted'][key]=value
    with pytest.raises(EIP3009Invalid,match='requirements_mismatch'):verify(payment,required)


@pytest.mark.parametrize('key,value',[('from','0x'+'22'*20),('to','0x'+'22'*20),
    ('value','10001'),('nonce','0x'+'22'*32)])
def test_exact_authorization_scope_cannot_be_changed(key,value):
    payment,required=fixture();payment['payload']['authorization'][key]=value
    with pytest.raises(EIP3009Invalid,match='authorization_mismatch'):verify(payment,required)


@pytest.mark.parametrize('key,value',[('validAfter','2000000000'),('validBefore','2000000000'),
    ('validBefore','2000000061'),('validBefore','-1'),('validAfter',True)])
def test_eip3009_strict_boundaries_and_bounded_validity(key,value):
    payment,required=fixture();payment['payload']['authorization'][key]=value
    with pytest.raises(EIP3009Invalid):verify(payment,required)


@pytest.mark.parametrize('instant',[True,-1,math.nan,math.inf,'2000000000'])
def test_invalid_clock_is_not_a_valid_authorization(instant):
    with pytest.raises(EIP3009Invalid,match='invalid_context'):verify(now=instant)


def test_signed_time_tamper_is_detected_cryptographically_even_inside_window():
    payment,required=fixture();payment['payload']['authorization']['validAfter']='1999999998'
    with pytest.raises(EIP3009Invalid,match='sender_mismatch'):verify(payment,required)


def test_recovered_signer_must_match_even_when_untrusted_from_matches_context():
    payment,required=fixture();other='0x'+'22'*20
    payment['payload']['authorization']['from']=other
    with pytest.raises(EIP3009Invalid,match='sender_mismatch'):
        verify(payment,required,expected_from=other)


@pytest.mark.parametrize('section,key',[('outer','accepted'),('payload','signature'),
    ('authorization','nonce'),('requirement','extra')])
def test_required_fields_cannot_be_omitted(section,key):
    payment,required=fixture()
    target=payment if section=='outer' else required if section=='requirement' else payment['payload'] if section=='payload' else payment['payload']['authorization']
    del target[key]
    with pytest.raises(EIP3009Invalid):verify(payment,required)


@pytest.mark.parametrize('signature',['0x'+'00'*65,'0x'+'11'*64,'private-key-like-invalid','0x'+'11'*66])
def test_malformed_signature_unsupported_compact_and_zero_values_are_refused(signature):
    payment,required=fixture();payment['payload']['signature']=signature
    with pytest.raises(EIP3009Invalid,match='invalid_signature'):verify(payment,required)


def test_malleated_high_s_signature_is_refused():
    payment,required=fixture();raw=bytes.fromhex(SIGNATURE[2:])
    flipped=raw[:32]+(SECP256K1_N-int.from_bytes(raw[32:64],'big')).to_bytes(32,'big')+bytes([27 if raw[-1]==28 else 28])
    payment['payload']['signature']='0x'+flipped.hex()
    with pytest.raises(EIP3009Invalid,match='invalid_signature'):verify(payment,required)


def test_in_range_signature_with_no_recoverable_curve_point_exposes_safe_code():
    payment,required=fixture()
    # r=5 is in range but has no recoverable secp256k1 point for this v.
    payment['payload']['signature']='0x'+((5).to_bytes(32,'big')+(1).to_bytes(32,'big')+b'\x1b').hex()
    with pytest.raises(EIP3009Invalid,match='invalid_signature'):verify(payment,required)


def test_wrong_expected_sender_nonce_and_resource_are_refused():
    for context in ({'expected_from':'0x'+'22'*20},{'expected_nonce':'0x'+'22'*32},
        {'resource_url':'https://resource.example.invalid/other'}):
        with pytest.raises(EIP3009Invalid):verify(**context)


@pytest.mark.parametrize('url',['http://resource.example.invalid/a','https://user:secret@example.invalid/a',
    'https://example.invalid/a#fragment','https://example.invalid/a b'])
def test_invalid_local_resource_context_is_refused(url):
    with pytest.raises(EIP3009Invalid,match='invalid_context'):verify(resource_url=url)


def test_resource_is_compared_but_honestly_not_in_the_eth_signature():
    payment,required=fixture();replacement=URL+'/different'
    payment['resource']['url']=replacement
    value=verify(payment,required,resource_url=replacement)
    assert value['signature_valid'] and value['resource_matches']
    assert not value['resource_cryptographically_bound']


@pytest.mark.parametrize('where,key,value',[('outer','x402Version',True),('outer','extension',{}),
    ('payload','privateKey','must-not-be-accepted'),('authorization','chainId',84532)])
def test_duplicate_or_unknown_wire_contract_fields_not_silently_ignored(where,key,value):
    payment,required=fixture();destination=payment if where=='outer' else payment['payload'] if where=='payload' else payment['payload']['authorization']
    destination[key]=value
    with pytest.raises(EIP3009Invalid):verify(payment,required)


def test_header_parser_accepts_ordinary_json_but_rejects_duplicate_keys_and_nonfinite():
    payment,_=fixture()
    encoded=base64.b64encode(json.dumps(payment,indent=2).encode()).decode()
    assert decode_payment_header(encoded)==payment
    for raw in (b'{"x402Version":2,"x402Version":1}',b'{"a":NaN}',b'[1]',b'{bad}'):
        with pytest.raises(EIP3009Invalid):decode_payment_header(base64.b64encode(raw).decode())


@pytest.mark.parametrize('value',['', 'not!base64', 'A'*20000])
def test_header_bounds_and_canonical_base64_reject_untrusted_bytes(value):
    with pytest.raises(EIP3009Invalid):decode_payment_header(value)


def test_error_contains_safe_code_not_supplied_signature_or_private_context():
    payment,required=fixture();payment['payload']['signature']='sensitive-untrusted-content'
    with pytest.raises(EIP3009Invalid) as caught:verify(payment,required)
    assert str(caught.value)=='invalid_signature' and 'sensitive' not in str(caught.value)
