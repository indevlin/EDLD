"""gui/markup.py — Rich console markup → Qt rich text.

Reusing the strings is the point.

Only the tags the blocks actually emit are translated.
"""

from __future__ import annotations

import html
import re

#: Rich color name → concrete hex.  ``None`` means "use the theme's color",
#: resolved at call time from the active palette so themed output tracks the
#: chosen theme instead of hard-coding one scheme's greens and ambers.
_THEME_COLOURS = {
    "green":   "green",
    "red":     "red",
    "yellow":  "amber",
    "magenta": "accent",
    "cyan":    "accent",
    "blue":    "accent",
    "white":   "fg",
    "dim":     "dim",
}

#: Colors with no palette equivalent, used as-is.
_LITERAL_COLOURS = {
    "black":   "#000000",
    "grey":    "#808080",
    "gray":    "#808080",
}

_TAG_RE = re.compile(r"\[(/?)([a-zA-Z0-9_ #]+)\]")


def _colour(name: str, palette: dict[str, str]) -> str | None:
    key = _THEME_COLOURS.get(name)
    if key:
        return palette.get(key, "")
    if name in _LITERAL_COLOURS:
        return _LITERAL_COLOURS[name]
    if name.startswith("#"):
        return name
    return None


#: A run of two or more spaces, or a space at the very start of the string.
#: These are alignment padding, not word gaps.
_PAD_RE = re.compile(r" {2,}|^ ")


def _keep_padding(escaped: str) -> str:
    """Make alignment padding survive Qt's rich-text whitespace collapsing.

    Qt collapses runs of spaces exactly as a browser does, and every label in
    the GUI is ``Qt.RichText``.

    Only runs of two or more, plus a leading single space, are protected.
    """
    return _PAD_RE.sub(lambda m: "&nbsp;" * len(m.group(0)), escaped)


def to_html(text: str, palette: dict[str, str]) -> str:
    """Convert Rich markup in ``text`` to Qt-compatible HTML.

    ``palette`` is a sigil-free palette dict (see ``core.palette.rgb``).

    A bracketed token that names no tag we recognize is emitted as literal
    text rather than being swallowed.  This matters because the game supplies
    plenty of bracketed strings that were never meant as markup: squadron tags
    render as ``[SOL]``, and faction names of the form ``[XYZ] Corporation``
    are common.  Dropping them would silently corrupt names in the Missions,
    Assets and Colonization windows.
    """
    if not text:
        return ""

    # Escape first, then re-find the markup tags in the escaped text.  Rich
    # markup uses square brackets, which escaping leaves untouched, so the
    # tags survive while any real angle brackets in the data do not.
    escaped = html.escape(str(text))

    out: list[str] = []
    # Each stack entry is (tag_name, closing_html).
    stack: list[tuple[str, str | None]] = []
    pos = 0

    for m in _TAG_RE.finditer(escaped):
        literal = m.group(0)
        out.append(_keep_padding(escaped[pos:m.start()]))
        pos = m.end()
        closing, body = m.group(1), m.group(2).strip().lower()

        if closing:
            if stack:
                _name, closer = stack.pop()
                out.append(literal if closer is None else closer)
            else:
                # A close with nothing open is not markup we produced.
                out.append(literal)
            continue

        parts = [p for p in body.split() if p]
        opened: list[str] = []
        closers: list[str] = []
        for part in parts:
            if part in ("b", "bold"):
                opened.append("<b>")
                closers.insert(0, "</b>")
            elif part in ("i", "italic"):
                opened.append("<i>")
                closers.insert(0, "</i>")
            elif part in ("u", "underline"):
                opened.append("<u>")
                closers.insert(0, "</u>")
            else:
                col = _colour(part, palette)
                if col:
                    opened.append(f'<span style="color:{col}">')
                    closers.insert(0, "</span>")

        if len(opened) != len(parts):
            out.append(literal)
            stack.append((body, None))
            continue

        out.append("".join(opened))
        stack.append((body, "".join(closers)))

    out.append(_keep_padding(escaped[pos:]))
    # Anything still open at the end gets closed so the label's HTML is valid.
    while stack:
        _name, closer = stack.pop()
        if closer:
            out.append(closer)

    return "".join(out)


def strip(text: str) -> str:
    """Return ``text`` with all Rich markup tags removed and nothing escaped.

    Used where a plain string is wanted — window titles, tooltips, and the
    accessible name of a widget.
    """
    if not text:
        return ""
    return _TAG_RE.sub("", str(text))


def has_markup(text: str) -> bool:
    """True when ``text`` contains at least one Rich markup tag."""
    return bool(text) and bool(_TAG_RE.search(str(text)))
