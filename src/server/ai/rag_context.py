"""RAGContextBuilder — assembles layered AI KP context from rules, scenario, characters, events, clues, assets."""

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)

SOURCE_QUOTAS = {
    "rule": 3,
    "scenario": 5,
    "character": 2,
    "event": 3,
    "clue": 2,
    "npc": 2,
    "asset": 1,
}


class RAGContextBuilder:
    """Assembles layered context for AI KP before turn resolution."""

    def __init__(self, conn, rag_store):
        self.conn = conn
        self.rag = rag_store

    def build(self, room_id: str, action_text: str = "",
              character_id: str = "", scenario_id: str = "") -> dict:
        """Build the full layered context package."""
        rules = []
        scenario = []
        characters = []
        events = []
        clues = []
        assets = []
        citations = []

        if not self.rag:
            return self._empty_context(room_id)

        # Determine scenario_id from room if not provided
        if not scenario_id and room_id:
            room = self.conn.execute("SELECT scenario_id FROM rooms WHERE room_id = %s", (room_id,)).fetchone()
            scenario_id = room["scenario_id"] if room and room.get("scenario_id") else ""

        query = action_text or "调查 行动 线索 检定"
        queries = [
            (query, ["rule"], SOURCE_QUOTAS["rule"]),
            (query, ["scenario"], SOURCE_QUOTAS["scenario"]),
            (query, ["character"], SOURCE_QUOTAS["character"]),
            (query, ["event"], SOURCE_QUOTAS["event"]),
            (query, ["clue"], SOURCE_QUOTAS["clue"]),
            (query, ["npc"], SOURCE_QUOTAS["npc"]),
            (query, ["asset"], SOURCE_QUOTAS["asset"]),
        ]

        for q, stypes, limit in queries:
            try:
                results = self.rag.search(
                    q,
                    room_id=room_id,
                    source_types=stypes,
                    top_k=limit,
                    audience="ai",
                )
                for r in results:
                    citation = dict(r.get("citation") or {})
                    citation.setdefault("source_type", r["source_type"])
                    citation.setdefault("source_id", r["source_id"])
                    citation["similarity"] = round(float(r.get("similarity", 0)), 3)
                    citation["score"] = round(float(r.get("score", 0)), 3)
                    citations.append(citation)
                    chunk = {"content": r.get("content", "")[:500], "citation": citation}
                    if r["source_type"] == "rule":
                        rules.append(chunk)
                    elif r["source_type"] == "scenario":
                        scenario.append(chunk)
                    elif r["source_type"] == "character":
                        characters.append(chunk)
                    elif r["source_type"] == "event":
                        events.append(chunk)
                    elif r["source_type"] == "clue":
                        clues.append(chunk)
                    elif r["source_type"] == "asset":
                        assets.append(chunk)
            except Exception as e:
                logger.debug("RAG search failed for %s: %s", stypes, e)

        # Add character sheet directly (authoritative)
        char_direct = {}
        if character_id:
            char_row = self.conn.execute(
                "SELECT * FROM characters WHERE character_id = %s", (character_id,)
            ).fetchone()
            if char_row:
                xlsx = self._json_val(char_row.get("xlsx_data"))
                char_direct = {
                    "character_id": character_id,
                    "name": xlsx.get("name", ""),
                    "occupation": xlsx.get("occupation", ""),
                    "hp": xlsx.get("hp", 0),
                    "max_hp": xlsx.get("max_hp", 0),
                    "san": xlsx.get("san", 0),
                    "max_san": xlsx.get("max_san", 0),
                    "skills": {k: v for k, v in xlsx.get("skills", {}).items() if int(v) > 0} if xlsx.get("skills") else {},
                }

        return {
            "room_id": room_id,
            "scenario_id": scenario_id,
            "rules": rules,
            "scenario": scenario,
            "characters": characters,
            "characters_direct": char_direct,
            "events": events,
            "clues": clues,
            "assets": assets,
            "citations": citations,
            "query_debug": {"query": query, "source_quotas": SOURCE_QUOTAS},
        }

    def preview(self, room_id: str, action_text: str = "", character_id: str = "",
                scenario_id: str = "") -> dict:
        """Admin preview of what AI will see."""
        ctx = self.build(room_id, action_text, character_id, scenario_id)
        # Truncate content for preview
        for key in ("rules", "scenario", "characters", "events", "clues", "assets"):
            for item in ctx.get(key, []):
                item["content"] = item["content"][:200] + "..." if len(item.get("content", "")) > 200 else item.get("content", "")
        return ctx

    @staticmethod
    def _empty_context(room_id: str) -> dict:
        return {
            "room_id": room_id, "scenario_id": "",
            "rules": [], "scenario": [], "characters": [], "characters_direct": {},
            "events": [], "clues": [], "assets": [], "citations": [],
            "query_debug": {"query": "", "source_quotas": {}},
        }

    @staticmethod
    def _json_val(value):
        if value is None:
            return {}
        if isinstance(value, dict):
            return value
        if isinstance(value, str):
            try:
                return json.loads(value)
            except (json.JSONDecodeError, TypeError):
                return {}
        return {}
