"""gui/blocks/navigation.py — Navigation block (Qt).

Route first, then the tabs described in core/tooltab.py: FSD, Neutron,
Carrier, Survey, Nearby, Services, Discoveries.

Each of the others is a form and a button.
"""

from __future__ import annotations

import threading
import time

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QHBoxLayout, QLineEdit, QPushButton, QTabWidget,
    QVBoxLayout, QWidget,
)

from gui.block_base import GuiBlock, RowScroll
from core import route_view as RV
from core import tooltab as TT


#: How long a footer click result stays on screen before the standing route
#: status reclaims the line.
_FOOTER_MSG_SECONDS = 6.0


class NavigationBlock(GuiBlock):
    BLOCK_TITLE = "NAVIGATION"

    #: Emitted from a tab's worker thread: (tab id, ToolResult).
    tool_done = Signal(str, object)

    def _build_body(self, layout) -> None:
        # What EDLD last put in each pre-filled field; a field still holding
        # it follows the game, one the commander typed in is left alone.
        self._auto: dict[str, str] = {}

        self._tabs = QTabWidget()
        self._tabs.setDocumentMode(True)
        self._route_rows = RowScroll()
        self._tabs.addTab(self._route_rows, "Route")
        # Every other tab is described once in core/tooltab.py — the FSD,
        # Neutron and Carrier plot forms, survey routes, nearby systems, the
        # nearest service, discoveries — and drawn the same way here, in the
        # terminal dashboard, and on a paired EDAM device.
        self.tool_done.connect(self._on_tool_done)
        self._tool_tabs: dict[str, TT.ToolTab] = {}
        self._tool_widgets: dict[str, dict] = {}
        for tab in TT.tabs(self.core):
            self._tool_tabs[tab.id] = tab
            self._tabs.addTab(self._make_tool_tab(tab), tab.title)

        layout.addWidget(self._tabs, 1)

        # Footer strip, same one-row budget the Cargo block uses.
        self._footer_msg = ""
        self._footer_msg_at = 0.0

        footer = QWidget()
        fl = QHBoxLayout(footer)
        fl.setContentsMargins(6, 2, 6, 2)
        fl.setSpacing(8)

        self._follow_btn = QPushButton("Follow: off")
        self._follow_btn.setProperty("role", "link")
        self._follow_btn.clicked.connect(self._on_toggle_follow)

        self._copy_btn = QPushButton("Copy Next")
        self._copy_btn.setProperty("role", "link")
        self._copy_btn.clicked.connect(self._on_copy_next)

        self._clear_btn = QPushButton("Clear Route")
        self._clear_btn.setProperty("role", "link")
        self._clear_btn.clicked.connect(self._on_clear_route)

        # TextRow rather than a bare QLabel so it picks up the block's
        # palette and markup handling like every other row in the app.
        self._follow_lbl = self.text("", "dim")
        self._follow_lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)

        fl.addWidget(self._follow_btn, 0)
        fl.addWidget(self._copy_btn, 0)
        fl.addWidget(self._clear_btn, 0)
        fl.addWidget(self._follow_lbl, 1)
        layout.addWidget(footer)

    # ── Route-follower footer ─────────────────────────────────────────────────

    def _nav_plugin(self):
        return self.core._plugins.get("navigation")

    def _set_follow_msg(self, text: str) -> None:
        """Show a transient result message; it decays back to route status."""
        self._footer_msg = text
        self._footer_msg_at = time.monotonic()
        self._follow_lbl.set_text(text)

    def _on_toggle_follow(self) -> None:
        nav = self._nav_plugin()
        if nav is None:
            self._set_follow_msg("[red]Navigation component not loaded.[/red]")
            return
        on = nav.toggle_follow()
        self._set_follow_msg(
            "Following route — next system copies on arrival."
            if on else "Follow off."
        )
        self._refresh_footer()

    def _on_copy_next(self) -> None:
        nav = self._nav_plugin()
        if nav is None:
            self._set_follow_msg("[red]Navigation component not loaded.[/red]")
            return
        ok, msg = nav.copy_next()
        self._set_follow_msg(msg if ok else f"[yellow]{msg}[/yellow]")
        self._refresh_footer()

    def _on_clear_route(self) -> None:
        nav = self._nav_plugin()
        if nav is None:
            self._set_follow_msg("[red]Navigation component not loaded.[/red]")
            return
        self._set_follow_msg(nav.clear_route())
        self._refresh_footer()

    def _refresh_footer(self) -> None:
        nav = self._nav_plugin()
        if nav is None:
            self._follow_btn.setText("Follow: n/a")
            self._follow_lbl.set_text(
                "[dim]Navigation component not loaded.[/dim]")
            return

        s = self.core.state
        on = bool(getattr(s, "nav_follow_enabled", False))
        self._follow_btn.setText(f"Follow: {'ON' if on else 'off'}")

        # A click result stays visible briefly, then the standing route
        # status takes the line back.
        if self._footer_msg and (time.monotonic() - self._footer_msg_at) < _FOOTER_MSG_SECONDS:
            return
        self._footer_msg = ""
        self._follow_lbl.set_text(
            getattr(s, "nav_follow_status", "") or "No route")

    # ── Tool tabs (core/tooltab.py) ───────────────────────────────────────────

    def _make_tool_tab(self, tab: TT.ToolTab) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(6, 6, 6, 6)
        lay.setSpacing(4)
        w: dict = {"fields": {}, "rows": {}}
        intro = self.text("", "dim")
        w["intro"] = intro
        lay.addWidget(intro)
        for f in tab.fields:
            row = QWidget()
            rl = QHBoxLayout(row)
            rl.setContentsMargins(0, 0, 0, 0)
            rl.setSpacing(4)
            if f.kind == "choice":
                ctl = QComboBox()
                for value, label in f.choices:
                    ctl.addItem(str(label), str(value))
                idx = ctl.findData(str(f.default))
                ctl.setCurrentIndex(idx if idx >= 0 else 0)
                if f.key == "kind":
                    ctl.currentIndexChanged.connect(
                        lambda _i, tid=tab.id: self._tool_visibility(tid))
                rl.addWidget(ctl, 1)
            elif f.kind == "check":
                ctl = QCheckBox(f.label)
                ctl.setChecked(bool(f.default))
                rl.addWidget(ctl, 1)
            else:
                ctl = QLineEdit()
                ctl.setPlaceholderText(f.label)
                if f.default:
                    ctl.setText(str(f.default))
                rl.addWidget(ctl, 1)
                if f.system:
                    # The game PC's clipboard: a system name copied from the
                    # galaxy map or anywhere else, one click away.
                    paste = QPushButton("📋")
                    paste.setToolTip("Paste a system name from the clipboard")
                    paste.setProperty("role", "link")
                    paste.clicked.connect(lambda _c=False, e=ctl: self._paste_into(e))
                    rl.addWidget(paste, 0)
            # The terminal dashboard's widget id, for the same field.
            ctl.setObjectName(f"nav-tool-{tab.id}-f-{f.key}")
            w["fields"][f.key] = ctl
            w["rows"][f.key] = row
            lay.addWidget(row)
        btn = QPushButton(tab.button)
        btn.setProperty("role", "primary")
        btn.clicked.connect(lambda _c=False, tid=tab.id: self._launch_tool(tid))
        lay.addWidget(btn)
        w["status"] = self.text("", "dim")
        lay.addWidget(w["status"])
        w["results"] = RowScroll()
        lay.addWidget(w["results"], 1)
        self._tool_widgets[tab.id] = w
        self._tool_visibility(tab.id)
        return page

    @staticmethod
    def _paste_into(edit: QLineEdit) -> None:
        from PySide6.QtWidgets import QApplication
        text = (QApplication.clipboard().text() or "").strip().splitlines()
        if text:
            edit.setText(text[0].strip())

    def _tool_values(self, tid: str) -> dict:
        out = {}
        for key, ctl in self._tool_widgets[tid]["fields"].items():
            if isinstance(ctl, QComboBox):
                out[key] = ctl.currentData()
            elif isinstance(ctl, QCheckBox):
                out[key] = ctl.isChecked()
            else:
                out[key] = ctl.text()
        return out

    def _tool_visibility(self, tid: str) -> None:
        tab = self._tool_tabs.get(tid)
        w = self._tool_widgets.get(tid)
        if tab is None or w is None:
            return
        values = self._tool_values(tid)
        for f in tab.fields:
            w["rows"][f.key].setVisible(TT.visible(tab, f, values))

    def _launch_tool(self, tid: str) -> None:
        tab = self._tool_tabs[tid]
        w = self._tool_widgets[tid]
        values = self._tool_values(tid)
        w["results"].set_rows([])
        w["status"].set_text("Working…")

        def _worker():
            result = TT.run(tab, self.core, values)
            self.tool_done.emit(tid, result)

        threading.Thread(target=_worker, daemon=True, name=f"nav-tool-{tid}").start()

    def _on_tool_done(self, tid: str, result) -> None:
        w = self._tool_widgets.get(tid)
        if w is None or result is None:
            return
        w["status"].set_text(result.status)
        w["results"].set_rows(self._rows_widgets(result.rows))
        if result.route:
            self._refresh_footer()

    def _rows_widgets(self, rows) -> list:
        out = []
        for row in rows or []:
            if row[0] == "hdr":
                out.append(self.hdr(row[1]))
            elif row[0] == "kv":
                out.append(self.kv(row[1], row[2]))
            else:
                out.append(self.text(row[1], "dim"))
        return out

    def _refresh_tools(self) -> None:
        for tid, tab in self._tool_tabs.items():
            w = self._tool_widgets[tid]
            if tab.intro is not None:
                try:
                    w["intro"].set_text(tab.intro(self.core) or "")
                except Exception:
                    pass
            if tab.autofill is None:
                continue
            try:
                fills = tab.autofill(self.core) or {}
            except Exception:
                continue
            for key, value in fills.items():
                ctl = w["fields"].get(key)
                if not isinstance(ctl, QLineEdit):
                    continue
                slot = f"tool-{tid}-{key}"
                new = RV.autofill(ctl.text(), self._auto.get(slot), str(value) if value else "")
                if new is not None:
                    ctl.setText(new)
                    self._auto[slot] = new

    # ── Refresh (state-driven content) ────────────────────────────────────────

    def refresh_data(self) -> None:
        self._route_rows.set_rows(self._route_widgets())
        self._refresh_tools()
        self._refresh_footer()

    def _route_widgets(self) -> list:
        return self._rows_widgets(RV.route_rows(RV.route_view(self.core)))
