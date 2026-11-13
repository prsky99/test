"""Run the opening-path tests against a release copy before it is deployed.

Releases are built by overlaying files on the active release, so tests in the working copy do
not prove the release. 11-02 07:01: batch-reads r5 passed in the working copy but every customer
opening page failed in production (gzip inside batched reads); 11-02: a release built from the
repository would have lost typed_engine_for. This copies the release and the repository's tests
into a scratch directory and runs a short list of tests there, at low priority (CLAUDE.md).

    .venv-tests/bin/python -m scripts.release_gate batch-reads-frontend-20261102-r6

When the release changes how Chat recommends (CHAT_FILES differ from the active frontend), it also
runs a fixed Chat evaluation sample on both releases against production, read-only, and refuses a
release that answers more of them wrongly (2nd review A-3, 2026-11-04). --skip-chat skips that.
"""
import argparse
import ast
import hashlib
import json
import time
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RELEASES = ROOT / 'gateway-data' / 'services' / 'releases'
# Fast checks of what every customer and public page needs to open (about a minute).
TESTS = (
    'tests/test_customer_batch.py',
    'tests/test_typed_engine_for.py',
    'tests/test_workspace_read_only_paths.py',
    'tests/test_front_first_entry_browser.py',
    'tests/test_workspace_entry_progress_browser.py',
    # AD Coin stays separate from organic selection (11-10: adcoin-credit-terms-frontend-r1 broke it and passed).
    'tests/test_ad_coin.py::test_organic_selection_cannot_import_ad_coin',
    # Screen quality bar (11-11): server-made pages open with zero console errors, and the main screens
    # keep 44px targets at desktop and phone widths.
    'tests/test_agent_adoption_browser.py::test_server_pages_have_no_console_errors_in_a_fresh_tab',
    'tests/test_main_ui_touch_targets.py',
    'tests/test_cookie_banner_phone.py',
    # Sponsored on main Explore and Chat (11-11): apart from results, nothing without a booking or when off.
    'tests/test_main_sponsored_browser.py',
    # 11-11 (PM): the public HTML policy itself: same bytes for everyone, no Set-Cookie, CSP hashes match the
    # inline scripts, live pages max-age=300 + swr 86400 (no s-maxage), others no-store (about 25 s together).
    'tests/test_public_page_cache.py',
    'tests/test_publication_security_audit.py::test_every_published_page_has_fresh_nonces_and_no_inline_handlers',
    # 11-11 (PM decision B): first-screen CSS is current and draws the first screen exactly like the full CSS.
    'tests/test_critical_css.py',
    'tests/test_earlier_asset_urls.py',  # 11-11: old bundle URLs keep their bytes after a deploy (swr condition)
    'tests/test_panels_split.py',  # 11-11: inactive panels in panels.js (HTML gzip about -40%)
    'tests/test_prerendered_segmented.py',  # 11-11: protocol groups drawn by the server, Chat phone CLS 0
    'tests/test_direct_sign_in_links.py',  # 11-12: our pages link to /customer/sign-in directly, no 303
    'tests/test_a2a_card_aliases.py',  # 11-12: the A2A card beside /a2a (two aliases that answered 404)
    'tests/test_public_html_long_swr.py',  # 11-12: live HTML swr 86400, private answers stay no-store
    'tests/test_home_about_layout.py',  # 11-13: Home without the toggle, spacing tokens; About necklace as a background
    # 11-12: discovery cards keep their public keys (usage_endpoint, tools_schema); ed37c569 dropped one.
    'tests/test_managed_agent_gateway.py::test_raw_discovery_json_and_text_hide_bindings_preserve_schema',
    # 11-12 (PM): the other public contracts, about 41 s together: MCP tools/list and search/find_agents,
    # A2A card and message/send, HTTP agent API, Explore API, well-known agent card, earlier QA contracts.
    'tests/test_mcp_contract.py',
    'tests/test_a2a.py',
    'tests/test_agent_http_interoperability.py',
    'tests/test_front_hybrid_discovery.py',
    'tests/test_front_seo_and_agent_discovery.py',
    'tests/test_qa10_contracts.py',
    'tests/test_qa11_contracts.py',
    'tests/test_sql_catalog_registration.py',  # 11-12: every SQL pair the code produces is registered
    'tests/test_front_dashboard_menus.py',  # 11-12 PM: the public frontend has no Korean text (01982678 slipped past the gate)
    'tests/test_panels_split_browser.py::test_the_page_is_the_same_with_the_panels_in_a_shared_script[index.html]',
    'tests/test_critical_css_browser.py::test_first_screen_with_inline_css_alone_matches_the_full_css[1280-light]',
    'tests/test_critical_css_browser.py::test_first_screen_with_inline_css_alone_matches_the_full_css[375-light]',
    'tests/test_notice_page_cache.py', 'tests/test_sitemap_parts.py', 'tests/test_csp_meta_removed.py',  # 11-13 PM 20:5x
    'tests/test_page_meta_trim.py',  # 11-13 PM 22:5x decision (b)
    'tests/test_brand_signals.py',  # 11-14 PM 02:2x search: brand title, JSON-LD names, visible brand
    'tests/test_noindex_tiers.py',  # 11-14 PM 03:1x search B: x402/thin/duplicate pages noindex and out of the sitemap
    'tests/test_a2a_run.py',  # 11-14 PM 04:0x: A2A "run N" within the MCP call tool's scope
    'tests/test_mcp_tool_descriptions.py',  # 11-14 PM 04:1x: tool purposes distinct, hints match behaviour (Glama)
    'tests/test_task_pages_job.py',  # 11-14 PM 03:2x: usage lines fill missing days; indexed fixtures after noindex tiers
    'tests/test_traffic.py',  # 11-14: day counts (tools/call by client name, Accept on /, funnel)
    'tests/test_first_run_fixes.py',  # 11-14 growth plan 7 item 4: a failed run says how to fix it
    'tests/test_run_here.py',  # 11-14 growth plan 7 item 3: the run line right under the first recommendation
    'tests/test_pearl_frontend.py',  # 11-14: the workspace text replacement follows the brand (AgentValCon broke it unseen)
    'tests/test_necklace_surface.py',  # 11-14 PM: necklace pages, list, feed and notices read the judged snapshot only
)
# Each role runs the tests for the code it serves. jobs releases run the collector, health checks,
# crawler and evaluation without the typed execution engine, so the opening-path list above
# (customer pages, typed_engine_for) does not apply to them (11-10: pct-cache-jobs and its base
# growth-md-jobs-r2 both failed collecting tests/test_typed_engine_for.py).
JOBS_TESTS = (
    'tests/test_collector.py',
    'tests/test_collector_observation_guards.py',
    'tests/test_crawler_x402_retry.py',
    'tests/test_a2a.py',
    'tests/test_evaluation.py',
    'tests/test_sql_catalog_registration.py',  # 11-12: jobs reads the same registered SQL list
)
ROLE_TESTS = {'frontend': TESTS, 'admin': TESTS, 'execution': TESTS, 'jobs': JOBS_TESTS}
ROLES = tuple(ROLE_TESTS)


