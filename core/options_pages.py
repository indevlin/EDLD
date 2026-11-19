"""core/options_pages.py — the order of Options' pages, in both front ends.

EDLD's own pages and the components' pages share one column, grouped:
setting up, being told things, activities, and the outside world. A
component page named in MERGED is drawn at the foot of the page it names
instead of on a page of its own. Pages not listed follow, alphabetically.
"""
from __future__ import annotations

#: EDLD's own pages: id and name.
CORE = (
    ("pref-tab-general",    "General"),
    ("pref-tab-interface",  "Interface"),
    ("pref-tab-appearance", "Appearance"),
    ("pref-tab-notif",      "Notifications"),
    ("pref-tab-discord",    "Discord"),
    ("pref-tab-combat",     "Combat"),
    ("pref-tab-data",       "Services"),
)

#: Every page's place in the column, by id.
ORDER = (
    "pref-tab-general",
    "pref-tab-interface",
    "pref-tab-appearance",
    "pref-tab-notif",
    "pref-tab-callouts",
    "pref-tab-discord",
    "pref-tab-combat",
    "pref-tab-ksw",
    "pref-tab-routes",
    "pref-tab-automation",
    "pref-tab-survey",
    "pref-tab-data",
    "pref-tab-dossier",
    "pref-tab-overlay",
    "pref-tab-server",
)

#: Component pages drawn at the foot of another page: id → host page id.
MERGED = {
    "pref-tab-backups":  "pref-tab-general",
    "pref-tab-edsmgaps": "pref-tab-data",
}


def arrange(extra: list[tuple]) -> tuple[list[tuple[str, str]], dict[str, list[tuple]]]:
    """The column and the merged pages for ``extra``, the components' pages
    as (id, name, builder) tuples.

    Returns the column as (id, name) pairs, and the merged builders by host
    page id, in the order the components gave them.
    """
    merged: dict[str, list[tuple]] = {}
    own: list[tuple] = []
    for entry in extra:
        host = MERGED.get(str(entry[0]))
        if host:
            merged.setdefault(host, []).append(entry)
        else:
            own.append(entry)
    pages = list(CORE) + [(str(e[0]), str(e[1])) for e in own]
    rank = {pid: i for i, pid in enumerate(ORDER)}
    pages.sort(key=lambda p: (rank.get(p[0], len(ORDER)), p[1].casefold()))
    return pages, merged
