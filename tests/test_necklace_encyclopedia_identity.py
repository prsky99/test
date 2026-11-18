"""PM 11-16 (company gate round 1): the background step must not give another company's article. Search entries are
kept only when they are about the registry's company; otherwise the next member is asked, and when no member has an
article about it the step answers 'No encyclopedia article found' (not_found, never another company)."""
from agent_market.necklaces import model, runner

DEFN = "tests/data/necklaces/company-due-diligence.v3.json"     # v3's title members (v4 of 11-19 keeps 47189 and adds our substitutes)
STATE = {"substitutes": [["sec-edgar", "company.registry.v1"], ["sec-filings", "sec.filings.v1"],
                         ["wikipedia-summary", "encyclopedia.summary.v1"]]}


def company(name, ticker=None, cik=None):
    return {"slot.registry.legal_name": name, "slot.registry.ticker": ticker, "slot.registry.cik": cik}


def entry(title, description, excerpt=""):
    return {"title": title, "description": description, "excerpt": excerpt}


def kept(raw, values):
    out = runner.normalize("encyclopedia.summary.v1", raw, values)
    return out is not None and not out.get(runner.IDENTITY_MISMATCH)


def test_round_one_mismatches_are_discarded():
    # what 241601 returned for Kodiak Sciences and for SUN (Sunoco LP) in round 1, and other near names
    assert not kept([entry("Bart the Bear", "Kodiak bear actor"), entry("King Kong", "film character")],
                    company("Kodiak Sciences Inc.", "KOD"))
    assert not kept([entry("Sun Group", "Indian media conglomerate")], company("SUN", "SUN"))
    assert not kept([entry("New Chain of Rocks Bridge", "Bridge in IL")], company("Chain Bridge I", "CBRG"))
    assert not kept([entry("Bank of America", "American bank")], company("Private Bancorp of America, Inc.", "PBAM"))
    assert not kept([entry("Martin Shkreli", "American businessman", "Rocket Pharmaceuticals ...")],
                    company("ROCKET PHARMACEUTICALS, INC.", "RCKT"))     # mentions the name, is not about it
    assert not kept([], company("QUICKLOGIC Corp", "QUIK"))               # an empty search answers nothing
    assert not kept("[]", company("QUICKLOGIC Corp", "QUIK"))


def test_the_company_s_own_article_is_kept_and_others_dropped():
    raw = [entry("Southwest Gas", "Energy company"), entry("Generac", "American industrial company")]
    out = runner.normalize("encyclopedia.summary.v1", raw, company("Southwest Gas Holdings, Inc.", "SWX"))
    assert out["identity"] == "matched" and "Southwest Gas" in out["text"] and "Generac" not in out["text"]
    assert kept([entry("Scholastic Corporation", "American publishing company")], company("SCHOLASTIC CORP", "SCHL"))
    assert kept([entry("Sunoco", "company", "Sunoco LP (NYSE: SUN) is a distributor")], company("SUN", "SUN"))
    assert kept({"title": "Allianz", "extract": "Allianz SE is a German insurer."}, company("Allianz SE"))


def test_a_topic_answer_is_not_checked_for_a_company():
    assert kept([entry("CRISPR", "gene editing")], {"input.topic": "CRISPR"})


def test_the_search_name_drops_legal_forms_and_state_tags():
    assert runner.search_name("QUICKLOGIC Corp") == "QUICKLOGIC"
    assert runner.search_name("Southwest Gas Holdings, Inc.") == "Southwest Gas"
    assert runner.search_name("Rand Capital Corp /DE/") == "Rand Capital"
    # PM 11-16: a legal form right after "&" or "and" is part of the name ("Cohen & Co", not "Cohen &")
    assert runner.search_name("Cohen & Co Inc.") == "Cohen & Co"
    assert runner.search_name("JOHNSON & JOHNSON") == "JOHNSON & JOHNSON"
    assert runner.search_name("Procter and Company Inc") == "Procter and Company"
    reg = runner.normalize("company.registry.v1", {"legal_name": "Kodiak Sciences Inc.", "cik": "1468748"}, {})
    assert reg["search_name"] == "Kodiak Sciences"


