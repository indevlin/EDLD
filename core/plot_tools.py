"""core/plot_tools.py — the FSD, Neutron and Carrier plot forms, described once.

FSD      Spansh's exact plotter, with the ship's own drive and fuel, or an
         EDSM search where no Loadout has been read (components/spansh.py).
Neutron  Neutron-boosted, at the drive's own supercharge.
Carrier  Fleet-carrier jumps with tritium planning.
"""
from __future__ import annotations

from core import route_view as RV
from core.tooltab import Field, ToolResult, ToolTab, number


def _here(core) -> dict:
    s = core.state
    plan = RV.plan_range(s)
    return {"from": str(getattr(s, "pilot_system", "") or ""),
            "range": f"{plan:.2f}" if plan else ""}


def _range_intro(core) -> str:
    return RV.range_hint(core.state)


def _ship_route(core, v: dict, neutron: bool) -> ToolResult:
    src = (v.get("from") or str(getattr(core.state, "pilot_system", "") or "")).strip()
    dst = (v.get("to") or "").strip()
    plan = RV.plan_range(core.state)
    if not src or not dst:
        raise ValueError("Source, destination, and range required.")
    rng = number(v, "range", 0.01, 1000, round(plan, 2) if plan else None, name="Range")
    try:
        if neutron:
            eff = number(v, "eff", 1, 100, 60, integer=True, name="Efficiency")
            result = core.plugin_call("spansh", "plot_neutron_route", src, dst, rng, eff)
        else:
            result = core.plugin_call("spansh", "plot_fsd_route", src, dst, rng,
                                      bool(v.get("neutrons")))
    except ValueError:
        raise
    except Exception as exc:
        result = {"_error": f"{type(exc).__name__}: {exc}"}
    if not result:
        return ToolResult("[yellow]No route returned (timeout or error).[/yellow]")
    if isinstance(result, dict) and result.get("_error"):
        return ToolResult(f"[red]Plot failed: {result['_error']}[/red]")
    if not (result.get("system_jumps") or result.get("jumps")):
        return ToolResult("[yellow]No jumps in response.[/yellow]")
    summary, wp_rows = RV.plot_summary(result, neutron)
    rows = [("hdr", "Waypoints")] + [("kv", label, value) for label, value in wp_rows]
    return ToolResult(f"[green]{summary}[/green]", rows,
                      route=(result, "neutron" if neutron else "fsd"))


def _carrier_fill(core) -> dict:
    c = getattr(core.state, "assets_carrier", None) or {}
    if not c:
        return {}
    out = {"used": str(int(c.get("cargo_used") or 0)), "fuel": str(int(c.get("fuel") or 0))}
    if c.get("system") and c.get("system") != "—":
        out["from"] = str(c["system"])
    return out


def _carrier_intro(core) -> str:
    c = getattr(core.state, "assets_carrier", None)
    if not c:
        return "[dim]No carrier on file — enter values by hand.[/dim]"
    return (f"{c.get('name') or 'Carrier'} · {c.get('system') or '—'} · "
            f"{c.get('fuel') or 0} t tritium · {c.get('cargo_used') or 0}/"
            f"{c.get('cargo_total') or 25000} t")


def _carrier_route(core, v: dict) -> ToolResult:
    from core.ui_helpers import carrier_route_rows, carrier_route_summary
    c = getattr(core.state, "assets_carrier", None) or {}
    src = (v.get("from") or str(c.get("system") or "")).strip()
    dst = (v.get("to") or "").strip()
    if not src or not dst:
        raise ValueError("Source and destination required.")
    used = number(v, "used", 0, 1e6, int(c.get("cargo_used") or 0), integer=True, name="Cargo")
    fuel = number(v, "fuel", 0, 1000, int(c.get("fuel") or 0), integer=True, name="Tritium")
    total = int(c.get("cargo_total") or 25000) or 25000
    try:
        result = core.plugin_call("spansh", "plot_carrier_route", src, dst, used, total, fuel)
    except Exception as exc:
        result = {"_error": f"{type(exc).__name__}: {exc}"}
    if not result:
        return ToolResult("[yellow]No route returned (timeout or error).[/yellow]")
    if isinstance(result, dict) and result.get("_error"):
        return ToolResult(f"[red]Plot failed: {result['_error']}[/red]")
    if not (result.get("jumps") or []):
        return ToolResult("[yellow]No jumps in response.[/yellow]")
    s = carrier_route_summary(result)
    rows: list[tuple] = [("hdr", "Route")]
    if s["restocks"]:
        rows.append(("text", f"[yellow]{s['restocks']} restock stop(s)[/yellow] · "
                             f"{s['tritium_sources']} systems with tritium available"))
    rows += [("kv", label, value) for label, value in carrier_route_rows(result)]
    return ToolResult(f"[green]{s['jumps']} jumps · {s['distance_ly']:,.0f} ly · "
                      f"{s['fuel_total']:,} t tritium[/green]", rows,
                      route=(result, "carrier"))


def tabs() -> list[ToolTab]:
    return [
        ToolTab(
            id="fsd", title="FSD", button="Plot FSD", order=10,
            fields=(
                Field("from", "From (current system)", system=True),
                Field("to", "To (e.g. Colonia)", system=True),
                Field("range", "Jump range, ly — filled from your ship"),
                Field("neutrons", "Use neutron and white-dwarf boosts", "check"),
            ),
            run=lambda core, v: _ship_route(core, v, neutron=False),
            autofill=_here, intro=_range_intro),
        ToolTab(
            id="neutron", title="Neutron", button="Plot Neutron", order=20,
            fields=(
                Field("from", "From (current system)", system=True),
                Field("to", "To (e.g. Beagle Point)", system=True),
                Field("range", "Jump range, ly — filled from your ship"),
                Field("eff", "Efficiency 1–100", default="60"),
            ),
            run=lambda core, v: _ship_route(core, v, neutron=True),
            autofill=_here, intro=_range_intro),
        ToolTab(
            id="carrier", title="Carrier", button="Plot Carrier", order=30,
            fields=(
                Field("from", "From (carrier's system)", system=True),
                Field("to", "To (e.g. Colonia)", system=True),
                Field("used", "Cargo used, t"),
                Field("fuel", "Tritium in tank, t"),
            ),
            run=_carrier_route, autofill=_carrier_fill, intro=_carrier_intro),
    ]
