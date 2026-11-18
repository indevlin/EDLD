"""scripts/discord_release.py: section extraction and Discord limits."""
from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("discord_release", ROOT / "scripts" / "discord_release.py")
dr = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(dr)

LOG = """# X CHANGELOG

---

## Unreleased

### Fixed: not yet

---

## Released in 20261118

### Added: a thing

First line of a
wrapped paragraph.

- a list item

---

## Released in 20261117

### Fixed: older
"""


def test_section_stops_at_next_release_and_drops_rule():
    text = dr.section(LOG, "20261118")
    assert text.startswith("### Added: a thing") and "older" not in text
    assert not text.endswith("---")


def test_missing_section_is_empty():
    assert dr.section(LOG, "20990101") == ""


def test_paragraphs_unwrapped_and_headings_bold():
    out = dr.to_discord(dr.section(LOG, "20261118"))
    assert "**Added: a thing**" in out
    assert "First line of a wrapped paragraph." in out
    assert "\n- a list item" in out


def test_long_section_falls_back_to_headings_within_limit():
    long = "\n\n".join(f"### Fixed: item {i}\n\n" + "word " * 400 for i in range(300))
    data = dr.payload("EDLD", "1", long, "https://example.invalid/r", "Notes")
    desc = data["embeds"][0]["description"]
    assert len(desc) <= 4096
    assert desc.startswith("• Fixed: item 0") and "more" in desc
    assert desc.endswith("[Notes](https://example.invalid/r)")


def test_no_mentions_and_title(tmp_path):
    data = dr.payload("EDAM", "20261116", "### Added: x", "https://p.invalid", "Get it")
    assert data["allowed_mentions"] == {"parse": []}
    assert data["embeds"][0]["title"] == "EDAM 20261116"


def test_every_shipped_release_fits():
    log = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    import re
    versions = re.findall(r"^## Released in (\S+)\s*$", log, re.M)
    assert versions
    for version in versions:
        text = dr.section(log, version)
        if text:
            desc = dr.payload("EDLD", version, text, "https://x.invalid", "Notes")["embeds"][0]["description"]
            assert len(desc) <= 4096


def test_unset_webhook_posts_nothing(monkeypatch, tmp_path, capsys):
    log = tmp_path / "CHANGELOG.md"
    log.write_text(LOG, encoding="utf-8")
    monkeypatch.delenv("DISCORD_WEBHOOK_URL", raising=False)
    rc = dr.main(["--product", "X", "--version", "20261118",
                  "--changelog", str(log), "--link", "https://x.invalid"])
    assert rc == 0 and "nothing posted" in capsys.readouterr().out


def test_rejection_fails(monkeypatch, tmp_path):
    log = tmp_path / "CHANGELOG.md"
    log.write_text(LOG, encoding="utf-8")
    monkeypatch.setenv("DISCORD_WEBHOOK_URL", "https://discord.invalid/api/webhooks/1/x")

    def boom(url, data):
        raise RuntimeError("HTTP 404: Unknown Webhook")
    monkeypatch.setattr(dr, "post", boom)
    rc = dr.main(["--product", "X", "--version", "20261118",
                  "--changelog", str(log), "--link", "https://x.invalid"])
    assert rc == 1
