"""scripts/paid_task_guidance.py: four strict checks for paid or keyed tasks, apart from the completion score."""
import json

from scripts import paid_task_guidance as g

P15 = {'id': 'p15', 'task': 'Find an API that gives me the transcript of a YouTube video',
       'needs': 'YouTube transcript or captions for a video URL', 'sample_input': {'url': 'https://www.youtube.com/watch?v=x'},
       'free_check': False, 'check': {'all': ['(?i)never gonna|transcript|caption']}}
FILE_TOOL = {'name': 'transcribe_to_markdown', 'description': 'Convert audio/video files into Markdown transcripts.',
             'inputSchema': {'properties': {'file_path': {'type': 'string'}}, 'required': ['file_path']}}
URL_TOOL = {'name': 'get_transcript', 'description': 'Timed caption text for a YouTube video URL.',
            'inputSchema': {'properties': {'url': {'type': 'string', 'description': 'YouTube link'}}, 'required': ['url']}}
SUMMARY_TOOL = {'name': 'summarize_video', 'description': 'Summaries, key points and chapters of YouTube transcripts.',
                'inputSchema': {'properties': {'url': {'type': 'string'}}}}


def test_a_file_only_tool_does_not_fit_a_link_task():
    assert g.input_fit(FILE_TOOL, P15['sample_input'])[0] is False
    assert g.input_fit(URL_TOOL, P15['sample_input'])[0] is True


def test_a_summary_tool_does_not_return_captions():
    assert g.output_fit(P15, URL_TOOL)[0] is True
    assert g.output_fit(P15, SUMMARY_TOOL)[0] is False


def test_what_the_recommendation_tells_before_connecting():
    assert g.disclosed({'price_usdc': 0, 'auth_required': False}) is None
    assert g.disclosed({'price_usdc': 0.002}) == 'paid'
    assert g.disclosed({'kind': 'x402'}) == 'paid'
    assert g.disclosed({'price_usdc': 0, 'auth_required': True}) == 'key'


def fake_rpc(answers):
    calls = []

    def rpc(client, url, method, params=None, rid=1):
        calls.append((url, method, (params or {}).get('name')))
        return answers(url, method, params)
    return rpc, calls


def recommendation(price=0, auth=False, tool='get_transcript'):
    return {'result': {'structuredContent': {'recommendations': [
        {'id': 7, 'kind': 'mcp', 'name': 'Captions', 'price_usdc': price, 'auth_required': auth,
         'reason': {'tool': tool}, 'tools': [tool]}]}}}


def test_passes_only_when_all_four_hold(monkeypatch):
    def answers(url, method, params):
        if url.endswith('/mcp'):
            return 200, recommendation(price=0.002)
        if method == 'tools/list':
            return 200, {'result': {'tools': [URL_TOOL]}}
        if method == 'tools/call':
            return 402, {'error': {'code': 402, 'message': 'Payment required', 'data': {'maxAmountRequired': '2000'}}}
        return 200, {'result': {}}
    rpc, calls = fake_rpc(answers)
    monkeypatch.setattr(g, 'rpc', rpc)
    row = g.score(None, P15)
    assert row['passed'] is True and all(c['ok'] for c in row['checks'].values())
    assert [c[1] for c in calls] == ['tools/call', 'initialize', 'tools/list', 'tools/call']  # one unpaid call, no payment


def test_presented_as_free_but_asks_for_payment_fails_disclosure(monkeypatch):
    def answers(url, method, params):
        if url.endswith('/mcp'):
            return 200, recommendation(price=0)
        if method == 'tools/list':
            return 200, {'result': {'tools': [URL_TOOL]}}
        if method == 'tools/call':
            return 402, {'error': {'code': 402, 'message': 'x402 payment required: $0.002 per minute'}}
        return 200, {'result': {}}
    rpc, _ = fake_rpc(answers)
    monkeypatch.setattr(g, 'rpc', rpc)
    row = g.score(None, P15)
    assert row['passed'] is False and row['checks']['disclosed']['ok'] is False and row['checks']['unpaid_call']['ok']


def test_todays_kind_of_answer_fails_on_input(monkeypatch):
    # 11-11 23시: Frenchie's file transcriber, presented as free, for a YouTube link.
    def answers(url, method, params):
        if url.endswith('/mcp'):
            return 200, recommendation(price=0, tool='transcribe_to_markdown')
        if method == 'tools/list':
            return 200, {'result': {'tools': [FILE_TOOL]}}
        if method == 'tools/call':
            return 200, {'result': {'isError': True, 'content': [{'type': 'text', 'text': 'file not found'}]}}
        return 200, {'result': {}}
    rpc, _ = fake_rpc(answers)
    monkeypatch.setattr(g, 'rpc', rpc)
    row = g.score(None, P15)
    assert row['passed'] is False
    assert row['checks']['input_fit']['ok'] is False and row['checks']['disclosed']['ok'] is False


def test_a_free_answer_flags_the_task_for_real_calls(monkeypatch):
    def answers(url, method, params):
        if url.endswith('/mcp'):
            return 200, recommendation()
        if method == 'tools/list':
            return 200, {'result': {'tools': [URL_TOOL]}}
        return 200, {'result': {'content': [{'type': 'text', 'text': json.dumps({'transcript': 'never gonna give you up'})}]}}
    rpc, _ = fake_rpc(answers)
    monkeypatch.setattr(g, 'rpc', rpc)
    row = g.score(None, P15)
    assert row['free_source_found'] is True and row['passed'] is False
