"""Verified Sponsored Offer: the one sponsored slot agents read (reports/agent-ad-strategy-2026-11-14, (A) and (B)).

An agent-facing response (MCP, A2A, REST) may carry one `sponsored` object, always after the organic results and
never inside them. The advertiser fills fixed fields only; one free line of at most 120 characters must pass the
instruction and injection screen. We attach independent facts (grade, latest test report score, link and
signature, data time, 7-day health) that ads cannot change, and show them even when they are low.

This module holds the schema, the screen, the sensitive-topic rule and the "why shown" line (no opt-out: ads are
always shown, user 11-15). It never
reads or writes judging data: facts come from a reader the response surface passes in (tests/test_ad_neutrality.py).
"""
import json
import re
import time
import unicodedata
from urllib.parse import urlsplit

from .contracts import ContractError
from .ledger import identifier

PREFIX = "Sponsored: "
DISCLOSURE_URL = "https://agentconcierge.biz/advertise"
LINE_LIMIT = 120
FIELDS = {"tool": 80, "endpoint": 300, "price": 80, "free_trial": 120, "sla": 80, "line": LINE_LIMIT}
REQUIRED = ("tool", "endpoint", "line")
FACT_KEYS = ("grade", "report_score", "report_url", "report_signature", "data_at", "health_7d")

# Site task categories where no ad is attached (B): medical, legal and financial advice topics.
SENSITIVE_SITE_CATEGORIES = frozenset({"health_science", "public_legal", "finance_crypto", "trading_derivatives"})
SENSITIVE_WORDS = re.compile(
    r"\b(diagnos\w*|symptom\w*|medication|dosage|prescri\w*|therapy|suicid\w*|self[- ]harm|pregnan\w*|"
    r"lawsuit|legal advice|attorney|lawyer|immigration|visa status|"
    r"invest(ment|ing)? advice|tax advice|loan|mortgage|bankrupt\w*|debt relief|stock tips?|"
    r"gambl\w*|betting)\b", re.I)

# The steering and imperative rules live in ad_rules (one place for every advertising text rule, 11-16).
from .ad_rules import IMPERATIVE_START as _IMPERATIVE_START, STEERING as _STEERING_RE  # noqa: E402
# R33: what agents read is printable ASCII only (no look-alike letters, no invisible or direction characters), and an
# endpoint path is plain characters with a bounded length.
_ASCII = re.compile(r"[\x20-\x7e]*\Z")
_ENDPOINT_PATH = re.compile(r"/?[A-Za-z0-9._~/-]{0,200}\Z")
NAME_LIMIT = 100


class OfferError(ValueError):
    def __init__(self, problems):
        super().__init__(", ".join(problems))
        self.problems = problems


def _clean(text):
    """Reject hidden characters outright (zero-width, bidi, control); return the NFKC form."""
    if any(unicodedata.category(c) in ("Cc", "Cf", "Co", "Cs") for c in text):
        raise OfferError(["hidden_characters"])
    return unicodedata.normalize("NFKC", text).strip()


def screen_text(name, text):
    """Problems with one free-text field: steering the agent, imperative opening, links or markup (ad_rules)."""
    from .ad_rules import steering_flags
    return steering_flags(name, text)


def agent_text_problems(name, text):
    """Problems with text that agents read verbatim (R33): non-ASCII, steering, imperative opening, links, markup."""
    from .ad_rules import flags, hard
    problems = [] if _ASCII.match(text) else [name + ":not_ascii"]
    # 11-16: the hard rules (injection, self-vouching, wallet requests, hidden markup) apply to agent text too
    return problems + screen_text(name, text) + [f for f in hard(flags(name, text)) if f not in problems]


def advertiser_name_ok(name):
    """The advertiser name opens the agent line ('Sponsored: <name> ...'), so it passes the same screen (R33)."""
    return isinstance(name, str) and 0 < len(name) <= NAME_LIMIT and not agent_text_problems("advertiser", name)


def campaign_name(store, campaign):
    """The name an ad shows, from the campaign's current revision."""
    revision = store.one("revision_get", (campaign["current_revision_id"],)) if campaign.get("current_revision_id") else None
    try:
        return str(json.loads(revision["payload_json"]).get("name", "")) if revision else ""
    except (TypeError, ValueError):
        return ""


def preview_line(name, offer, category="<task category>", region="<region>"):
    """The text line agents will read for this offer, for the operator's review (R33). Facts are added at serving."""
    from ...concierge.ad_slot import line
    return line(agent_block({"advertiser": name}, offer, category=category, region=region))


