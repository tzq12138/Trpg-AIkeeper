import json
import logging
from .models import SpoilerLevel

logger = logging.getLogger(__name__)

SPOILER_VISIBILITY: dict[str, dict[str, float]] = {
    "strict": {
        "public_observation": 1.0,
        "discovered_clue": 0.6,
        "npc_appearance": 0.4,
        "scene_description": 0.8,
        "hidden_npc": 0.0,
        "truth_summary": 0.0,
        "ending": 0.0,
        "undiscovered_clue": 0.0,
        "behind_scenes": 0.0,
    },
    "standard": {
        "public_observation": 1.0,
        "discovered_clue": 1.0,
        "npc_appearance": 0.7,
        "scene_description": 1.0,
        "hidden_npc": 0.1,
        "truth_summary": 0.0,
        "ending": 0.0,
        "undiscovered_clue": 0.1,
        "behind_scenes": 0.05,
    },
    "cinematic": {
        "public_observation": 1.0,
        "discovered_clue": 1.0,
        "npc_appearance": 1.0,
        "scene_description": 1.0,
        "hidden_npc": 0.3,
        "truth_summary": 0.15,
        "ending": 0.0,
        "undiscovered_clue": 0.3,
        "behind_scenes": 0.2,
    },
}


class SpoilerController:
    def __init__(self, conn):
        self.conn = conn

    def get_spoiler_level(self, room_id: str) -> SpoilerLevel:
        row = self.conn.execute(
            "SELECT spoiler_level FROM rooms WHERE room_id = %s", (room_id,)
        ).fetchone()
        if not row:
            return "standard"
        level = row["spoiler_level"]
        if level in ("strict", "standard", "cinematic"):
            return level  # type: ignore
        return "standard"

    def filter_for_player(
        self,
        scenario: dict,
        character_id: str,
        discovered_clue_ids: list[str],
        spoiler_level: SpoilerLevel = "standard",
    ) -> dict:
        visibility = SPOILER_VISIBILITY.get(spoiler_level, SPOILER_VISIBILITY["standard"])
        raw_text = scenario.get("raw_text", "")
        knowledge_graph = {}
        kg_raw = scenario.get("knowledge_graph")
        if kg_raw:
            try:
                knowledge_graph = json.loads(kg_raw) if isinstance(kg_raw, str) else kg_raw
            except (json.JSONDecodeError, TypeError):
                knowledge_graph = {}

        filtered = {
            "scenario_id": scenario.get("scenario_id", ""),
            "title": scenario.get("title", ""),
            "scene_description": "",
            "visible_clues": [],
            "visible_npcs": [],
            "atmosphere": "",
            "public_observations": [],
        }

        scene_desc = knowledge_graph.get("scene_description", "")
        if scene_desc and visibility.get("scene_description", 0) >= 0.5:
            filtered["scene_description"] = scene_desc
        elif raw_text:
            limit = int(len(raw_text) * visibility.get("scene_description", 0.5))
            filtered["scene_description"] = raw_text[:limit]

        for clue in knowledge_graph.get("clues", []):
            clue_id = clue.get("clue_id", "")
            if clue.get("is_hidden") and clue_id not in discovered_clue_ids:
                if visibility.get("undiscovered_clue", 0) < 0.2:
                    continue
                filtered["visible_clues"].append({
                    "clue_id": clue_id,
                    "text": "[尚未发现的线索暗示]",
                    "hint_only": True,
                })
            else:
                if visibility.get("discovered_clue", 0) >= 0.5:
                    filtered["visible_clues"].append({
                        "clue_id": clue_id,
                        "text": clue.get("text", ""),
                        "hint_only": False,
                    })

        for npc in knowledge_graph.get("npcs", []):
            is_hidden = npc.get("is_hidden", False)
            if is_hidden:
                if visibility.get("hidden_npc", 0) >= 0.2:
                    filtered["visible_npcs"].append({
                        "npc_id": npc.get("npc_id", ""),
                        "name": npc.get("name", "???"),
                        "description": npc.get("public_description", "一个神秘的身影"),
                        "hidden": True,
                    })
            else:
                if visibility.get("npc_appearance", 0) >= 0.3:
                    filtered["visible_npcs"].append({
                        "npc_id": npc.get("npc_id", ""),
                        "name": npc.get("name", ""),
                        "description": npc.get("description", ""),
                        "hidden": False,
                    })

        atmosphere = knowledge_graph.get("atmosphere", "")
        if atmosphere:
            filtered["atmosphere"] = atmosphere

        for obs in knowledge_graph.get("public_observations", []):
            if visibility.get("public_observation", 0) >= 0.5:
                filtered["public_observations"].append(obs)

        return filtered

    def get_discovered_clues(self, room_id: str, character_id: str) -> list[str]:
        rows = self.conn.execute(
            "SELECT clue_id FROM clues WHERE room_id = %s AND character_id = %s",
            (room_id, character_id),
        ).fetchall()
        return [row["clue_id"] for row in rows]

    def get_exposure_level(self, room_id: str, character_id: str) -> dict:
        discovered = self.get_discovered_clues(room_id, character_id)
        clue_count = len(discovered)
        if clue_count == 0:
            level = 0
        elif clue_count <= 2:
            level = 1
        elif clue_count <= 5:
            level = 2
        else:
            level = 3
        return {
            "character_id": character_id,
            "level": level,
            "discovered_elements": discovered,
        }

    def build_kp_context(
        self,
        room_id: str,
        scenario: dict,
        actions: list[dict],
    ) -> dict:
        spoiler_level = self.get_spoiler_level(room_id)
        all_characters = self.conn.execute(
            "SELECT character_id FROM characters WHERE room_id = %s", (room_id,)
        ).fetchall()

        character_contexts = []
        for char_row in all_characters:
            cid = char_row["character_id"]
            discovered = self.get_discovered_clues(room_id, cid)
            exposure = self.get_exposure_level(room_id, cid)
            filtered = self.filter_for_player(scenario, cid, discovered, spoiler_level)
            character_contexts.append({
                "character_id": cid,
                "exposure": exposure,
                "visible_scenario": filtered,
            })

        truth = scenario.get("knowledge_graph", "")
        if isinstance(truth, str):
            try:
                truth = json.loads(truth)
            except (json.JSONDecodeError, TypeError):
                truth = {}
        truth_summary = truth.get("truth_summary", "") if isinstance(truth, dict) else ""

        return {
            "spoiler_level": spoiler_level,
            "character_contexts": character_contexts,
            "actions": actions,
            "truth_summary_for_kp_only": truth_summary,
            "scenario_title": scenario.get("title", ""),
        }
