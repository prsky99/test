"""website-trust-brief: inner templates, the RDAP and robots.txt graders, the whole task and the gold builder."""
from agent_market.necklaces import gold_domains, model, retest, runner

CASE = {"case_id": "domain:python.org", "input": {"domain": "python.org"},
        "truth": {"domain": "python.org", "registered": "1995-03-27", "registrar": "Gandi SAS"}}
WHOIS = {"domain": "python.org", "registrar": "Gandi SAS", "created": "1995-03-27T05:00:00.545Z"}
XFIX_PASS = ("AI shopping readiness for python.org. AI crawler access on the home page: Pass. All 9 search and AI "
             "search bots may fetch /.")
XFIX_FAIL = "AI crawler access on the home page: Fail. GPTBot, ClaudeBot and PerplexityBot are blocked from /."


def robots(text, status=200):
    return lambda url: (status, text)


def test_inner_template_fills_a_url():
    assert runner.render({"store_url": "https://{{input.domain}}"}, {"domain": "python.org"}) == \
        {"store_url": "https://python.org"}
    assert runner.render({"store_url": "https://{{input.domain}}"}, {}) == {}
    defn = model.load("agent_market/necklaces/definitions/website-trust-brief.json")
    assert model.validate(defn) == []


def test_robots_reference_reads_clear_and_mixed_files():
    retest._ROBOTS_REFERENCE.clear()
    assert retest.robots_reference("a.test", 0, robots("User-agent: *\nDisallow: /private\n")) == "allowed"
    assert retest.robots_reference("b.test", 0, robots("User-agent: *\nDisallow: /\n")) == "blocked"
    assert retest.robots_reference("c.test", 0, robots("User-agent: GPTBot\nDisallow: /\n")) == "mixed"
    assert retest.robots_reference("d.test", 0, robots("", 404)) == "allowed"
    assert retest.robots_reference("e.test", 0, lambda url: None) is None
    retest._ROBOTS_REFERENCE.clear()


def test_crawler_grader_drops_verdicts_that_disagree():
    assert retest.grade_crawlers(CASE, XFIX_PASS, reference="allowed")
    assert not retest.grade_crawlers(CASE, XFIX_FAIL, reference="allowed")
    assert not retest.grade_crawlers(CASE, "GPTBot: disallowed for /", reference="allowed")
    assert retest.grade_crawlers(CASE, XFIX_FAIL, reference="blocked")
    assert not retest.grade_crawlers(CASE, XFIX_PASS, reference="blocked")
    assert retest.grade_crawlers(CASE, XFIX_FAIL, reference="mixed")
    assert retest.grade_crawlers(CASE, XFIX_PASS, reference="mixed")
    assert not retest.grade_crawlers(CASE, "python.org registered 1995", reference="mixed")   # nothing on crawlers
    fallback = {"signals": {"ai_crawlers": {"GPTBot": "allowed", "ClaudeBot": "allowed"}}}
    assert retest.grade_crawlers(CASE, fallback, reference="allowed")


def test_registration_grader_wants_the_day():
    assert retest.grade_registration(CASE, WHOIS)
    assert retest.grade_registration(CASE, {"created": "1995-03-26"})            # time zone slack
    assert not retest.grade_registration(CASE, {"created": "1995-04-27"})
    assert not retest.grade_registration(CASE, {"text": "registered in 1995"})


def test_task_needs_both_parts(monkeypatch):
    monkeypatch.setattr(retest, "robots_reference", lambda domain, now=None, get=None: "allowed")
    both = {"registration": {"answers": [WHOIS]}, "crawlers": {"answers": [{"text": XFIX_PASS}]}}
    assert retest.grade_site_task(CASE, both)
    assert not retest.grade_site_task(CASE, {"registration": both["registration"]})
    assert not retest.grade_site_task(CASE, {"crawlers": both["crawlers"]})
    assert retest.site_excluded(CASE) is None
    monkeypatch.setattr(retest, "robots_reference", lambda domain, now=None, get=None: None)
    assert retest.site_excluded(CASE) == "reference_unavailable"


def test_run_sends_the_url_and_the_domain():
    seen = {}

    def caller(member, args, timeout_s):
        seen[member["tool"]] = args
        return WHOIS if member["tool"] == "whois_lookup" else XFIX_PASS
    defn = model.load("agent_market/necklaces/definitions/website-trust-brief.json")
    runner.Runner(caller).run(defn, {"domain": "python.org"})
    assert seen["check_store_ai_readiness"] == {"store_url": "https://python.org"}
    assert seen["whois_lookup"] == {"domain": "python.org"}


def test_gold_builder_reads_the_rdap_registration_event():
    class Fake:
        calls = 0

        def json(self, url):
            self.calls += 1
            if url.endswith("/who.int"):
                return {"events": []}
            return {"events": [{"eventAction": "registration", "eventDate": "1995-03-27T05:00:00Z"}],
                    "entities": [{"roles": ["registrar"], "vcardArray": ["vcard", [["fn", {}, "text", "Gandi SAS"]]]}]}
    cases, dropped = gold_domains.domain_cases(Fake())
    assert dropped == ["who.int"]
    assert cases[0]["truth"]["registered"] == "1995-03-27" and cases[0]["truth"]["registrar"] == "Gandi SAS"
    assert {c["stratum"] for c in cases} == set(gold_domains.DOMAINS)
