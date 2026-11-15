"""Custom Sponsored plans paid in USDC: the advertiser names a budget, we propose plans (user decision 11-15, PM 11:3x).

Instead of choosing one fixed "one day, one category, one region, 5 USDC" slot, the advertiser gives the USDC they want
to spend and the task categories and regions they want. options() proposes two or three plans that fit the budget
(placements x days x audiences); the advertiser picks one and pays it once:
- one plan = one payment, quoted with a unique tail like single bookings (exact amount, Base USDC, sanctions screening,
  KRW rate and tx hash recorded, the server only receives);
- the plan never takes more than its own price: budget left over is not charged and nothing is kept as a balance;
- every placement of a plan is an ordinary adc2_paid_bookings row (no tx of its own, linked in adc2_paid_plan_items),
  so day capacity, serving, the daily settlement and the public ad library treat it like any paid placement. The
  payment, its tx hash, payer, KRW rate and refund live on the plan row (adc2_paid_plans), the unit the tax record
  and refunds use.
- the unit price stays 5 USDC (the reference price); the minimum plan and any bundle discount are settings PM decides.
Sponsored placements never change organic results, scores or ranking, and every one is labelled Sponsored.

The plan table comes from its own migration (scripts.ad_coin_v2_migrate migrate-paid-plans) under the DB change
procedure; until it exists options() still answers and quote() says plans are not open (409 plans_not_open).
"""

import secrets
from uuid import uuid4

from .contracts import ContractError
from .ledger import identifier
from .paid_bookings import QUOTE_TTL_MS, STALE_CONFIRMING_MS, TAIL_UNIQUE_DAYS, USDC_UNITS, verify_transfer
from .sponsored_booking import DAY_MS, HORIZON_DAYS, PLACEMENTS_PER_DAY, day_ms_of

PLAN_STATEMENTS = (
    "CREATE TABLE IF NOT EXISTS adc2_paid_plans ("
    "id TEXT PRIMARY KEY, advertiser_id TEXT NOT NULL REFERENCES adc2_advertisers(id), "
    "campaign_id TEXT NOT NULL REFERENCES adc2_campaigns(id), items INTEGER NOT NULL CHECK (items>=1), "
    "unit_units BIGINT NOT NULL CHECK (unit_units>0), discount_bps INTEGER NOT NULL CHECK (discount_bps>=0 AND discount_bps<5000), "
    "amount_units BIGINT NOT NULL CHECK (amount_units>0), pay_to TEXT NOT NULL, chain_id BIGINT NOT NULL, token TEXT NOT NULL, "
    "state TEXT NOT NULL CHECK (state IN ('quoted','confirming','confirmed','expired','review','refund_due','refunded')), "
    "tx_hash TEXT UNIQUE, payer TEXT, krw_rate TEXT, note TEXT, "
    "quoted_ms BIGINT NOT NULL, expires_ms BIGINT NOT NULL, confirmed_ms BIGINT, refund_tx_hash TEXT UNIQUE)",
    "CREATE INDEX IF NOT EXISTS adc2_paid_plans_state ON adc2_paid_plans(state, expires_ms)",
    "CREATE INDEX IF NOT EXISTS adc2_paid_plans_advertiser ON adc2_paid_plans(advertiser_id, quoted_ms)",
    "CREATE TABLE IF NOT EXISTS adc2_paid_plan_items (booking_id TEXT PRIMARY KEY REFERENCES adc2_paid_bookings(id), "
    "plan_id TEXT NOT NULL REFERENCES adc2_paid_plans(id))",
    "CREATE INDEX IF NOT EXISTS adc2_paid_plan_items_plan ON adc2_paid_plan_items(plan_id)",
)
ROLLBACK = ("DROP TABLE ad_coin_v2.adc2_paid_plan_items; "
            "DROP TABLE ad_coin_v2.adc2_paid_plans  -- only while both hold no rows")

