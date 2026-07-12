from __future__ import annotations

import json
from contextlib import nullcontext
from typing import Any


class SoloTransitionError(ValueError):
    pass


class SoloAdventureRuntime:
    def __init__(self, conn):
        self.conn = conn

    def current(self, room_id: str) -> dict[str, Any] | None:
        context = self._context(room_id)
        if not context:
            return None
        state = self.conn.execute(
            "SELECT current_scene, visited_scenes, version FROM room_scene_state WHERE room_id = %s",
            (room_id,),
        ).fetchone()
        node_id = _scene_node_id(state.get("current_scene") if state else "")
        if node_id not in context["nodes"]:
            node_id = context["root_node_id"]
        node = context["nodes"][node_id]
        return {
            "scenario_version_id": context["scenario_version_id"],
            "node_id": node_id,
            "title": node["title"],
            "text": _json_object(node.get("payload")).get("text", ""),
            "citation": _json_object(node.get("citation")),
            "target_node_ids": context["targets"].get(node_id, []),
            "scene_version": int(state.get("version") or 0) if state else 0,
        }

    def validate_transition(
        self, room_id: str, *, from_node_id: str, target_node_id: str
    ) -> str | None:
        context = self._context(room_id)
        if not context:
            return None
        current = self.current(room_id)
        if not current:
            return "solo_runtime_unavailable"
        if from_node_id and from_node_id != current["node_id"]:
            return "solo_transition_stale"
        if target_node_id not in context["targets"].get(current["node_id"], []):
            return "solo_transition_not_allowed"
        return ""

    def transition(
        self,
        room_id: str,
        *,
        from_node_id: str,
        target_node_id: str,
        transaction=None,
    ) -> dict[str, Any]:
        transaction_scope = (
            nullcontext(transaction) if transaction is not None else self.conn.transaction()
        )
        with transaction_scope as tx:
            context = self._context(room_id, connection=tx)
            if not context:
                raise SoloTransitionError("solo_adventure_not_enabled")
            state = tx.execute(
                "SELECT current_scene, visited_scenes FROM room_scene_state "
                "WHERE room_id = %s FOR UPDATE",
                (room_id,),
            ).fetchone()
            current_node_id = _scene_node_id(state.get("current_scene") if state else "")
            if current_node_id not in context["nodes"]:
                current_node_id = context["root_node_id"]
            if from_node_id and from_node_id != current_node_id:
                raise SoloTransitionError("solo_transition_stale")
            if target_node_id not in context["targets"].get(current_node_id, []):
                raise SoloTransitionError("solo_transition_not_allowed")
            visited = _json_list(state.get("visited_scenes") if state else [])
            for node_id in (current_node_id, target_node_id):
                scene_id = f"solo:{node_id}"
                if scene_id not in visited:
                    visited.append(scene_id)
            tx.execute(
                """
                INSERT INTO room_scene_state (room_id, current_scene, visited_scenes, scene_variables, version)
                VALUES (%s, %s, %s, %s, 1)
                ON CONFLICT (room_id) DO UPDATE SET
                    current_scene = EXCLUDED.current_scene,
                    visited_scenes = EXCLUDED.visited_scenes,
                    scene_variables = room_scene_state.scene_variables || EXCLUDED.scene_variables,
                    version = room_scene_state.version + 1,
                    updated_at = NOW()
                """,
                (
                    room_id,
                    f"solo:{target_node_id}",
                    json.dumps(visited, ensure_ascii=False),
                    json.dumps({"solo_adventure_version": context["scenario_version_id"]}, ensure_ascii=False),
                ),
            )
            target_text = str(
                _json_object(context["nodes"][target_node_id].get("payload")).get("text")
                or ""
            )
            is_ending = "【剧终】" in target_text
            room = tx.execute(
                "UPDATE rooms SET state_version = state_version + 1, "
                "status = CASE WHEN %s THEN 'completed' ELSE status END WHERE room_id = %s "
                "RETURNING state_version",
                (is_ending, room_id),
            ).fetchone()
            if is_ending:
                tx.execute(
                    "UPDATE encounters SET status = 'resolved', resolved_at = NOW(), "
                    "summary = COALESCE(summary, '') || ' [solo adventure ended]' "
                    "WHERE room_id = %s AND status IN ('suggested', 'active')",
                    (room_id,),
                )
            edge = context["edges"][(current_node_id, target_node_id)]
        return {
            "scenario_version_id": context["scenario_version_id"],
            "from_node_id": current_node_id,
            "target_node_id": target_node_id,
            "current_scene": f"solo:{target_node_id}",
            "citation": _json_object(edge.get("citation")),
            "state_version": int(room.get("state_version") or 0) if room else 0,
            "is_ending": is_ending,
        }

    def _context(self, room_id: str, *, connection=None) -> dict[str, Any] | None:
        connection = connection or self.conn
        room = connection.execute(
            """
            SELECT r.scenario_version_id, sv.knowledge_graph
            FROM rooms r
            JOIN scenario_versions sv ON sv.scenario_version_id = r.scenario_version_id
            WHERE r.room_id = %s
            """,
            (room_id,),
        ).fetchone()
        if not room:
            return None
        graph = _json_object(room.get("knowledge_graph"))
        solo = _json_object(graph.get("solo_adventure"))
        integrity = _json_object(solo.get("integrity"))
        root_node_id = str(solo.get("root_node_id") or "")
        if not root_node_id or not integrity.get("is_valid", False):
            return None
        rows = connection.execute(
            """
            SELECT content_item_id, logical_key, title, payload, citation
            FROM content_items
            WHERE scenario_version_id = %s AND item_type = 'branch_node'
            ORDER BY ordinal, logical_key
            """,
            (room["scenario_version_id"],),
        ).fetchall()
        nodes = {str(row["logical_key"]): dict(row) for row in rows}
        if root_node_id not in nodes:
            return None
        edges = connection.execute(
            """
            SELECT source.logical_key AS from_node_id, target.logical_key AS target_node_id,
                   edge.citation
            FROM content_item_edges edge
            JOIN content_items source ON source.content_item_id = edge.from_content_item_id
            JOIN content_items target ON target.content_item_id = edge.to_content_item_id
            WHERE edge.scenario_version_id = %s
              AND source.item_type = 'branch_node'
              AND target.item_type = 'branch_node'
              AND edge.relation_type = 'transitions_to'
            """,
            (room["scenario_version_id"],),
        ).fetchall()
        targets: dict[str, list[str]] = {node_id: [] for node_id in nodes}
        edge_map = {}
        for edge in edges:
            from_node_id = str(edge["from_node_id"])
            target_node_id = str(edge["target_node_id"])
            targets.setdefault(from_node_id, []).append(target_node_id)
            edge_map[(from_node_id, target_node_id)] = dict(edge)
        return {
            "scenario_version_id": room["scenario_version_id"],
            "root_node_id": root_node_id,
            "nodes": nodes,
            "targets": targets,
            "edges": edge_map,
        }


def _scene_node_id(current_scene: str) -> str:
    value = str(current_scene or "")
    return value[5:] if value.startswith("solo:") else ""


def _json_object(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def _json_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value]
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return []
        return [str(item) for item in parsed] if isinstance(parsed, list) else []
    return []
