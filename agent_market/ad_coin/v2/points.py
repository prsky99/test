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

# Points -> workspace credits (docs/AD_COIN_BENEFITS.md, approved 11-10). Code constants, stated in the public terms.
POINTS_PER_WORKSPACE_CREDIT = 10
MAX_CREDITS_PER_EXCHANGE = 10
MAX_CREDITS_PER_MONTH = 50

# Account purposes that hold a person's points, and an advertiser's coins.
PERSONAL_PURPOSES = frozenset(("user_available", "user_locked"))
ADVERTISER_PURPOSES = frozenset(("advertiser_available",))

# Coin economy (docs/AD_COIN_COIN_ECONOMY.md). Caps are code constants on purpose, not settings.
ATOMS_PER_COIN = 1_000_000
ISSUANCE_MONTHLY_CAP_ATOMS = 100_000 * ATOMS_PER_COIN        # new coins the platform may issue per UTC month
PROVIDER_REWARD_MONTHLY_CAP_ATOMS = 1_000 * ATOMS_PER_COIN   # coins one provider may receive per UTC month
WELCOME_GRANT_ATOMS = 100 * ATOMS_PER_COIN                   # one-time grant to a reviewed, active advertiser
OPERATOR_GRANT_MAX_ATOMS = 1_000 * ATOMS_PER_COIN            # largest single manual grant by platform staff
ISSUANCE_ACCOUNT = str(uuid5(NAMESPACE_URL, "https://agentconcierge.biz/ad-coin/issuance"))
GROWTH_ACCOUNT = str(uuid5(NAMESPACE_URL, "https://agentconcierge.biz/ad-coin/growth-budget"))
REVENUE_ACCOUNT = str(uuid5(NAMESPACE_URL, "https://agentconcierge.biz/ad-coin/coin-revenue"))
ECONOMY_KINDS = frozenset(("issuance", "grant", "sponsored_purchase", "growth_reward"))

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
    """In points mode coins never move between two people, or from a person to an advertiser."""
    if not points_mode():
        return
    holders = {row["owner_id"] for row in account_rows if row["purpose"] in PERSONAL_PURPOSES}
    if len(holders) > 1:
        raise ContractError("points_not_transferable", 403)
    if holders and any(row["purpose"] in ADVERTISER_PURPOSES for row in account_rows):
        raise ContractError("points_not_transferable", 403)


def require_issuance_shape(changes) -> None:
    """Issuance moves new coins from the issuance account into the growth budget, nowhere else."""
    if set(changes) != {ISSUANCE_ACCOUNT, GROWTH_ACCOUNT} or changes[GROWTH_ACCOUNT] <= 0:
        raise ContractError("invalid_issuance", 403)


def month_start_ms(now_ms: int) -> int:
    import datetime

    moment = datetime.datetime.fromtimestamp(now_ms / 1000, tz=datetime.timezone.utc)
    return int(moment.replace(day=1, hour=0, minute=0, second=0, microsecond=0).timestamp() * 1000)


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


def ensure_platform_accounts(ledger) -> None:
    ledger.create_account(PLATFORM_OWNER, "external_clearing", account_id=ISSUANCE_ACCOUNT)
    ledger.create_account(PLATFORM_OWNER, "platform_revenue", account_id=GROWTH_ACCOUNT)
    ledger.create_account(PLATFORM_OWNER, "platform_revenue", account_id=REVENUE_ACCOUNT)


def platform_holdings(ledger) -> dict:
    """Coins the platform holds (growth budget + coin revenue) and coins issued so far, in atoms.

    Read only. The x402 test-payment rule (11-10) compares this holding against 100,000 coins."""
    from .contracts import ContractError

    def balance(account_id):
        try:
            return int(ledger.account(account_id)["balance_atoms"])
        except ContractError as exc:
            if exc.code != "unknown_account":
                raise
            return 0  # accounts appear with the first issuance

    growth, revenue = balance(GROWTH_ACCOUNT), balance(REVENUE_ACCOUNT)
    return {"growth_budget_atoms": str(growth), "coin_revenue_atoms": str(revenue),
            "platform_holdings_atoms": str(growth + revenue), "issued_atoms": str(-balance(ISSUANCE_ACCOUNT)),
            "atoms_per_coin": ATOMS_PER_COIN}


def issue(ledger, amount_atoms: int, *, reason: str):
    """Issue new coins into the growth budget, within ISSUANCE_MONTHLY_CAP_ATOMS (checked by the ledger)."""
    ensure_platform_accounts(ledger)
    return ledger.post("issuance:" + reason, [(ISSUANCE_ACCOUNT, str(-int(amount_atoms))),
                                              (GROWTH_ACCOUNT, str(int(amount_atoms)))], kind="issuance")
