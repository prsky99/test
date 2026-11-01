"""Weather is recognised by weather-specific words; a bare "forecast" no longer means weather."""
from agent_market.gateway.classify import classify, VERSION


def test_version_was_raised_for_the_keyword_change():
    assert VERSION >= 9


def test_prediction_markets_and_statistical_forecasts_are_not_weather():
    assert classify('Polymarket odds and prediction market forecasts with probability') == 'finance_crypto'
    assert classify('Election forecasts versus official results, seat projections by party') != 'travel_maps_weather'
    assert classify('Holt linear trend forecast for a numeric series') != 'travel_maps_weather'


def test_real_weather_services_stay_weather():
    assert classify('Active weather alerts from the US National Weather Service (NOAA)') == 'travel_maps_weather'
    assert classify('Active tropical cyclones and hurricane advisories') == 'travel_maps_weather'
    assert classify('Hourly forecast with precipitation and rainfall totals') == 'travel_maps_weather'
    assert classify('Aviation weather METAR observations, NWS station data') == 'travel_maps_weather'


def test_a_bundle_listing_open_meteo_among_utilities_is_not_moved_by_meteo_alone():
    text = ('Content-MD5 base64 length, value discarded content-md5 base64 hash '
            'utc-time Current UTC timestamp. timezone open-meteo')
    assert classify(text) == 'data_utility'
