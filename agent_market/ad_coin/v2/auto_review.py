"""Automatic review of campaigns and agent offers; a person sees only what the checks flag (PM 11-15 12:4x).

Every campaign review used to wait for an operator, and the only operator is the user, so a paying advertiser could wait
for days. The worker now reviews what is pending:
- a campaign (name and ad text; campaigns carry no links, the ad text screen refuses them) is approved when it has no
  hidden characters, no steering or imperative wording aimed at agents and no word of a class we do not sell or that
  needs a person (docs/AD_COIN_SALES_POLICY.md 5); otherwise it stays pending with the reasons recorded;
- an agent offer (the Sponsored line agents read, with its https endpoint) is approved when its text passes the same
  screen, its endpoint resolves only to public addresses (check_public_url), the endpoint's registrable domain is at
  least 30 days old (RDAP, its own ad_review_rdap budget share, cached for 30 days) and, our own evidence first (PM 12:5x),
  the endpoint is a resource of our catalog that passed our keyless test call in the last 7 days and is not under
  security review or quarantine. An endpoint outside the catalog waits for a person. A blocklist is checked only once
  a source we may use for free and commercially is confirmed from its terms (OpenPhish's free feed forbids commercial
  use; URLhaus needs an account and a paid plan for it, 11-15). An approved offer is withdrawn on its own when its
  resource is later quarantined, put under review or fails three checks in a row (recheck_offers).
The worker daemon runs one pass every 10 minutes when AD_COIN_AUTO_REVIEW_ENABLED is on (off by default; PM switches
it in the daemon's runtime settings file), outside the hourly measurement window; it runs from the deployed release.
Approved work is decided through the operator paths (operator_review.decide, sponsored_offer.decide_offer) by an
in-process system principal with no credentials; every decision and every hold is in the audit log. An operator can
take an advertiser down at any time (takedown): the advertiser is suspended, its running campaigns pause and its
approved offers are withdrawn; paid placements that can no longer run become refunds due (a platform-side reason).
Nothing here sends our data anywhere: RDAP receives only the registrable domain of a public endpoint.
"""

import json
import logging
import os
import time
import unicodedata
from pathlib import Path
from uuid import NAMESPACE_URL, UUID, uuid5

from .contracts import ContractError
from .ledger import identifier
from .security_guards import AuditLogger

logger = logging.getLogger(__name__)
BASE = "https://agentconcierge.biz/ad-coin/"
AUTO_PRINCIPAL = str(uuid5(NAMESPACE_URL, BASE + "auto-review"))
AUTO_OWNER = str(uuid5(NAMESPACE_URL, BASE + "auto-review/owner"))
REASON_PASSED = "auto_checks_passed"
HELD_REVIEW, HELD_OFFER, TAKEDOWN = "review_held", "offer_held", "advertiser_takedown"
APPROVED_REVIEW, APPROVED_OFFER, WITHDRAWN_OFFER = "review_auto_approved", "offer_auto_approved", "offer_withdrawn"
BY = "auto_review"                    # every automatic decision says so in the audit log (PM 13:1x)
TIME_BUDGET_S = 60                    # one pass stops taking new items after this long (PM 13:1x)
MIN_DOMAIN_AGE_DAYS = 30
ROOT = Path(__file__).resolve().parents[3]
# A release folder has no gateway-data of its own; the worker runs from the repository root (as provider_budget).
STATE_DIR = Path(os.environ.get("AD_COIN_REVIEW_DIR") or (((ROOT if (ROOT / "gateway-data").is_dir() else Path.cwd())
                                                          / "gateway-data/ad-coin/review")))
RDAP_BOOTSTRAP = "https://data.iana.org/rdap/dns.json"
RDAP_CACHE_S = 30 * 86400
BLOCKLIST_MAX_AGE_S = 2 * 86400


def principal(access):
    """The system reviewer: an operator principal that exists only inside this process (no session, no token)."""
    from .access import COMMERCIAL_CAPABILITIES, HUMAN_CAPABILITIES, OPERATOR_CAPABILITY
    from .identity import Kind, Principal
    access.provision_principal(AUTO_PRINCIPAL, Kind.HUMAN, owner_id=AUTO_OWNER,
                               capabilities=HUMAN_CAPABILITIES | COMMERCIAL_CAPABILITIES | {OPERATOR_CAPABILITY})
    return Principal(UUID(AUTO_PRINCIPAL), Kind.HUMAN, 1, time.time() + 600, owner_id=UUID(AUTO_OWNER),
                     csrf_verified=True, audience="aiac-v2-model")


