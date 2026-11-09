"""
core/windows, core/plot_tools, core/panel_actions, core/ranks — the desktop
windows as one model, drawn by the desktop window, the terminal dashboard and
a paired EDAM device alike.
"""
from __future__ import annotations

from types import SimpleNamespace

from core import panel_actions, plot_tools, ranks, tooltab
from core.server import protocol
from core.state import MonitorState
from core.windows import wire


def _core(plugins=None, **state):
    s = MonitorState()
    for k, v in state.items():
        setattr(s, k, v)
    core = SimpleNamespace(state=s, _plugins=dict(plugins or {}), session_providers=[],
                           app_settings={}, gui_queue=None)

    def plugin_call(name, method, *a, **kw):
        p = core._plugins.get(name)
        fn = getattr(p, method, None) if p is not None else None
        return fn(*a, **kw) if fn else None
    core.plugin_call = plugin_call
    return core


def _panels(core):
    return {p["id"]: p for p in wire.panels(core)}


# ── The windows ───────────────────────────────────────────────────────────────

def test_cargo_is_a_table_with_limpets_last_and_totals():
    core = _core(cargo_capacity=300, cargo_items={
        "platinum": {"count": 120, "name_local": "Platinum"},
        "drones": {"count": 20, "name_local": "Limpet"},
        "gold": {"count": 4, "name_local": "Gold", "stolen": True},
    }, cargo_mean_prices={"platinum": 200_000, "gold": 50_000, "drones": 100})
    rows = _panels(core)["cargo"]["rows"]
    head = next(r for r in rows if r["kind"] == "head")
    assert head["label"] == "Commodity" and head["cells"] == ["Tons", "Price", "Value"]
    cells = [r for r in rows if r["kind"] == "cells"]
    assert [r["label"] for r in cells] == ["⚠ Gold", "Platinum", "Limpet", "Totals"]
    assert cells[1]["cells"] == ["120 t", "200K cr", "24.0M cr"]
    assert cells[-1]["cells"][0] == "144/300 t"


def test_modules_carry_the_damage_count_and_tones():
    core = _core(ship_modules=[
        {"name_display": "Refinery", "health": 0.5, "priority": 1},
        {"name_display": "Thrusters", "health": 1.0, "priority": 0, "on": False},
    ])
    p = _panels(core)["ship.modules"]
    assert p["heading"] == "MODULES — 1 damaged"
    tones = {r["label"].split("  ", 1)[1]: r.get("tone") for r in p["rows"]}
    assert tones == {"Thrusters (off)": "dim", "Refinery": "warn"}


def test_engineering_reaches_the_device_as_pages():
    core = _core(materials_raw={"iron": {"name_local": "Iron", "count": 300}})
    p = _panels(core)["ship.engineering"]
    ids = [pg["id"] for pg in p["pages"]]
    assert ids[:3] == ["raw", "manufactured", "encoded"]
    raw = p["pages"][0]["rows"]
    assert any("Iron" in (r["label"] + r["value"]) for r in raw)


def test_missions_stack_is_a_kills_missions_reward_table_with_a_warning():
    core = _core(mission_detail_map={
        1: {"faction": "A", "kill_count": 10, "reward": 5_000_000, "target_faction": "X"},
        2: {"faction": "B", "kill_count": 6, "reward": 3_000_000, "target_faction": "Y"},
    }, active_missions=[1, 2])
    rows = _panels(core)["missions.missions"]["rows"]
    head = next(r for r in rows if r["kind"] == "head")
    assert head["label"] == "MASSACRE SOURCE FACTION"
    assert head["cells"] == ["KILLS", "MISSIONS", "REWARD"]
    totals = next(r for r in rows if r["label"] == "Totals")
    assert totals["cells"] == ["10", "00 / 02", "8.0M"]
    warn = [r for r in rows if r.get("tone") == "warn"]
    assert warn and "Mixed targets" in warn[0]["value"]


def test_every_desktop_window_has_its_panels():
    ids = set(_panels(_core()))
    assert {"cargo", "ship.modules", "ship.engineering", "commander.info",
            "commander.ranks", "commander.wallet", "commander.ships",
            "commander.stored-modules", "crew.crew", "exploration.system",
            "missions.missions", "colonisation.colonisation",
            "session.session", "career.summary"} <= ids


