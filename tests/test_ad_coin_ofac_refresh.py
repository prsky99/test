import os

from agent_market.ad_coin.v2.paid_bookings import Sanctions
from scripts import ad_coin_ofac_refresh as refresh


def _csv(count, label="ETH"):
    rows = []
    for i in range(count):
        rows.append('%d,"PERSON %d","individual","CYBER2","","","","","","","","Digital Currency Address - %s 0x%040X; alt."'
                    % (i, i, label, i + 1))
    return "\n".join(rows)


def test_extracts_every_evm_label_lowercased_and_unique():
    text = _csv(3) + "\n" + _csv(2, "USDC") + "\nDigital Currency Address - XBT 1BoatSLRHtKNngkdXEeobR76b53LETtpyT"
    assert refresh.extract(text) == ["0x%040x" % (i + 1) for i in range(3)]


def test_writes_file_that_sanctions_screen_reads(tmp_path):
    out = tmp_path / "ofac" / "eth_addresses.txt"
    report = refresh.refresh(out, fetch=lambda: _csv(60))
    assert report["ok"] and report["written"] and report["addresses"] == 60
    assert oct(os.stat(out).st_mode & 0o777) == "0o644"
    screen = Sanctions(str(out))
    assert screen.screen("0x%040X" % 5) == "match"
    assert screen.screen("0x" + "ab" * 20) == "clear"


def test_keeps_old_file_when_new_list_is_too_small_or_shrinks(tmp_path):
    out = tmp_path / "eth_addresses.txt"
    refresh.refresh(out, fetch=lambda: _csv(100))
    before = out.read_text()
    small = refresh.refresh(out, fetch=lambda: _csv(10))
    assert not small["ok"] and small["problem"].startswith("too_few") and out.read_text() == before
    shrunk = refresh.refresh(out, fetch=lambda: _csv(70))
    assert not shrunk["ok"] and shrunk["problem"] == "dropped:100->70" and out.read_text() == before


def test_check_mode_does_not_write(tmp_path):
    out = tmp_path / "eth_addresses.txt"
    report = refresh.refresh(out, fetch=lambda: _csv(60), check=True)
    assert report["ok"] and not report["written"] and not out.exists()


def test_download_failure_exits_one(monkeypatch, capsys):
    def boom(*a, **k):
        raise OSError("offline")
    monkeypatch.setattr(refresh, "download", boom)
    assert refresh.main(["--check"]) == 1
    assert '"download:OSError"' in capsys.readouterr().out
