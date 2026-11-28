"""tests/test_edcmdr.py — the ED Commanders component on EDCMDR-core.

A fake ED Commanders signs its replies; the component reads history from the
journal index, takes live events, publishes, and keeps Options and EDCMDR's
shared settings file in step. The end-to-end test runs when EDCMDR_SERVER_REPO
points at an EDCMDR server checkout (php and MariaDB, as that repo's tests):

    EDCMDR_SERVER_REPO=~/projects/indevlin/EDCMDR python -m pytest tests/test_edcmdr.py
"""
from __future__ import annotations

import builtins
import hashlib
import importlib.util
import json
import os
import sys
import threading
import time
import tomllib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace

import pytest

pytest.importorskip("edcmdr_core")

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey  # noqa: E402
from edcmdr_core import keys  # noqa: E402
from edcmdr_core.settings import Settings  # noqa: E402

from core.plugin_loader import PluginStorage, _make_sandboxed_open  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
SERVER = Ed25519PrivateKey.generate()
BUILD = Ed25519PrivateKey.generate()
FID = "F7300001"


def _load_component():
    spec = importlib.util.spec_from_file_location("_test_plugin_edcmdr", ROOT / "components" / "edcmdr.py")
    mod = importlib.util.module_from_spec(spec)
    mod.__builtins__ = vars(builtins).copy()
    mod.__builtins__["open"] = _make_sandboxed_open("edcmdr")
    sys.modules["_test_plugin_edcmdr"] = mod
    spec.loader.exec_module(mod)
    return mod


class _Cfg:
    """config.toml as the component sees it: load_setting, a path, reload_now."""

    def __init__(self, path: Path, enabled: bool):
        self.config_path = path
        self.config_profile = ""
        self.app_settings = {}
        path.write_text(f"[EDCMDR]\nEnabled = {'true' if enabled else 'false'}\n")
        self.reload_now()

    def reload_now(self):
        self.config = tomllib.loads(self.config_path.read_text())

    def set(self, **kw):
        from core.config import config_to_toml
        self.config.setdefault("EDCMDR", {}).update(kw)
        self.config_path.write_text(config_to_toml(self.config))
        self.reload_now()

    def load_setting(self, section, defaults, warn=True, include_extra=False):
        return dict(defaults, **self.config.get(section, {}))


def _core(tmp: Path, journal_dir: Path, enabled: bool):
    cfg = _Cfg(tmp / "config.toml", enabled)
    return SimpleNamespace(journal_dir=journal_dir, cfg=cfg, load_setting=cfg.load_setting,
                           state=SimpleNamespace(pilot_fid=FID), data=None)


def _journal(path: Path, events: list[dict]) -> None:
    path.write_text("\n".join(json.dumps(e) for e in events) + "\n")


def _events(fid=FID, name="EDLD PILOT", combat=5, ts="2026-11-23T10:00:00Z"):
    return [
        {"timestamp": ts, "event": "Fileheader", "part": 1, "gameversion": "4.4.2.1", "build": "r1"},
        {"timestamp": ts, "event": "Commander", "FID": fid, "Name": name},
        {"timestamp": ts, "event": "LoadGame", "FID": fid, "Commander": name, "Ship": "Mandalay",
         "ShipID": 0, "GameMode": "Solo", "Credits": 1000},
        {"timestamp": ts, "event": "Rank", "Combat": combat, "Trade": 8, "Explore": 6, "Soldier": 2,
         "Exobiologist": 4, "Empire": 12, "Federation": 9, "CQC": 0},
    ]


