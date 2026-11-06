"""
tests/test_server_firewall.py — telling the commander their firewall is in the way.

A phone that cannot reach EDLD because this computer drops new incoming
connections produces nothing on EDLD's side at all: the connection never
arrives.  The first real pairing attempt failed exactly this way, on Arch's
stock nftables ruleset, which accepts ssh and drops everything else.
"""
from __future__ import annotations

import io
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.server import firewall  # noqa: E402

#: Arch Linux's /etc/nftables.conf as the nftables package installs it.
ARCH_DEFAULT = """\
#!/usr/bin/nft -f
# vim:set ts=2 sw=2 et:

# IPv4/IPv6 Simple & Safe firewall ruleset.
# More examples in /usr/share/nftables/ and /usr/share/doc/nftables/examples/.

destroy table inet filter
table inet filter {
  chain input {
    type filter hook input priority filter
    policy drop

    ct state invalid drop comment "early drop of invalid connections"
    ct state {established, related} accept comment "allow tracked connections"
    iifname lo accept comment "allow from loopback"
    ip protocol icmp accept comment "allow icmp"
    meta l4proto ipv6-icmp accept comment "allow icmp v6"
    tcp dport ssh accept comment "allow sshd"
    pkttype host limit rate 5/second counter reject with icmpx type admin-prohibited
    counter
  }
  chain forward {
    type filter hook forward priority filter
    policy drop
  }
}
"""


def test_arch_default_nftables_is_reported(tmp_path):
    conf = tmp_path / "nftables.conf"
    conf.write_text(ARCH_DEFAULT)
    lines = firewall.advice(28510, nft_conf=conf, active=["nftables"])
    assert lines and "drop incoming connections" in lines[0]
    assert any("nft insert rule inet filter input tcp dport 28510 accept" in l
               for l in lines)


def test_nftables_that_opens_the_port_is_left_alone(tmp_path):
    conf = tmp_path / "nftables.conf"
    conf.write_text(ARCH_DEFAULT.replace(
        'tcp dport ssh accept comment "allow sshd"',
        'tcp dport ssh accept comment "allow sshd"\n    tcp dport 28510 accept'))
    assert firewall.advice(28510, nft_conf=conf, active=["nftables"]) == []


def test_a_different_port_number_is_not_mistaken_for_this_one(tmp_path):
    conf = tmp_path / "nftables.conf"
    conf.write_text(ARCH_DEFAULT.replace("ssh", "128510"))
    assert firewall.advice(28510, nft_conf=conf, active=["nftables"])


def test_unreadable_rules_still_say_something(tmp_path):
    lines = firewall.advice(28510, nft_conf=tmp_path / "missing.conf",
                            active=["nftables"])
    assert lines and "could not be read" in lines[0]


@pytest.mark.parametrize("fw, needle", [
    ("ufw", "sudo ufw allow 28510/tcp"),
    ("firewalld", "--add-port=28510/tcp"),
])
def test_other_firewalls_get_their_own_command(tmp_path, fw, needle):
    lines = firewall.advice(28510, nft_conf=tmp_path / "x", active=[fw])
    assert any(needle in l for l in lines)


def test_no_firewall_no_advice(tmp_path):
    assert firewall.advice(28510, nft_conf=tmp_path / "x", active=[]) == []


def test_not_linux_is_silent(monkeypatch):
    monkeypatch.setattr(firewall.sys, "platform", "win32")
    assert firewall.active_firewalls() == []


def test_pair_command_prints_the_advice(tmp_path, monkeypatch):
    pytest.importorskip("cryptography")
    from core.server import cli
    monkeypatch.setattr(firewall, "active_firewalls", lambda: ["ufw"])
    out = io.StringIO()
    cli.pair(tmp_path, {"Port": 28510, "BindAddress": "192.168.1.20"}, "x",
             interactive=False, out=out)
    assert "firewall may stop devices" in out.getvalue()
    assert "sudo ufw allow 28510/tcp" in out.getvalue()


def test_loopback_detection_covers_mapped_addresses():
    from core.server.service import _is_loopback
    assert _is_loopback("127.0.0.1") and _is_loopback("::1")
    assert _is_loopback("::ffff:127.0.0.1")
    assert not _is_loopback("192.168.1.42")
    assert not _is_loopback("::ffff:192.168.1.42")


# ── ufw, and when to raise it ─────────────────────────────────────────────────
#
# ufw keeps its rules root-readable only.  An active ufw whose rules cannot be
# read used to raise the same alert at every start, long after the port had
# been opened — which is exactly what happened on the first machine to pair.

UFW_ALLOWED = """\
### tuple ### allow tcp 22 0.0.0.0/0 any 0.0.0.0/0 in
-A ufw-user-input -p tcp --dport 22 -j ACCEPT
### tuple ### allow tcp 28510 0.0.0.0/0 any 0.0.0.0/0 in
-A ufw-user-input -p tcp --dport 28510 -j ACCEPT
"""


def _ufw(tmp_path, text):
    f = tmp_path / "user.rules"
    if text is not None:
        f.write_text(text)
    return (f,)


def test_ufw_that_allows_the_port_says_nothing(tmp_path):
    lines, certain = firewall.check(28510, nft_conf=tmp_path / "x", active=["ufw"],
                                    ufw_rules=_ufw(tmp_path, UFW_ALLOWED))
    assert lines == [] and certain is False


def test_ufw_that_does_not_allow_it_is_certain(tmp_path):
    rules = _ufw(tmp_path, UFW_ALLOWED.replace("28510", "28511"))
    lines, certain = firewall.check(28510, nft_conf=tmp_path / "x", active=["ufw"],
                                    ufw_rules=rules)
    assert certain is True and "does not allow port 28510" in lines[0]


def test_unreadable_ufw_is_advice_not_a_warning(tmp_path):
    lines, certain = firewall.check(28510, nft_conf=tmp_path / "x", active=["ufw"],
                                    ufw_rules=_ufw(tmp_path, None))
    assert certain is False
    assert any("sudo ufw allow 28510/tcp" in l for l in lines)


def test_unreadable_nftables_does_not_claim_a_block(tmp_path):
    lines, certain = firewall.check(28510, nft_conf=tmp_path / "missing",
                                    active=["nftables"])
    assert certain is False
    assert "cannot reach" not in lines[0] and "If devices cannot connect" in lines[0]


def test_only_a_certain_block_raises_an_alert(tmp_path, monkeypatch):
    from core.server import service
    from types import SimpleNamespace
    core = SimpleNamespace(state=None, _plugins={})
    for certain, expect_alert in ((False, False), (True, True)):
        monkeypatch.setattr(firewall, "check",
                            lambda port, c=certain: (["ufw is active."], c))
        alerts: list[str] = []
        srv = service.ServerService(core, directory=tmp_path / f"s{certain}",
                                    settings={"Port": 0, "BindAddress": "127.0.0.1"},
                                    name="t", alert=alerts.append)
        srv.start()
        try:
            assert bool(alerts) is expect_alert
            assert srv.firewall_advice == ["ufw is active."]
        finally:
            srv.stop()