def run(background):
    defn = model.load(DEFN)
    seen = {}

    def caller(member, args, timeout_s):
        key = member.get("agent_id") or member.get("resource_id")
        seen[key] = args
        if key == "sec-edgar":
            return {"legal_name": "Kodiak Sciences Inc.", "cik": "1468748", "ticker": "KOD"}
        if key == "sec-filings":
            return {"answer": "Matched SEC filer: Kodiak Sciences Inc. (SEC CIK 1468748). 2026-11-06 10-Q "
                              "(accession 0001468748-26-000050)"}
        if key in background:
            if isinstance(background[key], Exception):
                raise background[key]
            return background[key]
        if key in (47189, 143970):              # v3 title members: no answer unless a test gives one
            return {}
        raise RuntimeError("not this member")
    return runner.Runner(caller, watch_state=STATE).run(defn, {"name": "Kodiak Sciences Inc", "country": "US"}), seen


def test_a_mismatch_moves_to_the_next_member():
    out, seen = run({241601: [entry("Bart the Bear", "Kodiak bear actor")],
                     "wikipedia-summary": {"title": "Kodiak Sciences", "extract": "Kodiak Sciences is a biotechnology company."}})
    assert seen[241601] == {"query": "Kodiak Sciences"}                  # searched without the legal form
    errors = [a["error_class"] for a in out["attempts"]["background"]]
    assert errors[0] == runner.IDENTITY_MISMATCH
    assert out["slots"]["background"]["status"] == "answered" and "biotechnology" in out["output"]["background"]["answers"][0]["text"]


def test_no_article_about_the_company_is_not_found_not_another_company():
    out, _ = run({241601: [entry("Bart the Bear", "Kodiak bear actor")],
                  "wikipedia-summary": {"title": "Kodiak bear", "extract": "The Kodiak bear is a subspecies."}})
    assert out["output"]["background"] == {"not_found": True, "note": runner.NOT_FOUND_NOTE}
    assert out["slots"]["background"]["status"] == "not_found" and not out["slots"]["background"]["failed"]
    assert "Bart" not in str(out["output"])
    assert out["failed_slot"] != "background"


def test_the_profile_member_answers_its_own_contract_when_no_article_is_about_the_company():
    """PM 11-16: background also accepts company.profile.v1; sec-company-profile runs once ops approved it for that
    contract, gets 'CIK <n>' and passes the identity check by its CIK."""
    defn = model.load(DEFN)
    state = {"substitutes": STATE["substitutes"] + [["sec-company-profile", "company.profile.v1"]]}
    seen = {}

    def caller(member, args, timeout_s):
        key = member.get("agent_id") or member.get("resource_id")
        seen[key] = args
        if key == "sec-edgar":
            return {"legal_name": "Kodiak Sciences Inc.", "cik": "1468748", "ticker": "KOD"}
        if key == "sec-filings":
            return {"answer": "2026-11-06 10-Q (accession 0001468748-26-000050)"}
        if key == "sec-company-profile":
            return {"title": "Kodiak Sciences Inc.", "cik": "1468748", "source": "SEC EDGAR filings",
                    "summary": "Kodiak Sciences Inc. (SEC CIK 1468748): Pharmaceutical Preparations. Company profile "
                               "from SEC EDGAR filings (not an encyclopedia article)."}
        return [entry("Bart the Bear", "Kodiak bear actor")]
    out = runner.Runner(caller, watch_state=state).run(defn, {"name": "Kodiak Sciences Inc", "country": "US"})
    assert seen["sec-company-profile"] == {"company": "CIK 1468748"}
    assert out["slots"]["background"]["status"] == "answered"
    assert "not an encyclopedia article" in out["output"]["background"]["answers"][0]["text"]


def test_a_member_contract_the_slot_does_not_accept_is_refused():
    defn = model.load(DEFN)
    assert [e for e in model.validate(defn) if "background" in e] == []
    bg = next(s for s in defn["slots"] if s["slot"] == "background")
    bg["also_contracts"] = []
    assert any("does not accept" in e for e in model.validate(defn))


