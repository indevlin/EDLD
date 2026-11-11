"""core/windows/wire.py — the windows, as panels for a paired EDAM device.

    group        panels                                     window
    vessel       ship (the vessel's name), cargo            Ship
    ship         ship.modules                               Ship
    engineering  engineering.fitting, .materials (pages)    Engineering
    commander    commander.info, .ranks, .wallet,           Commander
                 .ships, .stored-modules, .carrier,
                 .squadron-carrier
    crew         crew.crew                                  Crew / SLF
    exploration  exploration.system                         Exploration
    navigation   navigation.route — and the forms, sent     Navigation
                 in the header as "tools"
    missions     missions.missions                          Objectives
    colonization colonisation.colonisation                  Objectives
    mining       mining.hotspots, mining.sites (filter)     Mining
    session      session.session                            Career / Session
    career       career.summary, .combat, … .powerplay      Career / Session
"""
from __future__ import annotations

from core.windows import Tab, wire_rows


def panel(pid: str, title: str, group: str, tab: Tab | None = None, order: int = 100,
          rows: list | None = None, filter: bool = False) -> dict:
    p = {"id": pid, "title": title, "group": group, "order": order,
         "rows": wire_rows(tab.rows if tab is not None else rows or [])}
    if filter:
        p["filter"] = True            # the device offers a text filter over the rows
    if tab is not None and tab.pages:
        p["pages"] = [{"id": pg.id, "title": pg.title, "rows": wire_rows(pg.rows)}
                      for pg in tab.pages]
    if tab is not None and tab.heading:
        p["heading"] = tab.heading
    return p


def _safe(fault, name, fn, *a):
    try:
        return fn(*a)
    except Exception as exc:
        fault(name, exc)
        return None


def panels(core, fault=lambda name, exc: None) -> list[dict]:
    """Every window's panels, in the desktop's tab order."""
    from core import route_view as RV
    from core.windows import (career, commander, crew, engineering, exploration, mining,
                              objectives, ship)
    out: list[dict] = []

    t = _safe(fault, "cargo", ship.cargo, core)
    if t is not None:
        out.append(panel("cargo", t.title, "vessel", t, 30))
    t = _safe(fault, "ship", ship.modules, core)
    if t is not None:
        out.append(panel(f"ship.{t.id}", t.title, "ship", t, 1000))

    order = 1250
    for fn in (engineering.fitting_tab, engineering.materials):
        t = _safe(fault, "engineering", fn, core)
        if t is not None:
            out.append(panel(f"engineering.{t.id}", t.title, "engineering", t, order))
        order += 1

    order = 1100
    tabs = (_safe(fault, "commander", commander.identity_tabs, core) or []) + \
        (_safe(fault, "fleet", commander.fleet_tabs, core) or [])
    for t in tabs:
        out.append(panel(f"commander.{t.id}", t.title, "commander", t, order))
        order += 1

    t = _safe(fault, "crew", crew.tab, core)
    if t is not None:
        out.append(panel("crew.crew", "Crew", "crew", t, 1200))

    v = _safe(fault, "exploration", exploration.view, core)
    if v is not None:
        from core.windows import R
        rows = ([R.text(v["summary"], "dim")] if v["summary"] else []) + v["rows"]
        out.append(panel("exploration.system", v["title"], "exploration", rows=rows, order=1300))

    rv = _safe(fault, "route", RV.route_view, core)
    if rv is not None:
        out.append(panel("navigation.route", "Route", "navigation",
                         rows=RV.route_rows(rv), order=1400))

    t = _safe(fault, "missions", objectives.missions, core)
    if t is not None:
        out.append(panel("missions.missions", t.title, "missions", t, 1500))
    t = _safe(fault, "colonisation", objectives.colonisation, core)
    if t is not None:
        out.append(panel("colonisation.colonisation", t.title, "colonisation", t, 1600))
    for order, fn in ((1700, mining.hotspots), (1701, mining.surface_sites)):
        t = _safe(fault, "mining", fn, core, "", False)
        if t is not None:
            out.append(panel(f"mining.{t.id}", t.title, "mining", t, order, filter=True))

    order = 300
    for t in _safe(fault, "career", career.tabs, core) or []:
        group = "session" if t.id == "session" else "career"
        out.append(panel(f"{group}.{t.id}", t.title, group, t, order))
        order += 1

    # The buttons under a window's tabs, and the line beside them
    # (core/panel_actions.py).
    from core import panel_actions
    for p in out:
        acts = _safe(fault, "actions", panel_actions.actions, core, p["id"])
        if acts:
            p["actions"] = acts
            line = _safe(fault, "footer", panel_actions.footer, core, p["id"])
            if line:
                from core.tooltab import plain
                p["footer"] = plain(line)[0]
    return out
