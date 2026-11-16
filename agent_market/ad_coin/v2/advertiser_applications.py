"""Advertiser applications: open to anyone, approved automatically when the checks pass (user decision 11-15).

Until 11-15 only providers listed in our catalog could apply and an operator approved every application. The user
decided advertisers are not limited "except where a problem can arise", so a signed-in person applies with a
display name and, optionally, a website or a catalog page. The checks that stay:
- the name: no hidden characters, no steering or imperative wording aimed at agents (the screen ads already pass);
- the name: words of the classes we do not sell or that need a person (docs/AD_COIN_SALES_POLICY.md 5) hold it;
- the website: a public address only (check_public_url, never a private or local one).
An application that passes is approved at once; one that is held waits for an operator, who sees why. Sanctions
screening stays where money moves (each USDC payment). PM 11:5x: approval no longer brings the welcome grant, so
free coins cannot buy ads for anyone who signs up. The grant goes to an advertiser whose first USDC payment is
confirmed (welcome_after_payment) and, later, to a provider who proved ownership; others book with USDC only.
No new table: the application is a suspended advertiser record with the applicant's campaign memberships, and the
name, addresses and flags are kept in the audit log ("advertiser_applied"). Nothing here moves money.
"""

import json
import re
import unicodedata
from uuid import NAMESPACE_URL, uuid5

from .access import PLATFORM_OPERATORS_ID
from .contracts import ContractError
from .identity import Kind
from .ledger import MODEL_ASSET, identifier
from .security_guards import AuditLogger

APPLIED, APPROVED, REJECTED = "advertiser_applied", "advertiser_approved", "advertiser_rejected"
APPLICANT_CAPABILITIES = ("campaign.edit", "campaign.read", "campaign.pause", "budget.approve", "reports.read")
CATALOG = re.compile(r"https://agentconcierge\.biz/[A-Za-z0-9._~/%?=&-]{1,300}\Z")  # our catalog pages only
_NAME = re.compile(r"[^\x00-\x1f\x7f]{2,80}\Z")
_WEBSITE = re.compile(r"https://[A-Za-z0-9.-]{1,253}(:[0-9]{1,5})?(/[A-Za-z0-9._~/%?=&#+-]{0,300})?\Z")
MAX_APPLICATIONS_PER_PERSON = 5
AUTO_APPROVER = "auto-check"
from .ad_rules import RESTRICTED as _HOLD  # noqa: E402,F401 - one place for the rules (11-16)


def screen_application(name, website_url=None, *, check_url=None):
    """Flags that hold an application for a person (empty: approve at once). Raises for a private website."""
    from .ad_rules import flags as rule_flags
    flags = rule_flags("name", name)
    if website_url is not None:
        if check_url is None:
            from ...broker.discovery import check_public_url as check_url
        try:
            check_url(website_url)
        except Exception:
            raise ContractError("website_not_public", 422) from None
    return flags


def _last(store, advertiser_id, event):
    row = store.one("audit_by_target_event", (advertiser_id, event))
    return dict(row) if row else None


def apply(access, principal, *, display_name, listing_url=None, website_url=None, economy=None, check_url=None):
    """Applies, and approves at once when screen_application finds nothing (no coins: see welcome_after_payment)."""
    if principal.kind != Kind.HUMAN or principal.owner_id is None:
        raise ContractError("human_workspace_required", 403)
    name = display_name.strip() if type(display_name) is str else ""
    listing_url = listing_url.strip() if type(listing_url) is str and listing_url.strip() else None
    website_url = website_url.strip() if type(website_url) is str and website_url.strip() else None
    if (not _NAME.match(name) or (listing_url is not None and not CATALOG.match(listing_url))
            or (website_url is not None and not _WEBSITE.match(website_url))):
        raise ContractError("invalid_application", 422)
    flags = screen_application(name, website_url, check_url=check_url)
    store = access.store
    key = listing_url or website_url or ("name:" + unicodedata.normalize("NFKC", name).casefold())
    advertiser_id = str(uuid5(NAMESPACE_URL, "https://agentconcierge.biz/ad-coin/applications/"
                              + str(principal.id) + "/" + key))
    with store.atomic():
        store.lock("0:authority:" + str(principal.id))
        existing = store.one("advertiser_get", (advertiser_id,))
        if existing:
            return {"application_id": advertiser_id, "status": status_of(store, advertiser_id), "replayed": True}
        mine = int(store.one("applications_by_person", (str(principal.id), APPLIED))["n"])
        if mine >= MAX_APPLICATIONS_PER_PERSON:
            raise ContractError("application_limit_reached", 429)
        # One commercial tenant per application (a listing no longer has to be unique to one applicant).
        access.provision_advertiser(advertiser_id, str(uuid5(NAMESPACE_URL, "https://agentconcierge.biz/ad-coin/tenants/"
                                                             + advertiser_id)))
        access.set_advertiser_status(advertiser_id, "suspended")
        for capability in APPLICANT_CAPABILITIES:
            access.grant(advertiser_id, str(principal.id), capability)
        AuditLogger.log(store, APPLIED, "succeeded", actor_principal_id=str(principal.id), target_id=advertiser_id,
                        details={"display_name": name, "listing_url": listing_url or "", "website_url": website_url or "",
                                 "flags": flags})
        if flags:
            return {"application_id": advertiser_id, "status": "pending", "replayed": False, "held": True}
        access.set_advertiser_status(advertiser_id, "active")
        AuditLogger.log(store, APPROVED, "succeeded", actor_principal_id=str(principal.id), target_id=advertiser_id,
                        details={"approved_by": AUTO_APPROVER})
    return {"application_id": advertiser_id, "status": "approved", "replayed": False, "held": False,
            "welcome": WELCOME_LATER}


