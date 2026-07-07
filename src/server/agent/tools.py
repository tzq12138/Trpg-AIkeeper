import json
import random
import uuid
import logging
from typing import Any

from ..events.events_registry import event_type

logger = logging.getLogger(__name__)


def get_tools() -> list[dict]:
    return [
        {
            "type": "function",
            "function": {
                "name": "query_npcs",
                "description": "查询当前场景的NPC列表及详情（姓名、类型、性格、动机）",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "location": {"type": "string", "description": "地点名称（可选，不传则查询当前地点）"}
                    },
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "query_location",
                "description": "查询地点的描述、NPC、出口、互动点",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "location_name": {"type": "string", "description": "地点名称"}
                    },
                    "required": ["location_name"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "query_clues",
                "description": "查询已发现的线索列表",
            },
        },
        {
            "type": "function",
            "function": {
                "name": "query_inventory",
                "description": "查询玩家背包物品",
            },
        },
        {
            "type": "function",
            "function": {
                "name": "query_recent_events",
                "description": "查询最近的游戏事件（玩家行动和KP叙事）",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "limit": {"type": "integer", "description": "返回事件数量，默认5"}
                    },
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "query_character",
                "description": "查询当前玩家角色的属性、技能、状态",
            },
        },
        {
            "type": "function",
            "function": {
                "name": "query_scenario_info",
                "description": "查询剧本的基本信息（标题、概要）",
            },
        },
        {
            "type": "function",
            "function": {
                "name": "engine_roll_check",
                "description": "执行技能检定（掷骰子）",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "skill_name": {"type": "string", "description": "技能名称，如侦查、聆听、话术"},
                        "difficulty": {
                            "type": "string",
                            "enum": ["regular", "hard", "extreme"],
                            "description": "难度",
                        },
                    },
                    "required": ["skill_name"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "engine_save_clue",
                "description": "保存发现的线索",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "text": {"type": "string", "description": "线索内容"},
                        "source": {"type": "string", "description": "线索来源"},
                    },
                    "required": ["text"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "output_narrative",
                "description": "输出最终叙事文本给玩家（必须在推理结束时调用）",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "text": {"type": "string", "description": "叙事文本，200字以内"}
                    },
                    "required": ["text"],
                },
            },
        },
    ]


