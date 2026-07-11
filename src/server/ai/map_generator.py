"""Map generator — AI-driven (DeepSeek) with Python rule-based fallback.

Converts scenario_assets.scenes[] into a node graph (nodes + edges).
Follows the same two-tier pattern as MechanicCompiler:
1. DeepSeek API (when api_key is set) — returns JSON with nodes and edges
2. Python fallback (no API key or API failure) — sequential chain + cross-connections
"""

import json
import logging
import math
from typing import Any

import httpx

logger = logging.getLogger(__name__)

MAP_GEN_SYSTEM_PROMPT = """你是一个TRPG地图生成器。给定剧本的场景列表，生成一个节点图和连接边。

每个场景变成一个节点（node），具有：
- nodeId: "node_0", "node_1" 等（从0开始编号）
- name: 场景名（保持中文原名）
- description: 场景描述（保持中文）
- npcsPresent: 该场景出现的NPC名列表（字符串数组）
- cluesAvailable: 该场景可发现的线索列表（字符串数组）
- position: {x: 0-100, y: 0-100} 布局位置（避免重叠，均匀分布）
- isStart: 是否作为起点（默认第一个场景为true）

边（edge）定义：
- 若场景A的exits明确指向场景B，则创建边
- 相邻场景应双向连接（isOneWay: false）
- 共享NPC或线索的场景也应连接
- 每条边: {fromNode, toNode, isOneWay: false, label: ""}

必须以JSON格式返回，包含 nodes 和 edges 数组。只返回JSON，不要叙事文本。"""


class MapGenerator:
    """Generate map node graph from scenario_assets.scenes[]."""

    def __init__(
        self,
        api_key: str = "",
        model: str = "deepseek-v4-pro",
        api_base: str = "https://api.deepseek.com",
        gateway: Any | None = None,
    ):
        self.api_key = api_key
        self.model = model
        self.api_base = api_base
        self.gateway = gateway
        self.last_generated_by = "python"

    async def generate(self, scenes: list[dict]) -> tuple[list[dict], list[dict]]:
        """Generate nodes and edges from scenes. Returns (nodes, edges)."""
        if not scenes:
            return [], []

        if self.gateway:
            try:
                generated = await self.gateway.generate_map(scenes)
                if _is_complete_gateway_map(generated, len(scenes)):
                    nodes = generated.get("nodes", [])
                    edges = generated.get("edges", [])
                    self.last_generated_by = "gateway"
                    return (
                        [_normalize_node(node, index) for index, node in enumerate(nodes)],
                        [_normalize_edge(edge) for edge in edges],
                    )
            except Exception as exc:
                logger.warning("Configured AI map generation failed: %s", exc)

        if self.api_key:
            for attempt in range(2):
                try:
                    nodes, edges = await self._call_deepseek(scenes)
                    self.last_generated_by = "ai"
                    return nodes, edges
                except Exception as e:
                    logger.warning("AI map generation attempt %d failed: %s", attempt + 1, e)

        self.last_generated_by = "python"
        return _python_generate_map(scenes)

    async def generate_draft(self, scenes: list[dict], base_asset: dict | None = None) -> dict:
        """Generate a reviewable graph or hybrid map draft with normalized regions and paths."""
        nodes, edges = await self.generate(scenes)
        safe_base_asset = _safe_base_asset(base_asset)
        return {
            "map_type": "hybrid" if safe_base_asset else "graph",
            "base_asset": safe_base_asset,
            "nodes": nodes,
            "edges": edges,
            "regions": _regions_from_nodes(nodes),
            "paths": _paths_from_edges(edges),
        }

    async def _call_deepseek(self, scenes: list[dict]) -> tuple[list[dict], list[dict]]:
        """Call DeepSeek API to generate map nodes and edges."""
        scene_data = [
            {
                "index": i,
                "name": s.get("name", f"场景{i+1}"),
                "description": s.get("description", ""),
                "npcsPresent": s.get("npcs_present", s.get("npcsPresent", [])),
                "cluesAvailable": s.get("clues_available", s.get("cluesAvailable", [])),
                "exits": s.get("exits", []),
            }
            for i, s in enumerate(scenes)
        ]

        user_message = json.dumps({"scenes": scene_data}, ensure_ascii=False)

        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(
                f"{self.api_base}/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": self.model,
                    "response_format": {"type": "json_object"},
                    "messages": [
                        {"role": "system", "content": MAP_GEN_SYSTEM_PROMPT},
                        {"role": "user", "content": user_message},
                    ],
                    "temperature": 0.3,
                },
            )
            response.raise_for_status()

        data = response.json()
        content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
        result = json.loads(content)

        nodes = result.get("nodes", [])
        edges = result.get("edges", [])

        # Normalize field names (AI might return camelCase or snake_case)
        nodes = [_normalize_node(n, i) for i, n in enumerate(nodes)]
        edges = [_normalize_edge(e) for e in edges]

        return nodes, edges


def _normalize_node(node: dict, index: int) -> dict:
    return {
        "node_id": node.get("nodeId", node.get("node_id", f"node_{index}")),
        "name": node.get("name", f"区域{index + 1}"),
        "description": node.get("description", ""),
        "npcs_present": node.get("npcsPresent", node.get("npcs_present", [])),
        "clues_available": node.get("cluesAvailable", node.get("clues_available", [])),
        "position": node.get("position", _default_position(index, 0)),
        "is_start": node.get("isStart", node.get("is_start", index == 0)),
    }


