"""Paid Sponsored bookings in USDC on Base (user decision 11-11): one booking, one exact payment."""
import secrets
import time
from uuid import uuid4

import pytest

from agent_market.ad_coin.v2 import paid_bookings as paid
from agent_market.ad_coin.v2.access import HUMAN_CAPABILITIES, OPERATOR_CAPABILITY
from agent_market.ad_coin.v2.contracts import ContractError
from agent_market.ad_coin.v2.identity import Kind, Principal
from agent_market.ad_coin.v2.sponsored_booking import DAY_MS
from agent_market.chain import TRANSFER_TOPIC
from tests.test_ad_coin_postgres import cluster  # noqa: F401
from tests.test_ad_coin_v2_persistence import store  # noqa: F401
from tests.test_ad_coin_v2_p1 import NOW, _activate_campaign, p1_suite  # noqa: F401

PAY_TO = '0x' + '1' * 40
PAYER = '0x' + '2' * 40
TODAY = NOW - NOW % DAY_MS
NO_FILE = '/nonexistent/usdc-receive-address.txt'


@pytest.fixture(autouse=True)
def _no_operator_file(monkeypatch):
    monkeypatch.setenv('AD_COIN_PAID_PAY_TO_FILE', NO_FILE)   # never read the operator's real file in tests


def topic(address):
    return '0x' + address[2:].rjust(64, '0')


class FakeRPC:
    """Base receipts: tx -> (token, from, to, amount, block); the head block moves with .head."""

    def __init__(self):
        self.txs, self.head = {}, 100

    def send(self, amount, *, token=paid.BASE_USDC, sender=PAYER, to=PAY_TO, block=90, status='0x1'):
        tx = '0x' + secrets.token_hex(32)
        self.txs[tx] = dict(token=token, sender=sender, to=to, amount=amount, block=block, status=status)
        return tx

    def receipt(self, tx):
        t = self.txs.get(tx)
        if t is None:
            return None
        return {'status': t['status'], 'blockNumber': hex(t['block']), 'logs': [
            {'address': t['token'], 'topics': [TRANSFER_TOPIC, topic(t['sender']), topic(t['to'])], 'data': hex(t['amount'])}]}

    def block_number(self):
        return self.head

    def chain_id(self):
        return paid.BASE_CHAIN_ID


@pytest.fixture
def world(p1_suite):  # noqa: F811
    from scripts.ad_coin_v2_migrate import migrate_paid
    assert migrate_paid(p1_suite.service.store) == {'paid_bookings_table': True}
    rpc = FakeRPC()
    service = paid.PaidBookings(p1_suite.service.store, paid.PaidConfig(pay_to=PAY_TO), rpc=rpc,
                                sanctions=paid.Sanctions(addresses=['0x' + '9' * 40]),
                                taxonomy={'research', 'coding'}, regions={'US', 'KR'}, krw_rate=lambda: '1380.5')
    campaign = _activate_campaign(p1_suite)
    return p1_suite, service, rpc, campaign


def quote(world, *, day=TODAY + DAY_MS, region='US'):
    suite, service, _, campaign = world
    return service.quote(suite.advertiser, campaign_id=campaign['id'], region=region, task_category='research',
                         day=time.strftime('%Y-%m-%d', time.gmtime(day / 1000)), now_ms=NOW)


def operator(suite):
    pid, owner = str(uuid4()), str(uuid4())
    suite.service.access.provision_principal(pid, Kind.HUMAN, owner_id=owner,
                                             capabilities=HUMAN_CAPABILITIES | {OPERATOR_CAPABILITY})
    from uuid import UUID
    return Principal(UUID(pid), Kind.HUMAN, 1, time.time() + 300, owner_id=UUID(owner), csrf_verified=True,
                     audience='aiac-v2-model')


