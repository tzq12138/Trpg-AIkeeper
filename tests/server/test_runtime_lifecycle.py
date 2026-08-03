import asyncio
import hashlib

import pytest

from src.server.db_adapter import PgConnection
from src.server.runtime_lifecycle import lifecycle_guard


@pytest.mark.asyncio
async def test_cancelled_lifecycle_waiter_cleans_up_blocking_acquire():
    waiter_started = asyncio.Event()

    async def wait_for_guard():
        waiter_started.set()
        async with lifecycle_guard(["character:cancel-safe"]):
            raise AssertionError("cancelled waiter must not enter guarded work")

    async with lifecycle_guard(["character:cancel-safe"]):
        waiter = asyncio.create_task(wait_for_guard())
        await waiter_started.wait()
        await asyncio.sleep(0.05)
        waiter.cancel()
        await asyncio.sleep(0)
        assert not waiter.done()

    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(waiter, timeout=1.0)

    async with asyncio.timeout(1.0):
        async with lifecycle_guard(["character:cancel-safe"]):
            pass


@pytest.mark.asyncio
async def test_lifecycle_guard_holds_database_advisory_lock(test_db):
    key = "character:cross-process"
    lock_id = int.from_bytes(
        hashlib.sha256(f"lifecycle:{key}".encode("utf-8")).digest()[:8],
        byteorder="big",
        signed=True,
    )
    probe = PgConnection(test_db._pool)
    try:
        async with lifecycle_guard([key], conn=test_db):
            acquired = probe.execute(
                "SELECT pg_try_advisory_lock(%s) AS acquired",
                (lock_id,),
            ).fetchone()["acquired"]
            assert acquired is False

        acquired = probe.execute(
            "SELECT pg_try_advisory_lock(%s) AS acquired",
            (lock_id,),
        ).fetchone()["acquired"]
        assert acquired is True
        probe.execute("SELECT pg_advisory_unlock(%s)", (lock_id,))
    finally:
        probe.close()


@pytest.mark.asyncio
async def test_database_unlock_failure_still_releases_local_lifecycle_lock(monkeypatch):
    from src.server import runtime_lifecycle

    class FakeConnection:
        _pool = object()

    monkeypatch.setattr(
        runtime_lifecycle,
        "_acquire_database_locks",
        lambda _pool, _lock_ids: object(),
    )

    def fail_release(_pool, _raw_conn, _lock_ids):
        raise RuntimeError("database unlock failed")

    monkeypatch.setattr(
        runtime_lifecycle,
        "_release_database_locks",
        fail_release,
    )

    with pytest.raises(RuntimeError, match="database unlock failed"):
        async with lifecycle_guard(
            ["character:release-failure"],
            conn=FakeConnection(),
        ):
            pass

    assert "character:release-failure" not in runtime_lifecycle._locks