def release_role(release):
    """The role a release was built for: release.json 'role', else the -<role>- part of its name."""
    manifest = RELEASES / release / 'release.json'
    try:
        declared = json.loads(manifest.read_text()).get('role')
    except (OSError, ValueError, AttributeError):
        declared = None
    if declared in ROLES:
        return declared
    found = [role for role in ROLES if f'-{role}-' in f'-{release}-']
    if len(found) != 1:
        raise SystemExit(f'release role unknown: {release} (name it <change>-<role>-<date>-rN)')
    return found[0]


# Files whose change can move a Chat recommendation (the policy-hash files and the Chat path).
CHAT_FILES = (
    'agent_market/concierge/selection.py', 'agent_market/concierge/discovery.py',
    'agent_market/concierge/task_requirements.py', 'agent_market/concierge/explore_search.py',
    'agent_market/concierge/execution_policy.py', 'agent_market/capability_registry.py',
    'agent_market/collector/usage.py', 'agent_market/postgres_capability_text.py',
    'agent_market/concierge/fast_chat.py', 'agent_market/concierge/llm.py',
    'agent_market/concierge/chat_guidance.py', 'agent_market/concierge/chat_query_rewrite.py',
    'agent_market/concierge/chat_task_spec.py', 'agent_market/concierge/task_conditions.py',
    'agent_market/concierge/query_intent.py', 'agent_market/concierge/engine.py',
    # 11-10: the recommender is wrapped in front.py (ExposedFirstRecommender from gateway_exposure.py).
    'agent_market/concierge/front.py', 'agent_market/concierge/gateway_exposure.py',
)
# Modules these import directly also count, read from each release, so a new helper on the Chat path
# triggers the check without editing this list.
CHAT_ROOTS = (
    'agent_market/concierge/fast_chat.py', 'agent_market/concierge/selection.py',
    'agent_market/concierge/gateway_exposure.py',
)
CASES_1K = ROOT / 'tests' / 'data' / 'chat_answer_quality_cases_1k.json'
CASES_REVIEW = ROOT / 'tests' / 'data' / 'chat_answer_quality_cases.json'
CHAT_SAMPLE = 100   # holdout cases, chosen by id hash so every gate reads the same ones
CHAT_MARGIN = 2     # refuse when new failures exceed new passes by this many


