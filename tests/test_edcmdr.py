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
    events: dict = {}

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
        out = {"ok": True, "kind": env["kind"], "re": keys.b64u(hashlib.sha256(raw).digest())[:22],
               "pub_id": "k7q2m9xd4a", "accepted": list(env["body"].get("categories", {}))}
        body = env["body"]
        if env["kind"] == "events":
            out.update(Fake.events)
        elif env["kind"] == "event-admin":
            out.update({"save": {"event": {"id": "e0123456789abcde", "title": body.get("title")}},
                        "invite": {"code": "ABCD-EFGH-JKLM", "for": body.get("name"), "kind": body.get("kind")},
                        "remove": {"removed": body.get("name")}}.get(body.get("action"), {}))
        elif env["kind"] == "event-join":
            out.update({"joined": True, "event": {"title": "Osmium Rush"}})
        self._reply(out)


@pytest.fixture
def server(monkeypatch, tmp_path):
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Fake)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    Fake.log = []
    monkeypatch.setenv("EDCMDR_HOME", str(tmp_path / "edcmdr-home"))
    monkeypatch.setenv("EDCMDR_SERVER", f"http://127.0.0.1:{httpd.server_port}")
    monkeypatch.setenv("EDCMDR_BUILD_KEY", keys.b64u(BUILD.private_bytes_raw()))
    monkeypatch.setenv("EDCMDR_DEV_SERVER_KEY", keys.b64u(keys.raw_pub(SERVER)))
    Fake.events = {}
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


class _Capi:
    """EDLD's Frontier CAPI sign-in, as the component sees it."""

    def __init__(self, token="capi-token"):
        self.token, self.auth_calls = token, 0

    def is_connected(self):
        return self.token is not None

    def _valid_token(self):
        return self.token

    def authenticate(self):
        self.auth_calls += 1


def test_squad_amounts_parse():
    from core.windows.squad import parse_credits, parse_weights
    assert [parse_credits(x) for x in ("100M", "1.5B", "250k", "100,000,000", "", "12 cr", "25,000 t")] == \
        [100_000_000, 1_500_000_000, 250_000, 100_000_000, 0, 12, 25_000]
    assert parse_weights("50, 30,20") == [50.0, 30.0, 20.0]
    for bad in (lambda: parse_credits("lots"), lambda: parse_weights("five")):
        with pytest.raises(ValueError):
            bad()


def test_payout_preview_in_plain_words():
    from core.windows.squad import preview
    assert preview({"pool": 0}) == "No prize pool: standings only."
    text = preview({"pool": 100_000_000, "places": [50, 30, 20], "bands": [{"pct": 100, "w": 5}],
                    "tiers": [{"target": 10000, "pct": 50}, {"target": 25000, "pct": 100}]})
    assert text.startswith("With 10 commanders taking part: 1st ")
    assert "6th to 10th " in text and "50% of it once the squadron reaches 10,000" in text
    assert preview({"pool": 100_000_000, "places": [50, 30, 20]}).endswith("Nobody below 3rd is paid.")


def test_options_keep_only_what_belongs_there():
    mod = _load_component()
    keys_ = {getattr(x, "key", None) or getattr(x, "id", None) for x in mod.EDCMDRPlugin.SETTINGS}
    assert {"SquadEvents", "JoinCode", "ev_join", "PortraitFile"} <= keys_
    assert not {k for k in keys_ if k and (k.startswith("Ev") or k in ("Webhook", "MemberName", "InvKind"))}, \
        "the event form lives in the Squad Goals window"
    portrait = next(x for x in mod.EDCMDRPlugin.SETTINGS if getattr(x, "key", None) == "PortraitFile")
    assert portrait.kind == "file" and "*.png" in portrait.filter


def _view_core(view, access=None):
    plug = SimpleNamespace(squad_view=lambda: view,
                           squad_access=lambda: access or {"show": True, "lead": False, "why": ""})
    return SimpleNamespace(_plugins={"edcmdr": plug}, state=SimpleNamespace())


