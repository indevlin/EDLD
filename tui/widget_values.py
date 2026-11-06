"""
tui/widget_values.py — what a form widget holds, as the text a setting stores.

A Select with nothing chosen does not hold None. It holds Textual's blank
sentinel — Select.NULL in current releases, Select.BLANK in others, and in at
least one a plain False — and ``str()`` of that is the string "Select.NULL".
Read naively, an Amount left blank on purpose arrived as "Select.NULL" and was
rejected as not one of Low, Medium or High.
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
