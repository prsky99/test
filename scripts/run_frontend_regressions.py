"""CI entry point: isolated public feature/security tests and offline policy corpus.

An optional catalog database is opened read-only by the audit command. No live
provider or production deployment check runs automatically.
"""
import argparse
import ast
import importlib
from pathlib import Path
import shutil
# Fixed interpreter/argument arrays only; no shell execution.
import subprocess  # nosec B404
import sys


ROOT = Path(__file__).resolve().parents[1]
PATTERNS = (
    'test_front_*.py', 'test_workflow_*.py', 'test_single_*.py', 'test_recent_*.py',
    'test_managed_*.py', 'test_footer_*.py', 'test_notification_*.py',
    'test_destination_*.py', 'test_task_updates_*.py', 'test_visitor_desk*.py',
    'test_catalog_policy_and_live_examples.py', 'test_gateway_execution_regression.py',
    'test_gateway_projection*.py', 'test_gateway_report_projection*.py', 'test_gateway_schema_projection.py',
    'test_testbench_initialization.py', 'test_execution_error_categories.py',
    'test_fast_single_recommendation.py', 'test_mcp_proxy.py', 'test_customer_requests_hub.py',
    'test_gateway_startup.py', 'test_storage_lock_safety.py', 'test_logging.py',
    'test_operational_observability*.py', 'test_admin_security_audit.py', 'test_admin_security_browser.py',
    'test_capability_registry*.py', 'test_capability_adapters*.py', 'test_collector.py',
    'test_execution_authority*.py', 'test_admin_webapp_*.py',
    'test_admin_test_reports_and_workflows.py',
    'test_workspace*.py', 'test_customer_identity*.py', 'test_customer_workspace_runtime.py',
    'test_customer_organizations*.py',
    'test_customer_recovery*.py', 'test_customer_task_outcomes*.py', 'test_agentcon*.py',
    'test_stripe*.py',
    'test_first_party_corpus.py', 'test_customer_typed_authoring*.py',
    'test_customer_a2a_sessions*.py',
    'test_customer_authoring*.py', 'test_customer_ten_workflows*.py', 'test_needs_security.py',
    'test_privacy_review_admin_browser.py',
    'test_provider_claims*.py', 'test_advancement*.py', 'test_private_platform*.py',
    'test_store_migration*.py',
    'test_storage_*.py',
    'test_first_party_guides.py', 'test_application_*.py',
    'test_evidence_rollup*.py', 'test_postgres_archive*.py',
    'test_reliability_*.py', 'test_visitor_hit_worker.py', 'test_phase2_restore_quarantine.py',
    'test_postgres_operational*.py', 'test_postgres_restore*.py',
    'test_sns.py',
    'test_admin_refresh_pacing_browser.py', 'test_collector_observation_guards.py',
    'test_concierge.py', 'test_home_measured_verification.py',
    'test_observation_recording_recovery.py', 'test_operational_logging_limits.py',
    'test_report_*.py', 'test_vector_queue_progress.py',
    'test_execution_availability.py', 'test_execution_recovery_browser.py',
    'test_explore_report_*.py',
    'test_pearl_*.py',
)

# Independently maintained protection against silently dropping critical suites
# when filename patterns change. Each module must exist and belong to the union
# before any shard starts; an empty shard still never discovers unrelated tests.
REQUIRED_TESTS = (
    'test_capability_adapters.py', 'test_capability_adapters_browser.py',
    'test_customer_ten_workflows.py', 'test_customer_ten_workflows_browser.py',
    'test_admin_refresh_pacing_browser.py', 'test_collector_observation_guards.py',
    'test_concierge.py', 'test_home_measured_verification.py',
    'test_observation_recording_recovery.py', 'test_operational_logging_limits.py',
    'test_report_evidence_binding.py', 'test_report_sql_catalog.py',
    'test_vector_queue_progress.py', 'test_execution_availability.py',
    'test_execution_recovery_browser.py', 'test_explore_report_filter_browser.py',
    'test_explore_report_identity.py', 'test_report_binding_repair.py',
    'test_customer_authoring.py', 'test_customer_authoring_browser.py',
    'test_workspace_remote_a2a.py', 'test_workspace_crypto_inspection_api.py',
    'test_workspace_machine_automation.py', 'test_workspace_model_proposal.py',
    'test_reliability_public_receipt.py', 'test_workspace_remote_a2a_browser.py',
    'test_privacy_review_admin_browser.py',
    'test_customer_recovery.py', 'test_customer_recovery_browser.py',
    'test_customer_typed_authoring.py', 'test_customer_typed_authoring_browser.py',
    'test_first_party_corpus.py', 'test_workspace_a2a_sessions.py',
    'test_reliability_closeout_controllers.py', 'test_stripe_sandbox.py',
    'test_application_runtime.py', 'test_agentcon_config.py',
    'test_customer_a2a_sessions.py', 'test_customer_a2a_sessions_browser.py',
    'test_workflow_model_ollama.py', 'test_application_control_retention.py',
    'test_pearl_frontend.py', 'test_workflow_ai_providers.py', 'test_workflow_chatgpt_reconnect.py',
    'test_pearl_menu_compositions.py', 'test_pearl_task_ux.py', 'test_pearl_publication.py',
)


