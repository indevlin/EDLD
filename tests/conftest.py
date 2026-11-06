"""
tests/conftest.py — what every test shares.

The journal index (core/journal_index.py) is kept in memory for tests, so a
test's journals never leave a database in the real data directory, and each
test starts with none: a test's temporary folder can reuse a path an earlier
test's journals were indexed under.
"""
import os

import pytest

os.environ["EDLD_JOURNAL_INDEX"] = "memory"


@pytest.fixture(autouse=True)
def _fresh_journal_index():
    from core import journal_index
    journal_index.forget()
    yield
    journal_index.forget()
