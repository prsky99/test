"""PM 11-16: a single member of topic-evidence-brief is graded on the whole task (web, papers, background), and the
single members stay the papers step's external members."""
import copy

from agent_market.necklaces import model, retest

WIKI = {"title": "CRISPR", "description": "Family of DNA sequences", "url": "https://en.wikipedia.org/wiki/CRISPR"}
PAPER = {"doi": "10.1126/science.1231143", "title": "Multiplex Genome Engineering Using CRISPR/Cas Systems"}
CASE_FIXED = {"case_id": "topic:CRISPR", "input": {"topic": "CRISPR"},
              "truth": {"wiki": WIKI, "papers": [PAPER], "paper_phrase": "crispr"}}
OK = {"web": {"answer": "CRISPR is a family of DNA sequences.", "sources": ["https://en.wikipedia.org/wiki/CRISPR"]},
      "papers": {"results": [{"title": PAPER["title"], "doi": PAPER["doi"]}]},
      "background": {"title": "CRISPR", "extract": "CRISPR is a family of DNA sequences."}}


def test_the_task_needs_every_required_part():
    assert retest.grade_topic_task(CASE_FIXED, OK)
    for missing in ("web", "papers", "background"):
        out = {k: v for k, v in OK.items() if k != missing}
        assert not retest.grade_topic_task(CASE_FIXED, out), missing
    # a papers member alone (what a single run gives) passes its step but never the task
    assert retest.GRADERS["papers"](CASE_FIXED, OK["papers"]) and not retest.grade_topic_task(CASE_FIXED, {"papers": OK["papers"]})


def test_the_task_rule_is_the_necklace_rule():
    defn = model.load("agent_market/necklaces/definitions/topic-evidence-brief.json")
    for out in (OK, {"papers": OK["papers"]}, {k: v for k, v in OK.items() if k != "web"}):
        assert retest.grade_topic_task(CASE_FIXED, out) is (retest.grade(defn, CASE_FIXED, out)["ok"] is True)


def test_single_members_stay_the_papers_step():
    defn = copy.deepcopy(model.load("agent_market/necklaces/definitions/topic-evidence-brief.json"))
    members = retest.single_members(defn, retest.CONTRAST["topic-evidence-brief"], {})
    assert members and all(slot == "papers" for slot, _ in members)
    assert "topic-evidence-brief" not in retest.TASK_GRADERS          # the case verdict keeps grade() per slot
