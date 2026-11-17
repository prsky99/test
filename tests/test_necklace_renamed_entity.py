"""PM 11-18: company v3 round 1 dropped two companies whose Wikipedia article has a later or brand name ("Deckers
Brands" for DECKERS OUTDOOR CORP, "Acuity Brands" for ACUITY INC.). is_about now also takes an entry whose title has
the name's first distinctive word and whose opening text names the registered entity with a legal form. Synthetic
entries in the shape of a search result (title + snippet); the people, lists and other companies around them stay
out."""
import json

from agent_market.necklaces import runner


def about(legal, title, snippet, ticker=None):
    entry = json.dumps({"title": title, "snippet": snippet})
    return runner.is_about(entry, title, {"slot.registry.legal_name": legal, "slot.registry.ticker": ticker})


def test_a_renamed_company_is_kept():
    assert about("DECKERS OUTDOOR CORP", "Deckers Brands",
                 "The footwear company was renamed Deckers Outdoor Corporation when it went public.")
    assert about("ACUITY INC. (DE)", "Acuity Brands", "Acuity Inc. is an industrial technology company.")


def test_people_lists_and_other_companies_stay_out():
    assert not about("DECKERS OUTDOOR CORP", "Doug Otto", "A business executive who co-founded Deckers Outdoor Corporation.")
    assert not about("ACUITY INC. (DE)", "Lucid Design Group, Inc.", "Acuity Brands, Inc. announces acquisition of the company.")
    assert not about("ACUITY INC. (DE)", "Acuity Brands", "Acuity Brands, Inc. is a lighting company.")   # no 'Acuity Inc.'
    assert not about("DECKERS OUTDOOR CORP", "Deckers Brands", "A band whose album Deckers Outdoor came out in 1999.")
    assert not about("SUN CORP", "Sun Group", "Sun Group is a conglomerate founded in 1995.")


def test_the_exact_title_rule_is_unchanged():
    assert about("SCHOLASTIC CORP", "Scholastic Corporation", "An American publishing company founded in 1920.")
    assert not about("SUN", "Sun Group", "Sun Group is a company.")


def test_a_surname_list_is_never_the_company():
    """PM 11-18: our substitute returned "Traeger" (a surname list) for Traeger, Inc.; the answer set says no article."""
    assert not about("Traeger, Inc.", "Traeger", 'Traeger or Trager (German for "carrier") is a German surname. Notable '
                     "people with the surname include a company founder.")
    assert not about("Acme Corp", "Acme", "Acme may refer to: Acme Corp, a company founded in 1900.")
    assert about("UNITY SOFTWARE INC.", "Unity Technologies", "Unity Software Inc. (doing business as Unity Technologies) "
                 "is an American video game software development company.")