# ---- checks -----------------------------------------------------------------------------------------------------
def screen_words(name, text):
    """Flags for one free-text field (ad_rules: hard rules, steering or imperative wording, restricted classes)."""
    from .ad_rules import flags
    return flags(name, text if isinstance(text, str) else "")


def screen_campaign(payload):
    return screen_words("name", str(payload.get("name", ""))) + screen_words("text", str(payload.get("creative_text", "")))


def load_blocklist(directory=None, now=None):
    """(hosts, fresh) from the local blocklist files (one host or URL a line); fresh is False when none is settled."""
    from urllib.parse import urlsplit
    directory = Path(directory or STATE_DIR / "blocklists")
    now = time.time() if now is None else now
    try:
        meta = json.loads((directory / "meta.json").read_text())
    except (OSError, ValueError):
        return set(), False
    if not meta.get("sources") or now - float(meta.get("fetched_at", 0)) > BLOCKLIST_MAX_AGE_S:
        return set(), False
    hosts = set()
    for name in meta["sources"]:
        try:
            for line in (directory / (name + ".txt")).read_text(errors="replace").splitlines():
                item = line.strip().split("#", 1)[0].split()[-1:] if line.strip() else []
                if not item:
                    continue
                value = item[0].lower()
                host = urlsplit(value).hostname if "://" in value else value
                if host:
                    hosts.add(host.rstrip("."))
        except OSError:
            return set(), False
    return hosts, True


def _listed(host, hosts):
    parts = host.lower().rstrip(".").split(".")
    return any(".".join(parts[i:]) in hosts for i in range(len(parts) - 1))


