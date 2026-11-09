"""Activity points mode: the economy v2 runs in until real value is switched on separately.

Points are earned only by activity (for example an approved ad view). They cannot be bought,
cashed out, or moved to another person, and they are redeemed only for Agent Concierge's own
benefits. Unused points expire after a period without any activity. These rules keep the
points outside stored-value and virtual-asset territory; real value stays behind
AD_COIN_REAL_VALUE_ENABLED, which is off by default.
"""

import os
from uuid import NAMESPACE_URL, uuid5

from .contracts import ContractError

REAL_VALUE_ENV = "AD_COIN_REAL_VALUE_ENABLED"
POINTS_EXPIRY_DAYS = 365  # points expire after this many days without earning or redeeming

PLATFORM_OWNER = str(uuid5(NAMESPACE_URL, "https://agentconcierge.biz/ad-coin/platform"))
EXPIRED_POINTS_ACCOUNT = str(uuid5(NAMESPACE_URL, "https://agentconcierge.biz/ad-coin/expired-points"))

# Agent Concierge's own benefits. The redemption account is the platform's, never a third party's.
BENEFITS = {
    str(uuid5(NAMESPACE_URL, "https://agentconcierge.biz/ad-coin/benefit/free-run")): "free_run_credit",
    str(uuid5(NAMESPACE_URL, "https://agentconcierge.biz/ad-coin/benefit/workspace-boost")): "workspace_boost",
}

# Account purposes that hold a person's points.
PERSONAL_PURPOSES = frozenset(("user_available", "user_locked"))

RULES = (
    "Points are earned by activity and cannot be bought.",
    "Points have no cash value and cannot be cashed out.",
    "Points cannot be sent to another person.",
    "Points are redeemed only for Agent Concierge benefits.",
    "Points expire after %d days without activity." % POINTS_EXPIRY_DAYS,
)


def real_value_enabled() -> bool:
    return os.environ.get(REAL_VALUE_ENV, "0") in ("1", "true", "True")


def economy_mode() -> str:
    return "real_value" if real_value_enabled() else "activity_points"


def points_mode() -> bool:
    return economy_mode() == "activity_points"


def require_platform_benefit(provider_id) -> None:
    """In points mode points pay only for the platform's own benefits."""
    if points_mode() and str(provider_id) not in BENEFITS:
        raise ContractError("points_redeem_platform_benefits_only", 403)


def require_single_holder(kind, account_rows) -> None:
    """In points mode one journal never moves points between two people."""
    if not points_mode():
        return
    holders = {row["owner_id"] for row in account_rows if row["purpose"] in PERSONAL_PURPOSES}
    if len(holders) > 1:
        raise ContractError("points_not_transferable", 403)


def rules() -> dict:
    return {"mode": economy_mode(), "expiry_days": POINTS_EXPIRY_DAYS, "rules": list(RULES),
            "benefits": sorted(BENEFITS.values())}


def expire_inactive_points(store, ledger, *, now_ms: int, limit: int = 200) -> int:
    """Move the balance of wallets with no activity for POINTS_EXPIRY_DAYS to the expired-points account.

    Runs only in points mode. Each expiry is one idempotent journal per wallet and day.
    """
    from .contracts import MODEL_ASSET

    if not points_mode():
        return 0
    cutoff = now_ms - POINTS_EXPIRY_DAYS * 86_400_000
    ledger.create_account(PLATFORM_OWNER, "platform_revenue", account_id=EXPIRED_POINTS_ACCOUNT)
    with store.atomic():
        rows = store.all("points_inactive_accounts", (MODEL_ASSET, cutoff, limit))
    day = now_ms // 86_400_000
    expired = 0
    for row in rows:
        amount = int(row["balance_atoms"])
        if amount <= 0:
            continue
        ledger.post("points_expiry:%s:%d" % (row["id"], day),
                    [(row["id"], str(-amount)), (EXPIRED_POINTS_ACCOUNT, str(amount))], kind="expiry")
        expired += 1
    return expired
