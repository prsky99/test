"""Native CLI profile handling without launching a project server or live Store."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
PROFILE_HELPER = ROOT / 'scripts' / 'agentcon_config.py'
CAPTURED_KEYS = ('HOST', 'AGENT_FRONT_HOST', 'AGENT_FRONT_URL', 'DEPLOYMENT_MODE',
                 'PUBLIC_TLS_TERMINATION', 'FORWARDED_ALLOW_IPS')


@pytest.fixture
def native_cli(tmp_path):
    """Copy only the launcher; its default private profile stays inside tmp_path."""
    project = tmp_path / 'synthetic-project'
    project.mkdir()
    launcher = project / 'agentcon'
    shutil.copyfile(ROOT / 'agentcon', launcher)
    launcher.chmod(0o700)
    (project / 'scripts').mkdir()
    shutil.copyfile(PROFILE_HELPER, project / 'scripts' / 'agentcon_config.py')
    # The Python wrapper delegates parsing to the maintained real helper, and
    # rejects every application-server invocation before importing its module.
    wrapper = tmp_path / 'synthetic-python'
    captured = tmp_path / 'captured-profile.json'
    attempted_launch = tmp_path / 'server-launch-attempted'
    wrapper.write_text(
        '#!' + sys.executable + '\n'
        'import json, os, pathlib, subprocess, sys\n'
        f'helper = {str(PROFILE_HELPER)!r}\n'
        f'capture = pathlib.Path({str(captured)!r})\n'
        f'launch = pathlib.Path({str(attempted_launch)!r})\n'
        f'keys = {CAPTURED_KEYS!r}\n'
        'args = sys.argv[1:]\n'
        'if args and args[0].endswith("agentcon_config.py"):\n'
        '    args = args[1:]\n'
        'if "--export" in args:\n'
        f'    raise SystemExit(subprocess.run([{sys.executable!r}, helper, *args]).returncode)\n'
        'if "--check" in args:\n'
        '    capture.write_text(json.dumps({key: os.environ.get(key) for key in keys}))\n'
        '    if os.environ.get("SYNTHETIC_REAL_CHECK") == "1":\n'
        f'        raise SystemExit(subprocess.run([{sys.executable!r}, helper, *args]).returncode)\n'
        '    raise SystemExit(0)\n'
        'launch.write_text("blocked synthetic server invocation")\n'
        'raise SystemExit(93)\n'
    )
    wrapper.chmod(0o700)
    # Use a small allowlist: no deployment profile, account token, database path
    # or provider credential is inherited from the person running the tests.
    env = {key: os.environ[key] for key in ('PATH', 'HOME', 'TMPDIR', 'LANG', 'LC_ALL')
           if key in os.environ}
    env.update({'PYTHON_BIN': str(wrapper), 'AGENTCON_STRICT_PID': '1',
                'AGENTCON_PID_FILE': str(tmp_path / 'synthetic.pid'),
                'AGENTCON_LOG_FILE': str(tmp_path / 'synthetic.log'),
                'AGENTCON_STOP_TIMEOUT': '1', 'GATEWAY_DB': str(tmp_path / 'must-not-exist.sqlite3'),
                'SCHEDULER': '0', 'COLLECTOR_ENABLED': '0', 'CONCIERGE_LLM': 'off'})

    def invoke(command, **overrides):
        return subprocess.run([str(launcher), command], env={**env, **overrides},
                              capture_output=True, text=True, timeout=15, cwd=tmp_path)

    def profile(text):
        target = project / 'gateway-data' / 'agentcon.env'
        target.parent.mkdir(exist_ok=True)
        target.write_text(text)
        target.chmod(0o600)
        return target

    return {'invoke': invoke, 'profile': profile, 'env': env, 'capture': captured,
            'launch': attempted_launch, 'project': project}


def test_invalid_production_restart_preserves_synthetic_process_and_pid(native_cli):
    cli = native_cli
    profile = cli['profile']('DEPLOYMENT_MODE=production\nPUBLIC_TLS_TERMINATION=proxy\n'
                             'HOST=127.0.0.1\nAGENT_FRONT_HOST=127.0.0.1\n'
                             'FORWARDED_ALLOW_IPS=127.0.0.1,::1\nADMIN_TOKEN=too-short\n')
    # Its command line satisfies the launcher's process-identity test, but this
    # process only sleeps; it imports no project module and binds no port.
    idle = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)',
                             'agent_market.gateway.server'], stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL)
    pid_file = Path(cli['env']['AGENTCON_PID_FILE'])
    pid_file.write_text(str(idle.pid) + '\n')
    before = (pid_file.read_bytes(), pid_file.stat().st_mtime_ns)
    try:
        result = cli['invoke']('restart', AGENTCON_ENV_FILE=str(profile), SYNTHETIC_REAL_CHECK='1')
        assert result.returncode != 0
        assert idle.poll() is None, 'Failed preflight must not terminate the existing process'
        assert (pid_file.read_bytes(), pid_file.stat().st_mtime_ns) == before
        assert not cli['launch'].exists()
        assert not Path(cli['env']['GATEWAY_DB']).exists()
        assert 'Stopping server' not in result.stdout
    finally:
        if idle.poll() is None:
            idle.terminate()
        idle.wait(timeout=5)


def test_malformed_profile_never_executes_command_substitution(native_cli, tmp_path):
    cli = native_cli
    marker = tmp_path / 'shell-substitution-must-not-run'
    profile = cli['profile']('HOST=127.0.0.1\n$(touch ' + str(marker) + ')\n')
    result = cli['invoke']('check', AGENTCON_ENV_FILE=str(profile))
    assert result.returncode != 0
    assert not marker.exists()
    assert not cli['launch'].exists()
    assert not Path(cli['env']['GATEWAY_DB']).exists()


def test_default_private_profile_loads_and_explicit_environment_wins(native_cli):
    cli = native_cli
    cli['profile']('HOST=127.0.0.7\nAGENT_FRONT_HOST=127.0.0.8\n'
                   'DEPLOYMENT_MODE=production\nPUBLIC_TLS_TERMINATION=proxy\n')
    result = cli['invoke']('check', HOST='127.0.0.9')
    assert result.returncode == 0, result.stderr
    captured = json.loads(cli['capture'].read_text())
    assert captured['HOST'] == '127.0.0.9'
    assert captured['AGENT_FRONT_HOST'] == '127.0.0.8'
    assert captured['DEPLOYMENT_MODE'] == 'production'
    assert captured['PUBLIC_TLS_TERMINATION'] == 'proxy'
    assert not cli['launch'].exists()
    assert not Path(cli['env']['GATEWAY_DB']).exists()


def test_explicit_empty_profile_path_disables_default_file(native_cli):
    cli = native_cli
    cli['profile']('HOST=127.0.0.7\nAGENT_FRONT_HOST=127.0.0.8\n'
                   'DEPLOYMENT_MODE=production\nPUBLIC_TLS_TERMINATION=proxy\n')
    result = cli['invoke']('check', AGENTCON_ENV_FILE='')
    assert result.returncode == 0, result.stderr
    captured = json.loads(cli['capture'].read_text())
    assert captured['HOST'] == captured['AGENT_FRONT_HOST'] == '127.0.0.1'
    assert captured['DEPLOYMENT_MODE'] is None
    assert captured['PUBLIC_TLS_TERMINATION'] is None
    assert not cli['launch'].exists()
    assert not Path(cli['env']['GATEWAY_DB']).exists()
