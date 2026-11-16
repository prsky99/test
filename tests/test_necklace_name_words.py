"""runner.name_words for short, accented and ampersand company names (PM 11-16, with source review C01)."""
from agent_market.necklaces import runner


def test_short_accented_and_ampersand_names_keep_their_identity():
    assert runner.name_words("3M Co") == ["3m"]
    assert runner.name_words("HP Inc") == ["hp"]
    assert runner.name_words("Nestlé S.A.") == runner.name_words("NESTLE SA") == ["nestle"]
    assert runner.name_words("AT&T Inc.") == runner.name_words("AT&T") == ["att"]
    assert runner.name_words("Procter & Gamble Co") == ["procter", "gamble"]       # spaced & stays a separator
    assert runner.name_words("BJS RESTAURANTS INC") == runner.name_words("BJ's Restaurants")
    assert runner.name_words("A. O. Smith Corp") == ["smith"]                     # a long word wins over initials
    assert runner.name_words("Inc") == [] and runner.name_words("") == []
