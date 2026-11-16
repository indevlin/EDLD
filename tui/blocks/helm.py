"""tui/blocks/helm.py — the Helm panel (Textual): the game's controls and EDLD's
automation as buttons, along the foot of the terminal dashboard.
"""
from __future__ import annotations

from math import ceil

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Grid, Vertical
from textual.widgets import Button, Label

from core import helm as H
from tui.block_base import TuiBlock

#: Narrowest group, in cells, for balanced_columns. A button is as wide as
#: the longest name in its group, and a cell.
GROUP_CELLS = 24


#: Cells between groups on a line, and between buttons in a group.
GROUP_GAP = 2
BUTTON_GAP = 1


PREV, NEXT = "\u25C0", "\u25B6"


class HelmButton(Button):
    """A Helm cell: one control, or a pair (``ids`` two long) pressed by the
    half clicked, the next by the keyboard."""

    def __init__(self, label, ids: tuple[str, ...], **kw) -> None:
        super().__init__(label, **kw)
        self.ids = ids
        self.side = 1 if len(ids) > 1 else 0

    async def _on_click(self, event) -> None:
        if len(self.ids) > 1:
            self.side = 0 if event.x < self.size.width / 2 else 1
        await super()._on_click(event)

    def target(self) -> str:
        return self.ids[self.side] if len(self.ids) > 1 else self.ids[0]


def cell_id(ids: tuple[str, ...]) -> str:
    return "helm-" + "--".join(ids)


def cell_label(cell) -> Text:
    """A cell's face: its name, a pair's between ◀ and ▶, and an AUTO lamp
    for a sequence that runs on its own."""
    if len(cell) > 1:
        return Text(f"{PREV} {H.pair_label(tuple(b.id for b in cell))} {NEXT}")
    b = cell[0]
    if b.auto is None:
        return Text(b.label)
    return Text.assemble(b.label, " ", ("■", "green" if b.auto else "red"), "auto")


def spans(width: int, line: list[tuple[str, int]], button: int) -> list[int]:
    """Cells each group of a line takes of ``width``: as its columns need,
    the rest shared out by columns, the last taking what rounding leaves."""
    need = [c * button + BUTTON_GAP * (c - 1) for _g, c in line]
    gaps = GROUP_GAP * (len(line) - 1)
    spare = max(0, width - sum(need) - gaps)
    total = sum(c for _g, c in line) or 1
    out = [n + spare * c // total + (GROUP_GAP if i < len(line) - 1 else 0)
           for i, (n, (_g, c)) in enumerate(zip(need, line))]
    out[-1] = max(1, width - sum(out[:-1]))
    return out