def validate_offer(raw):
    """The advertiser's offer as stored: only the fixed fields, each within its limit and screened. Raises OfferError."""
    if not isinstance(raw, dict):
        raise OfferError(["not_an_object"])
    unknown = sorted(set(raw) - set(FIELDS))
    problems = ["unknown_field:" + k for k in unknown]
    offer = {}
    for name, limit in FIELDS.items():
        value = raw.get(name, "")
        if value is None:
            value = ""
        if not isinstance(value, str):
            problems.append(name + ":not_text")
            continue
        try:
            value = _clean(value)
        except OfferError as error:
            problems += [name + ":" + p for p in error.problems]
            continue
        if len(value) > limit:
            problems.append(name + ":too_long")
        if name in REQUIRED and not value:
            problems.append(name + ":required")
        if name == "endpoint" and value:
            parts = urlsplit(value)
            if parts.scheme != "https" or not parts.hostname or parts.username or parts.password or parts.query \
                    or parts.fragment or not _ASCII.match(value):
                problems.append("endpoint:https_url_required")
            elif not _ENDPOINT_PATH.match(parts.path or ""):
                problems.append("endpoint:path_characters")
        elif value:
            problems += agent_text_problems(name, value)
        offer[name] = value
    if problems:
        raise OfferError(problems)
    return offer


VARY = "CF-IPCountry"     # the only header that changes a Sponsored answer (ads always on, user 11-15)


def sensitive(site_category="", text=""):
    """True for topics that never carry an ad: sensitive site categories, or advice-seeking words in the task."""
    return site_category in SENSITIVE_SITE_CATEGORIES or bool(text and SENSITIVE_WORDS.search(text))


def why_shown(category, region):
    return "Booked for the %s task category in %s; it does not change the results above." % (category, region)


def facts_block(facts):
    """Independent facts exactly as the reader returned them (low values included); missing ones are null."""
    facts = facts or {}
    return {key: facts.get(key) for key in FACT_KEYS} | {"independent": True,
                                                       "note": "Measured by AgentValCon; advertising cannot change it."}


def card_line(text, limit=LINE_LIMIT):
    """The reviewed card text as one agent line: whitespace folded, cut at a word boundary within LIMIT."""
    text = " ".join(str(text or "").split())
    if len(text) <= limit:
        return text
    cut = text[:limit - 1].rsplit(" ", 1)[0].rstrip(" ,;:-")
    return (cut or text[:limit - 1]) + "\u2026"


def agent_block(card, offer, *, category, region, facts=None, paid_by=None):
    """The `sponsored` object for agent-facing responses, built from a booked card and, when there is one, its approved
    offer. PM 11-18 19:28 (A): without an approved offer the line is the card's own reviewed text and `offer` is null,
    so a booked advertiser appears in necklace, MCP and A2A answers too; the offer only adds the tool to call."""
    line = offer["line"] if offer else card_line(card.get("text"))
    return {"label": "Sponsored", "text": PREFIX + line, "advertiser": card["advertiser"],
            "paid_by": paid_by or card["advertiser"], "why_shown": why_shown(category, region),
            "disclosure_url": DISCLOSURE_URL,
            "offer": {k: offer.get(k, "") for k in ("tool", "endpoint", "price", "free_trial", "sla")} if offer else None,
            "facts": facts_block(facts)}


# ---- storage (ad_coin_v2 schema, created by `scripts.ad_coin_v2_migrate migrate-agent-ads` after approval) ----

OFFER_STATEMENTS = (
    "CREATE TABLE IF NOT EXISTS adc2_sponsored_offers (campaign_id TEXT PRIMARY KEY REFERENCES adc2_campaigns(id), "
    "advertiser_id TEXT NOT NULL REFERENCES adc2_advertisers(id), offer_json TEXT NOT NULL, "
    "state TEXT NOT NULL CHECK (state IN ('pending','approved','rejected')), reason TEXT, "
    "submitted_ms BIGINT NOT NULL, decided_ms BIGINT, decided_by TEXT)",
    "CREATE TABLE IF NOT EXISTS adc2_sponsored_clicks (day_ms BIGINT NOT NULL CHECK (day_ms % 86400000 = 0), "
    "campaign_id TEXT NOT NULL REFERENCES adc2_campaigns(id), task_category TEXT NOT NULL, region TEXT NOT NULL, "
    "surface TEXT NOT NULL CHECK (surface IN ('explore','chat','mcp','a2a','rest')), clicks BIGINT NOT NULL CHECK (clicks>=0), "
    "PRIMARY KEY (day_ms, campaign_id, task_category, region, surface))",
)
TABLES = ("adc2_sponsored_offers", "adc2_sponsored_clicks")
# Offers shown in MCP and A2A answers are counted in adc2_sponsored_impressions with placement 'mcp' or 'a2a'
# (PM 11-14: one change with the tables above). The migration replaces the placement CHECK by this one.
AGENT_PLACEMENTS = ("mcp", "a2a")
IMPRESSION_PLACEMENT_CHECK = "CHECK (placement IN ('explore','chat','mcp','a2a'))"
IMPRESSION_PLACEMENT_CONSTRAINT = "adc2_sponsored_impressions_placement_check"
SURFACES = ("explore", "chat", "mcp", "a2a", "rest")


def _check_public_url(url):
    from ...broker.discovery import check_public_url
    check_public_url(url)


URL_CHECK = _check_public_url    # resolves the host; private or internal addresses raise (tests replace it)


