"""PM 11-14 (real task a01): PDF converters taking a file URL get an input note about direct .pdf addresses."""
from agent_market.concierge.connections import file_url_note


def schema(name, props, description=''):
    return {'name': name, 'description': description, 'inputSchema': {'type': 'object', 'properties': props}}


def test_pdf_converter_with_a_url_parameter_gets_the_note():
    note = file_url_note([schema('convert_file', {'source_url': {'type': 'string'}, 'target_format': {'type': 'string'}},
                                 'Convert PDF, DOCX and images to text')])
    assert note and 'arxiv.org/pdf/<id>.pdf' in note


def test_other_tools_get_nothing():
    assert file_url_note([schema('get_weather', {'city': {'type': 'string'}})]) is None
    assert file_url_note([schema('fetch_page', {'url': {'type': 'string'}}, 'Fetch a web page as markdown')]) is None
    assert file_url_note([schema('pdf_stats', {'query': {'type': 'string'}}, 'Search PDF statistics')]) is None