def test_squad_window_shows_standings():
    from core.windows import squad as W
    now = int(time.time())
    ev = {"id": "e0123456789abcde", "title": "Osmium Rush", "note": "Ogmar rings", "metric": "mined_tons",
          "metric_label": "Tons refined", "unit": "t", "state": "open", "starts": now - 3600, "ends": now + 90000,
          "filters": {"systems": [{"id64": 1, "name": "Ogmar"}], "commodities": ["osmium"],
                      "commodity_names": ["Osmium"], "markets": []},
          "payout": {"pool": 100_000_000, "tiers": [{"target": 1000, "pct": 50}, {"target": 2000, "pct": 100}]},
          "total": 1200, "tier": 0, "pool": 50_000_000, "leader": True,
          "standings": [{"name": "ONE", "pub_id": "a", "value": 800, "rank": 1, "credits": 40_000_000},
                        {"name": "TWO", "pub_id": "b", "value": 400, "rank": 2, "credits": 10_000_000}],
          "me": {"name": "TWO", "pub_id": "b", "value": 400, "rank": 2, "credits": 10_000_000}}
    tab = W.events_tab(_view_core({"state": "on", "pub_id": "b", "events": [ev]}))
    text = json.dumps(tab.rows)
    for want in ("Osmium Rush", "Ogmar", "Osmium", "1,200 t", "next at 2,000 t", "CMDR ONE", "40.0M"):
        assert want in text, want
    assert "e0123456789abcde" not in text, "the event id stays out of sight"
    mine = [r for r in tab.rows if r[0] == "cells" and r[1] == "CMDR TWO"][0]
    assert "highlight" in mine[3], "your own row stands out"


@pytest.mark.parametrize("view, want", [
    ({"state": "off"}, "Options › ED Commanders"),
    ({"state": "switched-off", "name": "X"}, "Take part in my squadron"),
    ({"state": "unverified", "name": "X"}, "Verifying CMDR X"),
    ({"state": "on", "events": [], "note": "Sign in to Frontier to count in Squad Goals."}, "Sign in to Frontier"),
    ({"state": "on", "events": []}, "No events running"),
])
def test_squad_window_explains_itself(view, want):
    from core.windows import squad as W
    assert want in json.dumps(W.events_tab(_view_core(view)).rows, ensure_ascii=False)


def test_squad_goals_not_in_objectives_and_edam_only_when_it_applies():
    from core.windows import objectives, wire
    assert not hasattr(objectives, "squad_goals")
    on = _view_core({"state": "on", "events": []})
    off = _view_core({"state": "on", "events": []}, {"show": False, "lead": False, "why": "x"})
    ids = lambda core: {p["id"] for p in wire.panels(core)}
    assert "squad_goals.events" in ids(on)
    assert "squad_goals.events" not in ids(off)


def test_squad_access(plugin):
    make, _, _ = plugin
    p = make()
    _wait(lambda: _snapshots(), "first snapshot")
    assert p.squad_access()["show"] is False and "Sign in to Frontier" in p.squad_access()["why"]
    p.core.data = SimpleNamespace(capi=_Capi())
    p.core.state.pilot_squadron_name = ""
    assert "not in a squadron" in p.squad_access()["why"]
    p.core.state.pilot_squadron_name = "GOAL WING"
    acc = p.squad_access()
    assert acc["show"] is True and acc["lead"] is False, acc


def test_one_sign_in(plugin):
    make, _, _ = plugin
    p = make()
    _wait(lambda: _snapshots(), "first snapshot")
    capi = _Capi(token=None)
    p.core.data = SimpleNamespace(capi=capi)
    msg = p.settings_action("verify")
    assert capi.auth_calls == 1 and "browser" in msg, "no sign-in yet: EDLD's own Frontier sign-in starts"
    assert not any(e["kind"] == "verify-start" for e in Fake.log), "never the second, edcmdr.com sign-in"
    capi.token = "capi-token"
    p.engine.rt[FID].auto_verify_next = 0          # within a minute of signing in; not waited for here
    p.engine.push_now()
    _wait(lambda: any(e["kind"] == "verify-finish" for e in Fake.log), "verified by itself once signed in", 15)
    vf = [e for e in Fake.log if e["kind"] == "verify-finish"][-1]["body"]
    assert vf == {"access_token": "capi-token", "direct": True}
    assert "verified" in p.settings_action("verify")


