"""company holdout-r6 (ops 11-16): 30 unseen companies for the sec-company-profile substitute gate."""
import json

from agent_market.necklaces import gold_company_r6 as r6
from tests.test_necklace_gold_company_r4 import fake, setup


def test_thirty_unseen_cases_with_the_edgar_name(tmp_path):
    folder = setup(tmp_path)
    (folder / "holdout-r5.jsonl").write_text(json.dumps({"case_id": "US5:CIK3", "truth": {"cik": "3"}}) + "\n")
    out = r6.build(tmp_path, get=fake(), sleep=lambda s: None)
    assert out["written"] and out["cases"] == 30
    cases = [json.loads(l) for l in (folder / "holdout-r6.jsonl").read_text().splitlines()]
    ciks = {c["truth"]["cik"] for c in cases}
    assert "3" not in ciks and "5" not in ciks and len(ciks) == 30          # earlier sets' CIKs are left out
    assert all(c["case_id"].startswith("US6:CIK") and c["truth"]["sec_title"].startswith("ACME") for c in cases)
    entry = json.loads((folder / "manifest.json").read_text())["files"]["holdout-r6"]
    assert "sec-company-profile" in entry["for"] and "r6:" in entry["selection"]


def test_r4_still_builds_sixty(tmp_path):
    from agent_market.necklaces import gold_company_r4 as r4
    setup(tmp_path)
    assert r4.build(tmp_path, get=fake(), sleep=lambda s: None)["cases"] == 60