def test_panel_ids_survive_title_changes():
    core = _core(ship_modules=[{"name_display": "Refinery", "health": 1.0}])
    before = set(_panels(core))
    core.state.ship_modules[0]["health"] = 0.4
    assert set(_panels(core)) == before


def test_the_snapshot_carries_the_windows_and_omits_status():
    core = _core(cargo_capacity=64, cargo_items={"tritium": {"count": 64, "name_local": "Tritium"}})
    b = protocol.SnapshotBuilder(core)
    ids = {p["id"] for p in b.panels()}
    assert "cargo" in ids and "ship.engineering" in ids
    assert "status" in b.header()["edcars"]["omit"]


# ── Ranks ─────────────────────────────────────────────────────────────────────

def test_ranks_come_from_the_journal_without_frontier():
    s = MonitorState()
    ranks.apply(s, {"event": "Rank", "Combat": 3, "Trade": 5})
    ranks.apply(s, {"event": "Progress", "Combat": 40, "Trade": 7})
    assert s.pilot_rank_progress == 40
    assert dict(ranks.rows(s))["Combat"] == "Competent  +40%"
    assert dict(ranks.rows(s))["Trade"] == "Broker  +7%"


def test_frontier_progress_is_read_from_where_it_is_stored():
    s = MonitorState()
    s.journal_ranks = {"combat": 1}
    s.capi_ranks = {"combat": 3}
    s.capi_progress = {"combat": 12}
    assert dict(ranks.rows(s))["Combat"] == "Competent  +12%"


# ── The plot forms ────────────────────────────────────────────────────────────

class FakeSpansh:
    def __init__(self):
        self.calls = []

    def plot_fsd_route(self, src, dst, rng, neutrons):
        self.calls.append(("fsd", src, dst, rng, neutrons))
        return {"system_jumps": [{"system": src, "jumps": 0},
                                 {"system": dst, "jumps": 3, "distance_jumped": 90}]}

    def plot_neutron_route(self, src, dst, rng, eff):
        self.calls.append(("neutron", src, dst, rng, eff))
        return {}

    def search(self, q):
        return [{"name": "Jameson Memorial", "system": "Shinrarta Dezhra"},
                {"name": "Jameson Base", "system": "Elsewhere"}]

    def search_home(self, q):
        return [{"name": "Sol", "system": "Sol", "is_station": False, "star_pos": [0, 0, 0]}]

    def set_target(self, name, system, _record=None):
        self.target = (name, system)

    def clear_target(self):
        self.cleared = True


class FakeNav:
    def __init__(self):
        self.stored, self.follow = [], False

    def navigation_tool_tabs(self):
        return plot_tools.tabs()

    def store_route(self, result, kind):
        self.stored.append(kind)

    def toggle_follow(self):
        self.follow = not self.follow
        return self.follow

    def copy_next(self):
        return True, "Copied Sol"

    def clear_route(self):
        return "Route cleared."


class FakeCommander:
    home = None

    def set_home_location(self, name, system, pos):
        self.home = (name, system, pos)

    def get_home_location(self):
        return {"name": self.home[0], "system": self.home[1]} if self.home else None

    def home_distance_ly(self, pos):
        return None


def _nav_core(**state):
    return _core({"spansh": FakeSpansh(), "navigation": FakeNav(),
                  "commander": FakeCommander()}, pilot_system="Sol", **state)


def test_the_plot_forms_are_described_for_a_device():
    core = _nav_core()
    by_id = {t.id: tooltab.describe(t, core) for t in tooltab.tabs(core)}
    assert list(by_id)[:3] == ["fsd", "neutron", "carrier"]
    assert by_id["fsd"]["values"]["from"] == "Sol"
    assert [f["key"] for f in by_id["fsd"]["fields"]][:2] == ["from", "to"]
    assert "No carrier on file" in by_id["carrier"]["intro"]