WELCOME_LATER = {"granted_atoms": "0", "note": "after_first_usdc_payment"}


def welcome_after_payment(store, economy, advertiser_id):
    """The welcome grant, once, for an advertiser with a confirmed USDC payment (PM 11:5x). Called where paid
    bookings and plans are submitted or listed, so a payment the worker confirmed is noticed on the next visit.
    Returns the grant, or None (already granted, nothing paid yet, or the growth budget is empty: tried again later)."""
    from .ledger import MODEL_ASSET as asset
    with store.atomic():
        if store.one("journal_get", (asset, "welcome:" + advertiser_id)) is not None:
            return None
        if not store.one("paid_bookings_table")["present"]:
            return None
        paid = any(r["state"] in ("confirmed", "served") for r in store.all("paid_bookings_by_advertiser", (advertiser_id,)))
    if not paid:
        return None
    try:
        return economy.welcome_grant(advertiser_id)
    except ContractError as exc:
        if exc.code != "insufficient_balance":
            raise
        return None


def status_of(store, advertiser_id):
    row = store.one("advertiser_get", (advertiser_id,))
    if row is None or _last(store, advertiser_id, APPLIED) is None:
        return None
    if row["status"] == "active":
        return "approved"
    return "rejected" if _last(store, advertiser_id, REJECTED) else "pending"


def pending(access, principal, *, limit=50):
    access.require_operator(principal)
    store = access.store
    import json
    with store.atomic():
        rows = store.all("advertisers_suspended", (PLATFORM_OPERATORS_ID, limit))
        items = []
        for row in rows:
            applied = _last(store, row["id"], APPLIED)
            if applied is None or _last(store, row["id"], REJECTED):
                continue
            details = json.loads(applied["details_json"])
            items.append({"application_id": row["id"], "display_name": details.get("display_name", ""),
                          "listing_url": details.get("listing_url", ""), "website_url": details.get("website_url", ""),
                          "flags": list(details.get("flags", [])), "applied_ms": int(applied["timestamp_ms"])})
    return {"items": items}


def decide(access, economy, principal, application_id, *, approve, reason=""):
    access.require_operator(principal)
    advertiser_id = identifier(application_id)
    store = access.store
    with store.atomic():
        if status_of(store, advertiser_id) != "pending":
            raise ContractError("application_not_pending", 409)
        if approve:                          # 11-16: a person never approves a name the hard rules refuse
            from .ad_rules import flags as rule_flags, require_approvable
            applied = _last(store, advertiser_id, APPLIED)
            name = json.loads(applied["details_json"]).get("display_name", "") if applied else ""
            require_approvable(rule_flags("name", name), "application_refused")
        if not approve:
            if type(reason) is not str or not 3 <= len(reason.strip()) <= 200:
                raise ContractError("invalid_reason", 422)
            AuditLogger.log(store, REJECTED, "succeeded", actor_principal_id=str(principal.id),
                            target_id=advertiser_id, details={"reason": reason.strip()})
            return {"application_id": advertiser_id, "status": "rejected"}
        access.set_advertiser_status(advertiser_id, "active")
        AuditLogger.log(store, APPROVED, "succeeded", actor_principal_id=str(principal.id), target_id=advertiser_id)
    welcome = WELCOME_LATER          # PM 11:5x: coins come after a first USDC payment, not with approval
    return {"application_id": advertiser_id, "status": "approved", "welcome": welcome,
            "already_granted": store.one("journal_get", (MODEL_ASSET, "welcome:" + advertiser_id)) is not None}
