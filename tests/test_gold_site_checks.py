"""Answer sets and grading for the tls-certificate and site-reachability gates (agent team 11-17)."""
import datetime as dt

import pytest

from agent_market.fallback_agents.gold_check import SLUG, applies, judge
from scripts import gold_site_checks as G


def der(org="Example CA Org", cn="Example CA", days=90):
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID
    key = ec.generate_private_key(ec.SECP256R1())
    attrs = ([x509.NameAttribute(NameOID.ORGANIZATION_NAME, org)] if org else []) + [x509.NameAttribute(NameOID.COMMON_NAME, cn)]
    name = x509.Name(attrs)
    start = dt.datetime(2026, 11, 1, tzinfo=dt.timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
            .serial_number(1).not_valid_before(start).not_valid_after(start + dt.timedelta(days=days))
            .sign(key, hashes.SHA256()))
    return cert.public_bytes(serialization.Encoding.DER)


def test_cert_facts_reads_issuer_org_then_common_name():
    assert G.cert_facts(der(), None) == {"valid": True, "issuer": "Example CA Org", "not_after": "2027-01-30"}
    assert G.cert_facts(der(org=None), None)["issuer"] == "Example CA"
    assert G.cert_facts(None, "certificate has expired") == {"valid": False, "reason": "certificate has expired"}


def test_private_addresses_are_never_read():
    fake = lambda host, port, proto=0: [(2, 1, 6, "", ("10.0.0.5", 443))]
    with pytest.raises(ValueError):
        G.public_addresses("intranet.example", fake)
    assert G.read_tls("intranet.example", cafile="x", resolve=fake,
                      connect=lambda *a: pytest.fail("connected")) is None


def test_reach_follows_redirects_one_hop_at_a_time():
    answers = {"https://a.example/": (301, "/home"), "https://a.example/home": (200, None)}
    truth = G.read_reach("a.example", answers.get, lambda url: True)
    assert truth == {"reachable": True, "status_class": "2xx", "https": True, "redirects": 1,
                     "final_url": "https://a.example/home"}
    down = G.read_reach("b.example", lambda url: None, lambda url: True)
    assert down["reachable"] is False and down["status_class"] is None
    plain = G.read_reach("c.example", {"https://c.example/": (302, "http://c.example/")}.get, lambda url: True)
    assert plain["https"] is False and plain["status_class"] == "3xx" and plain["reachable"] is False
    walled = G.read_reach("d.example", {"https://d.example/": (403, None)}.get, lambda url: True)
    assert walled == {"reachable": False, "status_class": "4xx", "https": True, "redirects": 0,
                      "final_url": "https://d.example/"}
    private = G.read_reach("e.example", {"https://e.example/": (302, "https://10.0.0.1/")}.get,
                           lambda url: "10.0.0.1" not in url)
    assert private["reachable"] is False and private["note"] == "redirect to a non-public address"


def test_build_takes_spares_in_order_and_stops_at_keep():
    read = {"a.example": None, "b.example": {"valid": True}, "c.example": {"valid": False}, "d.example": {"valid": True}}
    cases = G.build(list(read), read.get, keep=2)
    assert [c["case_id"] for c in cases] == ["site:b.example", "site:c.example"]
    assert cases[0]["input"] == {"domain": "b.example"} and cases[0]["truth"]["domain"] == "b.example"


def test_tls_judge():
    case = {"input": {"domain": "x.example"}, "truth": {"domain": "x.example", "valid": True, "issuer": "Let's Encrypt",
                                                         "not_after": "2027-01-30"}}
    assert SLUG["tls-certificate"] == "website-trust-brief" and applies("tls-certificate", case)
    good = {"valid": True, "issuer": "Let's  Encrypt", "not_after": "2027-01-31"}
    assert judge("tls-certificate", case, good)["pass"] is True
    assert judge("tls-certificate", case, {**good, "not_after": "2027-02-02"})["pass"] is False
    assert judge("tls-certificate", case, {**good, "issuer": "DigiCert Inc"})["pass"] is False
    assert judge("tls-certificate", case, {"valid": False})["pass"] is False
    bad = {"input": case["input"], "truth": {"domain": "x.example", "valid": False, "reason": "expired"}}
    assert judge("tls-certificate", bad, {"valid": False, "answer": "does not validate"})["pass"] is True
    assert not applies("tls-certificate", {"input": case["input"], "truth": {"domain": "x.example"}})


def test_reach_judge():
    case = {"input": {"domain": "x.example"}, "truth": {"domain": "x.example", "reachable": True, "status_class": "2xx",
                                                         "https": True, "redirects": 1}}
    assert SLUG["site-reachability"] == "website-trust-brief" and applies("site-reachability", case)
    assert judge("site-reachability", case, {"reachable": True, "status": 204, "https": True, "redirects": 2})["pass"]
    assert not judge("site-reachability", case, {"reachable": False, "status": 503, "https": True})["pass"]
    down = {"input": case["input"], "truth": {"domain": "x.example", "reachable": False, "status_class": None, "https": True}}
    assert judge("site-reachability", down, {"reachable": False, "https": True, "answer": "unreachable"})["pass"]
    assert not judge("site-reachability", down, {"reachable": False, "status": 403, "https": True})["pass"]
    assert judge("site-reachability", case, None)["pass"] is False
