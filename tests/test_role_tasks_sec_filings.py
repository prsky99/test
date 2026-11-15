"""sec.filings.v1 role tasks (PM 11-15 13:46): fixed facts from data.sec.gov, "no SEC registration" cases, expiry."""
import json

from agent_market.necklaces import role_tasks as RT

RAG = RT.FILE.with_name("role-tasks-rag-v1.jsonl")


def cases(today="2026-11-16"):
    return {c["case_id"]: c for c in RT.by_role(RAG, today=today).get("sec.filings.v1", [])}


def test_the_role_has_fixed_fact_and_no_registration_cases():
    got = cases()
    assert {"sec-aapl-latest-10k", "sec-msft-latest-periodic", "sec-none-nongshim", "sec-none-mercadona"} <= set(got)
    assert "sec-apple-filings" not in got                 # retired: it only repeated its input
    for case in got.values():
        assert case["truth_sources"] and all(s["confirmed"] for s in case["truth_sources"])
        assert RT.fact_checks(case) >= 1


def test_our_agent_answer_shape_passes_and_a_stale_list_fails():
    case = cases()["sec-aapl-latest-10k"]
    answer = ("Matched SEC filer: Apple Inc. (SEC CIK 320193), by ticker AAPL. Recent EDGAR filings: 2026-11-03 10-K; "
              "2026-10-30 8-K. Periodic and current reports: 2026-11-03 10-K (accession 0000320193-26-000026).")
    assert RT.score(case, answer) == (True, [])
    stale = "Apple Inc. CIK 320193 filed its 10-K on 2025-10-31."
    ok, reasons = RT.score(case, stale)
    assert not ok and reasons == ["missing 2026-11-03"]
    assert RT.score(case, "Apple (CIK 0000320193) filed its annual report on Form 10-K on November 3, 2026.")[0]


def test_microsoft_accepts_the_latest_10q_or_the_latest_10k():
    case = cases()["sec-msft-latest-periodic"]
    assert RT.score(case, "MICROSOFT CORP, CIK 789019: 10-Q filed 2026-10-28.")[0]
    assert RT.score(case, "MICROSOFT CORP, CIK 789019: 10-K filed July 29, 2026 (0001193125-26-323660).")[0]
    assert not RT.score(case, "MICROSOFT CORP, CIK 789019: 10-K filed 2025-07-30.")[0]


def test_no_registration_answer_passes_and_a_made_up_record_fails():
    case = cases()["sec-none-nongshim"]
    ours = json.dumps({"result": {"answer": "No SEC EDGAR registration matches (company Nongshim Co., Ltd., query "
                                            "Nongshim): the company has no SEC filings under a listed ticker, CIK or "
                                            "this exact name.", "url": "https://www.sec.gov/edgar/search/"}})
    assert RT.score(case, ours) == (True, [])
    ok, reasons = RT.score(case, "Nongshim Co (CIK 1234567) filed a 20-F: accession 0001234567-26-000001.")
    assert not ok and len(reasons) == 3                    # no negative phrase, and both record patterns hit
    assert not RT.score(case, "Nongshim makes instant noodles.")[0]


def test_valid_until_drops_a_case_after_its_day():
    assert "sec-aapl-latest-10k" in cases("2027-01-20")
    assert "sec-aapl-latest-10k" not in cases("2027-01-21")
    assert "sec-none-nongshim" in cases("2030-01-01")      # no expiry
    assert RT.current({"valid_until": "2026-11-15"}, "2026-11-15") and not RT.current({"valid_until": "2026-11-15"}, "2026-11-16")