def test_a_plot_from_anywhere_becomes_the_followed_route():
    core = _nav_core()
    fsd = next(t for t in tooltab.tabs(core) if t.id == "fsd")
    msg = tooltab.result_message(fsd, 9, tooltab.run(fsd, core, {"to": "Colonia", "range": "50"}))
    assert msg["tone"] == "good" and msg["route"] is True and "3 jumps" in msg["status"]
    assert core._plugins["navigation"].stored == ["fsd"]
    assert core._plugins["spansh"].calls[0] == ("fsd", "Sol", "Colonia", 50.0, False)


def test_a_plot_without_a_destination_says_so():
    core = _nav_core()
    fsd = next(t for t in tooltab.tabs(core) if t.id == "fsd")
    msg = tooltab.result_message(fsd, 1, tooltab.run(fsd, core, {"range": "50"}))
    assert msg["tone"] == "crit" and "destination" in msg["status"]
    assert msg["route"] is False


def test_an_empty_answer_is_a_warning_not_a_route():
    core = _nav_core()
    neu = next(t for t in tooltab.tabs(core) if t.id == "neutron")
    msg = tooltab.result_message(neu, 1, tooltab.run(neu, core, {"to": "Colonia", "range": "50"}))
    assert msg["tone"] == "warn" and msg["route"] is False


# ── The buttons ───────────────────────────────────────────────────────────────

def test_buttons_ride_with_their_panels():
    p = _panels(_nav_core())
    assert [a["id"] for a in p["navigation.route"]["actions"]] == ["follow", "copy-next", "clear"]
    assert [a["id"] for a in p["cargo"]["actions"]] == ["target", "galavg"]
    assert p["cargo"]["footer"] == "No target set"
    assert p["commander.info"]["actions"][0]["id"] == "home"
    assert "actions" not in p["ship.modules"]


def test_no_buttons_without_their_components():
    p = _panels(_core())
    assert not any("actions" in x for x in p.values())


def test_follow_copy_and_clear():
    core = _nav_core()
    assert panel_actions.run(core, "navigation.route", "follow")["ok"]
    assert core._plugins["navigation"].follow is True
    assert panel_actions.run(core, "navigation.route", "copy-next") == {"ok": True, "message": "Copied Sol"}
    assert panel_actions.run(core, "navigation.route", "clear")["message"] == "Route cleared."
    assert panel_actions.run(core, "navigation.route", "nope")["ok"] is False


def test_set_target_is_a_search_then_a_choice():
    core = _nav_core()
    first = panel_actions.run(core, "cargo", "target", device="d1", text="Jameson")
    assert [c["label"] for c in first["choices"]][0].startswith("Jameson Memorial")
    # Another device's choice does not pick from this device's search.
    assert panel_actions.run(core, "cargo", "target", device="d2", choice=0)["ok"] is False
    done = panel_actions.run(core, "cargo", "target", device="d1", choice=0)
    assert done["ok"] and core._plugins["spansh"].target == ("Jameson Memorial", "Shinrarta Dezhra")
    # A choice is used once.
    assert panel_actions.run(core, "cargo", "target", device="d1", choice=0)["ok"] is False


def test_a_search_needs_two_letters():
    assert panel_actions.run(_nav_core(), "cargo", "target", text="J")["ok"] is False


def test_set_home_and_galactic_average():
    core = _nav_core()
    panel_actions.run(core, "commander.info", "home", device="d", text="Sol")
    assert panel_actions.run(core, "commander.info", "home", device="d", choice=0)["ok"]
    assert core._plugins["commander"].home == ("Sol", "Sol", [0, 0, 0])
    info = _panels(core)["commander.info"]
    # The Home System row is the control: no button, no footer line.
    home = next(r for r in info["rows"] if r["label"] == "Home System")
    assert home["action"] == "home" and home["value"].startswith("Sol")
    assert info["actions"] == [{"id": "home", "label": "Set Home System",
                                "input": "System or station name…", "row": True}]
    assert not info.get("footer")
    assert panel_actions.run(core, "cargo", "galavg")["ok"]
    assert core.state.cargo_price_galactic is True and core._plugins["spansh"].cleared


