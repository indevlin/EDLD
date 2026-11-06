"""
core/server/firewall.py — is a firewall on this computer likely to block devices?

The usual reason a phone on the same network cannot pair is not the network
but this computer's own firewall, which lets connections out and drops new
ones coming in.  That is invisible from EDLD's side — a dropped connection
never arrives, so there is nothing to log — and invisible from the phone's,
which only sees a timeout.  So EDLD looks for an active firewall and says what
it found, with the command that opens the port, rather than leave the
commander to work out why a code that looked fine never pairs.

Only what an ordinary user can see is checked: whether the service is active,
and the rules file where it is readable.  Nothing is changed.  Linux only;
Windows asks about the firewall itself the first time EDLD listens, and its
side of this lives in docs/SERVER.md.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
from pathlib import Path

NFTABLES_CONF = Path("/etc/nftables.conf")
IPTABLES_RULES = Path("/etc/iptables/iptables.rules")
UFW_RULES = (Path("/etc/ufw/user.rules"), Path("/etc/ufw/user6.rules"))

_SERVICES = ("nftables", "ufw", "firewalld", "iptables")


def _active(service: str) -> bool:
    try:
        r = subprocess.run(["systemctl", "is-active", "--quiet", service],
                           timeout=3, capture_output=True)
        return r.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def active_firewalls() -> list[str]:
    """Firewall services running on this machine, by systemd unit name."""
    if not sys.platform.startswith("linux") or not shutil.which("systemctl"):
        return []
    return [s for s in _SERVICES if _active(s)]


def _mentions_port(text: str, port: int) -> bool:
    return re.search(rf"(?<!\d){port}(?!\d)", text) is not None


def _nftables_verdict(port: int, conf: Path = NFTABLES_CONF) -> str | None:
    """'blocks', 'allows', or None when the rules cannot be read."""
    try:
        text = conf.read_text(encoding="utf-8")
    except OSError:
        return None
    if _mentions_port(text, port):
        return "allows"
    if re.search(r"hook\s+input[^}]*policy\s+drop", text, re.S) or "policy drop" in text:
        return "blocks"
    return "allows"


def _ufw_verdict(port: int, files=UFW_RULES) -> str | None:
    """'allows', 'blocks', or None when ufw's rules cannot be read.

    ufw keeps them root-readable only, so from an ordinary account this is
    usually None — which is why an active ufw is a note, not a warning.
    """
    texts = []
    for f in files:
        try:
            texts.append(Path(f).read_text(encoding="utf-8"))
        except OSError:
            continue
    if not texts:
        return None
    rule = re.compile(rf"--dport\s+{port}(?!\d)[^\n]*-j\s+ACCEPT")
    return "allows" if any(rule.search(t) for t in texts) else "blocks"


def check(port: int, nft_conf: Path = NFTABLES_CONF,
          active: list[str] | None = None, ufw_rules=UFW_RULES) -> tuple[list[str], bool]:
    """What to tell the commander, and whether the port is *known* to be blocked.

    The second value is what decides whether EDLD raises it in the Alerts pane
    at every start.  A firewall whose rules cannot be read — ufw from an
    ordinary account, nftables with its rules file locked down — gets its
    advice shown where someone setting up pairing will look, but not pushed at
    every launch, since EDLD cannot tell whether it was already followed.
    """
    return _advice(port, nft_conf, active, ufw_rules)


def advice(port: int, nft_conf: Path = NFTABLES_CONF,
           active: list[str] | None = None, ufw_rules=UFW_RULES) -> list[str]:
    """Lines to show the commander, or [] when nothing looks in the way."""
    return _advice(port, nft_conf, active, ufw_rules)[0]


def _advice(port, nft_conf, active, ufw_rules) -> tuple[list[str], bool]:
    found = active_firewalls() if active is None else active
    out: list[str] = []
    certain = False
    for fw in found:
        if fw == "nftables":
            verdict = _nftables_verdict(port, nft_conf)
            if verdict == "allows":
                continue
            certain = certain or verdict == "blocks"
            lead = ("nftables is active and its rules drop incoming connections "
                    f"without mentioning port {port}"
                    if verdict == "blocks" else
                    f"nftables is active; its rules ({nft_conf}) could not be read "
                    f"to check port {port}")
            out += [
                f"{lead}, so devices on your network cannot reach EDLD."
                if verdict == "blocks" else f"{lead}. If devices cannot connect:",
                f"  Now:       sudo nft insert rule inet filter input tcp dport {port} accept",
                f"  Permanent: add  tcp dport {port} accept  to the input chain in "
                f"{nft_conf}, beside the ssh line, then  sudo systemctl restart nftables",
            ]
        elif fw == "ufw":
            verdict = _ufw_verdict(port, ufw_rules)
            if verdict == "allows":
                continue
            certain = certain or verdict == "blocks"
            lead = (f"ufw is active and does not allow port {port}:"
                    if verdict == "blocks" else
                    f"ufw is active. If you have not already allowed port {port}:")
            out += [lead, f"  sudo ufw allow {port}/tcp"]
        elif fw == "firewalld":
            out += [f"firewalld is active. If you have not already opened port {port}:",
                    f"  sudo firewall-cmd --permanent --add-port={port}/tcp "
                    f"&& sudo firewall-cmd --reload"]
        elif fw == "iptables":
            try:
                if _mentions_port(IPTABLES_RULES.read_text(encoding="utf-8"), port):
                    continue
            except OSError:
                pass
            out += [f"iptables is active. If it does not already allow port {port}:",
                    f"  sudo iptables -I INPUT -p tcp --dport {port} -j ACCEPT",
                    f"  sudo ip6tables -I INPUT -p tcp --dport {port} -j ACCEPT"]
    return out, certain
