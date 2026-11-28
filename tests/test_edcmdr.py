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


def test_squad_fields_parse():
    mod = _load_component()
    assert mod.parse_utc("2026-12-01 18:00") == 1796148000
    assert mod.parse_utc("2026-12-01") == 1796083200
    assert [mod.parse_credits(x) for x in ("100M", "1.5B", "250k", "100,000,000", "", "12 cr")] == \
        [100_000_000, 1_500_000_000, 250_000, 100_000_000, 0, 12]
    assert mod.parse_weights("5, 3,2") == [5.0, 3.0, 2.0]
    assert mod.parse_pairs("50:2, 100:1", "pct", "w") == [{"pct": 50.0, "w": 2.0}, {"pct": 100.0, "w": 1.0}]
    assert mod.parse_pairs("10k:50", "target", "pct", amount_a=True) == [{"target": 10000, "pct": 50.0}]
    for bad in (lambda: mod.parse_utc("tomorrow"), lambda: mod.parse_credits("lots"),
                lambda: mod.parse_pairs("50", "a", "b")):
        with pytest.raises(ValueError):
            bad()


def test_squad_settings_listed():
    mod = _load_component()
    ids = {getattr(x, "key", None) or getattr(x, "id", None) for x in mod.EDCMDRPlugin.SETTINGS}
    assert {"SquadEvents", "JoinCode", "EvTitle", "EvMetric", "EvPool", "ev_save", "ev_invite", "ev_join",
            "Webhook"} <= ids


def _view_core(view):
    plug = SimpleNamespace(squad_view=lambda: view)
    return SimpleNamespace(_plugins={"edcmdr": plug}, state=SimpleNamespace())


def test_squad_tab_shows_standings():
    from core.windows import objectives as W
    now = int(time.time())
    ev = {"id": "e0123456789abcde", "title": "Osmium Rush", "note": "Ogmar rings", "metric": "mined_tons",
          "metric_label": "Tons refined", "unit": "t", "state": "open", "starts": now - 3600, "ends": now + 90000,
          "filters": {"systems": [{"id64": 1, "name": "Ogmar"}], "commodities": ["osmium"], "markets": []},
          "payout": {"pool": 100_000_000, "tiers": [{"target": 1000, "pct": 50}, {"target": 2000, "pct": 100}]},
          "total": 1200, "tier": 0, "pool": 50_000_000, "leader": True,
          "standings": [{"name": "ONE", "pub_id": "a", "value": 800, "rank": 1, "credits": 40_000_000},
                        {"name": "TWO", "pub_id": "b", "value": 400, "rank": 2, "credits": 10_000_000}],
          "me": {"name": "TWO", "pub_id": "b", "value": 400, "rank": 2, "credits": 10_000_000}}
    tab = W.squad_goals(_view_core({"state": "on", "pub_id": "b", "events": [ev]}))
    text = json.dumps(tab.rows)
    assert tab.title == "Squad Goals"
    for want in ("Osmium Rush", "Ogmar", "osmium", "1,200 t", "next at 2,000 t", "e0123456789abcde", "CMDR ONE",
                 "40.0M"):
        assert want in text, want
    mine = [r for r in tab.rows if r[0] == "cells" and r[1] == "CMDR TWO"][0]
    assert "highlight" in mine[3], "your own row stands out"


@pytest.mark.parametrize("view, want", [
    ({"state": "off"}, "Options › ED Commanders"),
    ({"state": "switched-off", "name": "X"}, "Take part in my squadron"),
    ({"state": "unverified", "name": "X"}, "Verify CMDR X"),
    ({"state": "on", "events": [], "note": "Sign in to Frontier to count in Squad Goals."}, "Sign in to Frontier"),
    ({"state": "on", "events": []}, "No events running"),
])
def test_squad_tab_explains_itself(view, want):
    from core.windows import objectives as W
    assert want in json.dumps(W.squad_goals(_view_core(view)).rows, ensure_ascii=False)


def test_squad_goals_panel_for_edam():
    from core.windows import wire
    core = _view_core({"state": "on", "events": []})
    panels = {p["id"]: p for p in wire.panels(core) if p["id"].startswith("squad_goals")}
    assert panels["squad_goals.events"]["group"] == "squad_goals"


def test_switching_events_off_reaches_shared_settings(plugin):
    make, _, _ = plugin
    p = make()
    _wait(lambda: _snapshots(), "first snapshot")
    assert Settings().prefs(FID)["events"], "on unless switched off"
    p.core.cfg.set(SquadEvents=False)
    _wait(lambda: not Settings().prefs(FID)["events"], "switch copied to the shared settings")
    _wait(lambda: any(e["kind"] == "prefs" and e["body"].get("events") is False for e in Fake.log), "sent")