def test_every_components_forms_can_be_sent_to_a_device():
    """Each loaded component's forms describe for a device, and a check's
    default is its default. Discoveries and Services passed theirs where the
    choices go, so neither form could be described, and the header carried no
    forms at all."""
    import importlib
    import inspect
    import pkgutil

    import components
    core = _core()
    found = {}
    for info in pkgutil.iter_modules(components.__path__):
        mod = importlib.import_module(f"components.{info.name}")
        for _, cls in inspect.getmembers(mod, inspect.isclass):
            if cls.__module__ == mod.__name__ and callable(getattr(cls, "navigation_tool_tabs", None)):
                for t in cls.__new__(cls).navigation_tool_tabs():
                    found[t.id] = tooltab.describe(t, core)
    assert {"fsd", "neutron", "carrier", "survey", "nearby", "services", "discoveries"} <= set(found)
    carriers = next(f for f in found["services"]["fields"] if f["key"] == "carriers")
    assert carriers["default"] is True


def test_a_checks_default_cannot_be_given_as_its_choices():
    import pytest
    with pytest.raises(TypeError):
        tooltab.Field("x", "X", "check", True)


# ── The squadron, from the journal ────────────────────────────────────────────

def test_the_squadron_comes_from_the_journal_without_frontier():
    from core import edcars, squadron
    s = MonitorState()
    s.pilot_name = "Merrick Calbruin"
    squadron.apply(s, {"event": "SquadronStartup", "SquadronID": 110393,
                       "SquadronName": "MINING AND LOGISTICS LTD", "CurrentRank": 0,
                       "CurrentRankName": "Executive Director"})
    assert (s.pilot_squadron_name, s.pilot_squadron_rank) == ("MINING AND LOGISTICS LTD",
                                                            "Executive Director")
    assert edcars.title_text(s) == "CMDR MERRICK CALBRUIN // MINING AND LOGISTICS LTD"
    # Frontier's tag is kept while the name matches, whatever its case.
    s.pilot_squadron_tag = "MALL"
    squadron.apply(s, {"event": "SquadronStartup", "SquadronName": "Mining and Logistics Ltd",
                       "CurrentRankName": "$SQUADRON_DEFAULTRANKNAME_RANK0;"})
    assert s.pilot_squadron_tag == "MALL" and s.pilot_squadron_rank == "Executive Director"
    squadron.apply(s, {"event": "JoinedSquadron", "SquadronName": "Other Wing"})
    assert (s.pilot_squadron_name, s.pilot_squadron_tag) == ("Other Wing", "")
    squadron.apply(s, {"event": "LeftSquadron", "SquadronName": "Other Wing"})
    assert edcars.title_text(s) == "CMDR MERRICK CALBRUIN"


# ── Markup never reaches a device ─────────────────────────────────────────────

def test_compound_rich_tags_are_stripped_and_keep_their_tone():
    """EDAM showed "[bold cyan]HIP 73225 (colonization ship)[/bold cyan]" as a
    colonization site's heading: only one-word tags were recognized."""
    assert tooltab.plain("[bold cyan]HIP 73225[/bold cyan]  0%") == ("HIP 73225  0%", "accent")
    assert tooltab.plain("[bold yellow]low[/bold yellow]") == ("low", "warn")
    assert tooltab.plain("[dim]x[/]") == ("x", "dim")
    assert tooltab.plain("list[int] stays")[0] == "list[int] stays"


def test_the_colonisation_window_reaches_edam_without_markup():
    site = {"market_id": 1, "system": "HIP 73225", "station": "HIP 73225 (colonization ship)",
            "progress": 0.0, "resources": {"steel": {"name": "Steel", "required": 6660,
                                                      "provided": 0}}}
    core = _core(colonisation_sites=[site], colonisation_docked=True,
                 _colonisation_current_market_id=1,
                 cargo_items={"steel": {"count": 10}})
    panel = _panels(core)["colonisation.colonisation"]

    def strings(o):
        if isinstance(o, dict):
            for v in o.values():
                yield from strings(v)
        elif isinstance(o, list):
            for v in o:
                yield from strings(v)
        elif isinstance(o, str):
            yield o
    texts = list(strings(panel))
    assert any("HIP 73225 (colonization ship)" in t for t in texts)
    assert not [t for t in texts if "[bold" in t or "[/" in t or "[yellow]" in t]
