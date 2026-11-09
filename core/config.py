"""core/config.py — Configuration loading, defaults, profile resolution,
                 and hot-reload.

Depends only on core.state (for EDLD_DATA_DIR).
"""

import sys
import re
import tomllib
from pathlib import Path

from core.state import EDLD_DATA_DIR


# ── Minimal terminal color for pre-emit warnings ────────────────────────────
# emit.py imports config, so we can't import Terminal from there.
# Only _WARNING is needed here; full Terminal lives in core.emit.

class _T:
    WARN = "\x1b[38;5;215m"
    END  = "\x1b[0m"

_WARNING = f"{_T.WARN}Warning:{_T.END}"


import re

# ── Canonical TOML format ─────────────────────────────────────────────────────

# Top-level config sections that are written as flat [Section] tables.
# Anything not in this set is treated as a profile and written under a single
# [ProfileName] header with dotted sub-keys (Settings.Key = ..., UI.Mode = ...).
# A [ProfileName.SubSection] sub-table header is NEVER written — that is the
# old format that this migration is designed to eliminate.
STANDARD_SECTIONS: frozenset[str] = frozenset({
    "Settings", "Discord", "LogLevels", "UI",
    "EDDN", "EDSM", "EDAstro", "Inara", "CAPI", "SurfaceSurvey", "Overlay", "OverlayPanels",
    "Radio", "Server", "Dossier",
})

# Matches any TOML section header that indicates old-format content:
#   [GUI]               — old interface section name
#   [ProfileName.Sub]   — old profile sub-table style
_NEEDS_MIGRATION = re.compile(r'^\[(?:GUI|\w+\.\w+)\]', re.MULTILINE)


def _scalar(v) -> str:
    """Format a Python value as a TOML literal."""
    if isinstance(v, bool):  return "true" if v else "false"
    if isinstance(v, int):   return str(v)
    if isinstance(v, float): return str(v)
    escaped = str(v).replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def config_to_toml(d: dict) -> str:
    """Serialize a config dict to canonical TOML.

    Rules:
      • Standard sections (Settings, Discord, UI, LogLevels, EDDN, EDSM,
        EDAstro, Inara, CAPI) are written as flat [Section] tables.
      • Profile sections (EDP1, REMOTE, anything else) are written as a
        single [ProfileName] table whose sub-section keys use dotted notation:
            [EDP1]
            Settings.JournalFolder = "..."
            UI.Mode = "textual"
        The old [EDP1.Settings] / [EDP1.UI] sub-table style is NEVER produced.
    """
    lines: list[str] = []

    # ── Top-level bare scalars (rare) ─────────────────────────────────────────
    for k, v in d.items():
        if not isinstance(v, dict):
            lines.append(f"{k} = {_scalar(v)}")

    # ── Standard flat sections ────────────────────────────────────────────────
    for section, val in d.items():
        if not isinstance(val, dict) or section not in STANDARD_SECTIONS:
            continue
        lines += ["", f"[{section}]"]
        for k, v in val.items():
            if not isinstance(v, dict):
                lines.append(f"{k} = {_scalar(v)}")

    # ── Profile sections — single header, dotted sub-keys ─────────────────────
    for section, val in d.items():
        if not isinstance(val, dict) or section in STANDARD_SECTIONS:
            continue
        lines += ["", f"[{section}]"]
        # Any root-level scalar keys within the profile, written before dotted sub-keys
        for k, v in val.items():
            if not isinstance(v, dict):
                lines.append(f"{k} = {_scalar(v)}")
        # Sub-section keys written as dotted pairs (never as [Profile.Sub] headers)
        for sub, sub_val in val.items():
            if not isinstance(sub_val, dict):
                continue
            for k, v in sub_val.items():
                if not isinstance(v, dict):
                    lines.append(f"{sub}.{k} = {_scalar(v)}")

    return "\n".join(lines) + "\n"


# ── Startup migration ─────────────────────────────────────────────────────────

def _apply_gui_to_ui(gui_dict: dict) -> dict:
    """Convert a [GUI] / profile GUI sub-dict to [UI] representation.

        Enabled = true   →  Mode = "textual"
        Enabled = false  →  Mode = "terminal"
        (absent)         →  Mode unchanged / not added
        All other keys   →  kept as-is (Theme, …)
    """
    src = dict(gui_dict)
    enabled = src.pop("Enabled", None)
    result: dict = {}
    if enabled is True:
        result["Mode"] = "textual"
    elif enabled is False:
        result["Mode"] = "terminal"
    result.update(src)
    return result