def test_switching_events_off_reaches_shared_settings(plugin):
    make, _, _ = plugin
    p = make()
    _wait(lambda: _snapshots(), "first snapshot")
    assert Settings().prefs(FID)["events"], "on unless switched off"
    p.core.cfg.set(SquadEvents=False)
    _wait(lambda: not Settings().prefs(FID)["events"], "switch copied to the shared settings")
    _wait(lambda: any(e["kind"] == "prefs" and e["body"].get("events") is False for e in Fake.log), "sent")


def test_invitation_code_from_options(plugin):
    make, _, _ = plugin
    p = make()
    _wait(lambda: _snapshots(), "first snapshot")
    assert "Invitation code" in p.settings_action("ev_join")
    p.core.cfg.set(JoinCode=" abcd-efgh-jklm ")
    assert "Osmium Rush" in p.settings_action("ev_join")
    assert [e for e in Fake.log if e["kind"] == "event-join"][-1]["body"] == {"code": "abcd-efgh-jklm"}


@pytest.fixture
def qapp():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    pytest.importorskip("PySide6")
    from PySide6 import QtWidgets
    yield QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


def test_squad_window_form(qapp):
    from PySide6.QtCore import QDate
    from gui import squad_goals as G
    calls = []
    plug = SimpleNamespace(
        squad_view=lambda: {"state": "on", "events": [], "webhook": True},
        squad_access=lambda: {"show": True, "lead": False, "why": ""},
        squad_admin=lambda action, **b: calls.append((action, b)) or {"event": {"id": "e1", "title": b.get("title")}})
    core = SimpleNamespace(_plugins={"edcmdr": plug}, state=SimpleNamespace(), cfg=None)
    win = G.SquadGoalsWindow(core)
    assert win.tabs.isTabVisible(1) is False, "the event form only for the squadron's verified leader"
    plug.squad_access = lambda: {"show": True, "lead": True, "why": ""}
    win.refresh(force=True)
    assert win.tabs.isTabVisible(1) is True
    f = win.form
    f.title.setText("Osmium Rush")
    f.starts.setDate(QDate(2026, 12, 1))
    f.ends.setDate(QDate(2026, 12, 7))
    f.measure.setCurrentIndex(f.measure.findData("mined_tons"))
    f.pool.setText("100M")
    f.places.setText("50, 30, 20")
    f.bands.set_rows([("50", "5"), ("100", "2")])
    f.tiers.set_rows([("10,000", "50"), ("25k", "100")])
    f.floor.setText("10")
    f.system.setText("Ogmar")
    body = f._body(["Osmium"])
    assert (body["starts"], body["ends"]) == (1796083200, 1796688000 - 1), "00:00:00 first day to 23:59:59 last"
    assert body["filters"] == {"systems": ["Ogmar"], "markets": [], "commodities": ["Osmium"]}
    assert body["payout"] == {"pool": 100_000_000, "places": [50.0, 30.0, 20.0],
                              "bands": [{"pct": 50.0, "w": 5.0}, {"pct": 100.0, "w": 2.0}], "min": 10,
                              "tiers": [{"target": 10000, "pct": 50}, {"target": 25000, "pct": 100}]}
    assert "id" not in body, "a new event: no id"
    assert "With 10 commanders" in f.preview.text()
    assert "saved for your squadron" in f.hook.placeholderText()
    assert "23:59:59" in f.days.text() and "7 days" in f.days.text()
    f.title.clear()
    with pytest.raises(ValueError):
        f._body([])
    win.close()


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