MIN_PLAN_UNITS = 10 * USDC_UNITS        # proposal for PM: two placements; one placement stays a single booking
MAX_PLAN_ITEMS = 60
MAX_BUDGET_UNITS = MAX_PLAN_ITEMS * 5 * USDC_UNITS
DISCOUNT_STEPS = ()                     # ((items, basis points), ...) e.g. ((10, 500), (30, 1000)); PM decides, none now
MAX_CATEGORIES, MAX_REGIONS = 3, 3
OPEN_PLANS_PER_ADVERTISER = 2
PLAN_GRACE_MS = STALE_CONFIRMING_MS     # placements stay held this long past the quote, so a payment can confirm


def discount_for(items, steps=DISCOUNT_STEPS):
    bps = 0
    for least, step_bps in sorted(steps):
        if items >= least:
            bps = step_bps
    return bps


def unit_after(unit_units, bps):
    return unit_units - unit_units * bps // 10_000


def affordable(budget_units, unit_units, steps=DISCOUNT_STEPS):
    """The most placements the budget pays for at the price that many would cost, and that price."""
    best = (0, unit_units, 0)
    for n in range(1, MAX_PLAN_ITEMS + 1):
        bps = discount_for(n, steps)
        each = unit_after(unit_units, bps)
        if n * each <= budget_units:
            best = (n, each, bps)
    return best


def _usdc(units):
    whole, frac = divmod(int(units), USDC_UNITS)
    return "%d.%s" % (whole, str(frac).rjust(6, "0").rstrip("0") or "0") if frac else str(whole)


def _day(ms):
    import time
    return time.strftime("%Y-%m-%d", time.gmtime(ms / 1000))


