"""
core/region.py — which of the galaxy's 42 regions a position is in.

The codex is kept per region: a species logged in the Inner Orion Spur is new
again in the Norma Arm. The journal names the region only on a CodexEntry, so
for any other system it is worked out with the map in data/regions.py
(klightspeed's EliteDangerousRegionMap, MIT).

The game places a system by its boxel — the cube its SystemAddress encodes —
not by its own coordinates. Against every CodexEntry in a commander's
journals the boxel gives the game's region 253 times in 253; the coordinates
miss a system on a region border. So the address is used whenever known.
"""
from __future__ import annotations

_X0, _Y0, _Z0 = -49985, -40985, -24105


def find_region(x: float, y: float, z: float) -> tuple[int, str] | None:
    """(region id, name) for a position, or None outside the map."""
    from data.regions import regions, regionmap
    px = int((x - _X0) * 83 / 4096)
    pz = int((z - _Z0) * 83 / 4096)
    if px < 0 or pz < 0 or pz >= len(regionmap):
        return None
    rx, pv = 0, 0
    for rl, value in regionmap[pz]:
        if px < rx + rl:
            pv = value
            break
        rx += rl
    if not pv:
        return None
    return pv, regions[pv]


def region_of_address(address: int) -> tuple[int, str] | None:
    """The region of the boxel a SystemAddress (id64) names."""
    try:
        a = int(address)
    except (TypeError, ValueError):
        return None
    mc = a & 7
    z = (((a >> 3) & (0x3FFF >> mc)) << mc) * 10 + _Z0
    y = (((a >> (17 - mc)) & (0x1FFF >> mc)) << mc) * 10 + _Y0
    x = (((a >> (30 - mc * 2)) & (0x3FFF >> mc)) << mc) * 10 + _X0
    return find_region(x, y, z)


def region_for(address=None, star_pos=None) -> tuple[int, str] | None:
    """By the address when there is one, else the coordinates."""
    if address:
        r = region_of_address(address)
        if r:
            return r
    return region_of(star_pos) if star_pos else None


def region_of(star_pos) -> tuple[int, str] | None:
    try:
        x, y, z = (float(v) for v in star_pos)
    except (TypeError, ValueError):
        return None
    return find_region(x, y, z)


def region_id_from_codex(token: str) -> int | None:
    """``$Codex_RegionName_18;`` → 18."""
    t = str(token or "")
    try:
        return int(t.rsplit("_", 1)[1].rstrip(";"))
    except (IndexError, ValueError):
        return None
