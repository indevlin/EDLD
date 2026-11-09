# EDLD Roadmap

Last updated: 20261108

---

## Active

**EDAM on Google Play** — EDAM is published by Indevlin, LLC as
`com.indevlin.edam`, with this release: AdMob's banner, the consent message
where the law asks for one, and a one-time purchase that removes the ads.

---

## Recently shipped

**The Mining window and ring hotspots** (20261108) — Ring Hotspots, read from
every ring the Detailed Surface Scanner has mapped, and Surface Sites, each a
filterable table edited in place, in a window of its own and a section of
EDCARS and EDAM. Hotspots are shared on the survey sheet, whose layout v4
renames Deposits to Surface Sites. See [SURFACE_SURVEY.md](SURFACE_SURVEY.md).

**Every mission on the board** (20261108) — the Missions tab shows each kind of
mission in a table of its own, rebuilt from the journals at every login, with
the ore a mining mission needs that is already in the hold or on your own
carrier.

**Uploads when things happen** (20261108) — EDSM, EDAstro and Inara receive
events at every dock and undock, jump, ship or vehicle change, death and
loadout change.

**Fast start-up** (20261105) — the journal index, the career scan's
checkpoint, the window opening before the history is read, and the last
session shown while the journals load: an everyday start in about two seconds
instead of nine, no longer growing with the history ([Start-up](STARTUP.md)).

