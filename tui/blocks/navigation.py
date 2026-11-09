"""tui/blocks/navigation.py — Navigation block (Textual).

Route first, then the tabs described in core/tooltab.py: FSD, Neutron,
Carrier, Survey, Nearby, Services, Discoveries.

Each of the others is a form and a button.
"""
from __future__ import annotations

import threading
import time

from textual.app        import ComposeResult
from textual.widgets    import (Label, Static, TabbedContent, TabPane, Input, Button,
                                Select, Checkbox)
from textual.containers import VerticalScroll, Horizontal

from tui.block_base     import TuiBlock, KVRow, SecHdr
from core               import route_view as RV
from core               import tooltab as TT


#: How long a footer click result stays on screen before the standing route
#: status reclaims the line.
_FOOTER_MSG_SECONDS = 6.0


class NavigationBlock(TuiBlock):
    BLOCK_TITLE = "NAVIGATION"

    def __init__(self, core, **kw) -> None:
        super().__init__(core, **kw)
        self._footer_msg = ""
        self._footer_msg_at = 0.0
        # What EDLD last put in each pre-filled field; a field still holding
        # it follows the game, one the commander typed in is left alone.
        self._auto: dict[str, str] = {}
        # Tabs the components describe in core/tooltab.py, drawn the same way
        # here and in the desktop window.
        self._tool_tabs: dict[str, TT.ToolTab] = {t.id: t for t in TT.tabs(core)}

    def compose(self) -> ComposeResult:
        yield Label(self.BLOCK_TITLE, classes="block-title")
        yield from self._compose_body()
        # Footer strip, same one-row budget the Cargo block uses.
        with Horizontal(id="nav-footer"):
            yield Static(">> Follow: off", id="nav-follow-btn",
                         classes="footer-lbl")
            yield Static(">> Copy Next", id="nav-copy-btn",
                         classes="footer-lbl")
            yield Static(">> Clear Route", id="nav-clear-btn",
                         classes="footer-lbl")
            yield Label("", id="nav-follow-lbl", classes="dim")

    def _compose_body(self) -> ComposeResult:
        with TabbedContent(id="nav-tabs"):
            # ── Route tab ────────────────────────────────────────────────────
            with TabPane("Route", id="nav-tab-route"):
                yield VerticalScroll(id="nav-route-rows")

            # ── Tool tabs (core/tooltab.py) ──────────────────────────────────
            for tab in self._tool_tabs.values():
                with TabPane(tab.title, id=f"nav-tab-tool-{tab.id}"):
                    with VerticalScroll(id=f"nav-tool-{tab.id}-scroll"):
                        yield Label("", id=f"nav-tool-{tab.id}-intro", classes="dim")
                        for f in tab.fields:
                            wid = f"nav-tool-{tab.id}-f-{f.key}"
                            if f.kind == "choice":
                                opts = [(str(lab), str(val)) for val, lab in f.choices]
                                yield Select(opts, value=str(f.default or f.choices[0][0]),
                                             id=wid, allow_blank=False)
                            elif f.kind == "check":
                                yield Checkbox(f.label, value=bool(f.default), id=wid)
                            else:
                                yield Input(value=str(f.default or ""),
                                            placeholder=f.label, id=wid)
                        yield Button(tab.button, id=f"nav-tool-{tab.id}-run",
                                     variant="primary")
                        yield Label("", id=f"nav-tool-{tab.id}-status", classes="dim")
                        yield VerticalScroll(id=f"nav-tool-{tab.id}-results")

    # ── Button dispatch ───────────────────────────────────────────────────────

    def on_button_pressed(self, event: Button.Pressed) -> None:
        btn_id = event.button.id or ""
        if btn_id.startswith("nav-tool-") and btn_id.endswith("-run"):
            self._launch_tool(btn_id[len("nav-tool-"):-len("-run")])

    # ── Tool tabs (core/tooltab.py) ───────────────────────────────────────────

    def _tool_values(self, tid: str) -> dict:
        tab = self._tool_tabs[tid]
        out = {}
        for f in tab.fields:
            try:
                w = self.query_one(f"#nav-tool-{tid}-f-{f.key}")
            except Exception:
                continue
            if isinstance(w, Select):
                out[f.key] = "" if w.value is Select.BLANK else str(w.value)
            elif isinstance(w, Checkbox):
                out[f.key] = bool(w.value)
            else:
                out[f.key] = w.value
        return out

    def _tool_visibility(self, tid: str) -> None:
        tab = self._tool_tabs.get(tid)
        if tab is None:
            return
        values = self._tool_values(tid)
        for f in tab.fields:
            try:
                self.query_one(f"#nav-tool-{tid}-f-{f.key}").display = \
                    TT.visible(tab, f, values)
            except Exception:
                pass

    def on_mount(self) -> None:
        for tid in self._tool_tabs:
            self._tool_visibility(tid)

    def on_select_changed(self, event: Select.Changed) -> None:
        wid = event.select.id or ""
        if wid.startswith("nav-tool-") and wid.endswith("-f-kind"):
            self._tool_visibility(wid[len("nav-tool-"):-len("-f-kind")])

    def _launch_tool(self, tid: str) -> None:
        tab = self._tool_tabs.get(tid)
        if tab is None:
            return
        values = self._tool_values(tid)
        try:
            self.query_one(f"#nav-tool-{tid}-results", VerticalScroll).remove_children()
            self.query_one(f"#nav-tool-{tid}-status", Label).update("Working…")
        except Exception:
            pass

        def _worker():
            result = TT.run(tab, self.core, values)
            # call_from_thread lives on App, not on Widget/MessagePump, so
            # this goes through self.app; on the block it raised
            # AttributeError after the work was done, leaving "Working…".
            self.app.call_from_thread(self._on_tool_done, tid, result)

        threading.Thread(target=_worker, daemon=True, name=f"nav-tool-{tid}").start()

    def _on_tool_done(self, tid: str, result) -> None:
        try:
            status = self.query_one(f"#nav-tool-{tid}-status", Label)
            box = self.query_one(f"#nav-tool-{tid}-results", VerticalScroll)
        except Exception:
            return
        status.update(result.status)
        box.remove_children()
        widgets = self._rows_widgets(result.rows)
        if widgets:
            box.mount(*widgets)
        if result.route:
            self._refresh_footer()

    @staticmethod
    def _rows_widgets(rows) -> list:
        out = []
        for row in rows or []:
            if row[0] == "hdr":
                out.append(SecHdr(row[1]))
            elif row[0] == "kv":
                out.append(KVRow(row[1], row[2]))
            else:
                out.append(Label(row[1], classes="dim"))
        return out

    def _refresh_tools(self) -> None:
        for tid, tab in self._tool_tabs.items():
            if tab.intro is not None:
                try:
                    self.query_one(f"#nav-tool-{tid}-intro", Label).update(tab.intro(self.core) or "")
                except Exception:
                    pass
            if tab.autofill is None:
                continue
            try:
                fills = tab.autofill(self.core) or {}
            except Exception:
                continue
            for key, value in fills.items():
                try:
                    inp = self.query_one(f"#nav-tool-{tid}-f-{key}", Input)
                except Exception:
                    continue
                slot = f"tool-{tid}-{key}"
                new = RV.autofill(inp.value, self._auto.get(slot), str(value) if value else "")
                if new is not None:
                    inp.value = new
                    self._auto[slot] = new

    # ── Route-follower footer ─────────────────────────────────────────────────

    def _nav_plugin(self):
        return self.core._plugins.get("navigation")

    def on_click(self, event) -> None:
        btn = str(getattr(event.widget, "id", "") or "")
        if btn not in ("nav-follow-btn", "nav-copy-btn", "nav-clear-btn"):
            return
        event.stop()

        nav = self._nav_plugin()
        if nav is None:
            self._set_follow_msg("[red]Navigation component not loaded.[/red]")
            return

        if btn == "nav-follow-btn":
            on = nav.toggle_follow()
            self._set_follow_msg(
                "Following route — next system copies on arrival."
                if on else "Follow off."
            )
        elif btn == "nav-copy-btn":
            ok, msg = nav.copy_next()
            # Over SSH the clipboard lives on the machine running the
            # terminal, not on this host, so the OS backends above cannot
            # reach it.  Textual's copy_to_clipboard emits OSC 52, which the
            # terminal emulator itself honors — the one mechanism that works
            # remotely.  Belt and braces: both are attempted, and a duplicate
            # copy of the same string is harmless.
            system = getattr(self.core.state, "nav_follow_next", "")
            if system:
                try:
                    self.app.copy_to_clipboard(system)
                    if not ok:
                        ok, msg = True, f"Copied {system} (terminal)"
                except Exception:
                    pass
            self._set_follow_msg(msg if ok else f"[yellow]{msg}[/yellow]")
        else:
            self._set_follow_msg(nav.clear_route())

        self._refresh_footer()

    def _set_follow_msg(self, text: str) -> None:
        """Show a transient result message; it decays back to route status."""
        self._footer_msg = text
        self._footer_msg_at = time.monotonic()
        try:
            self.query_one("#nav-follow-lbl", Label).update(text)
        except Exception:
            pass

    def _refresh_footer(self) -> None:
        nav = self._nav_plugin()
        try:
            toggle = self.query_one("#nav-follow-btn", Static)
            label = self.query_one("#nav-follow-lbl", Label)
        except Exception:
            return

        if nav is None:
            toggle.update(">> Follow: n/a")
            label.update("[dim]Navigation component not loaded.[/dim]")
            return

        s = self.core.state
        on = bool(getattr(s, "nav_follow_enabled", False))
        toggle.update(f">> Follow: {'ON' if on else 'off'}")

        # A click result stays visible briefly, then the standing route
        # status takes the line back.
        if self._footer_msg and (time.monotonic() - self._footer_msg_at) < _FOOTER_MSG_SECONDS:
            return
        self._footer_msg = ""
        label.update(getattr(s, "nav_follow_status", "") or "No route")

    # ── Refresh (state-driven content) ────────────────────────────────────────

    def refresh_data(self) -> None:
        self._refresh_route()
        self._refresh_tools()
        self._refresh_footer()

    def _refresh_route(self) -> None:
        try:
            box = self.query_one("#nav-route-rows", VerticalScroll)
        except Exception:
            return
        widgets = self._rows_widgets(RV.route_rows(RV.route_view(self.core)))
        box.remove_children()
        if widgets:
            box.mount(*widgets)
