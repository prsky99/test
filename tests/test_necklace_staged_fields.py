"""What a later stage can read is what the runner stages (PM 12:58, 11-15): the declaration matches the normalizers
and the gate refuses a definition that reads a field no step produces."""
from agent_market.necklaces import model, runner

SAMPLES = {
    "company.registry.v1": {"name": "Apple Inc.", "cik": "320193", "ticker": "AAPL", "lei": "HWUPKR0MPOU8FGXBT394"},
    "geocode.address.v1": {"lat": 35.6, "lon": 139.7, "name": "x", "country_code": "JP", "timezone": "Asia/Tokyo"},
    "earthquake.feed.v1": {"count": 1, "quakes": [{"mag": 5.1, "lat": 1.0, "lon": 2.0, "time": "2026-11-15T00:00:00Z"}],
                           "center": {"lat": 1.0, "lon": 2.0}},
    "book.search.v1": {"docs": [{"author_name": ["George Orwell"], "first_publish_year": 1949, "title": "1984"}]},
    "cve.record.v1": {"cvss": {"baseScore": 7.5}, "id": "CVE-2021-23337"},
    "encyclopedia.summary.v1": {"title": "Seoul", "extract": "Seoul is the capital."},
}


def staged(contract, raw, values=None):
    canon = runner.normalize(contract, raw, values or {"cve_id": "CVE-2021-23337"})
    return {k for k, v in (canon or {}).items() if isinstance(v, (str, int, float)) and not isinstance(v, bool)}


def test_the_declaration_is_what_the_normalizers_stage():
    for contract, raw in SAMPLES.items():
        assert staged(contract, raw) <= runner.staged_fields(contract), contract
    assert staged("company.registry.v1", SAMPLES["company.registry.v1"]) == {"cik", "ticker", "lei", "legal_name"}
    assert {"lat", "lon", "point", "country_code", "timezone"} <= staged("geocode.address.v1",
                                                                         SAMPLES["geocode.address.v1"])


def test_every_shipped_definition_reads_only_staged_fields():
    for defn in model.load_all():
        assert runner.slot_reference_problems(defn) == [], defn["slug"]


def test_a_reference_to_a_field_no_step_stages_is_named():
    defn = {"slots": [{"slot": "registry", "contract": "company.registry.v1", "chain": []},
                      {"slot": "filings", "contract": "sec.filings.v1", "chain": [
                          {"agent_id": "own-edgar", "input_map": {"cik": "{{slot.registry.cik}}",
                                                                  "ticker": "{{slot.registry.ticker}}",
                                                                  "company": "{{slot.registry.legal_name}}",
                                                                  "sic": "{{slot.registry.sic}}"}}]}]}
    problems = runner.slot_reference_problems(defn)
    assert len(problems) == 1 and "slot.registry.sic" in problems[0] and "own-edgar" in problems[0]