def validate_required_tests():
    selected = set(selected_tests())
    missing = ['tests/' + name for name in REQUIRED_TESTS
               if not (ROOT / 'tests' / name).is_file() or 'tests/' + name not in selected]
    if missing:
        raise ValueError('Required regression modules missing from selection: ' + ', '.join(missing))


def selected_tests(shard_index=1, shard_count=1):
    """Return a stable file shard; omitted arguments preserve the full corpus."""
    if (type(shard_count) is not int or not 1 <= shard_count <= 64
            or type(shard_index) is not int or not 1 <= shard_index <= shard_count):
        raise ValueError('Use a shard count from 1 to 64 and an index from 1 to that count.')
    tests = sorted({str(path.relative_to(ROOT)) for pattern in PATTERNS
                    for path in (ROOT / 'tests').glob(pattern)})
    return tests[shard_index - 1::shard_count]


def prepare_screenshot_directories(tests):
    for name in tests:
        for node in ast.walk(ast.parse((ROOT / name).read_text())):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute) or node.func.attr != 'screenshot':
                continue
            for arg in node.keywords:
                if arg.arg == 'path' and isinstance(arg.value, ast.Constant) and isinstance(arg.value.value, str):
                    destination = (ROOT / arg.value.value).resolve()
                    if destination.is_relative_to(ROOT / 'reports'):
                        destination.parent.mkdir(parents=True, exist_ok=True)


def validate_native_dependencies(tests):
    """Fail before launching a large native cohort with missing test tooling."""
    native = any('postgres' in Path(name).name or (
        'rehearse' in (ROOT / name).read_text() and 'postgres' in (ROOT / name).read_text())
        for name in tests)
    if not native:
        return
    try:
        driver = importlib.import_module('psycopg')
        if not callable(getattr(driver, 'connect', None)):
            raise ImportError
    except (ImportError, OSError):
        raise ValueError('Native PostgreSQL regressions require requirements-storage-postgres.txt in this interpreter.') from None
    from scripts.rehearse_storage_adapter_postgres import _tools, RehearsalError, TOOL_PATH
    if not all(shutil.which(name,path=TOOL_PATH) for name in ('initdb','pg_ctl')):
        raise ValueError('Native PostgreSQL regressions require local initdb and pg_ctl tools.')
    try:_tools()
    except RehearsalError:
        raise ValueError('Native PostgreSQL regressions require local initdb and pg_ctl tools.')


def run(args):
    # All commands use this interpreter and fixed module/script names.
    return subprocess.run([sys.executable, *args], cwd=ROOT, check=False).returncode  # noqa: S603 -- fixed interpreter and internal argument lists


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / 'reports/frontend-regressions')
    parser.add_argument('--catalog-db', type=Path, help='Explicit optional offline catalog; never copied to CI artifacts.')
    parser.add_argument('--list', action='store_true', help='List test modules without executing them.')
    parser.add_argument('--shard-index', type=int, default=1, help='One-based file shard index (default: 1).')
    parser.add_argument('--shard-count', type=int, default=1, help='Total deterministic file shards, 1 to 64 (default: 1).')
    args = parser.parse_args()
    try:
        validate_required_tests()
        tests = selected_tests(args.shard_index, args.shard_count)
    except ValueError as error:
        parser.error(str(error))
    if args.list:
        print('\n'.join(tests))
        return 0
    if not tests:
        # Passing no module paths to pytest would discover the whole corpus.
        print('No test modules assigned to this shard.')
        return 0
    try:
        validate_native_dependencies(tests)
    except ValueError as error:
        parser.error(str(error))
    if args.catalog_db and not args.catalog_db.is_file():
        parser.error('The optional catalog file must exist.')
    args.output = args.output.resolve()
    args.output.mkdir(parents=True, exist_ok=True)
    prepare_screenshot_directories(tests)
    code = run(['scripts/check_front_content.py'])
    if code:
        return code
    if args.catalog_db:
        code = run(['-m', 'scripts.audit_gateway_catalog', str(args.catalog_db.resolve()),
                    str(args.output / 'catalog-audit.json')])
        if code:
            return code
    return run(['-m', 'pytest', '-q', *tests, '--junitxml=' + str(args.output / 'regression.xml')])


if __name__ == '__main__':
    raise SystemExit(main())
