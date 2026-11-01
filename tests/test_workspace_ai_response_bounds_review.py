"""Independent response-bound repro; the planner is a synthetic transport only."""
import gzip
import json
from types import SimpleNamespace

import httpx
import pytest

from agent_market.workspace_ai_support import WorkspaceAISupport
from agent_market.workspace_access import WorkspaceInvalid
from tests.test_workspace_ai_support import ask
from tests.test_advancement_tools import tools


def test_model_response_does_not_accept_automatic_compression_before_body_bound(tools):
    value = {'answer': 'Review the saved snapshot guidance.', 'documents': ['private-snapshots'], 'changes': {}}
    envelope = json.dumps({'message': {'content': json.dumps(value)}}).encode()
    seen, reads = [], []
    class EncodedBody(httpx.SyncByteStream):
        def __iter__(self):
            reads.append(True)
            yield gzip.compress(envelope)
    def respond(request):
        seen.append(request)
        return httpx.Response(200, headers={'Content-Encoding': 'gzip'}, stream=EncodedBody())
    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        core = WorkspaceAISupport(tools['access'], SimpleNamespace(ollama_url='http://planner.test',
            generation_model='synthetic-model', http=client))
        with pytest.raises(WorkspaceInvalid):
            ask(tools, core)
    assert len(seen) == 1
    assert seen[0].headers['accept-encoding'] == 'identity' and not reads
    assert tools['store']._db.execute('SELECT COUNT(*) FROM workspace_support_proposals').fetchone()[0] == 0


@pytest.mark.parametrize('length', ['16385', '-1', 'unknown', '16,16'])
def test_model_invalid_or_oversized_length_is_refused_before_body_read(tools, length):
    reads = []
    class Body(httpx.SyncByteStream):
        def __iter__(self):
            reads.append(True)
            yield b'{}'
    with httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(200,
            headers={'Content-Length': length}, stream=Body()))) as client:
        core = WorkspaceAISupport(tools['access'], SimpleNamespace(ollama_url='http://planner.test',
            generation_model='synthetic-model', http=client))
        with pytest.raises(WorkspaceInvalid): ask(tools, core)
    assert not reads
