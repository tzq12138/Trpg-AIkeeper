from __future__ import annotations

import hashlib
import json
import uuid
from typing import Any


_ITEM_SPECS = (
    ("scene", "scenes", ("scene_id", "id", "name")),
    ("npc", "npcs", ("npc_id", "id", "name")),
    ("clue", "clues", ("clue_id", "id", "name")),
    ("ending", "endings", ("ending_id", "id", "name")),
    ("branch", "branches", ("branch_id", "id", "name")),
)


class ContentProjectionService:
    """Build a canonical, version-scoped projection without changing legacy worldbooks."""

    def __init__(self, conn):
        self.conn = conn

    def rebuild(
        self,
        scenario_version_id: str,
        knowledge_graph: dict[str, Any],
        *,
        requested_by: str,
    ) -> dict[str, Any]:
        graph = _json_object(knowledge_graph)
        input_checksum = _checksum(graph)
        projection_run_id = str(uuid.uuid4())
        items = _canonical_items(scenario_version_id, graph)
        item_ids = {
            (item["item_type"], item["logical_key"]): item["content_item_id"]
            for item in items
        }
        edges, diagnostics = _canonical_edges(
            scenario_version_id, graph, item_ids
        )
        output_checksum = _checksum({"items": items, "edges": edges})

        with self.conn.transaction() as tx:
            _require_version(tx, scenario_version_id)
            tx.execute(
                """
                INSERT INTO content_projection_runs (
                    projection_run_id, scenario_version_id, projection_kind, status,
                    input_checksum, diagnostics, requested_by
                ) VALUES (%s, %s, 'canonical_content', 'running', %s, %s, %s)
                """,
                (
                    projection_run_id,
                    scenario_version_id,
                    input_checksum,
                    json.dumps({"warnings": diagnostics}, ensure_ascii=False),
                    requested_by,
                ),
            )
            tx.execute(
                "DELETE FROM content_items WHERE scenario_version_id = %s",
                (scenario_version_id,),
            )
            for item in items:
                tx.execute(
                    """
                    INSERT INTO content_items (
                        content_item_id, scenario_version_id, source_part_id, item_type,
                        logical_key, title, visibility, payload, citation, checksum, ordinal
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        item["content_item_id"],
                        scenario_version_id,
                        item["source_part_id"],
                        item["item_type"],
                        item["logical_key"],
                        item["title"],
                        item["visibility"],
                        json.dumps(item["payload"], ensure_ascii=False),
                        json.dumps(item["citation"], ensure_ascii=False),
                        item["checksum"],
                        item["ordinal"],
                    ),
                )
            for edge in edges:
                tx.execute(
                    """
                    INSERT INTO content_item_edges (
                        content_item_edge_id, scenario_version_id, from_content_item_id,
                        to_content_item_id, relation_type, conditions, citation, ordinal
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        edge["content_item_edge_id"],
                        scenario_version_id,
                        edge["from_content_item_id"],
                        edge["to_content_item_id"],
                        edge["relation_type"],
                        json.dumps(edge["conditions"], ensure_ascii=False),
                        json.dumps(edge["citation"], ensure_ascii=False),
                        edge["ordinal"],
                    ),
                )
            tx.execute(
                """
                UPDATE content_projection_runs
                SET status = 'completed', output_checksum = %s, completed_at = NOW()
                WHERE projection_run_id = %s
                """,
                (output_checksum, projection_run_id),
            )

        return {
            "projection_run_id": projection_run_id,
            "status": "completed",
            "item_count": len(items),
            "edge_count": len(edges),
            "warnings": diagnostics,
        }

    def reset(self, scenario_version_id: str, *, requested_by: str) -> dict[str, Any]:
        projection_run_id = str(uuid.uuid4())
        input_checksum = _checksum({"operation": "reset", "version": scenario_version_id})
        output_checksum = _checksum({"items": [], "edges": []})
        with self.conn.transaction() as tx:
            _require_version(tx, scenario_version_id)
            tx.execute(
                "DELETE FROM content_items WHERE scenario_version_id = %s",
                (scenario_version_id,),
            )
            tx.execute(
                """
                INSERT INTO content_projection_runs (
                    projection_run_id, scenario_version_id, projection_kind, status,
                    input_checksum, output_checksum, diagnostics, requested_by, completed_at
                ) VALUES (%s, %s, 'canonical_content', 'reset', %s, %s, %s, %s, NOW())
                """,
                (
                    projection_run_id,
                    scenario_version_id,
                    input_checksum,
                    output_checksum,
                    json.dumps({"operation": "reset"}, ensure_ascii=False),
                    requested_by,
                ),
            )
        return {"projection_run_id": projection_run_id, "status": "reset"}

    def items(self, scenario_version_id: str) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            """
            SELECT content_item_id, source_part_id, item_type, logical_key, title,
                   visibility, payload, citation, checksum, ordinal
            FROM content_items
            WHERE scenario_version_id = %s
            ORDER BY item_type, ordinal, logical_key
            """,
            (scenario_version_id,),
        ).fetchall()
        return [{
            "content_item_id": row["content_item_id"],
            "source_part_id": row.get("source_part_id"),
            "item_type": row["item_type"],
            "logical_key": row["logical_key"],
            "title": row["title"],
            "visibility": row["visibility"],
            "payload": _json_object(row.get("payload")),
            "citation": _json_object(row.get("citation")),
            "checksum": row["checksum"],
            "ordinal": row["ordinal"],
        } for row in rows]


