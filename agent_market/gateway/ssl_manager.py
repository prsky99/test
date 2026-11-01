"""OpenSSL certificate lifecycle manager for Port 443 (HTTPS).

Handles:
- Certificate generation and renewal using local OpenSSL (1-year validity: 365 days).
- Certificate status inspection (validity, expiration dates, days remaining).
- Automated yearly renewal scheduling and manual renewal triggers for Admin.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

log = logging.getLogger("agent_market.gateway.ssl_manager")

DEFAULT_SSL_DIR = "deploy/ssl"
DEFAULT_CERT_FILE = "cert.pem"
DEFAULT_KEY_FILE = "key.pem"
DEFAULT_META_FILE = "ssl_meta.json"


def find_openssl_bin() -> str:
    """Find available openssl binary on the system."""
    custom = os.environ.get("OPENSSL_BIN")
    if custom and os.path.exists(custom):
        return custom
    which_bin = shutil.which("openssl")
    if which_bin:
        return which_bin
    for candidate in ("/opt/homebrew/bin/openssl", "/usr/bin/openssl", "/usr/local/bin/openssl"):
        if os.path.exists(candidate):
            return candidate
    return "openssl"


def get_openssl_version() -> str:
    """Retrieve installed OpenSSL version string."""
    try:
        bin_path = find_openssl_bin()
        res = subprocess.run([bin_path, "version"], capture_output=True, text=True, check=True, timeout=30)
        return res.stdout.strip()
    except Exception as exc:
        return f"Unknown ({exc})"


class SSLManager:
    """Manages SSL/TLS certificate renewal and automated yearly scheduling."""

    def __init__(self, ssl_dir: str = DEFAULT_SSL_DIR):
        self.ssl_dir = Path(ssl_dir)
        self.cert_path = self.ssl_dir / DEFAULT_CERT_FILE
        self.key_path = self.ssl_dir / DEFAULT_KEY_FILE
        self.meta_path = self.ssl_dir / DEFAULT_META_FILE
        self._lock = threading.Lock()
        self._scheduler_thread: threading.Thread | None = None
        self._stop_event = threading.Event()

    def renew_certificate(
        self,
        days: int = 365,
        common_name: str = "localhost",
        sans: list[str] | None = None,
    ) -> dict[str, Any]:
        """Generate or renew SSL certificate with 1-year (365 days) validity."""
        if os.environ.get("DEPLOYMENT_MODE") == "production":
            raise ValueError("Production TLS certificates must be provisioned externally")
        if type(days) is not int or not 1 <= days <= 1095:
            raise ValueError("Invalid certificate validity")
        if not isinstance(common_name, str) or not common_name or any(c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789.-" for c in common_name):
            raise ValueError("Invalid certificate common name")
        if sans is not None and (not isinstance(sans, list) or len(sans) > 20 or any(
                not isinstance(s, str) or not s.startswith(("DNS:", "IP:")) or any(c in s for c in "\r\n,/[]") for s in sans)):
            raise ValueError("Invalid certificate SANs")
        with self._lock:
            self.ssl_dir.mkdir(parents=True, exist_ok=True)
            if sans is None:
                sans = ["DNS:localhost", "IP:127.0.0.1", "IP:0.0.0.0"]
            san_str = ",".join(sans)
            bin_path = find_openssl_bin()

            # Execute openssl command
            cmd = [
                bin_path,
                "req",
                "-x509",
                "-nodes",
                "-newkey",
                "rsa:2048",
                "-keyout",
                str(self.key_path),
                "-out",
                str(self.cert_path),
                "-days",
                str(days),
                "-subj",
                f"/C=KR/ST=Seoul/O=A2A Gateway/CN={common_name}",
                "-addext",
                f"subjectAltName={san_str}",
            ]
            try:
                res = subprocess.run(cmd, capture_output=True, text=True, check=True, timeout=30)
                log.info("OpenSSL generated/renewed certificate: %s", res.stderr.strip()[:200])
            except subprocess.CalledProcessError as err:
                # Fallback for OpenSSL versions without -addext support
                log.warning("openssl -addext failed (%s), attempting config file fallback...", err)
                cnf_path = self.ssl_dir / "openssl_temp.cnf"
                cnf_content = f"""[req]
