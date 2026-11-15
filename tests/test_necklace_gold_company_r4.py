"""company-due-diligence holdout-r4: 60 unseen US filers in a fixed hash order, SEC truth, scope-only filter."""
import json

from agent_market.necklaces import gold_company_r4 as r4


def setup(tmp_path, seen_cik=5):
    folder = tmp_path / "gold" / "company-due-diligence"
    folder.mkdir(parents=True)
    (folder / "holdout-r1.jsonl").write_text(json.dumps({"case_id": f"US:CIK{seen_cik}", "truth": {"cik": str(seen_cik)}}) + "\n")
    (folder / "manifest.json").write_text(json.dumps({"files": {}}))
    return folder


def fake(n=120, foreign=lambda cik: cik % 7 == 0):
    tickers = {str(i): {"cik_str": i, "ticker": f"T{i}", "title": f"ACME {i} CORP"} for i in range(1, n + 1)}

    def get(url):
        if url.endswith("company_tickers.json"):
            return json.dumps(tickers)
        cik = int(url.split("CIK")[1].split(".")[0])
        form = "20-F" if foreign(cik) else "10-Q"
        return json.dumps({"name": f"ACME {cik} CORP", "filings": {"recent": {
            "form": ["8-K", form], "filingDate": ["2026-11-10", "2026-11-01"], "accessionNumber": ["a", f"000-{cik}"]}}})
    return get


def test_sixty_unseen_us_filers_with_sec_truth(tmp_path):
    folder = setup(tmp_path)
    out = r4.build(tmp_path, get=fake(), sleep=lambda s: None)
    assert out["written"] and out["cases"] == 60 and out["seen"] + out["not_us_periodic"] >= 1
    cases = [json.loads(l) for l in (folder / "holdout-r4.jsonl").read_text().splitlines()]
    assert not any(c["truth"]["cik"] == "5" for c in cases)                  # an earlier case's CIK is left out
    first = cases[0]
    assert first["truth"]["filings"]["form"] == "10-Q" and first["input"]["country"] == "US"
    assert first["input"]["name"].endswith("Corp") and first["truth"]["ticker"].startswith("T")
    entry = json.loads((folder / "manifest.json").read_text())["files"]["holdout-r4"]
    assert "same_source_note" in entry and "10-K or 10-Q" in entry["selection"]


def test_too_few_cases_writes_nothing(tmp_path):
    setup(tmp_path)
    out = r4.build(tmp_path, get=fake(n=30), sleep=lambda s: None)
    assert out["written"] is False and not (tmp_path / "gold" / "company-due-diligence" / "holdout-r4.jsonl").exists()


def test_typed_names():
    assert r4.typed("RAND CAPITAL CORP") == "Rand Capital Corp"
    assert r4.typed("APPLE INC") == "Apple Inc" and r4.typed("SOUTHERN CO /GA/") == "Southern Co"