class HelmBlock(TuiBlock):
    BLOCK_TITLE = "HELM"

    # Its rules are in tui/theme.py's STRUCTURAL_CSS, where the theme's
    # colors are: a widget's own DEFAULT_CSS cannot see them.

    def __init__(self, core, **kw) -> None:
        super().__init__(core, **kw)
        self._sig: tuple = ()
        self._layout: tuple = ()
        self._helm_context = H.SHIP

    def _compose_body(self) -> ComposeResult:
        yield Label("", id="helm-note")
        yield Grid(id="helm-groups")
        yield Label("", id="helm-status")

    # ── Data ──────────────────────────────────────────────────────────────────

    def _plugin(self):
        return (getattr(self.core, "_plugins", None) or {}).get("automation")

    def view(self) -> H.View:
        auto = self._plugin()
        if auto is None or not hasattr(auto, "helm_view"):
            return H.build_view(False, lambda c: False, lambda c: "",
                                "Automation is not available in this EDLD.")
        return auto.helm_view()

    def shown(self) -> bool:
        auto = self._plugin()
        if auto is None:
            return False
        try:
            on = bool(auto.settings().get("Enabled"))
        except Exception:
            on = False
        ui = getattr(getattr(self.core, "cfg", None), "ui_cfg", None) or {}
        return on and H.panel_wanted(ui)

    def refresh_data(self) -> None:
        want = self.shown()
        if self.display != want:
            self.display = want
        if not want:
            return
        v = self.view()
        self._build(v)
        self._show(v)

    def _show(self, v: H.View) -> None:
        try:
            note = self.query_one("#helm-note", Label)
            note.update(v.note)
            note.display = bool(v.note)
            status = self.query_one("#helm-status", Label)
            text = H.status_line(v)
            if text != getattr(self, "_status_text", None):
                self._status_text = text
                status.update(text)
                if text:
                    wait = getattr(self._plugin(), "RESULT_SECONDS", 8.0)
                    self.set_timer(wait + 0.1, self.refresh_data)
            status.display = bool(text)
        except Exception:
            return
        for g in v.groups:
            for cell in g.cells():
                try:
                    btn = self.query_one("#" + cell_id(tuple(b.id for b in cell)), HelmButton)
                except Exception:
                    continue
                btn.disabled = not any(b.ready for b in cell)
                if len(cell) > 1:
                    btn.tooltip = f"{PREV} {cell[0].label}  ·  {cell[1].label} {NEXT}"
                else:
                    btn.tooltip = cell[0].tip or None
                face = cell_label(cell)
                if str(face) != str(btn.label):
                    btn.label = face

    def _build(self, v: H.View) -> None:
        sig = (v.context,) + tuple((g.id, tuple(b.id for b in g.buttons)) for g in v.groups)
        if sig == self._sig:
            return
        self._sig = sig
        self._helm_context = v.context
        try:
            host = self.query_one("#helm-groups", Grid)
        except Exception:
            return
        boxes = []
        for g in v.groups:
            buttons = []
            for cell in g.cells():
                ids = tuple(b.id for b in cell)
                buttons.append(HelmButton(cell_label(cell), ids, id=cell_id(ids),
                                          classes="helm-bar" if g.bars else ""))
            boxes.append(Vertical(Label(g.label.upper(), classes="helm-group-title"),
                                  Grid(*buttons, classes="helm-buttons"),
                                  classes="helm-group", id=f"helm-group-{g.id}"))
        self._layout = ()
        if not host.children:
            host.mount_all(boxes)
            self.call_after_refresh(self._arrange)
            return
        # Another context's buttons share ids with these: the old ones go
        # first, then the new are mounted and given their state.
        self.run_worker(self._remount(host, boxes, v), exclusive=True, group="helm-build")

    async def _remount(self, host, boxes, v: H.View) -> None:
        self._mounting = True
        try:
            await host.remove_children()
            await host.mount_all(boxes)
        finally:
            self._mounting = False
        self._show(v)
        self.call_after_refresh(self._arrange)

    # ── Layout ────────────────────────────────────────────────────────────────

    def _arrange(self) -> None:
        # Mid-remount the old groups are going and the new not yet whole:
        # the remount arranges them once it is done.
        if getattr(self, "_mounting", False):
            return
        try:
            host = self.query_one("#helm-groups", Grid)
        except Exception:
            return
        boxes = [b for b in host.query(".helm-group") if b.query(".helm-buttons")]
        if not boxes:
            return
        width = max(1, (host.size.width or self.size.width - 4) - 2)
        groups = [(str(b.id or "")[len("helm-group-"):], b) for b in boxes]
        cells = [(g, btn) for g, b in groups for btn in b.query(HelmButton)]
        button = max([6] + [len(str(btn.label)) + 2 for g, btn in cells if g not in H.BARS])
        bar = max([4] + [len(str(btn.label)) + 2 for g, btn in cells if g in H.BARS])
        count = {g: len(b.query(HelmButton)) for g, b in groups}
        lines = H.plan(list(count.items()), self._helm_context, width, button,
                       BUTTON_GAP, GROUP_GAP, bar)
        layout = (width, tuple(tuple(line) for line in lines))
        if layout == self._layout:
            return
        self._layout = layout
        # One grid column a cell: each group spans the cells core.helm.plan's
        # line gives it, so a line's groups sit side by side and the next
        # line starts below.
        host.styles.grid_size_columns = width
        host.styles.grid_columns = "1"
        host.styles.grid_gutter_vertical = 0
        by_id = dict(groups)
        for line in lines:
            tall = H.line_rows(line, count)
            for i, ((gid, cols), span) in enumerate(zip(line, spans(width, line, button))):
                box = by_id[gid]
                box.styles.column_span = span
                box.styles.padding = (0, GROUP_GAP if i < len(line) - 1 else 0, 0, 0)
                grid = box.query(".helm-buttons").first(Grid)
                # Heights set outright: "auto" kept the height of the columns
                # before, and left blank lines under a group that now has fewer
                # rows. Bars side by side, as tall as their line.
                if gid in H.BARS:
                    grid.styles.grid_size_columns = len(grid.children)
                    grid.styles.grid_rows = str(tall)
                    rows = tall
                    for b in grid.children:
                        b.styles.height = tall
                        b.styles.padding = ((tall - 1) // 2, 1, 0, 1)
                else:
                    grid.styles.grid_size_columns = cols
                    rows = ceil(len(grid.children) / cols)
                grid.styles.height = rows
                box.styles.height = rows + 1
                box.refresh(layout=True)
        host.refresh(layout=True)
        self.refresh(layout=True)

    def on_resize(self, _event) -> None:
        self._arrange()

    # ── Pressing ──────────────────────────────────────────────────────────────

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if not isinstance(event.button, HelmButton):
            return
        event.stop()
        auto = self._plugin()
        if auto is not None and hasattr(auto, "press_here"):
            auto.press_here(event.button.target())
