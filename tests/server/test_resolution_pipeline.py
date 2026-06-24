import json
import random

import pytest

from src.server.mechanic_compiler import MechanicCompiler
from src.server.resolution_pipeline import ResolutionPipeline


class Rows:
    def __init__(self, rows=None):
        self.rows = rows or []

    def fetchone(self):
        return self.rows[0] if self.rows else None

    def fetchall(self):
        return self.rows


class FakeConn:
    def __init__(self):
        self.rooms = {
            "room-1": {
                "room_id": "room-1",
                "scenario_id": None,
                "state_version": 0,
            }
        }
        self.characters = {
            "char-1": {
                "character_id": "char-1",
                "room_id": "room-1",
                "player_name": "Alice",
                "xlsx_data": {"skills": {"侦查": 60}, "hp": 10, "san": 50, "luck": 40},
            }
        }
        self.actions = {
            "act-1": {
                "action_id": "act-1",
                "room_id": "room-1",
                "character_id": "char-1",
                "intent_type": "dialogue",
                "declared_intent": "我侦查房间",
                "status": "queued",
                "result": None,
            }
        }
        self.inventory = []
        self.scenarios = {}
        self.events = []

    def execute(self, sql, params=None):
        normalized = " ".join(sql.split())
        params = params or ()
        if normalized.startswith("SELECT * FROM actions WHERE action_id"):
            return Rows([self.actions[params[0]]] if params[0] in self.actions else [])
        if normalized.startswith("SELECT * FROM actions WHERE room_id"):
            room_id, status = params
            return Rows([
                a for a in self.actions.values()
                if a["room_id"] == room_id and a["status"] == status
            ])
        if normalized.startswith("UPDATE actions SET status = %s WHERE action_id"):
            status, action_id = params
            self.actions[action_id]["status"] = status
            return Rows()
        if normalized.startswith("UPDATE actions SET status = %s, result = %s, completed_at"):
            status, result, _completed_at, action_id = params
            self.actions[action_id]["status"] = status
            self.actions[action_id]["result"] = json.loads(result) if isinstance(result, str) else result
            return Rows()
        if normalized.startswith("SELECT * FROM characters WHERE character_id"):
            return Rows([self.characters[params[0]]] if params[0] in self.characters else [])
        if normalized.startswith("SELECT * FROM rooms WHERE room_id"):
            return Rows([self.rooms[params[0]]] if params[0] in self.rooms else [])
        if normalized.startswith("SELECT * FROM scenarios WHERE scenario_id"):
            return Rows([self.scenarios[params[0]]] if params[0] in self.scenarios else [])
        if normalized.startswith("SELECT * FROM inventory WHERE character_id"):
            return Rows([i for i in self.inventory if i["character_id"] == params[0]])
        if normalized.startswith("UPDATE rooms SET state_version = state_version + 1"):
            self.rooms[params[0]]["state_version"] += 1
            return Rows()
        if normalized.startswith("INSERT INTO events"):
            room_id, event_type, audience, payload = params
            self.events.append({
                "room_id": room_id,
                "event_type": event_type,
                "audience": audience,
                "payload": json.loads(payload) if isinstance(payload, str) else payload,
            })
            return Rows()
        raise AssertionError(f"Unhandled SQL: {normalized}")

    def commit(self):
        pass


class FakeDispatcher:
    def __init__(self):
        self.events = []

    async def emit(self, room_id, event_type, audience, payload, character_id=None):
        self.events.append((room_id, event_type, audience, payload, character_id))


class FailingRuleExecutor:
    async def execute(self, *args, **kwargs):
        raise RuntimeError("handler failed")


@pytest.mark.asyncio
async def test_pipeline_resolves_queued_action_and_projects_events():
    random.seed(0)
    conn = FakeConn()
    dispatcher = FakeDispatcher()
    pipeline = ResolutionPipeline(
        conn=conn,
        compiler=MechanicCompiler(api_key=""),
        dispatcher=dispatcher,
    )

    result = await pipeline.resolve_action("act-1")

    assert result["status"] == "resolved"
    assert conn.actions["act-1"]["status"] == "resolved"
    assert conn.rooms["room-1"]["state_version"] == 1
    assert conn.actions["act-1"]["result"]["mechanic"] == "skill_check"
    event_types = [event[1] for event in dispatcher.events]
    assert "s2c_reveal_transaction" in event_types
    assert "s2c_action_completed" in event_types


@pytest.mark.asyncio
async def test_pipeline_rejects_when_rule_handler_fails_without_partial_projection():
    conn = FakeConn()
    dispatcher = FakeDispatcher()
    pipeline = ResolutionPipeline(
        conn=conn,
        compiler=MechanicCompiler(api_key=""),
        dispatcher=dispatcher,
        rule_executor=FailingRuleExecutor(),
    )

    result = await pipeline.resolve_action("act-1")

    assert result["status"] == "rejected"
    assert conn.actions["act-1"]["status"] == "rejected"
    assert conn.actions["act-1"]["result"]["reason"] == "resolution failed: handler failed"
    event_types = [event[1] for event in dispatcher.events]
    assert event_types == ["s2c_action_completed"]
