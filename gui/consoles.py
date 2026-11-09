"""gui/consoles.py — how each console dresses the EDCARS layout.

    EDCARS    the band and the elbow, pills down the rail (Euro Caps)
    ORDER     Imperial: gray steel, indicator lights, chamfered black glass
              (Rajdhani)
    REBEL     Rebel: cream consoles, round lamps, screens in bezels
              (Saira Condensed)
    ROGUE     independent: worn plate, tape labels, toggles, amber CRTs
              (VT323, the labels in Permanent Marker)

The faces are bundled in fonts/ with their licenses (THIRD-PARTY-NOTICES.md).
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (
    QColor, QFont, QFontDatabase, QPainter, QPainterPath, QPen, QPolygonF,
)

from core import edcars as H

# ── Faces ─────────────────────────────────────────────────────────────────────

_FAMILIES: dict[str, str] = {}


def _family(filename: str, fallback: str) -> str:
    """Register a bundled face once and return its family, or ``fallback``.
    Looked for beside the code, or in the frozen bundle."""
    if filename in _FAMILIES:
        return _FAMILIES[filename]
    base = getattr(sys, "_MEIPASS", None)
    root = Path(base) if base else Path(__file__).resolve().parents[1]
    family = ""
    path = root / "fonts" / filename
    if path.is_file():
        fid = QFontDatabase.addApplicationFont(str(path))
        fams = QFontDatabase.applicationFontFamilies(fid) if fid >= 0 else []
        family = fams[0] if fams else ""
    _FAMILIES[filename] = family or fallback
    return _FAMILIES[filename]


# ── Consoles ──────────────────────────────────────────────────────────────────

class Console:
    """The original dress, EDCARS's own. The others override what they draw
    differently."""

    id = H.EDCARS_ID

    #: The chrome's face: file, fallback, whether it is drawn thickened (it
    #: has no bold of its own), and how its sizes compare with Euro Caps'.
    face_file = "EUROCAPS.TTF"
    face_fallback = "Arial Narrow"
    synthetic_bold = True
    scale = 1.0
    #: The face of the rail's labels, when it is not the chrome's.
    label_file = ""
    label_fallback = ""
    #: The pills are painted here rather than by the style sheet.
    painted_pills = False

    # Faces ─────────────────────────────────────────────────────────────────

    def family(self) -> str:
        return _family(self.face_file, self.face_fallback)

    def label_family(self) -> str:
        if not self.label_file:
            return self.family()
        return _family(self.label_file, self.label_fallback or self.family())

    def weight(self) -> str:
        """The style sheet's weight for the chrome."""
        return "bold"

    def pt(self, size: float) -> str:
        return f"{size * self.scale:g}pt"

    def font(self, pt: float, bold: bool = True) -> QFont:
        f = QFont(self.family())
        f.setPointSizeF(pt * self.scale)
        f.setBold(bold and self.weight() == "bold")
        if bold and self.synthetic_bold:
            # Euro Caps kerns some pairs very tight (L under O by 18 % of the
            # em), and a thickened L ran into the O — "LOGISTICS",
            # "EXPLORATION". So kerning is off, and 3 % more spacing makes
            # room for the extra weight.
            f.setKerning(False)
            f.setLetterSpacing(QFont.PercentageSpacing, 103)
        return f

    def label_font(self, pt: float) -> QFont:
        if not self.label_file:
            return self.font(pt)
        f = QFont(self.label_family())
        f.setPointSizeF(pt)
        return f

    # Header ────────────────────────────────────────────────────────────────

    def header_margins(self) -> tuple[int, int]:
        from gui.edcars import CAP_W, FILLET_R, GAP, RAIL_W
        return RAIL_W + FILLET_R + 6, CAP_W + GAP + 14

    def paint_header(self, p: QPainter, w: int, h: int, ink) -> None:
        from gui.edcars import BAND_H, CAP_W, ELBOW_R, FILLET_R, GAP, RAIL_W
        acc = QColor(ink.accent)
        # Elbow: the full height, rounded at the top left.
        elbow = QPainterPath()
        elbow.addRoundedRect(QRectF(0, 0, RAIL_W + ELBOW_R, h + ELBOW_R), ELBOW_R, ELBOW_R)
        clip = QPainterPath()
        clip.addRect(QRectF(0, 0, RAIL_W, h))
        p.fillPath(elbow.intersected(clip), acc)
        # Band, from the elbow to the cap.
        p.fillRect(QRectF(RAIL_W - 1, 0, w - RAIL_W - CAP_W - GAP + 1, BAND_H), acc)
        # The concave fillet joining them.
        fillet = QPainterPath()
        fillet.addRect(QRectF(RAIL_W - 1, BAND_H - 1, FILLET_R + 1, FILLET_R + 1))
        hole = QPainterPath()
        hole.addEllipse(QRectF(RAIL_W, BAND_H, FILLET_R * 2, FILLET_R * 2))
        p.fillPath(fillet.subtracted(hole), acc)
        # The cap.
        cap = QPainterPath()
        cap.addRoundedRect(QRectF(w - CAP_W, 0, CAP_W + BAND_H / 2, BAND_H),
                           BAND_H / 2, BAND_H / 2)
        cap_clip = QPainterPath()
        cap_clip.addRect(QRectF(w - CAP_W, 0, CAP_W, BAND_H))
        p.fillPath(cap.intersected(cap_clip), QColor(ink.cap))

    def band_text(self, ink) -> str:
        return ink.bg

    # Rail ──────────────────────────────────────────────────────────────────

    def paint_fill(self, p: QPainter, w: int, h: int, ink) -> None:
        from gui.edcars import ELBOW_R
        path = QPainterPath()
        path.addRoundedRect(QRectF(0, -ELBOW_R, w + ELBOW_R, h + ELBOW_R), ELBOW_R, ELBOW_R)
        clip = QPainterPath()
        clip.addRect(QRectF(0, 0, w, h))
        p.fillPath(path.intersected(clip), QColor(ink.fill))

    def paint_pill(self, p: QPainter, btn, ink) -> None:
        """Drawn over the style sheet's pill: the lamps, where a console has
        them. With ``painted_pills``, the whole pill."""

    # Frames ────────────────────────────────────────────────────────────────

    #: Left, top, right, bottom of the window's body inside its frame, and
    #: the frame's own indent on the left (EDCARS's accent rule sits there).
    holder_margins = (6, 4, 4, 4)
    frame_indent = 11

    def paint_frame(self, p: QPainter, frame, ink) -> None:
        title = frame.title.geometry()
        x0 = title.right() + 4
        y = title.center().y() - 3
        if x0 < frame.width() - 8:
            bar = QPainterPath()
            bar.addRoundedRect(QRectF(x0, y, frame.width() - x0, 6), 3, 3)
            p.fillPath(bar, QColor(ink.fill))
        top = title.bottom() + 4
        rule = QPainterPath()
        rule.addRoundedRect(QRectF(0, top, 5, frame.height() - top), 2.5, 2.5)
        p.fillPath(rule, QColor(ink.accent))

    # Style sheet ───────────────────────────────────────────────────────────

    def qss(self, ink, s: str) -> str:
        """The rules for the chrome under ``s`` (a selector scope)."""
        fam = self.family()
        wt = self.weight()
        return f"""
{s} QPushButton#edcarsPill {{
    background-color: {ink.pill};
    color: {ink.bg};
    border: none;
    border-radius: 0px;
    font-family: "{fam}";
    font-size: {self.pt(12)};
    font-weight: {wt};
    text-align: right;
    padding: 14px 14px 5px 8px;
    min-height: 20px;
}}
{s} QPushButton#edcarsPill:hover {{ background-color: {ink.pill_hover}; }}
{s} QPushButton#edcarsPill:checked {{ background-color: {ink.accent}; }}
{s} QPushButton#edcarsPill[pulse="on"] {{ background-color: {ink.red}; color: {ink.bg}; }}
{s} QPushButton#edcarsPill[pulse="dim"] {{ background-color: {ink.red_dim}; color: {ink.bg}; }}
{s} QLabel#edcarsCmdr, {s} QLabel#edcarsClock {{ color: {self.band_text(ink)}; background: transparent;
    font-family: "{fam}"; font-size: {self.pt(19)}; font-weight: {wt}; }}
{s} QLabel#edcarsKey {{ color: {ink.dim}; background: transparent;
    font-family: "{fam}"; font-size: {self.pt(9)}; font-weight: {wt}; }}
{s} QLabel#edcarsFrameTitle {{ color: {ink.accent}; background: transparent;
    font-family: "{fam}"; font-size: {self.pt(12)}; padding: 0px 10px 0px 0px; }}
{s} QWidget#edcarsFrameBody {{ background-color: {ink.block_bg}; }}
{s} QWidget#edcarsRadio {{ background-color: {ink.bg}; }}
{s} QLabel#edcarsRadioState {{ color: {ink.dim}; font-family: "{fam}"; font-size: {self.pt(9)}; }}
{s} QPushButton[role="helm"] {{
    background-color: {ink.pill};
    color: {ink.bg};
    border: none;
    border-radius: 8px;
    font-family: "{fam}";
    font-size: {self.pt(11)};
    font-weight: {wt};
    text-align: right;
    padding: 12px 10px 4px 8px;
}}
{s} QPushButton[role="helm"]:hover {{ background-color: {ink.pill_hover}; }}
{s} QPushButton[role="helm"][lit="true"] {{ background-color: {ink.accent}; }}
{s} QPushButton[role="helm"]:disabled {{ background-color: {ink.fill}; color: {ink.dim}; }}
{s} QLabel#helmGroupTitle {{ color: {ink.accent}; background: transparent;
    font-family: "{fam}"; font-size: {self.pt(10)}; font-weight: {wt}; }}
"""

    def dialog_qss(self, ink, s: str) -> str:
        """Dialogs opened from the console (``s`` scopes them): headings set
        as the frames' titles, their buttons as the Helm panel's."""
        fam = self.family()
        wt = self.weight()
        return f"""
{s} {{ background-color: {ink.bg}; }}
{s} QLabel[role="section"] {{
    color: {ink.accent};
    font-family: "{fam}";
    font-size: {self.pt(12)};
    font-weight: normal;
    letter-spacing: 0px;
}}
{s} QDialogButtonBox QPushButton {{
    background-color: {ink.pill};
    color: {ink.bg};
    border: none;
    border-radius: 8px;
    font-family: "{fam}";
    font-size: {self.pt(11)};
    font-weight: {wt};
    padding: 8px 18px 3px 18px;
    min-width: 64px;
}}
{s} QDialogButtonBox QPushButton:hover {{ background-color: {ink.pill_hover}; }}
{s} QDialogButtonBox QPushButton[role="primary"],
{s} QDialogButtonBox QPushButton:default {{ background-color: {ink.accent}; }}
"""


