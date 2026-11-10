"""Coin economy step 3: one-day Sponsored placements booked with an advertiser's coins.

PM decisions 2026-11-10 (reports/AI-AD-Coin-Sponsored-예약결제-설계초안-2026-11-10.md):
- 50 coins per (task category, broad region) per UTC day, two placements per pair and day;
- only booked campaigns appear in the Sponsored slot;
- coins come back in full when the platform is at fault (campaign rejected or suspended, advertiser
  suspended, or an operator records an outage) and when the booking is cancelled before its day;
  an advertiser who pauses the campaign gets nothing back;
- a new advertiser's first booking is paid from the growth budget, once per advertiser, while this
  month's support stays within 10% of the growth budget.

Coins only move between the advertiser (or the growth budget) and the platform's coin revenue. No
money, card, chain or payment provider is involved; the real-value switch is not consulted.
"""

import datetime
import re
import time
from uuid import NAMESPACE_URL, uuid5

from .contracts import ContractError
from .ledger import MODEL_ASSET, ModelLedger, identifier
from .points import ATOMS_PER_COIN, GROWTH_ACCOUNT, REVENUE_ACCOUNT, ensure_platform_accounts, month_start_ms
from .security_guards import AuditLogger, EventType

DAY_MS = 86_400_000
PRICE_ATOMS = 50 * ATOMS_PER_COIN
PLACEMENTS_PER_DAY = 2          # matches sponsored.MAX_CARDS
HORIZON_DAYS = 30               # bookable from tomorrow up to 30 days ahead
SUPPORT_SHARE_PERCENT = 10      # monthly first-booking support stays within 10% of the growth budget
SETTLE_DELAY_MS = 10 * 60_000   # settle a day ten minutes after it ends
PLATFORM_FAULT_CAMPAIGN_STATES = frozenset(("rejected", "suspended"))

_DAY = re.compile(r"20[0-9]{2}-[0-9]{2}-[0-9]{2}\Z")
_REQUEST = re.compile(r"[a-f0-9]{32}\Z")


def day_ms_of(day):
    if type(day) is not str or not _DAY.match(day):
        raise ContractError("invalid_day", 422)
    try:
        moment = datetime.datetime.strptime(day, "%Y-%m-%d").replace(tzinfo=datetime.timezone.utc)
    except ValueError:
        raise ContractError("invalid_day", 422) from None
    return int(moment.timestamp() * 1000)


def _view(row):
    return {"id": row["id"], "campaign_id": row["campaign_id"], "day_ms": int(row["day_ms"]),
            "task_category": row["task_category"], "region": row["region"],
            "price_atoms": str(int(row["price_atoms"])), "state": row["state"]}


