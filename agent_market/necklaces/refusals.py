"""Attempt error codes that are our side's refusal, in one place (PM 11-16 source review).

Before this the same list was written out five times (runner, retest, service, value, fingerprints) and had drifted:
the public path's provider cap (limits.DomainCap -> "provider_cap") was in none of them, so on a public run a
member refused by our own cap followed by "not_found" turned an encyclopedia step into a failure; the runner's own
"capacity" was missing from the gate's list; and every "budget_*" code, "budget_no_domain" too, read as our pause.

- OUR_SIDE: our ledger, our caps and our pace refused the call, or the provider asked us to pause. Such an attempt
  says nothing about the member: the necklace step goes on to the next member and the gate counts a case where
  only these stood in the failed step as not measured.
- NOT_SENT: the call never reached the member (no request went out), for the value measure's call count.

A member's own answer ("not_found", "contract_invalid", a timeout, an HTTP error) is never in these sets.
"""
from __future__ import annotations

CAPACITY = "capacity"                 # the runner's process-wide in-flight cap (runner._submit)
EDGE_CAPACITY = "CAPACITY_EXCEEDED"    # the edge's in-flight limit, as the public path reports it
OUR_CAPACITY = "our_capacity"          # the edge's CAPACITY_EXCEEDED as our gate relay reports it
PROVIDER_CAP = "provider_cap"          # limits.DomainCap: our per-provider cap on public runs (10 a minute, 300 a day)
QUOTA = "quota_exhausted"              # runner.live_quota_caller: 80% of a provider's published day limit
RELAY_THROTTLED = "relay_throttled"    # our own relay's pace (HTTP 429 from agentconcierge.biz)
PROVIDER_PAUSE = "PROVIDER_429"        # the provider asked for a pause (retry_after)
SOURCE_PAUSE = "rate_limited"          # an AgentValCon fallback's source asked us to slow down (fallback_agents)
BUDGET_PREFIX = "budget_"              # runner.BudgetDenied / QuotaExhausted: the shared ledger said no
# A member whose URL has no registrable domain cannot be counted at all: that is the definition's or the member's
# problem, not a pause of ours, so it stays a failure.
NOT_OURS_BUDGET = frozenset({"budget_no_domain"})

OUR_SIDE = frozenset({CAPACITY, EDGE_CAPACITY, OUR_CAPACITY, PROVIDER_CAP, QUOTA, RELAY_THROTTLED, PROVIDER_PAUSE,
                      SOURCE_PAUSE})
# Refused before a request went out (a provider pause and a source pause did reach the provider).
NOT_SENT = frozenset({CAPACITY, EDGE_CAPACITY, OUR_CAPACITY, PROVIDER_CAP, QUOTA, RELAY_THROTTLED,
                      "deadline", "connection_empty"})


def is_ours(code) -> bool:
    """True when the attempt was refused on our side (or paused at the provider's request), not answered by it."""
    code = str(code or "")
    if code.startswith(BUDGET_PREFIX):
        return code not in NOT_OURS_BUDGET
    return code in OUR_SIDE


def not_sent(code) -> bool:
    """True when the call never reached the member."""
    code = str(code or "")
    if code.startswith(BUDGET_PREFIX):
        return True
    return code in NOT_SENT