# ── ORDER ─────────────────────────────────────────────────────────────────────

STEEL = "#2b2f34"          # panels and pills
STEEL_EDGE = "#4a4f56"     # their lit top edge, and the rules
STEEL_HI = "#353a40"       # a pill under the pointer
STEEL_TEXT = "#c9ccd1"     # a pill's label
STEEL_DARK = "#16181b"     # the rail behind the pills
STEEL_GLASS = "#5a5f66"    # the edge of a screen
LED_OFF = "#3a3e44"
PANEL_WHITE = "#e8eaed"    # the lit pill
PANEL_BLACK = "#000000"


def _glow(p: QPainter, rect: QRectF, colour: str, round_: bool) -> None:
    c = QColor(colour)
    halo = QColor(c)
    halo.setAlpha(70)
    grown = rect.adjusted(-3, -3, 3, 3)
    p.setPen(Qt.NoPen)
    p.setBrush(halo)
    if round_:
        p.drawEllipse(grown)
    else:
        p.drawRect(grown)
    p.setBrush(c)
    if round_:
        p.drawEllipse(rect)
    else:
        p.drawRect(rect)


def _lamp_colour(btn, ink, lit: str, off: str) -> tuple[str, bool]:
    pulse = btn.property("pulse") or ""
    if pulse == "on":
        return ink.red, True
    if pulse == "dim":
        return ink.red_dim, False
    if btn.isChecked():
        return lit, True
    return off, False


