"""Agent ads (A): the provider the organic answer side calls for the one Sponsored offer on MCP and A2A answers.

agent_market/concierge/ad_slot.py (organic side, never imports ad_coin) calls provider(ctx) after the answer is final,
with surface, tool, site category, result categories, role, task text (sensitive-topic rule only, never kept),
region and whether the request counts. The call is a memory lookup only: booked cards come from the Sponsored slot
snapshot and approved offers from a snapshot this provider refreshes on its own timer, where the offer endpoint is
also checked with check_public_url (an endpoint that stops resolving to public addresses drops out within a minute).
Served counts per day, campaign, category, region and surface go to adc2_sponsored_impressions with placement 'mcp' or
'a2a' (no person, no query), only once migrate-agent-ads has widened its placement CHECK; until then nothing is
counted and nothing fails (PM 11-14).
Facts are not filled here: ad_slot reads them from our own records and replaces whatever the ad side sends.
"""
import json
import logging
from threading import Event, Lock, Thread
import time

from .sponsored import DAY_MS, SITE_CATEGORIES
from .sponsored_offer import AGENT_PLACEMENTS, OfferError, agent_block, public_endpoint, sensitive, validate_offer

logger = logging.getLogger(__name__)
REFRESH_SECONDS = 30
OFFER_LIMIT = 5000


class AgentOfferProvider:
    def __init__(self, slots, *, clock=None, url_check=None):
        self.slots, self.store = slots, slots.store
        self._clock = clock or time.time
        self._url_check = url_check or public_endpoint
        self._offers = {}
        self._lock = Lock()
        self._served = {}
        self._counting = False      # True once adc2_sponsored_impressions accepts 'mcp' and 'a2a'
        self._timer = None

    # ---- background: snapshots and counts (never on the request path) ----
    def refresh(self):
        """Rebuild the slot snapshot when due and reload approved offers whose endpoints are public right now."""
        self.slots._snapshot()
        with self.store.atomic():
            self._counting = bool(self.store.one("sponsored_impressions_agent_ready")["present"])
            if not self.store.one("sponsored_offers_table")["present"]:
                self._offers = {}
                return 0
            rows = self.store.all("sponsored_offers_approved", (OFFER_LIMIT,))
        offers = {}
        for row in rows:
            try:
                offer = validate_offer(json.loads(row["offer_json"]))
            except (OfferError, ValueError):
                continue
            if self._url_check(offer["endpoint"]):
                offers[row["campaign_id"]] = offer
        self._offers = offers
        return len(offers)

    def flush_now(self):
        with self._lock:
            pending, self._served = self._served, {}
        if not pending:
            return 0
        try:
            with self.store.atomic():
                if not self.store.one("sponsored_impressions_agent_ready")["present"]:
                    raise LookupError()
                for key, served in pending.items():
                    self.store.execute("sponsored_impression_add", key + (served,))
        except Exception:
            with self._lock:   # keep for the next try (bounded), never fail serving
                for key, served in pending.items():
                    if len(self._served) < 50_000:
                        self._served[key] = self._served.get(key, 0) + served
            return 0
        return sum(pending.values())

    def start(self, interval=REFRESH_SECONDS):
        if self._timer is not None:
            return
        self._stop = Event()

        def loop():
            while True:
                for step in (self.refresh, self.flush_now):
                    try:
                        step()
                    except Exception:
                        logger.warning("Agent offer provider %s failed", step.__name__, exc_info=True)
                if self._stop.wait(interval):
                    return
        self._timer = Thread(target=loop, name="agent-offer-provider", daemon=True)
        self._timer.start()

    def stop(self):
        stop = getattr(self, "_stop", None)
        if stop is not None:
            stop.set()
        written = self.flush_now()
        logger.info("Agent offer served counts flushed at shutdown: %d", written)
        return written

    # ---- request path: memory only ----
    def __call__(self, ctx):
        surface = ctx.get("surface")
        site = ctx.get("category") or next(iter(ctx.get("categories") or []), None)
        if surface not in AGENT_PLACEMENTS or not isinstance(site, str):
            return None
        sites = [site] + [c for c in ctx.get("categories") or [] if isinstance(c, str)]
        if any(sensitive(c) for c in sites) or sensitive(text=str(ctx.get("task") or "")[:500]):
            return None                                  # medical, legal and financial advice topics carry no ad
        category = SITE_CATEGORIES.get(site, site)
        region = str(ctx.get("region") or "").upper()[:2]
        if category not in self.slots.taxonomy or region not in self.slots.regions or not self._offers:
            return None
        for card in self.slots.cards(category, region, rebuild=False):
            offer = self._offers.get(card["id"])
            if offer is None:
                continue
            block = agent_block(card, offer, category=category, region=region)
            block["click_url"] = "/api/ad-coin/v2/sponsored/click/%s?surface=%s&category=%s" % (card["id"], surface, site)
            if ctx.get("counted") and self._counting:
                now_ms = int(self._clock() * 1000)
                key = (now_ms - now_ms % DAY_MS, card["id"], category, region, surface)
                with self._lock:
                    self._served[key] = self._served.get(key, 0) + 1
            return block
        return None

