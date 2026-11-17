"""Agent ads (A): the provider the organic answer side calls for the one Sponsored offer on MCP and A2A answers.

agent_market/concierge/ad_slot.py (organic side, never imports ad_coin) calls provider(ctx) after the answer is final,
with surface, tool, site category, result categories, role, task text (sensitive-topic rule only, never kept),
region and whether the request counts. The call is a memory lookup only: booked cards come from the Sponsored slot
snapshot and approved offers from a snapshot this provider refreshes on its own timer, where the offer endpoint is
also checked with check_public_url (an endpoint that stops resolving to public addresses drops out within a minute).
Served counts per day, campaign, category, region and surface go to adc2_sponsored_impressions with placement 'mcp' or
'a2a' (no person, no query), only once migrate-agent-ads has widened its placement CHECK; until then nothing is
counted and nothing fails (PM 11-14).
Necklace answers (PM 11-17): the impressions CHECK allows explore/chat/mcp/a2a only and the schema stays as it is, so
offers served in a necklace answer are also counted in memory per day, surface, necklace slug and category, and each
flush appends one JSON line to logs/growth/necklace-ad-served.jsonl under AGENTCON_PROJECT_ROOT (counts only: no
person, address, query or answer text). necklace_ad_served() sums that file for reports.
Facts are not filled here: ad_slot reads them from our own records and replaces whatever the ad side sends.
"""
import json
import logging
import os
from pathlib import Path
from threading import Event, Lock, Thread
import time

from .sponsored import DAY_MS, SITE_CATEGORIES
from .sponsored_offer import (AGENT_PLACEMENTS, OfferError, advertiser_name_ok, agent_block, public_endpoint, sensitive,
                              validate_offer)

logger = logging.getLogger(__name__)
REFRESH_SECONDS = 30
OFFER_LIMIT = 5000
NECKLACE_LOG = 'logs/growth/necklace-ad-served.jsonl'
KEEP_PENDING = 50_000


def necklace_log_path():
    """<AGENTCON_PROJECT_ROOT>/logs/growth/necklace-ad-served.jsonl; without that variable (the production frontend
    runs with the project as its working directory and does not set it, checked 11-17) the project's existing
    logs/growth directory found the way paid_bookings.data_path finds gateway-data. None when neither exists or under
    pytest, so tests never write into the real logs."""
    root = os.environ.get('AGENTCON_PROJECT_ROOT')
    if root:
        return Path(root) / NECKLACE_LOG
    if os.environ.get('PYTEST_CURRENT_TEST'):
        return None
    from .paid_bookings import data_path
    growth = Path(data_path(str(Path(NECKLACE_LOG).parent)))
    return growth / Path(NECKLACE_LOG).name if growth.is_dir() else None


def _day(day_ms):
    return time.strftime('%Y-%m-%d', time.gmtime(day_ms / 1000))


def write_necklace_counts(path, pending, now):
    """Append ONE line for PENDING {(day_ms, surface, necklace, category): served}. Raises OSError on failure."""
    rows = sorted(pending.items())
    line = {'day': _day(max(k[0] for k, _ in rows)), 'flushed_at': int(now),
            'counts': [{'day': _day(day_ms), 'surface': surface, 'necklace': necklace, 'category': category,
                        'served': served} for (day_ms, surface, necklace, category), served in rows]}
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, 'a', encoding='utf-8') as handle:
        handle.write(json.dumps(line, sort_keys=True) + '\n')


def necklace_ad_served(days=7, path=None, today=None):
    """{(necklace, surface): served} summed over the lines whose count day is within the last DAYS UTC days
    (today included). Unreadable lines are skipped; a missing file is an empty result."""
    path = path or necklace_log_path()
    if path is None:
        return {}
    today_ms = int((time.time() if today is None else today) * 1000)
    since = _day(today_ms - today_ms % DAY_MS - (max(1, int(days)) - 1) * DAY_MS)
    try:
        lines = Path(path).read_text(encoding='utf-8').splitlines()
    except OSError:
        return {}
    totals = {}
    for text in lines:
        try:
            line = json.loads(text)
        except ValueError:
            continue
        for row in (line.get('counts') if isinstance(line, dict) else None) or []:
            if not isinstance(row, dict):
                continue
            day = row.get('day') or line.get('day')
            served = row.get('served')
            if not isinstance(day, str) or day < since or type(served) is not int or served < 0:
                continue
            key = (str(row.get('necklace')), str(row.get('surface')))
            totals[key] = totals.get(key, 0) + served
    return totals


class AgentOfferProvider:
    def __init__(self, slots, *, clock=None, url_check=None, necklace_log=None):
        self.slots, self.store = slots, slots.store
        self._clock = clock or time.time
        self._url_check = url_check or public_endpoint
        self._offers = {}
        self._lock = Lock()
        self._served = {}
        self._necklace_served = {}  # (day_ms, surface, necklace slug, category) -> served, for the growth log
        self._necklace_log = necklace_log
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

    def flush_necklace(self):
        """Append the pending necklace counts as one line; on failure keep them for the next flush (bounded)."""
        with self._lock:
            pending, self._necklace_served = self._necklace_served, {}
        if not pending:
            return 0
        path = self._necklace_log or necklace_log_path()
        if path is None:
            return 0                                    # not inside the services (no project root): nothing to keep
        try:
            write_necklace_counts(path, pending, self._clock())
        except OSError:
            with self._lock:
                for key, served in pending.items():
                    if len(self._necklace_served) < KEEP_PENDING:
                        self._necklace_served[key] = self._necklace_served.get(key, 0) + served
            return 0
        return sum(pending.values())

    def flush_now(self):
        try:
            necklace = self.flush_necklace()
            if necklace:
                logger.info("Agent offer necklace served counts flushed: %d", necklace)
        except Exception:
            logger.warning("Agent offer necklace served counts not flushed", exc_info=True)
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
                    if len(self._served) < KEEP_PENDING:
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

    def offer(self, campaign_id):
        """The approved offer with a public endpoint as of the last refresh, or None (memory only)."""
        return self._offers.get(campaign_id)

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
            if offer is None or not advertiser_name_ok(card["advertiser"]):
                continue                                 # R33: a name that fails the screen never reaches agents
            block = agent_block(card, offer, category=category, region=region)
            block["click_url"] = "/api/ad-coin/v2/sponsored/click/%s?surface=%s&category=%s" % (card["id"], surface, site)
            if ctx.get("counted"):
                now_ms = int(self._clock() * 1000)
                day_ms = now_ms - now_ms % DAY_MS
                necklace = ctx.get("necklace") if ctx.get("tool") == "necklace" else None
                with self._lock:
                    if self._counting:
                        key = (day_ms, card["id"], category, region, surface)
                        self._served[key] = self._served.get(key, 0) + 1
                    if isinstance(necklace, str) and necklace and len(self._necklace_served) < KEEP_PENDING:
                        nkey = (day_ms, surface, necklace[:80], category)
                        self._necklace_served[nkey] = self._necklace_served.get(nkey, 0) + 1
            return block
        return None

