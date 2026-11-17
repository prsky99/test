"""C01 (PM 11-17): a search answer that arrives as one MCP text block holding a JSON list is split into its entries,
so a company's background keeps only the entry about that company (the 11-16 round kept five companies)."""
import json

from agent_market.necklaces import runner

VALUES = {"slot.registry.legal_name": "Southwest Gas Holdings, Inc.", "slot.registry.ticker": "SWX",
          "slot.registry.cik": "1692115"}
RESULTS = [{"title": "Southwest Gas", "description": "Energy company",
            "excerpt": "<span class=\"searchmatch\">Southwest</span> Gas Holdings, Inc. (NYSE: SWX) is an investor-owned utility"},
           {"title": "Generac", "description": "American industrial company",
            "excerpt": "Generac <span class=\"searchmatch\">Holdings</span> Inc. is an American manufacturer"},
           {"title": "CF Industries", "description": "American agrochemical manufacturer",
            "excerpt": "CF Industries Holdings, Inc. is an American manufacturer of fertilizers"}]


def test_a_text_block_holding_a_result_list_keeps_only_the_company_entry():
    raw = [{"type": "text", "text": json.dumps(RESULTS)}]
    out = runner.norm_encyclopedia(raw, VALUES)
    text = json.dumps(out)
    assert out.get("identity") == "matched" and "Southwest" in text
    assert "Generac" not in text and "CF Industries" not in text


def test_no_entry_about_the_company_is_an_identity_mismatch():
    raw = [{"type": "text", "text": json.dumps(RESULTS[1:])}]
    assert runner.norm_encyclopedia(raw, VALUES) == {runner.IDENTITY_MISMATCH: True}


def test_plain_text_blocks_and_topics_are_unchanged():
    plain = [{"type": "text", "text": "Southwest Gas Holdings, Inc. (NYSE: SWX) is an investor-owned utility company."}]
    assert runner._unwrap_content(plain) == plain
    topic = runner.norm_encyclopedia([{"type": "text", "text": json.dumps(RESULTS)}], {"topic": "utilities"})
    assert "Generac" in json.dumps(topic)                  # no registry company: a topic keeps every entry