class Fake(BaseHTTPRequestHandler):
    log: list = []

    def log_message(self, *a):
        pass

    def _reply(self, obj, status=200):
        body = json.dumps(obj).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("X-EDCMDR-Server", keys.key_id(keys.raw_pub(SERVER)))
        self.send_header("X-EDCMDR-Reply-Sig", keys.b64u(SERVER.sign(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        n = self.path.split("n=")[1]
        self._reply({"ok": True, "kind": "hello", "n": n, "protocols": [1], "time": int(time.time())})

    def do_POST(self):
        raw = self.rfile.read(int(self.headers["Content-Length"]))
        env = json.loads(raw)
        Fake.log.append(env)
        self._reply({"ok": True, "kind": env["kind"], "re": keys.b64u(hashlib.sha256(raw).digest())[:22],
                     "pub_id": "k7q2m9xd4a", "accepted": list(env["body"].get("categories", {}))})


@pytest.fixture
def server(monkeypatch, tmp_path):
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Fake)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    Fake.log = []
    monkeypatch.setenv("EDCMDR_HOME", str(tmp_path / "edcmdr-home"))
    monkeypatch.setenv("EDCMDR_SERVER", f"http://127.0.0.1:{httpd.server_port}")
    monkeypatch.setenv("EDCMDR_BUILD_KEY", keys.b64u(BUILD.private_bytes_raw()))
    monkeypatch.setenv("EDCMDR_DEV_SERVER_KEY", keys.b64u(keys.raw_pub(SERVER)))
    yield httpd
    httpd.shutdown()


@pytest.fixture
def plugin(server, tmp_path, monkeypatch):
    """A running component over one journal, with EDLD profiles for FID."""
    jdir = tmp_path / "journals"
    jdir.mkdir()
    _journal(jdir / "Journal.2026-11-23T100000.01.log", _events())
    data = tmp_path / "edld"
    (data / "commanders" / FID).mkdir(parents=True)
    mod = _load_component()
    monkeypatch.setattr(mod, "EDLD_DATA_DIR", data)
    monkeypatch.setattr(mod._Host, "presence_of", lambda self, fid: {"in_game": False})
    import core.state
    monkeypatch.setattr(core.state, "cmdr_data_dir", lambda: data / "commanders" / FID)
    p = mod.EDCMDRPlugin()
    p.storage = PluginStorage("edcmdr")
    created = []

    def make(share=("ranks",)):
        s = Settings()
        prefs = s.prefs(FID)
        for c in share:
            prefs["share"][c] = True
        s.set_prefs(FID, prefs)
        p.on_load(_core(tmp_path, jdir, enabled=True))
        created.append(p)
        return p
    yield make, jdir, mod
    for x in created:
        x.on_unload()


def _wait(cond, what, timeout=15):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if cond():
            return
        time.sleep(0.1)
    pytest.fail(f"timed out: {what}")


def _snapshots():
    return [e for e in Fake.log if e["kind"] == "snapshot"]


def test_off_by_default(tmp_path):
    mod = _load_component()
    p = mod.EDCMDRPlugin()
    p.storage = PluginStorage("edcmdr")
    p.on_load(_core(tmp_path, tmp_path, enabled=False))
    assert p.engine is None
    assert "off" in p.status()
    assert "off" in p.settings_action("push")
    p.on_unload()


def test_settings_page_is_complete():
    mod = _load_component()
    keys_ = {s.key for s in mod.EDCMDRPlugin.SETTINGS if hasattr(s, "kind")}
    actions = {s.id for s in mod.EDCMDRPlugin.SETTINGS if hasattr(s, "id")}
    from edcmdr_core.spec import SHAREABLE
    assert {f"Share_{c}" for c in SHAREABLE} <= keys_
    assert "Delay_portrait" not in keys_ and "Delay_presence" not in keys_, "never delayed"
    assert {"verify", "open", "push", "status", "portrait", "squadron", "forget"} <= actions
    assert mod.EDCMDRPlugin.SETTINGS_TAB[0] in __import__("core.options_pages", fromlist=["ORDER"]).ORDER


def test_build_key_stays_out_of_git():
    assert "core/_edcmdr_build.py" in (ROOT / ".gitignore").read_text().splitlines()


def test_publishes_history_as_edld(plugin):
    make, _, _ = plugin
    p = make()
    _wait(lambda: _snapshots(), "first snapshot")
    snap = _snapshots()[-1]
    assert snap["client"]["name"] == "EDLD"
    assert snap["fid"] == FID
    assert snap["body"]["categories"]["ranks"]["rank"]["Combat"] == 5
    assert "fleet" not in snap["body"]["categories"], "only what is shared"
    assert p.settings()["Share_ranks"] is True, "the client's sharing was copied into Options"


def test_live_events_follow_the_history(plugin):
    make, _, _ = plugin
    p = make()
    _wait(lambda: _snapshots(), "first snapshot")
    for ev in _events(combat=6, ts="2026-11-23T11:00:00Z"):
        p.on_event(dict(ev, _logtime=object()), SimpleNamespace(pilot_fid=FID))
    p.engine.push_now()
    _wait(lambda: _snapshots()[-1]["body"]["categories"].get("ranks", {}).get("rank", {}).get("Combat") == 6,
          "live Rank published")


def test_options_change_reaches_shared_settings(plugin):
    make, _, _ = plugin
    p = make()
    _wait(lambda: p.synced.get("config"), "first sync")
    p.core.cfg.set(Share_fleet=True, Delay_fleet="86400")
    p.engine._wake.set()
    _wait(lambda: Settings().prefs(FID)["share"]["fleet"], "fleet shared in EDCMDR's settings")
    assert Settings().prefs(FID)["delay"]["fleet"] == 86400


def test_client_change_reaches_options(plugin):
    make, _, _ = plugin
    p = make()
    _wait(lambda: p.synced.get("config"), "first sync")
    s = Settings()
    prefs = s.prefs(FID)
    prefs["share"]["powerplay"] = True
    s.set_prefs(FID, prefs)
    p.engine._wake.set()
    _wait(lambda: p.settings()["Share_powerplay"] is True, "client's change copied into Options")


def test_forget_needs_two_presses(plugin):
    make, _, _ = plugin
    p = make()
    _wait(lambda: _snapshots(), "first snapshot")
    assert "again" in p.settings_action("forget")
    assert not [e for e in Fake.log if e["kind"] == "forget"]
    assert "forgotten" in p.settings_action("forget")
    assert [e for e in Fake.log if e["kind"] == "forget"]


def test_squadron_needs_a_verified_leader(plugin):
    make, _, _ = plugin
    p = make()
    _wait(lambda: _snapshots(), "first snapshot")
    assert "verified squadron leader" in p.settings_action("squadron")


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
        monkeypatch.setenv("EDCMDR_BUILD_KEY", keys.b64u(ts.BUILD.private_bytes_raw()))
        monkeypatch.setenv("EDCMDR_DEV_SERVER_KEY", keys.b64u(ts.SERVER_PUB.public_bytes_raw()))
        jdir = tmp_path / "journals"
        jdir.mkdir()
        _journal(jdir / "Journal.2026-11-23T100000.01.log", _events())
        data = tmp_path / "edld"
        (data / "commanders" / FID).mkdir(parents=True)
        mod = _load_component()
        monkeypatch.setattr(mod, "EDLD_DATA_DIR", data)
        import core.state
        monkeypatch.setattr(core.state, "cmdr_data_dir", lambda: data / "commanders" / FID)
        s = Settings()
        prefs = s.prefs(FID)
        prefs["share"]["ranks"] = True
        s.set_prefs(FID, prefs)
        p = mod.EDCMDRPlugin()
        p.storage = PluginStorage("edcmdr")
        p.on_load(_core(tmp_path, jdir, enabled=True))
        _wait(lambda: (p.engine.rt.get(FID) and p.engine.rt[FID].last_push), "published", 20)
        st, html, _ = ts.request("/cmdr")
        assert "EDLD PILOT" in html
        p.on_unload()
    finally:
        ts.tearDownModule()
