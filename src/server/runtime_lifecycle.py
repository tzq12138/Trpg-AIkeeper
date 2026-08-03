"""Process-local and PostgreSQL lifecycle serialization for deletion races."""

import asyncio
import hashlib
import threading
from contextlib import asynccontextmanager
from collections.abc import AsyncIterator, Iterable


_registry_lock = threading.Lock()
_locks: dict[str, tuple[threading.Lock, int]] = {}


def _database_lock_id(key: str) -> int:
    return int.from_bytes(
        hashlib.sha256(f"lifecycle:{key}".encode("utf-8")).digest()[:8],
        byteorder="big",
        signed=True,
    )


async def _wait_uninterruptibly(task: asyncio.Task):
    interrupted = False
    while True:
        try:
            return await asyncio.shield(task), interrupted
        except asyncio.CancelledError:
            interrupted = True


def _acquire_database_locks(pool, lock_ids: list[int]):
    raw_conn = pool.getconn()
    cursor = None
    acquired: list[int] = []
    try:
        cursor = raw_conn.cursor()
        for lock_id in lock_ids:
            cursor.execute("SELECT pg_advisory_lock(%s)", (lock_id,))
            acquired.append(lock_id)
        raw_conn.commit()
        return raw_conn
    except Exception:
        raw_conn.rollback()
        try:
            if cursor is None or cursor.closed:
                cursor = raw_conn.cursor()
            for lock_id in reversed(acquired):
                cursor.execute("SELECT pg_advisory_unlock(%s)", (lock_id,))
            raw_conn.commit()
        finally:
            if cursor is not None:
                cursor.close()
            pool.putconn(raw_conn, close=True)
        raise
    finally:
        if cursor is not None and not cursor.closed:
            cursor.close()


def _release_database_locks(pool, raw_conn, lock_ids: list[int]) -> None:
    cursor = None
    close_connection = False
    try:
        cursor = raw_conn.cursor()
        for lock_id in reversed(lock_ids):
            cursor.execute("SELECT pg_advisory_unlock(%s)", (lock_id,))
        raw_conn.commit()
    except Exception:
        close_connection = True
        raw_conn.rollback()
        raise
    finally:
        if cursor is not None:
            cursor.close()
        pool.putconn(raw_conn, close=close_connection)


async def _acquire_cancel_safe(lock: threading.Lock) -> None:
    acquire_task = asyncio.create_task(asyncio.to_thread(lock.acquire))
    try:
        await asyncio.shield(acquire_task)
    except asyncio.CancelledError:
        acquired, _ = await _wait_uninterruptibly(acquire_task)
        if acquired:
            lock.release()
        raise


def _reserve(keys: list[str]) -> list[tuple[str, threading.Lock]]:
    reserved: list[tuple[str, threading.Lock]] = []
    with _registry_lock:
        for key in keys:
            lock, references = _locks.get(key, (threading.Lock(), 0))
            _locks[key] = (lock, references + 1)
            reserved.append((key, lock))
    return reserved


def _release_reservations(reserved: list[tuple[str, threading.Lock]]) -> None:
    with _registry_lock:
        for key, lock in reserved:
            current, references = _locks[key]
            if current is not lock:
                continue
            if references <= 1:
                _locks.pop(key, None)
            else:
                _locks[key] = (lock, references - 1)


@asynccontextmanager
async def lifecycle_guard(keys: Iterable[str], *, conn=None) -> AsyncIterator[None]:
    normalized = sorted({str(key).strip() for key in keys if str(key).strip()})
    reserved = _reserve(normalized)
    acquired: list[threading.Lock] = []
    pool = getattr(conn, "_pool", None)
    database_lock_ids = [_database_lock_id(key) for key in normalized]
    database_conn = None
    cleanup_cancelled = False
    try:
        for _, lock in reserved:
            await _acquire_cancel_safe(lock)
            acquired.append(lock)
        if pool is not None and database_lock_ids:
            acquire_task = asyncio.create_task(
                asyncio.to_thread(
                    _acquire_database_locks,
                    pool,
                    database_lock_ids,
                )
            )
            try:
                database_conn = await asyncio.shield(acquire_task)
            except asyncio.CancelledError:
                database_conn, _ = await _wait_uninterruptibly(acquire_task)
                release_task = asyncio.create_task(
                    asyncio.to_thread(
                        _release_database_locks,
                        pool,
                        database_conn,
                        database_lock_ids,
                    )
                )
                await _wait_uninterruptibly(release_task)
                database_conn = None
                raise
        yield
    finally:
        try:
            if database_conn is not None:
                release_task = asyncio.create_task(
                    asyncio.to_thread(
                        _release_database_locks,
                        pool,
                        database_conn,
                        database_lock_ids,
                    )
                )
                _, cleanup_cancelled = await _wait_uninterruptibly(release_task)
        finally:
            for lock in reversed(acquired):
                lock.release()
            _release_reservations(reserved)
        if cleanup_cancelled:
            raise asyncio.CancelledError


def character_lifecycle_guard(character_ids: Iterable[str], *, conn=None):
    return lifecycle_guard(
        (f"character:{character_id}" for character_id in character_ids),
        conn=conn,
    )


def account_lifecycle_guard(account_ids: Iterable[str], *, conn=None):
    return lifecycle_guard(
        (f"account:{account_id}" for account_id in account_ids),
        conn=conn,
    )


def deletion_lifecycle_guard(
    *,
    character_ids: Iterable[str] = (),
    account_ids: Iterable[str] = (),
    conn=None,
):
    return lifecycle_guard([
        *(f"account:{account_id}" for account_id in account_ids),
        *(f"character:{character_id}" for character_id in character_ids),
    ], conn=conn)
