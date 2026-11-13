import re

from agent_market.necklaces import role_tasks

PERSONAL = re.compile(r"(@[a-z0-9-]+\.[a-z]|password|passwd|api[_-]?key|token|secret|\bssn\b|phone)", re.I)
WRITE_VERBS = re.compile(r"\b(create|delete|update|send|post|pay|buy|book|submit|transfer)\b", re.I)


def test_every_role_has_two_or_three_cases_with_expectations():
    roles = role_tasks.by_role()
    assert len(roles) >= 10
    for role, cases in roles.items():
        assert 2 <= len(cases) <= 3, role
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
    assert len(ids) == 15
    for contract_id in ids:
        contract = model.load_contract(contract_id)
        assert contract["id"] == contract_id and contract["test_inputs"]
        assert contract["input_schema"]["type"] == contract["output_schema"]["type"] == "object"
    assert {c["role"] for c in role_tasks.load()} <= ids
    for defn in model.load_valid():
        assert {slot["contract"] for slot in defn["slots"]} <= ids
