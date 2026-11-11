"""11-11: a listing whose own text states a price is never shown as Free (MoneyTools Transcripts)."""
from agent_market.concierge import growth_pages as g
from tests.test_growth_pages import agent


def test_a_stated_price_wins_over_a_zero_price_field():
    priced = agent(1, price_usdc=0, description='STT + SRT/VTT; 3-hour async jobs; x402 $0.002/min, no prepaid credits')
    assert g.clean_agent(priced)['free'] is False
    assert g.clean_agent(agent(2, price_usdc=0, description='Twitter data for agents. $0.0006 per call.'))['free'] is False
    assert g.clean_agent(agent(3, price_usdc=0, name='Pay-per-call web reader', description='Web page to markdown'))['free'] is False
    assert g.clean_agent(agent(4, free=True, description='Guides at 0.01 USDC via x402 on Base.'))['free'] is False


def test_free_listings_stay_free_and_mentions_of_payments_are_not_prices():
    assert g.clean_agent(agent(5, price_usdc=0, description='Weather forecast for any city'))['free'] is True
    assert g.clean_agent(agent(6, price_usdc=0, description='Live health leaderboard of x402 paid endpoints'))['free'] is True
    assert g.clean_agent(agent(7, price_usdc=0.01, description='Weather'))['free'] is False
