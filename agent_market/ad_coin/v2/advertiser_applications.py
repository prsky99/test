"""Advertiser applications and operator approval (PM step 2, first criterion c: catalog providers only).

A signed-in person applies with a display name and the Agent Concierge catalog page of the agent or
MCP server they provide. No new table: the application is a suspended advertiser record (id derived
from the applicant and the listing) with the applicant's campaign memberships, and the name and
listing are kept in the audit log ("advertiser_applied"). A platform operator checks the listing and
approves (the advertiser becomes active and receives the welcome grant when the growth budget allows)
or rejects (it stays suspended). Nothing here moves money; the welcome grant is the existing one.
"""

import re
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
MAX_APPLICATIONS_PER_PERSON = 5


def _last(store, advertiser_id, event):
    row = store.one("audit_by_target_event", (advertiser_id, event))
    return dict(row) if row else None


def apply(access, principal, *, display_name, listing_url):
    if principal.kind != Kind.HUMAN or principal.owner_id is None:
        raise ContractError("human_workspace_required", 403)
    name = display_name.strip() if type(display_name) is str else ""
    if not _NAME.match(name) or type(listing_url) is not str or not CATALOG.match(listing_url):
        raise ContractError("invalid_application", 422)
    store = access.store
    advertiser_id = str(uuid5(NAMESPACE_URL, "https://agentconcierge.biz/ad-coin/applications/"
                              + str(principal.id) + "/" + listing_url))
    with store.atomic():
        store.lock("0:authority:" + str(principal.id))
        existing = store.one("advertiser_get", (advertiser_id,))
        if existing:
            return {"application_id": advertiser_id, "status": status_of(store, advertiser_id), "replayed": True}
        mine = int(store.one("applications_by_person", (str(principal.id), APPLIED))["n"])
        if mine >= MAX_APPLICATIONS_PER_PERSON:
            raise ContractError("application_limit_reached", 429)
        access.provision_advertiser(advertiser_id, str(uuid5(NAMESPACE_URL, listing_url)))
        access.set_advertiser_status(advertiser_id, "suspended")
        for capability in APPLICANT_CAPABILITIES:
            access.grant(advertiser_id, str(principal.id), capability)
        AuditLogger.log(store, APPLIED, "succeeded", actor_principal_id=str(principal.id), target_id=advertiser_id,
                        details={"display_name": name, "listing_url": listing_url})
    return {"application_id": advertiser_id, "status": "pending", "replayed": False}


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
                          "listing_url": details.get("listing_url", ""), "applied_ms": int(applied["timestamp_ms"])})
    return {"items": items}


def decide(access, economy, principal, application_id, *, approve, reason=""):
    access.require_operator(principal)
    advertiser_id = identifier(application_id)
    store = access.store
    with store.atomic():
        if status_of(store, advertiser_id) != "pending":
            raise ContractError("application_not_pending", 409)
        if not approve:
            if type(reason) is not str or not 3 <= len(reason.strip()) <= 200:
                raise ContractError("invalid_reason", 422)
            AuditLogger.log(store, REJECTED, "succeeded", actor_principal_id=str(principal.id),
                            target_id=advertiser_id, details={"reason": reason.strip()})
            return {"application_id": advertiser_id, "status": "rejected"}
        access.set_advertiser_status(advertiser_id, "active")
        AuditLogger.log(store, APPROVED, "succeeded", actor_principal_id=str(principal.id), target_id=advertiser_id)
    try:
        grant = economy.welcome_grant(advertiser_id)
        welcome = {"granted_atoms": grant["atoms"]}
    except ContractError as exc:
        if exc.code != "insufficient_balance":
            raise
        welcome = {"granted_atoms": "0", "note": "growth_budget_empty"}  # approve now, grant after issuance
    return {"application_id": advertiser_id, "status": "approved", "welcome": welcome,
            "already_granted": store.one("journal_get", (MODEL_ASSET, "welcome:" + advertiser_id)) is not None}
