"""gui/blocks/commander.py — Commander / ship / location / vitals block (Qt)."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QPushButton, QTabWidget, QWidget,
)

from gui.block_base import GuiBlock, RowScroll
from gui.markup import to_html

# Moved to core/windows/commander.py; kept importable from here.
from core.ui_helpers import pp_rank_progress  # noqa: E402,F401
from core.windows.ship import fmt_health as _fmt_health  # noqa: E402,F401


class CommanderBlock(GuiBlock):
    BLOCK_TITLE = "COMMANDER"

    def __init__(self, core, theme: str = "default", parent=None,
                 split_fleet: bool = False) -> None:
        #: EDCARS shows the commander's fleet — ships, stored modules, carriers —
        #: as a section of its own. Split, those tabs are built into
        #: ``fleet_tabs``, a widget EDCARS places itself, and the block keeps the
        #: identity tabs; its header lines are left to EDCARS's header, which
        #: already carries the name and squadron. Unsplit, it is unchanged.
        self._split_fleet = bool(split_fleet)
        super().__init__(core, theme=theme, parent=parent)

    def _build_body(self, layout) -> None:
        self._hdr1 = QLabel()
        self._hdr1.setTextFormat(Qt.RichText)
        self._hdr1.setProperty("role", "hdrkey")
        self._hdr1.setContentsMargins(6, 0, 6, 0)
        self._hdr2 = QLabel()
        self._hdr2.setTextFormat(Qt.RichText)
        self._hdr2.setProperty("role", "hdrkey")
        self._hdr2.setContentsMargins(6, 0, 6, 0)
        layout.addWidget(self._hdr1)
        layout.addWidget(self._hdr2)
        if self._split_fleet:
            self._hdr1.setVisible(False)
            self._hdr2.setVisible(False)

        self._tabs = QTabWidget()
        self._tabs.setDocumentMode(True)
        if self._split_fleet:
            self.fleet_tabs = QTabWidget()
            self.fleet_tabs.setDocumentMode(True)
        else:
            self.fleet_tabs = self._tabs

        info = RowScroll()
        self._info = info
        self._tabs.addTab(info, "Info")

        self._ranks = RowScroll()
        self._tabs.addTab(self._ranks, "Ranks")

        # ── Assets tabs ───────────────────────────────────────────────────
        # Absorbed from the former Assets window.  Everything about the
        # commander — who they are, what they have ranked, and what they own
        # — now lives behind one set of tabs instead of two windows competing
        # for the same grid space.
        self._wallet = RowScroll()
        self._tabs.addTab(self._wallet, "Wallet")

        # ── Ships / Modules ───────────────────────────────────────────────────
        self._ships = RowScroll()
        self.fleet_tabs.addTab(self._ships, "Ships")
        self._modules = RowScroll()
        self.fleet_tabs.addTab(self._modules, "Modules")

        # ── Fleet Carrier ─────────────────────────────────────────────────────
        # Rebuilt on every refresh rather than a fixed row set: which rows
        # apply depends on the carrier and on whether CAPI has polled, and
        # rendering absent data as a column of dashes reads like a bug.
        self._carrier = RowScroll()
        # Added on refresh only when a carrier is actually owned.
        self._carrier_added = False


        # Squadron carriers are rare, so this tab is only added when the
        # commander actually has one; an empty tab implying a carrier they do
        # not own would be worse than no tab.
        self._sqcarrier = RowScroll()
        self._sqcarrier_added = False

        layout.addWidget(self._tabs, 1)

        footer = QWidget()
        fl = QHBoxLayout(footer)
        fl.setContentsMargins(6, 2, 6, 2)
        fl.setSpacing(8)
        self._home_btn = QPushButton("Set Home")
        self._home_btn.setProperty("role", "link")
        self._home_btn.clicked.connect(self._on_set_home)
        self._home_lbl = QLabel()
        self._home_lbl.setProperty("role", "dim")
        self._home_lbl.setTextFormat(Qt.RichText)
        self._home_lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        fl.addWidget(self._home_btn, 0)
        fl.addWidget(self._home_lbl, 1)
        layout.addWidget(footer)

    # ── Footer: home search ───────────────────────────────────────────────────

    def _on_set_home(self) -> None:
        cmdr_plugin = self.core._plugins.get("commander")
        spansh      = self.core._plugins.get("spansh")
        if not spansh:
            return

        from gui.search_dialog import SearchDialog

        def _on_select(result: dict | None) -> None:
            if not result or not cmdr_plugin:
                return
            cmdr_plugin.set_home_location(
                result.get("name", ""),
                result.get("system", ""),
                result.get("star_pos"),
            )
            name = result.get("name", "")
            self._home_lbl.setText(to_html(f"→ {name}" if name else "",
                                           self.palette_map))
            self.refresh_data()

        dlg = SearchDialog(
            parent       = self.window(),
            title        = "Set Home Location",
            placeholder  = "System or station name…",
            search_fn    = spansh.search_home,
            result_label = lambda r: (
                f"{'🚉' if r.get('is_station') else '⭐'} {r['name']}"
                + (f"  {r.get('system', '')}" if r.get("is_station") else "")
            ),
            theme        = self.theme,
        )
        dlg.accepted_result.connect(_on_select)
        dlg.exec()

    # ── Refresh ───────────────────────────────────────────────────────────────
    #
    # What each tab shows is core/windows/commander.py, drawn the same way in
    # the terminal dashboard and on EDAM.

    def refresh_data(self) -> None:
        from core.windows import commander as W
        hdr1, hdr2 = W.headers(self.core)
        self._hdr1.setText(to_html(hdr1, self.palette_map))
        self._hdr2.setText(to_html(hdr2, self.palette_map))
        self._info.set_rows(self.render_rows(W.info(self.core).rows))
        self._ranks.set_rows(self.render_rows(W.ranks(self.core).rows))
        self._wallet.set_rows(self.render_rows(W.wallet(self.core).rows))
        self._ships.set_rows(self.render_rows(W.ships(self.core).rows))
        self._modules.set_rows(self.render_rows(W.modules(self.core).rows))
        self._show_tab(self._carrier, "Carrier", "_carrier_added", W.carrier(self.core))
        self._show_tab(self._sqcarrier, "S. Carrier", "_sqcarrier_added",
                       W.squadron_carrier(self.core))
        home = W.home_line(self.core)[1]
        if home:
            self._home_lbl.setText(to_html(home, self.palette_map))

    def _show_tab(self, scroll, title: str, flag: str, tab) -> None:
        """Add or remove a carrier tab with ownership: an empty tab implying
        a carrier the commander does not own is worse than no tab."""
        if tab is None:
            if getattr(self, flag):
                index = self.fleet_tabs.indexOf(scroll)
                if index >= 0:
                    self.fleet_tabs.removeTab(index)
                setattr(self, flag, False)
            return
        if not getattr(self, flag):
            self.fleet_tabs.addTab(scroll, title)
            setattr(self, flag, True)
        scroll.set_rows(self.render_rows(tab.rows))
