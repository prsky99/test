"""A necklace's daily capacity (PM 11-15 17:24): how many runs a day its providers allow us.

Per required step, on its running chain (necklaces.watch.runtime_chain):
- our own substitute can run -> no provider limit for that step (it runs on our host);
- otherwise the sum over the step's external provider domains of 80% of the day limit the provider publishes
  (provider_budget.published_per_day, from the terms table's declared_limit; live runs may use 80%, LIVE_SHARE);
- a domain that publishes no number: 80% of our own default cap (limits.DOMAIN_PER_DAY, 300) for live runs (PM 17:32:
  we do not send more to a provider that did not say it allows more; live_quota_caller moves on past it).
The necklace's capacity is the narrowest step with a known number; that step is its bottleneck. Steps with no known
limit are listed apart. Before a necklace is promoted (PM: a post that spreads must not hit a wall), its capacity is
read: a few hundred runs a day or fewer is not used as an example in a post.
"""
from __future__ import annotations

LIVE_SHARE = 0.8


def _published(domain: str):  # noqa: D401
    from .. import provider_budget as pb
    fn = getattr(pb, "published_per_day", None)
    return fn(domain) if fn else None


def _our_cap() -> int:
    from .limits import DOMAIN_PER_DAY
    return DOMAIN_PER_DAY


def _lead(chain: list[dict], published) -> dict | None:
    """The step's first member's own day limit (ops 17:2x: how many runs it answers before the next member takes over)."""
    first = chain[0] if chain else None
    if not first or first.get("kind") != "external" or not first.get("registrable_domain"):
        return None
    limit = published(first["registrable_domain"])
    return {"domain": first["registrable_domain"], "per_day": int(limit * LIVE_SHARE)} if limit else None


def step_capacity(chain: list[dict], published=_published) -> dict:
    lead = _lead(chain, published)
    out = _step(chain, published)
    if lead:
        out["lead"] = lead
    return out


def _step(chain: list[dict], published) -> dict:
    if any(m.get("kind") == "agentcon" for m in chain):
        return {"per_day": None, "why": "own substitute"}
    domains, numbers, unknown = [], [], []
    for m in chain:
        name = m.get("registrable_domain")
        if m.get("kind") != "external" or not name or name in domains:
            continue
        domains.append(name)
        limit = published(name)
        if limit:
            numbers.append(int(limit * LIVE_SHARE))
        else:
            unknown.append(name)
            numbers.append(int(_our_cap() * LIVE_SHARE))
    if not numbers:
        return {"per_day": 0, "why": "no member can run"}
    out = {"per_day": sum(numbers), "why": "published" if not unknown else "our cap", "domains": domains}
    if unknown:
        out["our_cap_domains"] = unknown
    return out


def capacity(defn: dict, chains: dict | None = None, published=_published) -> dict:
    """{per_day, bottleneck, slots, line}; chains maps slot -> running chain (default: the definition's)."""
    slots = {}
    for slot in defn["slots"]:
        if not slot.get("required", True):
            continue
        chain = (chains or {}).get(slot["slot"])
        if chain is None:
            chain = [m for m in slot["chain"] if m.get("state", "active") == "active"]
        slots[slot["slot"]] = step_capacity(chain, published)
    known = {name: s["per_day"] for name, s in slots.items() if s["per_day"] is not None}
    bottleneck = min(known, key=known.get) if known else None
    per_day = known[bottleneck] if bottleneck else None
    if bottleneck and per_day == 0:
        line = f"no runs: required step {bottleneck} has no member that can run"
    elif bottleneck:
        why = slots[bottleneck]["why"]
        basis = ("80% of its providers' published day limit" if why == "published" else
                 f"80% of our own cap of {_our_cap()} a day (limits.DOMAIN_PER_DAY) where a provider publishes no limit")
        line = f"daily capacity {per_day} runs (bottleneck: step {bottleneck}, {basis})"
    else:
        line = "no provider limit: every required step has our own substitute"
    leads = [f"{n} {s['lead']['per_day']} a day on {s['lead']['domain']}" for n, s in slots.items() if s.get("lead")]
    if leads:
        line += "; leads that publish a limit answer first, then the next member: " + "; ".join(leads)
    return {"per_day": per_day, "bottleneck": bottleneck, "slots": slots, "line": line}
