"""
tests/test_server_protocol.py — the wire model and the pairing pieces, offline.
"""
from __future__ import annotations

import io
import sys
import time
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.server import pairing, protocol  # noqa: E402


def test_framing_round_trip_and_limits():
    msg = {"t": "ping", "id": 3, "text": "Achenar ✓"}
    assert protocol.decode(protocol.encode(msg)) == msg
    for bad in (b"not json\n", b"[1,2]\n", b'{"no_type": 1}\n'):
        with pytest.raises(protocol.ProtocolError):
            protocol.decode(bad)
    with pytest.raises(protocol.ProtocolError):
        protocol.decode(b"x" * (protocol.MAX_LINE + 1))


def test_overlay_rows_keep_the_overlay_conventions():
    rows = protocol.rows_from_overlay([("", "Type-10"), ("Heading", ""),
                                       ("Value", "1.2B cr")])
    assert [r["kind"] for r in rows] == ["line", "sub", "kv"]


def test_tracker_sends_only_what_changed():
    t = protocol.ChangeTracker()
    a = protocol.panel("a", "A", "g", [protocol._row("x", "1")])
    b = protocol.panel("b", "B", "g", [protocol._row("y", "2")])
    first = t.update({"cmdr": "X"}, [a, b])
    assert {p["id"] for p in first["upsert"]} == {"a", "b"} and "header" in first
    assert t.update({"cmdr": "X"}, [a, b]) is None
    a2 = protocol.panel("a", "A", "g", [protocol._row("x", "9")])
    msg = t.update({"cmdr": "X"}, [a2])
    assert [p["id"] for p in msg["upsert"]] == ["a"]
    assert msg["remove"] == ["b"]
    assert "header" not in msg
    assert msg["seq"] == first["seq"] + 1
    snap = t.snapshot()
    assert snap["seq"] == msg["seq"] and [p["id"] for p in snap["panels"]] == ["a"]


def test_code_normalisation_forgives_misreads():
    assert pairing.normalise_code("abcde-fgh0l") == "ABCDEFGH01"
    assert pairing.normalise_code("O0IL-") == "0011"


def test_ticket_expires(tmp_path):
    code, _ = pairing.issue_ticket(tmp_path, ttl_s=-1)
    assert pairing.check_ticket(tmp_path, code) == (False, "expired")
    assert not (tmp_path / pairing.TICKET_FILE).exists()


def test_a_new_ticket_replaces_the_old(tmp_path):
    old, _ = pairing.issue_ticket(tmp_path)
    new, _ = pairing.issue_ticket(tmp_path)
    assert pairing.check_ticket(tmp_path, old)[1] == "wrong-code"
    assert pairing.check_ticket(tmp_path, new) == (True, "")


def test_unpair_needs_an_unambiguous_id(tmp_path):
    reg = pairing.DeviceRegistry(tmp_path)
    reg.add("AAAA1111", "Y2VydA==", "one")
    reg.add("AAAA2222", "Y2VydA==", "two")
    assert reg.remove("AAAA") is None
    assert reg.remove("AAAA2")["name"] == "two"
    time.sleep(0.01)
    assert [d["name"] for d in pairing.DeviceRegistry(tmp_path).all()] == ["one"]


def test_ipv6_hosts_are_bracketed():
    assert pairing.host_port("2001:db8::5", 28510) == "[2001:db8::5]:28510"
    assert pairing.host_port("me.duckdns.org", 28510) == "me.duckdns.org:28510"


def test_pair_command_link_carries_everything(tmp_path):
    pytest.importorskip("cryptography")
    from core.server import cli
    out = io.StringIO()
    cfg = {"Port": 28510, "BindAddress": "192.168.1.20",
           "ExternalHost": "cmdr.duckdns.org"}
    assert cli.pair(tmp_path, cfg, "EDLD test", interactive=False, out=out) == 0
    link = [l.split()[-1] for l in out.getvalue().splitlines()
            if l.strip().startswith("Link:")][0]
    q = parse_qs(urlparse(link).query)
    assert q["v"] == ["1"] and q["n"] == ["EDLD test"]
    assert q["h"] == ["192.168.1.20:28510", "cmdr.duckdns.org:28510"]
    assert len(q["fp"][0]) == 43
    # The code in the link is the one the ticket accepts.
    assert pairing.check_ticket(tmp_path, q["c"][0]) == (True, "")
    # And the QR image that carried it is gone with the ticket.
    assert not (tmp_path / pairing.QR_IMAGE).exists()


def test_pair_command_keeps_an_explicit_external_port(tmp_path):
    pytest.importorskip("cryptography")
    from core.server import cli
    out = io.StringIO()
    cli.pair(tmp_path, {"Port": 28510, "BindAddress": "10.0.0.2",
                        "ExternalHost": "cmdr.duckdns.org:443"},
             "x", interactive=False, out=out)
    addresses = next(line for line in out.getvalue().splitlines()
                     if line.strip().startswith("Addresses:"))
    assert addresses.split(":", 1)[1].split(",")[-1].strip() == "cmdr.duckdns.org:443"


# ── Themes ────────────────────────────────────────────────────────────────────

def test_wire_theme_carries_every_palette_colour():
    from core.palette import WIRE_KEYS, wire_theme
    t = wire_theme("default-green")
    assert t["id"] == "default-green" and t["name"] == "EDLD Default Green"
    assert set(t["colors"]) == set(WIRE_KEYS.values())
    assert t["colors"]["accent"] == "#00aa44"


def test_unknown_theme_falls_back_to_default():
    from core.palette import wire_theme
    assert wire_theme("gtk4-leftover")["id"] == "default"
    assert wire_theme("")["id"] == "default"


def test_custom_theme_arrives_as_its_colours(tmp_path, monkeypatch):
    import core.palette as P
    (tmp_path / "themes" / "custom").mkdir(parents=True)
    (tmp_path / "themes" / "custom" / "mine.css").write_text(
        ":root { --accent: #123456; --bg-deep: #000000; }")
    monkeypatch.setattr(P, "_repo_root", lambda: tmp_path)
    t = P.wire_theme("custom/mine")
    assert t["id"] == "custom/mine" and t["name"] == "Custom: mine"
    assert t["colors"]["accent"] == "#123456" and t["colors"]["bg"] == "#000000"


def test_the_header_follows_the_theme_setting():
    from types import SimpleNamespace
    core = SimpleNamespace(state=None, _plugins={},
                           cfg=SimpleNamespace(ui_cfg={"Theme": "default-blue"}))
    b = protocol.SnapshotBuilder(core)
    b.game_running = lambda: True
    assert b.header()["theme"]["id"] == "default-blue"
    core.cfg.ui_cfg["Theme"] = "elite-orange"
    assert b.header()["theme"]["colors"]["accent"] == "#ff7100"


def test_theme_exporter_covers_every_built_in():
    import subprocess
    from core.palette import THEME_CHOICES
    out = subprocess.run([sys.executable, str(ROOT / "scripts" / "export_edam_themes.py")],
                         capture_output=True, text=True, check=True).stdout
    for _name, tid in THEME_CHOICES:
        assert f'EdldPalette("{tid}",' in out
    assert "Color(0xFFE07B20)" in out           # default accent, as ARGB
    assert out.count("EdldPalette(") == len(THEME_CHOICES)
