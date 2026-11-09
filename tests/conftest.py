"""tests/conftest.py — what every test shares."""
import os

import pytest

os.environ["EDLD_JOURNAL_INDEX"] = "memory"


@pytest.fixture(autouse=True)
def _fresh_journal_index():
    from core import journal_index
    journal_index.forget()
    yield
    journal_index.forget()
