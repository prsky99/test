"""Paid Sponsored day bookings in USDC on Base (user decision 2026-11-11; switch off by default).

One booking is paid once, for its exact quoted amount, and is confirmed only after the payment is
final on chain. There is no stored balance, no top-up, no conversion into coins and no custody:
the platform only receives, at one address, and never sends (refunds are sent by the owner by hand
and recorded here). The ledger is separate from AI AD Coin: one table, adc2_paid_bookings, created by
its own migration (scripts.ad_coin_v2_migrate migrate-paid; it does not change the v2 schema version, so attaching stores are unaffected).

A quote adds a small unique tail to the price (e.g. 5.004217 USDC) so a transfer matches exactly one
quote; USDC transfers carry no memo. Confirmation reuses agent_market.chain (receipt, confirmations,
Transfer events). The sender is screened against a local copy of the OFAC SDN digital currency
addresses; a match, or a missing or stale list, sends the booking to operator review instead.
reports/AI-AD-Coin-USDC-유료예약-설계-2026-11-11.md
"""

import csv
import io
import os
import re
import secrets
import time
from dataclasses import dataclass
from uuid import uuid4

from .contracts import ContractError
from .ledger import identifier
from .sponsored_booking import DAY_MS, HORIZON_DAYS, PLACEMENTS_PER_DAY, day_ms_of

ENABLED_ENV = "AD_COIN_PAID_BOOKING_ENABLED"
BASE_CHAIN_ID = 8453
BASE_USDC = "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913"
USDC_UNITS = 1_000_000
QUOTE_TTL_MS = 30 * 60_000
SANCTIONS_MAX_AGE_S = 8 * 86400
HOLDING = ("quoted", "confirming", "confirmed", "review", "served")   # states that take a placement

STATEMENTS = (
    "CREATE TABLE IF NOT EXISTS adc2_paid_bookings ("
    "id TEXT PRIMARY KEY, advertiser_id TEXT NOT NULL REFERENCES adc2_advertisers(id), "
    "campaign_id TEXT NOT NULL REFERENCES adc2_campaigns(id), "
    "day_ms BIGINT NOT NULL CHECK (day_ms>=0 AND day_ms % 86400000 = 0), task_category TEXT NOT NULL, region TEXT NOT NULL, "
    "amount_units BIGINT NOT NULL CHECK (amount_units>0), pay_to TEXT NOT NULL, chain_id BIGINT NOT NULL, token TEXT NOT NULL, "
    "state TEXT NOT NULL CHECK (state IN ('quoted','confirming','confirmed','served','expired','review','refund_due','refunded')), "
    "tx_hash TEXT UNIQUE, payer TEXT, krw_rate TEXT, note TEXT, "
    "quoted_ms BIGINT NOT NULL, expires_ms BIGINT NOT NULL, confirmed_ms BIGINT, refund_tx_hash TEXT UNIQUE)",
    "CREATE INDEX IF NOT EXISTS adc2_paid_bookings_day ON adc2_paid_bookings(day_ms, task_category, region, state)",
    "CREATE INDEX IF NOT EXISTS adc2_paid_bookings_state ON adc2_paid_bookings(state, expires_ms)",
)
ROLLBACK = "DROP TABLE ad_coin_v2.adc2_paid_bookings  -- only while it holds no rows"

_TX = re.compile(r"0x[0-9a-fA-F]{64}\Z")
_ADDRESS = re.compile(r"0x[0-9a-fA-F]{40}\Z")


def enabled() -> bool:
    return os.environ.get(ENABLED_ENV, "0") in ("1", "true", "True")


@dataclass(frozen=True)
class PaidConfig:
    pay_to: str
    price_units: int = 5 * USDC_UNITS
    chain_id: int = BASE_CHAIN_ID
    token: str = BASE_USDC
    min_confirmations: int = 3

    @classmethod
    def from_env(cls, values=None):
        values = os.environ if values is None else values
        pay_to = values.get("AD_COIN_PAID_PAY_TO", "")
        price = values.get("AD_COIN_PAID_PRICE_USDC", "5")
        if not _ADDRESS.match(pay_to) or not re.fullmatch(r"[0-9]{1,4}(\.[0-9]{1,2})?", price):
            raise RuntimeError("Paid bookings need AD_COIN_PAID_PAY_TO and a price in USDC.")
        whole, _, cents = price.partition(".")
        return cls(pay_to=pay_to.lower(), price_units=int(whole) * USDC_UNITS + int(cents.ljust(2, "0")) * 10_000,
                   min_confirmations=max(1, int(values.get("AD_COIN_PAID_MIN_CONFIRMATIONS", "3"))))


