"""PM 11-17 02:4x: an A2A "payment storefront" answers the task with only a paid address, a price and x402 terms.
Its trial is recorded as payment_required (not a pass), so its grade stays under B and it is no pearl candidate;
a reply that gives a result and adds a paid upgrade keeps its place. Judged by content (texts are paraphrased)."""
import pytest

from agent_market.collector.a2a import payment_storefront, storefront_trial
from agent_market.collector.evaluation import trial_outcome
from tests.test_a2a_auth_required_reply import survey, task


@pytest.mark.parametrize("text", [
    "$0.02 USDC per call on Base. POST your address to https://shop.example/api/check; the unpaid call returns "
    "HTTP 402 with the x402 payment requirement.",
    "Shop sells each capability per call over x402: GET /v1/pdf ($0.006) extracts PDF text.",
    "Still missing: the pool address. Ask again with it, and the measured answer costs 0.10 USDC per answer over x402.",
    '{"recommendation": "payment-required", "reason": "pay $0.01 USDC via x402 for this single call"}',
    "Merchant concierge: we sell API access via x402 pay-per-call and USDC payment links.",
])
def test_replies_that_only_sell(text):
    assert payment_storefront(text)


@pytest.mark.parametrize("text", [
    "Spokane: US AQI 107, driven by PM2.5. FREE (this reply): current reading. PAID ($0.01 per query, x402): hourly outlook.",
    "Free preview: BTC spot about 68,965. Full data is sold per request over x402 at $0.02.",
    "Found 8 matching pages and returned 5 free previews; a full page costs $0.02 USDC through x402.",
    "Page 1 of 3: results 1-10. 1. Web search ... Listing your own costs $5 over x402.",
    "Agent 124595 verified: Trust Score 95/100. Route x402 payments, oracles at $0.01 USDC.",
    "x402 Directory: free to read, $1 to list an endpoint.",
    "Launch a market with the launch_market skill; buy tokens with USDC on Base (x402).",   # no price: not a sale
    "TripGenius: day-by-day itineraries. Free for 3 trips a month; paid plans coming soon.",
    "Meeting overlap for New York and Seoul: 08:00-09:00 KST.",
    None,
])
def test_replies_that_give_a_result_or_do_not_sell(text):
    assert not payment_storefront(text)


SHOP = "$0.03 USDC per call on Base. POST your text to https://shop.example/api/check; the unpaid call returns HTTP 402."


def test_a_fresh_trial_that_only_sells_is_payment_required_and_gated():
    s = survey(task("completed", SHOP + " Uses x402."))
    trial = s["trial"]
    assert trial["ok"] is False and trial["payment_required"] is True and trial["storefront"] is True
    assert trial_outcome(trial) == "gated"
    assert s["auth_required"] is False      # no key: it is a paid route, shown only for paid queries


def test_a_stored_passing_trial_that_only_sells_is_read_as_payment_required():
    stored = {"ok": True, "state": "completed", "sample_output": SHOP + " Uses x402.", "at": 1}
    marked = storefront_trial(stored)
    assert marked["ok"] is False and marked["storefront"] is True and stored["ok"] is True   # stored row untouched
    assert storefront_trial({"ok": True, "sample_output": "Meeting overlap: 08:00-09:00 KST."})["ok"] is True
    assert storefront_trial(None) is None


def test_the_grade_note_says_the_paid_call_is_not_tested():
    from agent_market.collector.evaluation import apply_quality_policy, POLICY_WEIGHTS
    ev = {"kind": "a2a", "score": 95, "grade": "A", "security": "ok",
          "dimensions": {k: 1.0 for k in POLICY_WEIGHTS}, "stats": {}, "findings": []}
    resource = {"kind": "a2a", "url": "https://shop.example/a2a", "health_n_24h": 24, "health_ok_24h": 24,
                "trial_info": storefront_trial({"ok": True, "sample_output": SHOP + " Uses x402.", "latency_ms": 300})}
    out = apply_quality_policy(resource, ev, (24, 24))
    assert out["grade"] != "A"
    assert any("payment terms" in f.get("message", "") for f in out["findings"])
