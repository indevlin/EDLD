"""
core/palette.py — UI-agnostic colour palettes.

The single source of truth for EDLD's colour schemes.  Both front ends read
from here:

  * ``tui/theme.py``  substitutes these values into the Textual CSS
  * ``gui/theme.py``  substitutes them into the Qt stylesheet

Keeping the palettes out of either UI module means a theme added here appears
in both front ends at once, and neither front end has to import the other (the
GUI must work on a machine with no Textual installed, and vice versa).

Palette keys carry their Textual ``$`` sigil because the TUI substitutes them
directly into CSS text.  ``rgb()`` returns the same values without the sigil
for callers that want plain names.
"""

from __future__ import annotations

from pathlib import Path

from core import edcars as _c

# ── Colour palettes ───────────────────────────────────────────────────────────

PALETTES: dict[str, dict[str, str]] = {
    # ── Default (Elite orange) ────────────────────────────────────────────────
    # Backgrounds carry a warm orange-amber tint matching the accent.
    # Accent #e07b20 — Elite Dangerous orange.
    "default": {
        "$bg":       "#120f0b",   # warm near-black, slight orange tint
        "$block-bg": "#1c1810",   # warm dark block fill
        "$title-bg": "#241e16",   # warm title / panel bar
        "$fg":       "#e8ddd0",   # warm off-white
        "$dim":      "#7a6a52",   # warm amber-brown muted text
        "$accent":   "#e07b20",   # Elite orange
        "$border":   "#3d2e18",   # dark amber-brown border
        "$green":    "#57e389",
        "$amber":    "#f8e45c",
        "$red":      "#e05c5c",
    },
    # ── Default Green ─────────────────────────────────────────────────────────
    # Backgrounds carry a cool forest-green tint.
    # Accent #00aa44 — green.
    "default-green": {
        "$bg":       "#0b0f0d",   # very dark, subtle green tint
        "$block-bg": "#141c18",   # dark green-tinted block fill
        "$title-bg": "#1a2420",   # green title / panel bar
        "$fg":       "#d4e4da",   # cool, slightly green-tinted white
        "$dim":      "#567060",   # muted green-gray
        "$accent":   "#00aa44",   # ED green
        "$border":   "#1e3428",   # dark forest-green border
        "$green":    "#57e389",
        "$amber":    "#f8e45c",
        "$red":      "#e05c5c",
    },
    # ── Elite Dangerous ───────────────────────────────────────────────────────
    # The cockpit HUD's default orange. Not one of the "EDLD Default" family:
    # those are EDLD's own identity, this one deliberately matches the game so
    # an overlay sitting on top of it does not look like a different program.
    "elite-orange": {
        "$bg":       "#0a0704",
        "$block-bg": "#150d05",
        "$title-bg": "#1f1407",
        "$fg":       "#ffb761",   # HUD body text
        "$dim":      "#8a5a22",   # muted amber, for labels
        "$accent":   "#ff7100",   # ED orange
        "$border":   "#3a2207",
        "$green":    "#57e389",
        "$amber":    "#f8e45c",
        "$red":      "#e05c5c",
    },
    # ── Default Blue ──────────────────────────────────────────────────────────
    # Accent #3d8fd4 — blue.
    "default-blue": {
        "$bg":       "#0c0e14",
        "$block-bg": "#141820",
        "$title-bg": "#1a2030",
        "$fg":       "#d0d8e8",
        "$dim":      "#556070",
        "$accent":   "#3d8fd4",
        "$border":   "#253050",
        "$green":    "#57e389",
        "$amber":    "#f8e45c",
        "$red":      "#e05c5c",
    },
    # ── Default Purple ────────────────────────────────────────────────────────
    # Accent #9b59b6 — purple.
    "default-purple": {
        "$bg":       "#0e0d14",
        "$block-bg": "#17151f",
        "$title-bg": "#201c28",
        "$fg":       "#dcd8e8",
        "$dim":      "#60587a",
        "$accent":   "#9b59b6",
        "$border":   "#302845",
        "$green":    "#57e389",
        "$amber":    "#f8e45c",
        "$red":      "#e05c5c",
    },
    # ── Default Red ───────────────────────────────────────────────────────────
    # Accent #cc3333 — red.
    "default-red": {
        "$bg":       "#130e0e",
        "$block-bg": "#1e1414",
        "$title-bg": "#261818",
        "$fg":       "#e8d8d8",
        "$dim":      "#7a5858",
        "$accent":   "#cc3333",
        "$border":   "#3d2020",
        "$green":    "#57e389",
        "$amber":    "#f8e45c",
        "$red":      "#e05c5c",
    },
    # ── Default Yellow ────────────────────────────────────────────────────────
    # Accent #d4a017 — yellow.
    "default-yellow": {
        "$bg":       "#110f08",
        "$block-bg": "#1a1810",
        "$title-bg": "#231f14",
        "$fg":       "#ede8d4",
        "$dim":      "#7a7050",
        "$accent":   "#d4a017",
        "$border":   "#3a3018",
        "$green":    "#57e389",
        "$amber":    "#f8e45c",
        "$red":      "#e05c5c",
    },
    "default-light": {
        "$bg":       "#f0f2f5",
        "$block-bg": "#ffffff",
        "$title-bg": "#e4e8f0",
        "$fg":       "#1a1e28",
        "$dim":      "#888ea0",
        "$accent":   "#005faa",
        "$border":   "#c8cdd8",
        "$green":    "#1a7a3a",
        "$amber":    "#b07000",
        "$red":      "#cc2222",
    },
    # ── The consoles' themes (core/edcars.py CONSOLES) ────────────────────────
    # Each made for the console of the same name, and usable with any
    # interface: the terminal dashboard and the Dashboard window too.
    #
    # ORDER — black glass, white readouts, red and green indicator light.
    "order": {
        "$bg":       "#0a0b0d",
        "$block-bg": "#050607",
        "$title-bg": "#16181b",
        "$fg":       "#e8eaed",
        "$dim":      "#8b9098",
        "$accent":   "#e03a2f",
        "$border":   "#2b2f34",
        "$green":    "#5fd068",
        "$amber":    "#e8c547",
        "$red":      "#ff6b5e",
    },
    # REBEL — deep navy room, green-tinted screens, orange and yellow lamps.
    "rebel": {
        "$bg":       "#1b222c",
        "$block-bg": "#0c1712",
        "$title-bg": "#26303d",
        "$fg":       "#e6dcc4",
        "$dim":      "#8fa889",
        "$accent":   "#e8762c",
        "$border":   "#2c4a35",
        "$green":    "#8be39a",
        "$amber":    "#f2c230",
        "$red":      "#ff6a50",
    },
    # ROGUE — worn slate, amber CRT phosphor.
    "rogue": {
        "$bg":       "#121416",
        "$block-bg": "#140d05",
        "$title-bg": "#23262a",
        "$fg":       "#ffb347",
        "$dim":      "#c9893a",
        "$accent":   "#ff9a2e",
        "$border":   "#34383d",
        "$green":    "#9be37c",
        "$amber":    "#ffd27a",
        "$red":      "#ff5a3c",
    },
}
PALETTES["default-dark"] = PALETTES["default"]