class Order(Console):
    id = H.ORDER_ID
    face_file = "Rajdhani-Bold.ttf"
    face_fallback = "Arial Narrow"
    synthetic_bold = False
    scale = 1.05

    def header_margins(self) -> tuple[int, int]:
        from gui.edcars import RAIL_W
        return RAIL_W + 22, 22

    def paint_header(self, p: QPainter, w: int, h: int, ink) -> None:
        from gui.edcars import BAND_H, RAIL_W
        # The block over the rail, a grid of indicator lights in it.
        p.fillRect(QRectF(0, 0, RAIL_W, h), QColor(STEEL))
        p.fillRect(QRectF(RAIL_W - 1, 0, 1, h), QColor(STEEL_EDGE))
        lit = {0: ink.accent, 2: ink.green, 4: PANEL_WHITE, 6: ink.accent,
               9: ink.green, 12: ink.accent, 13: ink.green, 15: PANEL_WHITE,
               16: PANEL_WHITE, 19: ink.accent, 22: ink.green}
        cols, rows, gap = 8, 3, 5
        cw = (RAIL_W - 32 - gap * (cols - 1)) / cols
        top = (BAND_H - rows * 8 - (rows - 1) * gap) / 2
        for i in range(cols * rows):
            r, c = divmod(i, cols)
            p.fillRect(QRectF(16 + c * (cw + gap), top + r * (8 + gap), cw, 8),
                       QColor(lit.get(i, LED_OFF)))
        # The band, black, over a rule of the accent.
        p.fillRect(QRectF(RAIL_W, 0, w - RAIL_W, BAND_H), QColor(PANEL_BLACK))
        p.fillRect(QRectF(RAIL_W, BAND_H - 2, w - RAIL_W, 2), QColor(ink.accent))
        # The strip's floor.
        p.fillRect(QRectF(RAIL_W, h - 1, w - RAIL_W, 1), QColor(STEEL))

    def band_text(self, ink) -> str:
        return ink.fg

    def paint_fill(self, p: QPainter, w: int, h: int, ink) -> None:
        # Spare tiles of the panel, one of them lit, gathered at the foot.
        p.fillRect(QRectF(0, 0, w, h), QColor(STEEL_DARK))
        cols, gap, pad, th = 4, 6, 16, 22
        cw = (w - pad * 2 - gap * (cols - 1)) / cols
        rows = max(0, min(4, int((h - pad) // (th + gap))))
        for r in range(rows):
            for c in range(cols):
                x = pad + c * (cw + gap)
                y = h - pad - (r + 1) * th - r * gap
                colour = ink.accent if (r, c) == (0, 3) else (LED_OFF if (r + c) % 3 == 0 else STEEL)
                p.fillRect(QRectF(x, y, cw, th), QColor(colour))

    def paint_pill(self, p: QPainter, btn, ink) -> None:
        colour, glow = _lamp_colour(btn, ink, ink.accent, LED_OFF)
        side = 10
        rect = QRectF(14, (btn.height() - side) / 2, side, side)
        if glow:
            _glow(p, rect, colour, round_=False)
        else:
            p.fillRect(rect, QColor(colour))

    holder_margins = (12, 10, 12, 10)
    frame_indent = 0

    def paint_frame(self, p: QPainter, frame, ink) -> None:
        title = frame.title.geometry()
        x0 = title.right() + 8
        y = title.center().y()
        if x0 < frame.width() - 8:
            p.fillRect(QRectF(x0, y, frame.width() - x0, 1), QColor(STEEL_EDGE))
        # The screen: black glass in a thin steel edge, its corners cut.
        top = title.bottom() + 5
        r = QRectF(0.5, top + 0.5, frame.width() - 1, frame.height() - top - 1)
        k = 14
        poly = QPolygonF([QPointF(r.left() + k, r.top()), QPointF(r.right(), r.top()),
                          QPointF(r.right(), r.bottom() - k),
                          QPointF(r.right() - k, r.bottom()),
                          QPointF(r.left(), r.bottom()), QPointF(r.left(), r.top() + k)])
        p.setBrush(QColor(ink.block_bg))
        p.setPen(QPen(QColor(STEEL_GLASS), 1))
        p.drawPolygon(poly)

    def qss(self, ink, s: str) -> str:
        fam = self.family()
        return super().qss(ink, s) + f"""
{s} QPushButton#edcarsPill {{
    background-color: {STEEL};
    color: {STEEL_TEXT};
    border: none;
    border-top: 1px solid {STEEL_EDGE};
    font-size: {self.pt(12)};
    letter-spacing: 2px;
    padding: 12px 14px 10px 32px;
}}
{s} QPushButton#edcarsPill:hover {{ background-color: {STEEL_HI}; }}
{s} QPushButton#edcarsPill:checked {{ background-color: {PANEL_WHITE}; color: #0a0b0d; }}
{s} QPushButton#edcarsPill[pulse="on"], {s} QPushButton#edcarsPill[pulse="dim"] {{
    background-color: {STEEL}; color: {PANEL_WHITE}; }}
{s} QLabel#edcarsFrameTitle {{ color: {STEEL_TEXT}; font-family: "{fam}";
    font-size: {self.pt(12)}; font-weight: bold; letter-spacing: 3px; padding: 0px; }}
{s} QWidget#edcarsFrameBody {{ background: transparent; }}
{s} QWidget#edcarsRadio {{ background-color: {PANEL_BLACK}; border-top: 1px solid {STEEL}; }}
{s} QPushButton[role="helm"] {{
    background-color: {STEEL};
    color: {STEEL_TEXT};
    border: none;
    border-top: 1px solid {STEEL_EDGE};
    border-radius: 0px;
    letter-spacing: 2px;
}}
{s} QPushButton[role="helm"]:hover {{ background-color: {STEEL_HI}; }}
{s} QPushButton[role="helm"][lit="true"] {{ background-color: {PANEL_WHITE}; color: #0a0b0d; }}
{s} QPushButton[role="helm"]:disabled {{ background-color: {STEEL_DARK}; color: {ink.dim}; }}
{s} QLabel#helmGroupTitle {{ color: {STEEL_TEXT}; letter-spacing: 3px; }}
"""

    def dialog_qss(self, ink, s: str) -> str:
        return super().dialog_qss(ink, s) + f"""
{s} QLabel[role="section"] {{ color: {STEEL_TEXT}; font-weight: bold; letter-spacing: 3px; }}
{s} QDialogButtonBox QPushButton {{
    background-color: {STEEL}; color: {STEEL_TEXT};
    border-top: 1px solid {STEEL_EDGE}; border-radius: 0px; letter-spacing: 2px;
}}
{s} QDialogButtonBox QPushButton:hover {{ background-color: {STEEL_HI}; }}
{s} QDialogButtonBox QPushButton[role="primary"],
{s} QDialogButtonBox QPushButton:default {{ background-color: {PANEL_WHITE}; color: #0a0b0d; }}
"""


# ── REBEL ─────────────────────────────────────────────────────────────────────

CREAM = "#e6dcc4"          # the consoles, the bezels, the band
CREAM_HI = "#f3ead6"
CREAM_INK = "#1b222c"      # text on cream
LAMP_OFF = "#8b8270"


class Rebel(Console):
    id = H.REBEL_ID
    face_file = "SairaCondensed-Bold.ttf"
    face_fallback = "Arial Narrow"
    synthetic_bold = False
    scale = 1.1

    def paint_header(self, p: QPainter, w: int, h: int, ink) -> None:
        from gui.edcars import BAND_H, CAP_W, ELBOW_R, FILLET_R, GAP, RAIL_W
        acc = QColor(ink.accent)
        # The elbow in the accent, the band in cream, the cap in amber.
        elbow = QPainterPath()
        elbow.addRoundedRect(QRectF(0, 0, RAIL_W + ELBOW_R, h + ELBOW_R), ELBOW_R, ELBOW_R)
        clip = QPainterPath()
        clip.addRect(QRectF(0, 0, RAIL_W, h))
        p.fillPath(elbow.intersected(clip), acc)
        fillet = QPainterPath()
        fillet.addRect(QRectF(RAIL_W - 1, BAND_H - 1, FILLET_R + 1, FILLET_R + 1))
        hole = QPainterPath()
        hole.addEllipse(QRectF(RAIL_W, BAND_H, FILLET_R * 2, FILLET_R * 2))
        p.fillPath(fillet.subtracted(hole), acc)
        p.fillRect(QRectF(RAIL_W - 1, 0, 8, BAND_H), acc)
        p.fillRect(QRectF(RAIL_W + 8 + GAP, 0, w - RAIL_W - 8 - GAP - CAP_W - GAP, BAND_H),
                   QColor(CREAM))
        cap = QPainterPath()
        cap.addRoundedRect(QRectF(w - CAP_W, 0, CAP_W + BAND_H / 2, BAND_H),
                           BAND_H / 2, BAND_H / 2)
        cap_clip = QPainterPath()
        cap_clip.addRect(QRectF(w - CAP_W, 0, CAP_W, BAND_H))
        p.fillPath(cap.intersected(cap_clip), QColor(ink.amber))

    def band_text(self, ink) -> str:
        return CREAM_INK

    def paint_fill(self, p: QPainter, w: int, h: int, ink) -> None:
        path = QPainterPath()
        path.addRoundedRect(QRectF(0, -40, w, h + 40), 40, 40)
        clip = QPainterPath()
        clip.addRect(QRectF(0, 4, w, h - 4))
        p.fillPath(path.intersected(clip), QColor(ink.accent))
        dark = QColor(CREAM_INK)
        dark.setAlpha(90)
        for i, frac in enumerate((0.7, 0.45, 0.85)):
            y = h - 20 - (2 - i) * 12
            if y > 10:
                p.fillRect(QRectF(16, y, (w - 32) * frac, 6), dark)

    def paint_pill(self, p: QPainter, btn, ink) -> None:
        colour, glow = _lamp_colour(btn, ink, ink.amber, LAMP_OFF)
        side = 14
        rect = QRectF(16, (btn.height() - side) / 2, side, side)
        p.setRenderHint(QPainter.Antialiasing)
        if glow:
            _glow(p, rect, colour, round_=True)
        else:
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(colour))
            p.drawEllipse(rect)

    holder_margins = (14, 12, 14, 12)
    frame_indent = 0

    def paint_frame(self, p: QPainter, frame, ink) -> None:
        pass                      # the bezel is the body's own border

    def qss(self, ink, s: str) -> str:
        fam = self.family()
        return super().qss(ink, s) + f"""
{s} QPushButton#edcarsPill {{
    background-color: {CREAM};
    color: {CREAM_INK};
    border: none;
    border-top-left-radius: 22px;
    border-bottom-left-radius: 22px;
    border-top-right-radius: 6px;
    border-bottom-right-radius: 6px;
    font-size: {self.pt(12)};
    letter-spacing: 2px;
    padding: 11px 16px 9px 40px;
}}
{s} QPushButton#edcarsPill:hover {{ background-color: {CREAM_HI}; }}
{s} QPushButton#edcarsPill:checked {{ background-color: {ink.accent}; color: {CREAM_INK}; }}
{s} QPushButton#edcarsPill[pulse="on"] {{ background-color: {ink.red}; color: {CREAM_INK}; }}
{s} QPushButton#edcarsPill[pulse="dim"] {{ background-color: {CREAM}; color: {CREAM_INK}; }}
{s} QLabel#edcarsFrameTitle {{ background-color: {CREAM}; color: {CREAM_INK};
    font-family: "{fam}"; font-size: {self.pt(10)}; font-weight: bold;
    letter-spacing: 3px; padding: 1px 12px; border-radius: 4px; }}
{s} QWidget#edcarsFrameBody {{ background-color: {ink.block_bg};
    border: 6px solid {CREAM}; border-radius: 16px; }}
{s} QWidget#edcarsRadio {{ background-color: {ink.title_bg}; }}
{s} QPushButton[role="helm"] {{
    background-color: {CREAM};
    color: {CREAM_INK};
    border-radius: 14px;
    letter-spacing: 2px;
}}
{s} QPushButton[role="helm"]:hover {{ background-color: {CREAM_HI}; }}
{s} QPushButton[role="helm"][lit="true"] {{ background-color: {ink.accent}; color: {CREAM_INK}; }}
{s} QPushButton[role="helm"]:disabled {{ background-color: {ink.title_bg}; color: {ink.dim}; }}
{s} QLabel#helmGroupTitle {{ color: {ink.amber}; letter-spacing: 2px; }}
"""

    def dialog_qss(self, ink, s: str) -> str:
        return super().dialog_qss(ink, s) + f"""
{s} QLabel[role="section"] {{ color: {ink.amber}; font-weight: bold; letter-spacing: 2px; }}
{s} QDialogButtonBox QPushButton {{
    background-color: {CREAM}; color: {CREAM_INK}; border-radius: 14px; letter-spacing: 2px;
}}
{s} QDialogButtonBox QPushButton:hover {{ background-color: {CREAM_HI}; }}
{s} QDialogButtonBox QPushButton[role="primary"],
{s} QDialogButtonBox QPushButton:default {{ background-color: {ink.accent}; color: {CREAM_INK}; }}
"""


# ── ROGUE ─────────────────────────────────────────────────────────────────────

PLATE = "#23262a"          # the panels
PLATE_EDGE = "#34383d"
RIVET = "#4a4f55"
BEZEL = "#2e3236"          # round a screen
TAPE = "#e8dcb5"           # masking tape
TAPE_HI = "#f4ead0"
MARKER = "#1a1a1a"
RUST = "#7a4526"
RUST_EDGE = "#8f5532"
RUST_RIVET = "#4a2a16"
TOGGLE_ON = "#c9ccd1"
TOGGLE_OFF = "#6b7077"
LAMP_DARK = "#3a2a18"


def _rivets(p: QPainter, r: QRectF, colour: str) -> None:
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(colour))
    for x, y in ((r.left() + 6, r.top() + 6), (r.right() - 12, r.top() + 6),
                 (r.left() + 6, r.bottom() - 12), (r.right() - 12, r.bottom() - 12)):
        p.drawEllipse(QRectF(x, y, 6, 6))


class Rogue(Console):
    id = H.ROGUE_ID
    face_file = "VT323-Regular.ttf"
    face_fallback = "Monospace"
    synthetic_bold = False
    scale = 1.45
    label_file = "PermanentMarker-Regular.ttf"
    label_fallback = "Comic Sans MS"
    painted_pills = True

    def weight(self) -> str:
        return "normal"           # a CRT has no bold

    def header_margins(self) -> tuple[int, int]:
        from gui.edcars import RAIL_W
        return RAIL_W + 28, 34

    def paint_header(self, p: QPainter, w: int, h: int, ink) -> None:
        from gui.edcars import BAND_H, RAIL_W
        p.setRenderHint(QPainter.Antialiasing)
        plate = QRectF(1, 1, w - 2, BAND_H + 4)
        path = QPainterPath()
        path.addRoundedRect(plate, 8, 8)
        p.fillPath(path, QColor(PLATE))
        p.setPen(QPen(QColor(PLATE_EDGE), 2))
        p.drawPath(path)
        _rivets(p, plate, RIVET)
        # The CRT the title and clock glow in.
        crt = QRectF(RAIL_W + 14, 6, w - RAIL_W - 14 - 20, BAND_H - 8)
        screen = QPainterPath()
        screen.addRoundedRect(crt, 10, 10)
        p.fillPath(screen, QColor(ink.block_bg))
        line = QColor(ink.fg)
        line.setAlpha(14)
        y = crt.top() + 1
        while y < crt.bottom():
            p.fillRect(QRectF(crt.left() + 4, y, crt.width() - 8, 1), line)
            y += 3
        # A strip of tape over the rail's head, with the ship's papers on it.
        p.save()
        p.translate(24, BAND_H / 2 + 2)
        p.rotate(-3)
        p.fillRect(QRectF(0, -13, RAIL_W - 48, 26), QColor(TAPE))
        p.setPen(QColor(MARKER))
        p.setFont(self.label_font(13))
        p.drawText(QRectF(0, -13, RAIL_W - 48, 26), Qt.AlignCenter, "FLIGHT DECK")
        p.restore()

    def band_text(self, ink) -> str:
        return ink.fg

    def fitting_label_font(self, text: str, width: float, pt: float) -> QFont:
        """The marker as large as ``pt`` and no larger than fits ``width``:
        "EXPLORATION" written on tape is wider than "HELM"."""
        from PySide6.QtGui import QFontMetricsF
        f = self.label_font(pt)
        while pt > 8 and QFontMetricsF(f).horizontalAdvance(text) > width:
            pt -= 0.5
            f = self.label_font(pt)
        return f

    def paint_fill(self, p: QPainter, w: int, h: int, ink) -> None:
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(8, 8, w - 16, h - 12)
        if r.height() < 24:
            return
        path = QPainterPath()
        path.addRoundedRect(r, 6, 6)
        p.fillPath(path, QColor(RUST))
        p.setPen(QPen(QColor(RUST_EDGE), 2))
        p.drawPath(path)
        _rivets(p, r, RUST_RIVET)

    def paint_pill(self, p: QPainter, btn, ink) -> None:
        p.setRenderHint(QPainter.Antialiasing)
        w, h = btn.width(), btn.height()
        lamp, glow = _lamp_colour(btn, ink, ink.fg, LAMP_DARK)
        # The toggle on the right, thrown up when its section is showing.
        tw, th = 22, min(36, h - 8)
        tr = QRectF(w - tw - 8, (h - th) / 2, tw, th)
        p.setPen(QPen(QColor(RIVET), 2))
        p.setBrush(QColor("#121416"))
        p.drawRoundedRect(tr, 6, 6)
        knob_h = th / 2 - 4
        ky = tr.top() + 3 if btn.isChecked() else tr.bottom() - 3 - knob_h
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(TOGGLE_ON if btn.isChecked() else TOGGLE_OFF))
        p.drawRoundedRect(QRectF(tr.left() + 4, ky, tw - 8, knob_h), 3, 3)
        # The lamp beside it.
        lr = QRectF(tr.left() - 20, (h - 12) / 2, 12, 12)
        if glow:
            _glow(p, lr, lamp, round_=True)
        else:
            p.setBrush(QColor(lamp))
            p.drawEllipse(lr)
        # The tape, a little askew, with the section on it in marker.
        tape = QRectF(8, h / 2 - 15, lr.left() - 18, 30)
        tilt = (-1.0, 0.6, -0.5, 1.0, -0.8, 0.4, -0.4)[sum(map(ord, btn.text())) % 7]
        p.save()
        p.translate(tape.center())
        p.rotate(tilt)
        local = QRectF(-tape.width() / 2, -tape.height() / 2, tape.width(), tape.height())
        p.fillRect(local, QColor(TAPE_HI if btn.underMouse() else TAPE))
        p.setPen(QColor(MARKER))
        room = local.adjusted(8, 0, -4, 0)
        p.setFont(self.fitting_label_font(btn.text(), room.width(), 13))
        p.drawText(room, Qt.AlignLeft | Qt.AlignVCenter, btn.text())
        p.restore()
        if btn.hasFocus():
            p.setPen(QPen(QColor(ink.fg), 1, Qt.DotLine))
            p.setBrush(Qt.NoBrush)
            p.drawRect(QRectF(2, 2, w - 4, h - 4))

    holder_margins = (12, 22, 12, 12)
    frame_indent = 0

    def paint_frame(self, p: QPainter, frame, ink) -> None:
        p.setRenderHint(QPainter.Antialiasing)
        top = frame.title.geometry().center().y()
        bezel = QPainterPath()
        bezel.addRoundedRect(QRectF(0, top, frame.width(), frame.height() - top), 22, 22)
        p.fillPath(bezel, QColor(BEZEL))

    def qss(self, ink, s: str) -> str:
        lab = self.label_family()
        return super().qss(ink, s) + f"""
{s} QPushButton#edcarsPill {{
    background: transparent;
    color: transparent;
    border: none;
    padding: 0px;
    min-height: 46px;
}}
{s} QPushButton#edcarsPill:hover, {s} QPushButton#edcarsPill:checked,
{s} QPushButton#edcarsPill[pulse="on"], {s} QPushButton#edcarsPill[pulse="dim"] {{
    background: transparent; color: transparent; }}
{s} QLabel#edcarsCmdr, {s} QLabel#edcarsClock {{ font-size: {self.pt(19)}; }}
{s} QLabel#edcarsFrameTitle {{ background-color: {TAPE}; color: {MARKER};
    font-family: "{lab}"; font-size: 11pt; font-weight: normal; padding: 0px 10px; }}
{s} QWidget#edcarsFrameBody {{ background-color: {ink.block_bg}; border-radius: 16px; }}
{s} QWidget#edcarsRadio {{ background-color: {PLATE}; border-top: 2px solid {PLATE_EDGE}; }}
{s} QPushButton[role="helm"] {{
    background-color: {PLATE_EDGE};
    color: {ink.fg};
    border: 1px solid {RIVET};
    border-radius: 6px;
    text-align: center;
    padding: 8px 10px 6px 10px;
}}
{s} QPushButton[role="helm"]:hover {{ background-color: #40454b; }}
{s} QPushButton[role="helm"][lit="true"] {{ background-color: {ink.fg}; color: {MARKER}; }}
{s} QPushButton[role="helm"]:disabled {{ background-color: {PLATE}; color: {ink.dim}; }}
{s} QLabel#helmGroupTitle {{ color: {MARKER}; background-color: {TAPE}; font-family: "{lab}";
    font-size: 10pt; font-weight: normal; padding: 0px 8px; }}
"""

    def dialog_qss(self, ink, s: str) -> str:
        lab = self.label_family()
        return super().dialog_qss(ink, s) + f"""
{s} QLabel[role="section"] {{ color: {MARKER}; background-color: {TAPE};
    font-family: "{lab}"; font-size: 11pt; padding: 0px 8px; }}
{s} QDialogButtonBox QPushButton {{
    background-color: {PLATE_EDGE}; color: {ink.fg}; border: 1px solid {RIVET};
    border-radius: 6px;
}}
{s} QDialogButtonBox QPushButton:hover {{ background-color: #40454b; }}
{s} QDialogButtonBox QPushButton[role="primary"],
{s} QDialogButtonBox QPushButton:default {{ background-color: {ink.fg}; color: {MARKER}; }}
"""


CONSOLES: dict[str, Console] = {c.id: c for c in (Console(), Order(), Rebel(), Rogue())}

# ── Which one is worn ─────────────────────────────────────────────────────────

_ACTIVE: Optional[Console] = None


def set_active(console_id: Optional[str]) -> Optional[Console]:
    """The console the window is wearing, or None for the Dashboard layout.
    Set once, when the window is built; dialogs opened from it follow it."""
    global _ACTIVE
    _ACTIVE = CONSOLES.get(str(console_id or "")) if console_id is not None else None
    return _ACTIVE


def active() -> Optional[Console]:
    return _ACTIVE


def worn() -> Console:
    """The console in use, or EDCARS's own when none is."""
    return _ACTIVE or CONSOLES[H.EDCARS_ID]
