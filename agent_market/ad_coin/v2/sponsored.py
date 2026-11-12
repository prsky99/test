"""Public "Sponsored" slot: labelled ads shown next to, never inside, agent recommendations.

The slot takes only a task category and a broad region, keeps no personal data and pays no
reward (rewards need the separate consent flow). It reads active, approved and funded
campaigns into an in-memory snapshot that is refreshed at most every TTL seconds, so a
request is a dictionary lookup however many campaigns exist.
"""

import json
from threading import Event, Lock, Thread
import time

from .contracts import ContractError

LABEL = "Sponsored"
DISCLOSURE = "Sponsored by the advertiser. Ads never change which agents are recommended."
MAX_CARDS = 2
SNAPSHOT_LIMIT = 5000
TEXT_LIMIT = 280
DAY_MS = 86_400_000
PLACEMENTS = ("explore", "chat")
FLUSH_SECONDS = 60
# Main-site categories (agent_market/broker/categories.py) -> AD Coin v2 task categories.
SITE_CATEGORIES = {
    "agent_infra": "technology", "ai_models": "technology", "dev_tools": "technology", "network_ops": "technology",
    "security": "technology", "database_analytics": "technology", "data_utility": "technology",
    "web_search": "research", "docs_knowledge": "research", "health_science": "research",
    "education_culture": "research", "public_legal": "research",
    "commerce_marketing": "commerce", "finance_crypto": "commerce", "trading_derivatives": "commerce",
    "productivity": "productivity", "communication_messaging": "productivity",
    "media_generation": "creative", "social": "creative", "travel_maps_weather": "general",
}
# Served counts per day, campaign, category, region and placement; no person, IP or query is kept.
IMPRESSION_STATEMENTS = (
    "CREATE TABLE IF NOT EXISTS adc2_sponsored_impressions (day_ms BIGINT NOT NULL CHECK (day_ms % 86400000 = 0), "
    "campaign_id TEXT NOT NULL REFERENCES adc2_campaigns(id), task_category TEXT NOT NULL, region TEXT NOT NULL, "
    "placement TEXT NOT NULL CHECK (placement IN ('explore','chat')), served BIGINT NOT NULL CHECK (served>=0), "
    "PRIMARY KEY (day_ms, campaign_id, task_category, region, placement))",
)


class SponsoredSlots:
    def __init__(self, store, *, taxonomy, regions, ttl_seconds=60, clock=None):
        self.store, self.taxonomy, self.regions = store, frozenset(taxonomy), frozenset(regions)
        self.ttl = ttl_seconds
        self._clock = clock or time.time
        self._lock = Lock()
        self._index, self._built = {}, None
        self._served, self._flushed = {}, self._clock()

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

    def response(self, category, region, placement="explore", limit=MAX_CARDS, count=True):
        """Booked cards for a placement; an empty list when nothing is booked or the region is not sold.
        count=False serves the same cards without adding to the served counts (a request that may be a
        replay, such as TLS 0-RTT early data)."""
        category = SITE_CATEGORIES.get(category, category)
        if category not in self.taxonomy or placement not in PLACEMENTS or type(limit) is not int \
                or not 1 <= limit <= MAX_CARDS:
            raise ContractError("unsupported_targeting", 422)
        cards = self.cards(category, region)[:limit] if region in self.regions else []
        if cards and count:
            self._count(cards, category, region, placement)
        return {"label": LABEL, "disclosure": DISCLOSURE, "reward": None, "placement": placement, "cards": cards}

    def _count(self, cards, category, region, placement):
        now = self._clock()
        day_ms = int(now * 1000) - int(now * 1000) % DAY_MS
        with self._lock:
            for card in cards:
                key = (day_ms, card["id"], category, region, placement)
                self._served[key] = self._served.get(key, 0) + 1
            due = now - self._flushed >= FLUSH_SECONDS
            if due:
                pending, self._served, self._flushed = self._served, {}, now
        if due:
            self.flush(pending)

    def flush_now(self):
        """Write what has been counted so far (timer, shutdown). The memory is taken and emptied under the lock
        before the write, so a request counting at the same moment goes into the next batch, never twice."""
        with self._lock:
            pending, self._served, self._flushed = self._served, {}, self._clock()
        if pending:
            self.flush(pending)
        return sum(pending.values())

    def start_timer(self, interval=FLUSH_SECONDS):
        """Write every `interval` seconds even when no request comes (11-12 PM: counts were lost at deploy).
        Writes only when something is pending; the store lends a connection just for that write."""
        if getattr(self, "_timer", None) is not None:
            return
        self._stop = Event()

        def loop():
            while not self._stop.wait(interval):
                if self._served:
                    try:
                        self.flush_now()
                    except Exception:  # flush() already keeps the counts for the next try
                        pass
        self._timer = Thread(target=loop, name="sponsored-flush", daemon=True)
        self._timer.start()

    def stop(self):
        """Shutdown (a slot going down at deploy, SIGTERM): stop the timer and write what is left, once."""
        stop = getattr(self, "_stop", None)
        if stop is not None:
            stop.set()
        return self.flush_now()

    def flush(self, pending):
        """Add counts to adc2_sponsored_impressions once it exists (operator migration); keep them until then."""
        try:
            with self.store.atomic():
                if not self.store.one("sponsored_impressions_table")["present"]:
                    raise LookupError()
                for (day_ms, campaign_id, category, region, placement), served in pending.items():
                    self.store.execute("sponsored_impression_add", (day_ms, campaign_id, category, region, placement, served))
        except Exception:
            with self._lock:  # never fail serving; retry with the next flush (bounded)
                for key, served in pending.items():
                    if len(self._served) < 50_000:
                        self._served[key] = self._served.get(key, 0) + served
