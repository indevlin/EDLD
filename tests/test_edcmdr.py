"""tests/test_edcmdr.py — the ED Commanders component and the vendored EDCMDR client.

The end-to-end test runs when EDCMDR_SERVER_REPO points at an EDCMDR server
checkout (it needs php and MariaDB, as that repo's tests do):

    EDCMDR_SERVER_REPO=~/projects/indevlin/EDCMDR python -m pytest tests/test_edcmdr.py
"""
from __future__ import annotations

import base64
import builtins
import hashlib
import importlib.util
import json
import os
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from core.plugin_loader import _make_sandboxed_open

ROOT = Path(__file__).resolve().parent.parent
VENDOR = ROOT / "vendor" / "edcmdr-client"


def _load_component():
    spec = importlib.util.spec_from_file_location("_test_plugin_edcmdr", ROOT / "components" / "edcmdr.py")
    mod = importlib.util.module_from_spec(spec)
    mod.__builtins__ = vars(builtins).copy()
    mod.__builtins__["open"] = _make_sandboxed_open("edcmdr")
    sys.modules["_test_plugin_edcmdr"] = mod
    spec.loader.exec_module(mod)
    return mod


def _core(journal_dir: Path, enabled: bool):
    def load_setting(section, defaults, warn=True, include_extra=False):
        return dict(defaults, Enabled=enabled) if section == "EDCMDR" else dict(defaults)
    return SimpleNamespace(journal_dir=str(journal_dir), load_setting=load_setting,
                           cfg=SimpleNamespace(app_settings={}))


def test_vendored_client_matches_its_lock():
    lock = json.loads((VENDOR / "protocol.lock").read_text())
    spec = VENDOR / "protocol" / "v1" / "spec.json"
    assert hashlib.sha256(spec.read_bytes()).hexdigest() == lock["sha256"]
    assert not (VENDOR / "edcmdr" / "_build_secret.py").exists(), "build keys never enter the repository"


def test_off_by_default(tmp_path):
    mod = _load_component()
    p = mod.EDCMDRPlugin()
    p.on_load(_core(tmp_path, enabled=False))
    assert p.engine is None
    assert "off" in p.status()
    assert p.open_settings() is False
    p.on_unload()


def _b64u(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


@pytest.mark.skipif(not os.environ.get("EDCMDR_SERVER_REPO"), reason="EDCMDR_SERVER_REPO not set")
def test_publishes_to_edcmdr(tmp_path, monkeypatch):
    repo = Path(os.environ["EDCMDR_SERVER_REPO"]).expanduser()
    spec = importlib.util.spec_from_file_location("edcmdr_server_tests", repo / "tests" / "test_server.py")
    ts = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ts)
    ts.setUpModule()
    try:
        monkeypatch.setenv("EDCMDR_HOME", str(tmp_path / "home"))
        monkeypatch.setenv("EDCMDR_SERVER", f"http://127.0.0.1:{ts.SERVER.port}")
        monkeypatch.setenv("EDCMDR_BUILD_KEY", _b64u(ts.BUILD.private_bytes_raw()))
        monkeypatch.setenv("EDCMDR_DEV_SERVER_KEY", _b64u(ts.SERVER_PUB.public_bytes_raw()))
        jdir = tmp_path / "journals"
        jdir.mkdir()
        now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        events = [
            {"timestamp": now, "event": "Fileheader", "part": 1, "gameversion": "4.4.2.1", "build": "r1"},
            {"timestamp": now, "event": "Commander", "FID": "F7300001", "Name": "EDLD PILOT"},
            {"timestamp": now, "event": "LoadGame", "FID": "F7300001", "Commander": "EDLD PILOT", "Ship": "Mandalay",
             "ShipID": 0, "GameMode": "Solo", "Credits": 1000},
            {"timestamp": now, "event": "Rank", "Combat": 5, "Trade": 8, "Explore": 6, "Soldier": 2,
             "Exobiologist": 4, "Empire": 12, "Federation": 9, "CQC": 0},
            {"timestamp": now, "event": "Progress", "Combat": 40, "Trade": 70, "Explore": 21, "Soldier": 0,
             "Exobiologist": 10, "Empire": 30, "Federation": 50, "CQC": 0},
        ]
        (jdir / "Journal.2026-11-23T100000.01.log").write_text("\n".join(json.dumps(e) for e in events) + "\n")

        mod = _load_component()
        sys.path.insert(0, str(VENDOR))
        import edcmdr
        from edcmdr.config import Settings
        s = Settings()
        prefs = s.prefs("F7300001")
        prefs["share"]["ranks"] = True
        s.set_prefs("F7300001", prefs)
        s.save()

        p = mod.EDCMDRPlugin()
        p.on_load(_core(jdir, enabled=True))
        assert p.engine is not None
        assert str(jdir) in p.engine.settings.data["journal_dirs"]
        assert edcmdr.NAME == "EDLD", "pushes name EDLD as the client"
        deadline = time.time() + 20
        while time.time() < deadline:
            rt = p.engine.rt.get("F7300001")
            if rt is not None and rt.enrolled and rt.last_push:
                break
            time.sleep(0.3)
        else:
            pytest.fail(f"not published: {p.engine.status}")
        assert p.engine.update_available() == "", "no client update notice inside EDLD"
        st, html, _ = ts.request("/cmdr")
        assert "EDLD PILOT" in html
        assert p.engine.hub is None, "EDLD's own uploaders stay in charge"

        # Squadron leader through EDLD: verify, then edits bound to the squadron the commander leads.
        import urllib.parse
        from edcmdr.proto import ProtoError
        v = p.engine.verify_start("F7300001")
        path = urllib.parse.urlsplit(v["url"]).path
        st, h = ts.get_noredirect(path + "/go")
        q = urllib.parse.parse_qs(urllib.parse.urlsplit(h["Location"]).query)
        ts.Frontier.challenge = q["code_challenge"][0]
        ts.Frontier.profile = {"commander": {"id": 7300001, "name": "EDLD PILOT"},
                               "squadron": {"id": 7301, "name": "EDLD WING", "tag": "EDW", "rank": 0}}
        st, _, _ = ts.request("/verify/callback?" + urllib.parse.urlencode({"code": "good-code", "state": q["state"][0]}))
        assert st == 200
        p.engine.rt["F7300001"].verify_next = 0
        p.engine._wake.set()
        deadline = time.time() + 20
        while time.time() < deadline and p.engine.rt["F7300001"].leader_of is None:
            time.sleep(0.3)
        rt = p.engine.rt["F7300001"]
        assert (rt.leader_of, rt.leader_squadron) == (7301, {"id": 7301, "name": "EDLD WING", "tag": "EDW"})
        with pytest.raises(ProtoError):
            p.engine.save_squadron("F7300001", {"tagline": "not ours"}, 7302)
        rt.leader_of = 7301
        assert p.engine.save_squadron("F7300001", {"tagline": "From EDLD"}, 7301)["squadron"] == 7301
        st, html, _ = ts.request("/squad/edw")
        assert "From EDLD" in html
        p.on_unload()
    finally:
        ts.tearDownModule()