def test_a_budget_refusal_then_the_next_member_s_not_found_is_not_found():
    """PM 11-16 (company round 1): 241601 refused by our day budget, then wikipedia-summary said it has no article.
    The step answers 'No encyclopedia article found', not a failed step (19 of the 30 round 1 cases)."""
    class NoRecord(Exception):
        code = "not_found"
    out, _ = run({241601: runner.BudgetDenied("domain_daily_total"), "wikipedia-summary": NoRecord("no record")})
    errors = [a["error_class"] for a in out["attempts"]["background"]]
    assert errors[0] == "budget_domain_daily_total" and errors[-1] == "not_found"    # v3 title members between
    assert out["output"]["background"] == {"not_found": True, "note": runner.NOT_FOUND_NOTE}
    assert out["slots"]["background"]["status"] == "not_found" and out["failed_slot"] != "background"


def test_a_real_failure_next_to_not_found_still_fails_the_step():
    class NoRecord(Exception):
        code = "not_found"
    out, _ = run({241601: RuntimeError("upstream broke"), "wikipedia-summary": NoRecord("no record")})
    assert out["slots"]["background"]["status"] != "not_found" and out["output"]["background"] == {"missing": True}
    out, _ = run({241601: runner.BudgetDenied("domain_daily_total")})     # nobody said there is no article
    assert out["output"]["background"] == {"missing": True}


def test_another_step_s_not_found_stays_a_failure():
    a = lambda code: runner.Attempt(1, "t", "external", 1, False, 0, code)
    assert runner.no_article("encyclopedia.summary.v1", [a("budget_domain_daily_total"), a("not_found")])
    assert not runner.no_article("sec.filings.v1", [a("budget_domain_daily_total"), a("not_found")])
    assert runner.no_article("sec.filings.v1", [a(runner.IDENTITY_MISMATCH)])          # the rule before 11-16


def test_an_upper_case_edgar_name_matches_its_article_title():
    """Agent team 11-16: wikipedia-summary now gets EDGAR's upper-case names; the identity check ignores case and
    reads an apostrophe as part of its word ("BJS" is "BJ's")."""
    text = "{} is an American {} company."
    for legal, title in (("BJS RESTAURANTS INC", "BJ's Restaurants"), ("DEXCOM INC", "Dexcom"),
                         ("ENTRAVISION COMMUNICATIONS CORP", "Entravision Communications")):
        assert runner.is_about(text.format(title, "public"), title, {"slot.registry.legal_name": legal}), legal
    assert not runner.is_about(text.format("Restaurants", "public"), "Restaurants",
                               {"slot.registry.legal_name": "BJS RESTAURANTS INC"})


def test_v3_title_members_get_the_name_as_an_article_title():
    """PM 11-16 v3: 47189 and 143970 look a title up exactly; an EDGAR name in capitals is given as a title."""
    assert runner.title_name("DEXCOM") == "Dexcom" and runner.title_name("REALTY INCOME") == "Realty Income"
    assert runner.title_name("CBRE") == "CBRE" and runner.title_name("Krispy Kreme") == "Krispy Kreme"
    reg = runner.norm_registry({"legal_name": "DEXCOM INC", "identifiers": {"SEC CIK": "1093557"}}, {})
    assert reg["search_name"] == "DEXCOM" and reg["title_name"] == "Dexcom"
    defn = model.load(DEFN)
    chain = next(s for s in defn["slots"] if s["slot"] == "background")["chain"]
    assert [m.get("resource_id") or m.get("agent_id") for m in chain][:3] == [241601, 47189, 143970]
    assert all(m["input_map"] == {"title": "{{slot.registry.title_name}}"} for m in chain[1:3])
    out, seen = run({241601: runner.BudgetDenied("domain_daily_total"),
                     47189: {"title": "Kodiak Sciences", "extract": "Kodiak Sciences is a biotechnology company."}})
    assert seen[47189] == {"title": "Kodiak Sciences"}
    assert out["slots"]["background"]["status"] == "answered"
