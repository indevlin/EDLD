"""gui/hotspots_table.py — Mining → Ring Hotspots as a RecordTable, with an
Add button for hotspots no scan recorded."""
from __future__ import annotations

from core import ring_hotspots as RH
from gui.record_table import RecordTable, Spec

#: (heading, record key, form key when editable)
COLUMNS = (
    ("System", "system_name", None),
    ("Body", "body_name", None),
    ("Ring", "ring", None),
    ("Ring Type", "ring_type", "ring_type"),
    ("Reserve", "reserve_level", "reserve_level"),
    ("Commodity", "commodity_display", None),
    ("Overlap", "overlap", "overlap"),
    ("Note", "note", "note"),
)
CHOICES = {"ring_type": RH.RING_TYPE_LEVELS, "reserve_level": RH.RESERVE_LEVELS,
           "overlap": RH.OVERLAPS, "note": RH.MINEABLE}


def cell_text(rec: dict, key: str) -> str:
    v = rec.get(key)
    if key == "commodity_display":
        return v or rec.get("commodity", "") or ""
    return "" if v in (None, "") else str(v)


def _edit(plugin, parent, hid) -> bool:
    from gui.hotspot_dialog import HotspotDialog
    return bool(HotspotDialog(plugin, parent, hid=hid).exec())


SPEC = Spec(plugin="ring_hotspots", id_key="hotspot_id", columns=COLUMNS,
            records=lambda p: p.records(),
            save=lambda p, hid, key, value: p.save_cell(hid, key, value),
            edit=_edit, cell_text=cell_text, choices=CHOICES,
            placeholder="Filter: system, body, ring, commodity, overlap…",
            empty="No ring hotspots recorded — map a ring with the Detailed Surface Scanner",
            noun="hotspot", add_label="Add hotspot…", stretch="note")


class HotspotsTable(RecordTable):
    def __init__(self, core, parent=None) -> None:
        super().__init__(core, SPEC, parent)
