"""gui/theme.py — Qt stylesheet built from the shared EDLD palettes.

The GUI renders the same themes as the TUI.

Qt Style Sheets support a useful subset of CSS.
"""

from __future__ import annotations

import re

from core.palette import rgb

#: Point sizes at the default text size; every size moves with the text's.
FONT_SIZES = {
    "title":   11,
    "section":  9,
    "body":     10,
    "small":    9,
}

#: The monospace stack used for value columns.
MONO_FAMILIES = '"DejaVu Sans Mono", "Consolas", "Menlo", "Courier New", monospace'

#: Text sizes offered in Options, in points.
FONT_SIZE_CHOICES = tuple(range(8, 21))

#: Where a row's value sits: [UI] ValuePlacement. "manual" places the value
#: column by ValueFromLeft (from the labels' left) and ValueFromRight (from
#: the right edge), each pixels ("320") or a share of the width ("25%").
VALUES_EDGE = "edge"
VALUES_MANUAL = "manual"
VALUE_PLACEMENTS = (
    (VALUES_EDGE,   "At the right edge"),
    (VALUES_MANUAL, "Manual alignment"),
)

_OFFSET = re.compile(r"^\s*(\d{1,4}(?:\.\d+)?)\s*(px|%)?\s*$", re.IGNORECASE)


def parse_offset(text) -> "tuple[float, bool] | None":
    """(amount, is_percent) for "320", "320px" or "25%"; None when blank or
    not understood."""
    m = _OFFSET.match(str(text or ""))
    if m is None:
        return None
    amount, unit = float(m.group(1)), (m.group(2) or "").lower()
    if unit == "%":
        return min(amount, 100.0), True
    return amount, False


def offset_px(offset, width: int) -> "int | None":
    """An offset from parse_offset in pixels, for a width of ``width``."""
    if offset is None:
        return None
    amount, pct = offset
    return int(round(width * amount / 100.0)) if pct else int(amount)


#: The [UI] settings the desktop windows' text and rows are drawn by
#: (configure()). Chrome drawn in a console's own face is not affected.
_TYPE: dict = {"family": "", "figures": "", "size": FONT_SIZES["body"],
               "stripes": True, "values": VALUES_EDGE,
               "from_left": None, "from_right": None}
_APP_FONT = None


#: The [UI] keys configure() reads.
TYPE_KEYS = ("FontFamily", "FigureFamily", "FontSize", "RowStripes", "ValuePlacement",
             "ValueFromLeft", "ValueFromRight")


def signature(ui: "dict | None") -> tuple:
    """What configure() would be given, to tell when it has changed."""
    ui = ui or {}
    return tuple(str(ui.get(k, "")) for k in TYPE_KEYS)


def configure(ui: "dict | None") -> None:
    """Take the text and row settings from the [UI] table."""
    ui = ui or {}
    try:
        size = int(float(ui.get("FontSize", FONT_SIZES["body"])))
    except (TypeError, ValueError):
        size = FONT_SIZES["body"]
    stripes = ui.get("RowStripes", True)
    if not isinstance(stripes, bool):
        stripes = str(stripes).strip().lower() in ("1", "true", "on", "yes")
    values = str(ui.get("ValuePlacement", VALUES_EDGE) or VALUES_EDGE).strip().lower()
    from_left = parse_offset(ui.get("ValueFromLeft", ""))
    from_right = parse_offset(ui.get("ValueFromRight", ""))
    if values == "labels":
        # The first form of manual alignment: values just past the labels.
        values, from_left, from_right = VALUES_MANUAL, (0.0, False), None
    _TYPE.update(
        family=str(ui.get("FontFamily", "") or "").strip(),
        figures=str(ui.get("FigureFamily", "") or "").strip(),
        size=min(max(size, FONT_SIZE_CHOICES[0]), FONT_SIZE_CHOICES[-1]),
        stripes=stripes,
        values=values if values in dict(VALUE_PLACEMENTS) else VALUES_EDGE,
        from_left=from_left,
        from_right=from_right,
    )