@pytest.mark.skipif(not os.environ.get("EDCMDR_SERVER_REPO"), reason="EDCMDR_SERVER_REPO not set")
def test_squad_goals_end_to_end(tmp_path, monkeypatch):
    """One sign-in: EDLD's own Frontier sign-in verifies the leader on the real server, no browser. The leader
    saves an event; the server reads the (fake) Frontier journal; the window shows the standings. And EDLD's
    payout preview pays what the server pays."""
    from datetime import datetime, timedelta, timezone as tz
    repo = Path(os.environ["EDCMDR_SERVER_REPO"]).expanduser()
    spec = importlib.util.spec_from_file_location("edcmdr_server_tests_sg", repo / "tests" / "test_server.py")
    ts = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ts)
    ts.setUpModule()
    fid, name = "F8800001", "SQUAD LEADER"
    try:
        monkeypatch.setenv("EDCMDR_HOME", str(tmp_path / "home"))
        monkeypatch.setenv("EDCMDR_SERVER", f"http://127.0.0.1:{ts.SERVER.port}")
        monkeypatch.setenv("EDCMDR_BUILD_KEY", keys.b64u(ts.BUILD.private_bytes_raw()))
        monkeypatch.setenv("EDCMDR_DEV_SERVER_KEY", keys.b64u(ts.SERVER_PUB.public_bytes_raw()))
        jdir = tmp_path / "journals"
        jdir.mkdir()
        _journal(jdir / "Journal.2026-11-23T100000.01.log", _events(fid=fid, name=name))
        data = tmp_path / "edld"
        (data / "commanders" / fid).mkdir(parents=True)
        mod = _load_component()
        monkeypatch.setattr(mod, "EDLD_DATA_DIR", data)
        import core.state
        monkeypatch.setattr(core.state, "cmdr_data_dir", lambda: data / "commanders" / fid)
        profile = {"commander": {"id": 8800001, "name": name},
                   "squadron": {"id": 8800, "name": "EDLD WING", "tag": "EDLW", "rank": 0}}
        ts.Frontier.profile = profile
        ts.Frontier.systems = {"Ogmar": 1234567}
        y = (datetime.now(tz.utc) - timedelta(days=1)).strftime("%Y-%m-%dT12:00:00Z")
        line = lambda **e: json.dumps(dict(timestamp=y, **e)) + "\n"
        ts.Frontier.days = {1: line(event="Location", StarSystem="Ogmar", SystemAddress=1234567)
                               + line(event="MiningRefined", Type="$osmium_name;")
                               + line(event="MiningRefined", Type="$osmium_name;")
                               + line(event="MiningRefined", Type="$painite_name;")}
        core = _core(tmp_path, jdir, enabled=True)
        core.state.pilot_fid = fid
        core.state.pilot_squadron_name = "EDLD WING"
        core.data = SimpleNamespace(capi=_Capi(token=ts.Frontier.token))
        p = mod.EDCMDRPlugin()
        p.storage = PluginStorage("edcmdr")
        p.on_load(core)
        core._plugins = {"edcmdr": p}
        _wait(lambda: p.engine.rt.get(fid) and p.engine.rt[fid].verified, "verified with EDLD's sign-in", 30)
        _wait(lambda: p.engine.rt[fid].leader_of == 8800, "leader known", 20)
        from core.windows import squad as W
        _wait(lambda: W.access(core)["lead"], "the event form is offered", 20)

        today = datetime.now(tz.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        starts = int((today - timedelta(days=3)).timestamp())
        j = p.squad_admin("lookup", system="ogmar", commodities=["osmim"])
        assert j["system"]["name"] == "Ogmar" and j["commodities"][0]["symbol"] == "osmium", j
        j = p.squad_admin("save", title="Osmium Rush", metric="mined_tons", starts=starts,
                          ends=starts + 7 * 86400 - 1, filters={"systems": ["ogmar"], "commodities": ["Osmium"]},
                          payout={"pool": 10_000_000, "places": [1]})
        assert j["event"]["title"] == "Osmium Rush"
        p.squad_sync_now()

        def mine():
            ev = (p.engine.events_of(fid) or {}).get("events") or []
            return ev and (ev[0].get("me") or {}).get("value") == 2
        _wait(mine, "the journal read from Frontier and scored", 40)
        text = json.dumps(W.events_tab(core).rows)
        assert "Osmium Rush" in text and f"CMDR {name}" in text and "10.0M" in text, text

        import random
        rnd = random.Random(3)
        cases = []
        for _ in range(150):
            places = sorted((rnd.randint(1, 50) for _ in range(rnd.randint(0, 4))), reverse=True)
            bw = sorted((rnd.randint(1, places[-1] if places else 40) for _ in range(rnd.randint(0, 3))), reverse=True)
            pcts = sorted(rnd.sample(range(1, 101), len(bw)))
            cases.append({"v": {f"c{i}": rnd.choice([0, 1, 3, 5, 5, 10, 40]) for i in range(rnd.randint(1, 25))},
                          "p": {"pool": rnd.randint(0, 10**9), "places": places, "min": rnd.randint(0, 6),
                                "bands": [{"pct": a, "w": b} for a, b in zip(pcts, bw)],
                                "tiers": [{"target": 20, "pct": 40}, {"target": 60, "pct": 100}][:rnd.randint(0, 2)]}})
        out = json.loads(ts.php("-r", 'require "lib/bootstrap.php"; $in = json_decode(stream_get_contents(STDIN), true);'
                                ' echo json_encode(array_map(fn($c) => Edcmdr\\SquadGoals::payouts($c["v"], $c["p"]), $in));',
                                stdin=json.dumps(cases)))
        for case, server in zip(cases, out):
            mine_ = W.payouts(case["v"], case["p"])
            assert [(r["cid"], r["rank"], r["credits"]) for r in mine_["standings"]] == \
                [(r["cid"], r["rank"], r["credits"]) for r in server["standings"]], case
        p.on_unload()
    finally:
        ts.Frontier.days = {}
        ts.tearDownModule()


def test_squad_goals_terminal_screen():
    """The terminal's read-only Squad Goals screen draws the events, and closes with Escape."""
    import asyncio
    from textual.app import App
    from tui.squad_screen import SquadScreen
    from tui.theme import build_css
    now = int(time.time())
    ev = {"id": "e1", "title": "Bounty Week", "metric": "bounty_value", "metric_label": "Bounty value earned",
          "unit": "cr", "state": "open", "starts": now - 60, "ends": now + 86000, "filters": {}, "payout": {},
          "total": 125000, "standings": [{"name": "ONE", "pub_id": "a", "value": 125000, "rank": 1, "credits": 0}]}
    core = _view_core({"state": "on", "events": [ev]})
    core.cfg = None
    out = {}

    class _Host(App):
        CSS = build_css("default")

    async def _run():
        app = _Host()
        async with app.run_test(size=(110, 40)) as pilot:
            await app.push_screen(SquadScreen(core))
            await pilot.pause()
            out["lines"] = "\n".join("".join(seg.text for seg in strip)
                                     for strip in app.screen._compositor.render_strips())
            await pilot.press("escape")
            await pilot.pause()
            out["stack"] = [type(s).__name__ for s in app.screen_stack]
    asyncio.run(_run())
    assert "Bounty Week" in out["lines"] and "CMDR ONE" in out["lines"], out["lines"]
    assert "SquadScreen" not in out["stack"]


def test_squad_goals_menu_follows_access(qapp):
    """The Squad Goals menu shows only while Squad Goals applies, and opens its window."""
    import queue

    class State:
        in_preload = False

        def __getattr__(self, name):
            if name.startswith("_"):
                raise AttributeError(name)
            return None

    class Cfg:
        config: dict = {}

        def save(self):
            pass

    access = {"show": False, "lead": False, "why": "x"}
    plug = SimpleNamespace(squad_view=lambda: {"state": "on", "events": []}, squad_access=lambda: access)

    class Core:
        state = State()
        cfg = Cfg()
        gui_queue = queue.Queue()
        journal_dir = "/tmp"
        _plugins = {"edcmdr": plug}
        session_providers: list = []
        app_settings: dict = {}

        def plugin_call(self, *a, **k):
            return None

        def register_session_provider(self, provider):
            pass

    from gui.app import EdldWindow
    w = EdldWindow(Core(), "EDLD", "test", "owner", "owner/repo")
    w._check_squad()
    assert w._squad_menu.menuAction().isVisible() is False
    access.update(show=True)
    w._squad_checked = 0
    w._check_squad()
    assert w._squad_menu.menuAction().isVisible() is True
    w.action_squad_goals()
    assert w._squad_window is not None and w._squad_window.isVisible()
    assert w._squad_window.tabs.isTabVisible(1) is False, "not the leader: no event form"
    access.update(show=False)
    w._squad_checked = 0
    w._check_squad()
    assert not w._squad_window.isVisible(), "closed once it no longer applies"
    w.close()
