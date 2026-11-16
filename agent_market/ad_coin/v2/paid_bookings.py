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
import logging
import os
from pathlib import Path
import re
import secrets
import time
from dataclasses import dataclass
from uuid import uuid4

from .contracts import ContractError
from .ledger import identifier
from .sponsored_booking import DAY_MS, HORIZON_DAYS, PLACEMENTS_PER_DAY, day_ms_of

logger = logging.getLogger(__name__)
ENABLED_ENV = "AD_COIN_PAID_BOOKING_ENABLED"
BASE_CHAIN_ID = 8453
BASE_USDC = "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913"
USDC_UNITS = 1_000_000
QUOTE_TTL_MS = 30 * 60_000
SANCTIONS_MAX_AGE_S = 2 * 86400   # 11-14: refreshed daily at 06:20; two missed days send every payment to review (R35: the refresh script says the same)
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


DEFAULT_PAY_TO_FILE = "gateway-data/usdc-receive-address.txt"  # git-ignored, 0600, written by the operator


DEFAULT_OFAC_LIST = "gateway-data/ofac/eth_addresses.txt"


def data_path(path):
    """Resolve a relative gateway-data path from the working directory or, for a process started inside a
    release folder (PROJECT/gateway-data/services/releases/<name>, e.g. the worker daemon), from the project."""
    if not path or os.path.isabs(path) or os.path.exists(path):
        return path
    for parent in Path(__file__).resolve().parents:
        candidate = parent / path
        if candidate.exists():
            return str(candidate)
    return path


def pay_to_from_file(path):
    """The one receive address in the operator's file ('#' lines are notes), lowercased; None if absent or unclear."""
    try:
        with open(data_path(path)) as handle:
            lines = [line.strip() for line in handle if line.strip() and not line.lstrip().startswith("#")]
    except (OSError, TypeError):
        return None
    return lines[0].lower() if len(lines) == 1 and _ADDRESS.match(lines[0]) else None


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
        pay_to = values.get("AD_COIN_PAID_PAY_TO", "").strip()
        listed = pay_to_from_file(values.get("AD_COIN_PAID_PAY_TO_FILE", DEFAULT_PAY_TO_FILE))
        if pay_to and listed and pay_to.lower() != listed:
            raise RuntimeError("AD_COIN_PAID_PAY_TO differs from the receive-address file.")
        pay_to = pay_to or listed or ""
        price = values.get("AD_COIN_PAID_PRICE_USDC", "5")
        if not _ADDRESS.match(pay_to) or not re.fullmatch(r"[0-9]{1,4}(\.[0-9]{1,2})?", price):
            raise RuntimeError("Paid bookings need AD_COIN_PAID_PAY_TO and a price in USDC.")
        whole, _, cents = price.partition(".")
        return cls(pay_to=pay_to.lower(), price_units=int(whole) * USDC_UNITS + int(cents.ljust(2, "0")) * 10_000,
                   min_confirmations=max(1, int(values.get("AD_COIN_PAID_MIN_CONFIRMATIONS", "3"))))


class Sanctions:
    """OFAC SDN digital currency addresses (ETH-format), one per line, kept fresh by an operator job."""

    def __init__(self, path=None, *, addresses=None, clock=None):
        self.path, self._clock = data_path(path), clock or time.time
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


def verify_transfer(rpc, tx_hash, *, token, pay_to, amount_units, min_confirmations, seen=None):
    """(state, payer): state is 'confirmed', 'pending' or an error code; reuses agent_market.chain.
    seen (a dict) receives the receipt that was read, for its block identifiers (F12)."""
    from ...chain import normalize, transfers_in
    try:
        receipt = rpc.receipt(tx_hash)
    except Exception:
        return "pending", None                         # RPC trouble: try again later
    if receipt is None:
        return "pending", None
    if seen is not None:
        seen["receipt"] = receipt
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


