"""11-11 real task a02: "a tool that returns X as JSON" searches for X; the format is a condition."""
from agent_market.concierge.fast_chat import retrieval_text
from agent_market.concierge.selection import capability_terms


def test_the_returned_thing_is_searched_without_the_frame_or_the_format():
    text = retrieval_text('Need a tool that returns current price of BTC in USD as JSON')
    assert text == 'current price of BTC in USD'
    assert 'returns' not in capability_terms(text) and 'json' not in capability_terms(text)
    assert retrieval_text('Find an API that gives me the transcript of a YouTube video') == 'the transcript of a YouTube video'
    assert retrieval_text('weather in Seoul as JSON') == 'weather in Seoul'


def test_capability_verbs_formats_as_subjects_and_bare_frames_are_kept():
    for kept in ('Find an agent that converts PDF to text', 'Convert CSV to JSON', 'Validate JSON against a JSON Schema',
                 'a tool that returns', 'json', 'Need a tool to get npm package metadata (latest version)'):
        assert retrieval_text(kept) == kept
    # "returns" stays when it is the subject ("tax returns"); only the leading frame goes.
    assert retrieval_text('Find an agent that returns tax returns data') == 'tax returns data'
