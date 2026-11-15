import json

from agent_market.necklaces import gold_r3


def entity(qid, title, lei_values, label=None):
    return {"id": qid, "sitelinks": {"enwiki": {"title": title}}, "labels": {"en": {"value": label or title}},
            "claims": {"P1278": [{"mainsnak": {"datavalue": {"value": v}}, "rank": "normal"} for v in lei_values]}}


def lei(n):
    return f"5299{n:014d}00"


def record(code, name, cc, status="ACTIVE", reg="ISSUED"):
    return {"id": code, "attributes": {"entity": {"legalName": {"name": name}, "legalAddress": {"country": cc},
                                                  "status": status}, "registration": {"status": reg}}}


def test_short_names_drop_legal_forms():
    assert gold_r3.short_name("Toyota Motor Corporation") == "Toyota Motor"
    assert gold_r3.short_name("Siemens Energy AG") == "Siemens Energy"
    assert gold_r3.short_name("Samsung Electronics Co., Ltd.") == "Samsung Electronics"
    assert gold_r3.short_name("AXA") == "AXA"


def test_candidates_need_one_lei_and_follow_redirected_titles():
    titles = [("Toyota", "Toyota", "JP"), ("Galp Energia", "Galp", "PT"), ("Sony", "Sony", "JP"), ("AXA", "AXA", "FR")]
    found = gold_r3.candidates({"entities": {
        "Q1": entity("Q1", "Toyota", [lei(3)]), "Q2": entity("Q2", "Galp", [lei(4)]),
        "Q3": entity("Q3", "Sony", [lei(5), lei(6)]), "Q4": entity("Q4", "AXA", ["not-an-lei"])}}, titles)
    assert [(c["name"], c["country"], c["lei"]) for c in found] == [("Toyota", "JP", lei(3)), ("Galp", "PT", lei(4))]


def test_choose_excludes_used_and_named_and_spreads_countries():
    cands = [{"label": n, "name": n, "country": cc, "lei": lei(i), "links": 100 - i}
             for i, (n, cc) in enumerate([("Philips", "NL"), ("HSBC Bank", "GB"), ("Toyota Motor", "JP"), ("Sony", "JP"),
                                          ("Hitachi", "JP"), ("AXA", "FR"), ("Used", "DE"), ("Toyota Motor", "JP")])]
    out = gold_r3.choose(cands, used_leis={lei(6)}, used_ids=set(), used_names=set(), per_country=2, target=10)
    assert [c["name"] for c in out] == ["Toyota Motor", "AXA", "Sony"]       # JP capped at 2, duplicate name dropped


def test_the_fixed_list_avoids_earlier_names_and_spreads_countries():
    from agent_market.necklaces import gold
    old = {gold.name_key(common) for _, common, _ in gold.NON_US + gold.NON_US_MORE}
    assert len(gold_r3.TITLES) == 50 and not old & {gold.name_key(n) for _, n, _ in gold_r3.TITLES}
    assert len({cc for _, _, cc in gold_r3.TITLES}) >= 15 and not any(gold_r3.excluded(n) for _, n, _ in gold_r3.TITLES)


def test_cases_take_every_truth_field_from_gleif():
    chosen = [{"name": "Toyota Motor", "country": "JP", "lei": lei(3)}, {"name": "AXA", "country": "FR", "lei": lei(6)},
              {"name": "Moved", "country": "DE", "lei": lei(9)}, {"name": "Gone", "country": "IT", "lei": lei(10)}]
    gleif = {"data": [record(lei(3), "TOYOTA MOTOR CORPORATION", "JP"), record(lei(6), "AXA", "FR", reg="LAPSED"),
                      record(lei(9), "Moved AG", "CH"), record(lei(10), "Gone S.p.A.", "IT", status="INACTIVE")]}
    cases = gold_r3.cases_from(chosen, gleif)
    assert [(c["case_id"], c["truth"]["legal_name"]) for c in cases] == [(f"JP:{lei(3)}", "TOYOTA MOTOR CORPORATION"),
                                                                          (f"FR:{lei(6)}", "AXA")]
    assert cases[0]["input"] == {"name": "Toyota Motor", "country": "JP"} and cases[0]["stratum"] == "has_lei"


def test_gleif_phase_adds_r3_to_the_manifest_without_touching_other_splits(tmp_path):
    folder = tmp_path / "gold" / gold_r3.SLUG
    folder.mkdir(parents=True)
    old = {"case_id": "DE:" + lei(99), "input": {"name": "Old", "country": "DE"}, "truth": {"lei": lei(99)}}
    (folder / "holdout-r1.jsonl").write_text(json.dumps(old) + "\n")
    (folder / "manifest.json").write_text(json.dumps({"files": {"holdout-r1": {"cases": 1}}}))
    chosen = [{"name": f"Co{i}", "country": "JP", "lei": lei(100 + i)} for i in range(31)] + \
             [{"name": "Old again", "country": "DE", "lei": lei(99)}]
    (tmp_path / "gold" / "raw").mkdir()
    (tmp_path / "gold" / "raw" / "company-r3-candidates.json").write_text(json.dumps({"chosen": chosen}))
    urls = []

    def get(url):
        urls.append(url)
        return {"data": [record(c["lei"], c["name"] + " K.K.", c["country"]) for c in chosen]}
    out = gold_r3.run_gleif(tmp_path, get)
    assert out["written"] and out["cases"] == 31 and len(urls) == 1 and lei(99) not in urls[0]
    manifest = json.loads((folder / "manifest.json").read_text())
    assert manifest["files"]["holdout-r1"] == {"cases": 1} and manifest["files"]["holdout-r3"]["cases"] == 31
    assert (folder / "holdout-r1.jsonl").read_text() == json.dumps(old) + "\n"


def test_too_few_survivors_write_nothing(tmp_path):
    (tmp_path / "gold" / "raw").mkdir(parents=True)
    (tmp_path / "gold" / gold_r3.SLUG).mkdir(parents=True)
    (tmp_path / "gold" / "raw" / "company-r3-candidates.json").write_text(json.dumps({"chosen": [
        {"name": "A", "country": "JP", "lei": lei(1)}]}))
    out = gold_r3.run_gleif(tmp_path, lambda url: {"data": [record(lei(1), "A", "JP")]})
    assert out["written"] is False and not (tmp_path / "gold" / gold_r3.SLUG / "holdout-r3.jsonl").exists()


def test_fetch_asks_the_ledger_first_and_reports_the_status():
    seen = []

    class Resp:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return b'{"ok": 1}'
    out = gold_r3.fetch("https://api.gleif.org/x", opener=lambda req, timeout: Resp(),
                        reserve=lambda url, system: (seen.append(("reserve", system)) or (True, None)),
                        note=lambda url, system, code, evidence=None: seen.append(("note", code)))
    assert out == {"ok": 1} and seen == [("reserve", "adhoc"), ("note", 200)]
    try:
        gold_r3.fetch("https://api.gleif.org/x", opener=lambda req, timeout: Resp(),
                      reserve=lambda url, system: (False, "domain total used"), note=lambda *a, **kw: None)
    except RuntimeError as exc:
        assert "domain total used" in str(exc)
    else:
        raise AssertionError("sent without the ledger")
