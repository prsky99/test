"""Public "Sponsored" slot: labelled ads shown next to, never inside, agent recommendations.

The slot takes only a task category and a broad region, keeps no personal data and pays no
reward (rewards need the separate consent flow). It reads active, approved and funded
campaigns into an in-memory snapshot that is refreshed at most every TTL seconds, so a
request is a dictionary lookup however many campaigns exist.
"""

import json
from threading import Lock
import time

from .contracts import ContractError

LABEL = "Sponsored"
DISCLOSURE = "Sponsored by the advertiser. Ads never change which agents are recommended."
MAX_CARDS = 2
SNAPSHOT_LIMIT = 5000
TEXT_LIMIT = 280
DAY_MS = 86_400_000


class SponsoredSlots:
    def __init__(self, store, *, taxonomy, regions, ttl_seconds=60, clock=None):
        self.store, self.taxonomy, self.regions = store, frozenset(taxonomy), frozenset(regions)
        self.ttl = ttl_seconds
        self._clock = clock or time.time
        self._lock = Lock()
        self._index, self._built = {}, None

    def _build(self, now_ms):
        # Only campaigns booked for today (coin economy step 3) appear; a booking names its own
        # task category and region, and the card ends with the booked day.
        day_ms = now_ms - now_ms % DAY_MS
        with self.store.atomic():
            rows = self.store.all("campaigns_sponsored_booked", (day_ms, now_ms, SNAPSHOT_LIMIT))
            from .paid_bookings import enabled as paid_enabled
            if paid_enabled():  # paid USDC bookings appear the same way once confirmed
                rows = list(rows) + self.store.all("campaigns_sponsored_paid", (day_ms, now_ms, SNAPSHOT_LIMIT))
        index = {}
        for row in rows:
            payload = json.loads(row["payload_json"])
            card = {"id": row["id"], "label": LABEL, "advertiser": str(payload.get("name", ""))[:100],
                    "text": str(payload.get("creative_text", ""))[:TEXT_LIMIT],
                    "ends_ms": min(int(row["ends_ms"]), day_ms + DAY_MS)}
            pool = index.setdefault((row["task_category"], row["region"]), [])
            if all(existing["id"] != card["id"] for existing in pool):
                pool.append(card)
        return index

    def _snapshot(self):
        now = self._clock()
        if self._built is None or now - self._built >= self.ttl:
            with self._lock:
                if self._built is None or now - self._built >= self.ttl:
                    self._index, self._built = self._build(int(now * 1000)), now
        return self._index, now

    def cards(self, category, region):
        if category not in self.taxonomy or region not in self.regions:
            raise ContractError("unsupported_targeting", 422)
        index, now = self._snapshot()
        now_ms = int(now * 1000)
        pool = index.get((category, region), ())
        if not pool:
            return []
        start = int(now // 60) % len(pool)  # rotate fairly each minute; no per-person data
        chosen = []
        for step in range(len(pool)):  # usually stops after MAX_CARDS steps
            card = pool[(start + step) % len(pool)]
            if card["ends_ms"] > now_ms:
                chosen.append({key: card[key] for key in ("id", "label", "advertiser", "text")})
                if len(chosen) == MAX_CARDS:
                    break
        return chosen

    def response(self, category, region):
        return {"label": LABEL, "disclosure": DISCLOSURE, "reward": None,
                "cards": self.cards(category, region)}