distinguished_name = req_distinguished_name
x509_extensions = v3_req
prompt = no
[req_distinguished_name]
C = KR
ST = Seoul
O = A2A Gateway
CN = {common_name}
[v3_req]
subjectAltName = {san_str}
"""
                cnf_path.write_text(cnf_content, encoding="utf-8")
                fallback_cmd = [
                    bin_path,
                    "req",
                    "-x509",
                    "-nodes",
                    "-newkey",
                    "rsa:2048",
                    "-keyout",
                    str(self.key_path),
                    "-out",
                    str(self.cert_path),
                    "-days",
                    str(days),
                    "-config",
                    str(cnf_path),
                ]
                try:
                    subprocess.run(fallback_cmd, capture_output=True, text=True, check=True, timeout=30)
                finally:
                    if cnf_path.exists():
                        cnf_path.unlink()

            now_ts = time.time()
            expires_ts = now_ts + (days * 86400)
            status_info = self.get_status()

            meta = {
                "common_name": common_name,
                "sans": sans,
                "validity_days": days,
                "renew_interval": "1 year (365 days)",
                "auto_renew": True,
                "renewed_at": now_ts,
                "renewed_at_iso": datetime.now(timezone.utc).isoformat(),
                "expires_at": expires_ts,
                "expires_at_iso": datetime.fromtimestamp(expires_ts, tz=timezone.utc).isoformat(),
                "openssl_version": get_openssl_version(),
                "cert_path": str(self.cert_path),
                "key_path": str(self.key_path),
                "status": status_info,
            }
            self.meta_path.write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
            log.info("SSL certificate renewed successfully. Valid for %d days until %s", days, meta["expires_at_iso"])
            return meta

    def get_status(self) -> dict[str, Any]:
        """Check status of current certificate, expiration dates, and remaining days."""
        exists = self.cert_path.exists() and self.key_path.exists()
        openssl_ver = get_openssl_version()

        if not exists:
            return {
                "exists": False,
                "valid": False,
                "status": "missing",
                "message": "SSL certificate or private key does not exist.",
                "cert_path": str(self.cert_path),
                "key_path": str(self.key_path),
                "openssl_version": openssl_ver,
                "auto_renew_enabled": True,
                "renewal_schedule": "Yearly (every 365 days)",
            }

        bin_path = find_openssl_bin()
        try:
            res = subprocess.run(
                [bin_path, "x509", "-in", str(self.cert_path), "-noout", "-dates", "-subject", "-issuer"],
                capture_output=True,
                text=True,
                check=True,
                timeout=10,
            )
            out = res.stdout.strip()
            lines = dict(item.split("=", 1) for item in out.splitlines() if "=" in item)

            not_before_str = lines.get("notBefore", "")
            not_after_str = lines.get("notAfter", "")

            # Parse openssl date format: 'Oct 14 23:20:07 2026 GMT'
            fmt = "%b %d %H:%M:%S %Y GMT"
            dt_before = datetime.strptime(not_before_str, fmt).replace(tzinfo=timezone.utc) if not_before_str else None
            dt_after = datetime.strptime(not_after_str, fmt).replace(tzinfo=timezone.utc) if not_after_str else None

            now_utc = datetime.now(timezone.utc)
            days_remaining = (dt_after - now_utc).total_seconds() / 86400 if dt_after else 0
            is_valid = (dt_before <= now_utc <= dt_after) if dt_before and dt_after else False

            meta = {}
            if self.meta_path.exists():
                try:
                    meta = json.loads(self.meta_path.read_text(encoding="utf-8"))
                except Exception:
                    pass

            return {
                "exists": True,
                "valid": is_valid,
                "status": "active" if is_valid and days_remaining > 30 else ("expiring_soon" if days_remaining > 0 else "expired"),
                "not_before": dt_before.isoformat() if dt_before else None,
                "not_after": dt_after.isoformat() if dt_after else None,
                "days_remaining": round(days_remaining, 1),
                "subject": lines.get("subject", ""),
                "issuer": lines.get("issuer", ""),
                "cert_path": str(self.cert_path),
                "key_path": str(self.key_path),
                "openssl_version": openssl_ver,
                "auto_renew_enabled": True,
                "renewal_schedule": "Yearly (every 365 days)",
                "last_renewed_at": meta.get("renewed_at_iso"),
            }
        except Exception as exc:
            return {
                "exists": True,
                "valid": False,
                "status": "error",
                "message": f"Error inspecting certificate: {exc}",
                "cert_path": str(self.cert_path),
                "key_path": str(self.key_path),
                "openssl_version": openssl_ver,
                "auto_renew_enabled": True,
                "renewal_schedule": "Yearly (every 365 days)",
            }

    def check_and_auto_renew(
        self,
        threshold_days: int = 30,
        common_name: str = "localhost",
        sans: list[str] | None = None,
    ) -> bool:
        """Check if certificate should be renewed (if missing, expiring within threshold, or domain mismatch)."""
        status = self.get_status()
        domain_mismatch = False
        if status.get("exists") and status.get("valid") and common_name != "localhost":
            meta = {}
            if self.meta_path.exists():
                try:
                    meta = json.loads(self.meta_path.read_text(encoding="utf-8"))
                except Exception:
                    pass
            current_cn = meta.get("common_name")
            current_sans = meta.get("sans", [])
            if current_cn != common_name or (sans and not all(s in current_sans for s in sans)):
                domain_mismatch = True

        if not status.get("exists") or not status.get("valid") or status.get("days_remaining", 0) <= threshold_days or domain_mismatch:
            log.info("SSL certificate requires renewal (status: %s, days remaining: %s, domain mismatch: %s). Renewing...",
                     status.get("status"), status.get("days_remaining"), domain_mismatch)
            self.renew_certificate(common_name=common_name, sans=sans)
            return True
        return False

    def start_scheduler(self, interval_seconds: float = 86400) -> None:
        """Start background daemon thread that checks certificate status every day and auto-renews yearly."""
        if self._scheduler_thread and self._scheduler_thread.is_alive():
            return

        self._stop_event.clear()

        def _worker():
            log.info("SSL yearly auto-renewal scheduler started (check interval: %ds).", interval_seconds)
            # Immediate check upon startup
            try:
                self.check_and_auto_renew()
            except Exception as e:
                log.error("Initial SSL auto-renew check error: %s", e)

            while not self._stop_event.is_set():
                if self._stop_event.wait(interval_seconds):
                    break
                try:
                    self.check_and_auto_renew()
                except Exception as e:
                    log.error("SSL auto-renewal background check failed: %s", e)

        self._scheduler_thread = threading.Thread(target=_worker, daemon=True, name="ssl-auto-renew-scheduler")
        self._scheduler_thread.start()

    def stop_scheduler(self) -> None:
        """Stop background scheduler."""
        self._stop_event.set()


# Default singleton instance
_default_ssl_manager: SSLManager | None = None


def get_ssl_manager(ssl_dir: str = DEFAULT_SSL_DIR) -> SSLManager:
    global _default_ssl_manager
    if _default_ssl_manager is None:
        _default_ssl_manager = SSLManager(ssl_dir=ssl_dir)
    return _default_ssl_manager
