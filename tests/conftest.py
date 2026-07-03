import os
import sys

project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

# Tests use PostgreSQL via TEST_DATABASE_URL (see tests/server/conftest.py).
# The old SQLite ":memory:" path has been removed.
