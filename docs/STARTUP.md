# EDLD Start-up

How EDLD gets from launch to live without reading every journal every time,
and what it keeps on disk to do so.

## What it used to do

Everything EDLD shows that reaches back before the current game session — the
crew member and what they have been paid, the massacre stack, the fighter, the
hull, the career figures, the vouchers held, the fleet, unsold discoveries —
comes from the journals. Each of those readers opened every journal and
decoded every line itself to find the few events it wanted. With 263 journals
(81 MB) that was about six full passes at every start, most of it spent on
chat, signal, music and cargo lines nobody wanted, and the window did not open
until the slowest of them on the main thread had finished. Starts took 9 s,
15 s with a fresh data folder, and grew with every session played.

## The journal index

`core/journal_index.py` keeps a small SQLite index of every event in every
journal: which journal, where in it, and what event. It holds positions, not
copies — the journals stay the record — so it is small (14 MB for those 263
journals) and can always be thrown away.

* **The first start** after installing reads each journal once to build it:
  under a second for 81 MB.
* **Every start after** reads only what the game has written since: new
  journals, and the new end of the one it was writing. A start with nothing
  new reads nothing.
* **A reader asks for events by name** — the crew events, the mission events,
  the career scan's own list — and gets exactly those, in journal order,
  decoded. Nothing else is read.

It follows the journals as the game writes them, a line at a time, and copes
with what the game never does: a journal deleted, shortened or rewritten is
read again from its first line. A line still being written waits for the next
look.

## The career scan carries on

Session / Career's lifetime figures are a running total over every journal.
They are kept as they stood after every journal but the newest — which the
game may still be writing — and the next start carries on from there, reading
only the journal the last run was writing and any since. A journal that has
changed underneath it, a new EDLD version, or a change to the scan itself
means a full scan, which takes about half a second.

## The window opens first

The history bootstraps, the session restore, the startup summary and the
server now run first thing on the monitor thread, before the current journal
is replayed — the same order as before — rather than before the window
opens. The desktop window and the terminal dashboard open at once and fill in
as the history lands.

## The last session, while the journals load

Until the current journal has been replayed, every window shows what it
showed at the end of the last run, dimmed, and the status line says
*Showing the last session — reading the journals…*. When the replay finishes
the windows are redrawn with the live figures and come back to full
brightness. Paired EDAM devices are served the same until then.

What the windows last showed is kept in your commander's data folder and
written when EDLD exits (and every five minutes while it runs). A new EDLD
version starts without it.

## What is kept, and where

| File | Where | What |
|---|---|---|
| `journal-index-<id>.sqlite3` | `cache/` in EDLD's data directory, one per journal folder | Where each event is in each journal: file, position, length, event name |
| `journal-history-<id>.pickle` | the same | The career scan's running totals after every journal but the newest |
| `last_session.pickle` | your commander's data folder | What each window showed at the end of the last run |

All three are rebuilt if deleted, and nothing in them leaves your computer.
Deleting the `cache` folder makes the next start read every journal once
more.

## Times

263 journals, 81 MB; the same machine, before and after:

| | Before | After |
|---|---|---|
| Window open (EDCARS) | 7.4 s | 0.9 s |
| Live, terminal output, everyday start | 8.5–9.2 s | 1.7–2.0 s |
| Live, first start after installing (index built) | — | 2.8 s |
| Live, fresh data folder | 12.6–15.1 s | 5.1 s |

The rest of an everyday start is the replay of the current journal, which
depends on how long the current game session has been, not on the history.
