from __future__ import annotations

import base64
import hashlib
import json
import logging
import shutil
import uuid
from pathlib import Path
from typing import Any


logger = logging.getLogger(__name__)


TARGET_TYPES = {"map", "branch_node", "scene", "item", "clue", "npc", "ending"}
BINDING_STATUSES = {"draft", "confirmed", "rejected", "stale"}
GENERIC_IMAGE_STEMS = {"火", "炎", "熊熊", "风景", "旅途"}


class AssetBindingError(ValueError):
    pass


class ScenarioAssetBindingService:
    def __init__(self, conn, *, asset_root: Path | None = None, gateway=None):
        self.conn = conn
        self.asset_root = asset_root or (
            Path(__file__).resolve().parents[3] / "data" / "scenario_assets"
        )
        self.gateway = gateway

    def materialize_source_images(
        self,
        scenario_id: str,
        source_rows: list[dict[str, Any]],
        source_root: Path,
    ) -> list[dict[str, Any]]:
        source_root = source_root.resolve()
        materialized = []
        for row in source_rows:
            if not str(row.get("mime_type") or "").startswith("image/"):
                continue
            source_document_id = str(row["source_document_id"])
            existing = self.conn.execute(
                "SELECT * FROM scenario_assets WHERE source_document_id = %s",
                (source_document_id,),
            ).fetchone()
            if existing:
                materialized.append(dict(existing))
                continue
            source_path = (source_root / str(row["relative_path"])).resolve()
            if not source_path.is_relative_to(source_root) or not source_path.is_file():
                raise AssetBindingError("source_image_unavailable")
            extension = Path(str(row.get("filename") or source_path.name)).suffix.lower() or ".bin"
            asset_id = hashlib.sha256(source_document_id.encode("utf-8")).hexdigest()[:12]
            stored_name = f"{asset_id}{extension}"
            destination_dir = self.asset_root / scenario_id
            destination_dir.mkdir(parents=True, exist_ok=True)
            destination = destination_dir / stored_name
            shutil.copyfile(source_path, destination)
            self.conn.execute(
                "INSERT INTO scenario_assets "
                "(asset_id, scenario_id, filename, original_name, mime_type, file_size, "
                "relative_path, visibility, source_document_id) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, 'host_only', %s) "
                "ON CONFLICT (source_document_id) WHERE source_document_id IS NOT NULL DO NOTHING",
                (
                    asset_id,
                    scenario_id,
                    stored_name,
                    Path(str(row.get("filename") or source_path.name)).name,
                    row.get("mime_type") or "application/octet-stream",
                    destination.stat().st_size,
                    f"data/scenario_assets/{scenario_id}/{stored_name}",
                    source_document_id,
                ),
            )
            self.conn.commit()
            created = self.conn.execute(
                "SELECT * FROM scenario_assets WHERE source_document_id = %s",
                (source_document_id,),
            ).fetchone()
            materialized.append(dict(created))
        return materialized

    async def generate_bindings(self, scenario_version_id: str) -> list[dict[str, Any]]:
        version = self.conn.execute(
            "SELECT scenario_id, knowledge_graph FROM scenario_versions "
            "WHERE scenario_version_id = %s",
            (scenario_version_id,),
        ).fetchone()
        if not version:
            raise AssetBindingError("scenario_version_not_found")
        graph = _json_object(version.get("knowledge_graph"))
        targets = _binding_targets(graph)
        assets = self.conn.execute(
            "SELECT * FROM scenario_assets WHERE scenario_id = %s ORDER BY created_at, asset_id",
            (version["scenario_id"],),
        ).fetchall()
        provider_suggestions = {}
        if self.gateway and hasattr(self.gateway, "bind_scenario_assets"):
            try:
                provider_assets = [
                    self._provider_asset(version["scenario_id"], dict(asset))
                    for asset in assets
                ]
                raw_suggestions = await self.gateway.bind_scenario_assets(
                    provider_assets,
                    [
                        {
                            "target_type": target["target_type"],
                            "target_key": target["target_key"],
                            "label": target["label"],
                        }
                        for target in targets
                    ],
                )
                valid_targets = {
                    (target["target_type"], target["target_key"])
                    for target in targets
                }
                for suggestion in raw_suggestions or []:
                    asset_id = str(suggestion.get("asset_id") or "")
                    target_type = str(suggestion.get("target_type") or "")
                    target_key = str(suggestion.get("target_key") or "")
                    if asset_id and (target_type, target_key) in valid_targets:
                        provider_suggestions[asset_id] = {
                            "target_type": target_type,
                            "target_key": target_key,
                            "confidence": max(
                                0.0,
                                min(1.0, float(suggestion.get("confidence") or 0)),
                            ),
                            "evidence": suggestion.get("evidence")
                            if isinstance(suggestion.get("evidence"), dict)
                            else {},
                        }
            except Exception:
                logger.exception(
                    "Multimodal asset binding failed for version %s; using local suggestions",
                    scenario_version_id,
                )
        for asset_row in assets:
            asset = dict(asset_row)
            existing = self.conn.execute(
                "SELECT * FROM scenario_asset_bindings "
                "WHERE scenario_version_id = %s AND asset_id = %s",
                (scenario_version_id, asset["asset_id"]),
            ).fetchone()
            if existing and existing["status"] == "confirmed":
                continue
            suggestion = provider_suggestions.get(asset["asset_id"]) or _local_suggestion(
                asset, targets
            )
            generated_by = "gateway" if asset["asset_id"] in provider_suggestions else "local"
            self.conn.execute(
                "INSERT INTO scenario_asset_bindings "
                "(binding_id, scenario_version_id, asset_id, target_type, target_key, "
                "confidence, evidence, generated_by, status) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'draft') "
                "ON CONFLICT (scenario_version_id, asset_id) DO UPDATE SET "
                "target_type = EXCLUDED.target_type, target_key = EXCLUDED.target_key, "
                "confidence = EXCLUDED.confidence, evidence = EXCLUDED.evidence, "
                "generated_by = EXCLUDED.generated_by, status = 'draft', updated_at = NOW()",
                (
                    str(existing["binding_id"]) if existing else str(uuid.uuid4()),
                    scenario_version_id,
                    asset["asset_id"],
                    suggestion["target_type"],
                    suggestion["target_key"],
                    suggestion["confidence"],
                    json.dumps(suggestion["evidence"], ensure_ascii=False),
                    generated_by,
                ),
            )
        self.conn.commit()
        return self.list_bindings(scenario_version_id)

    def _provider_asset(self, scenario_id: str, asset: dict[str, Any]) -> dict[str, Any]:
        path = (self.asset_root / scenario_id / str(asset["filename"])).resolve()
        if not path.is_relative_to(self.asset_root.resolve()) or not path.is_file():
            raise AssetBindingError("asset_file_unavailable")
        mime_type = str(asset.get("mime_type") or "image/png")
        data_url = (
            f"data:{mime_type};base64,"
            + base64.b64encode(path.read_bytes()).decode("ascii")
        )
        return {
            "asset_id": asset["asset_id"],
            "original_name": asset.get("original_name") or asset.get("filename") or "",
            "mime_type": mime_type,
            "data_url": data_url,
        }

    def list_bindings(self, scenario_version_id: str) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT sab.*, sa.original_name, sa.mime_type, sa.visibility AS asset_visibility "
            "FROM scenario_asset_bindings sab "
            "JOIN scenario_assets sa ON sa.asset_id = sab.asset_id "
            "WHERE sab.scenario_version_id = %s ORDER BY sa.created_at, sa.asset_id",
            (scenario_version_id,),
        ).fetchall()
        return [dict(row) for row in rows]

    def list_targets(self, scenario_version_id: str) -> list[dict[str, str]]:
        version = self.conn.execute(
            "SELECT knowledge_graph FROM scenario_versions WHERE scenario_version_id = %s",
            (scenario_version_id,),
        ).fetchone()
        if not version:
            raise AssetBindingError("scenario_version_not_found")
        return [
            {
                "target_type": target["target_type"],
                "target_key": target["target_key"],
                "label": target["label"],
            }
            for target in _binding_targets(_json_object(version.get("knowledge_graph")))
        ]

    def review_binding(
        self,
        binding_id: str,
        *,
        target_type: str,
        target_key: str,
        status: str,
        reviewed_by: str,
    ) -> dict[str, Any]:
        if target_type not in TARGET_TYPES or status not in BINDING_STATUSES:
            raise AssetBindingError("invalid_binding_review")
        binding = self.conn.execute(
            "SELECT * FROM scenario_asset_bindings WHERE binding_id = %s",
            (binding_id,),
        ).fetchone()
        if not binding:
            raise AssetBindingError("binding_not_found")
        version = self.conn.execute(
            "SELECT knowledge_graph FROM scenario_versions WHERE scenario_version_id = %s",
            (binding["scenario_version_id"],),
        ).fetchone()
        targets = _binding_targets(_json_object(version.get("knowledge_graph") if version else {}))
        if status == "confirmed" and (target_type, target_key) not in {
            (target["target_type"], target["target_key"]) for target in targets
        }:
            raise AssetBindingError("binding_target_not_found")
        reviewed_at = "NOW()" if status in {"confirmed", "rejected"} else "NULL"
        row = self.conn.execute(
            "UPDATE scenario_asset_bindings SET target_type = %s, target_key = %s, "
            "status = %s, reviewed_by = %s, reviewed_at = " + reviewed_at + ", "
            "updated_at = NOW() WHERE binding_id = %s RETURNING *",
            (target_type, target_key, status, reviewed_by, binding_id),
        ).fetchone()
        self.conn.commit()
        return dict(row)

    def confirmed_asset_for_target(
        self,
        scenario_version_id: str,
        target_type: str,
        target_key: str,
    ) -> dict[str, Any] | None:
        row = self.conn.execute(
            "SELECT sab.*, sa.original_name, sa.mime_type, sa.visibility AS asset_visibility "
            "FROM scenario_asset_bindings sab "
            "JOIN scenario_assets sa ON sa.asset_id = sab.asset_id "
            "WHERE sab.scenario_version_id = %s AND sab.target_type = %s "
            "AND sab.target_key = %s AND sab.status = 'confirmed' "
            "ORDER BY sab.confidence DESC, sab.created_at LIMIT 1",
            (scenario_version_id, target_type, target_key),
        ).fetchone()
        return dict(row) if row else None


