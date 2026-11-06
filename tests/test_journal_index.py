"""
tests/test_journal_index.py — every journal read once, and only what is new.

core/journal_index.py keeps where each event is in each journal; the history
readers ask it for the events they want instead of decoding every line of
every journal themselves. These check that what it hands back is exactly what
reading the files gives, that it follows the journals as the game writes them
(appended lines, a line still being written, a new journal) and as nothing
should (a file rewritten, shortened or deleted), and that the readers moved
onto it ask for every event they use.
"""
from __future__ import annotations

import ast
import json
import os
import re
import sys
import time
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.journal_index import JournalIndex, journal_sort_key  # noqa: E402


def _ev(name, ts="2026-11-03T15:00:00Z", **kw):
    return {"timestamp": ts, "event": name, **kw}


def _line(ev) -> str:
    # The game's own spacing: { "timestamp":"…", "event":"…", … }
    body = ", ".join(f'"{k}":{json.dumps(v)}' for k, v in ev.items())
    return "{ " + body + " }\r\n"


def _write(path: Path, events, mode="w"):
    with open(path, mode, encoding="utf-8", newline="") as fh:
        for ev in events:
            fh.write(_line(ev))


def _direct(jdir: Path):
    out = []
    for p in sorted(jdir.glob("Journal*.log"), key=lambda p: journal_sort_key(p.name)):
        for raw in p.read_text(encoding="utf-8").splitlines():
            try:
                out.append((p.name, json.loads(raw)))
            except ValueError:
                pass
    return out


@pytest.fixture
def jdir(tmp_path):
    d = tmp_path / "journals"
    d.mkdir()
    _write(d / "Journal.2026-11-01T100000.01.log",
           [_ev("Fileheader"), _ev("Commander", Name="X", FID="F1"),
            _ev("LoadGame", Commander="X"), _ev("CrewHire", Name="Ann"),
            _ev("ReceiveText", Message="hi")])
    _write(d / "Journal.2026-11-02T100000.01.log",
           [_ev("Fileheader"), _ev("LoadGame"), _ev("NpcCrewPaidWage", NpcCrewName="Ann", Amount=5)])
    return d


def _idx(jdir, tmp_path):
    return JournalIndex(jdir, tmp_path / "index.sqlite3")


def test_everything_in_journal_order(jdir, tmp_path):
    idx = _idx(jdir, tmp_path)
    assert list(idx.events()) == _direct(jdir)
    assert idx.files() == sorted(p.name for p in jdir.glob("Journal*.log"))


def test_only_the_events_asked_for(jdir, tmp_path):
    idx = _idx(jdir, tmp_path)
    got = [ev["event"] for _f, ev in idx.events({"CrewHire", "NpcCrewPaidWage"})]
    assert got == ["CrewHire", "NpcCrewPaidWage"]
    assert [ev["event"] for _f, ev in idx.events({"LoadGame"}, newest_first=True)] == \
        ["LoadGame", "LoadGame"]
    f, ev = idx.last({"LoadGame"})
    assert f == "Journal.2026-11-02T100000.01.log"
    assert idx.last({"Nothing"}) is None
    assert idx.count({"Fileheader"}) == 2 and idx.count() == 8
    only = [f for f, _ev in idx.events(None, files=["Journal.2026-11-01T100000.01.log"])]
    assert set(only) == {"Journal.2026-11-01T100000.01.log"} and len(only) == 5


def test_old_and_new_names_interleave_by_date(tmp_path):
    d = tmp_path / "j"
    d.mkdir()
    _write(d / "Journal.2026-01-02T100000.01.log", [_ev("A")])
    _write(d / "Journal.211231120000.01.log", [_ev("Old")])     # 2021, old style
    idx = _idx(d, tmp_path)
    assert [ev["event"] for _f, ev in idx.events()] == ["Old", "A"]


def test_appended_lines_and_a_line_still_being_written(jdir, tmp_path):
    idx = _idx(jdir, tmp_path)
    assert idx.count({"Died"}) == 0
    live = jdir / "Journal.2026-11-02T100000.01.log"
    with open(live, "a", encoding="utf-8", newline="") as fh:
        fh.write(_line(_ev("Died")))
        fh.write('{ "timestamp":"2026-11-03T15:00:01Z", "event":"Resur')   # half a line
    assert idx.count({"Died"}) == 1
    assert idx.count({"Resurrect"}) == 0
    with open(live, "a", encoding="utf-8", newline="") as fh:
        fh.write('rect", "Cost":1 }\r\n')
    assert idx.count({"Resurrect"}) == 1
    assert list(idx.events()) == _direct(jdir)


def test_a_last_line_without_a_newline_counts_when_whole(tmp_path):
    d = tmp_path / "j"
    d.mkdir()
    (d / "Journal.2026-11-01T100000.01.log").write_text(
        json.dumps(_ev("A")) + "\n" + json.dumps(_ev("B")), encoding="utf-8")
    assert [ev["event"] for _f, ev in _idx(d, tmp_path).events()] == ["A", "B"]


