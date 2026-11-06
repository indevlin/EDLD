"""
tests/test_sounds.py — the callout cues: one file per cue, all of one format,
and nothing played while the journal is replayed.
"""
from __future__ import annotations

import sys
import wave
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core import sounds  # noqa: E402


def test_every_cue_has_a_short_16_bit_file():
    for cue in sounds.CUES:
        with wave.open(str(ROOT / "sounds" / f"{cue}.wav"), "rb") as w:
            assert w.getsampwidth() == 2
            assert 0.1 < w.getnframes() / w.getframerate() < 3.0
        samples, rate, channels = sounds._load(cue)
        assert len(samples) and rate > 8000 and channels in (1, 2)


def test_when_nothing_plays(monkeypatch):
    started = []
    monkeypatch.setattr(sounds, "_failed", False)      # an earlier test may have found no audio
    monkeypatch.setattr(sounds.threading, "Thread",
                        lambda **k: SimpleNamespace(start=lambda: started.append(k["args"])))
    assert sounds.play("nonsense") is False
    assert sounds.play("found", state=SimpleNamespace(in_preload=True)) is False
    assert sounds.play("found", volume=0) is False
    assert sounds.play("found", volume=150) is True
    assert started == [("found", 1.0)]


def test_the_packaged_build_ships_them():
    src = (ROOT / "packaging" / "build_common.py").read_text(encoding="utf-8")
    assert '"sounds"' in src