def _binding_targets(graph: dict[str, Any]) -> list[dict[str, str]]:
    targets = [{"target_type": "map", "target_key": "map", "label": "地图", "search": "地图 map"}]
    solo = _json_object(graph.get("solo_adventure"))
    for node in solo.get("nodes") or []:
        if isinstance(node, dict) and node.get("node_id"):
            targets.append({
                "target_type": "branch_node",
                "target_key": str(node["node_id"]),
                "label": str(node.get("title") or f"条目 {node['node_id']}"),
                "search": " ".join(str(node.get(key) or "") for key in ("title", "text")),
            })
    for target_type, collection_name, id_keys in (
        ("scene", "scenes", ("scene_id", "sceneId", "id")),
        ("item", "items", ("item_id", "itemId", "id")),
        ("clue", "clues", ("clue_id", "clueId", "id")),
        ("npc", "npcs", ("npc_id", "npcId", "id")),
        ("ending", "endings", ("ending_id", "endingId", "id")),
    ):
        collection = graph.get(collection_name) or []
        if isinstance(collection, dict):
            collection = [dict(value, id=key) for key, value in collection.items() if isinstance(value, dict)]
        for index, item in enumerate(collection):
            if not isinstance(item, dict):
                continue
            target_key = next((str(item[key]) for key in id_keys if item.get(key)), str(index))
            label = str(item.get("name") or item.get("title") or target_key)
            targets.append({
                "target_type": target_type,
                "target_key": target_key,
                "label": label,
                "search": " ".join(str(item.get(key) or "") for key in ("name", "title", "description", "text")),
            })
    return targets


def _local_suggestion(asset: dict[str, Any], targets: list[dict[str, str]]) -> dict[str, Any]:
    stem = Path(str(asset.get("original_name") or asset.get("filename") or "")).stem.strip().lower()
    if stem in {"地图", "map"}:
        return {
            "target_type": "map",
            "target_key": "map",
            "confidence": 0.99,
            "evidence": {"method": "exact_filename", "matched_text": stem},
        }
    candidates = []
    for target in targets:
        label = target["label"].lower()
        search = target["search"].lower()
        if stem and stem == label:
            candidates.append((0.96, target, "exact_label"))
        elif stem and stem not in GENERIC_IMAGE_STEMS and stem in search:
            candidates.append((0.85, target, "content_match"))
    if candidates:
        confidence, target, method = sorted(candidates, key=lambda item: item[0], reverse=True)[0]
        return {
            "target_type": target["target_type"],
            "target_key": target["target_key"],
            "confidence": confidence,
            "evidence": {"method": method, "matched_text": stem},
        }
    return {
        "target_type": "scene",
        "target_key": "",
        "confidence": 0.0,
        "evidence": {"method": "unmatched", "matched_text": stem},
    }


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
