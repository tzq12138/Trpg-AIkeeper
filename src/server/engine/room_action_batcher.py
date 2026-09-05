import asyncio
import logging
from collections.abc import Awaitable, Callable


logger = logging.getLogger(__name__)


class RoomActionBatcher:
    """Coalesce same-room action resolution without replacing database locking."""

    def __init__(self, window_seconds: float = 2.0):
        self.window_seconds = max(0.0, window_seconds)
        self._tasks: dict[str, asyncio.Task[None]] = {}

    def schedule(self, room_id: str, flush: Callable[[], Awaitable[None]]) -> bool:
        existing = self._tasks.get(room_id)
        if existing and not existing.done():
            return False

        async def run() -> None:
            try:
                await asyncio.sleep(self.window_seconds)
                await flush()
            except Exception:
                logger.exception("Room action batch failed room=%s", room_id)
            finally:
                if self._tasks.get(room_id) is asyncio.current_task():
                    self._tasks.pop(room_id, None)

        self._tasks[room_id] = asyncio.create_task(run())
        return True

    def is_scheduled(self, room_id: str) -> bool:
        task = self._tasks.get(room_id)
        return bool(task and not task.done())

    async def shutdown(self) -> None:
        tasks = list(self._tasks.values())
        self._tasks.clear()
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
