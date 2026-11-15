"""holdout-r3-sec (PM 11-15 14:34): fresh SEC cases with legal suffixes, 20-F/40-F issuers and unregistered companies."""
import json

from agent_market.fallback_agents import gold_check
from agent_market.necklaces import gold_sec


def fake_sec(seen):
    def get(url):
        seen.append(url)
        if url == gold_sec.TICKERS:
            return json.dumps({"0": {"cik_str": 21344, "ticker": "KO", "title": "COCA COLA CO"},
                               "1": {"cik_str": 1094517, "ticker": "TM", "title": "TOYOTA MOTOR CORP/"},
                               "2": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."}})
        if "submissions" in url:
            form = "20-F" if "1094517" in url else "10-K"
            return json.dumps({"name": "TOYOTA MOTOR CORP/" if form == "20-F" else "COCA COLA CO",
                               "entityType": "operating", "filings": {"recent": {
                                   "form": ["8-K", form], "filingDate": ["2026-11-01", "2026-06-20"],
                                   "accessionNumber": ["0000000000-26-000001", "0000000000-26-000002"]}}})
        if "browse-edgar" in url:
            return "<feed><entry><cik>1</cik></entry></feed>" if "Ferrero" in url else "<feed></feed>"
        raise AssertionError(url)
    return get


def test_cases_mix_suffixes_foreign_issuers_and_no_registration(tmp_path):
    (tmp_path / "gold" / "company-due-diligence").mkdir(parents=True)
    seen = []
    cases, dropped = gold_sec.build_cases(tmp_path, fake_sec(seen), sleep=lambda s: None)
    by = {c["input"]["name"]: c for c in cases}
    assert by["Coca-Cola Co"]["truth"]["cik"] == "21344" and by["Coca-Cola Co"]["truth"]["filings"]["form"] == "10-K"
    assert by["Toyota Motor Corp"]["truth"]["filings"]["form"] == "20-F" and by["Toyota Motor Corp"]["stratum"] == "foreign"
    assert by["Robert Bosch GmbH"]["truth"] == {"cik": None, "sec_registered": False}
    assert "Ferrero International S.A." in dropped                  # EDGAR search found a filer: not unregistered
    assert "Boeing Co" in dropped                                    # its ticker is not in the fake file
    assert all("sec.gov" in u for u in seen)


def test_sec_filings_judge_accepts_no_registration_only_when_it_is_the_truth():
    none = {"truth": {"cik": None, "sec_registered": False}, "input": {"name": "Robert Bosch GmbH"}}
    assert gold_check.applies("sec-filings", none)
    assert gold_check.judge("sec-filings", none, {"answer": "No SEC EDGAR registration matches Robert Bosch GmbH."})["pass"]
    assert not gold_check.judge("sec-filings", none, {"answer": "Matched SEC filer: X (SEC CIK 12)"})["pass"]
    filer = {"truth": {"cik": "21344", "sec_registered": True}}
    assert gold_check.judge("sec-filings", filer, {"answer": "Matched SEC filer: COCA COLA CO (SEC CIK 21344)"})["pass"]
    assert not gold_check.judge("sec-filings", filer, {"answer": "No SEC EDGAR registration matches Coca-Cola Co."})["pass"]
