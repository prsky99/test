"""Runtime v2 parser/authority/arithmetic tests; no deployed routes or real funds."""
from dataclasses import replace
import hashlib
import json
from pathlib import Path
from uuid import UUID

import pytest

from agent_market.ad_coin.v2.contracts import (
    ContractError, MAX_ATOMS, P1Contract, atoms, canonical_bytes, decode_body, split_reward,
)
from agent_market.ad_coin.v2.identity import Kind, Principal, authorize

OWNER = UUID('00000000-0000-4000-8000-000000000001')
OTHER = UUID('00000000-0000-4000-8000-000000000002')
BINDING = UUID('00000000-0000-4000-8000-000000000003')
FRESH = UUID('00000000-0000-4000-8000-000000000004')
CONTRACT = P1Contract()


def consent(proof='p' * 43):
    return {'fresh_action_id': str(FRESH), 'fresh_action_proof': proof,
            'offer_id': str(OTHER), 'quote_hash': 'a' * 64}


@pytest.mark.parametrize('raw', [b'{"visible":true,"visible":false}', b'{"x":NaN}', b'{"x":1.0}',
                                  b'{"x":1e3}', b'{"x":9007199254740992}', b'{"x":"\xed\xa0\x80"}',
                                  b'{"x":"\\ud800"}', b'[]', b'{} trailing', b'\xff'])
def test_hostile_or_ambiguous_json_is_rejected(raw):
    with pytest.raises(ContractError):
        decode_body(raw)


def test_bounded_body_and_tree_and_content_encoding():
    for body, kwargs in [(b' '*32769, {}), (b'{"x":'+b'['*40+b'0'+b']'*40+b'}', {}),
                         (b'{}', {'content_type':'text/plain'}), (b'{}', {'content_type':'application/json;charset=utf-16'}),
                         (b'{}', {'content_encoding':'gzip'})]:
        with pytest.raises(ContractError):
            decode_body(body, **kwargs)
    assert decode_body(b'{"visible":true}', 'application/json; charset=UTF-8') == {'visible': True}


@pytest.mark.parametrize('value', [True, 1, 1.0, '-1', '01', '+1', '1.0', '1e3', '', str(MAX_ATOMS + 1)])
def test_atomic_units_have_no_implicit_numeric_conversion(value):
    with pytest.raises(ContractError):
        atoms(value)


def test_exact_uint256_and_rounding_conservation():
    assert atoms(str(MAX_ATOMS)) == MAX_ATOMS
    for gross in [2, 3, 17, 100_000_000, MAX_ATOMS]:
        allocation = split_reward(str(gross))
        assert sum(map(int, allocation.values())) == gross
        assert int(allocation['user']) > 0
    with pytest.raises(ContractError, match='zero_user_reward'):
        split_reward('1')
    with pytest.raises(ContractError, match='invalid_split'):
        split_reward('100', {'user': 4000, 'operator': 4000, 'direct': 1000, 'platform': 1000})


def test_semantic_and_idempotency_proofs_have_distinct_hashes_and_no_aliasing():
    a = CONTRACT.parse('approveOffer', json.dumps(consent()).encode())
    b = CONTRACT.parse('approveOffer', json.dumps(consent('q' * 43)).encode())
    assert a.semantic_digest == b.semantic_digest
    assert a.idempotency_digest != b.idempotency_digest
    copy = a.body; copy['offer_id'] = str(OWNER)
    assert a.body['offer_id'] == str(OTHER)
    assert canonical_bytes({'z': '한글', 'a': 1}) == '{"a":1,"z":"한글"}'.encode()
    with pytest.raises(ContractError):
        canonical_bytes({'x': 1.0})


def test_contract_pin_paths_preconditions_and_unknown_fields():
    with pytest.raises(ContractError, match='unsupported_contract'):
        CONTRACT.parse('approveOffer', b'{}', contract_version='v5')
    with pytest.raises(ContractError, match='invalid_request_schema'):
        CONTRACT.parse('approveOffer', json.dumps(dict(consent(), actor='human')).encode())
    body = json.dumps({'revision_hash':'a'*64}).encode()
    params = {'advertiser_id':str(OWNER), 'campaign_id':str(OTHER)}
    with pytest.raises(ContractError, match='version_precondition_required'):
        CONTRACT.parse('activateCampaign', body, path_parameters=params)
    a = CONTRACT.parse('activateCampaign', body, path_parameters=params, if_match='version-1')
    b = CONTRACT.parse('activateCampaign', body, path_parameters=params, if_match='version-2')
    assert a.semantic_digest != b.semantic_digest and a.idempotency_digest != b.idempotency_digest
    with pytest.raises(ContractError, match='invalid_path_parameters'):
        CONTRACT.parse('activateCampaign', body, path_parameters={**params, 'campaign_id':'../../other'}, if_match='v1')


