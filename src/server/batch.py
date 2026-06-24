import uuid
import time
import json
import logging
import asyncio
from collections import defaultdict
from typing import Callable, Any, Awaitable

logger = logging.getLogger(__name__)


class BatchCollector:
    def __init__(self, window_seconds: float = 10.0):
        self.window_seconds = window_seconds
        self._pending: dict[str, list[dict]] = defaultdict(list)
        self._first_action_time: dict[str, float] = {}

    def add_action(self, room_id: str, action: dict):
        if room_id not in self._first_action_time:
            self._first_action_time[room_id] = time.time()
        self._pending[room_id].append(action)

    def maybe_create_batch(self, room_id: str) -> dict | None:
        actions = self._pending.get(room_id, [])
        if not actions:
            return None

        first_time = self._first_action_time.get(room_id, 0)
        elapsed = time.time() - first_time

        if elapsed >= self.window_seconds or len(actions) >= 4:
            batch_id = str(uuid.uuid4())[:8]
            batch = {
                "batch_id": batch_id,
                "room_id": room_id,
                "actions": list(actions),
                "created_at": time.time(),
            }
            self._pending[room_id] = []
            self._first_action_time.pop(room_id, None)
            return batch

        return None

    def get_pending_count(self, room_id: str) -> int:
        return len(self._pending.get(room_id, []))


BatchStatus = str  # "collecting" | "processing" | "completed" | "failed"


class BatchProcessor:
    def __init__(
        self,
        collector: BatchCollector,
        process_fn: Callable[[str, dict, dict], Awaitable[Any] | Any] | None = None,
        get_scenario_fn: Callable[[str], dict | None] | None = None,
    ):
        self.collector = collector
        self.process_fn = process_fn
        self.get_scenario_fn = get_scenario_fn
        self._batch_status: dict[str, BatchStatus] = {}
        self._last_batch: dict[str, dict] = {}
        self._last_response: dict[str, Any] = {}

    def add_action(self, room_id: str, action: dict):
        self.collector.add_action(room_id, action)
        self._batch_status[room_id] = "collecting"

    async def try_process(self, room_id: str, scenario: dict | None = None) -> Any | None:
        batch = self.collector.maybe_create_batch(room_id)
        if not batch:
            return None

        if scenario is None and self.get_scenario_fn:
            scenario = self.get_scenario_fn(room_id)

        if scenario is None:
            scenario = {"title": "默认场景", "raw_text": ""}

        self._batch_status[room_id] = "processing"
        self._last_batch[room_id] = batch

        try:
            if self.process_fn:
                result = self.process_fn(room_id, batch, scenario)
                if asyncio.iscoroutine(result) or asyncio.isfuture(result):
                    response = await result
                else:
                    response = result
            else:
                response = {"narrative": "KP正在处理行动...", "batch_id": batch["batch_id"]}
            self._batch_status[room_id] = "completed"
            self._last_response[room_id] = response
            return response
        except Exception as e:
            logger.error(f"Batch processing failed for room {room_id}: {e}")
            self._batch_status[room_id] = "failed"
            return None

    def get_status(self, room_id: str) -> dict:
        return {
            "batch_status": self._batch_status.get(room_id, "idle"),
            "pending_count": self.collector.get_pending_count(room_id),
            "last_batch_id": self._last_batch.get(room_id, {}).get("batch_id"),
        }

    def get_last_response(self, room_id: str) -> Any | None:
        return self._last_response.get(room_id)