class Sanctions:
    """OFAC SDN digital currency addresses (ETH-format), one per line, kept fresh by an operator job."""

    def __init__(self, path=None, *, addresses=None, clock=None):
        self.path, self._clock = path, clock or time.time
        self._fixed = None if addresses is None else {a.lower() for a in addresses}

    def screen(self, address):
        if self._fixed is not None:
            return "match" if address.lower() in self._fixed else "clear"
        try:
            if self._clock() - os.stat(self.path).st_mtime > SANCTIONS_MAX_AGE_S:
                return "unavailable"
            with open(self.path) as handle:
                listed = {line.strip().lower() for line in handle if _ADDRESS.match(line.strip())}
        except (OSError, TypeError):
            return "unavailable"
        if not listed:
            return "unavailable"
        return "match" if address.lower() in listed else "clear"


def upbit_krw_rate():
    """Public KRW price of USDC at confirmation time (no key). None when unavailable."""
    try:
        import httpx
        response = httpx.get("https://api.upbit.com/v1/ticker", params={"markets": "KRW-USDC"}, timeout=3)
        value = response.json()[0]["trade_price"]
        return str(value) if isinstance(value, (int, float)) and value > 0 else None
    except Exception:
        return None


def _usdc(units):
    return "%d.%06d" % divmod(int(units), USDC_UNITS)


def _view(row):
    return {"id": row["id"], "campaign_id": row["campaign_id"], "day_ms": int(row["day_ms"]),
            "task_category": row["task_category"], "region": row["region"], "state": row["state"],
            "amount_usdc": _usdc(row["amount_units"]), "amount_units": str(int(row["amount_units"])),
            "pay_to": row["pay_to"], "network": "Base", "chain_id": int(row["chain_id"]), "token": row["token"],
            "token_symbol": "USDC", "expires_ms": int(row["expires_ms"]), "tx_hash": row["tx_hash"]}


def verify_transfer(rpc, tx_hash, *, token, pay_to, amount_units, min_confirmations):
    """(state, payer): state is 'confirmed', 'pending' or an error code; reuses agent_market.chain."""
    from ...chain import normalize, transfers_in
    try:
        receipt = rpc.receipt(tx_hash)
    except Exception:
        return "pending", None                         # RPC trouble: try again later
    if receipt is None:
        return "pending", None
    if int(receipt.get("status", "0x0"), 16) != 1:
        return "payment_failed", None
    try:
        confirmations = rpc.block_number() - int(receipt["blockNumber"], 16) + 1
    except Exception:
        return "pending", None
    paid = [(frm, amt) for frm, to, amt in transfers_in(receipt, token) if to == normalize(pay_to)]
    if not paid:
        return "payment_not_found", None               # other token, other recipient or other network
    payers = {frm for frm, _ in paid}
    if len(payers) != 1:
        return "ambiguous_payer", None
    if sum(amt for _, amt in paid) != amount_units:
        return "amount_mismatch", payers.pop()
    if confirmations < min_confirmations:
        return "pending", payers.pop()
    return "confirmed", payers.pop()