def active_frontend():
    state = json.loads((ROOT / 'gateway-data' / 'services' / 'state.json').read_text())['services']['frontend']
    return state['slots'][state['active']]


def chat_imports(root):
    """agent_market modules the CHAT_ROOTS of one release import directly (relative or absolute)."""
    found = []
    for name in CHAT_ROOTS:
        source = root / name
        if not source.is_file():
            continue
        try:
            tree = ast.parse(source.read_text(encoding='utf-8'))
        except (SyntaxError, UnicodeDecodeError):
            continue
        package = Path(name).parent
        for node in ast.walk(tree):
            if not isinstance(node, ast.ImportFrom):
                continue
            if node.level == 1:
                base = package
            elif node.level == 0 and (node.module or '').startswith('agent_market'):
                base = Path()
            else:
                continue
            stem = base / (node.module or '').replace('.', '/') if node.module else base
            candidates = [stem.with_suffix('.py')] + [stem / f'{alias.name}.py' for alias in node.names]
            found += [str(path) for path in candidates if (root / path).is_file()]
    return found


def chat_changed(release, active):
    """Chat files (CHAT_FILES plus the direct imports of CHAT_ROOTS) whose bytes differ."""
    def read(name, path):
        target = RELEASES / name / path
        return target.read_bytes() if target.is_file() else None
    paths = dict.fromkeys(CHAT_FILES + tuple(chat_imports(RELEASES / release)) + tuple(chat_imports(RELEASES / active)))
    return [path for path in paths if read(release, path) != read(active, path)]


def chat_sample(size=CHAT_SAMPLE):
    holdout = json.loads(CASES_1K.read_text(encoding='utf-8'))['holdout']
    picked = sorted(holdout, key=lambda case: hashlib.sha1(case['id'].encode()).hexdigest())[:size]
    review = json.loads(CASES_REVIEW.read_text(encoding='utf-8')).get('review', [])
    return review + picked


