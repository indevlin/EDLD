"""tui/widget_values.py — what a form widget holds, as the text a setting stores.
"""

from __future__ import annotations


def widget_text(widget) -> str:
    """The widget's value as text, with any "nothing selected" as ""."""
    value = getattr(widget, "value", "")
    if value is None or value is False:
        return ""
    try:
        from textual.widgets import Select
        if isinstance(value, type(Select.NULL)) or value is Select.BLANK:
            return ""
    except Exception:
        pass
    return str(value)
