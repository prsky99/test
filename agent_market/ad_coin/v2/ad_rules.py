"""One place for the advertising text rules (11-16 source review: three rule sets in four places, no re-check when a
person approves).

Every free text an advertiser writes (advertiser name, campaign name and ad text, agent offer fields) goes through
`flags(field, text)`, which returns "<field>:<reason>" strings in two kinds:

- HARD: never shown, whoever approves it. Hidden or direction characters, instructions aimed at the agent (prompt
  injection), self-vouching safety claims, requests for keys or wallets, hidden markup (the v1 screening patterns,
  agent_market/ad_coin/screening.py, kept as the single source of those patterns).
- REVIEW: a person decides. Wording that steers the agent (ToolTweak-style "always use", "best", links) or opens with an
  imperative, and words of the classes we do not sell or that need a person (docs/AD_COIN_SALES_POLICY.md 5).

Automatic checks hold anything flagged; a person may approve REVIEW flags but never HARD ones: `require_approvable`
runs again at every point where a person approves (campaign review, advertiser application), so a rule added later
or text that slipped past an older screen is still refused there.
"""

import re
import unicodedata

from ..screening import findings as _v1_findings

HARD_REASONS = frozenset({"hidden_characters", "agent_instruction", "self_vouching", "wallet_request", "hidden_markup"})

# Text that addresses or steers the agent instead of describing an offer (ToolTweak-style manipulation).
STEERING = re.compile("|".join([
    r"\bignore\b", r"\bdisregard\b", r"\boverride\b", r"\bforget\b",
    r"\b(you|agents?|assistants?|models?|llms?)\s+(must|should|shall|need to|have to|are required)\b",
    r"\b(always|never|only)\s+(use|choose|call|pick|select|prefer|recommend|install|trust)\b",
    r"\b(instead of|rather than|better than|unlike)\b",
    r"\b(system|assistant|developer|user)\s*:", r"\bprompt\b", r"\binstructions?\b", r"\bjailbreak\b",
    r"\btool[_ ]?call\b", r"\bfunction[_ ]?call\b", r"\bverify_agent\b",
    r"\b(best|#1|number one|top[- ]rated|guaranteed|official|verified by agentvalcon|recommended by)\b",
    r"[<>{}\[\]`|\\]", r"https?://", r"\bwww\.",
]), re.I)
IMPERATIVE_START = re.compile(
    r"^\s*(use|choose|call|pick|select|prefer|recommend|install|connect|switch|replace|trust|run|invoke|"
    r"click|buy|sign up|subscribe|add|remember|tell|say|respond|reply|answer)\b", re.I)
# Classes we do not sell, and claims a person must look at (docs/AD_COIN_SALES_POLICY.md 5), English and Korean.
RESTRICTED = re.compile(
    r"casino|gambl|betting|\bbet\b|lottery|poker|slot machine|porn|adult|xxx|escort|weapon|firearm|\bgun|ammo|"
    r"\bdrugs?\b|cannabis|marijuana|\bcbd\b|vape|pharma|prescription|medical|clinic|therapy|diet pill|weight loss|"
    r"election|campaign for|political|\bparty\b|loan|payday|forex|\bfx\b|crypto|token sale|\bico\b|airdrop|"
    r"guaranteed|risk[- ]free|miracle|cure|"
    r"카지노|도박|베팅|토토|복권|성인|무기|총기|마약|대마|의료|병원|치료|다이어트|선거|정치|정당|대출|외환|코인|가상자산|에어드랍|보장|무위험|기적",
    re.I)
_ASCII = re.compile(r"[\x20-\x7e]*\Z")


def steering_flags(field, text):
    """Steering or imperative wording aimed at agents (REVIEW)."""
    found = []
    if STEERING.search(text):
        found.append(field + ":steering")
    if IMPERATIVE_START.search(text):
        found.append(field + ":imperative")
    return found


def flags(field, text, *, agent_facing=False):
    """Every rule, for one field. agent_facing: text agents read verbatim must be printable ASCII (R33)."""
    text = text if isinstance(text, str) else ""
    found = []
    if any(unicodedata.category(c) in ("Cc", "Cf", "Co", "Cs") for c in text.replace("\n", " ").replace("\t", " ")):
        found.append(field + ":hidden_characters")
    plain = re.sub(r"\s+", " ", unicodedata.normalize("NFKC", text)).strip()
    found += [field + ":" + reason for reason in _v1_findings(plain)]
    if agent_facing and not _ASCII.match(text):
        found.append(field + ":not_ascii")
    found += steering_flags(field, plain)
    if RESTRICTED.search(plain):
        found.append(field + ":restricted_class")
    return list(dict.fromkeys(found))


def hard(found):
    """The flags no person may approve."""
    return [f for f in found if f.split(":", 1)[-1] in HARD_REASONS]


def campaign_flags(payload):
    return flags("name", str(payload.get("name", ""))) + flags("text", str(payload.get("creative_text", "")))


def require_approvable(found, code="text_refused"):
    """At a point where a person approves: refuse when any HARD rule matches (409, with the reasons)."""
    from .contracts import ContractError
    blocked = hard(found)
    if blocked:
        raise ContractError(code + ":" + ",".join(blocked)[:180], 409)