def _canonical_items(
    scenario_version_id: str, knowledge_graph: dict[str, Any]
) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for item_type, source_key, identifier_keys in _ITEM_SPECS:
        values = knowledge_graph.get(source_key) or []
        if not isinstance(values, list):
            continue
        for ordinal, value in enumerate(values):
            if not isinstance(value, dict):
                continue
            logical_key = _logical_key(value, identifier_keys, ordinal)
            items.append(
                _make_item(
                    scenario_version_id,
                    item_type,
                    logical_key,
                    value,
                    ordinal,
                )
            )

    truth = knowledge_graph.get("truth")
    if isinstance(truth, dict) and truth:
        items.append(_make_item(scenario_version_id, "truth", "truth", truth, 0))
    solo_adventure = _json_object(knowledge_graph.get("solo_adventure"))
    solo_nodes = solo_adventure.get("nodes") or []
    if isinstance(solo_nodes, list):
        for ordinal, node in enumerate(solo_nodes):
            if not isinstance(node, dict):
                continue
            logical_key = _logical_key(node, ("node_id", "id", "name"), ordinal)
            items.append(
                _make_item(
                    scenario_version_id,
                    "branch_node",
                    logical_key,
                    node,
                    ordinal,
                )
            )
    return items


def _canonical_edges(
    scenario_version_id: str,
    knowledge_graph: dict[str, Any],
    item_ids: dict[tuple[str, str], str],
) -> tuple[list[dict[str, Any]], list[str]]:
    edges: list[dict[str, Any]] = []
    diagnostics: list[str] = []
    branches = knowledge_graph.get("branches") or []
    if not isinstance(branches, list):
        return edges, diagnostics
    for ordinal, branch in enumerate(branches):
        if not isinstance(branch, dict):
            continue
        from_key = str(branch.get("from_scene_id") or branch.get("from") or "").strip()
        to_key = str(branch.get("to_scene_id") or branch.get("to") or "").strip()
        from_id = item_ids.get(("scene", from_key))
        to_id = item_ids.get(("scene", to_key))
        branch_key = _logical_key(branch, ("branch_id", "id", "name"), ordinal)
        if not from_id or not to_id:
            diagnostics.append(f"branch:{branch_key}:missing_scene_target")
            continue
        citation = _citation(branch)
        edge_id = str(uuid.uuid5(
            uuid.NAMESPACE_URL,
            f"aikeeper://{scenario_version_id}/transitions_to/{from_key}/{to_key}/{branch_key}",
        ))
        conditions = branch.get("conditions")
        edges.append({
            "content_item_edge_id": edge_id,
            "from_content_item_id": from_id,
            "to_content_item_id": to_id,
            "relation_type": "transitions_to",
            "conditions": conditions if isinstance(conditions, list) else [],
            "citation": citation,
            "ordinal": ordinal,
        })
    solo_adventure = _json_object(knowledge_graph.get("solo_adventure"))
    solo_nodes = solo_adventure.get("nodes") or []
    if not isinstance(solo_nodes, list):
        return edges, diagnostics
    for node_ordinal, node in enumerate(solo_nodes):
        if not isinstance(node, dict):
            continue
        from_key = _logical_key(node, ("node_id", "id", "name"), node_ordinal)
        from_id = item_ids.get(("branch_node", from_key))
        targets = node.get("target_node_ids") or []
        if not isinstance(targets, list):
            continue
        for target_ordinal, target in enumerate(targets):
            to_key = str(target or "").strip()
            to_id = item_ids.get(("branch_node", to_key))
            if not from_id or not to_id:
                diagnostics.append(f"solo_node:{from_key}:missing_target:{to_key}")
                continue
            edge_id = str(uuid.uuid5(
                uuid.NAMESPACE_URL,
                f"aikeeper://{scenario_version_id}/solo/{from_key}/{to_key}/{target_ordinal}",
            ))
            conditions = node.get("conditions")
            edges.append({
                "content_item_edge_id": edge_id,
                "from_content_item_id": from_id,
                "to_content_item_id": to_id,
                "relation_type": "transitions_to",
                "conditions": conditions if isinstance(conditions, list) else [],
                "citation": _citation(node),
                "ordinal": target_ordinal,
            })
    return edges, diagnostics