class PaidBookings:
    def __init__(self, store, config, *, rpc, sanctions, taxonomy, regions, krw_rate=upbit_krw_rate, clock=None):
        self.store, self.config, self.rpc, self.sanctions = store, config, rpc, sanctions
        self.taxonomy, self.regions = frozenset(taxonomy), frozenset(regions)
        self.krw_rate, self._clock = krw_rate, clock or time.time

    def _now(self, now_ms):
        return int(self._clock() * 1000) if now_ms is None else int(now_ms)

    def check_network(self):
        if int(self.rpc.chain_id()) != self.config.chain_id:
            raise RuntimeError("The RPC is not Base mainnet.")

    def quote(self, advertiser_id, *, campaign_id, day, task_category, region, now_ms=None):
        advertiser_id, campaign_id = identifier(advertiser_id), identifier(campaign_id)
        if task_category not in self.taxonomy or region not in self.regions:
            raise ContractError("unsupported_targeting", 422)
        day_ms, now_ms = day_ms_of(day), self._now(now_ms)
        today = now_ms - now_ms % DAY_MS
        if not today + DAY_MS <= day_ms <= today + HORIZON_DAYS * DAY_MS:
            raise ContractError("day_not_bookable", 422)
        with self.store.atomic():
            self.store.lock("sponsored_day:%d:%s:%s" % (day_ms, task_category, region))
            self.store.execute("paid_bookings_expire", (now_ms,))
            advertiser = self.store.one("advertiser_get", (advertiser_id,))
            if advertiser is None or advertiser["status"] != "active":
                raise ContractError("advertiser_not_active", 409)
            campaign = self.store.one("campaign_get", (campaign_id,))
            if campaign is None or campaign["advertiser_id"] != advertiser_id:
                raise ContractError("unknown_resource", 404)
            if campaign["state"] != "active" or campaign["approval_status"] != "approved":
                raise ContractError("campaign_not_bookable", 409)
            coin = int(self.store.one("sponsored_booking_day_count", (day_ms, task_category, region))["n"])
            paid = int(self.store.one("paid_bookings_day_count", (day_ms, task_category, region))["n"])
            if coin + paid >= PLACEMENTS_PER_DAY:
                raise ContractError("sponsored_day_full", 409)
            for _ in range(20):                         # a tail no open quote uses
                amount = self.config.price_units + secrets.randbelow(9999) + 1
                if self.store.one("paid_booking_open_amount", (amount, now_ms)) is None:
                    break
            else:
                raise ContractError("try_again", 503)
            booking_id = str(uuid4())
            self.store.execute("paid_booking_insert", (
                booking_id, advertiser_id, campaign_id, day_ms, task_category, region, amount, self.config.pay_to,
                self.config.chain_id, self.config.token, now_ms, now_ms + QUOTE_TTL_MS))
            return _view(self.store.one("paid_booking_get", (booking_id,)))

    def submit(self, advertiser_id, booking_id, tx_hash, *, now_ms=None):
        advertiser_id, booking_id = identifier(advertiser_id), identifier(booking_id)
        if type(tx_hash) is not str or not _TX.match(tx_hash):
            raise ContractError("invalid_tx_hash", 422)
        tx_hash, now_ms = tx_hash.lower(), self._now(now_ms)
        with self.store.atomic():
            self.store.lock("paid_tx:" + tx_hash)
            row = self.store.one("paid_booking_get", (booking_id,))
            if row is None or row["advertiser_id"] != advertiser_id:
                raise ContractError("unknown_resource", 404)
            used = self.store.one("paid_booking_by_tx", (tx_hash,))
            if used is not None and used["id"] != booking_id:
                raise ContractError("payment_already_used", 409)
            if row["state"] == "expired":
                raise ContractError("quote_expired", 409)
            if row["state"] not in ("quoted", "confirming"):
                return _view(row)
            if row["state"] == "quoted" and now_ms > int(row["expires_ms"]):
                raise ContractError("quote_expired", 409)
            self.store.execute("paid_booking_attach_tx", (tx_hash, booking_id))
        return self._check(booking_id, now_ms)

    def _check(self, booking_id, now_ms):
        row = self.store.one("paid_booking_get", (booking_id,))
        state, payer = verify_transfer(self.rpc, row["tx_hash"], token=row["token"], pay_to=row["pay_to"],
                                       amount_units=int(row["amount_units"]),
                                       min_confirmations=self.config.min_confirmations)
        refused = None
        with self.store.atomic():
            if state == "pending":
                self.store.execute("paid_booking_set_state", ("confirming", payer, None, None, None, booking_id))
            elif state in ("payment_failed", "payment_not_found"):
                # Nothing reached the receiving address in USDC on Base: keep the quote open, free the hash.
                self.store.execute("paid_booking_detach_tx", (state, booking_id))
                refused = state
            elif state in ("amount_mismatch", "ambiguous_payer"):
                # Money arrived but not as quoted: an operator decides (accept or refund by hand).
                self.store.execute("paid_booking_set_state", ("review", payer, self.krw_rate(), state, now_ms, booking_id))
            else:
                screened = self.sanctions.screen(payer)
                target = "confirmed" if screened == "clear" else "review"
                note = None if screened == "clear" else "sanctions_" + screened
                self.store.execute("paid_booking_set_state", (target, payer, self.krw_rate(), note, now_ms, booking_id))
            view = _view(self.store.one("paid_booking_get", (booking_id,)))
        if refused:
            raise ContractError(refused, 409)
        return view

    def recheck(self, *, now_ms=None, limit=50):
        """Worker: confirm 'confirming' bookings, expire unpaid quotes; returns how many changed."""
        now_ms, changed = self._now(now_ms), 0
        with self.store.atomic():
            changed += int(getattr(self.store.execute("paid_bookings_expire", (now_ms,)), "rowcount", 0) or 0)
            rows = self.store.all("paid_bookings_confirming", (limit,))
        for row in rows:
            try:
                if self._check(row["id"], now_ms)["state"] != "confirming":
                    changed += 1
            except ContractError:
                changed += 1
        return changed

    def settle_due(self, *, now_ms=None, limit=50):
        """After the day: served, or refund_due when the platform side stopped the placement."""
        now_ms, settled = self._now(now_ms), 0
        with self.store.atomic():
            for row in self.store.all("paid_bookings_due", (now_ms - DAY_MS - 10 * 60_000, limit)):
                fault = row["campaign_state"] in ("rejected", "suspended") or row["advertiser_status"] == "suspended"
                self.store.execute("paid_booking_settle", ("refund_due" if fault else "served",
                                                           "platform:" + row["campaign_state"] if fault else None, row["id"]))
                settled += 1
        return settled

    def list_for(self, advertiser_id):
        with self.store.atomic():
            return {"items": [_view(r) for r in self.store.all("paid_bookings_by_advertiser", (identifier(advertiser_id),))]}

    # Operator side ---------------------------------------------------------------------------------

    def operator_queue(self, access, principal):
        access.require_operator(principal)
        with self.store.atomic():
            rows = self.store.all("paid_bookings_operator_queue", ())
        return {"items": [{**_view(r), "payer": r["payer"], "note": r["note"], "krw_rate": r["krw_rate"]} for r in rows]}

    def operator_decide(self, access, principal, booking_id, *, action, refund_tx_hash=None):
        """review -> confirmed (cleared) or refund_due; platform outage -> refund_due; refund_due -> refunded."""
        access.require_operator(principal)
        booking_id = identifier(booking_id)
        transitions = {"clear": ("review", "confirmed"), "refund": (None, "refund_due"),
                       "refunded": ("refund_due", "refunded")}
        if action not in transitions:
            raise ContractError("invalid_paid_decision", 422)
        if action == "refunded" and (type(refund_tx_hash) is not str or not _TX.match(refund_tx_hash)):
            raise ContractError("invalid_tx_hash", 422)
        source, target = transitions[action]
        with self.store.atomic():
            row = self.store.one("paid_booking_get", (booking_id,))
            if row is None:
                raise ContractError("unknown_resource", 404)
            allowed = (row["state"] == source) if source else row["state"] in ("review", "confirmed", "served")
            if not allowed:
                raise ContractError("paid_booking_state_changed", 409)
            self.store.execute("paid_booking_operator_set", (
                target, refund_tx_hash.lower() if refund_tx_hash else None, booking_id, row["state"]))
            return _view(self.store.one("paid_booking_get", (booking_id,)))

    def monthly_csv(self, access, principal, month):
        """Received payments of a UTC month: time, amount, sender, tx hash, KRW rate and KRW value."""
        access.require_operator(principal)
        if type(month) is not str or not re.fullmatch(r"20[0-9]{2}-(0[1-9]|1[0-2])", month):
            raise ContractError("invalid_month", 422)
        import datetime
        start = datetime.datetime.strptime(month + "-01", "%Y-%m-%d").replace(tzinfo=datetime.timezone.utc)
        end = (start.replace(day=28) + datetime.timedelta(days=4)).replace(day=1)
        with self.store.atomic():
            rows = self.store.all("paid_bookings_month", (int(start.timestamp() * 1000), int(end.timestamp() * 1000)))
        out = io.StringIO()
        writer = csv.writer(out)
        writer.writerow(["confirmed_utc", "booking_id", "state", "amount_usdc", "payer", "tx_hash", "krw_per_usdc",
                         "amount_krw", "refund_tx_hash"])
        for r in rows:
            rate = r["krw_rate"]
            krw = "%.0f" % (float(rate) * int(r["amount_units"]) / USDC_UNITS) if rate else ""
            writer.writerow([datetime.datetime.fromtimestamp(int(r["confirmed_ms"]) / 1000, datetime.timezone.utc)
                             .strftime("%Y-%m-%d %H:%M:%S"), r["id"], r["state"], _usdc(r["amount_units"]),
                             r["payer"], r["tx_hash"], rate or "", krw, r["refund_tx_hash"] or ""])
        return out.getvalue()
