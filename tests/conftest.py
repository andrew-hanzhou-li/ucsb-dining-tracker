import os
import sys
import tempfile
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

# main.py opens dining.db in the current folder when it's imported, so import
# it from a temporary folder to keep tests away from any real database.
_db_dir = tempfile.mkdtemp()
_old_cwd = os.getcwd()
os.chdir(_db_dir)
try:
    import main
finally:
    os.chdir(_old_cwd)

TEST_KEY = "test-key"


@pytest.fixture(autouse=True)
def clean_main(monkeypatch):
    """Empty events table, known API key, normal meal hours, repo as cwd."""
    main.db.execute("DELETE FROM events")
    main.db.commit()
    monkeypatch.setattr(main, "API_KEY", TEST_KEY)
    monkeypatch.setattr(main, "ALWAYS_OPEN", False)
    monkeypatch.chdir(REPO)     # "/" serves index.html from the current folder
    yield main


def add_events(hall, lane, times):
    main.db.executemany("INSERT INTO events VALUES (?, ?, ?)",
                        [(hall, lane, t.isoformat()) for t in times])
    main.db.commit()