def test_a_new_journal_and_one_deleted(jdir, tmp_path):
    idx = _idx(jdir, tmp_path)
    assert len(idx.files()) == 2
    _write(jdir / "Journal.2026-11-03T100000.01.log", [_ev("Fileheader"), _ev("Location")])
    assert idx.last({"Location"})[0] == "Journal.2026-11-03T100000.01.log"
    (jdir / "Journal.2026-11-01T100000.01.log").unlink()
    assert idx.count({"CrewHire"}) == 0
    assert list(idx.events()) == _direct(jdir)


def test_a_journal_rewritten_is_read_again(jdir, tmp_path):
    idx = _idx(jdir, tmp_path)
    old = jdir / "Journal.2026-11-01T100000.01.log"
    assert idx.count({"CrewHire"}) == 1
    # Shorter: read again from the start.
    _write(old, [_ev("Fileheader"), _ev("CrewFire", Name="Ann")])
    assert idx.count({"CrewHire"}) == 0 and idx.count({"CrewFire"}) == 1
    # The same size, different content, later: read again too.
    text = old.read_text(encoding="utf-8").replace("CrewFire", "CrewXire")
    time.sleep(0.01)
    old.write_text(text, encoding="utf-8", newline="")
    os.utime(old, ns=(time.time_ns(), time.time_ns() + 10_000_000))
    assert idx.count({"CrewFire"}) == 0 and idx.count({"CrewXire"}) == 1
    assert list(idx.events()) == _direct(jdir)


def test_it_persists_and_a_second_open_reads_nothing(jdir, tmp_path):
    idx = _idx(jdir, tmp_path)
    assert idx.refresh() == 8
    idx.close()
    again = _idx(jdir, tmp_path)
    assert again.refresh() == 0
    assert list(again.events()) == _direct(jdir)


def test_a_damaged_index_is_rebuilt(jdir, tmp_path):
    path = tmp_path / "index.sqlite3"
    path.write_bytes(b"this is not a database" * 100)
    idx = JournalIndex(jdir, path)
    assert list(idx.events()) == _direct(jdir)


def test_an_index_that_cannot_be_written_lives_in_memory(jdir, tmp_path):
    blocker = tmp_path / "file"
    blocker.write_text("x")
    idx = JournalIndex(jdir, blocker / "sub" / "index.sqlite3")   # parent is a file
    assert list(idx.events()) == _direct(jdir)


# ── the readers ask for every event they use ─────────────────────────────────

def _compared_names(src: str, var: str) -> set[str]:
    names = set(re.findall(rf'\b{var}\s*(?:==|!=)\s*"([A-Za-z]+)"', src))
    for m in re.finditer(rf'\b{var}\s+(?:not\s+)?in\s*[\(\{{\[]([^)\}}\]]*)[\)\}}\]]', src, re.S):
        names |= set(re.findall(r'"([A-Za-z]+)"', m.group(1)))
    return names


def _method_source(path: Path, cls: str, method: str) -> str:
    src = path.read_text(encoding="utf-8")
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == cls:
            for fn in node.body:
                if isinstance(fn, ast.FunctionDef) and fn.name == method:
                    return ast.get_source_segment(src, fn)
    raise AssertionError(f"{cls}.{method} not found")


def test_journal_history_asks_for_every_event_it_reads():
    from components.journal_history import HISTORY_EVENTS
    body = _method_source(ROOT / "components" / "journal_history.py",
                          "JournalHistoryPlugin", "_scan")
    missing = _compared_names(body, "name") - set(HISTORY_EVENTS)
    assert not missing, f"add to _SCANNED: {sorted(missing)}"
    from core.credit_flows import CREDIT_EVENTS
    assert set(CREDIT_EVENTS) <= set(HISTORY_EVENTS)


def test_journal_history_checkpoints_every_accumulator():
    from components.journal_history import _ACC
    src = (ROOT / "components" / "journal_history.py").read_text(encoding="utf-8")
    fn = next(n for n in ast.walk(ast.parse(src))
              if isinstance(n, ast.FunctionDef) and n.name == "_scan")
    before_loop = set()
    for st in fn.body:
        if isinstance(st, ast.For):
            break
        if isinstance(st, (ast.Assign, ast.AnnAssign)):
            for t in (st.targets if isinstance(st, ast.Assign) else [st.target]):
                before_loop |= {n.id for n in ast.walk(t) if isinstance(n, ast.Name)}
    loop_vars = {"jdir", "idx", "files", "sizes", "checkpoint", "resume", "done", "live", "snap"}
    assert before_loop - loop_vars == set(_ACC)


def test_holdings_and_discoveries_ask_for_every_event_they_read():
    from components.holdings import _BOOTSTRAP_EVENTS
    body = _method_source(ROOT / "components" / "holdings.py", "HoldingsPlugin", "_bootstrap_all")
    assert _compared_names(body, "name") <= set(_BOOTSTRAP_EVENTS)
    from components.discoveries import LEDGER_EVENTS
    body = _method_source(ROOT / "components" / "discoveries.py", "Ledger", "apply")
    assert _compared_names(body, "name") <= set(LEDGER_EVENTS)


