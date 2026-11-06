"""
gui/blocks/ship_info.py — Ship window (Qt).

The vessel's name, then Cargo, Modules and Engineering. What each shows is
core/windows/ship.py, drawn the same way in the terminal dashboard and on a
paired EDAM device; this file draws it and owns the cargo footer's market
controls.
"""

from __future__ import annotations

from core.ui_helpers import cargo_cols, fmt_cargo_cr, is_limpet
from core.windows.ship import GRADES as _TABS, fmt_health as _fmt_health
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QPushButton, QTabWidget, QVBoxLayout, QWidget,
)
from gui.markup import to_html
from gui.block_base import GuiBlock, RowScroll


# Re-exported from core.ui_helpers; imported from here by tests.
_fmt_cr     = fmt_cargo_cr
_cargo_cols = cargo_cols
_is_limpet  = is_limpet


class ShipInfoBlock(GuiBlock):
    BLOCK_TITLE = "SHIP"

    def _build_body(self, layout) -> None:
        # One header line naming the vessel.  The focus of this window is the
        # ship, not its condition, so the identity is the whole heading.
        self._hdr1 = self.text("", "section-hdr")
        layout.addWidget(self._hdr1)

        self._tabs = QTabWidget()
        self._tabs.setDocumentMode(True)

        # Cargo leads: it changes constantly and is checked far more often
        # than a module list that only moves when something takes damage.
        cargo_page = QWidget()
        cargo_page_layout = QVBoxLayout(cargo_page)
        cargo_page_layout.setContentsMargins(0, 0, 0, 0)

        # The price-source label lives on the title bar, right-aligned, the
        # same place the TUI puts it.
        self._price_src = QLabel()
        self._price_src.setTextFormat(Qt.RichText)
        self._price_src.setProperty("role", "dim")
        self._price_src.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        title_bar = self._title.parentWidget()
        # Rebuild the title row so the source label sits beside the title.
        hdr = QWidget()
        hl = QHBoxLayout(hdr)
        hl.setContentsMargins(0, 0, 8, 0)
        hl.setSpacing(8)
        self._title.setParent(None)
        hl.addWidget(self._title, 1)
        hl.addWidget(self._price_src, 0)
        outer = self.layout()
        outer.insertWidget(0, hdr)

        # Two tabs: Cargo is what the hold contains, Colonisation is what a
        # construction depot still needs.  Same activity from opposite ends.

        self._cargo_scroll = RowScroll()

        cargo_page_layout.addWidget(self._cargo_scroll, 1)

        footer = QWidget()
        fl = QHBoxLayout(footer)
        fl.setContentsMargins(6, 2, 6, 2)
        fl.setSpacing(8)
        self._target_btn = QPushButton("Set Target")
        self._target_btn.setProperty("role", "link")
        self._target_btn.clicked.connect(self._on_set_target)
        self._galavg_btn = QPushButton("Gal. Avg")
        self._galavg_btn.setProperty("role", "link")
        self._galavg_btn.setToolTip(
            "Price the manifest at galactic average, ignoring the target "
            "market and the station docked at")
        self._galavg_btn.clicked.connect(self._on_galactic_average)
        self._target_lbl = QLabel()
        self._target_lbl.setProperty("role", "dim")
        self._target_lbl.setTextFormat(Qt.RichText)
        self._target_lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        fl.addWidget(self._target_btn, 0)
        fl.addWidget(self._galavg_btn, 0)
        fl.addWidget(self._target_lbl, 1)
        cargo_page_layout.addWidget(footer)
        self._tabs.addTab(cargo_page, "Cargo")

        modules_page = QWidget()
        modules_layout = QVBoxLayout(modules_page)
        modules_layout.setContentsMargins(0, 0, 0, 0)
        self._modules_hdr = self.hdr("Modules")
        self._scroll = self.scroll()
        modules_layout.addWidget(self._modules_hdr)
        modules_layout.addWidget(self._scroll, 1)
        self._tabs.addTab(modules_page, "Modules")

        eng_page = QWidget()
        eng_layout = QVBoxLayout(eng_page)
        eng_layout.setContentsMargins(0, 0, 0, 0)

        self._eng_tabs = QTabWidget()
        self._eng_tabs.setDocumentMode(True)
        self._scrolls: dict[str, RowScroll] = {}
        for key, label in _TABS:
            scroll = RowScroll()
            self._scrolls[key] = scroll
            self._eng_tabs.addTab(scroll, label)
        eng_layout.addWidget(self._eng_tabs, 1)
        self._tabs.addTab(eng_page, "Engineering")

        layout.addWidget(self._tabs, 1)

    # ── Target market search ──────────────────────────────────────────────────

    def _on_set_target(self) -> None:
        spansh = self.core._plugins.get("spansh")
        if spansh is None:
            return

        from gui.search_dialog import SearchDialog

        def _on_select(result: dict | None) -> None:
            if not result:
                return
            name    = result.get("name", "")
            raw_rec = result.get("_rec") or result
            spansh.set_target(name, result.get("system", ""), _record=raw_rec)
            self.refresh_data()

        dlg = SearchDialog(
            parent       = self.window(),
            title        = "Set Target Market",
            placeholder  = "Station name…",
            search_fn    = spansh.search,
            result_label = lambda r: f"{r['name']}  {r.get('system', '')}",
            theme        = self.theme,
        )
        dlg.accepted_result.connect(_on_select)
        dlg.exec()

    def _on_galactic_average(self) -> None:
        """Pin the manifest to galactic average.

        One control, both effects: drop the target market and stop quoting
        whatever station happens to be underfoot.  Clearing the target alone
        would fall back to the docked station's prices, which is not what
        "galactic average" means.
        """
        self.core.state.cargo_price_galactic = True
        spansh = self.core._plugins.get("spansh")
        if spansh is not None:
            spansh.clear_target()
        self.refresh_data()

    # ── Refresh ───────────────────────────────────────────────────────────────

    def refresh_data(self) -> None:
        # The window's content is core/windows/ship.py, drawn here as it is
        # in the terminal dashboard and on EDAM.
        from core.windows import ship as W
        self._hdr1.set_text(W.header(self.core))
        mods = W.modules(self.core)
        self._modules_hdr.set_title(mods.heading)
        self._scroll.set_rows(self.render_rows(mods.rows))
        src, target = W.price_source(self.core)
        self._price_src.setText(to_html(f" {src} ", self.palette_map))
        self._target_lbl.setText(to_html(target, self.palette_map))
        self._cargo_scroll.set_rows(self.render_rows(W.cargo(self.core).rows))
        for page in W.engineering(self.core).pages:
            scroll = self._scrolls.get(page.id)
            if scroll is not None:
                scroll.set_rows(self.render_rows(page.rows))