def test_switch_is_off_and_config_needs_a_receiving_address(monkeypatch):
    monkeypatch.delenv(paid.ENABLED_ENV, raising=False)
    assert not paid.enabled()
    with pytest.raises(RuntimeError):
        paid.PaidConfig.from_env({'AD_COIN_PAID_PAY_TO_FILE': NO_FILE})
    config = paid.PaidConfig.from_env({'AD_COIN_PAID_PAY_TO': PAY_TO.upper().replace('0X', '0x'), 'AD_COIN_PAID_PRICE_USDC': '5',
                                       'AD_COIN_PAID_PAY_TO_FILE': NO_FILE})
    assert config.price_units == 5_000_000 and config.pay_to == PAY_TO and config.chain_id == 8453


def test_exact_payment_confirms_once_and_records_krw(world):
    suite, service, rpc, _ = world
    q = quote(world)
    assert q['state'] == 'quoted' and q['network'] == 'Base' and q['token_symbol'] == 'USDC'
    amount = int(q['amount_units'])
    assert 5_000_001 <= amount <= 5_009_999 and q['amount_usdc'].startswith('5.00') and q['pay_to'] == PAY_TO
    tx = rpc.send(amount)
    done = service.submit(suite.advertiser, q['id'], tx, now_ms=NOW + 60_000)
    assert done['state'] == 'confirmed' and done['tx_hash'] == tx
    other = quote(world, region='KR')
    with pytest.raises(ContractError) as error:                       # one transaction pays one booking
        service.submit(suite.advertiser, other['id'], tx, now_ms=NOW + 60_000)
    assert error.value.code == 'payment_already_used'
    row = suite.service.store.one('paid_booking_get', (q['id'],))
    assert row['payer'] == PAYER and row['krw_rate'] == '1380.5'


def test_short_or_wrong_amount_goes_to_operator_review(world):
    suite, service, rpc, _ = world
    q = quote(world)
    tx = rpc.send(5_000_000)                                          # the price without the quote's tail
    assert service.submit(suite.advertiser, q['id'], tx, now_ms=NOW + 60_000)['state'] == 'review'
    assert suite.service.store.one('paid_booking_get', (q['id'],))['note'] == 'amount_mismatch'


def test_other_token_recipient_or_failed_transfer_leaves_the_quote_open(world):
    suite, service, rpc, _ = world
    q = quote(world)
    amount = int(q['amount_units'])
    for tx in (rpc.send(amount, token='0x' + '3' * 40), rpc.send(amount, to='0x' + '4' * 40)):
        with pytest.raises(ContractError) as error:
            service.submit(suite.advertiser, q['id'], tx, now_ms=NOW + 60_000)
        assert error.value.code == 'payment_not_found'
    with pytest.raises(ContractError) as error:
        service.submit(suite.advertiser, q['id'], rpc.send(amount, status='0x0'), now_ms=NOW + 60_000)
    assert error.value.code == 'payment_failed'
    row = suite.service.store.one('paid_booking_get', (q['id'],))
    assert row['state'] == 'quoted' and row['tx_hash'] is None
    assert service.submit(suite.advertiser, q['id'], rpc.send(amount), now_ms=NOW + 60_000)['state'] == 'confirmed'


def test_sanctioned_or_unscreened_payers_go_to_review(world, tmp_path):
    suite, service, rpc, _ = world
    q = quote(world)
    tx = rpc.send(int(q['amount_units']), sender='0x' + '9' * 40)
    assert service.submit(suite.advertiser, q['id'], tx, now_ms=NOW + 60_000)['state'] == 'review'
    assert suite.service.store.one('paid_booking_get', (q['id'],))['note'] == 'sanctions_match'
    service.sanctions = paid.Sanctions(str(tmp_path / 'missing.txt'))      # no list: never confirm blindly
    q2 = quote(world, region='KR')
    assert service.submit(suite.advertiser, q2['id'], rpc.send(int(q2['amount_units'])), now_ms=NOW + 60_000)['state'] == 'review'
    assert suite.service.store.one('paid_booking_get', (q2['id'],))['note'] == 'sanctions_unavailable'


