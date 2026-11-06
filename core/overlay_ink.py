"""
core/overlay_ink.py — the overlay's colours: shadows, backing and contrast.

Pure functions, strings in and strings out, shared by the component that lays
the overlay out and the renderer that draws it. The renderer used to own the
shadow colour, but the renderer is a child process that takes over stdout at
import, so nothing else could use it — and the contrast floor has to know the
backing colour before the frame is sent.

What the overlay draws on
-------------------------
The game, which over one session is a black starfield, a white station
interior and a ring full of ice. No single ink is readable against all three,
which is why the visibility tweaks exist. When the commander gives the text
something of its own to sit on — an outline or a backing panel — that colour
is what the text has to stand out from. Otherwise it is the game, and the game
is overwhelmingly dark.
"""

from __future__ import annotations

import colorsys

#: What the text is assumed to sit on when it has no backing of its own: a
#: dark scene, which is most of what the game shows.
GAME_BACKGROUND = "#0b0e14"

#: Minimum contrast for each role under the contrast floor. 4.5:1 is the
#: usual floor for body text on a page that holds still; the overlay sits on
#: moving, textured scenes, so it asks for more. Values carry the numbers and
#: get the most, which also keeps labels quieter than values.
CONTRAST_TARGETS = {
    "TitleColour": 5.5,
    "LabelColour": 5.5,
    "ValueColour": 8.0,
}


def _rgb(colour: str):
    raw = (colour or "").strip().lstrip("#")
    if len(raw) == 3:
        raw = "".join(ch * 2 for ch in raw)
    if len(raw) != 6:
        raise ValueError(colour)
    return tuple(int(raw[i:i + 2], 16) / 255.0 for i in (0, 2, 4))


def _hex(rgb) -> str:
    return "#" + "".join(f"{int(round(max(0.0, min(1.0, c)) * 255)):02x}"
                         for c in rgb)


def shadow_colour(colour: str) -> str:
    """A shadow colour derived from the text it will sit behind.

    Flat black is the obvious choice and it is wrong twice over. Against a
    tinted palette it reads as a separate colour — a black fringe on Elite
    orange looks like a printing error — and it does nothing at all for dark
    text on the light theme, where the shadow has to be *lighter* than the ink
    to separate it from the background.

    So the shadow keeps the text's hue and moves its lightness to the far end:
    near-black behind light text, near-white behind dark. Saturation is pulled
    down so it reads as depth rather than as a second colour in the palette.
    """
    try:
        r, g, b = _rgb(colour)
    except (ValueError, IndexError):
        return "#000000"
    h, light, sat = colorsys.rgb_to_hls(r, g, b)
    # The threshold is deliberately low. What matters is not whether the ink
    # is light in the abstract but whether it is lighter than what is behind
    # it, and what is behind it is the game — overwhelmingly dark. A midpoint
    # threshold gave the muted amber label colour a near-white shadow, which
    # against a starfield would have been the brightest thing on screen. Only
    # genuinely dark ink, the sort a light theme uses, needs a light shadow.
    return _hex(colorsys.hls_to_rgb(h, 0.06 if light > 0.25 else 0.94,
                                    min(sat, 0.35)))


def backing_colour(colours: dict) -> str:
    """The one colour an outline or backing panel is drawn in.

    Derived from the value colour, the ink that carries the numbers, so a
    theme with light text gets a dark backing and the light theme a pale one.
    One colour for the whole panel, rather than one per line, because the
    contrast floor needs a single thing to measure against.
    """
    return shadow_colour(str(colours.get("ValueColour", "#cfd6e4")))


def relative_luminance(colour: str) -> float:
    def lin(c):
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (lin(c) for c in _rgb(colour))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def blend(ink: str, background: str, alpha: float) -> str:
    """``ink`` drawn at ``alpha`` over ``background``, as one colour."""
    a = max(0.0, min(1.0, alpha))
    return _hex(a * i + (1 - a) * b for i, b in zip(_rgb(ink), _rgb(background)))


def contrast_ratio(a: str, b: str) -> float:
    la, lb = sorted((relative_luminance(a), relative_luminance(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def ensure_contrast(ink: str, background: str, ratio: float,
                    alpha: float = 1.0) -> str:
    """``ink``, with its lightness moved until it meets ``ratio``.

    Hue and saturation are kept, so a theme still looks like itself; only how
    light it is changes, and only as far as it has to. The ink moves away from
    the background — lighter on a dark one, darker on a light one — and is
    measured as it will actually appear, drawn at ``alpha``. If no lightness
    reaches the ratio (faint text on a mid-grey, say) the furthest one is used.
    """
    try:
        r, g, b = _rgb(ink)
        _rgb(background)
    except (ValueError, IndexError):
        return ink

    def seen(colour: str) -> float:
        return contrast_ratio(blend(colour, background, alpha), background)

    if seen(ink) >= ratio:
        return ink
    h, light, sat = colorsys.rgb_to_hls(r, g, b)
    upward = relative_luminance(background) < 0.18
    target = 1.0 if upward else 0.0
    best = _hex(colorsys.hls_to_rgb(h, target, sat))
    if seen(best) < ratio:
        return best
    lo, hi = light, target          # lo fails, hi passes
    for _ in range(24):
        mid = (lo + hi) / 2
        if seen(_hex(colorsys.hls_to_rgb(h, mid, sat))) >= ratio:
            hi = mid
        else:
            lo = mid
    return _hex(colorsys.hls_to_rgb(h, hi, sat))


def apply_contrast_floor(colours: dict, background: str,
                         alpha: float = 1.0) -> dict:
    """``colours`` with each role lifted to its minimum contrast."""
    out = dict(colours)
    for key, ratio in CONTRAST_TARGETS.items():
        if key in out:
            out[key] = ensure_contrast(str(out[key]), background, ratio, alpha)
    return out