def evaluate(release, cases_file, out, only=None):
    python = ROOT / '.venv' / 'bin' / 'python'
    env = {**os.environ, **({'EVAL_ONLY': ','.join(only)} if only else {})}
    env.pop('EVAL_REPEAT', None); env.pop('EVAL_SUBSET', None); env.pop('EVAL_RECALL', None)
    subprocess.run(['nice', '-n', '10', str(python), '-B', 'scripts/evaluate_chat_answer_quality.py',
                    str(RELEASES / release), f'{cases_file}:gate', str(out)],
                   cwd=ROOT, env=env, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return {row['id']: bool(row['ok']) for row in json.loads(Path(out).read_text(encoding='utf-8'))}


def compare(before, after):
    """(new failures, new passes) between two {id: ok} verdicts on the same cases."""
    broken = sorted(i for i in before if before[i] and not after.get(i, False))
    fixed = sorted(i for i in before if not before[i] and after.get(i, False))
    return broken, fixed


CHAT_RECORDS = ROOT / 'logs' / 'ops' / 'chat-gate'


def record_chat_check(release, active, before, after, broken, fixed):
    """Keep each case's verdict (PM 11-13 23:3x): the active release went from 93 to 92 of 110 between two gates
    and no record said which case moved. A failed write never fails the gate."""
    try:
        CHAT_RECORDS.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime('%Y%m%d-%H%M%S')
        (CHAT_RECORDS / f'{stamp}-{release}.json').write_text(json.dumps(
            {'at': stamp, 'release': release, 'active': active, 'active_verdicts': before, 'release_verdicts': after,
             'new_failures': broken, 'new_passes': fixed}, indent=1, sort_keys=True), encoding='utf-8')
    except OSError:
        pass


def chat_check(release, active=None, *, evaluate=evaluate):
    """0 when the release answers the sample no worse than the active frontend, 1 otherwise."""
    active = active or active_frontend()
    changed = chat_changed(release, active)
    if not changed:
        print(f'chat check: skipped (no Chat file differs from {active})')
        return 0
    print(f'chat check: {len(changed)} Chat file(s) differ from {active}: ' + ', '.join(Path(p).name for p in changed))
    with tempfile.TemporaryDirectory(prefix='chat-gate-') as scratch:
        cases = Path(scratch) / 'cases.json'
        cases.write_text(json.dumps({'gate': chat_sample()}), encoding='utf-8')
        before = evaluate(active, cases, Path(scratch) / 'active.json')
        after = evaluate(release, cases, Path(scratch) / 'release.json')
        broken, fixed = compare(before, after)
        if broken:
            # A verdict that flips on a second run is noise (live health, model load), and a case the
            # active release now fails too was moved by catalog data, not by the release (11-04:
            # stock_quote-ask failed on both after a new listing ranked first).
            again = evaluate(release, cases, Path(scratch) / 'again.json', only=broken)
            still = evaluate(active, cases, Path(scratch) / 'active-again.json', only=broken)
            broken = [i for i in broken if not again.get(i, False) and still.get(i, False)]
    print(f'chat check: active {sum(before.values())}/{len(before)}, release {sum(after.values())}/{len(after)}; '
          f'new failures {len(broken)} {broken[:10]}, new passes {len(fixed)}')
    record_chat_check(release, active, before, after, broken, fixed)
    if len(broken) - len(fixed) >= CHAT_MARGIN:
        print('chat check: FAILED (more new failures than passes; see scripts/evaluate_chat_answer_quality.py)')
        return 1
    return 0


def committed_tests(target, commit='HEAD'):
    """Committed tests, not the working copy: other sessions' uncommitted test edits in the shared
    working tree failed an unrelated jobs release on 11-10 (scavenger and health-lane tests).
    COMMIT is the release's own commit (release.json), so a test added for a later feature is not run
    against a release that predates it (11-12 00:01: am08-frontend at 414782c6 failed collecting
    test_prerendered_segmented.py from 43275460). An unknown commit falls back to HEAD."""
    (target / 'tests').mkdir(exist_ok=True)
    archive = subprocess.run(['git', 'archive', commit, 'tests'], cwd=ROOT, capture_output=True)
    if archive.returncode != 0 and commit != 'HEAD':
        archive = subprocess.run(['git', 'archive', 'HEAD', 'tests'], cwd=ROOT, capture_output=True)
    if archive.returncode == 0:
        subprocess.run(['tar', '-x', '-C', str(target)], input=archive.stdout, check=True)
    else:  # not a git checkout: fall back to the files on disk
        shutil.rmtree(target / 'tests')
        shutil.copytree(ROOT / 'tests', target / 'tests')


def present(tests, copy):
    """(tests whose file exists in the copy, the others). Files missing at the release's commit belong to
    later changes; the list itself is checked against HEAD by tests/test_release_gate.py."""
    kept = [t for t in tests if (copy / t.split('::')[0]).is_file()]
    return kept, [t for t in tests if t not in kept]


def copy_release(release, into):
    source = RELEASES / release
    if not (source / 'release.json').is_file():
        raise SystemExit(f'release not found: {release}')
    target = into / release
    # APFS clones (cp -c) make a full copy of a release almost free.
    subprocess.run(['cp', '-cR', str(source), str(target)], check=True)
    try:
        commit = json.loads((source / 'release.json').read_text()).get('commit') or 'HEAD'
    except (ValueError, OSError):
        commit = 'HEAD'
    committed_tests(target, commit)
    for name in ('pytest.ini', 'conftest.py', 'pyproject.toml', 'setup.cfg'):
        if (ROOT / name).is_file() and not (target / name).exists():
            shutil.copy2(ROOT / name, target / name)
    return target


def run(release, tests, python):
    with tempfile.TemporaryDirectory(prefix='release-gate-') as scratch:
        copy = copy_release(release, Path(scratch).resolve())
        env = {**os.environ, 'PYTHONPATH': str(copy)}
        where = subprocess.run([python, '-c', 'import agent_market; print(agent_market.__file__)'],
                               cwd=copy, env=env, capture_output=True, text=True, check=True).stdout.strip()
        if not str(Path(where).resolve()).startswith(str(copy)):
            raise SystemExit(f'tests would import the wrong code: {where}')
        tests, missing = present(tests, copy)
        if missing:
            print(f'release gate {release}: not at the release commit, skipped: ' + ', '.join(missing))
        if not tests:  # pytest with no arguments would run every test in the copy
            print(f'release gate {release}: no listed test exists at the release commit')
            return 5
        result = subprocess.run(['nice', '-n', '10', python, '-m', 'pytest', '-q', '-p', 'no:cacheprovider', *tests],
                                cwd=copy, env=env)
        return result.returncode


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('release')
    parser.add_argument('tests', nargs='*')
    parser.add_argument('--python', default=sys.executable)
    parser.add_argument('--skip-chat', action='store_true', help='skip the Chat evaluation comparison')
    args = parser.parse_args(argv)
    role = release_role(args.release)
    tests = args.tests or list(ROLE_TESTS[role])
    print(f'release gate {args.release}: role {role}, {len(tests)} test file(s)')
    code = run(args.release, tests, args.python)
    # Chat answers come from the frontend; other roles are not compared with the active frontend.
    if code == 0 and not args.skip_chat and role == 'frontend':
        code = chat_check(args.release)
    print(f'release gate {args.release}: ' + ('passed' if code == 0 else f'FAILED (pytest exit {code})'))
    return code


if __name__ == '__main__':
    raise SystemExit(main())
