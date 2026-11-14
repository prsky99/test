"""Verified Sponsored Offer: the one sponsored slot agents read (reports/agent-ad-strategy-2026-11-14, (A) and (B)).

An agent-facing response (MCP, A2A, REST) may carry one `sponsored` object, always after the organic results and
never inside them. The advertiser fills fixed fields only; one free line of at most 120 characters must pass the
instruction and injection screen. We attach independent facts (grade, latest test report score, link and
signature, data time, 7-day health) that ads cannot change, and show them even when they are low.

This module holds the schema, the screen, the opt-out, the sensitive-topic rule and the "why shown" line. It never
reads or writes judging data: facts come from a reader the response surface passes in (tests/test_ad_neutrality.py).
"""
import re
import unicodedata
from urllib.parse import urlsplit

PREFIX = "Sponsored: "
DISCLOSURE_URL = "https://agentconcierge.biz/advertise"
LINE_LIMIT = 120
FIELDS = {"tool": 80, "endpoint": 300, "price": 80, "free_trial": 120, "sla": 80, "line": LINE_LIMIT}
REQUIRED = ("tool", "endpoint", "line")
FACT_KEYS = ("grade", "report_score", "report_url", "report_signature", "data_at", "health_7d")

# Site task categories where no ad is attached (B): medical, legal and financial advice topics.
SENSITIVE_SITE_CATEGORIES = frozenset({"health_science", "public_legal", "finance_crypto", "trading_derivatives"})
SENSITIVE_WORDS = re.compile(
    r"\b(diagnos\w*|symptom\w*|medication|dosage|prescri\w*|therapy|suicid\w*|self[- ]harm|pregnan\w*|"
    r"lawsuit|legal advice|attorney|lawyer|immigration|visa status|"
    r"invest(ment|ing)? advice|tax advice|loan|mortgage|bankrupt\w*|debt relief|stock tips?|"
    r"gambl\w*|betting)\b", re.I)

# Text that addresses or steers the agent instead of describing an offer (ToolTweak-style manipulation).
_STEERING = [
    r"\bignore\b", r"\bdisregard\b", r"\boverride\b", r"\bforget\b",
    r"\b(you|agents?|assistants?|models?|llms?)\s+(must|should|shall|need to|have to|are required)\b",
    r"\b(always|never|only)\s+(use|choose|call|pick|select|prefer|recommend|install|trust)\b",
    r"\b(instead of|rather than|better than|unlike)\b",
    r"\b(system|assistant|developer|user)\s*:", r"\bprompt\b", r"\binstructions?\b", r"\bjailbreak\b",
    r"\btool[_ ]?call\b", r"\bfunction[_ ]?call\b", r"\bverify_agent\b",
    r"\b(best|#1|number one|top[- ]rated|guaranteed|official|verified by agentvalcon|recommended by)\b",
    r"[<>{}\[\]`|\\]", r"https?://", r"\bwww\.",
]
_STEERING_RE = re.compile("|".join(_STEERING), re.I)
_IMPERATIVE_START = re.compile(
    r"^\s*(use|choose|call|pick|select|prefer|recommend|install|connect|switch|replace|trust|run|invoke|"
    r"click|buy|sign up|subscribe|add|remember|tell|say|respond|reply|answer)\b", re.I)


class OfferError(ValueError):
    def __init__(self, problems):
        super().__init__(", ".join(problems))
        self.problems = problems


def _clean(text):
    """Reject hidden characters outright (zero-width, bidi, control); return the NFKC form."""
    if any(unicodedata.category(c) in ("Cc", "Cf", "Co", "Cs") for c in text):
        raise OfferError(["hidden_characters"])
    return unicodedata.normalize("NFKC", text).strip()


def screen_text(name, text):
    """Problems with one free-text field: steering the agent, imperative opening, links or markup."""
    problems = []
    if _STEERING_RE.search(text):
        problems.append(name + ":steering")
    if _IMPERATIVE_START.search(text):
        problems.append(name + ":imperative")
    return problems


def validate_offer(raw):
    """The advertiser's offer as stored: only the fixed fields, each within its limit and screened. Raises OfferError."""
    if not isinstance(raw, dict):
        raise OfferError(["not_an_object"])
    unknown = sorted(set(raw) - set(FIELDS))
    problems = ["unknown_field:" + k for k in unknown]
    offer = {}
    for name, limit in FIELDS.items():
        value = raw.get(name, "")
        if value is None:
            value = ""
        if not isinstance(value, str):
            problems.append(name + ":not_text")
            continue
        try:
            value = _clean(value)
        except OfferError as error:
            problems += [name + ":" + p for p in error.problems]
            continue
        if len(value) > limit:
            problems.append(name + ":too_long")
        if name in REQUIRED and not value:
            problems.append(name + ":required")
        if name == "endpoint" and value:
            parts = urlsplit(value)
            if parts.scheme != "https" or not parts.hostname or parts.username or parts.password or parts.query \
                    or parts.fragment:
                problems.append("endpoint:https_url_required")
        elif value:
            problems += screen_text(name, value)
        offer[name] = value
    if problems:
        raise OfferError(problems)
    return offer


def wants_ads(params=None, headers=None):
    """An agent opts out with ads=none (query or body parameter) or the header `Ads: none` / `X-Ads: none`."""
    params, headers = params or {}, {k.lower(): v for k, v in (headers or {}).items()}
    values = [params.get("ads"), headers.get("ads"), headers.get("x-ads")]
    return not any(isinstance(v, str) and v.strip().lower() == "none" for v in values)


def sensitive(site_category="", text=""):
    """True for topics that never carry an ad: sensitive site categories, or advice-seeking words in the task."""
    return site_category in SENSITIVE_SITE_CATEGORIES or bool(text and SENSITIVE_WORDS.search(text))


def why_shown(category, region):
    return "Booked for the %s task category in %s; it does not change the results above." % (category, region)


def facts_block(facts):
    """Independent facts exactly as the reader returned them (low values included); missing ones are null."""
    facts = facts or {}
    return {key: facts.get(key) for key in FACT_KEYS} | {"independent": True,
                                                       "note": "Measured by AgentValCon; advertising cannot change it."}


def agent_block(card, offer, *, category, region, facts=None, paid_by=None):
    """The `sponsored` object for agent-facing responses, built from a booked card and its approved offer."""
    return {"label": "Sponsored", "text": PREFIX + offer["line"], "advertiser": card["advertiser"],
            "paid_by": paid_by or card["advertiser"], "why_shown": why_shown(category, region),
            "disclosure_url": DISCLOSURE_URL,
            "offer": {k: offer.get(k, "") for k in ("tool", "endpoint", "price", "free_trial", "sla")},
            "facts": facts_block(facts)}