def test_slow_confirmation_waits_then_confirms_and_unpaid_quotes_expire(world):
    suite, service, rpc, _ = world
    q = quote(world)
    tx = rpc.send(int(q['amount_units']), block=100)                 # 1 confirmation of 3
    assert service.submit(suite.advertiser, q['id'], tx, now_ms=NOW + 60_000)['state'] == 'confirming'
    rpc.head = 102
    assert service.recheck(now_ms=NOW + 120_000) >= 1
    assert suite.service.store.one('paid_booking_get', (q['id'],))['state'] == 'confirmed'
    late = quote(world, region='KR')
    service.recheck(now_ms=NOW + paid.QUOTE_TTL_MS + 1)
    assert suite.service.store.one('paid_booking_get', (late['id'],))['state'] == 'expired'
    # 11-14: money that arrives after the quote expired is kept for review, never lost in an error
    kept = service.submit(suite.advertiser, late['id'], rpc.send(int(late['amount_units'])), now_ms=NOW + paid.QUOTE_TTL_MS + 2)
    assert kept['state'] == 'review'
    assert suite.service.store.one('paid_booking_get', (late['id'],))['note'] == 'late_payment'


def test_placements_count_coin_and_paid_bookings_together(world):
    suite, service, rpc, _ = world
    for _ in range(2):
        q = quote(world)
        service.submit(suite.advertiser, q['id'], rpc.send(int(q['amount_units'])), now_ms=NOW + 60_000)
    with pytest.raises(ContractError) as error:
        quote(world)
    assert error.value.code == 'sponsored_day_full'


def test_operator_clears_reviews_records_refunds_and_exports_a_month(world):
    suite, service, rpc, _ = world
    access, op = suite.service.access, operator(suite)
    q = quote(world)
    service.submit(suite.advertiser, q['id'], rpc.send(5_000_000), now_ms=NOW + 60_000)       # review
    assert [i['id'] for i in service.operator_queue(access, op)['items']] == [q['id']]
    assert service.operator_decide(access, op, q['id'], action='refund')['state'] == 'refund_due'
    with pytest.raises(ContractError):
        service.operator_decide(access, op, q['id'], action='refunded', refund_tx_hash='nope')
    refund = '0x' + 'a' * 64
    assert service.operator_decide(access, op, q['id'], action='refunded', refund_tx_hash=refund)['state'] == 'refunded'
    good = quote(world, region='KR')
    service.submit(suite.advertiser, good['id'], rpc.send(int(good['amount_units'])), now_ms=NOW + 60_000)
    month = time.strftime('%Y-%m', time.gmtime((NOW + 60_000) / 1000))
    text = service.monthly_csv(access, op, month)
    assert text.splitlines()[0].startswith('confirmed_utc,booking_id,state,amount_usdc,payer,tx_hash,krw_per_usdc')
    assert good['id'] in text and refund in text and ',1380.5,' in text
    with pytest.raises(ContractError):
        service.operator_queue(access, Principal(uuid4(), Kind.HUMAN, 1, time.time() + 300, owner_id=uuid4(),
                                                 csrf_verified=True, audience='aiac-v2-model'))


def test_platform_fault_after_the_day_becomes_refund_due(world):
    suite, service, rpc, campaign = world
    q = quote(world)
    service.submit(suite.advertiser, q['id'], rpc.send(int(q['amount_units'])), now_ms=NOW + 60_000)
    from agent_market.ad_coin.sql_registry import unchecked
    store = suite.service.store
    with unchecked(), store.atomic():
        store._connection().execute("UPDATE adc2_campaigns SET state='suspended' WHERE id=?", (campaign['id'],))
    assert service.settle_due(now_ms=TODAY + 2 * DAY_MS + 11 * 60_000) == 1
    assert store.one('paid_booking_get', (q['id'],))['state'] == 'refund_due'


