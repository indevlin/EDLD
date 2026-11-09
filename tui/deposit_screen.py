"""tui/deposit_screen.py — Add or edit the surface deposit you are parked on.
"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label, Select, TextArea

from core.deposit_form import FIELDS
from tui.widget_values import widget_text


class DepositScreen(ModalScreen):
    """A small form over the dashboard, dismissed with Escape."""

    BINDINGS = [("escape", "dismiss", "Close")]

    def __init__(self, core, plugin, dep_id: str | None = None) -> None:
        """``dep_id`` None: the deposit underfoot (form_for_here / submit_form)."""
        super().__init__()
        self._core = core
        self._plugin = plugin
        self._dep_id = dep_id
        self._form, self._heading = (plugin.form_for(dep_id) if dep_id
                                     else plugin.form_for_here())

    def compose(self) -> ComposeResult:
        with Vertical(id="deposit-dialog"):
            yield Label("SURFACE DEPOSIT", classes="pref-title")
            yield Label(self._heading, id="deposit-heading", classes="pref-note")

            # The fields scroll; the heading and the buttons do not.
            with VerticalScroll(id="deposit-fields"):
                for field in FIELDS:
                    current = str(self._form.get(field.key, "") or "")
                    if field.kind == "note":
                        with Horizontal(classes="pref-row dep-note-row"):
                            yield Label(field.label, classes="key")
                            yield self._note_area(field, current)
                        continue
                    with Horizontal(classes="pref-row"):
                        yield Label(field.label, classes="key")
                        if field.kind == "choice":
                            # The value is omitted entirely when there is
                            # nothing to select.
                            kwargs = {"id": f"dep-{field.key}",
                                      "classes": "pref-choice",
                                      "allow_blank": True}
                            # Matched case-insensitively against the options, and
                            # dropped if it matches none. A stored value that is
                            # not an option crashes the same way None did, and one
                            # can reach the store: deposits imported from a shared
                            # sheet are written as the sheet spells them, so
                            # another commander hand-editing a cell to "high" or
                            # "Very High" would take this window down on whoever
                            # opened it next.
                            chosen = next((c for c in field.choices
                                           if c.lower() == current.lower()), None)
                            if chosen:
                                kwargs["value"] = chosen
                            yield Select([(c, c) for c in field.choices], **kwargs)
                        elif field.kind == "bool":
                            yield Select([("No", ""), ("Yes", "true")],
                                         value=current or "",
                                         id=f"dep-{field.key}",
                                         classes="pref-choice", allow_blank=False)
                        else:
                            yield Input(value=current, placeholder=field.hint,
                                        id=f"dep-{field.key}", classes="pref-input",
                                        disabled=bool(self._dep_id)
                                        and field.key == "commodity")

            yield Label("", id="deposit-result", classes="pref-note")
            with Horizontal(classes="pref-buttons"):
                yield Button("Save", id="dep-save", variant="primary")
                yield Button("Cancel", id="dep-cancel")

    #: Rows the dialog spends on everything but the fields: border and
    #: padding, title, heading, the result line and the button row.
    _CHROME_ROWS = 12

    def on_mount(self) -> None:
        self._fit()

    def on_resize(self, _event) -> None:
        self._fit()

    def _fit(self) -> None:
        """Let the fields have whatever the terminal leaves after the chrome."""
        try:
            fields = self.query_one("#deposit-fields", VerticalScroll)
        except Exception:
            return
        room = int(self.app.size.height * 0.9) - self._CHROME_ROWS
        fields.styles.max_height = max(3, room)

    @staticmethod
    def _note_area(field, current: str) -> TextArea:
        """A few lines of wrapping text, whatever Textual release is installed.
        """
        area = TextArea(current, id=f"dep-{field.key}", classes="dep-note")
        for attr, value in (("soft_wrap", True),
                            ("show_line_numbers", False),
                            # Tab moves on to Save, as from every other field.
                            ("tab_behavior", "focus")):
            if hasattr(area, attr):
                try:
                    setattr(area, attr, value)
                except Exception:
                    pass
        return area

    def _values(self) -> dict:
        out: dict = {}
        for field in FIELDS:
            try:
                widget = self.query_one(f"#dep-{field.key}")
            except Exception:
                continue
            if isinstance(widget, TextArea):
                out[field.key] = widget.text
                continue
            out[field.key] = widget_text(widget)
        return out

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "dep-cancel":
            self.dismiss()
            return
        if event.button.id != "dep-save":
            return
        values = self._values()
        result = (self._plugin.submit_form_for(self._dep_id, values) if self._dep_id
                  else self._plugin.submit_form(values))
        # Rejection keeps the screen open with the message.
        if result.startswith(("recorded", "updated")) or result == "nothing to change":
            self.dismiss()
        else:
            self.query_one("#deposit-result", Label).update(result)