def public_endpoint(url):
    """True when the offer endpoint resolves only to public addresses (checked at approval and at every redirect)."""
    try:
        URL_CHECK(url)
        return True
    except Exception:
        return False


DAY_MS = 86_400_000


def _require_tables(store):
    """Before migrate-agent-ads, submitting or deciding an offer answers 409 offers_not_available (never a 5xx, which
    the full check, edge watch and error ledger count as failures; PM 11-14)."""
    if not store.one("sponsored_offers_table")["present"]:
        raise ContractError("offers_not_available", 409)


def submit_offer(store, advertiser_id, campaign_id, raw, *, now_ms=None):
    """An advertiser's offer for one of its campaigns: screened now, then pending an operator's review.
    A changed offer goes back to pending (the approved one stops showing until it is reviewed again)."""
    advertiser_id, campaign_id = identifier(advertiser_id), identifier(campaign_id)
    try:
        offer = validate_offer(raw)
    except OfferError as error:
        raise ContractError("offer_refused:" + ",".join(error.problems)[:200], 422)
    now_ms = int(time.time() * 1000) if now_ms is None else int(now_ms)
    with store.atomic():
        _require_tables(store)
        campaign = store.one("campaign_get", (campaign_id,))
        if campaign is None or campaign["advertiser_id"] != advertiser_id:
            raise ContractError("unknown_resource", 404)
        name = campaign_name(store, campaign)
        if not advertiser_name_ok(name):
            raise ContractError("offer_refused:advertiser_name", 422)   # R33: the name opens the agent line
        store.execute("sponsored_offer_upsert", (campaign_id, advertiser_id, json.dumps(offer, sort_keys=True), now_ms))
    return {"campaign_id": campaign_id, "state": "pending", "offer": offer, "preview": preview_line(name, offer)}


def decide_offer(store, access, principal, campaign_id, *, approve, reason="", now_ms=None):
    access.require_operator(principal)
    campaign_id = identifier(campaign_id)
    now_ms = int(time.time() * 1000) if now_ms is None else int(now_ms)
    if not approve and not (isinstance(reason, str) and 3 <= len(reason.strip()) <= 200):
        raise ContractError("invalid_reason", 422)
    with store.atomic():
        _require_tables(store)
        row = store.one("sponsored_offer_get", (campaign_id,))
        if row is None or row["state"] != "pending":
            raise ContractError("offer_not_pending", 409)
        offer = validate_offer(json.loads(row["offer_json"]))  # the screen again, in case the rules changed
        if approve and not advertiser_name_ok(campaign_name(store, store.one("campaign_get", (campaign_id,)) or {})):
            raise ContractError("offer_refused:advertiser_name", 422)
        if approve and not public_endpoint(offer["endpoint"]):
            raise ContractError("endpoint_not_public", 422)    # check_public_url: no private or internal targets
        store.execute("sponsored_offer_decide", ("approved" if approve else "rejected", (reason or "").strip() or None,
                                                 now_ms, str(principal.id), campaign_id))
    return {"campaign_id": campaign_id, "state": "approved" if approve else "rejected"}


def _held(store, campaign_id):
    from .auto_review import HELD_OFFER, flags_of
    return flags_of(store, HELD_OFFER, campaign_id)


def pending_offers(store, access, principal, limit=50):
    access.require_operator(principal)
    with store.atomic():
        if not store.one("sponsored_offers_table")["present"]:
            return {"items": [], "available": False}      # nothing can be pending before the tables exist
        rows = store.all("sponsored_offers_pending", (limit,))
        items = []
        for r in rows:
            offer = json.loads(r["offer_json"])
            name = campaign_name(store, store.one("campaign_get", (r["campaign_id"],)) or {})
            items.append({"campaign_id": r["campaign_id"], "advertiser_id": r["advertiser_id"], "offer": offer,
                          "submitted_ms": int(r["submitted_ms"]), "advertiser": name,
                          "advertiser_name_ok": advertiser_name_ok(name),
                          "auto_flags": _held(store, r["campaign_id"]),     # why the automatic review held it
                          "preview": preview_line(name, offer)})   # R33: the exact line agents will read
    return {"items": items}


def approved_offer(store, campaign_id):
    with store.atomic():
        if not store.one("sponsored_offers_table")["present"]:
            return None
        row = store.one("sponsored_offer_get", (identifier(campaign_id),))
    return json.loads(row["offer_json"]) if row and row["state"] == "approved" else None


def count_click(store, campaign_id, *, category, region, surface, now_ms=None):
    """A click on a sponsored card or offer, counted on the server: no cookie, no person, no query text."""
    if surface not in SURFACES:
        raise ContractError("unsupported_surface", 422)
    now_ms = int(time.time() * 1000) if now_ms is None else int(now_ms)
    with store.atomic():
        if store.one("sponsored_offers_table")["present"]:
            store.execute("sponsored_click_add", (now_ms - now_ms % DAY_MS, identifier(campaign_id), category, region,
                                                  surface))