def test_frozen_product_contract_matches_the_reviewed_design():
    root = Path(__file__).resolve().parents[1]
    product = root/'agent_market/ad_coin/v2/p1_contract.json'
    design = root/'docs/ad_coin_platform_p1_v6_2.openapi.json'
    assert hashlib.sha256(product.read_bytes()).digest() == hashlib.sha256(design.read_bytes()).digest()
    assert len(CONTRACT.operation_ids) == 29


def test_human_approval_csrf_and_agent_authority_are_separate():
    human = Principal(OWNER, Kind.HUMAN, 1, 2_000_000_000, owner_id=OWNER, csrf_verified=True)
    agent = Principal(OTHER, Kind.AGENT, 1, 2_000_000_000, owner_id=OWNER, agent_binding_id=BINDING,
                      capabilities=frozenset({'offers.request','wallet.read'}))
    authorize(CONTRACT, 'approveOffer', human, owner_id=OWNER, current_epoch=1)
    for principal in [agent, replace(human, csrf_verified=False), replace(human, epoch=2)]:
        with pytest.raises(ContractError):
            authorize(CONTRACT, 'approveOffer', principal, owner_id=OWNER, current_epoch=1)
    authorize(CONTRACT, 'getWallet', agent, owner_id=OWNER, manager_binding_id=BINDING)
    with pytest.raises(ContractError, match='unknown_resource'):
        authorize(CONTRACT, 'getWallet', agent, owner_id=OTHER)
    with pytest.raises(ContractError, match='unknown_resource'):
        authorize(CONTRACT, 'getWallet', agent, owner_id=OWNER, manager_binding_id=OTHER)


def test_advertiser_scopes_and_review_mtls_have_no_owner_bypass():
    human = Principal(OWNER, Kind.HUMAN, 1, 2_000_000_000, owner_id=OWNER, csrf_verified=True,
                       advertiser_permissions=frozenset({(OTHER,'budget.approve')}))
    authorize(CONTRACT, 'activateCampaign', human, advertiser_id=OTHER, current_epoch=1)
    with pytest.raises(ContractError):
        authorize(CONTRACT, 'activateCampaign', human, advertiser_id=OWNER)
    reviewer = Principal(OTHER, Kind.REVIEWER, 1, 2_000_000_000, capabilities=frozenset({'creative.review'}),
                          audience='aiac-v2-reviewer', mtls_verified=True)
    authorize(CONTRACT, 'decideReview', reviewer, current_epoch=1)
    with pytest.raises(ContractError, match='verified_mtls_required'):
        authorize(CONTRACT, 'decideReview', replace(reviewer, mtls_verified=False))
    with pytest.raises(ContractError):
        authorize(CONTRACT, 'decideReview', replace(reviewer, audience='aiac-v2-model'))


def test_authentication_evidence_cannot_be_truthy_strings():
    with pytest.raises(ContractError, match='invalid_authentication_evidence'):
        Principal(OWNER, Kind.HUMAN, 1, 2_000_000_000, owner_id=OWNER, csrf_verified='yes')


def test_missing_object_scope_never_falls_back_to_global_capability():
    human = Principal(OWNER, Kind.HUMAN, 1, 2_000_000_000, owner_id=OWNER, csrf_verified=True,
                      capabilities=frozenset({'budget.approve', 'wallet.read'}))
    with pytest.raises(ContractError, match='advertiser_scope_required'):
        authorize(CONTRACT, 'activateCampaign', human)
    with pytest.raises(ContractError, match='owner_scope_required'):
        authorize(CONTRACT, 'getWallet', human)
    agent = Principal(OTHER, Kind.AGENT, 1, 2_000_000_000, owner_id=OWNER, agent_binding_id=BINDING,
                      capabilities=frozenset({'wallet.read'}))
    with pytest.raises(ContractError, match='manager_scope_required'):
        authorize(CONTRACT, 'getWallet', agent, owner_id=OWNER)


def test_expired_or_untyped_authority_is_rejected():
    human = Principal(OWNER, Kind.HUMAN, 1, 1000, owner_id=OWNER, csrf_verified=True)
    with pytest.raises(ContractError, match='authority_expired'):
        authorize(CONTRACT, 'approveOffer', human, owner_id=OWNER, now=1001)
    with pytest.raises(ContractError, match='invalid_principal'):
        authorize(CONTRACT, 'approveOffer', {'kind': 'human'}, owner_id=OWNER)
    with pytest.raises(ContractError, match='invalid_authority_expiry'):
        Principal(OWNER, Kind.HUMAN, 1, float('inf'), owner_id=OWNER)


def test_write_authorization_cannot_skip_current_revocation_epoch():
    human = Principal(OWNER, Kind.HUMAN, 1, 2_000_000_000, owner_id=OWNER, csrf_verified=True)
    with pytest.raises(ContractError, match='authority_epoch_required'):
        authorize(CONTRACT, 'approveOffer', human, owner_id=OWNER)