# ── Derived colours ───────────────────────────────────────────────────────────

#: How far the zebra stripe is pulled from the block fill toward the text
#: colour.  Blending toward $fg rather than adding a fixed offset means the
#: stripe lightens on the dark palettes and darkens on the light one, with no
#: per-theme special case.
#:
#: The figure is set by the terminal, not by taste.  Below 10% the stripe
#: stops surviving 256-colour quantisation: #1c1810 and a 6%-lighter #241e16
#: are both nearest to colour 16 on the xterm palette, so a 256-colour
#: terminal paints every row the same and the striping silently disappears.
#: Qt is always truecolor, which is why the desktop window showed a stripe the
#: terminal never did.  12% clears the threshold in all eight palettes with
#: margin, and still reads as about a 9% step where truecolor is available.
_STRIPE_BLEND = 0.12


def _blend(base: str, toward: str, pct: float) -> str:
    """Mix two ``#rrggbb`` colours.  Returns ``base`` if either is unparseable."""
    try:
        a = base.lstrip("#")
        b = toward.lstrip("#")
        if len(a) != 6 or len(b) != 6:
            return base
        mixed = tuple(
            round(int(a[i:i + 2], 16)
                  + (int(b[i:i + 2], 16) - int(a[i:i + 2], 16)) * pct)
            for i in (0, 2, 4)
        )
        return "#%02x%02x%02x" % tuple(max(0, min(255, v)) for v in mixed)
    except ValueError:
        return base