def sizes() -> dict:
    """FONT_SIZES moved by the chosen text size."""
    delta = _TYPE["size"] - FONT_SIZES["body"]
    return {k: max(6, v + delta) for k, v in FONT_SIZES.items()}


def mono_families() -> str:
    fig = _TYPE["figures"].replace('"', "")
    return f'"{fig}", {MONO_FAMILIES}' if fig else MONO_FAMILIES


def row_stripes() -> bool:
    return bool(_TYPE["stripes"])


def value_offsets() -> "tuple | None":
    """(from_left, from_right) as parse_offset gives them, while manual
    alignment is chosen; None at the right edge."""
    if _TYPE["values"] != VALUES_MANUAL:
        return None
    return _TYPE["from_left"], _TYPE["from_right"]


def apply_app_font(app=None) -> None:
    """The chosen face as the application's font; blank restores the
    system's. Widgets given a face of their own keep it."""
    global _APP_FONT
    from PySide6.QtWidgets import QApplication
    app = app or QApplication.instance()
    if app is None:
        return
    from PySide6.QtGui import QFont
    if _APP_FONT is None:
        _APP_FONT = QFont(app.font())
    font = QFont(_APP_FONT)
    if _TYPE["family"]:
        font.setFamilies([_TYPE["family"]] + list(_APP_FONT.families()))
    app.setFont(font)


def _arrow_png(colour: str) -> str:
    """A small down-pointing triangle in ``color``, as a PNG path for QSS.
    """
    import struct
    import zlib
    try:
        from core.state import EDLD_DATA_DIR
        hexc = colour.lstrip("#")[:6].lower()
        r, g, b = (int(hexc[i:i + 2], 16) for i in (0, 2, 4))
        path = EDLD_DATA_DIR / "cache" / f"combo-arrow-{hexc}.png"
        if not path.exists():
            w, h, ss = 20, 12, 4          # drawn at 2x, supersampled 4x4
            rows = []
            for y in range(h):
                row = bytearray(b"\x00")
                for x in range(w):
                    hits = 0
                    for sy in range(ss):
                        for sx in range(ss):
                            px = x + (sx + 0.5) / ss
                            py = y + (sy + 0.5) / ss
                            # Triangle: top edge y=1, apex at (w/2, h-1).
                            half = (w / 2 - 1) * (1 - (py - 1) / (h - 2))
                            if 1 <= py <= h - 1 and abs(px - w / 2) <= half:
                                hits += 1
                    row += bytes((r, g, b, round(255 * hits / (ss * ss))))
                rows.append(bytes(row))

            def chunk(kind, data):
                return (struct.pack(">I", len(data)) + kind + data
                        + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF))
            png = (b"\x89PNG\r\n\x1a\n"
                   + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0))
                   + chunk(b"IDAT", zlib.compress(b"".join(rows), 9))
                   + chunk(b"IEND", b""))
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(".tmp")
            tmp.write_bytes(png)
            tmp.replace(path)
        return path.as_posix()
    except Exception:
        return ""


