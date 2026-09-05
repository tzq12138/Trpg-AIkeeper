import asyncio

import pytest

from src.server.engine.room_action_batcher import RoomActionBatcher


@pytest.mark.asyncio
async def test_room_batcher_coalesces_actions_for_the_same_room():
    batcher = RoomActionBatcher(window_seconds=0)
    flushed = []

    async def flush():
        flushed.append("room-1")

    assert batcher.schedule("room-1", flush) is True
    assert batcher.schedule("room-1", flush) is False

    await asyncio.sleep(0)
    await asyncio.sleep(0)

    assert flushed == ["room-1"]
    assert batcher.is_scheduled("room-1") is False
