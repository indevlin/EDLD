"""core/overlay_ink.py — the overlay's colors: shadows, backing and contrast.
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
    """A shadow color derived from the text it will sit behind.

    Flat black is the obvious choice and it is wrong twice over.
    """
    try:
        r, g, b = _rgb(colour)
    except (ValueError, IndexError):
        return "#000000"
    h, light, sat = colorsys.rgb_to_hls(r, g, b)
    return _hex(colorsys.hls_to_rgb(h, 0.06 if light > 0.25 else 0.94,
                                    min(sat, 0.35)))


def backing_colour(colours: dict) -> str:
    """The one color an outline or backing panel is drawn in."""
    return shadow_colour(str(colours.get("ValueColour", "#cfd6e4")))


def relative_luminance(colour: str) -> float:
    def lin(c):
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (lin(c) for c in _rgb(colour))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def blend(ink: str, background: str, alpha: float) -> str:
    """``ink`` drawn at ``alpha`` over ``background``, as one color."""
    a = max(0.0, min(1.0, alpha))
    return _hex(a * i + (1 - a) * b for i, b in zip(_rgb(ink), _rgb(background)))


def contrast_ratio(a: str, b: str) -> float:
    la, lb = sorted((relative_luminance(a), relative_luminance(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def ensure_contrast(ink: str, background: str, ratio: float,
                    alpha: float = 1.0) -> str:
    """``ink``, with its lightness moved until it meets ``ratio``."""
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
    """``colors`` with each role lifted to its minimum contrast."""
    out = dict(colours)
    for key, ratio in CONTRAST_TARGETS.items():
        if key in out:
            out[key] = ensure_contrast(str(out[key]), background, ratio, alpha)
    return out
