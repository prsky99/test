"""Give or take the AI AD Coin v2 operator capability (platform.operate) for one site customer.

Server only: there is no public API for this. The customer must have signed in and opened the v2
workspace once, so their v2 person exists; the v2 id is derived from the customer id with the
owner-link key in the key folder (the same key the frontend uses). Every change is written to the
v2 audit log without the customer id.

  status  show whether the customer's v2 person exists and is an operator (read only)
  grant   add platform.operate          (changes the production database: --i-have-approval)
  revoke  remove platform.operate       (changes the production database: --i-have-approval)

  .venv/bin/python -m scripts.ad_coin_grant_operator status --customer-id cu_... \\
      --dsn-file <dsn file> --key-file <workflow key file> --key-dir <AD_COIN_V2_KEY_DIR>

One database connection. No ledger journal, no new table; the first grant adds the reserved
operators record (a suspended advertiser with an empty account).
"""
import argparse
import json
import os
import re
import sys

ACTIONS = ("status", "grant", "revoke")
CUSTOMER = re.compile(r"cu_[0-9a-f]{32}\Z")


def principal_id_for(customer_id: str, owner_link_key: bytes) -> str:
    from agent_market.ad_coin.v2.live_auth import linked_id
    if type(customer_id) is not str or not CUSTOMER.match(customer_id):
        raise ValueError("customer id must look like cu_ followed by 32 hex characters")
    return linked_id(owner_link_key, "adc2-principal:", customer_id)


def owner_link_key_from(key_dir: str) -> bytes:
    """Read the existing key; never create one here (a new key would point at nobody)."""
    path = os.path.join(key_dir or "", "owner-link.key")
    if not key_dir or not os.path.isabs(key_dir) or not os.path.isfile(path):
        raise SystemExit("owner-link.key not found in the absolute --key-dir the frontend uses")
    with open(path, "rb") as handle:
        key = bytes.fromhex(handle.read().decode("ascii").strip())
    if len(key) != 32:
        raise SystemExit("owner-link.key is not a 32-byte key")
    return key


def ensure_platform_record(store):
    """The reserved operators record: a suspended advertiser that only carries memberships."""
    from agent_market.ad_coin.v2.access import PLATFORM_OPERATORS_ID, Access
    access = Access(store)
    row = store.one("advertiser_get", (PLATFORM_OPERATORS_ID,))
    if row is None:
        access.provision_advertiser(PLATFORM_OPERATORS_ID, PLATFORM_OPERATORS_ID)
        row = store.one("advertiser_get", (PLATFORM_OPERATORS_ID,))
    if row["status"] != "suspended":
        access.set_advertiser_status(PLATFORM_OPERATORS_ID, "suspended")


def run(store, principal_id: str, action: str) -> dict:
    """status, grant or revoke on a v2 store; idempotent. Principals are immutable, so the
    operator capability is an active membership of the reserved platform operators record."""
    from agent_market.ad_coin.v2.access import OPERATOR_CAPABILITY, PLATFORM_OPERATORS_ID
    from agent_market.ad_coin.v2.security_guards import AuditLogger, EventType
    with store.atomic():
        store.lock("0:authority:" + principal_id)
        row = store.one("principal_get", (principal_id,))
        if row is None or row["kind"] != "human":
            return {"principal_exists": False, "operator": False,
                    "hint": "the customer must sign in and open /ad-coin/v2 once first"}
        member = store.one("membership_get", (PLATFORM_OPERATORS_ID, principal_id, OPERATOR_CAPABILITY))
        before = bool(member and member["active"]) or OPERATOR_CAPABILITY in json.loads(row["capabilities_json"])
        if action == "status":
            return {"principal_exists": True, "operator": before}
        if action == "grant" and not before:
            ensure_platform_record(store)
            store.execute("membership_grant", (PLATFORM_OPERATORS_ID, principal_id, OPERATOR_CAPABILITY))
        elif action == "revoke" and member and member["active"]:
            store.execute("membership_revoke", (PLATFORM_OPERATORS_ID, principal_id, OPERATOR_CAPABILITY))
        member = store.one("membership_get", (PLATFORM_OPERATORS_ID, principal_id, OPERATOR_CAPABILITY))
        after = bool(member and member["active"]) or OPERATOR_CAPABILITY in json.loads(row["capabilities_json"])
        if after != before:
            AuditLogger.log(store, EventType.OPERATOR_GRANTED if after else EventType.OPERATOR_REVOKED,
                            "succeeded", target_id=principal_id, details={"via": "server_script"})
        return {"principal_exists": True, "operator": after, "changed": after != before}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("action", choices=ACTIONS)
    parser.add_argument("--customer-id", required=True)
    parser.add_argument("--dsn-file", required=True)
    parser.add_argument("--key-file", required=True, help="the application workflow key file")
    parser.add_argument("--key-dir", default=os.environ.get("AD_COIN_V2_KEY_DIR", ""))
    parser.add_argument("--i-have-approval", action="store_true",
                        help="Required for grant and revoke: the user approved this change")
    args = parser.parse_args(argv)
    if args.action != "status" and not args.i_have_approval:
        parser.error(args.action + " changes the production database; pass --i-have-approval only after approval")
    try:
        principal_id = principal_id_for(args.customer_id, owner_link_key_from(args.key_dir))
    except ValueError as exc:
        parser.error(str(exc))
    from agent_market.ad_coin.v2.live_service import store_from_application
    from scripts.ad_coin_v2_migrate import _connect
    runtime = _connect(args)
    try:
        os.environ["AD_COIN_V2_POOL_MAXIMUM"] = "1"
        store = store_from_application(runtime.store)
        try:
            result = run(store, principal_id, args.action)
        finally:
            store.close()
        print(json.dumps({"action": args.action, **result}, sort_keys=True))
    finally:
        runtime.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