def test_leader_saves_and_invites_from_options(plugin):
    make, _, _ = plugin
    p = make()
    _wait(lambda: _snapshots(), "first snapshot")
    p.core.cfg.set(EvTitle="Osmium Rush", EvMetric="mined_tons", EvStart="2026-12-01 18:00",
                   EvEnd="2026-12-08", EvSystems="Ogmar, Sol", EvCommodities="osmium", EvPool="100M",
                   EvPlaces="5,3", EvBands="100:1", EvTiers="10k:50, 20k:100", EvMin="1")
    msg = p.settings_action("ev_save")
    assert "e0123456789abcde" in msg, msg
    sent = [e for e in Fake.log if e["kind"] == "event-admin"][-1]["body"]
    assert sent["action"] == "save" and "id" not in sent
    assert (sent["starts"], sent["ends"]) == (1796148000, 1796688000)
    assert sent["filters"] == {"systems": ["Ogmar", "Sol"], "markets": [], "commodities": ["osmium"]}
    assert sent["payout"] == {"pool": 100_000_000, "places": [5.0, 3.0], "bands": [{"pct": 100.0, "w": 1.0}],
                              "min": 1, "tiers": [{"target": 10000, "pct": 50}, {"target": 20000, "pct": 100}]}
    assert p.settings()["EvId"] == "e0123456789abcde", "the saved event's id goes into Options"
    p.core.cfg.set(InvKind="personal", InvName="GUEST PILOT", InvDays="2")
    msg = p.settings_action("ev_invite")
    assert "ABCD-EFGH-JKLM" in msg and "GUEST PILOT" in msg, msg
    sent = [e for e in Fake.log if e["kind"] == "event-admin"][-1]["body"]
    assert sent["id"] == "e0123456789abcde" and sent["kind"] == "personal" and "max_uses" not in sent
    p.core.cfg.set(EvStart="soon")
    assert "UTC date" in p.settings_action("ev_save"), "a bad field says which"


def test_invitation_code_from_options(plugin):
    make, _, _ = plugin
    p = make()
    _wait(lambda: _snapshots(), "first snapshot")
    assert "Invitation code" in p.settings_action("ev_join")
    p.core.cfg.set(JoinCode=" abcd-efgh-jklm ")
    assert "Osmium Rush" in p.settings_action("ev_join")
    assert [e for e in Fake.log if e["kind"] == "event-join"][-1]["body"] == {"code": "abcd-efgh-jklm"}


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
    """A leader verified on the real server saves an event from Options; the server reads the (fake) Frontier
    journal through EDLD's sign-in; the Squad Goals tab shows the standings."""
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
        s = Settings()
        prefs = s.prefs(fid)
        prefs["share"]["ranks"] = True
        s.set_prefs(fid, prefs)
        core = _core(tmp_path, jdir, enabled=True)
        core.state.pilot_fid = fid
        p = mod.EDCMDRPlugin()
        p.storage = PluginStorage("edcmdr")
        p.on_load(core)
        _wait(lambda: p.engine.rt.get(fid) and p.engine.rt[fid].last_push, "published", 20)

        # Verify EDLD's own commander key as the squadron's leader, through the server's fake Frontier.
        profile = {"commander": {"id": 8800001, "name": name},
                   "squadron": {"id": 8800, "name": "EDLD WING", "tag": "EDLW", "rank": 0}}
        p.engine.pause()
        time.sleep(1.5)
        st, j, *_ = ts.follow_verify(ts.Client(fid=fid, key=keys.commander_key(fid)), name, profile)
        assert st == 200, j
        ts.Frontier.profile = profile
        ts.Frontier.systems = {"Ogmar": 1234567}
        y = (datetime.now(tz.utc) - timedelta(days=1)).strftime("%Y-%m-%dT12:00:00Z")
        line = lambda **e: json.dumps(dict(timestamp=y, **e)) + "\n"
        ts.Frontier.days = {1: line(event="Location", StarSystem="Ogmar", SystemAddress=1234567)
                               + line(event="MiningRefined", Type="$osmium_name;")
                               + line(event="MiningRefined", Type="$osmium_name;")
                               + line(event="MiningRefined", Type="$painite_name;")}
        p.engine.frontier_token = lambda f: ts.Frontier.token
        p.engine.rt[fid].prefs_sent = None     # verified outside the engine: its next prefs reply says so
        p.engine.resume()
        p.engine.push_now()
        _wait(lambda: p.engine.rt[fid].leader_of == 8800, "leader known", 20)

        fmt = lambda d: (datetime.now(tz.utc) + timedelta(days=d)).strftime("%Y-%m-%d %H:%M")
        core.cfg.set(EvTitle="Osmium Rush", EvMetric="mined_tons", EvStart=fmt(-3), EvEnd=fmt(3),
                     EvSystems="ogmar", EvCommodities="osmium", EvPool="10M", EvPlaces="1")
        msg = p.settings_action("ev_save")
        assert "event id" in msg, msg
        p.engine.sync_events_now(fid)

        def mine():
            ev = (p.engine.events_of(fid) or {}).get("events") or []
            return ev and (ev[0].get("me") or {}).get("value") == 2
        _wait(mine, "the journal read from Frontier and scored", 40)
        from core.windows import objectives as W
        core._plugins = {"edcmdr": p}
        text = json.dumps(W.squad_goals(core).rows)
        assert "Osmium Rush" in text and f"CMDR {name}" in text and "10.0M" in text, text
        p.on_unload()
    finally:
        ts.Frontier.days = {}
        ts.tearDownModule()