class ToolExecutor:
    def __init__(self, conn, room_id: str, character_id: str, scenario: dict | None):
        self.conn = conn
        self.room_id = room_id
        self.character_id = character_id
        self.scenario = scenario

    async def execute(self, tool_name: str, arguments: dict) -> str:
        try:
            handler = getattr(self, f"_tool_{tool_name}", None)
            if handler:
                result = await handler(**arguments)
                return json.dumps(result, ensure_ascii=False)
            return json.dumps({"error": f"Unknown tool: {tool_name}"})
        except Exception as e:
            logger.warning("Tool %s failed: %s", tool_name, e)
            return json.dumps({"error": str(e)})

    async def _tool_query_npcs(self, location: str = "") -> dict:
        if not self.scenario:
            return {"npcs": []}
        kg = _json_value(self.scenario.get("knowledge_graph")) or {}
        assets = _json_value(self.scenario.get("scenario_assets")) or {}

        if not location:
            char = self._get_character()
            xlsx = _json_value(char.get("xlsx_data")) if char else {}
            location = xlsx.get("current_location", "")

        target_scene = None
        for scene in assets.get("scenes", []):
            if scene.get("name") == location:
                target_scene = scene
                break
        if not target_scene and assets.get("scenes"):
            target_scene = assets["scenes"][0]

        if not target_scene:
            return {"npcs": [], "location": location}

        npcs_in_scene = target_scene.get("npcs_present", [])
        npcs_detail = []
        for npc_name in npcs_in_scene:
            npc_data = None
            for npc in kg.get("npcs", []):
                # Match by name first, also try npc_id
                if npc.get("name") == npc_name or npc.get("npc_id") == npc_name:
                    npc_data = npc
                    break
            if npc_data:
                entry = {
                    "npc_id": npc_data.get("npc_id", ""),
                    "name": npc_data.get("public_name", npc_data.get("name", npc_name)),
                    "type": npc_data.get("type", "story"),
                    "role": npc_data.get("role", ""),
                    "public_description": npc_data.get("public_description", ""),
                }
                # Only include personality/motivation for internal AI context,
                # not for player-facing narrative generation
                if npc_data.get("personality"):
                    entry["personality"] = npc_data["personality"]
                if npc_data.get("motivation"):
                    entry["motivation"] = npc_data["motivation"]
                npcs_detail.append(entry)
            else:
                npcs_detail.append({"name": npc_name, "type": "story"})
        return {"npcs": npcs_detail, "location": location}

    async def _tool_query_location(self, location_name: str) -> dict:
        if not self.scenario:
            return {"error": "No scenario"}
        assets = _json_value(self.scenario.get("scenario_assets")) or {}
        for scene in assets.get("scenes", []):
            if scene.get("name") == location_name:
                return {
                    "name": location_name,
                    "description": scene.get("description", ""),
                    "npcs_present": scene.get("npcs_present", []),
                    "exits": scene.get("exits", []),
                    "clues_available": scene.get("clues_available", []),
                }
        return {"error": f"Location '{location_name}' not found"}

    async def _tool_query_clues(self) -> dict:
        # Owned clues (full text visible)
        owned_rows = self.conn.execute(
            "SELECT clue_id, text, source, is_private FROM clues "
            "WHERE character_id = %s AND room_id = %s ORDER BY clue_id DESC LIMIT 10",
            (self.character_id, self.room_id),
        ).fetchall()
        clues = []
        for r in owned_rows:
            clues.append({
                "clue_id": r["clue_id"],
                "text": r["text"],
                "source": r["source"],
                "owned": True,
            })
        # Shared clues from teammates (public_version only)
        shared_rows = self.conn.execute(
            "SELECT cs.clue_id, cs.public_version, cs.shared_by "
            "FROM clue_shares cs JOIN clues c ON cs.clue_id = c.clue_id "
            "WHERE c.room_id = %s AND c.character_id != %s "
            "ORDER BY cs.shared_at DESC LIMIT 10",
            (self.room_id, self.character_id),
        ).fetchall()
        for r in shared_rows:
            clues.append({
                "clue_id": r["clue_id"],
                "text": r["public_version"],
                "source": "shared",
                "shared_by": r["shared_by"],
                "owned": False,
            })
        return {"clues": clues}

    async def _tool_query_inventory(self) -> dict:
        rows = self.conn.execute(
            "SELECT id, name, description, quantity FROM inventory WHERE character_id = %s AND room_id = %s",
            (self.character_id, self.room_id),
        ).fetchall()
        return {"items": [dict(r) for r in rows]}

    async def _tool_query_recent_events(self, limit: int = 5) -> dict:
        rows = self.conn.execute(
            "SELECT event_type, payload FROM events WHERE room_id = %s AND audience IN ('party', 'player') ORDER BY sequence DESC LIMIT %s",
            (self.room_id, limit),
        ).fetchall()
        events = []
        for row in reversed(rows):
            row = dict(row)
            payload = _json_value(row.get("payload", {})) or {}
            text = payload.get("text", "")
            if text:
                prefix = "KP" if row.get("event_type") == event_type("s2c_public_observation") else "System"
                events.append(f"[{prefix}] {text[:150]}")
        return {"events": events}

    async def _tool_query_character(self) -> dict:
        char = self._get_character()
        if not char:
            return {"error": "Character not found"}
        xlsx = _json_value(char.get("xlsx_data")) or {}
        return {
            "name": char.get("player_name", ""),
            "occupation": xlsx.get("occupation", ""),
            "hp": xlsx.get("hp", 0), "max_hp": xlsx.get("max_hp", 0),
            "san": xlsx.get("san", 0), "max_san": xlsx.get("max_san", 0),
            "mp": xlsx.get("mp", 0), "luck": xlsx.get("luck", 0),
            "skills": xlsx.get("skills", {}),
            "location": xlsx.get("current_location", ""),
        }

    async def _tool_query_scenario_info(self) -> dict:
        if not self.scenario:
            return {"error": "No scenario"}
        kg = _json_value(self.scenario.get("knowledge_graph")) or {}
        return {
            "title": self.scenario.get("title", ""),
            "synopsis": kg.get("synopsis", "")[:300],
        }

    async def _tool_engine_roll_check(self, skill_name: str, difficulty: str = "regular") -> dict:
        char = self._get_character()
        xlsx = _json_value(char.get("xlsx_data")) if char else {}
        skills = xlsx.get("skills", {})
        skill_value = skills.get(skill_name, 50)

        roll = random.randint(1, 100)
        if difficulty == "hard":
            target = skill_value // 2
        elif difficulty == "extreme":
            target = skill_value // 5
        else:
            target = skill_value

        if roll == 1:
            success_level, is_success = "critical", True
        elif roll == 100:
            success_level, is_success = "fumble", False
        elif roll >= 96 and skill_value < 50:
            success_level, is_success = "fumble", False
        elif roll <= target:
            if roll <= target // 5:
                success_level = "extreme"
            elif roll <= target // 2:
                success_level = "hard"
            else:
                success_level = "regular"
            is_success = True
        else:
            success_level, is_success = "failure", False

        return {
            "skill_name": skill_name, "skill_value": skill_value,
            "roll": roll, "target": target, "difficulty": difficulty,
            "success_level": success_level, "is_success": is_success,
        }

    async def _tool_engine_save_clue(self, text: str, source: str = "") -> dict:
        """Save a clue through the controlled path — writes clue + discovery event.

        The clue is saved as private (is_private=true) for the current character.
        An s2c_clue_discovered event is written for archival and projection.
        """
        clue_id = str(uuid.uuid4())[:8]
        try:
            self.conn.execute(
                "INSERT INTO clues (clue_id, room_id, character_id, text, source, is_private) "
                "VALUES (%s, %s, %s, %s, %s, %s)",
                (clue_id, self.room_id, self.character_id, text, source or "agent", True),
            )
            # Write discovery event for archival/journal
            try:
                from ..events.event_log import EventLog
                el = EventLog(self.conn)
                el.log_event(self.room_id, "s2c_clue_discovered", "player", {
                    "clueId": clue_id,
                    "characterId": self.character_id,
                    "source": source or "agent",
                    "visibility": "self",
                })
            except Exception as ev_err:
                logger.warning("Failed to write clue_discovered event: %s", ev_err)
            self.conn.commit()
            return {"clue_id": clue_id, "saved": True, "text": text}
        except Exception as e:
            return {"error": str(e)}

    async def _tool_output_narrative(self, text: str) -> dict:
        return {"narrative": text, "final": True}

    def _get_character(self) -> dict | None:
        row = self.conn.execute(
            "SELECT * FROM characters WHERE character_id = %s", (self.character_id,)
        ).fetchone()
        return dict(row) if row else None


def _json_value(value) -> Any:
    if value is None:
        return None
    if isinstance(value, (dict, list)):
        return value
    if isinstance(value, str):
        try:
            return json.loads(value)
        except (json.JSONDecodeError, TypeError):
            return None
    return value
