"""data/mining.py — which commodities can be mined.

Frontier publishes no "mineable" flag.

  * everything in **Minerals** is mined.  That is what the category is for —
    every one of the 39 entries is either a laser yield, a sub-surface
    deposit, or a core motherlode;
  * a **named ten Metals**, which are the refinery outputs.  The rest of the
    category — Aluminium, Steel, Titanium, the rare-goods entries — is
    manufactured or traded, never dug up;
  * a **named four Chemicals**: the three ices and the tritium that fuels
    carriers.
"""

from __future__ import annotations

#: Categories mined in their entirety, by canonical (lowercased, unwrapped)
#: category symbol.
MINEABLE_CATEGORIES: frozenset[str] = frozenset({"minerals"})

#: Metals a refinery produces.  The rest of the Metals category is traded.
MINEABLE_METALS: frozenset[str] = frozenset({
    "cobalt", "copper", "gold", "osmium", "palladium",
    "platinum", "praseodymium", "samarium", "silver", "thorium",
})

#: Chemicals taken from ice rings, plus the tritium carriers run on.
MINEABLE_CHEMICALS: frozenset[str] = frozenset({
    "hydrogenperoxide", "liquidoxygen", "tritium", "water",
})

#: Every named exception to the category rule, squashed for comparison.
MINEABLE_NAMES: frozenset[str] = MINEABLE_METALS | MINEABLE_CHEMICALS


def _squash(text: str) -> str:
    """Lowercase and strip everything that is not a letter or digit."""
    return "".join(ch for ch in str(text or "").lower() if ch.isalnum())


#: Frontier wraps the category as ``$MARKET_category_minerals;``; other
#: sources send the bare display name.  Squashing alone is not enough — it
#: would leave ``marketcategoryminerals``, which matches nothing.
_CATEGORY_WRAPPER = "marketcategory"


def _category_key(category: str) -> str:
    """Reduce a category to its bare symbol, whichever form it arrives in."""
    key = _squash(category)
    if key.startswith(_CATEGORY_WRAPPER):
        key = key[len(_CATEGORY_WRAPPER):]
    return key


def is_mineable(name: str = "", category: str = "") -> bool:
    """True when a mining laser, sub-surface charge, or core can produce this.
    """
    if _category_key(category) in MINEABLE_CATEGORIES:
        return True
    return _squash(name) in MINEABLE_NAMES
