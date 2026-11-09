"""gui/deposits_table.py — Mining → Surface Sites: the surface survey as a
RecordTable. Columns are the shared sheet's dashboard columns."""
from __future__ import annotations

from core.deposit_form import AMOUNT_LEVELS, DENSITY_LEVELS
from gui.record_table import ID_ROLE, RecordTable, Spec  # noqa: F401

#: (heading, record key, form key when editable)
COLUMNS = (
    ("System", "system_name", None),
    ("Body", "body_name", None),
    ("Gravity", "gravity", None),
    ("Mining Site", "signal_no", "signal_no"),
    ("Commodity", "commodity_display", None),
    ("Amount", "amount", "amount"),
    ("Density", "density_observed", "density_observed"),
    ("Rigs", "rigs", "rigs"),
    ("Depleted", "depleted_on", "depleted_on"),
    ("Notes", "notes", "notes"),
)
CHOICES = {"amount": AMOUNT_LEVELS, "density_observed": DENSITY_LEVELS}


def cell_text(rec: dict, key: str) -> str:
    v = rec.get(key)
    if key == "commodity_display":
        return v or rec.get("commodity", "") or ""
    if key == "density_observed":
        return v or rec.get("density_claimed", "") or ""
    if key == "gravity":
        return f"{float(v):.2f}" if v not in (None, "") else ""
    if key == "depleted_on":
        return (v or "")[:10]
    if key == "notes":
        return " ".join((v or "").split())
    return "" if v in (None, "") else str(v)


def _records(plugin) -> list[dict]:
    return plugin.deposit_records()


def _save(plugin, dep_id: str, key: str, value: str) -> str:
    return plugin.submit_form_for(dep_id, {key: value})


def _edit(plugin, parent, dep_id) -> bool:
    if not dep_id:
        return False
    from gui.deposit_dialog import DepositDialog
    return bool(DepositDialog(plugin, parent, dep_id=dep_id).exec())


SPEC = Spec(plugin="surface_mining", id_key="deposit_id", columns=COLUMNS,
            records=_records, save=_save, edit=_edit, cell_text=cell_text,
            choices=CHOICES, placeholder="Filter: system, body, commodity, notes…",
            empty="No surface sites recorded", noun="site",
            struck=lambda rec: bool(rec.get("depleted_on")), stretch="notes")


class DepositsTable(RecordTable):
    def __init__(self, core, parent=None) -> None:
        super().__init__(core, SPEC, parent)