def _toml_scalar(value) -> str:
    """Render a default value as a TOML scalar."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    return '"' + str(value).replace('\\', '\\\\').replace('"', '\\"') + '"'


def backfill_config_defaults(config_path: Path) -> list[str]:
    """Add newly-introduced default keys to an existing config.toml.

    Every release that adds a setting leaves existing configs without it.

    The file is edited **in place, by line**, rather than reparsed and
    rewritten.  ``example.config.toml`` is a heavily commented reference that
    users copy and edit, and regenerating the file from parsed values would
    throw all of that away.  Insertions go at the end of the matching
    top-level section, keeping surrounding comments intact.

    Only *adds*, and only to top-level sections.

    Returns the ``Section.Key`` names added, for the caller to report.
    """
    try:
        config = load_config_file(config_path)
    except SystemExit:
        raise
    except Exception:
        return []

    wanted: dict[str, dict] = {
        "Settings":  {**CFG_DEFAULTS_SETTINGS, **CFG_DEFAULTS_EXTRA},
        "Discord":   CFG_DEFAULTS_DISCORD,
        "UI":        CFG_DEFAULTS_UI,
        "LogLevels": CFG_DEFAULTS_NOTIFY,
        "CAPI":      CFG_DEFAULTS_CAPI,
        "Radio":     CFG_DEFAULTS_RADIO,
        "Server":    CFG_DEFAULTS_SERVER,
    }
    # SessionMgmt's defaults are owned by the component that reads them;
    # imported late to keep core/ from depending on components/ at import time.
    try:
        from components.ksw import CFG_DEFAULTS as _SESSION_DEFAULTS
        wanted["SessionMgmt"] = _SESSION_DEFAULTS
    except Exception:
        pass
    try:
        from components.dossier import CFG_DEFAULTS as _DOSSIER_DEFAULTS
        wanted["Dossier"] = _DOSSIER_DEFAULTS
    except Exception:
        pass

    missing: dict[str, list[tuple[str, object]]] = {}
    for section, defaults in wanted.items():
        existing = config.get(section)
        if not isinstance(existing, dict):
            continue                      # section absent — do not invent it
        gaps = [(k, v) for k, v in defaults.items()
                if k not in existing and not (isinstance(v, str) and v == "")]
        if gaps:
            missing[section] = gaps
    if not missing:
        return []

    try:
        lines = config_path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []

    # Find where each top-level section's body ends, so insertions land inside
    # it rather than after a later section header.
    section_end: dict[str, int] = {}
    current: str | None = None
    for index, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            current = stripped[1:-1].strip()
            if current not in section_end:
                section_end[current] = index + 1
        elif current is not None and stripped and not stripped.startswith("#"):
            section_end[current] = index + 1

    added: list[str] = []
    # Insert from the bottom up so earlier indices stay valid.
    for section in sorted(missing, key=lambda s: section_end.get(s, 0), reverse=True):
        at = section_end.get(section)
        if at is None:
            continue
        block = ["", "# Added automatically — new in this release."]
        for key, value in missing[section]:
            block.append(f"{key} = {_toml_scalar(value)}")
            added.append(f"{section}.{key}")
        lines[at:at] = block

    try:
        config_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    except OSError as exc:
        print(f"{_WARNING} Could not add new config defaults: {exc}")
        return []
    return added


_SUBTABLE = re.compile(r'^\[\s*([A-Za-z0-9_-]+)((?:\.[A-Za-z0-9_-]+)+)\s*\]\s*(#.*)?$')
_HEADER = re.compile(r'^\[\s*([^\[\]]+?)\s*\]\s*(#.*)?$')
_KEYLINE = re.compile(r'^(\s*)([A-Za-z0-9_-]+)(\s*=.*)$')


def _collapse_subtables(raw: str) -> str | None:
    """``[Profile.Section]`` tables folded into ``[Profile]`` as dotted keys, by
    line, so every comment stays where it was.

    Returns the new text, or None when the result would not read back as
    exactly the same settings — the caller then leaves the file alone.
    """
    blocks: list[list] = [[None, None, []]]          # [name, header line, body]
    for line in raw.splitlines():
        st = line.strip()
        m = _HEADER.match(st) if st.startswith("[") and not st.startswith("[[") else None
        if m:
            blocks.append([m.group(1).strip(), line, []])
        else:
            blocks[-1][2].append(line)

    out: list[list] = []
    where: dict[str, int] = {}
    made: set[str] = set()
    for name, header, body in blocks:
        m = _SUBTABLE.match(header.strip()) if header else None
        if not m:
            if name in made:
                # The parent's own block, after a sub-table that made one for
                # it: one table may not be declared twice.
                out[where[name]][2].extend(body)
                continue
            out.append([name, header, list(body)])
            if name is not None:
                where.setdefault(name, len(out) - 1)
            continue
        parent, rest, note = m.group(1), m.group(2)[1:], m.group(3)
        moved = [f"# {note.lstrip('#').strip()}"] if note else []
        for line in body:
            k = _KEYLINE.match(line)
            moved.append(f"{k.group(1)}{rest}.{k.group(2)}{k.group(3)}" if k else line)
        if out and out[-1][0] == parent:
            out[-1][2].extend(moved)                 # straight after its parent
        elif parent in where:
            target = out[where[parent]][2]
            end = len(target)
            while end and (not target[end - 1].strip()
                           or target[end - 1].lstrip().startswith("#")):
                end -= 1
            target[end:end] = [""] + [x for x in moved if x.strip()]
        else:
            out.append([parent, f"[{parent}]", moved])
            where[parent] = len(out) - 1
            made.add(parent)
    text = "\n".join(line for _name, header, body in out
                     for line in ([header] if header else []) + body) + "\n"
    try:
        if tomllib.loads(text) != tomllib.loads(raw):
            return None
    except Exception:
        return None
    return text


def migrate_config_if_needed(config_path: Path) -> bool:
    """Detect old config formats and silently rewrite to canonical format.

    Handles all of:
      • [GUI] global section  →  [UI]  (Enabled= → Mode=)
      • [ProfileName.GUI] sub-table  →  ProfileName.UI.*  (dotted key)
      • ProfileName.GUI.Enabled = true in a profile block  →  UI.Mode = "textual"
      • [ProfileName.Section] sub-table headers  →  [ProfileName] + dotted keys

    Returns True if the file was rewritten, False if no migration was needed.

    MUST be called before load_config_file() in edld.py.
    """
    try:
        raw = config_path.read_text(encoding="utf-8")
    except Exception:
        return False

    if not _NEEDS_MIGRATION.search(raw):
        return False   # already canonical — nothing to do

    # Only [Profile.Section] tables: fold them in by line.
    if not re.search(r'^\[(?:\w+\.)?GUI\]', raw, re.MULTILINE):
        folded = _collapse_subtables(raw)
        if folded is None:
            print(f"{_WARNING} Config has [Profile.Section] tables EDLD could not fold "
                  f"into dotted keys; left as written: {config_path}")
            return False
        try:
            config_path.write_text(folded, encoding="utf-8")
            return True
        except Exception as e:
            print(f"{_WARNING} Config migration failed — file unchanged: {e}")
            return False

    # File needs migration: parse it, transform, rewrite
    try:
        with open(config_path, "rb") as _f:
            d = tomllib.load(_f)
    except Exception:
        return False   # parse errors handled by load_config_file later

    changed = False

    # 1. Global [GUI] → [UI]
    if "GUI" in d:
        existing_ui = dict(d.get("UI") or {})
        migrated = _apply_gui_to_ui(d.pop("GUI"))
        # Migrated values fill gaps; they never overwrite an explicit [UI] key
        for k, v in migrated.items():
            existing_ui.setdefault(k, v)
        d["UI"] = existing_ui
        changed = True

    # 2. Profile-level GUI sub-dicts
    for key, val in d.items():
        if not isinstance(val, dict) or key in STANDARD_SECTIONS:
            continue
        if "GUI" in val:
            existing_ui = dict(val.get("UI") or {})
            migrated = _apply_gui_to_ui(val.pop("GUI"))
            for k, v in migrated.items():
                existing_ui.setdefault(k, v)
            val["UI"] = existing_ui
            changed = True

    # 3. Rewrite in canonical format (fixes [ProfileName.Section] sub-tables
    #    even if no GUI key was present — the regex already confirmed this file
    #    has at least one [X.Y] header that needs collapsing)
    try:
        config_path.write_text(config_to_toml(d), encoding="utf-8")
        return True
    except Exception as e:
        print(f"{_WARNING} Config migration failed — file unchanged: {e}")
        return False


def migrate_ui_interface(config_path: Path) -> list[str]:
    """Fold the old ``[UI] Mode`` and ``Style`` keys into ``Interface``.

    ``Mode = "textual"`` was written into every config as the default, and
    Options never offered it, so it is not taken as a choice: such a config
    opens EDCARS, the new default.  ``gui`` keeps the layout ``Style`` gave
    it; ``terminal`` and ``headless`` are kept.  The global ``[UI]`` table and
    each profile's ``UI.*`` keys are migrated alike, by line, so the file's
    comments survive (``edit_config_keys``).  The old keys' presence is the
    marker: a migrated file has neither, so this never runs twice.

    Returns a description of each table changed, for the caller to report.
    """
    from core import modes as _modes
    try:
        config = load_config_file(config_path)
    except SystemExit:
        raise
    except Exception:
        return []
    if not isinstance(config, dict):
        return []

    tables: list[tuple[tuple[str, ...], dict]] = []
    if isinstance(config.get("UI"), dict):
        tables.append((("UI",), config["UI"]))
    for name, val in config.items():
        if (isinstance(val, dict) and name not in STANDARD_SECTIONS
                and isinstance(val.get("UI"), dict)):
            tables.append(((name, "UI"), val["UI"]))

    edits: dict[tuple[str, ...], dict[str, object]] = {}
    report: list[str] = []
    for path, ui in tables:
        if "Mode" not in ui and "Style" not in ui:
            continue
        new = _modes.from_legacy(ui.get("Mode"), ui.get("Style"))
        change: dict[str, object] = {"Mode": None, "Style": None}
        if new is not None and "Interface" not in ui:
            change["Interface"] = new
        edits[path] = change
        where = "[UI]" if path == ("UI",) else f"[{path[0]}] UI"
        now = change.get("Interface", ui.get("Interface"))
        report.append(f"{where}: Mode/Style replaced by "
                      + (f'Interface = "{now}"' if now else "the default interface"))
    if not edits:
        return []
    try:
        edit_config_keys(config_path, edits)
    except ConfigEditError as exc:
        print(f"{_WARNING} Could not move [UI] Mode/Style to Interface: {exc}")
        return []
    return report


def remember_interface(config_path: Path, profile: str | None, mode_id: str) -> bool:
    """Record ``mode_id`` as ``[UI] Interface``: what a launch without a flag
    opens next time.

    A plain launch opens the interface you last chose — in Options, or by
    starting one with its flag or launcher shortcut — so this is called when
    an interface is asked for by name.  It is written where the setting is
    read from: the active profile's ``UI.Interface`` if that profile sets one,
    otherwise the global ``[UI]`` table.  Edited by line, so comments survive,
    and only when the value changes.  Returns True if the file was changed.
    """
    from core import modes as _modes
    if mode_id not in dict(_modes.options_choices()):
        return False                      # headless is never remembered
    try:
        config = load_config_file(config_path)
    except SystemExit:
        raise
    except Exception:
        return False
    if not isinstance(config, dict):
        return False
    prof = config.get(profile) if profile else None
    prof_ui = prof.get("UI") if isinstance(prof, dict) else None
    if isinstance(prof_ui, dict) and "Interface" in prof_ui:
        path: tuple[str, ...] = (profile, "UI")
        current = prof_ui.get("Interface")
    else:
        path = ("UI",)
        ui = config.get("UI") if isinstance(config.get("UI"), dict) else {}
        current = ui.get("Interface")
    if _modes.normalise(current) == mode_id and current is not None:
        return False
    try:
        edit_config_keys(config_path, {path: {"Interface": mode_id}})
    except ConfigEditError:
        return False
    return True


# ── Config defaults ───────────────────────────────────────────────────────────

CFG_DEFAULTS_SETTINGS = {
    "JournalFolder":  "",
    "UseUTC":         False,
    "PrimaryInstance": True,   # Set False on remote/secondary instances to suppress data uploads
    "WarnKillRate":   20,
    "WarnNoKills":    20,
    "PirateNames":    False,
    "BountyFaction":  False,
    "BountyValue":    False,
    "ExtendedStats":  False,
    "MinScanLevel":   1,
}

CFG_DEFAULTS_EXTRA = {
    "TruncateNames":      30,
    "WarnNoKillsInitial": 5,
    "WarnCooldown":       15,
    "FullStackSize":      20,
}

CFG_DEFAULTS_UI = {
    # What a launch with no interface flag opens (core/modes.py): "edcars"
    # (the desktop window, EDCARS layout), "gui" (the desktop window,
    # Dashboard layout), "textual" (terminal dashboard), "terminal" (scrolling
    # log) or "headless".  Replaces the old Mode and Style keys; see
    # migrate_ui_interface().
    "Interface": "edcars",
    "Theme": "default",
    # EDCARS: on a new urgent alert, "pulse" the Alerts pill or also "switch"
    # to the Alerts section.
    "EdcarsAlerts": "pulse",
    # EDCARS: the console it is drawn as (core/edcars.py CONSOLES): "edcars",
    # "order", "rebel" or "rogue".
    "Console": "edcars",
    # The Dashboard layouts (desktop and terminal): show the Helm panel along
    # the foot while automation is on (core/helm.py). EDCARS always has it.
    "HelmPanel": True,
}

CFG_DEFAULTS_DISCORD = {
    "WebhookURL":      "",
    "UserID":          0,
    "PrependCmdrName": False,
    "ForumChannel":    False,
    "ThreadCmdrNames": False,
    "Timestamp":       True,
    "Identity":        True,
}

CFG_DEFAULTS_EDDN = {
    "Enabled":    False,
    "UploaderID": "",
    "TestMode":   False,
}

# No CommanderName: both services are told the name the journal gives.
CFG_DEFAULTS_EDSM = {
    "Enabled":       False,
    "ApiKey":        "",
}

CFG_DEFAULTS_EDASTRO = {
    "Enabled":             False,
    "UploadCarrierEvents": False,
}

CFG_DEFAULTS_INARA = {
    "Enabled":       False,
    "ApiKey":        "",
}

CFG_DEFAULTS_CAPI = {
    "Enabled": False,   # set True automatically after first successful auth
}

# Stations for the Radio tab (Crew / Alerts window), two keys per station:
# Name_<Id> is what the list shows, Url_<Id> the stream.  Any other Id is a
# user's own station; it is read with include_extra, so these are the defaults
# rather than the schema.  See core/radio.py for why the layout is flat.
CFG_DEFAULTS_RADIO = {
    "Name_RadioSidewinder": "Radio Sidewinder",
    "Url_RadioSidewinder":
        "https://radiosidewinder.out.airtime.pro:8000/radiosidewinder_b",
    "Name_HuttonOrbital":   "Hutton Orbital Radio",
    "Url_HuttonOrbital":    "https://quincy.torontocast.com/hutton",
    "Name_RadioSkvortsov":  "Radio Skvortsov",
    "Url_RadioSkvortsov":   "https://cast1.torontocast.com:3225/stream",
}

# Server mode, for the EDAM mobile client.  See docs/SERVER.md.
#   Enabled          run the server without passing -s
#   Port             TCP port to listen on; forward this one on the router
#   BindAddress      blank listens on every interface, IPv6 and IPv4
#   ExternalHost     the name devices use away from home, e.g. a DuckDNS name;
#                    only put into pairing codes, never looked up or contacted
#   AllowEndSession  let a paired device end the game session (Solo only)
#   PortMapping      ask the router to forward Port (UPnP / NAT-PMP)
#   DuckDNSDomain    keep this DuckDNS name pointed at this connection;
#   DuckDNSToken     both blank if something else already updates it
CFG_DEFAULTS_SERVER = {
    "Enabled":         False,
    "Port":            28510,
    "BindAddress":     "",
    "ExternalHost":    "",
    "AllowEndSession": False,
    "PortMapping":     False,
    "DuckDNSDomain":   "",
    "DuckDNSToken":    "",
}

CFG_DEFAULTS_COLONISATION = {
    # Raven Colonial API key for ravencolonial.com project tracking.
    # Leave blank to disable API integration (local tracking still works).
    "ApiKey": "",
}

CFG_DEFAULTS_NOTIFY = {
    "InboundScan":      1,
    "RewardEvent":      2,
    "FighterDamage":    2,
    "FighterLost":      3,
    "ShieldEvent":      3,
    "HullEvent":        3,
    "Died":             3,
    "CargoLost":        3,
    "LowCargoValue":    2,
    "PoliceScan":       2,
    "PoliceAttack":     3,
    "FuelStatus":       1,
    "FuelWarning":      2,
    "FuelCritical":     3,
    "MissionUpdate":    2,
    "AllMissionsReady": 3,
    "MeritEvent":       0,
    "InactiveAlert":    3,
    "RateAlert":        3,
    "PeriodicKills":    2,
    "PeriodicFaction":  0,
    "PeriodicCredits":  2,
    "PeriodicMerits":   2,
    # CAPI / external service health
    # Frontier's CAPI refresh token is valid for ~30 days. When it expires, all
    # CAPI features stop working until the user re-runs the OAuth flow.
    "CapiAuthRequired": 3,
    # Fleet / squadron carrier jump lifecycle.  A scheduled jump starts a
    # 15-minute lockdown during which the carrier cannot be boarded or
    # docked with, so it matters whether or not the commander is aboard —
    # level 3 puts it in the Alerts window and on Discord.  Completion is
    # quieter because by then the carrier has already arrived.
    "CarrierJumpScheduled": 3,
    "CarrierJumpCancelled": 3,
    "CarrierJumpComplete":  2,
    # Callouts (components/callouts.py), routes (components/navigation.py),
    # discoveries and automation.
    "RouteWarning":         2,
    "SurveyArrival":        1,
    "ExploTarget":          1,
    "FirstsWatch":          2,
    "MiningCallout":        1,
    "MiningWarning":        2,
    "ExobioCallout":        1,
    "ExobioWarning":        2,
    "CarrierUpkeep":        3,
    "Automation":           1,
}


# ── Config file resolution ────────────────────────────────────────────────────
# Priority:
#   1. User data dir  (~/.local/share/EDLD/config.toml)
#   2. Repo-adjacent  (same dir as edld.py)   — dev / legacy fallback

def resolve_config_path(script_path: Path) -> Path | None:
    """Return the first existing config.toml candidate, or None."""
    candidates = [
        EDLD_DATA_DIR / "config.toml",
        script_path.parent / "config.toml",
    ]
    for p in candidates:
        if p.is_file():
            return p
    return None


def load_config_file(config_path: Path) -> dict:
    """Read and parse a TOML config file.  Calls sys.exit on decode error."""
    with open(config_path, mode="rb") as f:
        try:
            return tomllib.load(f)
        except tomllib.TOMLDecodeError as e:
            print(f"Config decode error: {e}")
            sys.exit(1)


# ── Setting resolution ────────────────────────────────────────────────────────

def _safe_section(d: dict, key: str) -> dict:
    """Return d[key] if it is a dict, else {}. Prevents crashes when a config
    key exists but holds a scalar value instead of a nested table."""
    v = d.get(key)
    return v if isinstance(v, dict) else {}


def load_setting(
    config: dict,
    config_profile: str | None,
    category: str,
    defaults: dict,
    warn_missing: bool = True,
    include_extra: bool = False,
) -> dict:
    """Resolve a settings block with profile → global → default fallback.

    Resolution order per key:
      1. config[config_profile][category][key]   (if profile active)
      2. config[category][key]
      3. defaults[key]

    ``include_extra`` also returns keys present in the file but absent from
    ``defaults``.
    """
    settings = {}

    # Pre-extract sections once so the loop is clean and type-safe.
    # _safe_section guards against any level being a non-dict value.
    profile_section: dict = _safe_section(config, config_profile) if config_profile else {}
    profile_cat:     dict = _safe_section(profile_section, category)
    global_cat:      dict = _safe_section(config, category)

    for key in defaults:
        value = None

        if profile_cat.get(key) is not None:
            value = profile_cat[key]
        elif global_cat.get(key) is not None:
            value = global_cat[key]
        else:
            value = defaults[key]
            if warn_missing:
                print(
                    f"{_WARNING} Config '{category}' -> '{key}' not found "
                    f"(using default: {defaults[key]})"
                )

        if type(value) != type(defaults[key]):
            print(
                f"{_WARNING} Config '{category}' -> '{key}' expected type "
                f"{type(defaults[key]).__name__} but got "
                f"{type(value).__name__} "
                f"(using default: {defaults[key]})"
            )
            value = defaults[key]

        settings[key] = value

    if include_extra:
        for source in (global_cat, profile_cat):
            for key, value in source.items():
                if key not in defaults:
                    settings[key] = value

    return settings


# ── ConfigManager ─────────────────────────────────────────────────────────────

# ── In-place key edits ────────────────────────────────────────────────────────

class ConfigEditError(Exception):
    """An edit that could not be made safely.  config.toml is left untouched."""


def _header_path(line: str) -> tuple[str, ...] | None:
    """The table path of a ``[a.b]`` header line, or None if not a header.
    An array-of-tables header returns an empty tuple: a boundary, never a
    match."""
    s = line.strip()
    if s.startswith("[["):
        return ()
    m = re.match(r"^\[\s*([^\[\]]+?)\s*\]\s*(#.*)?$", s)
    if not m:
        return None
    return tuple(p.strip().strip('"').strip("'") for p in m.group(1).split("."))


def _trailing_comment(rest: str) -> str:
    """The comment after a scalar value, with the spaces before it, or "".

    ``rest`` is the line after ``key =``.
    """
    quote = None
    i = 0
    while i < len(rest):
        c = rest[i]
        if quote:
            if quote == '"' and c == "\\":
                i += 2
                continue
            if c == quote:
                quote = None
        elif c in "\"'":
            quote = c
        elif c == "#":
            start = i
            while start > 0 and rest[start - 1] in " \t":
                start -= 1
            return rest[start:] if start > 0 else " " + rest[i:]
        i += 1
    return ""


def edit_config_keys(config_path: Path,
                     edits: dict[tuple[str, ...], dict[str, object]]) -> None:
    """Set or remove keys in config.toml without rewriting the rest of it.

    ``edits`` maps a table path — ``("Radio",)`` or ``("EDP1", "Radio")`` — to
    ``{key: value}``, where a value of None removes the key.

    ``ConfigManager.save()`` regenerates the whole file from parsed values,
    which discards every comment in a file most users copied from the heavily
    commented example.  That is acceptable behind Preferences' Save button; it
    is not acceptable as a side effect of adding a radio station.  So this
    works line by line, like ``backfill_config_defaults``: a key already in
    the file is replaced where it stands, a new one goes at the end of its
    table, and a table that does not exist is appended.  A profile table is
    edited where the user keeps it — ``[EDP1.Radio]`` if that header exists,
    otherwise dotted ``Radio.<key>`` lines under ``[EDP1]``.
    """
    import copy
    import os
    import shutil
    import tomllib

    try:
        text = config_path.read_text(encoding="utf-8")
        before = tomllib.loads(text)
    except OSError as exc:
        raise ConfigEditError(f"cannot read {config_path.name}: {exc}") from exc
    except tomllib.TOMLDecodeError as exc:
        raise ConfigEditError(f"{config_path.name} does not parse: {exc}") from exc

    expected = copy.deepcopy(before)
    for path, keys in edits.items():
        node = expected
        for part in path:
            node = node.setdefault(part, {})
            if not isinstance(node, dict):
                raise ConfigEditError(f"[{'.'.join(path)}] is not a table")
        for key, value in keys.items():
            if value is None:
                node.pop(key, None)
            else:
                node[key] = value

    lines = text.splitlines()

    def _headers() -> list[tuple[int, tuple[str, ...]]]:
        return [(i, h) for i, ln in enumerate(lines)
                if (h := _header_path(ln)) is not None]

    def _body(start: int) -> tuple[int, int]:
        """(first, end) line indices of the table whose header is at start."""
        nxt = [i for i, _ in _headers() if i > start]
        return start + 1, (nxt[0] if nxt else len(lines))

    def _key_re(parts: tuple[str, ...]) -> re.Pattern:
        dotted = r"\s*\.\s*".join(re.escape(p) for p in parts)
        return re.compile(rf"^\s*{dotted}\s*=")

    for path, keys in edits.items():
        header = next((i for i, h in _headers() if h == path), None)
        prefix: tuple[str, ...] = ()
        if header is None and len(path) > 1:
            parent = next((i for i, h in _headers() if h == path[:-1]), None)
            if parent is not None:
                header, prefix = parent, (path[-1],)
        for key, value in keys.items():
            if header is None:
                if value is None:
                    continue                       # nothing to remove
                if lines and lines[-1].strip():
                    lines.append("")
                lines.append(f"[{'.'.join(path)}]")
                header = len(lines) - 1
            first, end = _body(header)
            pattern = _key_re(prefix + (key,))
            hit = next((i for i in range(first, end) if pattern.match(lines[i])), None)
            if value is None:
                if hit is not None:
                    del lines[hit]
                continue
            line = f"{'.'.join(prefix + (key,))} = {_toml_scalar(value)}"
            if hit is not None:
                # Keep the key exactly as written, alignment included; only
                # the value changes.
                lead = pattern.match(lines[hit]).group(0)
                lines[hit] = (f"{lead} {_toml_scalar(value)}"
                              + _trailing_comment(lines[hit][len(lead):]))
                continue
            at = header + 1
            for i in range(first, end):
                stripped = lines[i].strip()
                if stripped and not stripped.startswith("#"):
                    at = i + 1
            lines.insert(at, line)

    def _prune(doc: dict) -> dict:
        # A table emptied by removals may or may not survive, depending on how
        # the file spelled it: dotted keys vanish with their last key, while a
        # [EDP1.Radio] header stays behind empty.  Either is correct, so an
        # empty table on an edited path counts the same as no table.
        for path in edits:
            for depth in range(len(path), 0, -1):
                node = doc
                for part in path[:depth - 1]:
                    node = node.get(part, {}) if isinstance(node, dict) else {}
                leaf = node.get(path[depth - 1]) if isinstance(node, dict) else None
                if isinstance(leaf, dict) and not leaf:
                    del node[path[depth - 1]]
        return doc

    new_text = "\n".join(lines) + "\n"
    try:
        after = tomllib.loads(new_text)
    except tomllib.TOMLDecodeError as exc:
        raise ConfigEditError(
            f"could not edit {config_path.name} safely ({exc}); "
            "it has been left unchanged") from exc
    if _prune(after) != _prune(expected):
        raise ConfigEditError(
            f"could not edit {config_path.name} safely; it has been left "
            "unchanged — edit it by hand")

    tmp = config_path.with_name(config_path.name + ".tmp")
    try:
        tmp.write_text(new_text, encoding="utf-8")
        try:
            shutil.copymode(config_path, tmp)     # it can hold credentials
        except OSError:
            pass
        os.replace(tmp, config_path)
    except OSError as exc:
        try:
            tmp.unlink()
        except OSError:
            pass
        raise ConfigEditError(f"cannot write {config_path.name}: {exc}") from exc


class ConfigManager:
    """Holds live config state and supports hot-reload.

    Instantiated once in edld.py after initial load.
    """

    def __init__(
        self,
        config: dict,
        config_path: Path,
        config_profile: str | None,
    ):
        self.config         = config
        self.config_path    = config_path
        self.config_profile = config_profile
        self._mtime         = config_path.stat().st_mtime

        # Resolved setting dicts — refreshed on hot-reload
        self.app_settings  = {}
        self.discord_cfg   = {}
        self.notify_levels = {}
        self.ui_cfg        = {}
        self.capi_cfg         = {}
        self.colonisation_cfg = {}
        self._resolve_all(warn=True)

    def _resolve_all(self, warn: bool = False):
        self.app_settings  = self.load_setting("Settings",  CFG_DEFAULTS_SETTINGS, warn)
        self.app_settings.update(
            self.load_setting("Settings", CFG_DEFAULTS_EXTRA, False)
        )
        self.discord_cfg   = self.load_setting("Discord",   CFG_DEFAULTS_DISCORD,  warn)
        self.notify_levels = self.load_setting("LogLevels", CFG_DEFAULTS_NOTIFY,   warn)
        self.ui_cfg        = self.load_setting("UI",        CFG_DEFAULTS_UI,       False)
        self.eddn_cfg      = self.load_setting("EDDN",      CFG_DEFAULTS_EDDN,     False)
        self.edsm_cfg      = self.load_setting("EDSM",      CFG_DEFAULTS_EDSM,     False)
        self.edastro_cfg   = self.load_setting("EDAstro",   CFG_DEFAULTS_EDASTRO,  False)
        self.inara_cfg     = self.load_setting("Inara",        CFG_DEFAULTS_INARA,        False)
        self.capi_cfg      = self.load_setting("CAPI",         CFG_DEFAULTS_CAPI,         False)
        self.colonisation_cfg = self.load_setting("Colonisation", CFG_DEFAULTS_COLONISATION, False)


    def save(self) -> None:
        """Write current resolved config sections back to config.toml.

        Writes into the global config sections (no profile nesting) which is
        the canonical flat format.
        """
        d = dict(self.config)
        # Remove any existing section then write the resolved dict.
        d["Settings"]  = dict(self.app_settings)
        d["LogLevels"] = dict(self.notify_levels)
        d["UI"]        = dict(self.ui_cfg)
        if self.discord_cfg:
            d["Discord"] = dict(self.discord_cfg)
        self.config_path.write_text(config_to_toml(d), encoding="utf-8")
        try:
            self._mtime = self.config_path.stat().st_mtime
        except OSError:
            pass
        # Re-resolve so in-memory state matches what was written
        self._resolve_all(warn=False)


    def load_setting(
        self,
        category: str,
        defaults: dict,
        warn_missing: bool = True,
        include_extra: bool = False,
    ) -> dict:
        """Convenience wrapper using stored config and profile."""
        return load_setting(
            self.config,
            self.config_profile,
            category,
            defaults,
            warn_missing,
            include_extra,
        )

    def reload_now(self) -> None:
        """Re-read config.toml immediately, after EDLD itself edited it."""
        self.config = load_config_file(self.config_path)
        try:
            self._mtime = self.config_path.stat().st_mtime
        except OSError:
            pass
        self._resolve_all(warn=False)

    def refresh(self, terminal_print: bool = True) -> bool:
        """Re-read config.toml if modified.  Returns True if reloaded."""
        try:
            new_mtime = self.config_path.stat().st_mtime
        except OSError:
            return False

        if new_mtime <= self._mtime:
            return False

        try:
            self.config = load_config_file(self.config_path)
        except SystemExit:
            return False

        self._mtime = new_mtime
        self._resolve_all(warn=False)

        if terminal_print:
            # Deferred import avoids circular dependency at module load time
            from core.emit import Terminal
            print(f"{Terminal.YELL}Config reloaded.{Terminal.END}")

        return True