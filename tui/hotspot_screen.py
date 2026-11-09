"""tui/hotspot_screen.py — Add or edit a ring hotspot. Fields come from
``core.ring_hotspots.FIELDS``; identity fields are disabled once it exists."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label, Select

from core.ring_hotspots import FIELDS, IDENTITY
from tui.widget_values import widget_text


class HotspotScreen(ModalScreen):
    """``hid`` None: a new hotspot. Dismissed with Escape or Cancel."""

    BINDINGS = [("escape", "dismiss", "Close")]

    def __init__(self, core, plugin, hid: str | None = None) -> None:
        super().__init__()
        self._core = core
        self._plugin = plugin
        self._hid = hid
        self._form, self._heading = plugin.form_for(hid)

    def compose(self) -> ComposeResult:
        with Vertical(id="hotspot-dialog"):
            yield Label("RING HOTSPOT", classes="pref-title")
            yield Label(self._heading, id="hotspot-heading", classes="pref-note")
            with VerticalScroll(id="hotspot-fields"):
                for f in FIELDS:
                    current = str(self._form.get(f.key, "") or "")
                    fixed = bool(self._hid) and f.key in IDENTITY
                    with Horizontal(classes="pref-row"):
                        yield Label(f.label, classes="key")
                        if f.kind == "choice":
                            options = list(f.choices)
                            if current and current not in options:
                                options.append(current)
                            kwargs = {"id": f"hs-{f.key}", "classes": "pref-choice",
                                      "allow_blank": True, "disabled": fixed}
                            if current:
                                kwargs["value"] = current
                            yield Select([(c, c) for c in options], **kwargs)
                        elif f.kind == "bool":
                            yield Select([("No", ""), ("Yes", "true")], value=current or "",
                                         id=f"hs-{f.key}", classes="pref-choice",
                                         allow_blank=False)
                        else:
                            yield Input(value=current, placeholder=f.hint, id=f"hs-{f.key}",
                                        classes="pref-input", disabled=fixed)
            yield Label("", id="hotspot-result", classes="pref-note")
            with Horizontal(classes="pref-buttons"):
                yield Button("Save", id="hs-save", variant="primary")
                yield Button("Cancel", id="hs-cancel")

    #: Rows for border, padding, title, heading, result line and buttons.
    _CHROME_ROWS = 12

    def on_mount(self) -> None:
        self._fit()

    def on_resize(self, _event) -> None:
        self._fit()

    def _fit(self) -> None:
        """Fields get the terminal height left after the chrome."""
        try:
            fields = self.query_one("#hotspot-fields", VerticalScroll)
        except Exception:
            return
        fields.styles.max_height = max(3, int(self.app.size.height * 0.9) - self._CHROME_ROWS)

    def values(self) -> dict:
        out: dict = {}
        for f in FIELDS:
            try:
                out[f.key] = widget_text(self.query_one(f"#hs-{f.key}"))
            except Exception:
                continue
        return out

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "hs-cancel":
            self.dismiss()
            return
        if event.button.id != "hs-save":
            return
        result = self._plugin.submit_form_for(self._hid, self.values())
        if result.startswith(("recorded", "updated")) or result == "nothing to change":
            self.dismiss()
        else:
            self.query_one("#hotspot-result", Label).update(result)
