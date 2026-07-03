"""Verify test database isolation — guards against wiping the dev database."""

import os
import pytest


def test_test_db_uses_test_database(test_db):
    """The test_db fixture MUST connect to a database whose name contains 'test'."""
    row = test_db.execute("SELECT current_database() AS dbname").fetchone()
    dbname = (row["dbname"] or "").lower()
    assert "test" in dbname, (
        f"Test database name '{dbname}' does not contain 'test'. "
        f"Set TEST_DATABASE_URL to a database name containing 'test'."
    )


def test_rejects_non_test_database_url():
    """Non-test database URLs MUST be rejected with a clear error."""
    from tests.server.conftest import _validate_test_db_url

    bad_urls = [
        "postgresql://aikeeper:aikeeper123@localhost:5432/aikeeper",
        "postgresql://user:pass@host:5432/production_db",
    ]
    for url in bad_urls:
        with pytest.raises(RuntimeError, match="REFUSING"):
            _validate_test_db_url(url)

    # Good URLs should pass
    good_urls = [
        "postgresql://aikeeper:aikeeper123@localhost:5432/aikeeper_test",
        "postgresql://user:pass@host:5432/test_db",
        "postgresql://user:pass@host:5432/testing123",
    ]
    for url in good_urls:
        result = _validate_test_db_url(url)  # should not raise
        assert result == url


def test_validate_handles_query_params():
    """DSN with query parameters should be parsed correctly."""
    from tests.server.conftest import _validate_test_db_url

    url = "postgresql://aikeeper:aikeeper123@localhost:5432/aikeeper_test?sslmode=disable"
    result = _validate_test_db_url(url)  # should not raise
    assert result == url
