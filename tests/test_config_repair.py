"""core/config.py repair_config(): hand-edited config.toml mistakes."""
from __future__ import annotations

import tomllib

from core.config import repair_config


def _repair(tmp_path, text: str):
    p = tmp_path / "config.toml"
    p.write_bytes(text.encode("utf-8"))
    notes = repair_config(p)
    return notes, p.read_text(encoding="utf-8")


def test_windows_path_in_double_quotes_at_root(tmp_path):
    notes, text = _repair(
        tmp_path, 'JournalFolder = "C:\\Users\\me\\Downloads\\EDLOGS"\r\n')
    assert len(notes) == 2
    assert tomllib.loads(text) == {
        "Settings": {"JournalFolder": "C:\\Users\\me\\Downloads\\EDLOGS"}}


def test_valid_escapes_in_a_path_are_kept_as_typed(tmp_path):
    _, text = _repair(tmp_path, '[Settings]\nJournalFolder = "C:\\temp\\new"\n')
    assert tomllib.loads(text)["Settings"]["JournalFolder"] == "C:\\temp\\new"


def test_unc_path(tmp_path):
    _, text = _repair(tmp_path, '[Settings]\nJournalFolder = "\\\\nas\\share\\ED" # x\n')
    assert tomllib.loads(text)["Settings"]["JournalFolder"] == "\\\\nas\\share\\ED"


def test_path_with_an_apostrophe_is_escaped(tmp_path):
    _, text = _repair(tmp_path, '[Settings]\nJournalFolder = "C:\\Users\\o\'neil\\ED"\n')
    assert tomllib.loads(text)["Settings"]["JournalFolder"] == "C:\\Users\\o'neil\\ED"


def test_escaped_path_and_clean_file_are_left_alone(tmp_path):
    original = '[Settings]\nJournalFolder = "C:\\\\Users\\\\me"\nUseUTC = true\n'
    notes, text = _repair(tmp_path, original)
    assert notes == [] and text == original


def test_root_setting_joins_existing_section(tmp_path):
    notes, text = _repair(tmp_path, "UseUTC = true\nMystery = 1\n\n[Settings]\nWarnNoKills = 5\n")
    parsed = tomllib.loads(text)
    assert parsed["Settings"] == {"UseUTC": True, "WarnNoKills": 5}
    assert parsed["Mystery"] == 1
    assert notes == ["UseUTC: moved under [Settings]"]


def test_ambiguous_root_key_stays(tmp_path):
    notes, _ = _repair(tmp_path, "Enabled = true\n")
    assert notes == []


def test_unparseable_result_is_not_written(tmp_path):
    original = "UseUTC = true\n[Settings]\nUseUTC = false\n"
    notes, text = _repair(tmp_path, original)
    assert notes == [] and text == original
