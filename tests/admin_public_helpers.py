"""Isolated legacy acceptance helpers for reviewed public changes."""

import json
from agent_market.gateway.admin_auth import session_reference
from agent_market.workspace_admin_events import migrate
from tests.test_admin_reviewed_commands import act


def prepare(store, headers):
    migrate(store, b"synthetic-public-integration-key32")
    raw = next(v[7:] for k, v in headers.items() if k.lower() == "authorization")
    with store.tx() as db:
        db.execute(
            "UPDATE admin_users SET active=0 WHERE role='superadmin' AND id!=(SELECT user_id FROM admin_sessions WHERE token=?)",
            (session_reference(raw),),
        )


def approved(client, headers, response):
    assert response.status_code == 202, response.text
    result = act(client, headers, response.json()["review"], acknowledge=True)
    assert result.status_code == 200, result.text
    item = result.json()["item"]
    assert item["status"] == "applied", result.text
    return (
        item["result"]
        if isinstance(item["result"], dict)
        else json.loads(item["result"])
    )