class PaidPlans:
    """Plans on top of PaidBookings: the same config, chain reader, sanctions list and KRW rate."""

    def __init__(self, bookings, *, steps=DISCOUNT_STEPS, min_plan_units=MIN_PLAN_UNITS):
        self.bookings, self.store, self.config = bookings, bookings.store, bookings.config
        self.steps, self.min_plan_units = tuple(steps), int(min_plan_units)

    def ready(self):
        with self.store.atomic():
            return bool(self.store.one("paid_plans_table")["present"])

    # ---- proposing ----------------------------------------------------------------------------------------------
    def _targets(self, categories, regions):
        cats = [c for c in dict.fromkeys(categories or []) if isinstance(c, str)]
        regs = [r for r in dict.fromkeys(regions or []) if isinstance(r, str)]
        if (not cats or not regs or len(cats) > MAX_CATEGORIES or len(regs) > MAX_REGIONS
                or any(c not in self.bookings.taxonomy for c in cats) or any(r not in self.bookings.regions for r in regs)):
            raise ContractError("unsupported_targeting", 422)
        return [(c, r) for c in cats for r in regs]

    def _free(self, combos, today):
        """{(day_ms, category, region): free places} for every bookable day (tomorrow .. HORIZON_DAYS ahead)."""
        free = {}
        with self.store.atomic():
            for offset in range(1, HORIZON_DAYS + 1):
                day = today + offset * DAY_MS
                for category, region in combos:
                    coin = int(self.store.one("sponsored_booking_day_count", (day, category, region))["n"])
                    paid = int(self.store.one("paid_bookings_day_count", (day, category, region))["n"])
                    free[(day, category, region)] = max(0, PLACEMENTS_PER_DAY - coin - paid)
        return free

    def options(self, advertiser_id, *, campaign_id, budget_usdc, categories, regions, now_ms=None):
        """Two or three plans that fit the budget, each at most the budget (left over is never charged)."""
        identifier(advertiser_id), identifier(campaign_id)
        budget = _units(budget_usdc)
        if budget > MAX_BUDGET_UNITS:
            raise ContractError("budget_too_large", 422)
        if budget < self.min_plan_units:
            raise ContractError("budget_below_minimum", 422)
        combos = self._targets(categories, regions)
        now_ms = self.bookings._now(now_ms)
        today = now_ms - now_ms % DAY_MS
        count, each, bps = affordable(budget, self.config.price_units, self.steps)
        free = self._free(combos, today)
        slots = sorted((k for k, v in free.items() if v > 0), key=lambda k: (k[0], combos.index(k[1:])))
        if not slots:
            raise ContractError("no_free_days", 409)
        plans = []
        seen = set()

        def add(kind, title, detail, chosen):
            chosen = sorted(chosen)
            n = len(chosen)
            if n < 2 or n * unit_after(self.config.price_units, discount_for(n, self.steps)) < self.min_plan_units:
                return
            key = tuple(chosen)
            if key in seen:
                return
            seen.add(key)
            unit = unit_after(self.config.price_units, discount_for(n, self.steps))
            plans.append({"plan": kind, "title": title, "detail": detail, "placements": n,
                          "unit_usdc": _usdc(unit), "discount_bps": discount_for(n, self.steps),
                          "total_usdc": _usdc(n * unit), "total_units": str(n * unit),
                          "first_day": _day(chosen[0][0]), "last_day": _day(chosen[-1][0]),
                          "audiences": sorted({c + " · " + r for _, c, r in chosen}),
                          "items": [{"day": _day(d), "task_category": c, "region": r} for d, c, r in chosen]})

        # 1. Focus: the first audience on consecutive free days, as soon as possible.
        first = combos[0]
        focus = [s for s in slots if s[1:] == first][:count]
        add("focus", "Every day, one audience",
            "One placement a day for %s in %s, starting tomorrow." % first, focus)
        # 2. Spread: every chosen audience, earliest days first (more audiences, fewer days).
        add("spread", "All your audiences",
            "Placements across every category and region you chose, the earliest free days first.", slots[:count])
        # 3. Steady: the same number of placements spaced evenly over the next 30 days.
        if count:
            step = max(1, len(slots) // count)
            add("steady", "Spread over the month",
                "The same number of placements spaced evenly over the next 30 days.", slots[::step][:count])
        if not plans:
            raise ContractError("budget_below_minimum", 422)
        return {"budget_usdc": _usdc(budget), "unit_usdc": _usdc(self.config.price_units),
                "minimum_usdc": _usdc(self.min_plan_units), "plans": plans[:3],
                "note": "You pay the plan total once. Any budget left over is not charged."}

    # ---- quoting and paying -------------------------------------------------------------------------------------
    def _items(self, items, today):
        if type(items) is not list or not 2 <= len(items) <= MAX_PLAN_ITEMS:
            raise ContractError("invalid_plan", 422)
        out = set()
        for item in items:
            if not isinstance(item, dict):
                raise ContractError("invalid_plan", 422)
            category, region = item.get("task_category"), item.get("region")
            if category not in self.bookings.taxonomy or region not in self.bookings.regions:
                raise ContractError("unsupported_targeting", 422)
            day = day_ms_of(item.get("day"))
            if not today + DAY_MS <= day <= today + HORIZON_DAYS * DAY_MS:
                raise ContractError("day_not_bookable", 422)
            out.add((day, category, region))
        if len(out) != len(items):
            raise ContractError("invalid_plan", 422)            # the same placement twice
        return sorted(out)

    def quote(self, advertiser_id, *, campaign_id, items, now_ms=None):
        advertiser_id, campaign_id = identifier(advertiser_id), identifier(campaign_id)
        now_ms = self.bookings._now(now_ms)
        today = now_ms - now_ms % DAY_MS
        chosen = self._items(items, today)
        n = len(chosen)
        bps = discount_for(n, self.steps)
        unit = unit_after(self.config.price_units, bps)
        if n * unit < self.min_plan_units:
            raise ContractError("budget_below_minimum", 422)
        with self.store.atomic():
            if not self.store.one("paid_plans_table")["present"]:
                raise ContractError("plans_not_open", 409)
            self.store.lock(*["sponsored_day:%d:%s:%s" % key for key in chosen], "paid_advertiser:" + advertiser_id)
            self.store.execute("paid_bookings_expire", (now_ms,))
            self.store.execute("paid_plans_expire", (now_ms,))
            advertiser = self.store.one("advertiser_get", (advertiser_id,))
            if advertiser is None or advertiser["status"] != "active":
                raise ContractError("advertiser_not_active", 409)
            campaign = self.store.one("campaign_get", (campaign_id,))
            if campaign is None or campaign["advertiser_id"] != advertiser_id:
                raise ContractError("unknown_resource", 404)
            if campaign["state"] != "active" or campaign["approval_status"] != "approved":
                raise ContractError("campaign_not_bookable", 409)
            if int(self.store.one("paid_plans_open_for_advertiser", (advertiser_id, now_ms))["n"]) >= OPEN_PLANS_PER_ADVERTISER:
                raise ContractError("too_many_open_plans", 409)
            for day, category, region in chosen:
                coin = int(self.store.one("sponsored_booking_day_count", (day, category, region))["n"])
                paid = int(self.store.one("paid_bookings_day_count", (day, category, region))["n"])
                if coin + paid >= PLACEMENTS_PER_DAY:
                    raise ContractError("sponsored_day_full", 409)
            since = now_ms - TAIL_UNIQUE_DAYS * DAY_MS
            for _ in range(20):                       # a tail no booking or plan of the last 7 days used (R32)
                amount = n * unit + secrets.randbelow(9999) + 1
                if (self.store.one("paid_booking_amount_recent", (amount, since)) is None
                        and self.store.one("paid_plan_amount_recent", (amount, since)) is None):
                    break
            else:
                raise ContractError("try_again", 409)
            plan_id = str(uuid4())
            expires = now_ms + QUOTE_TTL_MS
            self.store.execute("paid_plan_insert", (
                plan_id, advertiser_id, campaign_id, n, unit, bps, amount, self.config.pay_to, self.config.chain_id,
                self.config.token, now_ms, expires))
            for day, category, region in chosen:
                item_id = str(uuid4())
                self.store.execute("paid_booking_insert_plan_item", (
                    item_id, advertiser_id, campaign_id, day, category, region, unit, self.config.pay_to,
                    self.config.chain_id, self.config.token, now_ms, expires + PLAN_GRACE_MS, "plan"))
                self.store.execute("paid_plan_item_link", (item_id, plan_id))
            return self._view(plan_id)

    def _view(self, plan_id):
        row = self.store.one("paid_plan_get", (plan_id,))
        if row is None:
            raise ContractError("unknown_resource", 404)
        items = self.store.all("paid_plan_items", (plan_id,))
        return {"id": row["id"], "campaign_id": row["campaign_id"], "state": row["state"], "placements": int(row["items"]),
                "unit_usdc": _usdc(row["unit_units"]), "discount_bps": int(row["discount_bps"]),
                "amount_usdc": _usdc(row["amount_units"]), "amount_units": str(row["amount_units"]),
                "pay_to": row["pay_to"], "network": "Base", "chain_id": int(row["chain_id"]), "token": row["token"],
                "token_symbol": "USDC", "expires_ms": int(row["expires_ms"]), "tx_hash": row["tx_hash"],
                "items": [{"day": _day(int(i["day_ms"])), "task_category": i["task_category"], "region": i["region"],
                           "state": i["state"]} for i in items]}

    def get(self, advertiser_id, plan_id):
        with self.store.atomic():
            row = self.store.one("paid_plan_get", (identifier(plan_id),))
            if row is None or row["advertiser_id"] != identifier(advertiser_id):
                raise ContractError("unknown_resource", 404)
            return self._view(row["id"])

    def list(self, advertiser_id):
        """The advertiser's recent plans, and whether plans are open (the workspace shows the plan button then)."""
        with self.store.atomic():
            if not self.store.one("paid_plans_table")["present"]:
                return {"items": [], "open": False}
            return {"open": True, "items": [self._view(r["id"]) for r in self.store.all(
                "paid_plans_by_advertiser", (identifier(advertiser_id),))]}

    def _refuse_used(self, tx_hash, plan_id):
        used = self.store.one("paid_plan_by_tx", (tx_hash,))
        if ((used is not None and used["id"] != plan_id) or self.store.one("paid_booking_by_tx", (tx_hash,))
                or self.store.one("paid_booking_by_refund_tx", (tx_hash,)) or self.store.one("paid_plan_by_refund_tx", (tx_hash,))):
            raise ContractError("payment_already_used", 409)

    def submit(self, advertiser_id, plan_id, tx_hash, *, now_ms=None):
        """Attach a payment once the chain shows exactly the plan amount (as PaidBookings.submit, one tx per plan)."""
        from .paid_bookings import _TX
        advertiser_id, plan_id = identifier(advertiser_id), identifier(plan_id)
        if type(tx_hash) is not str or not _TX.match(tx_hash):
            raise ContractError("invalid_tx_hash", 422)
        tx_hash, now_ms = tx_hash.lower(), self.bookings._now(now_ms)
        with self.store.atomic():
            row = self.store.one("paid_plan_get", (plan_id,))
            if row is None or row["advertiser_id"] != advertiser_id:
                raise ContractError("unknown_resource", 404)
            self._refuse_used(tx_hash, plan_id)
        if row["state"] not in ("quoted", "confirming", "expired"):
            return self.get(advertiser_id, plan_id)
        if row["tx_hash"] == tx_hash:
            return self._check(plan_id, now_ms)
        if row["tx_hash"] and row["state"] == "confirming":
            raise ContractError("payment_already_submitted", 409)
        if not self.bookings._on_base():
            raise ContractError("payment_not_seen_yet", 409)
        late = row["state"] == "expired" or now_ms > int(row["expires_ms"])
        seen = {}
        state, payer = verify_transfer(self.bookings.rpc, tx_hash, token=row["token"], pay_to=row["pay_to"],
                                       amount_units=int(row["amount_units"]),
                                       min_confirmations=self.config.min_confirmations, seen=seen)
        if late and (state in ("payment_failed", "payment_not_found") or (state == "pending" and payer is None)):
            raise ContractError("quote_expired", 409)
        if state == "pending" and payer is None:
            raise ContractError("payment_not_seen_yet", 409)
        if state not in ("pending", "confirmed"):
            raise ContractError(state, 409)
        screened = self.bookings.sanctions.screen(payer)
        rate = self.bookings.krw_rate() if (state == "confirmed" or late) else None
        with self.store.atomic():
            self.store.lock("paid_tx:" + tx_hash, "paid_plan:" + plan_id)
            self._refuse_used(tx_hash, plan_id)
            current = self.store.one("paid_plan_get", (plan_id,))
            if current["state"] not in ("quoted", "confirming", "expired") or current["tx_hash"] is not None:
                return self._view(plan_id)
            if self.store.execute("paid_plan_attach_tx", (tx_hash, plan_id)).rowcount != 1:
                return self._view(plan_id)
            if late:     # money that came after the quote expired is never lost in an error: an operator decides
                self.store.execute("paid_plan_set_state", ("review", payer, rate, "late_payment", now_ms, plan_id))
            else:
                self._settle(current, state, payer, screened, rate, now_ms)
            if late or state == "confirmed":
                self._record(current, tx_hash, seen.get("receipt"), now_ms, screened)
            return self._view(plan_id)

    def _settle(self, row, state, payer, screened, rate, now_ms):
        plan_id = note_key = row["id"]
        if state == "pending":
            self.store.execute("paid_plan_set_state", ("confirming", payer, None, None, None, plan_id))
            self.store.execute("paid_plan_items_hold", (now_ms + PLAN_GRACE_MS, note_key))   # keep the days held
            return
        note = None if screened == "clear" else "sanctions_" + screened
        if note is None and rate is None:
            note = "krw_rate_unavailable"
        if note is None:
            moved = self.store.execute("paid_plan_items_confirm", (payer, rate, now_ms, note_key)).rowcount
            if moved != int(row["items"]):
                note = "placements_released"            # a day was let go meanwhile: an operator decides
        self.store.execute("paid_plan_set_state", ("confirmed" if note is None else "review", payer, rate, note,
                                                   now_ms, plan_id))
        if note is not None:
            self.store.execute("paid_plan_items_hold", (now_ms + PLAN_GRACE_MS, note_key))

    def _record(self, row, tx_hash, receipt, now_ms, screened):
        """The receipt goes on every placement's audit trail (adc2_paid_booking_events), with the plan it paid."""
        from ...chain import normalize, transfers_in
        from .paid_audit import block_of, ready, record
        if not receipt or not ready(self.store):
            return
        number, block_hash = block_of(receipt)
        received = sum(amt for _f, to, amt in transfers_in(receipt, row["token"]) if to == normalize(row["pay_to"]))
        for item in self.store.all("paid_plan_items", (row["id"],)):
            record(self.store, item["id"], "receipt", tx_hash=tx_hash, block_number=number, block_hash=block_hash,
                   finality=None, now_ms=now_ms,
                   detail={"plan_id": row["id"], "received_units": received, "quoted_units": int(row["amount_units"]),
                           "sanctions": screened})

    def _check(self, plan_id, now_ms):
        with self.store.atomic():
            row = self.store.one("paid_plan_get", (plan_id,))
        if row["state"] != "confirming" or not row["tx_hash"]:
            return self._view(plan_id)
        seen = {}
        if not self.bookings._on_base():
            state, payer = "pending", None
        else:
            state, payer = verify_transfer(self.bookings.rpc, row["tx_hash"], token=row["token"], pay_to=row["pay_to"],
                                           amount_units=int(row["amount_units"]),
                                           min_confirmations=self.config.min_confirmations, seen=seen)
        screened = self.bookings.sanctions.screen(payer) if payer else None
        rate = self.bookings.krw_rate() if state == "confirmed" else None
        with self.store.atomic():
            self.store.lock("paid_plan:" + plan_id)
            current = self.store.one("paid_plan_get", (plan_id,))
            if current["state"] != "confirming" or current["tx_hash"] != row["tx_hash"]:
                return self._view(plan_id)
            if state == "pending":
                self.store.execute("paid_plan_items_hold", (now_ms + PLAN_GRACE_MS, plan_id))
            elif state in ("payment_failed", "payment_not_found", "amount_mismatch", "ambiguous_payer"):
                self.store.execute("paid_plan_detach_tx", (state, plan_id))
            else:
                self._settle(current, state, payer, screened, rate, now_ms)
                self._record(current, current["tx_hash"], seen.get("receipt"), now_ms, screened)
            return self._view(plan_id)

    def recheck(self, *, now_ms=None, limit=50):
        """Worker: expire unpaid plan quotes and confirm confirming plans (their placements expire on their own)."""
        now_ms, changed = self.bookings._now(now_ms), 0
        with self.store.atomic():
            if not self.store.one("paid_plans_table")["present"]:
                return 0
            changed += int(getattr(self.store.execute("paid_plans_expire", (now_ms,)), "rowcount", 0) or 0)
            rows = list(self.store.all("paid_plans_confirming", (limit,)))
        for row in rows:
            try:
                if self._check(row["id"], now_ms)["state"] != "confirming":
                    changed += 1
            except ContractError:
                changed += 1
        return changed


def _units(value):
    """A USDC amount from the client ('25', '25.5', 25) as 6-decimal units; whole cents at most."""
    text = str(value).strip() if isinstance(value, (str, int)) and not isinstance(value, bool) else ""
    import re
    if not re.fullmatch(r"[0-9]{1,6}(\.[0-9]{1,2})?", text):
        raise ContractError("invalid_budget", 422)
    whole, _, cents = text.partition(".")
    return int(whole) * USDC_UNITS + int(cents.ljust(2, "0") or 0) * 10_000