def _normalize_edge(edge: dict) -> dict:
    return {
        "from_node": edge.get("fromNode", edge.get("from_node", "")),
        "to_node": edge.get("toNode", edge.get("to_node", "")),
        "is_one_way": edge.get("isOneWay", edge.get("is_one_way", False)),
        "label": edge.get("label", ""),
    }


# ── Python fallback ──

def _python_generate_map(scenes: list[dict]) -> tuple[list[dict], list[dict]]:
    """Construct nodes and edges from scene order + exit data + shared NPC/clue heuristics."""
    n = len(scenes)
    nodes = []
    edges = []

    for i, scene in enumerate(scenes):
        node_id = f"node_{i}"
        nodes.append({
            "node_id": node_id,
            "name": scene.get("name", f"场景{i + 1}"),
            "description": scene.get("description", ""),
            "npcs_present": scene.get("npcs_present", scene.get("npcsPresent", [])),
            "clues_available": scene.get("clues_available", scene.get("cluesAvailable", [])),
            "position": _default_position(i, n),
            "is_start": (i == 0),
        })

    # Sequential edges
    for i in range(n - 1):
        edges.append({
            "from_node": f"node_{i}",
            "to_node": f"node_{i + 1}",
            "is_one_way": False,
            "label": "",
        })

    # Cross-connections: scenes sharing NPCs or clues get connected
    for i in range(n):
        for j in range(i + 2, n):
            if _share_npc_or_clue(nodes[i], nodes[j]):
                edges.append({
                    "from_node": f"node_{i}",
                    "to_node": f"node_{j}",
                    "is_one_way": False,
                    "label": "关联",
                })

    # Process explicit exits from scenes
    for i, scene in enumerate(scenes):
        exits = scene.get("exits", [])
        for exit_name in exits:
            # Find node matching exit name
            for j, node in enumerate(nodes):
                if j != i and (
                    exit_name in node["name"]
                    or node["name"] in exit_name
                ):
                    already_connected = any(
                        (e["from_node"] == f"node_{i}" and e["to_node"] == f"node_{j}")
                        or (e["from_node"] == f"node_{j}" and e["to_node"] == f"node_{i}")
                        for e in edges
                    )
                    if not already_connected:
                        edges.append({
                            "from_node": f"node_{i}",
                            "to_node": f"node_{j}",
                            "is_one_way": False,
                            "label": "",
                        })
                    break

    return nodes, edges


def _share_npc_or_clue(node_a: dict, node_b: dict) -> bool:
    """Check if two nodes share any NPC or clue."""
    npcs_a = set(node_a.get("npcs_present", []))
    npcs_b = set(node_b.get("npcs_present", []))
    clues_a = set(node_a.get("clues_available", []))
    clues_b = set(node_b.get("clues_available", []))
    return bool(npcs_a & npcs_b) or bool(clues_a & clues_b)


def _default_position(index: int, total: int) -> dict[str, float]:
    """Generate a default grid/radial position for a node."""
    if total <= 1:
        return {"x": 50.0, "y": 50.0}

    # Arrange in a circle-ish layout
    angle = (2 * math.pi * index) / total - math.pi / 2
    radius = 35.0
    x = 50.0 + radius * math.cos(angle)
    y = 50.0 + radius * math.sin(angle)
    return {"x": round(x, 1), "y": round(y, 1)}


def _safe_base_asset(base_asset: dict | None) -> dict:
    if not isinstance(base_asset, dict):
        return {}
    asset_id = base_asset.get("assetId", base_asset.get("asset_id", ""))
    return {"assetId": asset_id} if isinstance(asset_id, str) and asset_id else {}


def _regions_from_nodes(nodes: list[dict]) -> list[dict]:
    regions = []
    for index, node in enumerate(nodes):
        node_id = node.get("node_id", node.get("nodeId", f"node_{index}"))
        position = node.get("position", {}) if isinstance(node.get("position", {}), dict) else {}
        raw_x = position.get("x", 50)
        raw_y = position.get("y", 50)
        x = float(raw_x) / 100 if float(raw_x) > 1 else float(raw_x)
        y = float(raw_y) / 100 if float(raw_y) > 1 else float(raw_y)
        left = round(max(0.0, x - 0.05), 4)
        right = round(min(1.0, x + 0.05), 4)
        top = round(max(0.0, y - 0.05), 4)
        bottom = round(min(1.0, y + 0.05), 4)
        regions.append({
            "regionId": f"region-{node_id}",
            "nodeId": node_id,
            "polygon": [[left, top], [right, top], [right, bottom], [left, bottom]],
        })
    return regions


def _paths_from_edges(edges: list[dict]) -> list[dict]:
    return [
        {
            "pathId": f"path-{index}",
            "fromNodeId": edge.get("from_node", edge.get("fromNode", "")),
            "toNodeId": edge.get("to_node", edge.get("toNode", "")),
            "isOneWay": bool(edge.get("is_one_way", edge.get("isOneWay", False))),
            "label": edge.get("label", ""),
        }
        for index, edge in enumerate(edges)
        if edge.get("from_node", edge.get("fromNode", ""))
        and edge.get("to_node", edge.get("toNode", ""))
    ]


def _is_complete_gateway_map(value: Any, scene_count: int) -> bool:
    if not isinstance(value, dict):
        return False
    nodes = value.get("nodes")
    edges = value.get("edges")
    if not isinstance(nodes, list) or not isinstance(edges, list):
        return False
    if len(nodes) < scene_count or any(not isinstance(node, dict) for node in nodes):
        return False
    if scene_count > 1 and not edges:
        return False
    return all(isinstance(edge, dict) for edge in edges)
