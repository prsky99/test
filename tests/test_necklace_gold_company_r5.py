"""company-due-diligence holdout-r5 (PM 11-16): r4's selection with its own seed, plus truth.background (does English
Wikipedia have an article about the company), so "No encyclopedia article found" is right where none exists."""
import json

from agent_market.necklaces import gold_company_r5 as r5, retest
from tests.test_necklace_gold_company_r4 import fake, setup


def fake_json(mapped=(2, 3), titled=("ACME 4",)):
    seen = []

    def get(url):
        seen.append(url)
        if "query.wikidata.org" in url:
            rows = [{"cik": {"value": str(c).zfill(10)}, "article": {"value": f"https://en.wikipedia.org/wiki/Acme_{c}"}}
                    for c in range(1, 200) if c in mapped]
            return 200, {"results": {"bindings": rows}}
        pages = [{"title": t, "description": "American manufacturing company", "fullurl": "https://en.wikipedia.org/wiki/x"}
                 for t in titled] + [{"title": "ACME 9", "missing": True}]
        return 200, {"query": {"pages": pages}}
    return get, seen


def test_sixty_unseen_cases_with_the_article_truth(tmp_path):
    folder = setup(tmp_path)
    (folder / "holdout-r4.jsonl").write_text(json.dumps({"case_id": "US4:CIK2", "truth": {"cik": "2"}}) + "\n")
    get_json, seen = fake_json(mapped=(3,), titled=("ACME 4",))
    out = r5.build(tmp_path, get=fake(), get_json=get_json, sleep=lambda s: None)
    assert out["written"] and out["cases"] == 60 and len(seen) == 2          # one Wikidata and one Wikipedia call
    cases = {c["truth"]["cik"]: c for c in map(json.loads, (folder / "holdout-r5.jsonl").read_text().splitlines())}
    assert "2" not in cases and "5" not in cases                              # r4's and r1's CIKs are left out
    assert all(c["case_id"].startswith("US5:CIK") for c in cases.values())
    if "3" in cases:
        assert cases["3"]["truth"]["background"] == {"wiki_article": True, "title": "Acme 3",
                                                     "url": "https://en.wikipedia.org/wiki/Acme_3", "matched_by": "wikidata_cik"}
    if "4" in cases:
        assert cases["4"]["truth"]["background"]["matched_by"] == "title"
    assert out["no_article"] == sum(1 for c in cases.values() if not c["truth"]["background"]["wiki_article"]) > 0
    entry = json.loads((folder / "manifest.json").read_text())["files"]["holdout-r5"]
    assert "r5:" in entry["selection"] and entry["same_source_kind"] == "official" and "not_found" in entry["background_rule"]


def test_a_title_page_that_is_not_the_company_is_no_article():
    get_json, _ = fake_json(titled=("ACME 4",))
    assert r5.title_articles({"4": "ACME 4 CORP", "7": "ACME 7 CORP"}, get_json) == {
        "4": {"title": "ACME 4", "url": "https://en.wikipedia.org/wiki/x"}}

    def other(url):
        return 200, {"query": {"pages": [{"title": "Sun", "description": "Star at the centre of the Solar System"}]}}
    assert r5.title_articles({"9": "SUN"}, other) == {}


CASE = {"case_id": "US5:CIK1468748", "input": {"name": "Kodiak Sciences Inc", "country": "US"},
        "truth": {"cik": "1468748", "sec_title": "Kodiak Sciences Inc.",
                  "background": {"wiki_article": False, "title": None, "url": None, "matched_by": None}}}
WITH = {**CASE, "truth": {**CASE["truth"], "background": {"wiki_article": True, "title": "Kodiak Sciences",
                                                           "url": "u", "matched_by": "wikidata_cik"}}}
ARTICLE = {"answers": [{"text": "Kodiak Sciences is an American biotechnology company developing retinal medicines."}]}


def test_not_found_is_right_only_without_an_article():
    not_found = {"not_found": True, "note": "No encyclopedia article found for this company."}
    assert retest.grade_background(CASE, not_found) and not retest.grade_background(WITH, not_found)
    assert retest.grade_background(WITH, ARTICLE)
    assert not retest.grade_background(CASE, ARTICLE)                     # no article exists: this is someone else's
    sec = {"answers": [{"text": "Kodiak Sciences Inc. (CIK 1468748): pharmaceutical preparations, incorporated in DE. "
                                "Company profile from SEC EDGAR filings (not an encyclopedia article)."}]}
    assert retest.grade_background(CASE, sec)
    assert not retest.grade_background(CASE, {"missing": True})
