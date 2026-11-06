"""
tui/blocks/career.py — Career block (Textual).

Career block: nine tabs in fixed order — Summary,
Combat, Explore, Exobio, Mining, Trade, Credits, Carrier, PPlay.

The Summary tab is a genuine career summary: it pulls the headline
figures from every other tab into one place — wealth, combat,
exploration, exobiology, mining, trade, missions, on-foot, PowerPlay,
fleet carrier, and the top earning and spending categories — so the tab
answers "how is my career going" without tabbing through the other
eight.  It is built from ``core.summary_model.career_sections()``.

That model is shared with the Session window, which renders the same
sections in the same order at session scope.  The two windows are meant
to show the same things at different scopes, so they are built from one
model rather than two renderers that would drift apart.  Current-session
activity used to live at the bottom of this tab; it now has a window of
its own (tui/blocks/session.py) and full height to go with it.

All other tabs are lifetime activity sourced from the journal_history
scan plus the most recent in-game Statistics event.

The Credits tab carries the journal-derived earnings/spending ledger
introduced in v20260515.  In-game Statistics fields like
``Trading.Goods_Sold`` sit at zero for many commanders even after
hundreds of tonnes sold; journal events are authoritative.
"""
from __future__ import annotations

from textual.app        import ComposeResult
from textual.widgets    import Label, TabbedContent, TabPane
from textual.containers import VerticalScroll

from tui.block_base     import TuiBlock


#: Session leads: it is the tab you want on a glance mid-flight, where the
#: lifetime figures below it change on a scale of weeks.
from core.windows.career import TABS as _TABS  # noqa: E402
_ALL_TABS = [(title, f"car-tab-{key}") for title, key in _TABS]


# Moved to core/windows/career.py; kept importable from here.
from core.windows.career import _fmt_distance, _fmt_pledged  # noqa: E402,F401


class CareerBlock(TuiBlock):
    BLOCK_TITLE = "CAREER"

    def _compose_body(self) -> ComposeResult:
        with TabbedContent(id="car-tabs"):
            for title, pane_id in _ALL_TABS:
                with TabPane(title, id=pane_id):
                    yield VerticalScroll(id=f"{pane_id}-scroll")

    # ── Refresh ───────────────────────────────────────────────────────────────
    #
    # What each tab shows is core/windows/career.py, drawn the same way in the
    # desktop window and on EDAM.

    def refresh_data(self) -> None:
        from core.windows import career as W
        for tab in W.tabs(self.core):
            self._repopulate(f"car-tab-{tab.id}", self.render_rows(tab.rows))

    def _repopulate(self, pane_id: str, rows: list) -> None:
        try:
            scroll = self.query_one(f"#{pane_id}-scroll", VerticalScroll)
        except Exception:
            return
        scroll.remove_children()
        scroll.mount(*(rows or [Label("—", classes="dim")]))