def derive(palette: dict[str, str]) -> dict[str, str]:
    """Add the computed entries a palette does not state for itself.

    Currently just ``$row-alt``, the zebra stripe.  Applied to the built-ins
    below and to every custom theme as it loads, so a theme file never has to
    know the stripe exists.
    """
    if "$row-alt" in palette:
        return palette
    palette = dict(palette)
    palette["$row-alt"] = _blend(
        palette.get("$block-bg", "#161a1f"),
        palette.get("$fg", "#d8dce5"),
        _STRIPE_BLEND,
    )
    return palette


# "default-dark" is the same object as "default", so derive into a fresh dict
# per name rather than mutating in place.
PALETTES = {name: derive(pal) for name, pal in PALETTES.items()}

#: Display names for the built-in themes, in the order the preferences
#: selectors present them.  Shared so the TUI and GUI offer the same list.
THEME_CHOICES: list[tuple[str, str]] = [
    ("Elite Dangerous",     "elite-orange"),
    ("EDLD Default",        "default"),
    ("EDLD Default Dark",   "default-dark"),
    ("EDLD Default Green",  "default-green"),
    ("EDLD Default Blue",   "default-blue"),
    ("EDLD Default Purple", "default-purple"),
    ("EDLD Default Red",    "default-red"),
    ("EDLD Default Yellow", "default-yellow"),
    ("EDLD Default Light",  "default-light"),
    (_c.ORDER_NAME,         "order"),
    (_c.REBEL_NAME,         "rebel"),
    (_c.ROGUE_NAME,         "rogue"),
]


#: Colour theme names the overlay offers, plus the escape hatch.
#:
#: "custom" means the explicit TitleColour / LabelColour / ValueColour settings
#: are used verbatim. Picking a theme overwrites what is drawn but not what is
#: stored, so switching to custom brings back whatever was set before rather
#: than whatever the last theme happened to be.
OVERLAY_THEME_CHOICES: list[tuple[str, str]] = (
    [("Custom", "custom")] + THEME_CHOICES
)


#: The overlay choice that draws with whatever theme the dashboard uses,
#: custom themes included.
FOLLOW_DASHBOARD = "dashboard"


def overlay_theme_choices() -> list[tuple[str, str]]:
    """Every colour theme the overlay offers, as ``[(name, id)]``.

    Custom (the three colour fields verbatim), Follow dashboard, the built-in
    themes, then any custom dashboard themes in ``themes/custom/`` — read
    when asked, so a theme file dropped in appears without a restart.
    """
    return ([("Custom", "custom"), ("Follow dashboard", FOLLOW_DASHBOARD)]
            + THEME_CHOICES
            + [(f"Custom: {stem}", tid) for tid, stem in list_custom_themes()])


def overlay_colours(theme: str, dashboard_theme: str = "") -> dict | None:
    """Title / label / value colours for a theme, or None for custom.

    Derived from the palette rather than listed separately, so a theme added to
    palette.py reaches the overlay without anything else being edited. A
    custom dashboard theme (``custom/<stem>``) is read from its CSS file, and
    Follow dashboard resolves ``dashboard_theme`` the same way.
    """
    if not theme or theme == "custom":
        return None
    if theme == FOLLOW_DASHBOARD:
        theme = dashboard_theme or "default"
    if theme.startswith("custom/"):
        pal = palette_for(theme)
    else:
        pal = PALETTES.get(theme)
    if not pal:
        return None
    return {"TitleColour": pal.get("$accent", "#7aa2d2"),
            "LabelColour": pal.get("$dim", "#9aa4b2"),
            "ValueColour": pal.get("$fg", "#cfd6e4")}


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def load_custom_palette(css_path) -> dict | None:
    """Parse a custom theme CSS file and extract a palette dict."""
    import re as _re
    try:
        block_m = _re.search(
            r":root\s*\{([^}]+)\}",
            Path(css_path).read_text(encoding="utf-8"),
            _re.DOTALL,
        )
        if not block_m:
            return None
        block = block_m.group(1)

        def _v(name, default=""):
            m = _re.search(rf"--{name}\s*:\s*([^;]+);", block)
            return m.group(1).strip() if m else default

        return derive({
            "$bg":       _v("bg-deep",  "#0d0f12"),
            "$block-bg": _v("bg-mid",   "#161a1f"),
            "$title-bg": _v("bg-panel", "#1c2128"),
            "$fg":       _v("fg",       "#d8dce5"),
            "$dim":      _v("fg-dim",   "#606878"),
            "$accent":   _v("accent",   "#aaaaaa"),
            "$border":   _v("border",   "#2a3040"),
            "$green":    _v("green",    "#57e389"),
            "$amber":    _v("amber",    "#f8e45c"),
            "$red":      _v("red",      "#e05c5c"),
        })
    except Exception:
        return None