def _make_item(
    scenario_version_id: str,
    item_type: str,
    logical_key: str,
    payload: dict[str, Any],
    ordinal: int,
) -> dict[str, Any]:
    citation = _citation(payload)
    title = str(
        payload.get("name")
        or payload.get("title")
        or payload.get("summary")
        or logical_key
    ).strip()
    content_item_id = str(uuid.uuid5(
        uuid.NAMESPACE_URL,
        f"aikeeper://{scenario_version_id}/{item_type}/{logical_key}",
    ))
    return {
        "content_item_id": content_item_id,
        "item_type": item_type,
        "logical_key": logical_key,
        "title": title or logical_key,
        "visibility": _visibility(payload),
        "payload": payload,
        "citation": citation,
        "source_part_id": citation.get("source_part_id"),
        "checksum": _checksum({"item_type": item_type, "logical_key": logical_key, "payload": payload, "citation": citation}),
        "ordinal": ordinal,
    }


def _logical_key(value: dict[str, Any], keys: tuple[str, ...], ordinal: int) -> str:
    for key in keys:
        candidate = str(value.get(key) or "").strip()
        if candidate:
            return candidate
    return f"{keys[0]}-{ordinal + 1}"


def _citation(value: dict[str, Any]) -> dict[str, Any]:
    raw = value.get("citation")
    citation = dict(raw) if isinstance(raw, dict) else {}
    for key in ("source_part_id", "source_ref", "page_number", "anchor", "excerpt"):
        if key not in citation and value.get(key) not in (None, ""):
            citation[key] = value[key]
    return citation


def _visibility(value: dict[str, Any]) -> str:
    visibility = str(value.get("visibility") or "").strip()
    if visibility in {"player", "host_only", "keeper", "internal"}:
        return visibility
    return "host_only"


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


def _checksum(value: Any) -> str:
    serialized = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _require_version(conn, scenario_version_id: str) -> None:
    row = conn.execute(
        "SELECT scenario_version_id FROM scenario_versions WHERE scenario_version_id = %s",
        (scenario_version_id,),
    ).fetchone()
    if not row:
        raise ValueError(f"scenario version not found: {scenario_version_id}")
