"""
tui/blocks/helm.py — the Helm panel (Textual): the game's controls and EDLD's
automation as buttons, along the foot of the terminal dashboard.

The desktop's gui/blocks/helm.py, in cells: what is in it is core/helm.py,
what can be pressed and why not is the automation component's ``helm_view``.
It is laid out as short as the terminal allows (``arrange``): on a wide one
every group in one row, two rows of buttons each, each group as wide as its
buttons' names; on a narrower one the groups wrap, each group's buttons in as
many columns as its width holds whole names in. Shown while automation is on and the
panel is not turned off in Options → Appearance.

Pressing from a terminal is pressing from another window: the game is
brought to the front first (core/keys.focus_game), on a thread of its own,
and the outcome comes back on the status line.
"""
from __future__ import annotations

from math import ceil

from textual.app import ComposeResult
from textual.containers import Grid, Vertical
from textual.widgets import Button, Label

from core import helm as H
from tui.block_base import TuiBlock

#: Narrowest group, in cells, for balanced_columns. A button is as wide as
#: the longest name in its group, and a cell.
GROUP_CELLS = 24


def balanced_columns(width: int, min_width: int, n: int) -> int:
    cols = H.columns_for(width, min_width, n)
    rows = ceil(n / cols) if n else 1
    return max(1, ceil(n / rows)) if n else 1


#: Cells between groups, and between buttons in a group (the grid gutters).
GROUP_GAP = 2
BUTTON_GAP = 1


def arrange(width: int, labels: list[list[str]]) -> tuple[int, list[int], str, int]:
    """(groups per row, each group's button columns, the grid's column
    widths, the gap between groups) that make the panel as short as it can
    be in ``width`` cells, with every button's name whole where it can be.

    Tried: every group in one row, each as wide as two rows of its buttons
    need, a cell apart; and every count of groups per row at equal widths,
    two cells apart. The shortest wins; of equals, the one whose deepest
    group is shallowest, then the one with more groups to a row. A layout
    that cuts a name short is taken only when none would not.
    """
    n = len(labels)
    cell = [max((len(t) for t in g), default=4) + 2 for g in labels]
    cands = []
    two = [max(1, ceil(len(g) / 2)) for g in labels]
    need = [c * w + BUTTON_GAP * (c - 1) for c, w in zip(two, cell)]
    if sum(need) + (n - 1) <= width:
        height = 1 + max(ceil(len(g) / c) for g, c in zip(labels, two))
        # Each group exactly as wide as it needs, the last taking what is
        # left: shares (fr) round a narrow group down past its longest name.
        widths = " ".join([str(w) for w in need[:-1]] + ["1fr"])
        cands.append((0, height, ceil(max(len(g) for g in labels) / 2), -n,
                      n, two, widths, 1))
    for per_row in range(n, 0, -1):
        group_w = (width - GROUP_GAP * (per_row - 1)) // per_row
        cols = [max(1, min(len(g), (group_w + BUTTON_GAP) // (w + BUTTON_GAP)))
                for g, w in zip(labels, cell)]
        cut = int(any(w > group_w for w in cell))
        height = sum(1 + max(ceil(len(g) / c) for g, c in
                             zip(labels[i:i + per_row], cols[i:i + per_row]))
                     for i in range(0, n, per_row))
        deepest = max(ceil(len(g) / c) for g, c in zip(labels, cols))
        cands.append((cut, height, deepest, -per_row, per_row, cols,
                      " ".join(["1fr"] * per_row), GROUP_GAP))
    best = min(cands, key=lambda c: c[:4])
    return best[4], best[5], best[6], best[7]


class HelmBlock(TuiBlock):
    BLOCK_TITLE = "HELM"

    # Its rules are in tui/theme.py's STRUCTURAL_CSS, where the theme's
    # colours are: a widget's own DEFAULT_CSS cannot see them.

    def __init__(self, core, **kw) -> None:
        super().__init__(core, **kw)
        self._sig: tuple = ()
        self._layout: tuple = ()

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
        try:
            note = self.query_one("#helm-note", Label)
            note.update(v.note)
            note.display = bool(v.note)
            self.query_one("#helm-status", Label).update(v.status)
        except Exception:
            return
        for g in v.groups:
            for b in g.buttons:
                try:
                    btn = self.query_one(f"#helm-{b.id}", Button)
                except Exception:
                    continue
                btn.disabled = not b.ready
                btn.tooltip = b.tip or None

    def _build(self, v: H.View) -> None:
        sig = tuple((g.id, tuple(b.id for b in g.buttons)) for g in v.groups)
        if sig == self._sig:
            return
        self._sig = sig
        try:
            host = self.query_one("#helm-groups", Grid)
        except Exception:
            return
        host.remove_children()
        boxes = []
        for g in v.groups:
            buttons = [Button(b.label, id=f"helm-{b.id}") for b in g.buttons]
            boxes.append(Vertical(Label(g.label.upper(), classes="helm-group-title"),
                                  Grid(*buttons, classes="helm-buttons"),
                                  classes="helm-group"))
        host.mount_all(boxes)
        self._layout = ()
        self.call_after_refresh(self._arrange)

    # ── Layout ────────────────────────────────────────────────────────────────

    def _arrange(self) -> None:
        try:
            host = self.query_one("#helm-groups", Grid)
        except Exception:
            return
        boxes = list(host.query(".helm-group"))
        if not boxes:
            return
        width = max(1, host.size.width or self.size.width - 4)
        labels = [[str(b.label) for b in box.query(Button)] for box in boxes]
        per_row, cols_of, widths, gap = arrange(width, labels)
        layout = (per_row, tuple(cols_of), widths, gap)
        if layout == self._layout:
            return
        self._layout = layout
        host.styles.grid_size_columns = per_row
        host.styles.grid_columns = widths
        # Textual names the gap between columns the vertical gutter.
        host.styles.grid_gutter_vertical = gap
        for box, cols in zip(boxes, cols_of):
            grid = box.query_one(".helm-buttons", Grid)
            grid.styles.grid_size_columns = cols
            # Heights set outright: "auto" kept the height of the columns
            # before, and left blank lines under a group that now has fewer
            # rows.
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
        bid = str(event.button.id or "")
        if not bid.startswith("helm-"):
            return
        event.stop()
        auto = self._plugin()
        if auto is not None and hasattr(auto, "press_here"):
            auto.press_here(bid[len("helm-"):])
