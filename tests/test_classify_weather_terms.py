from agent_market.gateway.classify import classify


def test_conditions_and_outdoor_terms_are_weather_not_network():
    assert classify("Hawaii Conditions: surf report, weather and ocean safety. Tools: ping, get_conditions") == "travel_maps_weather"
    assert classify("Find My Tide: tide times and tide tables for any beach") == "travel_maps_weather"
    assert classify("Sunrise and sunset times for any location") == "travel_maps_weather"


def test_generic_words_do_not_pull_listings_into_weather():
    # Tax "sunset" provisions, audit "trail status" and astrology were the dry-run false positives.
    assert classify("Pass-through tax rules with sunset provisions for each state") != "travel_maps_weather"
    assert classify("ClearPolicy: compliance audit trail status for every policy change") != "travel_maps_weather"
    assert classify("Vedic panchang with sunrise, tithi and nakshatra") != "travel_maps_weather"


def test_a_bare_ping_health_tool_is_not_network_operations():
    assert classify("Invoice API. Tools: ping, create_invoice") != "network_ops"
    assert classify("ICMP ping test and traceroute for any host") == "network_ops"
