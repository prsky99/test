"""website-trust-brief v2 (PM 11-17): answer sets (gold_domains_v2) and the v2 task grader."""
import json

from agent_market.necklaces import gold_domains, gold_domains_v2 as v2, model, retest

CASE = {"case_id": "domain:example.org", "input": {"domain": "example.org"},
        "truth": {"domain": "example.org", "registered": "1995-08-14", "registrar": "X",
                  "spf": ["v=spf1 -all"], "dmarc": []}}


def test_v2_lists_are_unseen_and_disjoint():
    v1 = {d for names in gold_domains.DOMAINS.values() for d in names}
    r3, r4 = ({d for _, d in v2.LISTS[s]} for s in ("holdout-r3", "holdout-r4"))
    assert not (r3 | r4) & v1 and not r3 & r4 and len(r3) >= 30 and len(r4) >= 30


def test_builder_freezes_registration_and_mail_records_and_takes_the_first_30_readable(tmp_path):
    calls = []

    def get(url, accept="application/json"):
        calls.append(url)
        if url.startswith(v2.RDAP):
            name = url[len(v2.RDAP):]
            if name == "usa.gov":
                return 404, None                                      # no RDAP answer: skipped, next one is used
            return 200, {"events": [{"eventAction": "registration", "eventDate": "2001-02-03T00:00:00Z"}]}
        if "_dmarc." in url:
            return 200, {"Status": 3}                                 # NXDOMAIN: no DMARC
        return 200, {"Status": 0, "Answer": [{"type": 16, "data": '"v=spf1 include:_spf.example" " -all"'},
                                             {"type": 16, "data": '"google-site-verification=x"'}]}
    out = v2.build(tmp_path, "holdout-r3", get, sleep=lambda s: None)
    assert out["written"] and out["cases"] == 30 and out["skipped"] == ["usa.gov"]
    folder = tmp_path / "gold" / "website-trust-brief"
    cases = [json.loads(x) for x in (folder / "holdout-r3.jsonl").read_text().splitlines()]
    assert cases[0]["truth"]["spf"] == ["v=spf1 include:_spf.example -all"] and cases[0]["truth"]["dmarc"] == []
    entry = json.loads((folder / "manifest.json").read_text())["files"]["holdout-r3"]
    assert entry["grading_rule"]["name"] == "website-trust-v2" and entry["answer_set"] == "website-trust-brief-v2"
    assert v2.build(tmp_path, "holdout-r3", get, sleep=lambda s: None)["written"] is False     # never rewritten


def test_mail_auth_needs_each_record_quoted_or_its_absence_stated():
    assert retest.grade_mail_auth(CASE, {"answer": "SPF: v=spf1  -all. No DMARC record is published."})
    assert not retest.grade_mail_auth(CASE, {"answer": "SPF: v=spf1 -all."})                 # DMARC not addressed
    assert not retest.grade_mail_auth(CASE, {"answer": "SPF looks fine, no DMARC"})          # record not quoted


def test_tls_takes_the_expiry_day_or_the_issuer_organisation():
    ref = ("2027-03-01", "Let's Encrypt")
    assert retest.grade_tls(CASE, {"answer": "valid until 2027-03-02"}, reference=ref)
    assert retest.grade_tls(CASE, {"answer": "issued by Let's Encrypt R11"}, reference=ref)
    assert not retest.grade_tls(CASE, {"answer": "certificate is valid"}, reference=ref)


def test_v2_task_needs_registration_mail_and_tls_and_not_crawlers(monkeypatch):
    monkeypatch.setattr(retest, "tls_reference", lambda domain, now=None: ("2027-03-01", "DigiCert Inc"))
    good = {"registration": {"answer": "registered 1995-08-14"},
            "mail_auth": {"answer": "v=spf1 -all; no DMARC record"}, "tls": {"answer": "DigiCert, until 2027-03-01"}}
    assert retest.grade_site_task(CASE, good)
    assert not retest.grade_site_task(CASE, {**good, "tls": {"answer": "ok"}})
    assert retest.site_excluded(CASE) is None
    monkeypatch.setattr(retest, "tls_reference", lambda domain, now=None: None)
    assert retest.site_excluded(CASE) == "reference_unavailable"


def test_shipped_v2_definition_is_valid_with_three_required_steps_and_mail_auth_singles():
    defn = next(d for d in model.load_valid() if d["slug"] == "website-trust-brief")
    assert defn["version"] == 2 and model.validate(defn) == []
    assert [s["slot"] for s in defn["slots"] if s.get("required", True)] == ["registration", "mail_auth", "tls"]
    assert all(m.get("resource_id") != 132732 for s in defn["slots"] for m in s["chain"])
    assert retest.CONTRAST["website-trust-brief"] == "mail_auth"


def test_mail_auth_answer_says_dkim_is_not_checked():
    from agent_market.necklaces import runner
    out = runner.merge("dns.mail_auth.v1", [({"kind": "external", "resource_id": 39800}, {"answer": "v=spf1 -all"})])
    assert "DKIM is not" in out["note"] and out["material"] == runner.MATERIAL_NOTICE
