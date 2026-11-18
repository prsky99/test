"""PM 11-18: a Python child a test starts (a rehearsal in a private cluster) cannot reach the outside network either."""
import os
import subprocess
import sys
from pathlib import Path

GUARD = Path(__file__).resolve().parent / 'child_guard'
CODE = '''
import socket, sys
for host in ("93.184.216.34", "8.8.8.8", "2606:4700:4700::1111"):
    s = socket.socket(socket.AF_INET6 if ":" in host else socket.AF_INET)
    s.settimeout(1)
    try:
        s.connect((host, 80))
        print("CONNECTED", host); sys.exit(2)
    except PermissionError:
        pass
    except OSError as error:
        print("OS", host, error); sys.exit(3)
print("blocked")
'''


def run(env_extra=None, path=True):
    env = {'PATH': os.environ.get('PATH', ''), 'PYTHONDONTWRITEBYTECODE': '1', **(env_extra or {})}
    if path:
        env['PYTHONPATH'] = str(GUARD)
    return subprocess.run([sys.executable, '-c', CODE], env=env, capture_output=True, text=True, timeout=20)


def test_a_child_with_the_guard_folder_cannot_connect_outside():
    done = run()
    assert done.returncode == 0 and done.stdout.strip() == 'blocked', done.stdout + done.stderr


def test_loopback_and_private_addresses_still_connect_or_fail_normally():
    code = ('import socket\ns = socket.socket(); s.settimeout(1)\n'
            'try:\n    s.connect(("127.0.0.1", 9))\nexcept PermissionError:\n    raise SystemExit(5)\nexcept OSError:\n    pass\n'
            'print("ok")')
    env = {'PATH': os.environ.get('PATH', ''), 'PYTHONPATH': str(GUARD)}
    done = subprocess.run([sys.executable, '-c', code], env=env, capture_output=True, text=True, timeout=20)
    assert done.returncode == 0 and done.stdout.strip() == 'ok', done.stdout + done.stderr


def test_the_guard_can_be_turned_off_for_a_deliberate_live_child():
    done = run({'NETWORK_GUARD': 'off'})
    assert 'blocked' not in done.stdout        # no PermissionError: the connect was attempted (OS error or success)


def test_a_private_cluster_environment_carries_the_guard_and_the_news_bundle_path():
    from scripts import rehearse_storage_adapter_postgres as rehearsal
    root = Path('/private/tmp') / 'guard-env-check'
    (root).mkdir(exist_ok=True)
    try:
        env = rehearsal._environment(root) if not (root / 'home').exists() else None
        if env is None:
            import shutil
            shutil.rmtree(root)
            root.mkdir()
            env = rehearsal._environment(root)
        assert 'child_guard' in env.get('PYTHONPATH', '') and env.get('OWNED_NEWS_BUNDLE', '').endswith('tech-news.json')
    finally:
        import shutil
        shutil.rmtree(root, ignore_errors=True)


def test_every_rehearsal_child_builds_its_path_through_the_guard_helper():
    """The 11-18 tech-news bundle was written by a child whose PYTHONPATH the test set itself; no child may set one
    without tests/child_guard first (scripts.rehearse_storage_adapter_postgres.guarded_path)."""
    root = Path(__file__).resolve().parents[1]
    for name in ('tests/test_qa7_native_postgres.py', 'tests/test_feature_native_postgres.py',
                 'scripts/rehearse_worker_binding_postgres.py', 'scripts/rehearse_storage_adapter_postgres.py'):
        text = (root / name).read_text(encoding='utf-8')
        assert 'guarded_path(' in text, name
        assert "env['PYTHONPATH']=str(" not in text and "env['PYTHONPATH'] = os.pathsep.join" not in text, name


def test_a_child_started_with_the_helper_path_cannot_reach_the_outside():
    from scripts.rehearse_storage_adapter_postgres import guarded_path
    env = {'PATH': os.environ.get('PATH', ''), 'PYTHONPATH': guarded_path(Path(__file__).resolve().parents[1])}
    done = subprocess.run([sys.executable, '-c', CODE], env=env, capture_output=True, text=True, timeout=20)
    assert done.returncode == 0 and done.stdout.strip() == 'blocked', done.stdout + done.stderr


def test_the_default_mode_is_report_and_block_is_opt_in():
    """First nights (PM 11-18): the guard only writes the attempts to a log until the affected tests are listed and
    marked; NETWORK_GUARD=block refuses them."""
    import tests.report_redirect as redirect
    source = Path(redirect.__file__).read_text(encoding='utf-8')
    assert "network='block' if environ.get('NETWORK_GUARD') == 'block' else 'report'" in source
