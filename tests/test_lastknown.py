"""tests/test_lastknown.py — the windows show the last session while the
journals load, and start-up no longer waits for the history.
"""
from __future__ import annotations

import pickle
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core import lastknown as L  # noqa: E402


def _core(preload: bool):
    return SimpleNamespace(state=SimpleNamespace(in_preload=preload))


def test_a_model_answers_from_the_last_session_only_while_warming(tmp_path):
    lk = L.LastKnown(tmp_path / "last.pickle", "v1")
    calls = []

    def model(core, page=None):
        calls.append(page)
        return f"live {len(calls)}"
    m = lk.wrap("x.model", model)

    # Warming with nothing remembered: computed, and not remembered.
    assert m(_core(True)) == "live 1"
    # Live: computed and remembered, per argument.
    assert m(_core(False)) == "live 2"
    assert m(_core(False), page="b") == "live 3"
    # Warming again: the remembered answers, without computing.
    assert m(_core(True)) == "live 2"
    assert m(_core(True), page="b") == "live 3"
    assert len(calls) == 3


def test_the_last_session_is_saved_and_loaded_for_the_same_version(tmp_path):
    path = tmp_path / "last.pickle"
    lk = L.LastKnown(path, "v1")
    lk.wrap("x.m", lambda core: {"rows": [1, 2]})(_core(False))
    lk.wrap("x.bad", lambda core: (lambda: None))(_core(False))   # cannot be pickled
    lk.save()
    saved = pickle.loads(path.read_bytes())
    assert saved["version"] == "v1" and list(saved["values"]) == [("x.m",)]

    again = L.LastKnown(path, "v1")
    again.load()
    assert again.restored
    assert again.wrap("x.m", lambda core: "live")(_core(True)) == {"rows": [1, 2]}

    other = L.LastKnown(path, "v2")
    other.load()
    assert not other.restored
    assert other.wrap("x.m", lambda core: "live")(_core(True)) == "live"


def test_state_first_models_too(tmp_path):
    lk = L.LastKnown(tmp_path / "p", "v")
    m = lk.wrap("core.edcars.strip", lambda state: ["live"])
    assert m(SimpleNamespace(in_preload=False)) == ["live"]
    assert m(SimpleNamespace(in_preload=True)) == ["live"]


def test_every_listed_model_exists():
    import importlib
    for mod, names in L.MODELS.items():
        m = importlib.import_module(mod)
        for n in names:
            assert callable(getattr(m, n, None)), f"{mod}.{n}"


@pytest.fixture
def installed(tmp_path, monkeypatch):
    import importlib
    saved = {}
    for mod, names in L.MODELS.items():
        m = importlib.import_module(mod)
        saved[mod] = {n: getattr(m, n) for n in names}
    monkeypatch.setattr(L, "_installed", None)
    monkeypatch.setattr(L.atexit, "register", lambda fn: None)
    yield
    for mod, fns in saved.items():
        m = importlib.import_module(mod)
        for n, fn in fns.items():
            setattr(m, n, fn)


def test_install_wraps_the_models_and_says_when_it_is_restoring(tmp_path, installed):
    path = tmp_path / "last.pickle"
    first = L.install(_core(False), path=path, version="v")
    from core.windows import commander
    assert hasattr(commander.info, "__wrapped_model__")
    assert not L.restoring(_core(True))           # nothing to restore yet
    first._values[("core.windows.commander.info",)] = "kept"
    first._dirty = True
    first.save()
    L._installed = None
    for mod, names in L.MODELS.items():           # undo, as a new run would start
        import importlib
        m = importlib.import_module(mod)
        for n in names:
            setattr(m, n, getattr(m, n).__wrapped_model__)
    L.install(_core(True), path=path, version="v")
    assert L.restoring(_core(True)) and not L.restoring(_core(False))
    from core.windows import commander as again
    assert again.info(_core(True)) == "kept"


def test_the_history_runs_on_the_monitor_thread():
    """edld.py: the bootstraps, the session restore and the server are in
    _prepare_history, which run_monitor calls first — not between loading the
    components and opening a window."""
    import ast
    src = (ROOT / "edld.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    fns = {n.name: n for n in tree.body if isinstance(n, ast.FunctionDef)}
    prep = ast.get_source_segment(src, fns["_prepare_history"])
    for call in ("bootstrap_crew(", "bootstrap_missions(", "load_session_state(",
                 "emit_summary(", "ServerService("):
        assert call in prep, call
    run = ast.get_source_segment(src, fns["run_monitor"])
    assert run.index("_prepare_history()") < run.index("_run_monitor(")
    top_level_calls = [ast.get_source_segment(src, n) for n in tree.body
                       if isinstance(n, ast.Expr)]
    assert not any("bootstrap_crew" in (c or "") for c in top_level_calls)


def test_the_header_says_nothing_of_fuel_until_the_tank_is_known():
    from core.edcars import _fuel
    st = SimpleNamespace(vessel_mode="ship", fuel_current=128.0, fuel_tank_size=64)
    assert _fuel(st) == ("", "")
    st.fuel_tank_size = 128
    assert _fuel(st)[0] == "100%"
