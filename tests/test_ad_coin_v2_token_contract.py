"""Source rules for the draft AIADCoin contract and its deployment tool.

No Solidity compiler is installed here, so these checks read the source. Compiled behaviour
tests are still required before any deployment (see docs/AD_COIN_TOKEN_CONTRACT.md).
"""
import json
import pathlib
import re

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
CONTRACTS = ROOT / 'agent_market' / 'ad_coin' / 'v2' / 'contracts'
SOURCE = (CONTRACTS / 'AIADCoin.sol').read_text()
BODY = SOURCE[SOURCE.index('contract AIADCoin'):]


def _function(name):
    match = re.search(r'function ' + name + r'\b[^{;]*\{', BODY)
    assert match, name
    depth, i = 1, match.end()
    while depth:
        depth += {'{': 1, '}': -1}.get(BODY[i], 0)
        i += 1
    return BODY[match.start():i]


def test_mint_fails_closed_on_the_reserve_feed():
    mint = _function('mint')
    assert 'onlyBridgeMinter' in mint and 'whenNotPaused' in mint
    assert 'currentReserves()' in mint and 'ReserveDeficitDetected' in mint
    assert 'if (reserveOracleFeed != address(0))' not in SOURCE  # the old fail-open branch
    reserves = _function('currentReserves')
    for rule in ('ReserveFeedMissing', 'ReserveDecimalsMismatch', 'answer <= 0', 'ReserveAnswerStale',
                 'MAX_RESERVE_AGE', 'updatedAt > block.timestamp', 'answeredInRound < roundId'):
        assert rule in reserves, rule


def test_only_the_bridge_minter_mints():
    modifier = SOURCE[SOURCE.index('modifier onlyBridgeMinter'):]
    modifier = modifier[:modifier.index('}')]
    assert 'owner' not in modifier


def test_ownership_moves_in_two_steps_to_a_multisig_contract():
    assert 'pendingOwner = newOwner' in _function('transferOwnership')
    assert 'msg.sender != pendingOwner' in _function('acceptOwnership')
    assert 'account.code.length == 0' in _function('_requireMultisig')
    assert '_requireMultisig(initialOwner)' in SOURCE
    assert 'owner = msg.sender;\n        bridgeMinter' not in SOURCE  # deployer is no longer the owner


def test_minter_and_feed_changes_are_delayed():
    assert 'function setBridgeMinter' not in SOURCE and 'function setReserveOracleFeed' not in SOURCE
    assert 'block.timestamp + CHANGE_DELAY' in _function('scheduleChange')
    apply = _function('applyChange')
    assert 'ChangeNotReady' in apply and 'ChangeExpired' in apply and 'delete pendingChanges' in apply
    assert re.search(r'CHANGE_DELAY = [1-9]\d* days', SOURCE)


def test_zero_addresses_are_refused():
    for name in ('constructor', 'scheduleChange', '_transfer', 'mint', 'approve'):
        body = SOURCE[SOURCE.index('constructor('):] if name == 'constructor' else _function(name)
        assert 'ZeroAddress' in body[:1200], name


def test_spec_marks_the_contract_as_an_undeployed_draft():
    spec = json.loads((CONTRACTS / 'aiac_token_spec.json').read_text())
    assert spec['token']['status'] == 'draft_not_audited_not_deployed'
    assert 'ERC-2612' not in json.dumps(spec)  # permit is not implemented
    assert not (CONTRACTS / 'testnet_deployment.json').exists()


def test_deploy_tool_only_simulates():
    from scripts import deploy_token_testnet as tool
    source = (ROOT / 'scripts' / 'deploy_token_testnet.py').read_text()
    for forbidden in ('web3', 'eth_account', 'PRIVATE_KEY', 'write_text', 'HTTPProvider'):
        assert forbidden not in source, forbidden
    with pytest.raises(tool.DeploymentRefused):
        tool.main(['--execute', '--owner-multisig', '0x' + '1' * 40,
                   '--bridge-minter', '0x' + '2' * 40, '--reserve-feed', '0x' + '3' * 40])
    plan = tool.plan('base_sepolia', '0x' + '1' * 40, '0x' + '2' * 40, '0x' + '3' * 40)
    assert plan['status'] == 'simulation_only_not_deployed'
    with pytest.raises(ValueError):
        tool.plan('base_sepolia', '0x' + '0' * 40, '0x' + '2' * 40, '0x' + '3' * 40)


def test_experiment_bucketing_does_not_use_md5():
    source = (ROOT / 'agent_market' / 'ad_coin' / 'v2' / 'advertiser_platform.py').read_text()
    assert 'hashlib.md5' not in source and 'hashlib.sha256(f"{experiment_id}:{user_id}"' in source


@pytest.mark.skipif(not __import__('shutil').which('forge'), reason='Foundry is not installed on this machine')
def test_contract_behaviour_suite_passes_under_forge():
    """Compiles AIADCoin.sol and runs the behaviour tests (test/AIADCoin.t.sol) locally; no network chain."""
    import subprocess
    result = subprocess.run(['forge', 'test', '--offline'], cwd=CONTRACTS, capture_output=True, text=True, timeout=600)
    assert result.returncode == 0, result.stdout[-3000:] + result.stderr[-2000:]
    assert '0 failed' in result.stdout
