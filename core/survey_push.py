"""core/survey_push.py — Ctrl+G: publish surface sites and ring hotspots now."""
from __future__ import annotations


def push_all(core) -> str:
    """``publish_now()`` of surface_mining and ring_hotspots, as one line;
    "" when neither is loaded."""
    plugins = getattr(core, "_plugins", None) or {}
    parts = []
    for name, label in (("surface_mining", "Sites"), ("ring_hotspots", "Hotspots")):
        plugin = plugins.get(name)
        if plugin is not None and hasattr(plugin, "publish_now"):
            parts.append(f"{label}: {plugin.publish_now()}")
    return " · ".join(parts)
