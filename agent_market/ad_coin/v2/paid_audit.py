"""USDC paid bookings: receipt block identifiers, chain finality watch and the operator audit trail (F12, PM 11-14).

adc2_paid_booking_events is append-only and kept with the payment records (5 years, never pruned; the general
adc2_audit_log is pruned after 90 days). It is created by `scripts.ad_coin_v2_migrate migrate-paid-events` after
approval; until then receipts and finality are not recorded and operator decisions go only to adc2_audit_log.

Chain states on Base (OP Stack): a block is 'unsafe' when the sequencer has produced it, 'safe' once its batch is
posted to Ethereum, 'finalized' once that Ethereum block is final (usually 15-30 minutes). A booking is confirmed
after min_confirmations blocks (unsafe); the watch then re-reads the receipt until the block is finalized, for at
most FINALITY_WATCH_DAYS. If the payment can no longer be found as paid (receipt gone twice in a row, failed, wrong
recipient or amount) the booking goes to review with note 'reorg' and stops showing; an operator decides. A payment
re-included in another block keeps its state and the new block is recorded.
"""
import json
import time
from uuid import uuid4

FINALITY_WATCH_DAYS = 7
DAY_MS = 86_400_000
KINDS = ("receipt", "finality", "reorg", "operator", "reconcile")
FINALITY = ("unsafe", "safe", "finalized")
EVENT_STATEMENTS = (
    "CREATE TABLE IF NOT EXISTS adc2_paid_booking_events (id TEXT PRIMARY KEY, "
    "booking_id TEXT NOT NULL REFERENCES adc2_paid_bookings(id), at_ms BIGINT NOT NULL, "
    "kind TEXT NOT NULL CHECK (kind IN ('receipt','finality','reorg','operator','reconcile')), actor TEXT NOT NULL, "
    "from_state TEXT, to_state TEXT, reason TEXT, tx_hash TEXT, block_number BIGINT, block_hash TEXT, "
    "finality TEXT CHECK (finality IS NULL OR finality IN ('unsafe','safe','finalized')), detail TEXT)",
    "CREATE INDEX IF NOT EXISTS adc2_paid_booking_events_booking ON adc2_paid_booking_events(booking_id, at_ms)",
)
SYSTEM = "system:payment-watch"


def ready(store):
    return bool(store.one("paid_events_table")["present"])


def record(store, booking_id, kind, *, actor=SYSTEM, from_state=None, to_state=None, reason=None, tx_hash=None,
           block_number=None, block_hash=None, finality=None, detail=None, now_ms=None):
    """Append one event inside the caller's transaction; a no-op (False) before the table exists."""
    if kind not in KINDS or (finality is not None and finality not in FINALITY):
        raise ValueError("bad event")
    if not ready(store):
        return False
    now_ms = int(time.time() * 1000) if now_ms is None else int(now_ms)
    store.execute("paid_event_add", (str(uuid4()), booking_id, now_ms, kind, actor, from_state, to_state, reason, tx_hash,
                                     block_number, block_hash, finality,
                                     json.dumps(detail, sort_keys=True) if detail is not None else None))
    return True


def finality_of(rpc, block_number):
    """'finalized', 'safe' or 'unsafe' for a block number; None when the RPC cannot tell (try again later)."""
    try:
        for tag in ("finalized", "safe"):
            block = rpc.call("eth_getBlockByNumber", tag, False)
            if block and block_number <= int(block["number"], 16):
                return tag
        return "unsafe"
    except Exception:
        return None


def block_of(receipt):
    try:
        return int(receipt["blockNumber"], 16), str(receipt["blockHash"]).lower()
    except (KeyError, TypeError, ValueError):
        return None, None


def last_block_event(store, booking_id):
    return store.one("paid_event_last_block", (booking_id,))


def watch(bookings, *, now_ms=None, limit=50):
    """Re-read receipts of recent paid bookings until their block is finalized. Returns counts per outcome.
    Memory of a missing receipt is the previous event, so a restart does not reset it."""
    from .paid_bookings import verify_transfer
    store, rpc = bookings.store, bookings.rpc
    now_ms = bookings._now(now_ms)
    out = {"checked": 0, "finalized": 0, "moved": 0, "reorg": 0, "missing_once": 0, "rpc_unavailable": 0}
    with store.atomic():
        if not ready(store):
            return out
        rows = store.all("paid_bookings_watch", (now_ms - FINALITY_WATCH_DAYS * DAY_MS, limit))
    if rows and not bookings._on_base():
        out["rpc_unavailable"] = len(rows)
        return out
    for row in rows:
        out["checked"] += 1
        try:
            receipt = rpc.receipt(row["tx_hash"])
        except Exception:
            out["rpc_unavailable"] += 1
            continue
        with store.atomic():
            last = last_block_event(store, row["id"])
            if receipt is None:
                if last is not None and last["detail"] and "receipt_missing" in last["detail"]:
                    _reorg(store, row, "receipt missing twice", now_ms)
                    out["reorg"] += 1
                else:
                    record(store, row["id"], "finality", tx_hash=row["tx_hash"], detail={"receipt_missing": True},
                           block_number=last["block_number"] if last else None,
                           block_hash=last["block_hash"] if last else None, now_ms=now_ms)
                    out["missing_once"] += 1
                continue
        state, _payer = verify_transfer(_Fixed(rpc, receipt), row["tx_hash"], token=row["token"], pay_to=row["pay_to"],
                                        amount_units=int(row["amount_units"]), min_confirmations=1)
        number, block_hash = block_of(receipt)
        level = finality_of(rpc, number) if number is not None else None
        with store.atomic():
            last = last_block_event(store, row["id"])
            if state not in ("confirmed", "pending", "amount_mismatch", "ambiguous_payer") or (
                    state in ("amount_mismatch", "ambiguous_payer") and row["state"] in ("confirmed", "served")):
                _reorg(store, row, "payment no longer as recorded: " + state, now_ms)
                out["reorg"] += 1
                continue
            moved = last is None or last["block_hash"] != block_hash
            if moved or (level is not None and level != last["finality"]):
                record(store, row["id"], "reorg" if (moved and last is not None) else "finality", tx_hash=row["tx_hash"],
                       block_number=number, block_hash=block_hash, finality=level,
                       detail={"reincluded_from": last["block_hash"]} if (moved and last is not None) else None,
                       now_ms=now_ms)
                out["moved"] += int(moved and last is not None)
            if level == "finalized":
                out["finalized"] += 1
    return out


def _reorg(store, row, why, now_ms):
    store.execute("paid_booking_reorg", ("reorg", row["id"]))
    record(store, row["id"], "reorg", from_state=row["state"], to_state="review", reason=why, tx_hash=row["tx_hash"],
           now_ms=now_ms)


class _Fixed:
    """An RPC view that answers verify_transfer from a receipt already read (one RPC call per booking)."""

    def __init__(self, rpc, receipt):
        self._rpc, self._receipt = rpc, receipt

    def receipt(self, _tx_hash):
        return self._receipt

    def block_number(self):
        number, _ = block_of(self._receipt)
        return number if number is not None else self._rpc.block_number()
