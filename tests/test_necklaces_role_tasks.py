import re

from agent_market.necklaces import role_tasks

PERSONAL = re.compile(r"(@[a-z0-9-]+\.[a-z]|password|passwd|api[_-]?key|token|secret|\bssn\b|phone)", re.I)
WRITE_VERBS = re.compile(r"\b(create|delete|update|send|post|pay|buy|book|submit|transfer)\b", re.I)


def test_every_role_has_two_or_three_cases_with_expectations():
    roles = role_tasks.by_role()
    assert len(roles) >= 10
    for role, cases in roles.items():
        fixed = [c for c in cases if not c.get("rotating")]
        assert 2 <= len(fixed) <= 3 and len(cases) - len(fixed) <= 1, role
        for case in cases:
            assert case["contract"] == role and case["task_type"] == "role_test"
            assert case["expect"], case["case_id"]
    ids = [c["case_id"] for c in role_tasks.load()]
    assert len(ids) == len(set(ids))


def test_inputs_hold_no_personal_data_credentials_or_write_actions():
    for case in role_tasks.load():
        text = " ".join(str(v) for v in case["input"].values())
        assert not PERSONAL.search(text), case["case_id"]
        assert not WRITE_VERBS.search(text), case["case_id"]


def case(case_id):
    return next(c for c in role_tasks.load() if c["case_id"] == case_id)


def test_alias_groups_accept_any_alias():
    c = case("adv-lodash-4.17.20")
    assert role_tasks.score(c, "GHSA-35jh-r3h4-6jhm and CVE-2020-28500")[0]
    ok, reasons = role_tasks.score(c, "only CVE-2020-28500")
    assert not ok and reasons == ["missing CVE-2021-23337"]


def test_kev_checks_both_directions():
    listed, not_listed = case("kev-cve-2021-44228"), case("kev-cve-2024-3094")
    assert role_tasks.score(not_listed, "CVE-2024-3094 is not in the CISA KEV catalog.")[0]
    assert not role_tasks.score(not_listed, "CVE-2024-3094 is a known exploited vulnerability")[0]
    assert role_tasks.score(listed, "Listed in CISA KEV", {"kev": True, "epss": 0.97})[0]
    ok, reasons = role_tasks.score(listed, "Listed in CISA KEV", {"kev": True, "epss": 0.2})
    assert not ok and "epss" in reasons[0]


def test_any_words_and_https_link():
    c = case("web-canberra")
    assert role_tasks.score(c, "Canberra is the capital. https://en.wikipedia.org/wiki/Canberra")[0]
    assert role_tasks.score(c, "Canberra")[1] == ["no https link"]
    assert role_tasks.score(case("papers-bert"), "arXiv 1810.04805")[0]


def test_contracts_are_the_canonical_role_list():
    from agent_market.necklaces import model
    ids = set(model.contract_ids())
    # One list (PM 11-14): the search team's pearl-test catalog names exactly these contracts.
    from scripts.role_catalog import ROLES
    assert ids == set(ROLES)
    for contract_id in ids:
        contract = model.load_contract(contract_id)
        assert contract["id"] == contract_id and contract["test_inputs"]
        assert contract["input_schema"]["type"] == contract["output_schema"]["type"] == "object"
    assert {c["role"] for c in role_tasks.load()} <= ids
    for defn in model.load_valid():
        assert {slot["contract"] for slot in defn["slots"]} <= ids


def test_every_role_task_file_uses_contract_names_and_public_inputs():
    from agent_market.necklaces import model
    ids = set(model.contract_ids())
    files = sorted(role_tasks.FILE.parent.glob("*.jsonl"))
    assert len(files) >= 2          # the workflow file and the search team's file
    seen = set()
    for path in files:
        for case in role_tasks.load(path):
            assert case["role"] in ids, (path.name, case["case_id"])
            assert case["case_id"] not in seen, case["case_id"]
            seen.add(case["case_id"])
            text = " ".join(str(v) for v in case["input"].values())
            assert not PERSONAL.search(text) and not WRITE_VERBS.search(text), case["case_id"]


# ---------------------------------------------------------------- weekly recent KEV case (search team, PM 11-15 10:24)
FEED = {"vulnerabilities": [{"cveID": "CVE-2026-1111", "dateAdded": "2026-10-01"},
                            {"cveID": "CVE-2026-2222", "dateAdded": "2026-11-10"},
                            {"cveID": "CVE-2026-3333", "dateAdded": "2026-11-12"},
                            {"cveID": "bad", "dateAdded": "2026-11-14"}]}


def test_the_recent_case_is_the_newest_addition_within_30_days():
    case = role_tasks.recent_kev_case(FEED, "2026-11-15")
    assert case["input"] == {"cve_id": "CVE-2026-3333"} and case["expect"] == {"kev": True, "kev_date_added": "2026-11-12"}
    assert case["truth_sources"][0]["checked_on"] == "2026-11-15" and case["rotating"] == "weekly-recent-kev"
    assert role_tasks.recent_kev_case({"vulnerabilities": FEED["vulnerabilities"][:1]}, "2026-11-15") is None


def test_refresh_is_weekly_and_load_adds_the_case(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENTCON_PROJECT_ROOT", str(tmp_path))
    gets = []
    feed = lambda url: gets.append(url) or FEED
    assert role_tasks.refresh_recent_kev("2026-11-15", get=feed)["refreshed"] is True
    assert role_tasks.refresh_recent_kev("2026-11-20", get=feed)["refreshed"] is False      # within 7 days
    assert role_tasks.refresh_recent_kev("2026-11-22", get=feed)["refreshed"] is True
    assert len(gets) == 2
    ids = [c["case_id"] for c in role_tasks.load()]
    assert ids.count("kev-recent-cve-2026-3333") == 1
    assert "kev-recent-cve-2026-3333" not in [c["case_id"] for c in role_tasks.load_plain(role_tasks.FILE)]