def stylesheet(theme_name: str = "default") -> str:
    """Return the complete Qt Style Sheet for ``theme_name``."""
    c = rgb(theme_name)
    f = sizes()
    mono = mono_families()
    arrow = _arrow_png(c["dim"])
    arrow_rule = (f'QComboBox::down-arrow {{ image: url("{arrow}"); '
                  f'width: 10px; height: 6px; }}') if arrow else ""
    return f"""
QWidget {{
    background-color: {c['bg']};
    color: {c['fg']};
    font-size: {f['body']}pt;
}}
QMainWindow, QDialog {{ background-color: {c['bg']}; }}

/* ── Dashboard blocks ──────────────────────────────────────────────────── */

QFrame#block {{
    background-color: {c['block-bg']};
    border: 1px solid {c['border']};
    border-radius: 3px;
}}
QLabel#blockTitle {{
    background-color: {c['title-bg']};
    color: {c['accent']};
    font-size: {f['title']}pt;
    font-weight: 600;
    letter-spacing: 1px;
    padding: 3px 8px;
    border-bottom: 1px solid {c['border']};
}}

/* ── Rows ──────────────────────────────────────────────────────────────── */

QLabel[role="key"]  {{ color: {c['dim']}; background: transparent; }}
QLabel[role="val"]  {{
    color: {c['fg']};
    background: transparent;
    font-family: {mono};
}}
QLabel[role="section"] {{
    color: {c['accent']};
    background: transparent;
    font-size: {f['section']}pt;
    font-weight: 600;
    letter-spacing: 1px;
    padding-top: 4px;
}}
QLabel[role="dim"]    {{ color: {c['dim']}; background: transparent; }}

/* A value column stays monospace whatever color it is wearing.
   classes_to_props turns "val dim" and "val highlight" into role="dim" and
   role="highlight", which carry a color and nothing else — so a value marked
   either way silently lost the monospace face that role="val" supplies, and
   with it every column the shared helpers had padded into line.  The column
   headings on the cargo manifest were the visible case: proportional
   headings sitting over monospace figures, lining up with nothing.

   Keyed on a property KVRow sets once and never rewrites, rather than on the
   role, because the role is exactly what changes when the color does. */
QLabel[col="value"] {{ font-family: {mono}; }}
QLabel[role="hdrkey"] {{
    color: {c['accent']};
    background: transparent;
    font-weight: 600;
}}
QLabel[health="good"] {{ color: {c['green']}; }}
QLabel[health="warn"] {{ color: {c['amber']}; }}
QLabel[health="crit"] {{ color: {c['red']}; }}
QLabel[role="highlight"] {{ color: {c['accent']}; background: transparent; }}

/* Rows (gui/block_base.py): every other row of a group in the stripe the
   tables use, while [UI] RowStripes is on. */
QWidget[kvrow="true"] {{ background: transparent; }}
QWidget[kvrow="true"][stripe="true"] {{ background-color: {c['row-alt']}; }}

QFrame[role="rule"] {{
    background-color: {c['border']};
    max-height: 1px;
    min-height: 1px;
    border: none;
}}

/* ── Tabs ──────────────────────────────────────────────────────────────── */

QTabWidget::pane {{
    border: none;
    border-top: 1px solid {c['border']};
    background: {c['block-bg']};
}}
QTabBar {{ qproperty-drawBase: 0; background: {c['title-bg']}; }}
QTabBar::tab {{
    background: {c['title-bg']};
    color: {c['dim']};
    padding: 3px 9px;
    margin: 0;
    border: none;
    border-right: 1px solid {c['border']};
    font-size: {f['small']}pt;
}}
QTabBar::tab:selected {{
    color: {c['accent']};
    font-weight: 600;
    background: {c['block-bg']};
}}
QTabBar::tab:hover:!selected {{ color: {c['fg']}; }}

/* ── Scroll areas ──────────────────────────────────────────────────────── */

QScrollArea {{ background: {c['block-bg']}; border: none; }}
QScrollArea > QWidget > QWidget {{ background: {c['block-bg']}; }}
QScrollBar:vertical {{
    background: {c['block-bg']};
    width: 9px;
    margin: 0;
    border: none;
}}
QScrollBar::handle:vertical {{
    background: {c['border']};
    min-height: 24px;
    border-radius: 4px;
}}
QScrollBar::handle:vertical:hover {{ background: {c['accent']}; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: none; }}
QScrollBar:horizontal {{
    background: {c['block-bg']};
    height: 9px;
    margin: 0;
    border: none;
}}
QScrollBar::handle:horizontal {{
    background: {c['border']};
    min-width: 24px;
    border-radius: 4px;
}}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0; }}
QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {{ background: none; }}

/* ── Controls ──────────────────────────────────────────────────────────── */

QPushButton {{
    background-color: {c['title-bg']};
    border: 1px solid {c['border']};
    border-radius: 3px;
    padding: 4px 12px;
    color: {c['fg']};
}}
QPushButton:hover  {{ border-color: {c['accent']}; }}
QPushButton:pressed{{ background-color: {c['border']}; }}
QPushButton:disabled {{ color: {c['dim']}; border-color: {c['border']}; }}
QPushButton[role="primary"] {{
    background-color: {c['accent']};
    border: 1px solid {c['accent']};
    color: {c['bg']};
    font-weight: 600;
}}
QPushButton[role="primary"]:hover {{ background-color: {c['fg']}; }}
QPushButton[role="link"] {{
    background: transparent;
    border: none;
    padding: 2px 4px;
    color: {c['dim']};
}}
QPushButton[role="link"]:hover {{ color: {c['accent']}; }}
/* The Helm panel (gui/blocks/helm.py): a button lights for a moment when
   pressed, whatever the game then does. */
QPushButton[role="helm"] {{ padding: 3px 6px; }}
QPushButton[role="helm"][lit="true"] {{
    background-color: {c['accent']};
    border-color: {c['accent']};
    color: {c['bg']};
}}
QLabel#helmGroupTitle {{ color: {c['accent']}; font-weight: 600; }}
QLabel#helmNote {{ color: {c['amber']}; padding: 4px 8px; }}
QLabel#helmStatus {{ color: {c['dim']}; }}

QLineEdit, QSpinBox, QComboBox {{
    background-color: {c['bg']};
    border: 1px solid {c['border']};
    border-radius: 3px;
    padding: 3px 6px;
    color: {c['fg']};
    selection-background-color: {c['accent']};
    selection-color: {c['bg']};
}}
QLineEdit:focus, QSpinBox:focus, QComboBox:focus {{ border-color: {c['accent']}; }}
QLineEdit:disabled, QSpinBox:disabled, QComboBox:disabled {{
    color: {c['dim']};
    background-color: {c['block-bg']};
}}
/* Radio buttons (the Add Station dialog).  Without a rule the platform
   indicator is drawn in the window color and an unchecked one vanishes. */
QRadioButton {{ spacing: 6px; }}
QRadioButton::indicator {{
    width: 12px; height: 12px;
    border: 1px solid {c['border']};
    border-radius: 7px;
    background-color: {c['bg']};
}}
QRadioButton::indicator:hover {{ border-color: {c['accent']}; }}
QRadioButton::indicator:checked {{
    border-color: {c['accent']};
    background-color: qradialgradient(cx:0.5, cy:0.5, radius:0.5, fx:0.5, fy:0.5,
        stop:0 {c['accent']}, stop:0.45 {c['accent']},
        stop:0.55 {c['bg']}, stop:1 {c['bg']});
}}
QRadioButton:disabled {{ color: {c['dim']}; }}
QRadioButton::indicator:disabled {{ border-color: {c['dim']}; }}
QComboBox::drop-down {{ border: none; width: 18px; }}
{arrow_rule}
QComboBox QAbstractItemView {{
    background-color: {c['block-bg']};
    border: 1px solid {c['border']};
    color: {c['fg']};
    selection-background-color: {c['accent']};
    selection-color: {c['bg']};
    outline: none;
}}

/* ── Menus ─────────────────────────────────────────────────────────────── */

QMenuBar {{
    background-color: {c['title-bg']};
    color: {c['fg']};
    border-bottom: 1px solid {c['border']};
}}
QMenuBar::item {{ background: transparent; padding: 4px 10px; }}
QMenuBar::item:selected {{ background: {c['accent']}; color: {c['bg']}; }}
QMenu {{
    background-color: {c['block-bg']};
    border: 1px solid {c['border']};
    color: {c['fg']};
}}
QMenu::item {{ padding: 4px 22px; }}
QMenu::item:selected {{ background: {c['accent']}; color: {c['bg']}; }}
QMenu::item:disabled {{ color: {c['dim']}; }}
QMenu::separator {{ height: 1px; background: {c['border']}; margin: 3px 0; }}

/* ── Status bar and notices ────────────────────────────────────────────── */

QStatusBar {{
    background-color: {c['title-bg']};
    color: {c['dim']};
    border-top: 1px solid {c['border']};
}}
QStatusBar::item {{ border: none; }}
QLabel#updateNotice {{
    background-color: {c['title-bg']};
    color: {c['amber']};
    padding: 3px 8px;
    font-weight: 600;
}}

/* ── Support bar ───────────────────────────────────────────────────────── */

QWidget#supportBar {{ background-color: {c['title-bg']}; }}
QLabel#supportLabel {{
    color: {c['dim']};
    font-size: {f['small']}pt;
    letter-spacing: 1px;
}}
QLabel[role="supportSep"] {{ color: {c['border']}; }}

/* ── Dialogs ───────────────────────────────────────────────────────────── */

QLabel#aboutTitle {{
    color: {c['accent']};
    font-size: 17pt;
    font-weight: 600;
    letter-spacing: 1px;
}}
QLabel#aboutSubtitle {{ color: {c['dim']}; font-size: {f['small']}pt; }}
QGroupBox {{
    border: 1px solid {c['border']};
    border-radius: 3px;
    margin-top: 16px;
    padding: 10px 10px 8px 10px;
    background-color: {c['block-bg']};
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 8px;
    padding: 2px 6px;
    color: {c['accent']};
    font-size: {f['small']}pt;
    font-weight: 600;
}}
/* Tables.  alternate-background-color must be stated or Qt supplies its own,
   which is a light gray and unreadable on every dark palette here.
   {c['row-alt']} is derived from the block fill in core.palette and is the
   same stripe the TUI paints, so the two windows match. */
QTableWidget, QTableView {{
    background: {c['block-bg']};
    alternate-background-color: {c['row-alt']};
    color: {c['fg']};
    border: none;
    gridline-color: {c['border']};
}}
QTableWidget::item, QTableView::item {{ padding: 3px 6px; }}
QHeaderView::section {{
    background: {c['title-bg']};
    color: {c['dim']};
    border: none;
    border-bottom: 1px solid {c['border']};
    padding: 4px 6px;
}}
QTableCornerButton::section {{ background: {c['title-bg']}; border: none; }}

QListWidget {{
    background-color: {c['bg']};
    border: 1px solid {c['border']};
    color: {c['fg']};
    outline: none;
}}
QListWidget::item {{ padding: 3px 6px; }}
QListWidget::item:selected {{ background: {c['accent']}; color: {c['bg']}; }}
QSplitter::handle {{ background: {c['bg']}; }}
QSplitter::handle:horizontal {{ width: 3px; }}
QSplitter::handle:vertical   {{ height: 3px; }}
QToolTip {{
    background-color: {c['title-bg']};
    color: {c['fg']};
    border: 1px solid {c['accent']};
    padding: 3px;
}}
"""


def health_class(pct) -> str:
    """Map a 0–100 health percentage to a stylesheet ``health`` property.

    Thresholds match ``tui/block_base._health_cls`` exactly so a hull at 30%
    is amber in both front ends.
    """
    if pct is None:
        return ""
    try:
        v = float(pct)
    except (TypeError, ValueError):
        return ""
    if v > 75:
        return "good"
    if v >= 25:
        return "warn"
    return "crit"


def classes_to_props(classes: str) -> dict[str, str]:
    """Translate a TUI CSS class string into Qt property values.

    Blocks pass class strings like ``"val health-crit"`` or ``"val dim"``
    straight through from the ported TUI code.
    """
    parts = set((classes or "").split())
    props: dict[str, str] = {"role": "val"}
    if "health-good" in parts:
        props["health"] = "good"
    elif "health-warn" in parts:
        props["health"] = "warn"
    elif "health-crit" in parts:
        props["health"] = "crit"
    if "dim" in parts:
        props["role"] = "dim"
    if "highlight" in parts:
        props["role"] = "highlight"
    if "section-hdr" in parts:
        props["role"] = "section"
    return props