def domain_age_days(url, *, now=None, fetch=None, cache_dir=None):
    """Days since the endpoint's registrable domain was registered (RDAP), or None when unknown. Cached 30 days."""
    from ...provider_budget import domain, reserve
    now = time.time() if now is None else now
    name = domain(url)
    if not name:
        return None
    cache_dir = Path(cache_dir or STATE_DIR / "rdap")
    cached = cache_dir / (name + ".json")
    try:
        hit = json.loads(cached.read_text())
        if now - float(hit["checked_at"]) < RDAP_CACHE_S:
            return None if hit["registered_at"] is None else int((now - float(hit["registered_at"])) // 86400)
    except (OSError, ValueError, KeyError):
        pass
    fetch = fetch or _get_json
    try:
        boot = cache_dir / "bootstrap.json"
        try:
            table = json.loads(boot.read_text())
            if now - float(table.get("_checked_at", 0)) > 7 * 86400:
                raise ValueError("stale")
        except (OSError, ValueError):
            ok, _ = reserve(RDAP_BOOTSTRAP, "ad_review_rdap")
            if not ok:
                return None
            table = {**fetch(RDAP_BOOTSTRAP), "_checked_at": now}
            cache_dir.mkdir(parents=True, exist_ok=True)
            boot.write_text(json.dumps(table))
        tld = name.rsplit(".", 1)[-1]
        server = next((urls[0] for tlds, urls in table.get("services", []) if tld in tlds and urls), None)
        if not server:
            return None
        lookup = server.rstrip("/") + "/domain/" + name
        ok, _ = reserve(lookup, "ad_review_rdap")              # counted per RDAP server; E6 has its own share
        if not ok:
            return None
        events = fetch(lookup).get("events", [])
        stamp = next((e.get("eventDate") for e in events if e.get("eventAction") == "registration"), None)
        registered = None
        if stamp:
            from datetime import datetime
            registered = datetime.fromisoformat(stamp.replace("Z", "+00:00")).timestamp()
        cache_dir.mkdir(parents=True, exist_ok=True)
        cached.write_text(json.dumps({"checked_at": now, "registered_at": registered}))
        return None if registered is None else int((now - registered) // 86400)
    except Exception:                                    # unknown age: a person looks
        logger.info("RDAP lookup failed for %s", name, exc_info=True)
        return None


def _get_json(url):
    import httpx
    with httpx.Client(timeout=8.0, follow_redirects=False) as client:
        response = client.get(url, headers={"Accept": "application/rdap+json, application/json",
                                            "User-Agent": "AgentValCon-ad-review/1"})
        response.raise_for_status()
        if len(response.content) > 2 * 1024 * 1024:
            raise ValueError("too large")
        return response.json()


CATALOG_TRIAL_DAYS = 7
WITHDRAW_AFTER_FAILURES = 3
_RESOURCE_BY_URL = "SELECT id, name, kind, source, url FROM resources WHERE url=? OR key=?"   # registered (dashboard)


def catalog_facts(app_store, endpoint):
    """Our catalog's record of the endpoint (two registered reads), or None when it is not in the catalog."""
    if app_store is None or not endpoint:
        return None
    for url in dict.fromkeys((endpoint, endpoint.rstrip("/"), endpoint.rstrip("/") + "/")):
        rows = app_store.query(_RESOURCE_BY_URL, (url, url))
        if rows:
            return app_store.resource(int(dict(rows[0])["id"]))
    return None


def catalog_flags(facts, *, now=None):
    """Flags from our own evidence (PM 12:5x): in the catalog, a keyless test call passed within 7 days, not under
    security review or quarantine."""
    now = time.time() if now is None else now
    if not facts:
        return ["endpoint:not_in_catalog"]
    flags = []
    if (facts.get("eval_security") or "") in ("quarantine", "review"):
        flags.append("endpoint:security_" + facts["eval_security"])
    try:
        trial = json.loads(facts.get("trial_info") or "null") or {}
    except (TypeError, ValueError):
        trial = {}
    try:
        at = float(trial.get("at")) if trial.get("at") is not None else None
    except (TypeError, ValueError):
        at = None
    if at is not None and at > 1e12:
        at = at / 1000                                   # milliseconds
    if not (trial.get("ok") is True and at is not None and now - at <= CATALOG_TRIAL_DAYS * 86400):
        flags.append("endpoint:no_recent_test_success")
    return flags


def screen_offer(offer, *, advertiser_name, blocklist=None, age_days=None, public=None, catalog=None):
    """Flags for an agent offer: its text, its endpoint (public, in our catalog with a recent test success, domain old
    enough, on no confirmed blocklist)."""
    from urllib.parse import urlsplit
    from .sponsored_offer import advertiser_name_ok, public_endpoint
    flags = [] if advertiser_name_ok(advertiser_name) else ["advertiser_name"]
    for field in ("tool", "line", "price", "free_trial", "sla"):
        flags += screen_words(field, str(offer.get(field, "") or ""))
    endpoint = str(offer.get("endpoint", ""))
    host = urlsplit(endpoint).hostname or ""
    if urlsplit(endpoint).scheme != "https" or not host:
        return flags + ["endpoint:https_url_required"]
    if not (public or public_endpoint)(endpoint):
        flags.append("endpoint:not_public")
    hosts, fresh = blocklist if blocklist is not None else load_blocklist()
    if fresh and _listed(host, hosts):               # only a confirmed source counts (PM 12:5x); none yet
        flags.append("endpoint:blocklisted")
    flags += catalog(endpoint) if catalog is not None else ["endpoint:not_in_catalog"]
    age = (age_days or domain_age_days)(endpoint)
    if age is None:
        flags.append("endpoint:domain_age_unknown")
    elif age < MIN_DOMAIN_AGE_DAYS:
        flags.append("endpoint:young_domain")
    return flags


# ---- the worker step ---------------------------------------------------------------------------------------------
def _hold_once(store, event, target, flags):
    with store.atomic():
        last = store.one("audit_by_target_event", (target, event))
        if last and json.loads(last["details_json"] or "{}").get("flags") == flags:
            return False
        AuditLogger.log(store, event, "succeeded", actor_principal_id=AUTO_PRINCIPAL, target_id=target,
                        details={"flags": flags, "by": BY})
    return True


def flags_of(store, event, target):
    """The reasons the checks held a review or offer (shown to the operator)."""
    row = store.one("audit_by_target_event", (target, event))
    try:
        return list(json.loads(row["details_json"]).get("flags", [])) if row else []
    except (TypeError, ValueError):
        return []


def _approved(store, event, target):
    with store.atomic():
        AuditLogger.log(store, event, "succeeded", actor_principal_id=AUTO_PRINCIPAL, target_id=target,
                        details={"by": BY, "reason": REASON_PASSED})


def run(commercial, *, limit=20, screen=None, app_store=None, budget_s=TIME_BUDGET_S, clock=time.monotonic):
    """One pass over pending reviews and offers, then the recheck of approved offers. Returns counts; never raises
    for one bad item. app_store: the application catalog store (registered reads only)."""
    from . import operator_review
    from .sponsored_offer import campaign_name, decide_offer
    store, access = commercial.store, commercial.access
    me = principal(access)
    done = {"approved_reviews": 0, "held_reviews": 0, "approved_offers": 0, "held_offers": 0, "errors": 0,
            "out_of_time": 0}
    deadline = clock() + budget_s

    def out_of_time():
        if clock() > deadline:
            done["out_of_time"] = 1                      # the rest waits for the next pass
            return True
        return False
    with store.atomic():
        reviews = list(store.all("reviews_pending_for_operator", (limit,)))
    for row in reviews:
        if out_of_time():
            break
        try:
            flags = screen_campaign(json.loads(row["payload_json"]))
            if flags:
                done["held_reviews"] += _hold_once(store, HELD_REVIEW, row["id"], flags)
                continue
            operator_review.decide(commercial, me, row["id"], verdict="eligible", reason_code=REASON_PASSED)
            _approved(store, APPROVED_REVIEW, row["id"])
            done["approved_reviews"] += 1
        except Exception:
            done["errors"] += 1
            logger.warning("Automatic review of %s failed; it is tried again", row["id"], exc_info=True)
    with store.atomic():
        offers = list(store.all("sponsored_offers_pending", (limit,))) if store.one("sponsored_offers_table")["present"] else []
    blocklist = load_blocklist()
    for row in offers:
        if out_of_time():
            break
        try:
            with store.atomic():
                name = campaign_name(store, store.one("campaign_get", (row["campaign_id"],)) or {})
            flags = (screen or screen_offer)(json.loads(row["offer_json"]), advertiser_name=name, blocklist=blocklist,
                                             catalog=lambda url: catalog_flags(catalog_facts(app_store, url)))
            if flags:
                done["held_offers"] += _hold_once(store, HELD_OFFER, row["campaign_id"], flags)
                continue
            decide_offer(store, access, me, row["campaign_id"], approve=True)
            _approved(store, APPROVED_OFFER, row["campaign_id"])
            done["approved_offers"] += 1
        except Exception:
            done["errors"] += 1
            logger.warning("Automatic review of offer %s failed; it is tried again", row["campaign_id"], exc_info=True)
    try:
        done["withdrawn_offers"] = 0 if out_of_time() else recheck_offers(commercial, app_store=app_store, limit=200)
    except Exception:
        done["errors"] += 1
        logger.warning("Approved-offer recheck failed; it runs again next pass", exc_info=True)
    return done


def recheck_offers(commercial, *, app_store=None, limit=200, now_ms=None):
    """Withdraw approved offers whose catalog resource is now quarantined, under security review or failing its
    checks (PM 12:5x). An offer outside the catalog was approved by a person and is left to them."""
    store = commercial.store
    now_ms = int(time.time() * 1000) if now_ms is None else int(now_ms)
    with store.atomic():
        if not store.one("sponsored_offers_table")["present"]:
            return 0
        rows = list(store.all("sponsored_offers_approved", (limit,)))
    withdrawn = 0
    for row in rows:
        facts = catalog_facts(app_store, str(json.loads(row["offer_json"]).get("endpoint", "")))
        if facts is None:
            continue
        security = facts.get("eval_security") or ""
        why = ("security_" + security if security in ("quarantine", "review")
               else "failing_checks" if int(facts.get("consecutive_failures") or 0) >= WITHDRAW_AFTER_FAILURES else None)
        if why is None:
            continue
        with store.atomic():
            changed = store.execute("sponsored_offer_withdraw", ("auto: " + why, now_ms, AUTO_PRINCIPAL,
                                                                 row["campaign_id"])).rowcount or 0
            if changed:
                AuditLogger.log(store, WITHDRAWN_OFFER, "succeeded", actor_principal_id=AUTO_PRINCIPAL,
                                target_id=row["campaign_id"], details={"reason": why, "by": BY})
        withdrawn += changed
    return withdrawn


# ---- a person looks again within 24 hours (PM 11-17, condition (b) for switching automatic review on) --------------
CHECKED = "auto_approval_checked"
RECHECK_HOURS = 24
RECHECK_LIST_DAYS = 7
_DAY_MS = 86_400_000


def _advertiser_of(store, event, target):
    if event == APPROVED_REVIEW:
        row = store.one("review_get", (target,))
        return (row["advertiser_id"], row["campaign_id"]) if row else (None, None)
    row = store.one("campaign_get", (target,))
    return (row["advertiser_id"], target) if row else (None, target)


def approvals_to_check(commercial, operator, *, now_ms=None):
    """Automatic approvals of the last RECHECK_LIST_DAYS days that no person has looked at yet, oldest first, each
    with the time a person should have looked by (approval + RECHECK_HOURS) and whether that time has passed. A wrong
    one is taken down with the existing takedown (paid placements that cannot run become refunds due; the refund
    transfer is made by the user)."""
    commercial.access.require_operator(operator)
    now_ms = int(time.time() * 1000) if now_ms is None else int(now_ms)
    store, items = commercial.store, []
    with store.atomic():
        for row in store.all("audit_auto_approvals_since", (now_ms - RECHECK_LIST_DAYS * _DAY_MS,)):
            if store.one("audit_by_target_event", (row["id"], CHECKED)) is not None:
                continue
            advertiser_id, campaign_id = _advertiser_of(store, row["event_type"], row["target_id"])
            due = int(row["timestamp_ms"]) + RECHECK_HOURS * 3_600_000
            items.append({"approval_id": row["id"], "kind": "campaign" if row["event_type"] == APPROVED_REVIEW else "agent_offer",
                          "target_id": row["target_id"], "advertiser_id": advertiser_id, "campaign_id": campaign_id,
                          "approved_ms": int(row["timestamp_ms"]), "check_by_ms": due, "overdue": now_ms > due})
    return {"items": items, "check_within_hours": RECHECK_HOURS,
            "take_down": "POST /api/ad-coin/v2/admin/advertisers/{advertiser_id}/takedown"}


def mark_checked(commercial, operator, approval_id, *, now_ms=None):
    """A person looked at one automatic approval and kept it. Idempotent; only automatic approvals can be marked."""
    commercial.access.require_operator(operator)
    approval_id = identifier(approval_id)
    store = commercial.store
    with store.atomic():
        row = store.one("audit_by_id", (approval_id,))
        if row is None or row["event_type"] not in (APPROVED_REVIEW, APPROVED_OFFER) or row["actor_principal_id"] != AUTO_PRINCIPAL:
            raise ContractError("unknown_resource", 404)
        if store.one("audit_by_target_event", (approval_id, CHECKED)) is None:
            AuditLogger.log(store, CHECKED, "succeeded", actor_principal_id=str(operator.id), target_id=approval_id,
                            now_ms=now_ms)
    return {"approval_id": approval_id, "checked": True}


def takedown(commercial, operator, advertiser_id, *, reason, now_ms=None):
    """Operator: stop everything an advertiser shows, now (suspend, pause running campaigns, withdraw offers)."""
    access, store = commercial.access, commercial.store
    access.require_operator(operator)
    advertiser_id = identifier(advertiser_id)
    if not isinstance(reason, str) or not 3 <= len(reason.strip()) <= 200:
        raise ContractError("invalid_reason", 422)
    now_ms = int(time.time() * 1000) if now_ms is None else int(now_ms)
    paused, withdrawn = [], 0
    with store.atomic():
        if store.one("advertiser_get", (advertiser_id,)) is None:
            raise ContractError("unknown_resource", 404)
        access.set_advertiser_status(advertiser_id, "suspended")
        for campaign in store.all("ui_campaigns", (advertiser_id, "")):
            if campaign["state"] == "active":
                store.lock("2:campaign:" + campaign["id"])
                commercial._pause(commercial._campaign(campaign["id"], True))
                paused.append(campaign["id"])
            if store.one("sponsored_offers_table")["present"]:
                withdrawn += store.execute("sponsored_offer_withdraw", (reason.strip(), now_ms, str(operator.id),
                                                                        campaign["id"])).rowcount or 0
        # Paid placements from today on can no longer run for a platform-side reason: their refunds are due now
        # (the user sends refunds by hand; the operations watch tells PM the count and total, PM 12:5x).
        refunds, refund_units = [], 0
        if store.one("paid_bookings_table")["present"]:
            today = now_ms - now_ms % 86_400_000
            for booking in store.all("paid_bookings_by_advertiser", (advertiser_id,)):
                if booking["state"] == "confirmed" and int(booking["day_ms"]) >= today:
                    if store.execute("paid_booking_operator_set", ("refund_due", None, booking["id"], "confirmed")).rowcount:
                        refunds.append(booking["id"])
                        refund_units += int(booking["amount_units"])
        AuditLogger.log(store, TAKEDOWN, "succeeded", actor_principal_id=str(operator.id), target_id=advertiser_id,
                        details={"reason": reason.strip(), "paused": paused, "offers_withdrawn": withdrawn,
                                 "refunds_due": refunds, "refund_units": str(refund_units)})
    return {"advertiser_id": advertiser_id, "status": "suspended", "paused_campaigns": paused,
            "offers_withdrawn": withdrawn, "refunds_due": len(refunds), "refund_units": str(refund_units)}