def custom_theme_dirs() -> list[Path]:
    """Where custom themes are looked for, first match winning.

    ``<data>/themes/custom/`` comes first: it is writable in every install,
    including the packaged binaries, whose own ``themes/`` sits inside the
    executable where nothing can be added. ``themes/custom/`` beside the code
    follows, so a theme kept in a source checkout goes on working.
    """
    dirs = []
    try:
        from core.state import EDLD_DATA_DIR
        dirs.append(Path(EDLD_DATA_DIR) / "themes" / "custom")
    except Exception:
        pass
    dirs.append(_repo_root() / "themes" / "custom")
    return dirs


def custom_theme_path(theme_name: str) -> Path | None:
    """The CSS file for ``custom/<stem>``, or None when there is none."""
    if not theme_name or not theme_name.startswith("custom/"):
        return None
    stem = theme_name[len("custom/"):]
    if not stem or "/" in stem or "\\" in stem or stem.startswith("."):
        return None
    for d in custom_theme_dirs():
        f = d / f"{stem}.css"
        if f.is_file():
            return f
    return None


def list_custom_themes() -> list[tuple[str, str]]:
    """Return ``[(theme_id, stem)]`` for every custom theme, sorted by name.

    A stem found in more than one directory is listed once; the file used is
    the one :func:`custom_theme_path` picks.
    """
    stems = set()
    for d in custom_theme_dirs():
        try:
            stems.update(f.stem for f in d.glob("*.css") if f.is_file())
        except Exception:
            pass
    return [(f"custom/{s}", s) for s in sorted(stems)]


def palette_for(theme_name: str) -> dict[str, str]:
    """Return the palette dict for a theme id, falling back to ``default``.

    Handles the ``custom/<stem>`` form by parsing the matching CSS file, so
    both front ends resolve a custom theme identically.
    """
    if theme_name and theme_name.startswith("custom/"):
        css_file = custom_theme_path(theme_name)
        return (load_custom_palette(css_file) if css_file else None) or PALETTES["default"]
    return PALETTES.get(theme_name, PALETTES["default"])


def rgb(theme_name: str) -> dict[str, str]:
    """Palette for a theme with the ``$`` sigils stripped from the keys.

    ``rgb("default")["accent"]`` is the same colour as
    ``palette_for("default")["$accent"]``; the sigil-free form reads better in
    the Qt stylesheet builder, which has no use for Textual's variable syntax.
    """
    return {k.lstrip("$"): v for k, v in palette_for(theme_name).items()}


# ── For other programs ────────────────────────────────────────────────────────

#: Wire names for the palette keys, as the EDAM client and the exported theme
#: list use them.  Every key a palette has, so a device can draw exactly what
#: EDLD draws.
WIRE_KEYS = {
    "$bg": "bg", "$block-bg": "blockBg", "$title-bg": "titleBg", "$fg": "fg",
    "$dim": "dim", "$accent": "accent", "$border": "border",
    "$green": "green", "$amber": "amber", "$red": "red", "$row-alt": "rowAlt",
}


def theme_name(theme_id: str) -> str:
    """What the preferences selectors call a theme."""
    for name, tid in THEME_CHOICES:
        if tid == theme_id:
            return name
    if theme_id and theme_id.startswith("custom/"):
        return f"Custom: {theme_id.split('/', 1)[1]}"
    return "EDLD Default"


def wire_theme(theme_id: str) -> dict:
    """A theme as sent to a paired device: id, display name and colours.

    Resolved through palette_for(), so a custom theme arrives as the colours
    EDLD is actually drawing with, not as a name the device cannot look up.
    """
    tid = theme_id or "default"
    pal = palette_for(tid)
    if tid.startswith("custom/") or tid in PALETTES:
        resolved = tid
    else:
        resolved = "default"
    return {"id": resolved, "name": theme_name(resolved),
            "colors": {WIRE_KEYS[k]: v for k, v in pal.items() if k in WIRE_KEYS}}
