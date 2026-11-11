"""tui/blocks/engineering.py — Engineering window (Textual): Fitting and Materials.

Fitting draws core/windows/engineering.py's rows: each slot fitted, with the
target beside it, the work left and the materials it takes. The ship list,
and the buttons for the target build, run along the top.
"""
from __future__ import annotations

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Horizontal, VerticalScroll
from textual.widgets import Label, Select, Static, TabbedContent, TabPane

from core.windows import engineering as EW
from tui.block_base import TuiBlock


class EngineeringBlock(TuiBlock):
    BLOCK_TITLE = "ENGINEERING"

    def __init__(self, core, **kw) -> None:
        super().__init__(core, **kw)
        self._key = ""
        self._shown: list = []
        self._apply_shown: list = []

    def compose(self) -> ComposeResult:
        yield Label("ENGINEERING", classes="block-title")
        with TabbedContent(id="eng-tabs"):
            with TabPane("Fitting", id="eng-pane-fitting"):
                yield Select([], id="eng-ship", prompt="Ship", allow_blank=True)
                with Horizontal(id="eng-actions"):
                    yield Static(">> Target", id="eng-target-btn", classes="footer-lbl")
                    yield Static(">> Clear", id="eng-clear-btn", classes="footer-lbl")
                    yield Static(">> Shopping list", id="eng-shop-btn", classes="footer-lbl")
                with Horizontal(id="eng-plan-bar"):
                    yield Select([], id="eng-apply", prompt="Apply to", allow_blank=True)
                    with Horizontal(id="eng-plan-actions"):
                        yield Static(">> Apply", id="eng-apply-btn", classes="footer-lbl")
                        yield Static(">> Delete plan", id="eng-delete-btn",
                                     classes="footer-lbl")
                yield VerticalScroll(id="eng-fit")
            with TabPane("Materials", id="eng-pane-materials"):
                with TabbedContent(id="eng-mat-tabs"):
                    for key, label in EW.GRADES:
                        with TabPane(label, id=f"eng-mat-pane-{key}"):
                            yield VerticalScroll(id=f"eng-mat-{key}")

    # ── Refresh ───────────────────────────────────────────────────────────────

    def refresh_data(self) -> None:
        for page in EW.materials(self.core).pages:
            self._fill(f"#eng-mat-{page.id}", page.rows)
        self._refresh_fitting()

    def _refresh_fitting(self) -> None:
        v = EW.fitting(self.core)
        self._key = v.key
        self._sync_select("#eng-ship", EW.choices(self.core), v.key, "_shown")
        self._sync_select("#eng-apply", v.apply_to,
                          v.apply_to[0][0] if v.apply_to else None, "_apply_shown")
        self._show("#eng-target-btn", bool(v.key), ">> Build" if v.planned else ">> Target")
        self._show("#eng-clear-btn", v.has_target and not v.planned)
        self._show("#eng-shop-btn", v.short > 0)
        try:
            self.query_one("#eng-plan-bar").display = v.planned
        except Exception:
            pass
        self._fill("#eng-fit", EW.fitting_tab(self.core).rows)

    def _sync_select(self, selector: str, options, value, attr: str) -> None:
        try:
            sel = self.query_one(selector, Select)
        except Exception:
            return
        if options != getattr(self, attr):
            setattr(self, attr, list(options))
            sel.set_options([(Text(label), key) for key, label in options])
        if value is not None and any(k == value for k, _l in options) and sel.value != value:
            sel.value = value

    def _show(self, selector: str, visible: bool, text: str | None = None) -> None:
        try:
            w = self.query_one(selector, Static)
            w.display = visible
            if text is not None:
                w.update(text)
        except Exception:
            pass

    def _fill(self, selector: str, rows) -> None:
        try:
            scroll = self.query_one(selector, VerticalScroll)
        except Exception:
            return
        scroll.remove_children()
        widgets = self.render_rows(rows)
        if widgets:
            scroll.mount(*widgets)

    # ── Actions ───────────────────────────────────────────────────────────────

    def _plugin(self):
        return self.core._plugins.get("engineering")

    def on_select_changed(self, event: Select.Changed) -> None:
        if event.select.id != "eng-ship":
            return
        event.stop()
        key = event.value
        eng = self._plugin()
        if not isinstance(key, str) or eng is None or key == self._key:
            return
        if key == EW.NEW_PLAN:
            self._new_plan()
            return
        eng.select(key)
        self._refresh_fitting()

    def _new_plan(self) -> None:
        from tui.eng_modals import NewPlanModal
        eng = self._plugin()

        def chosen(ship_type: str) -> None:
            eng.add_plan(ship_type)
            self._refresh_fitting()
            self._open_target()
        self.app.push_screen(NewPlanModal(EW.ship_types(self.core), chosen))
        self._refresh_fitting()

    def _open_target(self) -> None:
        from tui.eng_modals import TargetModal
        eng = self._plugin()
        v = EW.fitting(self.core, self._key)
        if eng is None or not v.key:
            return
        ship_type = v.ship_type

        def read(text):
            return eng.import_build(text, ship_type)

        def got(build):
            eng.set_target(v.key, build)
            self._refresh_fitting()

        title = f"Build for {v.label}" if v.planned else f"Target build for {v.label}"
        self.app.push_screen(TargetModal(title, read, got, current=v.target_url))

    def on_click(self, event) -> None:
        wid = str(getattr(event.widget, "id", ""))
        eng = self._plugin()
        if eng is None or not wid.startswith("eng-") or not wid.endswith("-btn"):
            return
        event.stop()
        if wid == "eng-target-btn":
            self._open_target()
        elif wid == "eng-clear-btn":
            eng.set_target(self._key, None)
            self._refresh_fitting()
        elif wid == "eng-apply-btn":
            ship = self.query_one("#eng-apply", Select).value
            if isinstance(ship, str):
                name = dict(self._apply_shown).get(ship, "the ship")
                ask = (f"Replace {name}'s target with this plan?" if eng.target(ship)
                       else f"Make this plan {name}'s target?")
                self._confirm(ask, lambda: eng.apply_plan(self._key, ship)
                              and self._refresh_fitting())
        elif wid == "eng-delete-btn":
            self._confirm("Forget this planned build?",
                          lambda: (eng.delete_plan(self._key), self._refresh_fitting()))
        elif wid == "eng-shop-btn":
            from tui.eng_modals import ShoppingModal
            kinds = EW.trade_kinds(self.core, self._key)
            self.app.push_screen(ShoppingModal(self, self._key, kinds,
                                               lambda ks: eng.nearest_traders(ks)))

    def _confirm(self, text: str, then) -> None:
        from tui.confirm_modal import ConfirmModal

        def done(ok) -> None:
            if ok:
                then()
        try:
            self.app.push_screen(ConfirmModal(text), done)
        except Exception:
            then()