**EDCARS consoles** (20261105) — EDCARS drawn as ORDER, an Imperial fleet
console; REBEL, a Rebel ops board; or ROGUE, an independent freighter's
cockpit, beside its own dress, each with a theme of the same name, on the
desktop and on EDAM. Options and every dialog opened from EDCARS wear the
console too. See [EDCARS.md](EDCARS.md#consoles).

**Options in a column** (20261105) — every page of Options in one column down
the left, in the desktop window and the terminal, the components' pages in
alphabetical order. A row of sixteen tabs no longer fitted either.

**Server mode and EDAM** (20261102) — `edld -s`, or Options → Server, serves
the dashboard to EDAM, the Android companion app published by Indevlin, LLC.
In landscape it draws EDCARS as the desktop does, from the one model of each
window the desktop and the terminal dashboard draw, with the Navigation forms
and the buttons under each window run by EDLD. Pairing by QR code, TLS 1.3
with keys pinned on both sides, NAT-PMP/UPnP and DuckDNS for reaching home,
`--headless` and an EDLD-server download for running it as a service. See
[SERVER.md](SERVER.md).

**EDCARS** (20261102) — the desktop window drawn as a console, and the default
interface: a header band, a rail of seven sections, one to three windows
framed in each. See [EDCARS.md](EDCARS.md).

**The Helm panel** (20261102) — the game's controls and EDLD's automation as
buttons, grouped by what they are for: a section of EDCARS, a strip along the
foot of the Dashboard on the desktop and in the terminal, and a section or a
page on EDAM. See [AUTOMATION.md](AUTOMATION.md#the-helm-panel).

**Routes and surveys** (20261102) — routes plotted with the ship's own drive
and fuel, checked as they are followed; Road to Riches, Exomastery and trade
survey routes; systems nearby and the nearest service; unsold discoveries
watched; callouts with chimes for firsts, exobiology and mining.

**Automation** (20261102) — auto honk and the next stop after a supercharge,
through the commander's own bindings, on their own or from the Helm panel.
See [AUTOMATION.md](AUTOMATION.md).

**Commander dossier** (20261102) — a self-contained web page and Markdown files
per commander, kept current from the journals: the fleet with every ship's
fitting, stored ships included, stored modules, engineering, the fleet carrier,
ring hotspots by refinement rate, surface deposits and on-foot kit. Journals are
read incrementally and what is learned is kept, so it outlives old journals.
See [DOSSIER.md](DOSSIER.md).

**Overlay visibility tweaks** (20261102) — five independent switches that keep
the streamer overlay readable over any scene in any theme, custom themes
included. See [STREAMER_STATS_OVERLAY.md](STREAMER_STATS_OVERLAY.md#visibility-tweaks).

**Unknown Credits** (20261102) — money the game pays without a journal event,
PowerPlay care packages among it, found by reconciling the balance and counted
as income. See [CONFIGURATION.md](CONFIGURATION.md#unknown-credits).

**Cargo manifest accuracy** (20260914) — the hold is now followed from
`Cargo.json` rather than inferred from journal events, journals are selected by
filename rather than modification time, and the SRV's hold is restored at
startup. Each of these was a case of the manifest disagreeing with the game;
see the changelog for what each one looked like from the outside.

**Sell table and commodity catalog** (20260912) — `Ctrl+S` in either
interface opens what the quoted market pays for each commodity, most valuable
first, on a Mineable tab with All Items behind it. The same table is written
beside the catalog as Markdown and HTML on every market read.

Two decisions in there are worth keeping if this is extended. Carrier markets
are excluded everywhere the table is concerned — they are player-run and
mobile, and the test is a substring match on the station type rather than a
list, because Frontier writes `FleetCarrier` and Spansh writes `Drake-Class
Carrier`. And a commodity with no galactic average is dropped from the table
rather than shown: stations quote a sell price for carrier-only goods that no
NPC will honor, which otherwise put a Titan Maw tissue sample near the top of
almost every market in the bubble.

What can be mined lives in `data/mining.py` and is mostly category rather than
a list — everything in Minerals, plus ten named Metals and four Chemicals — so
a mineral added in a future update needs no edit.

**Cross-platform desktop interface** (20260811) — a PySide6 window rendering
the same dashboard as the terminal interface, with prebuilt binaries for Linux,
Windows and macOS. This is what prompted the rename from ED Linux Dash to ED
Live Dashboard. See the changelog for the full entry.

Worth noting for anyone picking up work here: both front ends are rendered from
one layout model and one set of components, so a new dashboard window should be
added to both rather than to whichever is convenient. `core/summary_model.py`
and `core/palette.py` exist for the same reason.

**Window consolidation** (20260905–06) — windows that duplicated each other's
rows were folded into the window they belonged with, and the size classes cut
from three to two. The set is now seven windows in seven slots, so everything
is on screen at once and rearranging swaps two windows rather than hiding one.

Assets became tabs on Commander, Exobiology nested under the body it describes
in Exploration, Cargo and Engineering became tabs on Ship, missions and
colonization became the Objectives window, Session became Career's first tab,
and Crew / SLF merged with Alerts. Hull, shields and fuel live on Commander's
Info tab, which is the default view and therefore the one place they cost
nothing to reach.

No data was dropped. A `windows.json` from before this release describes a
window set and a slot grid that no longer exist, so it is replaced with the
current defaults and rewritten once, on the next launch.

**Spansh fleet-carrier routing** (20260905) — carrier routing works. The endpoint and parameter names had been correct all
along; the two list-shaped parameters were being sent as JSON strings where
Spansh's form parser expects repeated bare keys — jQuery's `traditional`
serialization — so a job was accepted with `HTTP 202` and then had no
destination to route to. Routes come back with full per-jump fuel planning:
tritium burned, tank level on arrival, restock stops and amounts, and which
systems have a market or a pristine icy ring to mine.

---

## Deferred

### Exploration / Exobiology module split
Exploration and Exobiology now render as one window — the biology for a body
sits nested under that body's exploration row — but their shared body-data
layer (`core/explo_*`) still mixes Exploration logic
(scan / mapping / discovery) with Exobiology logic (flora status, waypoints,
clonal distance, one-sample-in-progress reset) as a legacy of their shared
origin. A future refactor will split these into distinct modules so the two
concerns are cleanly separated. The tables are interlinked via shared
systems/bodies, so the approach is a module split rather than a separate
database. Deferred — no target release. Background in
[EXPLORATION_EXOBIOLOGY_PLAN.md](EXPLORATION_EXOBIOLOGY_PLAN.md).

