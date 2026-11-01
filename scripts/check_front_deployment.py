"""Read-only TLS/header inspection of the public frontend; never prints credentials."""

import argparse
import json
import ssl
from urllib.parse import urlsplit

import httpx


def inspect_origin(url):
    parsed = urlsplit(url)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username is not None or parsed.query:
        raise ValueError("An HTTPS URL without credentials or query parameters is required")
    result = {"origin": f"https://{parsed.netloc}", "tls_verified": False}
    try:
        with httpx.Client(verify=True, trust_env=False, follow_redirects=False, timeout=10.0) as client:
            with client.stream("GET", url, headers={"accept": "text/html"}) as response:
                result["tls_verified"] = True
                stream = response.extensions.get("network_stream")
                ssl_object = stream.get_extra_info("ssl_object") if stream else None
                if ssl_object:
                    cert = ssl_object.getpeercert()
                    result.update({"tls_version": ssl_object.version(), "certificate_not_after": cert.get("notAfter"),
                        "certificate_expiry_epoch": ssl.cert_time_to_seconds(cert["notAfter"]) if cert.get("notAfter") else None})
                result["status_code"] = response.status_code
                csp = response.headers.get("content-security-policy", "")
                directives = {part.strip().split(" ", 1)[0]: part.strip() for part in csp.split(";") if part.strip()}
                scripts = directives.get("script-src", directives.get("default-src", ""))
                result.update({"csp_present": bool(csp), "scripts_allow_unsafe_inline": "'unsafe-inline'" in scripts,
                    "scripts_allow_eval": "'unsafe-eval'" in scripts,
                    "inline_handlers_blocked": directives.get("script-src-attr") == "script-src-attr 'none'",
                    "script_nonce_present": "'nonce-" in scripts,
                    "hsts_present": bool(response.headers.get("strict-transport-security")),
                    "nosniff": response.headers.get("x-content-type-options") == "nosniff",
                    "frame_embedding_blocked": response.headers.get("x-frame-options", "").upper() == "DENY"})
                # No response body or cookies are stored in the report.
    except httpx.HTTPError as exc:
        result["error_type"] = type(exc).__name__
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="https://agentconcierge.biz/")
    args = parser.parse_args()
    print(json.dumps(inspect_origin(args.url), indent=2))


if __name__ == "__main__":
    main()
