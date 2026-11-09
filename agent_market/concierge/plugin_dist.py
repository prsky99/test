"""Self-hosted Claude Code marketplace for the Agent Concierge plugin (11-10, no GitHub).

    /plugin marketplace add https://agentconcierge.biz/claude-plugins/marketplace.json
    /plugin install agent-concierge@agent-concierge

A marketplace added by URL downloads only marketplace.json, so the plugin entry uses an `archive`
source: a zip served next to it with its sha256. The zip is built in memory from the files in
claude_plugin/ (a copy of integrations/claude-code-plugin, kept equal by a test) with fixed
timestamps, so the same files always give the same bytes and hash.
"""
import hashlib
import io
import json
import zipfile
from functools import lru_cache
from pathlib import Path

ORIGIN = 'https://agentconcierge.biz'
SOURCE = Path(__file__).with_name('claude_plugin')
FILES = ('.claude-plugin/plugin.json', '.mcp.json', 'skills/find-agent/SKILL.md', 'README.md')
NAME = 'agent-concierge'
DESCRIPTION = 'Find AI agents and MCP servers for a task, ranked by recorded checks.'


def version():
    return json.loads((SOURCE / '.claude-plugin/plugin.json').read_text(encoding='utf-8'))['version']


def zip_name():
    return f'{NAME}-plugin-{version()}.zip'


@lru_cache(maxsize=1)
def archive():
    """(zip bytes, sha256 hex) built deterministically from the plugin files."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as out:
        for name in FILES:
            info = zipfile.ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0))
            info.external_attr = 0o644 << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            out.writestr(info, (SOURCE / name).read_bytes())
    data = buffer.getvalue()
    return data, hashlib.sha256(data).hexdigest()


def marketplace():
    _, sha = archive()
    return {'name': NAME, 'owner': {'name': 'Agent Concierge', 'url': ORIGIN},
            'metadata': {'description': 'Agent Concierge: ' + DESCRIPTION[0].lower() + DESCRIPTION[1:]},
            'plugins': [{'name': NAME, 'description': DESCRIPTION, 'version': version(),
                         'source': {'source': 'archive', 'url': f'{ORIGIN}/claude-plugins/{zip_name()}', 'sha256': sha}}]}


def install(router):
    from fastapi.responses import JSONResponse, Response

    @router.get('/claude-plugins/marketplace.json', include_in_schema=False)
    def plugin_marketplace():
        return JSONResponse(marketplace(), headers={'Cache-Control': 'public, max-age=300'})

    @router.get('/claude-plugins/{name}', include_in_schema=False)
    def plugin_archive(name: str):
        if name != zip_name():
            return Response(status_code=404)
        data, sha = archive()
        return Response(data, media_type='application/zip', headers={
            'Cache-Control': 'public, max-age=3600', 'Content-Disposition': f'attachment; filename="{name}"',
            'ETag': '"'+sha[:32]+'"'})