SECOND_RPC_URL = "https://base-rpc.publicnode.com"   # free, keyless; a receipt must agree with the primary (R36)
RPC_TIMEOUT_S = 4.0
STALE_CONFIRMING_MS = 60 * 60_000      # R34: confirming with no sender seen, an hour past the quote: released
OPEN_PER_ADVERTISER = 5                # R34: open quotes plus confirming bookings per advertiser
TAIL_UNIQUE_DAYS = 7                   # R32: a tail amount is not reused by any booking of the last 7 days
CHAIN_RECHECK_S = 600                  # R36: the chain id is read again every 10 minutes
CONFIRMING_BATCH = 500


class AgreeingRPC:
    """Two free public Base RPCs (R36, no spend): a receipt counts only when both return it from the same block.
    Anything else (one missing it, different blocks, one failing) reads as 'not yet', so nothing is confirmed on
    the word of one node. Block number, chain id and other calls go to the primary."""

    def __init__(self, primary, secondary):
        self.primary, self.secondary = primary, secondary

    def receipt(self, tx_hash):
        first = self.primary.receipt(tx_hash)
        if first is None:
            return None
        second = self.secondary.receipt(tx_hash)
        if second is None or str(second.get("blockHash", "")).lower() != str(first.get("blockHash", "")).lower():
            return None
        return first

    def block_number(self):
        return self.primary.block_number()

    def chain_id(self):
        return self.primary.chain_id()

    def call(self, method, *params):
        return self.primary.call(method, *params)


def default_rpc(primary_url=None):
    """Request-path RPC: 4 s per call, one retry, two public nodes that must agree (R36)."""
    import httpx
    from ...chain import RPC
    primary_url = primary_url or os.environ.get("AD_COIN_PAID_RPC_URL", "https://mainnet.base.org")
    make = lambda url: RPC(url, client=httpx.Client(timeout=RPC_TIMEOUT_S), max_retries=2)   # noqa: E731
    return AgreeingRPC(make(primary_url), make(SECOND_RPC_URL))


def tx_used_elsewhere(store, tx_hash, *, booking_id=None, plan_id=None):
    """One check for every USDC table (11-16 source review): a transaction pays or refunds one thing only.
    True when tx_hash already pays another booking or plan, or is any booking's or plan's refund."""
    used = store.one("paid_booking_by_tx", (tx_hash,))
    if (used is not None and used["id"] != booking_id) or store.one("paid_booking_by_refund_tx", (tx_hash,)):
        return True
    if store.one("paid_plans_table")["present"]:
        plan = store.one("paid_plan_by_tx", (tx_hash,))
        if (plan is not None and plan["id"] != plan_id) or store.one("paid_plan_by_refund_tx", (tx_hash,)):
            return True
    return False


def tail_used(store, amount, since):
    """True when a booking or plan quoted this exact amount since `since` (R32 across both tables)."""
    if store.one("paid_booking_amount_recent", (amount, since)) is not None:
        return True
    return bool(store.one("paid_plans_table")["present"]) and store.one("paid_plan_amount_recent", (amount, since)) is not None


def krw_value(rate, units):
    """KRW for USDC units at a recorded rate, exact decimal arithmetic, rounded half up to whole won (11-16)."""
    from decimal import ROUND_HALF_UP, Decimal
    return str((Decimal(str(rate)) * Decimal(int(units)) / Decimal(USDC_UNITS)).quantize(Decimal(1), rounding=ROUND_HALF_UP))


def received_units(store, row):
    """Units that actually arrived for a booking (R31): the receipt event's record when there is one; otherwise the
    quote, since a payment is attached only when it matches the quote exactly (R32). None when unknown."""
    if not row["tx_hash"]:
        return None
    try:
        if store.one("paid_events_table")["present"]:
            for event in store.all("paid_events_for", (row["id"],)):
                if event["kind"] == "receipt" and event["detail"]:
                    import json
                    value = json.loads(event["detail"]).get("received_units")
                    if value is not None:
                        return int(value)
    except Exception:   # noqa: BLE001 - the record is a convenience; the rule below still holds
        pass
    if row["note"] in ("amount_mismatch", "ambiguous_payer") or (row["note"] or "").startswith("late_payment_"):
        return None     # attached before R32 with a different amount: read the chain
    return int(row["amount_units"])


