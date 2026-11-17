"""PM 11-17: topic v2's papers step has no external member, so its single baseline is measured like the whole-task
necklaces (company): every lead of every step and our substitutes in the run chain, each graded on the whole task."""
from agent_market.necklaces import model, retest


def test_topic_v2_has_a_single_baseline_and_others_keep_the_contrast_rule():
    topic = next(d for d in model.load_valid() if d["slug"] == "topic-evidence-brief")
    singles = retest.single_members(topic, retest.CONTRAST["topic-evidence-brief"], {})
    assert singles, "no single baseline: the delta could not be judged"
    assert {slot for slot, _ in singles} - {"papers"}            # not only the papers step
    assert "topic-evidence-brief" in retest.SINGLE_TASK_GRADERS  # each single is graded on the whole task
    cve = next(d for d in model.load_valid() if d["slug"] == "cve-incident-brief")
    assert {slot for slot, _ in retest.single_members(cve, retest.CONTRAST["cve-incident-brief"], {})} <= {"record"}
