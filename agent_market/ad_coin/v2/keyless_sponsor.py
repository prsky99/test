"""Keyless Sponsored orders: an agent buys one Sponsored placement in API calls, with no site account and no
browser session (PM 11-17 decision B, docs/AD_COIN_KEYLESS_QUOTE.md).

Three calls, with a review in between:
1. create(): the order is screened (ad_rules through the same screen the automatic review uses, the advertiser name
   screen of open applications, check_public_url for the endpoint, a per-address daily limit) and then creates, with
   existing tables only, a person whose ids are a server-secret HMAC of a fresh random read key (the same secret and
   derivation as the site sign-in bridge, live_auth.linked_id), an advertiser through the open application path
   (approved at once when its checks pass, held for a person otherwise), a Sponsored-only campaign with the agent
   offer, and a review request. The read key is returned once and never stored, not even as a hash: whoever presents
   it derives the same principal id, which is compared in constant time with the applicant recorded in the audit log.
2. status(): in review, rejected (with the reason) or approved. Once the review passed, the first read starts the
   campaign's platform-covered 2-atom display budget through start_display_budget (an in-process system principal,
   no fresh human challenge, nothing answered on the buyer's behalf) and quotes it with the shared payment engine:
   PaidBookings.quote for one day, PaidPlans for a budget. Later and concurrent reads return the same open quote (one
   advisory lock per order); a new one is made only after the previous one expired unpaid.
3. pay(): the transaction hash goes to the existing submit path (exact amount, Base USDC, sanctions, KRW record).

No contact data, no account, no balance, no custody: the server only receives USDC at its one address and holds no
private key. A lost read key cannot be recovered (there is no contact to recover it with); answers say so.
"""

import hashlib
import hmac
import json
import os
import secrets
import threading
import time
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from .contracts import ContractError
from .identity import Kind, Principal
from .live_auth import linked_id
from .security_guards import AuditLogger

ORDER_EVENT = "keyless_offer_submitted"
CAMPAIGN_EVENT = "keyless_campaign_created"
BUDGET_EVENT = "keyless_budget_started"
SYSTEM_PRINCIPAL = str(uuid5(NAMESPACE_URL, "https://agentconcierge.biz/ad-coin/keyless-display-budget"))
SYSTEM_OWNER = str(uuid5(NAMESPACE_URL, "https://agentconcierge.biz/ad-coin/keyless-display-budget/owner"))
LIMIT_ENV = "AD_COIN_KEYLESS_ORDERS_PER_IP_DAY"
DEFAULT_LIMIT_PER_IP_DAY = 5
PRINCIPAL_LABEL, OWNER_LABEL = "adc2-keyless-principal:", "adc2-keyless-owner:"
TEXT_LIMIT = 120                      # the agent offer line limit (sponsored_offer.LINE_LIMIT)
MARKER_ATOMS = "2"                    # a Sponsored-only campaign (never offered for rewarded views)
SPAN_DAYS_AFTER_HORIZON = 2
LOST_KEY_NOTE = ("Keep the read_key: it is shown once and is never stored. Without it this order cannot be read, "
                 "quoted or paid, and it cannot be recovered because no contact details are collected.")
PAY_NOTE = ("Send exactly amount_usdc in USDC on Base (chain 8453) to pay_to before expires_at, then POST the "
            "transaction hash to payment_url. Any other amount is not matched.")


def limit_per_ip_day(values=None):
    values = os.environ if values is None else values
    try:
        return max(0, int(values.get(LIMIT_ENV, DEFAULT_LIMIT_PER_IP_DAY)))
    except (TypeError, ValueError):
        return DEFAULT_LIMIT_PER_IP_DAY


class DailyAddressLimit:
    """Orders created per client address and UTC day, in memory only: the address is kept as an HMAC with a key
    that lives in this process, and every count is dropped when the day changes (no address is stored)."""

    def __init__(self, limit=None, clock=None):
        self._limit, self._clock = limit, clock or time.time
        self._key, self._day, self._counts = secrets.token_bytes(32), None, {}
        self._lock = threading.Lock()

    def _slot(self, address):
        day = int(self._clock() // 86400)
        if day != self._day:
            self._day, self._counts = day, {}
        return hmac.new(self._key, (address or "").encode(), hashlib.sha256).hexdigest()[:32]

    def allowed(self, address):
        limit = limit_per_ip_day() if self._limit is None else self._limit
        with self._lock:
            return self._counts.get(self._slot(address), 0) < limit

    def count(self, address):
        with self._lock:
            slot = self._slot(address)
            self._counts[slot] = self._counts.get(slot, 0) + 1


def _url_check(url):
    from ...broker.discovery import check_public_url
    check_public_url(url)


URL_CHECK = _url_check     # resolves the host; private or internal addresses raise (tests replace it)


def _iso(ms):
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(int(ms) / 1000))