class SponsoredBookings:
    def __init__(self, store, ledger=None, *, taxonomy, regions, access=None, clock=None):
        self.store, self.ledger, self.access = store, ledger or ModelLedger(store), access
        self.taxonomy, self.regions = frozenset(taxonomy), frozenset(regions)
        self._clock = clock or time.time

    def _now_ms(self, now_ms):
        return int(self._clock() * 1000) if now_ms is None else int(now_ms)

    def _balance(self, account_id):
        row = self.store.one("account_get", (account_id,))
        return int(row["balance_atoms"]) if row else 0

    def _support_allowed(self, advertiser_id, now_ms):
        """First booking per advertiser, within this month's share of the growth budget."""
        if self.store.one("journal_get", (MODEL_ASSET, "sponsored_support:" + advertiser_id)):
            return False
        spent = -int(self.store.one("sponsored_support_month_total",
                                    (MODEL_ASSET, GROWTH_ACCOUNT, month_start_ms(now_ms)))["total"])
        growth = self._balance(GROWTH_ACCOUNT)
        cap = (growth + spent) * SUPPORT_SHARE_PERCENT // 100
        return growth >= PRICE_ATOMS and spent + PRICE_ATOMS <= cap

    def book(self, advertiser_id, *, campaign_id, day, task_category, region, request_id, now_ms=None):
        """Book one placement. The same request_id returns the same booking (replayed=True)."""
        advertiser_id, campaign_id = identifier(advertiser_id), identifier(campaign_id)
        if type(request_id) is not str or not _REQUEST.match(request_id):
            raise ContractError("invalid_request_id", 422)
        if task_category not in self.taxonomy or region not in self.regions:
            raise ContractError("unsupported_targeting", 422)
        day_ms, now_ms = day_ms_of(day), self._now_ms(now_ms)
        today = now_ms - now_ms % DAY_MS
        if not today + DAY_MS <= day_ms <= today + HORIZON_DAYS * DAY_MS:
            raise ContractError("day_not_bookable", 422)
        booking_id = str(uuid5(NAMESPACE_URL, "https://agentconcierge.biz/ad-coin/sponsored/"
                               + advertiser_id + "/" + request_id))
        ensure_platform_accounts(self.ledger)
        with self.store.atomic():
            self.store.lock("sponsored_day:%d:%s:%s" % (day_ms, task_category, region),
                            "sponsored_advertiser:" + advertiser_id)
            existing = self.store.one("sponsored_booking_get", (booking_id,))
            if existing:
                same = (existing["campaign_id"], int(existing["day_ms"]), existing["task_category"],
                        existing["region"]) == (campaign_id, day_ms, task_category, region)
                if not same:
                    raise ContractError("idempotency_conflict", 409)
                return {**_view(existing), "paid_by": None, "replayed": True}
            advertiser = self.store.one("advertiser_get", (advertiser_id,))
            if advertiser is None:
                raise ContractError("unknown_advertiser", 404)
            if advertiser["status"] != "active":
                raise ContractError("advertiser_not_active", 409)
            campaign = self.store.one("campaign_get", (campaign_id,))
            if campaign is None or campaign["advertiser_id"] != advertiser_id:
                raise ContractError("unknown_resource", 404)
            if campaign["state"] != "active" or campaign["approval_status"] != "approved":
                raise ContractError("campaign_not_bookable", 409)
            if self.store.one("sponsored_booking_slot", (campaign_id, day_ms, task_category, region)):
                raise ContractError("already_booked", 409)
            taken = int(self.store.one("sponsored_booking_day_count", (day_ms, task_category, region))["n"])
            if taken >= PLACEMENTS_PER_DAY:
                raise ContractError("sponsored_day_full", 409)
            if self._support_allowed(advertiser_id, now_ms):
                payer, key, paid_by = GROWTH_ACCOUNT, "sponsored_support:" + advertiser_id, "growth_support"
            else:
                payer, key, paid_by = advertiser["available_account"], "sponsored_booking:" + booking_id, "advertiser"
            journal = self.ledger.post(key, [(payer, str(-PRICE_ATOMS)), (REVENUE_ACCOUNT, str(PRICE_ATOMS))],
                                       kind="sponsored_purchase")
            self.store.execute("sponsored_booking_insert", (
                booking_id, advertiser_id, campaign_id, day_ms, task_category, region, str(PRICE_ATOMS),
                journal.journal_id, now_ms))
            AuditLogger.log(self.store, EventType.SPONSORED_BOOKED, "succeeded", target_id=booking_id,
                            details={"campaign_id": campaign_id, "day_ms": day_ms, "task_category": task_category,
                                     "region": region, "atoms": str(PRICE_ATOMS), "paid_by": paid_by})
            row = self.store.one("sponsored_booking_get", (booking_id,))
        return {**_view(row), "paid_by": paid_by, "replayed": False}

    def list(self, advertiser_id):
        with self.store.atomic():
            rows = self.store.all("sponsored_bookings_by_advertiser", (identifier(advertiser_id),))
        return {"items": [_view(row) for row in rows]}

    def _refund(self, booking, reason):
        """Return the price to whoever paid it (advertiser or growth budget); one refund per booking."""
        postings = self.store.all("journal_postings", (booking["journal_id"],))
        payer = next(row["account_id"] for row in postings if int(row["delta_atoms"]) < 0)
        price = str(int(booking["price_atoms"]))
        journal = self.ledger.post("sponsored_refund:" + booking["id"],
                                   [(REVENUE_ACCOUNT, str(-int(price))), (payer, price)], kind="refund")
        changed = self.store.execute("sponsored_booking_set_state",
                                     ("refunded", journal.journal_id, booking["id"], booking["state"]))
        if getattr(changed, "rowcount", 1) != 1:
            raise ContractError("booking_state_changed", 409)
        AuditLogger.log(self.store, EventType.SPONSORED_REFUNDED, "succeeded", target_id=booking["id"],
                        details={"reason": reason, "atoms": price})
        return {**_view({**booking, "state": "refunded"}), "refunded_atoms": price}

    def cancel(self, advertiser_id, booking_id, *, now_ms=None):
        """Cancel before the booked day starts (UTC) and get every coin back."""
        advertiser_id, booking_id, now_ms = identifier(advertiser_id), identifier(booking_id), self._now_ms(now_ms)
        with self.store.atomic():
            self.store.lock("sponsored_advertiser:" + advertiser_id)
            booking = self.store.one("sponsored_booking_get", (booking_id,))
            if booking is None or booking["advertiser_id"] != advertiser_id:
                raise ContractError("unknown_resource", 404)
            if booking["state"] != "booked":
                raise ContractError("booking_not_cancellable", 409)
            if now_ms >= int(booking["day_ms"]):
                raise ContractError("booking_day_started", 409)
            return self._refund(booking, "cancelled_before_day")

    def operator_refund(self, principal, booking_id, *, reason):
        """Platform staff return a day's coins after an outage on the platform side."""
        if self.access is None:
            raise ContractError("operator_required", 403)
        self.access.require_operator(principal)
        if type(reason) is not str or not 5 <= len(reason.strip()) <= 200:
            raise ContractError("invalid_reason", 422)
        with self.store.atomic():
            booking = self.store.one("sponsored_booking_get", (identifier(booking_id),))
            if booking is None:
                raise ContractError("unknown_resource", 404)
            if booking["state"] not in ("booked", "served"):
                raise ContractError("booking_already_refunded", 409)
            return self._refund(booking, "operator:" + reason.strip())

    def settle_due(self, *, now_ms=None, limit=50):
        """Close days that ended: served, or refunded when the platform side stopped the placement."""
        now_ms = self._now_ms(now_ms)
        settled = 0
        with self.store.atomic():
            rows = self.store.all("sponsored_bookings_due", (now_ms - DAY_MS - SETTLE_DELAY_MS, limit))
            for row in rows:
                fault = (row["campaign_state"] in PLATFORM_FAULT_CAMPAIGN_STATES
                         or row["advertiser_status"] == "suspended")
                booking = {key: row[key] for key in row if key not in ("campaign_state", "advertiser_status")}
                if fault:
                    self._refund(booking, "platform:" + (row["campaign_state"] if row["campaign_state"]
                                                         in PLATFORM_FAULT_CAMPAIGN_STATES else "advertiser_suspended"))
                else:
                    self.store.execute("sponsored_booking_set_state", ("served", None, row["id"], "booked"))
                settled += 1
        return settled
