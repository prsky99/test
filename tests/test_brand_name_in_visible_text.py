"""The public name is AgentValCon (user decision 11-14); the old name stays out of what people and agents see (PM 11-15).

Scans the runtime code and served files (agent_market, new/en, integrations), not comments, docs or one-off scripts.
Kept on purpose, so they are allowed:
- identifiers and addresses: the domain agentconcierge.biz, the registry name biz.agentconcierge/..., the package
  agent_concierge, the server name agent-concierge (none of these is the two-word name);
- public_availability.SERVICE_NAMES and public_metadata.BRAND_ALIASES, which match either name in our own checks;
- comment lines.
A new screen, mail or answer that says the old name fails here; add a reasoned allow entry only for a matching rule."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OLD = 'Agent Concierge'
SCAN = [('agent_market', ('.py', '.html', '.js', '.json', '.svg', '.css', '.txt')),
        ('new/en', ('.html', '.js', '.json', '.svg', '.css', '.txt')),
        ('integrations', ('.py', '.js', '.json', '.toml')),
        ('agent_market/concierge/claude_plugin', ('.md',)),            # shipped in the plugin archive
        ('integrations/claude-code-plugin', ('.md',)),
        ('agent_market/agent_access/distribution', ('.md',))]
ALLOWED = {
    'agent_market/public_availability.py': 'SERVICE_NAMES',      # either name means our own service in checks
    'agent_market/concierge/public_metadata.py': 'BRAND_ALIASES',  # aliases that point at us
}


def offending_lines():
    found = []
    for folder, suffixes in SCAN:
        for path in (ROOT / folder).rglob('*'):
            if not path.is_file() or path.suffix not in suffixes or '__pycache__' in path.parts:
                continue
            rel = path.relative_to(ROOT).as_posix()
            try:
                text = path.read_text(encoding='utf-8')
            except (UnicodeDecodeError, OSError):
                continue
            if OLD not in text:
                continue
            for number, line in enumerate(text.splitlines(), 1):
                if OLD not in line:
                    continue
                stripped = line.strip()
                if stripped.startswith(('#', '//', '*', '/*')):
                    continue
                if rel in ALLOWED and ALLOWED[rel] in line:
                    continue
                found.append(f'{rel}:{number}: {stripped[:120]}')
    return found


def test_visible_text_uses_the_current_name():
    assert offending_lines() == []
