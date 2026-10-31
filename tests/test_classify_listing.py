"""A listing's own description decides its category; bundled tool text only breaks ties or fills a blank."""
from agent_market.gateway.classify import classify, classify_listing, VERSION

# Shared tool descriptions of one publisher's MCP packs: research, citations, papers, notes, government data...
BUNDLE = 200 * ("semantic search over research papers with citation and fact check, academic brief, notes, "
          "government registry, sec filings, edgar, patents, clinical drug fda data, weather nws timezone. ")


def test_version_bumped_for_listing_rules():
    assert VERSION >= 10


def test_own_description_outweighs_a_large_shared_tool_bundle():
    assert classify_listing("Twilio MCP Pack — send SMS, list messages, make calls via Twilio REST API.", BUNDLE) \
        == "communication_messaging"
    assert classify_listing("Phone number validation MCP.", BUNDLE) == "communication_messaging"
    assert classify_listing("Crypto Fng Crypto Fear & Greed Index MCP.", BUNDLE) == "finance_crypto"
    assert classify_listing("Pacer PACER Case Locator — live US federal court case & party search", BUNDLE) == "public_legal"


def test_ordinary_tool_text_is_read_with_the_description_as_before():
    assert classify_listing("Open data portal", "") == "other"
    assert classify_listing("Acme", "get hourly weather forecast for a location; daily weather by latitude") \
        == "travel_maps_weather"
    assert classify_listing("pipe token count", "geocode a place by latitude and longitude") \
        == classify("pipe token count geocode a place by latitude and longitude")
    assert classify_listing("Stratz Dota 2 MCP.", BUNDLE) == classify("Stratz Dota 2 MCP. " + BUNDLE)


def test_package_security_advisories_are_security_not_weather():
    assert classify("tornado Advisory severity breakdown for PyPI package tornado, from OSV") == "security"
    assert classify("tornado warnings from the National Weather Service") == "travel_maps_weather"
