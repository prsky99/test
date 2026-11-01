import os
import socket
import subprocess
import time
from pathlib import Path
import urllib.error
import urllib.request


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _wait_for_http(port: int, path: str) -> None:
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        try:
            with opener.open(f"http://127.0.0.1:{port}{path}", timeout=0.5) as response:
                if response.status == 200:
                    return
        except (OSError, urllib.error.URLError):
            pass
        time.sleep(0.1)
    raise AssertionError("The isolated server did not become ready")


def _isolated_project(repo_root: Path, tmp_path: Path) -> Path:
    """A throwaway project root for agentcon.

    agentcon derives PROJECT_DIR from its own location. On a host whose real project
    has a managed gateway-data/services/state.json, start/stop/restart are dispatched to
    the real launchd services regardless of AGENTCON_PID_FILE; running the repository
    copy once stopped the operating frontend/admin/proxy (2026-10-26). The copy here has
    no gateway-data, so only the legacy, PID-file-scoped path can run.
    """
    project = tmp_path / "project"
    project.mkdir()
    for name in ("agent_market", "scripts", ".venv"):
        (project / name).symlink_to(repo_root / name, target_is_directory=True)
    binary = project / "agentcon"
    binary.write_bytes((repo_root / "agentcon").read_bytes())
    binary.chmod(0o755)
    assert not (project / "gateway-data").exists()
    return binary


def test_agentcon_start_status_restart_stop(tmp_path: Path):
    repo_root = Path(__file__).resolve().parent.parent
    assert os.access(repo_root / "agentcon", os.X_OK)
    agentcon_bin = _isolated_project(repo_root, tmp_path)

    admin_port = _free_port()
    front_port = _free_port()
    while front_port == admin_port:
        front_port = _free_port()

    pid_file = tmp_path / "test_agentcon.pid"
    log_file = tmp_path / "test_agentcon.log"
    db_file = tmp_path / "test_collector.sqlite3"

    env = {key: os.environ[key] for key in ("PATH", "HOME", "TMPDIR", "LANG", "LC_ALL")
           if key in os.environ}
    env.update(
        {
            "PORT": str(admin_port),
            "AGENT_FRONT_PORT": str(front_port),
            "AGENT_FRONT_HOST": "127.0.0.1",
            "AGENT_FRONT": "1",
            "AGENT_FRONT_URL": "https://agentconcierge.biz",
            "GATEWAY_DB": str(db_file),
            "AGENTCON_PID_FILE": str(pid_file),
            "AGENTCON_LOG_FILE": str(log_file),
            "AGENTCON_STRICT_PID": "1",
            "AGENTCON_STOP_TIMEOUT": "10",
            "AGENTCON_ENV_FILE": "",
            "DEPLOYMENT_MODE": "production",
            "PUBLIC_TLS_TERMINATION": "proxy",
            "ADMIN_TOKEN": "synthetic-cli-token-" + "a" * 48,
            "ADMIN_BOOTSTRAP_PASSWORD": "synthetic-cli-bootstrap-password",
            "HOST": "127.0.0.1",
            "FORWARDED_ALLOW_IPS": "127.0.0.1,::1",
            "SSL_ENABLED": "0",
            "ALLOW_PRIVATE_AGENT_URLS": "0",
            "SCHEDULER": "0",
            "CONCIERGE_LLM": "off",
            "AGENT_DISCOVERY": "0",
            "USAGE_TRIALS": "0",
            "REDIS_HOST": "127.0.0.1",
            "REDIS_PORT": str(_free_port()),
            "LOG_DIR": str(tmp_path / "logs"),
            "LOG_ARCHIVE_DIR": str(tmp_path / "archives"),
        }
    )

    try:
        # 1. Initial status should be STOPPED
        res = subprocess.run([str(agentcon_bin), "status"], env=env, capture_output=True, text=True)
        assert res.returncode == 1
        assert "STOPPED" in res.stdout

        # 2. Start server in background
        res_start = subprocess.run([str(agentcon_bin), "start"], env=env, capture_output=True, text=True, timeout=20)
        assert res_start.returncode == 0, f"stdout={res_start.stdout}\nstderr={res_start.stderr}"
        assert "Server started in background" in res_start.stdout
        assert pid_file.exists()
        first_pid = int(pid_file.read_text().strip())
        assert first_pid > 0
        _wait_for_http(admin_port, "/health")
        _wait_for_http(front_port, "/robots.txt")

        # 3. Status should be RUNNING with first_pid
        res_status = subprocess.run([str(agentcon_bin), "status"], env=env, capture_output=True, text=True)
        assert res_status.returncode == 0
        assert "RUNNING" in res_status.stdout
        assert str(first_pid) in res_status.stdout

        # 4. Restart server and verify new PID
        res_restart = subprocess.run([str(agentcon_bin), "restart"], env=env, capture_output=True, text=True, timeout=25)
        assert res_restart.returncode == 0, f"stdout={res_restart.stdout}\nstderr={res_restart.stderr}"
        assert "Stopping server" in res_restart.stdout
        assert "Server started in background" in res_restart.stdout
        second_pid = int(pid_file.read_text().strip())
        assert second_pid > 0
        assert second_pid != first_pid
        _wait_for_http(admin_port, "/health")
        _wait_for_http(front_port, "/robots.txt")

        # 5. Stop server and verify STOPPED
        res_stop = subprocess.run([str(agentcon_bin), "stop"], env=env, capture_output=True, text=True, timeout=20)
        assert res_stop.returncode == 0
        assert "Server stopped" in res_stop.stdout
        assert not pid_file.exists()

        res_final = subprocess.run([str(agentcon_bin), "status"], env=env, capture_output=True, text=True)
        assert res_final.returncode == 1
        assert "STOPPED" in res_final.stdout
    finally:
        subprocess.run([str(agentcon_bin), "stop"], env=env, capture_output=True, text=True)
