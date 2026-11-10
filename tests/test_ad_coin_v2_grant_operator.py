"""Server-only operator grant for AI AD Coin v2 (PM step 1, 11-11)."""
import json

import pytest

from scripts import ad_coin_grant_operator as tool
from tests.test_ad_coin_postgres import cluster  # noqa: F401
from tests.test_ad_coin_v2_persistence import store  # noqa: F401
from tests.test_ad_coin_v2_site_session import headers, site  # noqa: F401

LINK_KEY = b'L' * 32  # the key the site fixture's vault uses
CUSTOMER = 'cu_' + '7' * 32


def test_operator_is_granted_and_revoked_for_one_signed_in_customer(site):  # noqa: F811
    principal = tool.principal_id_for(CUSTOMER, LINK_KEY)
    assert tool.run(site.store, principal, 'status') == {
        'principal_exists': False, 'operator': False,
        'hint': 'the customer must sign in and open /ad-coin/v2 once first'}
    assert tool.run(site.store, principal, 'grant')['principal_exists'] is False  # nothing created
    token = site.identity.sign_in(CUSTOMER)
    assert site.get('/ad-coin/v2/ui/session', headers=headers(token)).status_code == 200
    assert site.get('/api/ad-coin/v2/admin/overview', headers=headers(token)).status_code == 403
    assert tool.run(site.store, principal, 'grant') == {'principal_exists': True, 'operator': True, 'changed': True}
    assert tool.run(site.store, principal, 'grant')['changed'] is False               # idempotent
    assert site.get('/api/ad-coin/v2/admin/overview', headers=headers(token)).status_code == 200
    from agent_market.ad_coin.v2.access import PLATFORM_OPERATORS_ID
    assert site.store.one('advertiser_get', (PLATFORM_OPERATORS_ID,))['status'] == 'suspended'
    assert site.get('/ad-coin/v2/ui/session', headers=headers(token)).json()['advertisers'] == []  # not an advertiser
    other = site.identity.sign_in('cu_' + '8' * 32)
    site.get('/ad-coin/v2/ui/session', headers=headers(other))
    assert site.get('/api/ad-coin/v2/admin/overview', headers=headers(other)).status_code == 403  # only that one
    assert tool.run(site.store, principal, 'revoke') == {'principal_exists': True, 'operator': False, 'changed': True}
    assert site.get('/api/ad-coin/v2/admin/overview', headers=headers(token)).status_code == 403  # at once


def test_changes_are_audited_without_the_customer_id(site):  # noqa: F811
    principal = tool.principal_id_for(CUSTOMER, LINK_KEY)
    site.get('/ad-coin/v2/ui/session', headers=headers(site.identity.sign_in(CUSTOMER)))
    tool.run(site.store, principal, 'grant')
    tool.run(site.store, principal, 'revoke')
    from agent_market.ad_coin.sql_registry import unchecked
    with unchecked(), site.store.atomic():
        rows = site.store.database.all(
            "SELECT event_type,target_id,details_json FROM adc2_audit_log "
            "WHERE event_type IN ('operator_granted','operator_revoked') ORDER BY timestamp_ms")
    assert [row['event_type'] for row in rows] == ['operator_granted', 'operator_revoked']
    assert all(row['target_id'] == principal for row in rows)
    assert CUSTOMER not in json.dumps([dict(row) for row in rows])


def test_command_needs_approval_a_valid_customer_and_the_existing_key(tmp_path):
    base = ['--customer-id', CUSTOMER, '--dsn-file', 'x', '--key-file', 'y', '--key-dir', str(tmp_path)]
    with pytest.raises(SystemExit):
        tool.main(['grant'] + base)                                   # no --i-have-approval
    with pytest.raises(SystemExit):
        tool.main(['status'] + base)                                  # no owner-link.key yet: never create one
    (tmp_path / 'owner-link.key').write_text(LINK_KEY.hex())
    with pytest.raises(SystemExit):
        tool.main(['status', '--customer-id', 'someone@example.com'] + base[2:])  # not a customer id
    assert tool.owner_link_key_from(str(tmp_path)) == LINK_KEY
    with pytest.raises(SystemExit):
        tool.owner_link_key_from('relative/keys')
