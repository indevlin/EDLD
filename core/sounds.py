"""core/sounds.py — short cues for callouts.

Eight sounds in ``sounds/``, made with earcongen (one family, so they read as
related and sit at the same loudness):

    target_new        a targeted system no one has reported         (rise)
    target_unscanned  known, but its bodies not all reported        (rise, held)
    target_done       every body already reported                   (level)
    clear             safe to sample; a threshold passed            (leap up)
    found             a prospector hit you asked for                (up and down)
    low               a resource running low: hold, limpets, fuel   (down and up)
    warning           something about to be lost                    (fall, urgent)
    attention         something worth a look                        (fall)
"""
from __future__ import annotations

import array
import sys
import threading
import wave
from pathlib import Path

CUES = ("target_new", "target_unscanned", "target_done", "clear", "found",
        "low", "warning", "attention")

_lock = threading.Lock()
_cache: dict[str, tuple[array.array, int, int]] = {}
_failed = False


def _dir() -> Path:
    base = getattr(sys, "_MEIPASS", None)
    return (Path(base) if base else Path(__file__).resolve().parents[1]) / "sounds"


def _load(cue: str):
    if cue in _cache:
        return _cache[cue]
    path = _dir() / f"{cue}.wav"
    with wave.open(str(path), "rb") as w:
        frames = w.readframes(w.getnframes())
        rate, channels = w.getframerate(), w.getnchannels()
    samples = array.array("h")
    samples.frombytes(frames)
    _cache[cue] = (samples, rate, channels)
    return _cache[cue]


def _note_failure(why: str) -> None:
    global _failed
    if _failed:
        return
    _failed = True
    try:
        from core import debug as _dbg
        _dbg.log(f"Callout sounds unavailable: {why}", level="WARNING")
    except Exception:
        pass


def play(cue: str, volume: int = 70, state=None) -> bool:
    """Play a cue at ``volume`` percent. Returns at once; False when it will
    not play (unknown cue, replaying the journal, no audio)."""
    if cue not in CUES or _failed:
        return False
    if state is not None and getattr(state, "in_preload", False):
        return False
    vol = max(0, min(int(volume), 100)) / 100.0
    if vol <= 0:
        return False
    threading.Thread(target=_play, args=(cue, vol), daemon=True,
                     name=f"sound-{cue}").start()
    return True


def _play(cue: str, vol: float) -> None:
    try:
        import miniaudio
    except Exception as exc:
        _note_failure(f"miniaudio is not installed ({exc})")
        return
    try:
        samples, rate, channels = _load(cue)
        if vol < 1.0:
            samples = array.array("h", (int(s * vol) for s in samples))

        def stream():
            pos = 0
            need = yield b""
            while pos < len(samples):
                n = need * channels
                chunk = samples[pos:pos + n]
                pos += n
                need = yield chunk

        with _lock:
            dev = miniaudio.PlaybackDevice(output_format=miniaudio.SampleFormat.SIGNED16,
                                           nchannels=channels, sample_rate=rate)
            gen = stream()
            next(gen)
            dev.start(gen)
            import time
            time.sleep(len(samples) / channels / rate + 0.15)
            dev.close()
    except Exception as exc:
        _note_failure(f"{type(exc).__name__}: {exc}")