class PaidBookings:
    def __init__(self, store, config, *, rpc, sanctions, taxonomy, regions, krw_rate=upbit_krw_rate, clock=None):
        self.store, self.config, self.rpc, self.sanctions = store, config, rpc, sanctions
        self.taxonomy, self.regions = frozenset(taxonomy), frozenset(regions)
        self.krw_rate, self._clock = krw_rate, clock or time.time
        self._network_ok, self._network_at, self._cursor = False, 0.0, 0

    def _now(self, now_ms):
        return int(self._clock() * 1000) if now_ms is None else int(now_ms)

    def check_network(self):
        if int(self.rpc.chain_id()) != self.config.chain_id:
            raise RuntimeError("The RPC is not Base mainnet.")

    def _on_base(self):
        now = time.monotonic()
        if not self._network_ok or now - self._network_at > CHAIN_RECHECK_S:
            try:
                self.check_network()
                self._network_ok, self._network_at = True, now
            except Exception:
                self._network_ok = False
                return False
        return True

    def quote(self, advertiser_id, *, campaign_id, day, task_category, region, now_ms=None):
        advertiser_id, campaign_id = identifier(advertiser_id), identifier(campaign_id)
        if task_category not in self.taxonomy or region not in self.regions:
            raise ContractError("unsupported_targeting", 422)
        day_ms, now_ms = day_ms_of(day), self._now(now_ms)
        today = now_ms - now_ms % DAY_MS
        if not today + DAY_MS <= day_ms <= today + HORIZON_DAYS * DAY_MS:
            raise ContractError("day_not_bookable", 422)
        with self.store.atomic():
            self.store.lock("sponsored_day:%d:%s:%s" % (day_ms, task_category, region), "paid_advertiser:" + advertiser_id)
            self.store.execute("paid_bookings_expire", (now_ms,))
            advertiser = self.store.one("advertiser_get", (advertiser_id,))
            if advertiser is None or advertiser["status"] != "active":
                raise ContractError("advertiser_not_active", 409)
            campaign = self.store.one("campaign_get", (campaign_id,))
            if campaign is None or campaign["advertiser_id"] != advertiser_id:
                raise ContractError("unknown_resource", 404)
            if campaign["state"] != "active" or campaign["approval_status"] != "approved":
                raise ContractError("campaign_not_bookable", 409)
            if int(self.store.one("paid_bookings_open_for_advertiser", (advertiser_id, now_ms))["n"]) >= OPEN_PER_ADVERTISER:
                raise ContractError("too_many_open_bookings", 409)
            coin = int(self.store.one("sponsored_booking_day_count", (day_ms, task_category, region))["n"])
            paid = int(self.store.one("paid_bookings_day_count", (day_ms, task_category, region))["n"])
            if coin + paid >= PLACEMENTS_PER_DAY:
                raise ContractError("sponsored_day_full", 409)
            for _ in range(20):                         # a tail no booking of the last 7 days used (R32)
                amount = self.config.price_units + secrets.randbelow(9999) + 1
                if not tail_used(self.store, amount, now_ms - TAIL_UNIQUE_DAYS * DAY_MS):
                    break
            else:
                raise ContractError("try_again", 409)
            booking_id = str(uuid4())
            self.store.execute("paid_booking_insert", (
                booking_id, advertiser_id, campaign_id, day_ms, task_category, region, amount, self.config.pay_to,
                self.config.chain_id, self.config.token, now_ms, now_ms + QUOTE_TTL_MS))
            return _view(self.store.one("paid_booking_get", (booking_id,)))

    def submit(self, advertiser_id, booking_id, tx_hash, *, now_ms=None):
        """Attach a payment to a quote only once the chain shows it paid exactly the quoted amount (R32): a transfer of
        another amount, or one the chain does not show yet, is refused and stays unattached (the daily reconciliation
        lists money without a booking). The chain is read outside any database transaction (R36)."""
        advertiser_id, booking_id = identifier(advertiser_id), identifier(booking_id)
        if type(tx_hash) is not str or not _TX.match(tx_hash):
            raise ContractError("invalid_tx_hash", 422)
        tx_hash, now_ms = tx_hash.lower(), self._now(now_ms)
        with self.store.atomic():
            row = self.store.one("paid_booking_get", (booking_id,))
            if row is None or row["advertiser_id"] != advertiser_id:
                raise ContractError("unknown_resource", 404)
            self._refuse_used(tx_hash, booking_id)
        if row["state"] not in ("quoted", "confirming", "expired"):
            return _view(row)
        if row["tx_hash"] == tx_hash:
            return self._check(booking_id, now_ms)
        if not self._on_base():
            raise ContractError("payment_not_seen_yet", 409)
        replacing = row["tx_hash"] if row["state"] == "confirming" and row["tx_hash"] else None
        if replacing is not None:                      # R34: only a payment the chain never showed can be replaced
            try:
                old = self.rpc.receipt(replacing)
            except Exception:
                raise ContractError("payment_not_seen_yet", 409)
            if old is not None:
                raise ContractError("payment_already_submitted", 409)
        seen = {}
        late = row["state"] == "expired" or now_ms > int(row["expires_ms"])
        state, payer = verify_transfer(self.rpc, tx_hash, token=row["token"], pay_to=row["pay_to"],
                                       amount_units=int(row["amount_units"]),
                                       min_confirmations=self.config.min_confirmations, seen=seen)
        if late and (state in ("payment_failed", "payment_not_found") or (state == "pending" and payer is None)):
            raise ContractError("quote_expired", 409)             # expired and no payment to keep
        if state == "pending" and payer is None:
            raise ContractError("payment_not_seen_yet", 409)      # not mined, RPCs disagree or unreachable
        if state != "pending" and state != "confirmed":
            raise ContractError(state, 409)                       # failed, not to us, other amount, several senders
        screened = self.sanctions.screen(payer)
        rate = self.krw_rate() if (state == "confirmed" or late) else None
        finality = self._finality(seen.get("receipt"))
        with self.store.atomic():
            self.store.lock("paid_tx:" + tx_hash, "paid_booking:" + booking_id)
            self._refuse_used(tx_hash, booking_id)
            current = self.store.one("paid_booking_get", (booking_id,))
            if current["state"] not in ("quoted", "confirming", "expired") or current["tx_hash"] != row["tx_hash"]:
                return _view(current)                             # moved meanwhile
            if replacing is not None:
                if self.store.execute("paid_booking_replace_tx", (tx_hash, booking_id, replacing)).rowcount != 1:
                    return _view(self.store.one("paid_booking_get", (booking_id,)))
            elif self.store.execute("paid_booking_attach_tx", (tx_hash, booking_id)).rowcount != 1:
                return _view(self.store.one("paid_booking_get", (booking_id,)))
            if late:   # 11-14: money that arrived after the quote expired is never lost in an error
                self.store.execute("paid_booking_set_state", ("review", payer, rate, "late_payment", now_ms, booking_id))
            else:
                self._settle_state(booking_id, state, payer, screened, rate, now_ms)
            if late or state == "confirmed":     # money settled here; a confirming one is recorded when it confirms
                self._record_receipt(current, tx_hash, seen.get("receipt"), finality, now_ms, screened)
            return _view(self.store.one("paid_booking_get", (booking_id,)))

    def retry_krw(self, *, now_ms=None, limit=20):
        """A booking held only because the KRW rate could not be read is confirmed once the rate is back (11-16)."""
        now_ms, done = self._now(now_ms), 0
        with self.store.atomic():
            rows = list(self.store.all("paid_bookings_krw_retry", (limit,)))
        for row in rows:
            rate = self.krw_rate()
            if rate is None:
                break                                   # the rate source is down: try again next pass
            with self.store.atomic():
                self.store.lock("paid_booking:" + row["id"])
                current = self.store.one("paid_booking_get", (row["id"],))
                if current["state"] != "review" or current["note"] != "krw_rate_unavailable":
                    continue
                self.store.execute("paid_booking_set_state", ("confirmed", None, rate, None,
                                                              current["confirmed_ms"] or now_ms, row["id"]))
                done += 1
        return done

    def _refuse_used(self, tx_hash, booking_id):
        if tx_used_elsewhere(self.store, tx_hash, booking_id=booking_id):
            raise ContractError("payment_already_used", 409)

    def _settle_state(self, booking_id, state, payer, screened, rate, now_ms):
        if state == "pending":
            self.store.execute("paid_booking_set_state", ("confirming", payer, None, None, None, booking_id))
            return
        note = None if screened == "clear" else "sanctions_" + screened
        if note is None and rate is None:
            note = "krw_rate_unavailable"       # the record needs a KRW value; an operator confirms it
        self.store.execute("paid_booking_set_state", ("confirmed" if note is None else "review", payer, rate, note,
                                                      now_ms, booking_id))

    def _finality(self, receipt):
        if not receipt:
            return None
        from .paid_audit import block_of, finality_of
        number, _ = block_of(receipt)
        return finality_of(self.rpc, number) if number is not None else None

    def _check(self, booking_id, now_ms):
        """Worker and resubmission: a confirming booking (exact amount already seen) waits for its confirmations."""
        with self.store.atomic():
            row = self.store.one("paid_booking_get", (booking_id,))
        if row["state"] != "confirming" or not row["tx_hash"]:
            return _view(row)
        seen = {}
        if not self._on_base():
            state, payer = "pending", None             # wrong or unreachable network: never confirm, retry later
        else:
            state, payer = verify_transfer(self.rpc, row["tx_hash"], token=row["token"], pay_to=row["pay_to"],
                                           amount_units=int(row["amount_units"]),
                                           min_confirmations=self.config.min_confirmations, seen=seen)
        screened = self.sanctions.screen(payer) if payer else None
        rate = self.krw_rate() if state == "confirmed" else None
        finality = self._finality(seen.get("receipt")) if state == "confirmed" else None
        with self.store.atomic():
            # F12 concurrent confirmation: write only if the booking is still waiting for this tx.
            self.store.lock("paid_booking:" + booking_id)
            current = self.store.one("paid_booking_get", (booking_id,))
            if current["state"] != "confirming" or current["tx_hash"] != row["tx_hash"]:
                return _view(current)
            if state == "pending":
                if payer is not None and current["payer"] is None:
                    self.store.execute("paid_booking_set_state", ("confirming", payer, None, None, None, booking_id))
            elif state in ("payment_failed", "payment_not_found", "amount_mismatch", "ambiguous_payer"):
                # R32: not paid exactly as quoted (or gone): detach; the money, if any, shows in the reconciliation.
                self.store.execute("paid_booking_detach_tx", (state, booking_id))
            else:
                self._settle_state(booking_id, state, payer, screened, rate, now_ms)
                self._record_receipt(current, current["tx_hash"], seen.get("receipt"), finality, now_ms, screened)
            return _view(self.store.one("paid_booking_get", (booking_id,)))

    def _record_receipt(self, row, tx_hash, receipt, finality, now_ms, screened=None):
        from ...chain import normalize, transfers_in
        from .paid_audit import block_of, record
        if not receipt:
            return
        number, block_hash = block_of(receipt)
        received = sum(amt for _f, to, amt in transfers_in(receipt, row["token"]) if to == normalize(row["pay_to"]))
        record(self.store, row["id"], "receipt", tx_hash=tx_hash, block_number=number, block_hash=block_hash,
               finality=finality, now_ms=now_ms,
               detail={"received_units": received, "quoted_units": int(row["amount_units"]), "sanctions": screened})

    def recheck(self, *, now_ms=None, limit=50):
        """Worker: expire unpaid quotes, release confirming bookings whose sender was never seen (R34), confirm
        confirming bookings in turn (a rotating window, so a slow one never starves the rest), then watch recent
        payments until their block is finalized (F12); returns how many changed."""
        now_ms, changed = self._now(now_ms), 0
        with self.store.atomic():
            changed += int(getattr(self.store.execute("paid_bookings_expire", (now_ms,)), "rowcount", 0) or 0)
            changed += int(getattr(self.store.execute("paid_bookings_stale_confirming",
                                                      (now_ms - STALE_CONFIRMING_MS,)), "rowcount", 0) or 0)
            rows = list(self.store.all("paid_bookings_confirming", (CONFIRMING_BATCH,)))
        if rows:
            start = self._cursor % len(rows)
            rows = (rows[start:] + rows[:start])[:limit]
            self._cursor = start + len(rows)
        for row in rows:
            try:
                if self._check(row["id"], now_ms)["state"] != "confirming":
                    changed += 1
            except ContractError:
                changed += 1
        changed += self.retry_krw(now_ms=now_ms)            # 11-16 source review: a missing KRW rate is retried
        try:                                            # custom plans (11-15): their payments, once the tables exist
            from .paid_plans import PaidPlans
            changed += PaidPlans(self).recheck(now_ms=now_ms, limit=limit)
        except Exception:
            logger.warning("Paid plan recheck failed; it runs again with the next recheck", exc_info=True)
        from .paid_audit import watch
        try:
            watched = watch(self, now_ms=now_ms, limit=limit)
            changed += watched["reorg"] + watched["moved"]
            if watched["checked"] or watched["rpc_unavailable"]:
                logger.info("Paid finality watch: %s", " ".join("%s=%d" % kv for kv in sorted(watched.items())))
        except Exception:                               # the watch never stops confirmations; it runs again next time
            logger.warning("Paid finality watch failed; it runs again with the next recheck", exc_info=True)
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
        """Bookings waiting for an operator, with what arrived next to what was quoted (R31) and a fresh sanctions
        screen of the sender (R35)."""
        access.require_operator(principal)
        with self.store.atomic():
            rows = self.store.all("paid_bookings_operator_queue", ())
            items = []
            for r in rows:
                received = received_units(self.store, r)
                items.append({**_view(r), "payer": r["payer"], "note": r["note"], "krw_rate": r["krw_rate"],
                              "received_usdc": _usdc(received) if received is not None else None,
                              "quoted_usdc": _usdc(r["amount_units"]),
                              "refund_cap_usdc": _usdc(received) if received is not None else None,
                              "sanctions": self.sanctions.screen(r["payer"]) if r["payer"] else None})
        return {"items": items}

    def operator_decide(self, access, principal, booking_id, *, action, refund_tx_hash=None, reason=None,
                        sanctions_ack=False, now_ms=None):
        """review -> confirmed (cleared) or refund_due; platform outage -> refund_due; refund_due -> refunded.
        An operator only, with a reason of 3-200 characters, recorded with the payment (adc2_paid_booking_events) and
        in adc2_audit_log (F12). Clearing (R31, R35): never when less than the quote arrived; the sender is screened
        again and a sender that is not 'clear' needs sanctions_ack and a reason of at least 20 characters; a missing
        KRW rate is fetched or the clear is refused. 'refunded' needs a successful USDC transfer on Base from the
        receiving wallet to the sender, after the payment, no more than arrived, used by no other booking."""
        access.require_operator(principal)
        booking_id = identifier(booking_id)
        transitions = {"clear": ("review", "confirmed"), "refund": (None, "refund_due"),
                       "refunded": ("refund_due", "refunded")}
        if action not in transitions:
            raise ContractError("invalid_paid_decision", 422)
        if not isinstance(reason, str) or not 3 <= len(reason.strip()) <= 200:
            raise ContractError("invalid_reason", 422)
        if action == "refunded" and (type(refund_tx_hash) is not str or not _TX.match(refund_tx_hash)):
            raise ContractError("invalid_tx_hash", 422)
        reason, now_ms = reason.strip(), self._now(now_ms)
        refund_tx_hash = refund_tx_hash.lower() if refund_tx_hash else None
        source, target = transitions[action]
        with self.store.atomic():
            row = self.store.one("paid_booking_get", (booking_id,))
            if row is None:
                raise ContractError("unknown_resource", 404)
            allowed = (row["state"] == source) if source else row["state"] in ("review", "confirmed", "served")
            if not allowed:
                raise ContractError("paid_booking_state_changed", 409)
            received = received_units(self.store, row)
            if refund_tx_hash and refund_tx_hash == (row["tx_hash"] or "").lower():
                raise ContractError("refund_is_the_payment", 409)
            if refund_tx_hash and tx_used_elsewhere(self.store, refund_tx_hash):
                raise ContractError("refund_tx_already_used", 409)
        detail, rate = {"action": action}, None
        if action == "clear":
            if received is None or received < int(row["amount_units"]):
                raise ContractError("received_less_than_quote", 409)
            screened = self.sanctions.screen(row["payer"]) if row["payer"] else "unavailable"
            detail["sanctions"] = screened
            if screened != "clear" and not (sanctions_ack is True and len(reason) >= 20):
                raise ContractError("sanctions_review_required", 409)
            if not row["krw_rate"]:
                rate = self.krw_rate()
                if rate is None:
                    raise ContractError("krw_rate_unavailable", 409)
        if action == "refund":
            detail["refund_cap_units"] = received
        if action == "refunded":
            detail["refund_units"] = self._verify_refund(row, refund_tx_hash)
        with self.store.atomic():
            row = self.store.one("paid_booking_get", (booking_id,))
            allowed = (row["state"] == source) if source else row["state"] in ("review", "confirmed", "served")
            if not allowed:
                raise ContractError("paid_booking_state_changed", 409)
            if rate is not None:
                self.store.execute("paid_booking_set_krw", (rate, booking_id))
            changed = self.store.execute("paid_booking_operator_set", (target, refund_tx_hash, booking_id, row["state"]))
            if int(getattr(changed, "rowcount", 1) or 0) != 1:
                raise ContractError("paid_booking_state_changed", 409)
            from .paid_audit import record
            record(self.store, booking_id, "operator", actor="operator:" + str(principal.id), from_state=row["state"],
                   to_state=target, reason=reason, tx_hash=refund_tx_hash, detail=detail, now_ms=now_ms)
            import json
            self.store.execute("audit_log_insert", (
                str(uuid4()), now_ms, "paid_booking_" + action, str(principal.id),
                str(principal.owner_id) if getattr(principal, "owner_id", None) else None, booking_id, None, None,
                "succeeded", json.dumps({"from": row["state"], "to": target, "reason": reason}, sort_keys=True)))
            view = _view(self.store.one("paid_booking_get", (booking_id,)))
        view["refund_cap_usdc"] = _usdc(received) if received is not None else None
        return view

    def _verify_refund(self, row, refund_tx):
        """Units of USDC the refund sent back to the payer; refuses a wrong refund record (F12, R31)."""
        from ...chain import normalize, transfers_in
        from .paid_audit import block_of
        if refund_tx == (row["tx_hash"] or "").lower():
            raise ContractError("refund_is_the_payment", 409)
        if not row["payer"]:
            raise ContractError("refund_without_payer", 409)
        if not self._on_base():
            raise ContractError("refund_unverifiable", 409)       # RPC down or not Base: record it later
        try:
            receipt = self.rpc.receipt(refund_tx)
            payment = self.rpc.receipt(row["tx_hash"]) if row["tx_hash"] else None
        except Exception:
            raise ContractError("refund_unverifiable", 409)
        if receipt is None:
            raise ContractError("refund_not_found", 409)         # not mined yet, or another network
        if payment is None:
            raise ContractError("refund_unverifiable", 409)
        if int(receipt.get("status", "0x0"), 16) != 1:
            raise ContractError("refund_failed", 409)
        back = [(frm, amt) for frm, to, amt in transfers_in(receipt, row["token"]) if to == normalize(row["payer"])]
        if not back:
            raise ContractError("refund_not_to_payer", 409)
        if any(frm != normalize(row["pay_to"]) for frm, _ in back):
            raise ContractError("refund_not_from_receiving_wallet", 409)
        refund_block, _ = block_of(receipt)
        payment_block, _ = block_of(payment)
        if refund_block is None or payment_block is None or refund_block <= payment_block:
            raise ContractError("refund_before_payment", 409)
        sent = sum(amt for _, amt in back)
        # the cap is what actually arrived (an underpaid booking returns less than its quote), read from the payment
        received = sum(amt for frm, to, amt in transfers_in(payment, row["token"])
                       if to == normalize(row["pay_to"]) and frm == normalize(row["payer"]))
        if sent > received:
            raise ContractError("refund_more_than_paid", 409)
        return sent

    def monthly_csv(self, access, principal, month):
        """Received payments of a UTC month: time, quoted and received amount, sender, tx hash, KRW rate and value."""
        access.require_operator(principal)
        if type(month) is not str or not re.fullmatch(r"20[0-9]{2}-(0[1-9]|1[0-2])", month):
            raise ContractError("invalid_month", 422)
        import datetime
        start = datetime.datetime.strptime(month + "-01", "%Y-%m-%d").replace(tzinfo=datetime.timezone.utc)
        end = (start.replace(day=28) + datetime.timedelta(days=4)).replace(day=1)
        span = (int(start.timestamp() * 1000), int(end.timestamp() * 1000))
        with self.store.atomic():
            # A plan's placements carry no tx of their own (the plan row does): one line per payment, never per
            # placement, so a plan is not counted once for each of its days (custom plans, 11-15).
            rows = [r for r in self.store.all("paid_bookings_month", span) if r["tx_hash"] is not None]
            received = {r["id"]: received_units(self.store, r) for r in rows}
            if self.store.one("paid_plans_table")["present"]:
                for plan in self.store.all("paid_plans_month", span):
                    rows.append(plan)
                    received[plan["id"]] = None
            rows.sort(key=lambda r: (int(r["confirmed_ms"]), r["id"]))
        out = io.StringIO()
        writer = csv.writer(out)
        writer.writerow(["confirmed_utc", "booking_id", "state", "amount_usdc", "payer", "tx_hash", "krw_per_usdc",
                         "amount_krw", "refund_tx_hash", "received_usdc", "kind"])
        for r in rows:
            rate = r["krw_rate"]
            got = received[r["id"]]
            base = got if got is not None else int(r["amount_units"])
            krw = krw_value(rate, base) if rate else ""
            writer.writerow([datetime.datetime.fromtimestamp(int(r["confirmed_ms"]) / 1000, datetime.timezone.utc)
                             .strftime("%Y-%m-%d %H:%M:%S"), r["id"], r["state"], _usdc(r["amount_units"]),
                             r["payer"], r["tx_hash"], rate or "", krw, r["refund_tx_hash"] or "",
                             _usdc(got) if got is not None else "", "plan" if "items" in r.keys() else "booking"])
        return out.getvalue()
