"""
core/dossier — the documents EDLD writes about a commander.

    ledger.py       reads the journals, incrementally, into a kept state
    sources.py      the survey database, the carrier's CAPI snapshot, career income
    model.py        every page, as blocks both formats share; privacy applied here
    names.py        journal ids as the pages print them
    render_html.py  one self-contained, themed web page
    render_md.py    the same pages as Markdown files
    build.py        reads, keeps and writes; used by components/dossier.py

See docs/DOSSIER.md.
"""
