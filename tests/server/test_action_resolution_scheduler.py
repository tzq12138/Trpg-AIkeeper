"""Scheduling contract for background action resolution.

Migration note (B1, recorded in docs/日期/20260905/04 范围处置):
the previous case asserted resolution MUST flow through RoomActionBatcher.
Production never adopted the batcher (no lifecycle host; single actions are
already deduplicated by the atomic queued->resolving claim; a coalescing
window delays free-form actions). The frozen behaviour asserted here instead:
the scheduler keeps using the same background worker it always has, and does
not crash or enqueue when invoked from a context without an event loop or
without an available pipeline. Equivalent assertions (single authority
commit under concurrent triggers) live in test_background_resolution_runtime.py.
"""

import asyncio
from types import SimpleNamespace

from src.server.player.router_actions_v2 import _schedule_action_resolution


class _Rows:
    def __init__(self, row):
        self._row = row

    def fetchone(self):
        return self._row


class _Conn:
    def execute(self, _sql, _params):
        return _Rows({"turn_id": None, "room_status": "active", "room_id": "room-1"})


def test_schedule_without_pipeline_or_db_is_a_noop():
    """Without a pipeline or pg_db the scheduler must not raise or enqueue."""
    app = SimpleNamespace(state=SimpleNamespace(pipeline=None, pg_db=None))

    _schedule_action_resolution(app, _Conn(), "action-1")


def test_non_turn_action_runs_through_the_same_background_worker():
    """A non-turn action is handed to the shared background worker."""
    calls = []

    class _FakePipeline:
        async def resolve_action(self, action_id):
            calls.append(action_id)

    app = SimpleNamespace(state=SimpleNamespace(
        pipeline=_FakePipeline(),
        pg_db=None,
        action_batcher=None,
    ))

    async def _schedule():
        _schedule_action_resolution(app, _Conn(), "action-1")
        # Yield once so the spawned background task starts.
        await asyncio.sleep(0.01)

    asyncio.run(_schedule())
    assert calls == ["action-1"]
