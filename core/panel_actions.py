"""core/panel_actions.py — the buttons under a window's tabs, for EDAM.

    navigation.route   Follow: on/off · Copy Next · Clear Route
    cargo              Set Target · Gal. Avg
    commander.info     Set Home System (row: Home System)
    colonisation.colonisation  clear:<market id> (row: Stop tracking)

Set Target and Set Home take a search: the first press sends the text and
gets back what matched, the second sends the one chosen.
"""
from __future__ import annotations

import threading

#: The last search each device ran, so its choice can be applied:
#: (device id, panel, action) → the matches.
_SEARCHES: dict[tuple, list] = {}
_LOCK = threading.Lock()


def actions(core, panel_id: str) -> list[dict]:
    """The buttons a panel carries: {"id", "label", "input"?}. ``input`` is
    the prompt for a search."""
    s = getattr(core, "state", None)
    plugins = getattr(core, "_plugins", None) or {}
    if panel_id == "navigation.route" and plugins.get("navigation") is not None:
        on = bool(getattr(s, "nav_follow_enabled", False))
        return [{"id": "follow", "label": f"Follow: {'ON' if on else 'off'}"},
                {"id": "copy-next", "label": "Copy Next"},
                {"id": "clear", "label": "Clear Route"}]
    if panel_id == "cargo" and plugins.get("spansh") is not None:
        return [{"id": "target", "label": "Set Target", "input": "Station name…"},
                {"id": "galavg", "label": "Gal. Avg"}]
    if panel_id == "commander.info" and plugins.get("spansh") is not None \
            and plugins.get("commander") is not None:
        return [{"id": "home", "label": "Set Home System", "input": "System or station name…",
                 "row": True}]
    if panel_id == "colonisation.colonisation" and plugins.get("colonisation") is not None:
        return [{"id": f"clear:{site.get('market_id')}",
                 "label": f"Clear {site.get('station') or site.get('system') or 'site'}",
                 "row": True}
                for site in getattr(s, "colonisation_sites", []) or []
                if site.get("market_id") is not None]
    return []


def footer(core, panel_id: str) -> str:
    """The line the desktop shows beside a panel's buttons."""
    s = getattr(core, "state", None)
    if panel_id == "navigation.route":
        return str(getattr(s, "nav_follow_status", "") or "No route")
    if panel_id == "cargo":
        tgt = getattr(s, "cargo_target_market_name", "") or ""
        return f"→ {tgt}" if tgt else "No target set"
    return ""


def run(core, panel_id: str, action_id: str, *, device: str = "",
        text: str | None = None, choice: int | None = None) -> dict:
    """Press a button. Returns {"ok", "message"} and, for the first step of
    a search, {"choices": [{"id", "label"}]}."""
    if not any(a["id"] == action_id for a in actions(core, panel_id)):
        return {"ok": False, "message": "Not available."}
    plugins = core._plugins
    if panel_id == "colonisation.colonisation" and action_id.startswith("clear:"):
        ok = plugins["colonisation"].clear_site(int(action_id.split(":", 1)[1]))
        return {"ok": ok, "message": "Site cleared." if ok else "Not tracked."}
    nav = plugins.get("navigation")
    if panel_id == "navigation.route":
        if action_id == "follow":
            on = nav.toggle_follow()
            return {"ok": True, "message": "Following route — next system copies on arrival."
                    if on else "Follow off."}
        if action_id == "copy-next":
            ok, msg = nav.copy_next()
            return {"ok": ok, "message": msg}
        return {"ok": True, "message": nav.clear_route()}
    spansh = plugins.get("spansh")
    if panel_id == "cargo" and action_id == "galavg":
        core.state.cargo_price_galactic = True
        spansh.clear_target()
        return {"ok": True, "message": "Prices at the galactic average."}
    key = (device, panel_id, action_id)
    if choice is None:
        query = (text or "").strip()
        if len(query) < 2:
            return {"ok": False, "message": "Type at least two letters."}
        found = (spansh.search(query) if action_id == "target"
                 else spansh.search_home(query)) or []
        found = list(found)[:20]
        with _LOCK:
            _SEARCHES[key] = found
        if not found:
            return {"ok": False, "message": f"Nothing found for {query!r}."}
        return {"ok": True, "message": "", "choices": [
            {"id": i, "label": _choice_label(action_id, r)} for i, r in enumerate(found)]}
    with _LOCK:
        found = _SEARCHES.pop(key, [])
    if not 0 <= int(choice) < len(found):
        return {"ok": False, "message": "That search has expired — search again."}
    r = found[int(choice)]
    if action_id == "target":
        spansh.set_target(r.get("name", ""), r.get("system", ""), _record=r.get("_rec") or r)
        return {"ok": True, "message": f"Target: {r.get('name', '')}"}
    plugins["commander"].set_home_location(r.get("name", ""), r.get("system", ""),
                                           r.get("star_pos"))
    return {"ok": True, "message": f"Home: {r.get('name', '')}"}


def _choice_label(action_id: str, r: dict) -> str:
    if action_id == "target":
        return f"{r.get('name', '')}  {r.get('system', '')}".strip()
    station = r.get("is_station")
    return f"{'🚉' if station else '⭐'} {r.get('name', '')}" + \
        (f"  {r.get('system', '')}" if station else "")