def test_no_history_reader_globs_the_journals_any_more():
    """Every full-history reader goes through the index. What is left reading
    files directly reads one or a few: the newest journal (find_latest_journal,
    the session-end check), the last four for the hold (cargo), the backups,
    the EDSM gap check (a window of days) and the dossier's own incremental
    ledger."""
    allowed = {"core/journal.py": 2, "components/cargo.py": 1, "components/backups.py": 1,
               "components/edsm_gaps.py": 1, "core/dossier/ledger.py": 1,
               "core/explo_import.py": 1}
    found = {}
    for path in list(ROOT.glob("core/**/*.py")) + list(ROOT.glob("components/*.py")) + [ROOT / "edld.py"]:
        n = len(re.findall(r'glob\(\s*["\']Journal\*\.log|_JOURNAL_GLOB\s*=', path.read_text(encoding="utf-8")))
        if n:
            found[str(path.relative_to(ROOT))] = n
    assert found == allowed


# ── Journal History: the checkpoint ─────────────────────────────────────────

def _history(jdir, checkpoint):
    import threading
    from components.journal_history import JournalHistoryPlugin
    p = JournalHistoryPlugin.__new__(JournalHistoryPlugin)
    p.core = types.SimpleNamespace(journal_dir=jdir, gui_queue=None)
    p.scan_done = threading.Event()
    p.results = {}
    p._checkpoint = checkpoint
    p._scan()
    return p.results


def _session(day: int, sold: int):
    ts = f"2026-10-{day:02d}T10:00:00Z"
    return [_ev("Fileheader", ts), _ev("LoadGame", ts, FID="F1", Credits=1000 * day),
            _ev("FSDJump", ts, StarSystem=f"S{day}"),
            _ev("Scan", ts, ScanType="Detailed", SystemAddress=day, BodyID=1,
                PlanetClass="Water world", WasDiscovered=False),
            _ev("MarketSell", ts, Count=1, TotalSale=sold, AvgPricePaid=1),
            _ev("Bounty", ts, TotalReward=50 * day),
            _ev("PowerplayMerits", ts, MeritsGained=day, Power="Nakato Kaine")]


def test_a_resumed_scan_is_the_full_scan(tmp_path):
    from components.journal_history import _Checkpoint
    d = tmp_path / "j"
    d.mkdir()
    for day in range(1, 6):
        _write(d / f"Journal.2026-10-{day:02d}T100000.01.log", _session(day, 100 * day))
    ck = _Checkpoint(d, path=tmp_path / "ck.pickle")
    first = _history(d, ck)
    assert ck.path.exists()
    # Two more sessions, and the newest of the first five grew.
    with open(d / "Journal.2026-10-05T100000.01.log", "a", encoding="utf-8", newline="") as fh:
        fh.write(_line(_ev("MarketSell", "2026-10-05T11:00:00Z", Count=1, TotalSale=7)))
    for day in (6, 7):
        _write(d / f"Journal.2026-10-{day:02d}T100000.01.log", _session(day, 100 * day))
    resumed = _history(d, ck)
    from core import journal_index
    journal_index.forget()
    full = _history(d, _Checkpoint(d, path=tmp_path / "other.pickle"))
    assert resumed == full and resumed != first


def test_a_checkpoint_for_other_journals_is_not_used(tmp_path):
    from components.journal_history import _Checkpoint
    d = tmp_path / "j"
    d.mkdir()
    for day in range(1, 4):
        _write(d / f"Journal.2026-10-{day:02d}T100000.01.log", _session(day, 10))
    ck = _Checkpoint(d, path=tmp_path / "ck.pickle")
    _history(d, ck)
    from core.journal_index import index_for
    files, sizes = index_for(d).files(), index_for(d).file_stats()
    assert ck.load(files, sizes)[0] is not None
    # An older journal changed: not the journals it covered.
    _write(d / "Journal.2026-10-01T100000.01.log", _session(1, 99))   # same size
    later = time.time_ns() + 10_000_000
    os.utime(d / "Journal.2026-10-01T100000.01.log", ns=(later, later))
    assert ck.load(index_for(d).files(), index_for(d).file_stats())[0] is None
    # Another EDLD (or a changed scan): its key differs.
    ck.key = "something else"
    assert ck.load(files, sizes)[0] is None


def test_two_runs_sharing_one_index_add_each_line_once(jdir, tmp_path):
    """Two EDLD profiles reading one journal folder share its index."""
    import threading
    path = tmp_path / "shared.sqlite3"
    a, b = JournalIndex(jdir, path), JournalIndex(jdir, path)
    a.refresh()
    live = jdir / "Journal.2026-11-02T100000.01.log"
    _write(live, [_ev("Died", f"2026-11-03T15:00:{i:02d}Z") for i in range(50)], mode="a")
    threads = [threading.Thread(target=x.refresh) for x in (a, b)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert a.count({"Died"}) == b.count({"Died"}) == 50
    assert list(b.events()) == _direct(jdir)
