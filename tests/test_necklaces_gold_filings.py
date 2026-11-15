import json
from datetime import date

from agent_market.necklaces import gold_filings

INDEX = """Description:           Daily Index of EDGAR Dissemination Feed by Form Type
Form Type   Company Name                                                  CIK         Date Filed  File Name
---------------------------------------------------------------------------------------------------------------------------------------------
10-K        APPLE INC.                                                    320193      2026-11-03  edgar/data/320193/0000320193-26-000026.txt
10-K/A      APPLE INC.                                                    320193      2026-11-10  edgar/data/320193/0000320193-26-000030.txt
10-Q        APPLE INC.                                                    320193      2026-08-01  edgar/data/320193/0000320193-26-000020.txt
8-K         APPLE INC.                                                    320193      2026-11-09  edgar/data/320193/0001140361-26-042798.txt
10-Q        OTHER CO                                                      99          2026-11-01  edgar/data/99/0000000099-26-000001.txt
"""


def test_the_latest_periodic_filing_without_amendments_or_current_reports():
    out = gold_filings.parse_index(INDEX, {"320193"})
    assert out == {"320193": {"form": "10-K", "date": "2026-11-03", "accession": "0000320193-26-000026"}}


def test_build_writes_truth_apart_from_the_split_files(tmp_path):
    folder = tmp_path / "gold" / "company-due-diligence"
    folder.mkdir(parents=True)
    rows = [{"case_id": "US:CIK320193", "input": {"name": "Apple Inc", "country": "US"}, "truth": {"cik": "320193"}},
            {"case_id": "US:CIK5", "input": {"name": "Gone Inc", "country": "US"}, "truth": {"cik": "5"}},
            {"case_id": "JP:x", "input": {"name": "Toyota", "country": "JP"}, "truth": {"lei": "x"}}]
    split = "".join(json.dumps(r) + "\n" for r in rows)
    (folder / "holdout-r1.jsonl").write_text(split)
    urls = []
    out = gold_filings.build(tmp_path, get=lambda url: urls.append(url) or INDEX, today=date(2026, 11, 15))
    assert out["us_cases"] == 2 and out["with_filing"] == 1
    assert urls == ["https://www.sec.gov/Archives/edgar/full-index/2026/QTR3/form.idx",
                    "https://www.sec.gov/Archives/edgar/full-index/2026/QTR4/form.idx"]
    assert (folder / "holdout-r1.jsonl").read_text() == split
    cases = gold_filings.attach(tmp_path, [dict(r) for r in rows])
    assert cases[0]["truth"]["filings"]["valid_until"] == "2027-02-23" and "filings" not in cases[1]["truth"]