class KeylessSponsor:
    def __init__(self, commercial, bookings, *, owner_link_key, limiter=None):
        if type(owner_link_key) is not bytes or len(owner_link_key) != 32:
            raise ContractError("owner_link_key_required", 503)
        from .paid_plans import PaidPlans
        self.commercial, self.bookings, self.plans = commercial, bookings, PaidPlans(bookings)
        self.store, self.access = commercial.store, commercial.access
        self._key = owner_link_key
        self.limiter = limiter or DailyAddressLimit()

    # ---- identity ---------------------------------------------------------------------------------------------
    def _ids(self, read_key):
        return linked_id(self._key, PRINCIPAL_LABEL, read_key), linked_id(self._key, OWNER_LABEL, read_key)

    def _principal(self, principal_id, owner_id):
        with self.store.atomic():
            epoch = self.access.guards.current(principal_id)
        return Principal(UUID(principal_id), Kind.HUMAN, epoch, time.time() + 300, owner_id=UUID(owner_id),
                         csrf_verified=True, audience="aiac-v2-model")

    @staticmethod
    def _session_hash(principal_id):
        return hashlib.sha256(("keyless:" + principal_id).encode()).hexdigest()

    # ---- screening --------------------------------------------------------------------------------------------
    def screen(self, body):
        """The checked order and the flags that hold it for a person. Raises for what can never be sold."""
        from .ad_rules import hard
        from .advertiser_applications import _NAME, _WEBSITE, screen_application
        from .auto_review import screen_campaign
        from .paid_bookings import USDC_UNITS
        from .paid_plans import MAX_BUDGET_UNITS, MIN_PLAN_UNITS, _units
        from .sponsored import SITE_CATEGORIES
        from .sponsored_booking import DAY_MS, HORIZON_DAYS, day_ms_of
        from .sponsored_offer import SENSITIVE_SITE_CATEGORIES, OfferError, validate_offer
        if not isinstance(body, dict):
            raise ContractError("invalid_json", 400)
        unknown = set(body) - {"name", "text", "url", "category", "region", "day", "budget_usdc"}
        if unknown:
            raise ContractError("unknown_field", 422)
        name, text, url = (body.get(k).strip() if isinstance(body.get(k), str) else "" for k in ("name", "text", "url"))
        category = body.get("category") if isinstance(body.get("category"), str) else ""
        region = body.get("region").upper() if isinstance(body.get("region"), str) else ""
        if not _NAME.match(name) or len(name) > 80 or not text or len(text) > TEXT_LIMIT or not _WEBSITE.match(url):
            raise ContractError("invalid_order", 422)
        if category in SENSITIVE_SITE_CATEGORIES:
            raise ContractError("sensitive_category", 422)       # these topics never carry an ad
        mapped = SITE_CATEGORIES.get(category, category)
        if mapped not in self.bookings.taxonomy or mapped not in self.commercial.taxonomy \
                or region not in self.bookings.regions or region not in self.commercial.regions:
            raise ContractError("unsupported_targeting", 422)
        day, budget = body.get("day"), body.get("budget_usdc")
        if (day is None) == (budget is None):
            raise ContractError("day_or_budget_required", 422)   # exactly one of the two
        now_ms = self.bookings._now(None)
        today = now_ms - now_ms % DAY_MS
        if day is not None:
            if not today + DAY_MS <= day_ms_of(day) <= today + HORIZON_DAYS * DAY_MS:
                raise ContractError("day_not_bookable", 422)
        else:
            units = _units(budget)
            if units > MAX_BUDGET_UNITS:
                raise ContractError("budget_too_large", 422)
            if units < MIN_PLAN_UNITS:
                raise ContractError("budget_below_minimum", 422)
            budget = "%d.%02d" % (units // USDC_UNITS, units % USDC_UNITS // 10_000)
        try:
            offer = validate_offer({"tool": name, "endpoint": url, "line": text})
        except OfferError as error:
            problems = error.problems
            offer = None
        else:
            problems = []
        flags = list(dict.fromkeys(screen_campaign({"name": name, "creative_text": text}) + problems))
        if hard(flags) or any(p.split(":", 1)[-1] in ("https_url_required", "path_characters", "too_long",
                                                       "not_text", "required") for p in problems):
            raise ContractError("order_refused:" + ",".join(flags)[:200], 422)
        try:
            name_flags = screen_application(name, url, check_url=URL_CHECK)
        except ContractError:
            raise ContractError("url_not_public", 422) from None
        flags = list(dict.fromkeys(flags + name_flags))
        order = {"name": name, "text": text, "url": url, "category": mapped, "site_category": category,
                 "region": region, "day": day, "budget_usdc": budget}
        return order, offer, flags

    # ---- 1. create --------------------------------------------------------------------------------------------
    def create(self, body, *, address, write=True):
        """write=False (Early-Data or our own QA requests): the same answer shape, nothing written."""
        if write and not self.limiter.allowed(address):
            raise ContractError("daily_order_limit", 429)       # before the screen, which resolves the host
        order, offer, flags = self.screen(body)
        if not write:
            return {"dry_run": True, "state": "in_review", "hold_reasons": flags}
        from . import advertiser_applications as applications
        from .access import HUMAN_CAPABILITIES
        read_key = secrets.token_urlsafe(32)                    # 32 random bytes, shown once, never stored
        principal_id, owner_id = self._ids(read_key)
        self.access.provision_principal(principal_id, Kind.HUMAN, owner_id=owner_id, capabilities=HUMAN_CAPABILITIES)
        principal = self._principal(principal_id, owner_id)
        applied = applications.apply(self.access, principal, display_name=order["name"], website_url=order["url"],
                                     check_url=lambda _url: None)    # the url was checked in screen()
        order_id = applied["application_id"]
        AuditLogger.log(self.store, ORDER_EVENT, "succeeded", actor_principal_id=principal_id, target_id=order_id,
                        details={**order, "flags": flags, "offer": offer or {}})
        self.limiter.count(address)
        view = {"order_id": order_id, "status_url": "/api/ad-coin/v2/sponsor/" + order_id, "read_key": read_key,
                "read_key_header": "X-Read-Key", "note": LOST_KEY_NOTE}
        if applied.get("held"):
            return {**view, "state": "in_review", "hold_reasons": flags or ["advertiser_name_review"]}
        try:
            self._ensure_campaign(order_id, principal, self._order(order_id))
        except ContractError:
            pass       # the read key is already issued: the next status read creates the campaign again
        return {**view, "state": "in_review", "hold_reasons": flags}

    def _order(self, order_id):
        with self.store.atomic():
            row = self.store.one("audit_by_target_event", (order_id, ORDER_EVENT))
        return json.loads(row["details_json"]) if row else None

    def _campaign_id(self, order_id):
        with self.store.atomic():
            row = self.store.one("audit_by_target_event", (order_id, CAMPAIGN_EVENT))
        return json.loads(row["details_json"]).get("campaign_id") if row else None

    def _write(self, operation, principal, body, *, params=None, if_match=None):
        from .contracts import canonical_bytes
        return self.commercial.write(operation, principal, canonical_bytes(body), key=str(uuid4()),
                                     path_parameters=params or {}, if_match=if_match,
                                     session_hash=self._session_hash(str(principal.id)))

    def _ensure_campaign(self, order_id, principal, order):
        """The Sponsored-only campaign for an order whose advertiser is active, once; then its review request and
        the agent offer (pending until the automatic review or a person approves it)."""
        from .commercial import date_text, etag
        from .contracts import MODEL_ASSET
        from .sponsored_booking import DAY_MS, HORIZON_DAYS
        existing = self._campaign_id(order_id)
        if existing:
            return existing
        with self.store.atomic():
            advertiser = self.store.one("advertiser_get", (order_id,))
        if advertiser is None or advertiser["status"] != "active":
            return None
        now_ms = int(self.commercial.clock_ms())
        today = now_ms - now_ms % DAY_MS
        created = self._write("createCampaign", principal, {
            "name": order["name"], "asset_id": MODEL_ASSET, "total_budget_atoms": MARKER_ATOMS,
            "daily_budget_atoms": MARKER_ATOMS, "gross_p1_atoms": MARKER_ATOMS, "budget_timezone": "UTC",
            "starts_at": date_text(now_ms),
            "ends_at": date_text(today + (HORIZON_DAYS + SPAN_DAYS_AFTER_HORIZON) * DAY_MS),
            "task_categories": [order["category"]], "regions": [order["region"]], "creative_text": order["text"],
            "min_exposure_ms": 15000, "split_policy_id": "default_v5", "renderer_profile": "platform_text_v1"},
            params={"advertiser_id": order_id})
        campaign_id = created["id"]
        AuditLogger.log(self.store, CAMPAIGN_EVENT, "succeeded", actor_principal_id=str(principal.id),
                        target_id=order_id, details={"campaign_id": campaign_id})
        self._write("requestReview", principal, {"revision_hash": created["revision_hash"]},
                    params={"advertiser_id": order_id, "campaign_id": campaign_id}, if_match=etag(created))
        offer = order.get("offer") or {}
        if offer:
            from .sponsored_offer import submit_offer
            try:
                submit_offer(self.store, order_id, campaign_id, offer)
            except ContractError:
                pass       # before the offer tables exist, or a name the agent line refuses: the placement still runs
        return campaign_id

    # ---- the read key -----------------------------------------------------------------------------------------
    def authenticate(self, order_id, read_key):
        """(order_id, principal) for the right key; the same 404 for an unknown order, a wrong key or no key."""
        from .advertiser_applications import APPLIED
        try:
            order_id = str(UUID(str(order_id)))
        except ValueError:
            order_id = None
        key = read_key if isinstance(read_key, str) and 0 < len(read_key) <= 128 else secrets.token_urlsafe(32)
        derived, owner = self._ids(key)
        recorded = None
        if order_id is not None:
            with self.store.atomic():
                applied = self.store.one("audit_by_target_event", (order_id, APPLIED))
                ordered = self.store.one("audit_by_target_event", (order_id, ORDER_EVENT))
            if applied is not None and ordered is not None:
                recorded = applied["actor_principal_id"]
        same = hmac.compare_digest(derived.encode(), str(recorded or "").encode())
        if not same or recorded is None or read_key is not key:
            raise ContractError("unknown_order", 404)
        return order_id, self._principal(derived, owner)

    # ---- 2. status and quote ----------------------------------------------------------------------------------
    def status(self, order_id, read_key, *, write=True):
        from . import advertiser_applications as applications
        order_id, principal = self.authenticate(order_id, read_key)
        order = self._order(order_id)
        base = {"order_id": order_id, "status_url": "/api/ad-coin/v2/sponsor/" + order_id,
                "payment_url": "/api/ad-coin/v2/sponsor/" + order_id + "/payment",
                "day": order.get("day"), "budget_usdc": order.get("budget_usdc"),
                "category": order.get("site_category") or order.get("category"), "region": order.get("region")}
        with self.store.atomic():
            applied = applications.status_of(self.store, order_id)
            rejected = self.store.one("audit_by_target_event", (order_id, applications.REJECTED))
        if applied == "rejected":
            reason = json.loads(rejected["details_json"]).get("reason", "") if rejected else ""
            return {**base, "state": "rejected", "reason": reason or "advertiser_not_approved"}
        if applied != "approved":
            return {**base, "state": "in_review", "hold_reasons": order.get("flags") or ["advertiser_name_review"]}
        campaign_id = self._campaign_id(order_id)
        if campaign_id is None:
            if not write:
                return {**base, "state": "in_review", "hold_reasons": []}
            campaign_id = self._ensure_campaign(order_id, principal, order)
            if campaign_id is None:
                return {**base, "state": "in_review", "hold_reasons": []}
        with self.store.atomic():
            campaign = dict(self.store.one("campaign_get", (campaign_id,)))
            review = self.store.one("review_latest", (campaign["current_revision_id"],))
            review = dict(review) if review else None
        if campaign["state"] == "rejected" or (review and review["state"] == "rejected"):
            return {**base, "state": "rejected", "reason": (review or {}).get("reason_code") or "ad_not_approved",
                    "note": "No money has moved. Place a new order with different text."}
        if campaign["state"] == "draft" and write:     # an earlier creation stopped before its review request
            from .commercial import etag
            with self.store.atomic():
                view = self.commercial._campaign_view(self.store.one("campaign_get", (campaign_id,)))
            self._write("requestReview", principal, {"revision_hash": view["revision_hash"]},
                        params={"advertiser_id": order_id, "campaign_id": campaign_id}, if_match=etag(view))
            return {**base, "state": "in_review", "hold_reasons": []}
        if campaign["state"] in ("draft", "in_review"):
            from .auto_review import HELD_REVIEW, flags_of
            with self.store.atomic():
                held = flags_of(self.store, HELD_REVIEW, review["id"]) if review else []
            return {**base, "state": "in_review", "hold_reasons": held}
        if campaign["state"] == "eligible":
            if not write:
                return {**base, "state": "approved", "quote": None, "quote_error": "retry_without_early_data"}
            try:
                self.start_display_budget(campaign_id, order_id)
            except ContractError as exc:
                return {**base, "state": "approved", "quote": None, "quote_error": exc.code}
        if not write:
            quote = self._open_quote(order_id, campaign_id, order)
            if quote is None:
                return {**base, "state": "approved", "quote": None, "quote_error": "retry_without_early_data"}
            return {**base, "state": "approved", "quote": quote, "note": PAY_NOTE}
        try:
            quote = self._quote_once(order_id, campaign_id, order)
        except ContractError as exc:
            return {**base, "state": "approved", "quote": None, "quote_error": exc.code}
        return {**base, "state": "approved", "quote": quote, "note": PAY_NOTE}

    def _quote_once(self, order_id, campaign_id, order):
        """The order's open quote, or a new one: one transaction holds the order's advisory lock while it re-reads the
        open quotes and quotes, so concurrent reads of one approved order leave exactly one open quote."""
        with self.store.atomic():
            self.store.lock("keyless_quote:" + campaign_id)
            quote = self._open_quote(order_id, campaign_id, order)
            return quote if quote is not None else self._new_quote(order_id, campaign_id, order)

    # ---- the platform display budget --------------------------------------------------------------------------
    def system_principal(self):
        """The in-process principal that starts keyless display budgets: a fixed id, no session, no token, no
        capability; it exists only to name the actor in the audit log (modelled on auto_review.principal)."""
        self.access.provision_principal(SYSTEM_PRINCIPAL, Kind.HUMAN, owner_id=SYSTEM_OWNER, capabilities=frozenset())
        return SYSTEM_PRINCIPAL

    def start_display_budget(self, campaign_id, order_id):
        """Approves and activates a keyless order's display-only campaign, and nothing else.

        A keyless buyer has no person to answer a fresh human challenge, and the server must not answer one for
        them. This path needs none: it starts only a campaign that this order created (its keyless_campaign_created
        record) whose budget is the 2-atom display marker the platform covers (Commercial._cover_sponsored_marker),
        after its review passed. It funds the marker and opens the budget window exactly as activation does, writes
        no approval or fresh-action row (a display-only campaign is never offered for rewarded views, which need
        one), and logs keyless_budget_started once. Paid placements still need a confirmed USDC payment."""
        from .commercial import SPONSORED_MARKER_ATOMS
        from .ledger import MODEL_ASSET, identifier
        campaign_id, order_id = identifier(campaign_id), identifier(order_id)
        system = self.system_principal()
        commercial, store = self.commercial, self.store
        with store.atomic():
            store.lock("2:campaign:" + campaign_id, "keyless_budget:" + campaign_id)
            if self._order(order_id) is None or self._campaign_id(order_id) != campaign_id:
                raise ContractError("not_a_keyless_campaign", 409)
            campaign = commercial._campaign(campaign_id, True)
            if campaign["advertiser_id"] != order_id:
                raise ContractError("not_a_keyless_campaign", 409)
            revision = store.one("revision_get", (campaign["current_revision_id"],))
            if any(int(revision[k]) != SPONSORED_MARKER_ATOMS for k in ("total_atoms", "daily_atoms", "gross_atoms")):
                raise ContractError("not_a_display_marker_budget", 409)
            if (campaign["state"], campaign["approval_status"]) == ("active", "approved"):
                return False                                   # started already (a concurrent read did it)
            now_ms = int(commercial.clock_ms())
            review = store.one("review_latest", (campaign["current_revision_id"],))
            advertiser = store.one("advertiser_get", (campaign["advertiser_id"],))
            if (campaign["state"] != "eligible" or campaign["approval_status"] != "unapproved" or campaign["funded"]
                    or not review or review["state"] != "eligible" or revision["ends_ms"] <= now_ms
                    or advertiser is None or advertiser["status"] != "active"):
                raise ContractError("campaign_not_startable", 409)
            if not store.one("commercial_control_locked")["model_activation_enabled"]:
                raise ContractError("model_activation_disabled", 503)
            source = commercial.ledger.account(advertiser["available_account"])
            target = commercial.ledger.account(campaign["account_id"])
            if (source["owner_id"], source["purpose"], source["asset_id"]) != (advertiser["id"], "advertiser_available", MODEL_ASSET) \
                    or (target["owner_id"], target["purpose"], target["asset_id"]) != (advertiser["id"], "campaign_available", MODEL_ASSET):
                raise ContractError("campaign_funding_account_mismatch", 503)
            commercial._cover_sponsored_marker(advertiser, campaign, revision)
            commercial.ledger.post("campaign_funding:" + campaign_id + ":" + MODEL_ASSET,
                                   [(advertiser["available_account"], str(-int(revision["total_atoms"]))),
                                    (campaign["account_id"], str(revision["total_atoms"]))], kind="campaign_funding")
            window_id = commercial.budgets.create_window(campaign["account_id"], "total", revision["starts_ms"],
                                                         revision["ends_ms"], str(revision["total_atoms"]))
            commercial._update(campaign, state="active", approval_status="approved", funded=1,
                               total_window_id=window_id, dispatch_epoch=campaign["dispatch_epoch"] + 1)
            commercial.outbox.enqueue("report-plan:" + campaign_id, {"environment": "model",
                                                                     "event": "report_plan_requested",
                                                                     "campaign_id": campaign_id}, available_ms=0)
            AuditLogger.log(store, BUDGET_EVENT, "succeeded", actor_principal_id=system, target_id=campaign_id,
                            details={"order_id": order_id, "budget_atoms": str(revision["total_atoms"])})
        return True

    def _open_quote(self, order_id, campaign_id, order):
        """The order's current quote: open, being confirmed or settled. An expired unpaid one does not count."""
        now_ms = self.bookings._now(None)

        def live(item):
            return item["state"] != "expired" and not (item["state"] == "quoted" and int(item["expires_ms"]) <= now_ms)

        if order.get("budget_usdc") is not None:
            if not self.plans.ready():
                return None
            for item in self.plans.list(order_id)["items"]:
                if item["campaign_id"] == campaign_id and live(item):
                    return self._quote_view(item, kind="plan")
            return None
        from .paid_bookings import _view
        with self.store.atomic():
            rows = [dict(r) for r in self.store.all("paid_bookings_by_advertiser", (order_id,))]
        for row in rows:
            if row["campaign_id"] == campaign_id and row["note"] != "plan" and live(row):
                return self._quote_view(_view(row), kind="booking")
        return None

    def _new_quote(self, order_id, campaign_id, order):
        if order.get("budget_usdc") is not None:
            if not self.plans.ready():
                raise ContractError("plans_not_open", 409)
            options = self.plans.options(order_id, campaign_id=campaign_id, budget_usdc=order["budget_usdc"],
                                         categories=[order["category"]], regions=[order["region"]])
            plan = options["plans"][0]
            return self._quote_view(self.plans.quote(order_id, campaign_id=campaign_id, items=plan["items"]),
                                    kind="plan")
        return self._quote_view(self.bookings.quote(order_id, campaign_id=campaign_id, day=order["day"],
                                                    task_category=order["category"], region=order["region"]),
                                kind="booking")

    @staticmethod
    def _quote_view(item, *, kind):
        view = {"quote_id": item["id"], "kind": kind, "state": item["state"], "amount_usdc": item["amount_usdc"],
                "amount_units": item["amount_units"], "pay_to": item["pay_to"], "network": "Base",
                "chain_id": item["chain_id"], "token": item["token"], "token_symbol": "USDC",
                "expires_ms": item["expires_ms"], "expires_at": _iso(item["expires_ms"]), "tx_hash": item["tx_hash"]}
        if kind == "plan":
            view["placements"] = item["items"]
        else:
            view["day"] = time.strftime("%Y-%m-%d", time.gmtime(item["day_ms"] / 1000))
        return view

    # ---- 3. payment -------------------------------------------------------------------------------------------
    def pay(self, order_id, read_key, tx_hash):
        order_id, _ = self.authenticate(order_id, read_key)
        order = self._order(order_id)
        campaign_id = self._campaign_id(order_id)
        quote = self._open_quote(order_id, campaign_id, order) if campaign_id else None
        if quote is None:
            raise ContractError("no_open_quote", 409)
        if quote["kind"] == "plan":
            done = self.plans.submit(order_id, quote["quote_id"], tx_hash)
        else:
            done = self.bookings.submit(order_id, quote["quote_id"], tx_hash)
        return {"order_id": order_id, "quote": self._quote_view(done, kind=quote["kind"])}
