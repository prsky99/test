"""Check public frontend language, Chat presentation, and metadata consistency.

Run from any directory: python scripts/check_front_content.py
List the selected files without checking content: add --list.
"""
import argparse
import ast
import re
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HANGUL = re.compile(r'[\u1100-\u11ff\u3130-\u318f\ua960-\ua97f\uac00-\ud7af\ud7b0-\ud7ff]')
COMMERCIAL = re.compile(r'\b(?:free|paid|micro[ -]?payments?|payments?|billing|pricing|prices?|fees?|costs?|charges?|subscriptions?|wallets?|USDC)\b', re.I)


class ChatText(HTMLParser):
    def __init__(self):
        super().__init__()
        self.text = []

    def handle_data(self, text):
        self.text.append(text)


def public_content_paths():
    """Return the checker's exact source inventory in deterministic path order."""
    paths = {p for p in (ROOT / 'agent_market/concierge').rglob('*')
             if p.is_file() and p.suffix in ('.py', '.html', '.js', '.css', '.svg')}
    paths.update(p for p in (ROOT / 'agent_market/owned_data_agents').glob('*.py')
                 if p.is_file())
    paths.update(p for p in (ROOT / 'agent_market/agent_access').rglob('*')
                 if p.is_file() and p.suffix in ('.py', '.json', '.html', '.js', '.css'))
    paths.update(ROOT / name for name in ('extracted_html.txt', 'AGENT_FRONT.md'))
    paths.update(ROOT / 'agent_market/edge_gateway' / name for name in ('sdk.js', 'router.py', 'service.py'))
    # The default entry serves the built publication. Check its public assets
    # and generator alongside the retained embedded presentation.
    for directory in ('new/en', 'new/html', 'new/live-assets'):
        paths.update(p for p in (ROOT / directory).rglob('*')
                     if p.is_file() and p.suffix in ('.html', '.js', '.css', '.svg'))
    paths.update(p for p in (ROOT / 'new').glob('*')
                 if p.is_file() and p.suffix in ('.py', '.js'))
    # These administrator-generated packages are public frontend artifacts too.
    paths.update(p for p in (ROOT / 'agent_market/gateway/webapp').glob('*')
                 if p.is_file() and p.suffix in ('.js', '.html', '.css', '.svg'))
    paths.update(ROOT / 'agent_market' / name for name in (
        'workflow_webapp.py', 'admin_workflow_webapp.py', 'admin_workflow_webapp_v12.py',
        'admin_workflow_webapp_v13.py',
        'public_workflow_connection.py', 'customer_identity_service.py', 'customer_identity_view.py', 'customer_organization_service.py',
        'customer_authoring.py', 'customer_authoring_service.py', 'customer_authoring_view.py',
        'customer_credits.py', 'customer_credit_service.py', 'customer_credit_view.py', 'customer_workspace_pearl.py',
        'customer_recovery_service.py', 'customer_recovery_view.py', 'workspace_support_view.py',
        'first_party_corpus.py', 'customer_typed_authoring_view.py', 'customer_template_hub_view.py', 'customer_studio_design.py', 'workspace_template_hub.py',
        'customer_provider_connections_service.py', 'customer_provider_connections_view.py', 'workspace_provider_connections.py',
        'first_party_guides.py',
        'reliability_public_receipt.py',
        'workspace_release_service.py', 'workspace_sdk_bff.py')
        if (ROOT / 'agent_market' / name).is_file())
    for p in (ROOT / 'scripts').glob('*.py'):
        content = p.read_text()
        if 'concierge/front.py' in content or 'extracted_html.txt' in content:
            paths.add(p)
    return tuple(sorted(paths))


def check():
    paths = public_content_paths()
    errors = []
    for p in paths:
        for number, line in enumerate(p.read_text().splitlines(), 1):
            if HANGUL.search(line):
                errors.append(f'{p.relative_to(ROOT)}:{number}: literal Hangul in public frontend source')
    module = ast.parse((ROOT / 'agent_market/concierge/front.py').read_text())
    html = next(n.value.value for n in module.body if isinstance(n, ast.Assign)
                and any(isinstance(t, ast.Name) and t.id == 'HTML' for t in n.targets))
    if html != (ROOT / 'extracted_html.txt').read_text():
        errors.append('The embedded HTML and extracted_html.txt are out of sync')
    chat = html.split('<section id="secChat"', 1)[1].split('</section>', 1)[0]
    parser = ChatText()
    parser.feed(chat)
    if COMMERCIAL.search(' '.join(parser.text)):
        errors.append('Commercial language in the Chat section')
    for removed in ('chatVisitorTokenDisplay', 'chatOutput', 'chatCallingSpecCode', 'Global Protocol Runtime:'):
        if removed in html:
            errors.append(f'Removed private/development presentation found: {removed}')
    for required in ('id="homeRecommendationIntro"', 'One task. Three relevant agents.',
                     'name="page:overview:target-action" content="find-up-to-three-verified-agents"',
                     'name="page:chat:target-action" content="three-recent-verified-recommendations-a2a-then-mcp"',
                     'latest successful test report'):
        if required not in html:
            errors.append(f'Missing current discovery content: {required}')
    return len(paths), errors


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--list', action='store_true',
                        help='Print the sorted repository-relative file inventory without checking content.')
    args = parser.parse_args()
    if args.list:
        for path in public_content_paths():
            print(path.relative_to(ROOT).as_posix())
        raise SystemExit(0)
    count, errors = check()
    for error in errors:
        print(error)
    print(f'{count} public frontend files checked; {len(errors)} content policy violations.')
    raise SystemExit(bool(errors))