def test_routes_are_absent_while_the_switch_is_off(store, monkeypatch):  # noqa: F811
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from agent_market.ad_coin.v2.key_vault import KeyVault
    from agent_market.ad_coin.v2.live_service import create_live_ad_coin_v2_router
    monkeypatch.delenv(paid.ENABLED_ENV, raising=False)
    store.migrate_model()
    app = FastAPI()
    app.include_router(create_live_ad_coin_v2_router(store, key_vault=KeyVault()))
    client = TestClient(app)
    path = '/api/ad-coin/v2/advertisers/' + str(uuid4()) + '/paid-bookings'
    assert client.post(path, json={}).status_code in (404, 405)
    assert client.get('/api/ad-coin/v2/admin/paid-bookings').status_code in (404, 405)


def test_http_quote_pay_list_and_operator_export(world):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from agent_market.ad_coin.v2.paid_bookings_http import router_for
    suite, service, rpc, campaign = world
    app = FastAPI()
    app.include_router(router_for(suite.service, service, resolve_auth=suite.resolver))
    client = TestClient(app)
    base = '/api/ad-coin/v2/advertisers/' + suite.advertiser + '/paid-bookings'
    body = {'campaign_id': campaign['id'], 'task_category': 'research', 'region': 'US',
            'day': time.strftime('%Y-%m-%d', time.gmtime((int(time.time() * 1000) // DAY_MS + 1) * DAY_MS / 1000))}
    assert client.post(base, json=body, headers=suite.headers('user')).status_code == 403     # a person cannot book
    q = client.post(base, json=body, headers=suite.headers('approver'))
    assert q.status_code == 200, q.text
    q = q.json()
    tx = rpc.send(int(q['amount_units']))
    done = client.post(base + '/' + q['id'] + '/payment', json={'tx_hash': tx}, headers=suite.headers('approver'))
    assert done.status_code == 200 and done.json()['state'] == 'confirmed'
    bad = client.post(base + '/' + q['id'] + '/payment', json={'tx_hash': 'x'}, headers=suite.headers('approver'))
    assert bad.status_code == 422
    assert [i['id'] for i in client.get(base, headers=suite.headers('editor')).json()['items']] == [q['id']]
    assert client.get('/api/ad-coin/v2/admin/paid-bookings', headers=suite.headers('approver')).status_code == 403


def test_missing_krw_rate_sends_the_payment_to_review(world):
    suite, service, rpc, _ = world
    service.krw_rate = lambda: None
    q = quote(world)
    assert service.submit(suite.advertiser, q['id'], rpc.send(int(q['amount_units'])), now_ms=NOW + 60_000)['state'] == 'review'
    assert suite.service.store.one('paid_booking_get', (q['id'],))['note'] == 'krw_rate_unavailable'


def test_router_assembles_with_the_switch_on(store, monkeypatch):  # noqa: F811
    """11-11 journey: switching paid bookings on must not break the v2 router (import path regression)."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from agent_market.ad_coin.v2.key_vault import KeyVault
    from agent_market.ad_coin.v2.live_service import create_live_ad_coin_v2_router
    monkeypatch.setenv(paid.ENABLED_ENV, '1')
    monkeypatch.setenv('AD_COIN_PAID_PAY_TO', PAY_TO)
    store.migrate_model()
    app = FastAPI()
    app.include_router(create_live_ad_coin_v2_router(store, key_vault=KeyVault()))
    response = TestClient(app).post('/api/ad-coin/v2/advertisers/' + str(uuid4()) + '/paid-bookings', json={})
    assert response.status_code == 401                                    # mounted: asks for sign-in


BRIDGED_USDBC = '0xd9aaec86b65d86f6a7b5b1b0c42ffa531710b6ca'   # older bridged USDC on Base: not accepted


def test_receive_address_comes_from_the_operator_file(tmp_path):
    path = tmp_path / 'usdc-receive-address.txt'
    path.write_text('# receive only, no key on the server\n# checks: checksum, OFAC, plain account\n%s\n' % PAY_TO.upper().replace('0X', '0x'))
    config = paid.PaidConfig.from_env({'AD_COIN_PAID_PAY_TO_FILE': str(path)})
    assert config.pay_to == PAY_TO and config.token == paid.BASE_USDC
    assert config.token == '0x833589fcd6edb6e08f4c7c32d4f71b54bda02913'          # Circle's native USDC on Base
    assert paid.PaidConfig.from_env({'AD_COIN_PAID_PAY_TO_FILE': str(path), 'AD_COIN_PAID_PAY_TO': PAY_TO}).pay_to == PAY_TO
    with pytest.raises(RuntimeError):                                             # env and file must agree
        paid.PaidConfig.from_env({'AD_COIN_PAID_PAY_TO_FILE': str(path), 'AD_COIN_PAID_PAY_TO': PAYER})
    path.write_text('%s\n%s\n' % (PAY_TO, PAYER))                                 # two addresses: unclear, refuse
    with pytest.raises(RuntimeError):
        paid.PaidConfig.from_env({'AD_COIN_PAID_PAY_TO_FILE': str(path)})


def test_real_receive_file_parses_when_present():
    from pathlib import Path
    path = Path(paid.DEFAULT_PAY_TO_FILE)
    if not path.exists():
        pytest.skip('operator file is local only')
    assert paid.pay_to_from_file(str(path)) is not None
    assert oct(path.stat().st_mode & 0o777) == '0o600'


def test_payment_screen_shows_the_file_address_and_only_native_usdc_to_it_counts(world, tmp_path):
    suite, service, rpc, _ = world
    path = tmp_path / 'usdc-receive-address.txt'
    path.write_text('# note\n%s\n' % PAY_TO)
    service.config = paid.PaidConfig.from_env({'AD_COIN_PAID_PAY_TO_FILE': str(path)})
    q = quote(world)
    assert q['pay_to'] == PAY_TO and q['network'] == 'Base' and q['token_symbol'] == 'USDC'
    amount = int(q['amount_units'])
    for tx in (rpc.send(amount, token=BRIDGED_USDBC), rpc.send(amount, to='0x' + '5' * 40)):
        with pytest.raises(ContractError) as error:
            service.submit(suite.advertiser, q['id'], tx, now_ms=NOW + 60_000)
        assert error.value.code == 'payment_not_found'
    assert service.submit(suite.advertiser, q['id'], rpc.send(amount), now_ms=NOW + 60_000)['state'] == 'confirmed'


def test_other_network_rpc_never_confirms(world):
    suite, service, rpc, _ = world
    rpc.chain_id = lambda: 1                                                     # Ethereum mainnet, not Base
    with pytest.raises(RuntimeError):
        service.check_network()
    q = quote(world)
    tx = rpc.send(int(q['amount_units']))
    assert service.submit(suite.advertiser, q['id'], tx, now_ms=NOW + 60_000)['state'] == 'confirming'
    rpc.chain_id = lambda: paid.BASE_CHAIN_ID
    assert service.recheck(now_ms=NOW + 120_000) is not None
    assert suite.service.store.one('paid_booking_get', (q['id'],))['state'] == 'confirmed'


def test_gateway_data_paths_resolve_from_a_release_folder(tmp_path, monkeypatch):
    # The worker daemon runs with cwd = PROJECT/gateway-data/services/releases/<name>: relative paths must still work.
    release = tmp_path / 'gateway-data/services/releases/r1'
    release.mkdir(parents=True)
    monkeypatch.chdir(release)
    assert paid.data_path(paid.DEFAULT_OFAC_LIST).endswith('gateway-data/ofac/eth_addresses.txt')
    from pathlib import Path
    project = Path(paid.__file__).resolve().parents[3]
    if (project / paid.DEFAULT_OFAC_LIST).exists():
        assert paid.data_path(paid.DEFAULT_OFAC_LIST) == str(project / paid.DEFAULT_OFAC_LIST)
        assert paid.Sanctions(paid.DEFAULT_OFAC_LIST).screen('0x' + 'ab' * 20) == 'clear'
    assert paid.data_path('/abs/x.txt') == '/abs/x.txt'
