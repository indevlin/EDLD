"""gui/blocks/exploration.py — Exploration window (Qt).

Shows the system the commander is currently in: honk / scan / map state, each
body's current and max-if-mapped cartographic value, high-value-mappable
highlights, bodies with biological signals, and system totals.  Location comes
from the explo_sync component; per-body data from core.explo_view; what the
window shows from core/windows/exploration.py, as in the terminal dashboard
and on EDAM.
"""

from __future__ import annotations

from gui.block_base import GuiBlock
# Moved to core/windows/exploration.py; kept importable from here.
from core.windows.exploration import (  # noqa: F401
    abbr as _abbr, arrow as _arrow, markers as _markers, short as _fmt,
    value_range as _range,
)


class ExplorationBlock(GuiBlock):
    BLOCK_TITLE = "EXPLORATION"

    def _build_body(self, layout) -> None:
        self._sys_lbl = self.hdr("—")
        self._sum_lbl = self.text("", "dim")
        self._scroll = self.scroll()
        layout.addWidget(self._sys_lbl)
        layout.addWidget(self._sum_lbl)
        layout.addWidget(self._scroll, 1)

    def refresh_data(self) -> None:
        # What the window shows is core/windows/exploration.py, drawn the
        # same way in the terminal dashboard and on EDAM.
        from core.windows.exploration import view
        v = view(self.core)
        self._sys_lbl.set_title(v["title"])
        self._sum_lbl.set_text(v["summary"])
        self._scroll.set_rows(self.render_rows(v["rows"]))
