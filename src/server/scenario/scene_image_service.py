"""Review-only scene image suggestions, previews, and confirmed bindings."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
import uuid
from pathlib import Path
from typing import Any


_ALLOWED_IMAGE_MIME_TYPES = {"image/png", "image/jpeg", "image/webp"}
_ALLOWED_SIZES = {"1024x1024", "1536x1024", "1024x1536"}
_MAX_IMAGE_BYTES = 8 * 1024 * 1024
_PREVIEW_TTL_SECONDS = 30 * 60
_SUGGESTIBLE_TARGET_TYPES = {"scene", "npc", "item", "clue"}
_SUGGESTIBLE_TARGET_ORDER = ("scene", "npc", "item", "clue")
_TARGET_COLLECTIONS = {
    "scene": ("scenes", ("scene_id", "sceneId", "id")),
    "npc": ("npcs", ("npc_id", "npcId", "id")),
    "item": ("items", ("item_id", "itemId", "id")),
    "clue": ("clues", ("clue_id", "clueId", "id")),
}


class SceneImageError(ValueError):
    """Raised for safe, administrator-facing scene image workflow errors."""


class SceneImageService:
    """Keep AI image creation behind an explicit review and adoption boundary."""

    def __init__(self, conn, *, gateway=None, asset_root: Path | None = None):
        self.conn = conn
        self.gateway = gateway
        self.asset_root = asset_root or (
            Path(__file__).resolve().parents[3] / "data" / "scenario_assets"
        )

    async def suggest(
        self,
        scenario_id: str,
        scenario_version_id: str,
        *,
        target_types: set[str] | None = None,
    ) -> dict[str, Any]:
        graph = self._review_graph(scenario_id, scenario_version_id)
        requested_types = target_types or {"scene"}
        if not requested_types <= _SUGGESTIBLE_TARGET_TYPES:
            raise SceneImageError("image_target_type_invalid")
        targets = self._missing_image_targets(graph, scenario_version_id, requested_types)
        if not targets:
            return {"summary": "所选目标都已有确认配图。", "suggestions": []}
        if not self.gateway:
            raise SceneImageError("image_suggestion_provider_unavailable")

        source_parts = self._source_excerpts(scenario_version_id)
        try:
            if requested_types == {"scene"} and hasattr(self.gateway, "suggest_scene_images"):
                response = await self.gateway.suggest_scene_images({
                    "scenes": targets,
                    "source_parts": source_parts,
                })
            elif hasattr(self.gateway, "suggest_scenario_images"):
                response = await self.gateway.suggest_scenario_images({
                    "targets": targets,
                    "source_parts": source_parts,
                })
            else:
                raise SceneImageError("image_suggestion_provider_unavailable")
        except Exception as exc:
            if isinstance(exc, SceneImageError):
                raise
            raise SceneImageError("image_suggestion_provider_unavailable") from exc
        if not isinstance(response, dict):
            raise SceneImageError("image_suggestion_provider_unavailable")

        valid_targets = {
            (str(target["target_type"]), str(target["target_key"]))
            for target in targets
        }
        valid_part_ids = {part["source_part_id"] for part in source_parts}
        suggestions = []
        suggested_targets: set[tuple[str, str]] = set()
        for raw in response.get("suggestions") or []:
            if not isinstance(raw, dict):
                continue
            target_type = str(raw.get("target_type") or ("scene" if requested_types == {"scene"} else "")).strip()
            target_key = str(raw.get("target_key") or raw.get("scene_id") or "").strip()
            citation = _json_object(raw.get("citation"))
            target = (target_type, target_key)
            if (
                target not in valid_targets
                or target in suggested_targets
                or str(citation.get("source_part_id") or "") not in valid_part_ids
            ):
                continue
            image_summary = str(raw.get("image_summary") or "").strip()
            prompt = str(raw.get("prompt") or "").strip()
            if not image_summary or not prompt:
                continue
            suggested_targets.add(target)
            suggestions.append({
                "target_type": target_type,
                "target_key": target_key,
                "scene_id": target_key if target_type == "scene" else None,
                "image_summary": image_summary,
                "prompt": prompt,
                "style": str(raw.get("style") or "调查恐怖插画，避免任何文字").strip(),
                "visibility": "host_only",
                "confidence": _confidence(raw.get("confidence")),
                "citation": citation,
            })
        return {
            "summary": str(response.get("summary") or "AI 已依据原文起草待确认配图。"),
            "suggestions": suggestions,
        }

    async def preview(
        self,
        scenario_id: str,
        scenario_version_id: str,
        *,
        suggestion: dict[str, Any],
        prompt: str,
        visibility: str,
        size: str,
    ) -> dict[str, Any]:
        graph = self._review_graph(scenario_id, scenario_version_id)
        target_type, target_key, target, citation = self._validated_suggestion(
            graph,
            scenario_version_id,
            suggestion,
        )
        if visibility not in {"host_only", "party"}:
            raise SceneImageError("image_visibility_invalid")
        if size not in _ALLOWED_SIZES:
            raise SceneImageError("image_size_invalid")
        if visibility == "party":
            generated_prompt = _public_target_prompt(graph, target_type, target_key, target)
        else:
            generated_prompt = str(prompt or suggestion.get("prompt") or "").strip()
            if not generated_prompt or len(generated_prompt) > 3_000:
                raise SceneImageError("image_prompt_invalid")
        if not self.gateway or not hasattr(self.gateway, "generate_scene_image"):
            raise SceneImageError("image_provider_unavailable")
        try:
            result = await self.gateway.generate_scene_image({
                "prompt": generated_prompt,
                "size": size,
            })
        except Exception as exc:
            raise SceneImageError("image_provider_unavailable") from exc
        if not isinstance(result, dict):
            raise SceneImageError("image_provider_unavailable")
        data_url, mime_type, image_bytes = _decode_image_data_url(result.get("data_url"))
        preview_payload = {
            "scenario_id": scenario_id,
            "scenario_version_id": scenario_version_id,
            "target_type": target_type,
            "target_key": target_key,
            "visibility": visibility,
            "citation": citation,
            "image_sha256": hashlib.sha256(image_bytes).hexdigest(),
            "expires_at": int(time.time()) + _PREVIEW_TTL_SECONDS,
        }
        return {
            "target_type": target_type,
            "target_key": target_key,
            "scene_id": target_key if target_type == "scene" else None,
            "visibility": visibility,
            "size": size,
            "mime_type": mime_type,
            "data_url": data_url,
            "generated_prompt": generated_prompt,
            "preview_token": _sign_preview(preview_payload),
        }

    def adopt(
        self,
        scenario_id: str,
        scenario_version_id: str,
        *,
        preview_token: str,
        data_url: str,
        adopted_by: str,
    ) -> dict[str, Any]:
        graph = self._review_graph(scenario_id, scenario_version_id)
        preview = _verify_preview(preview_token)
        if (
            preview.get("scenario_id") != scenario_id
            or preview.get("scenario_version_id") != scenario_version_id
            or int(preview.get("expires_at") or 0) < int(time.time())
        ):
            raise SceneImageError("image_preview_expired")
        target_type = str(preview.get("target_type") or "scene")
        target_key = str(preview.get("target_key") or preview.get("scene_id") or "")
        if not _find_target(graph, target_type, target_key):
            raise SceneImageError("image_target_not_found")
        data_url, mime_type, image_bytes = _decode_image_data_url(data_url)
        if not hmac.compare_digest(
            str(preview.get("image_sha256") or ""),
            hashlib.sha256(image_bytes).hexdigest(),
        ):
            raise SceneImageError("image_preview_mismatch")
        citation = _json_object(preview.get("citation"))
        self._assert_source_part_in_version(scenario_version_id, citation)

        asset_id = str(uuid.uuid4())
        extension = {"image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp"}[mime_type]
        filename = f"{asset_id}{extension}"
        directory = self.asset_root / scenario_id
        directory.mkdir(parents=True, exist_ok=True)
        destination = directory / filename
        destination.write_bytes(image_bytes)
        visibility = str(preview.get("visibility") or "host_only")
        binding_id = str(uuid.uuid4())
        patch_id = str(uuid.uuid4())
        try:
            with self.conn.transaction() as tx:
                tx.execute(
                    """
                    INSERT INTO scenario_assets (
                        asset_id, scenario_id, filename, original_name, mime_type,
                        file_size, relative_path, visibility
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        asset_id, scenario_id, filename, f"AI {_target_label(target_type)}图 {target_key}{extension}",
                        mime_type, len(image_bytes),
                        f"data/scenario_assets/{scenario_id}/{filename}", visibility,
                    ),
                )
                tx.execute(
                    """
                    INSERT INTO scenario_asset_bindings (
                        binding_id, scenario_version_id, asset_id, target_type, target_key,
                        confidence, evidence, generated_by, status, reviewed_by, reviewed_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, 'ai_image_generation',
                              'confirmed', %s, NOW())
                    """,
                    (
                        binding_id, scenario_version_id, asset_id, target_type, target_key, 1.0,
                        json.dumps({"citation": citation, "preview": "administrator_confirmed"}, ensure_ascii=False),
                        adopted_by,
                    ),
                )
                tx.execute(
                    """
                    INSERT INTO scenario_review_patches (
                        review_patch_id, scenario_version_id, target_type, target_key,
                        payload, provenance, citation, rationale, created_by
                    ) VALUES (%s, %s, %s, %s, %s, 'source', %s, %s, %s)
                    """,
                    (
                        patch_id, scenario_version_id, target_type, target_key,
                        json.dumps({
                            _target_id_key(target_type): target_key,
                            "image_asset_id": asset_id,
                            "image_visibility": visibility,
                        }, ensure_ascii=False),
                        json.dumps(citation, ensure_ascii=False),
                        "管理员确认 AI 场景配图并绑定到审核草稿。",
                        adopted_by,
                    ),
                )
        except Exception:
            destination.unlink(missing_ok=True)
            raise
        return {
            "asset": {
                "asset_id": asset_id,
                "filename": filename,
                "mime_type": mime_type,
                "visibility": visibility,
            },
            "binding": {
                "binding_id": binding_id,
                "target_type": target_type,
                "target_key": target_key,
                "status": "confirmed",
            },
            "review_patch_id": patch_id,
        }

    def _review_graph(self, scenario_id: str, scenario_version_id: str) -> dict[str, Any]:
        version = self.conn.execute(
            """
            SELECT sv.knowledge_graph
            FROM scenario_versions sv
            JOIN scenario_review_drafts srd ON srd.scenario_version_id = sv.scenario_version_id
            WHERE sv.scenario_id = %s AND sv.scenario_version_id = %s
            """,
            (scenario_id, scenario_version_id),
        ).fetchone()
        if not version:
            raise SceneImageError("scenario_review_draft_not_found")
        return _json_object(version.get("knowledge_graph"))

    def _missing_image_targets(
        self,
        graph: dict[str, Any],
        scenario_version_id: str,
        target_types: set[str],
    ) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            """
            SELECT target_type, target_key FROM scenario_asset_bindings
            WHERE scenario_version_id = %s AND status = 'confirmed'
            """,
            (scenario_version_id,),
        ).fetchall()
        bound_targets = {
            (str(row.get("target_type") or ""), str(row.get("target_key") or ""))
            for row in rows
        }
        targets = []
        for target_type in _SUGGESTIBLE_TARGET_ORDER:
            if target_type not in target_types:
                continue
            collection_name, id_keys = _TARGET_COLLECTIONS[target_type]
            for index, raw_target in enumerate(_collection_values(graph.get(collection_name))):
                if not isinstance(raw_target, dict) or raw_target.get("image_asset_id"):
                    continue
                target_key = _target_key(raw_target, id_keys, index)
                if not target_key or (target_type, target_key) in bound_targets:
                    continue
                targets.append({
                    "target_type": target_type,
                    "target_key": target_key,
                    "scene_id": target_key if target_type == "scene" else None,
                    "name": str(raw_target.get("name") or raw_target.get("title") or target_key),
                    "description": str(raw_target.get("description") or raw_target.get("summary") or raw_target.get("text") or ""),
                    "public_description": str(raw_target.get("public_description") or ""),
                })
        return targets

    def _validated_suggestion(
        self,
        graph: dict[str, Any],
        scenario_version_id: str,
        suggestion: dict[str, Any],
    ) -> tuple[str, str, dict[str, Any], dict[str, Any]]:
        if not isinstance(suggestion, dict):
            raise SceneImageError("image_suggestion_invalid")
        target_type = str(suggestion.get("target_type") or "scene").strip()
        target_key = str(suggestion.get("target_key") or suggestion.get("scene_id") or "").strip()
        target = _find_target(graph, target_type, target_key)
        if not target:
            raise SceneImageError("image_target_not_found")
        citation = _json_object(suggestion.get("citation"))
        self._assert_source_part_in_version(scenario_version_id, citation)
        return target_type, target_key, target, citation

    def _assert_source_part_in_version(self, scenario_version_id: str, citation: dict[str, Any]) -> None:
        source_part_id = str(citation.get("source_part_id") or "")
        row = self.conn.execute(
            """
            SELECT 1
            FROM scenario_version_sources svs
            JOIN source_parts sp ON sp.source_document_id = svs.source_document_id
            WHERE svs.scenario_version_id = %s AND sp.source_part_id = %s
            """,
            (scenario_version_id, source_part_id),
        ).fetchone()
        if not row:
            raise SceneImageError("image_suggestion_citation_invalid")

    def _source_excerpts(self, scenario_version_id: str) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            """
            SELECT sp.source_part_id, sp.page_number, sp.anchor, sp.text_content
            FROM scenario_version_sources svs
            JOIN source_parts sp ON sp.source_document_id = svs.source_document_id
            WHERE svs.scenario_version_id = %s
            ORDER BY svs.ordinal, sp.ordinal
            """,
            (scenario_version_id,),
        ).fetchall()
        remaining = 24_000
        excerpts = []
        for row in rows:
            if remaining <= 0:
                break
            text = str(row.get("text_content") or "").strip()
            excerpt = text[: min(4_000, remaining)]
            remaining -= len(excerpt)
            excerpts.append({
                "source_part_id": str(row["source_part_id"]),
                "page_number": row.get("page_number"),
                "anchor": _json_object(row.get("anchor")),
                "text_content": excerpt,
            })
        return excerpts


def _collection_values(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if isinstance(value, dict):
        return [
            {**item, "id": key} if isinstance(item, dict) else item
            for key, item in value.items()
        ]
    return []


def _target_key(target: dict[str, Any], id_keys: tuple[str, ...], index: int) -> str:
    for key in id_keys:
        value = str(target.get(key) or "").strip()
        if value:
            return value
    return ""


def _find_target(
    graph: dict[str, Any],
    target_type: str,
    target_key: str,
) -> dict[str, Any] | None:
    target_config = _TARGET_COLLECTIONS.get(target_type)
    if not target_config:
        return None
    collection_name, id_keys = target_config
    for index, raw_target in enumerate(_collection_values(graph.get(collection_name))):
        if isinstance(raw_target, dict) and _target_key(raw_target, id_keys, index) == target_key:
            return raw_target
    return None


def _target_id_key(target_type: str) -> str:
    return {
        "scene": "scene_id",
        "npc": "npc_id",
        "item": "item_id",
        "clue": "clue_id",
    }.get(target_type, "id")


def _target_label(target_type: str) -> str:
    return {
        "scene": "场景",
        "npc": "NPC",
        "item": "物品",
        "clue": "线索",
    }.get(target_type, "素材")


def _public_target_prompt(
    graph: dict[str, Any],
    target_type: str,
    target_key: str,
    target: dict[str, Any],
) -> str:
    public_description = str(target.get("public_description") or "").strip()
    if not public_description:
        for boundary in graph.get("spoiler_boundaries") or []:
            if not isinstance(boundary, dict):
                continue
            if (
                str(boundary.get("target_type") or "") == target_type
                and str(boundary.get("target_id") or "") == target_key
                and str(boundary.get("player_visibility") or "") == "public"
            ):
                public_description = str(boundary.get("player_description") or "").strip()
                break
    if not public_description:
        raise SceneImageError("image_public_description_required")
    return (
        f"为玩家可见的 TRPG {_target_label(target_type)}绘制无文字插画。"
        f"仅可表现以下公开描述：{public_description}。"
        "不得表现隐藏线索、人物真实身份、幕后真相、结局或任何可读文字。"
    )


def _decode_image_data_url(value: Any) -> tuple[str, str, bytes]:
    data_url = str(value or "")
    prefix, separator, encoded = data_url.partition(",")
    if not separator or not prefix.startswith("data:") or not prefix.endswith(";base64"):
        raise SceneImageError("image_preview_invalid")
    mime_type = prefix[5:-7].lower()
    if mime_type not in _ALLOWED_IMAGE_MIME_TYPES:
        raise SceneImageError("image_preview_invalid")
    try:
        image_bytes = base64.b64decode(encoded, validate=True)
    except Exception as exc:
        raise SceneImageError("image_preview_invalid") from exc
    if not image_bytes or len(image_bytes) > _MAX_IMAGE_BYTES:
        raise SceneImageError("image_preview_invalid")
    return data_url, mime_type, image_bytes


def _preview_secret() -> bytes:
    value = os.getenv("AI_CONFIG_MASTER_KEY", "").strip() or os.getenv("JWT_SECRET", "").strip()
    if not value:
        raise SceneImageError("image_preview_token_unavailable")
    return value.encode("utf-8")


def _sign_preview(payload: dict[str, Any]) -> str:
    encoded = base64.urlsafe_b64encode(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    ).decode("ascii")
    signature = hmac.new(_preview_secret(), encoded.encode("ascii"), hashlib.sha256).hexdigest()
    return f"{encoded}.{signature}"


def _verify_preview(token: str) -> dict[str, Any]:
    encoded, separator, signature = str(token or "").partition(".")
    expected = hmac.new(_preview_secret(), encoded.encode("ascii"), hashlib.sha256).hexdigest()
    if not separator or not hmac.compare_digest(expected, signature):
        raise SceneImageError("image_preview_invalid")
    try:
        payload = json.loads(base64.urlsafe_b64decode(encoded.encode("ascii")).decode("utf-8"))
    except Exception as exc:
        raise SceneImageError("image_preview_invalid") from exc
    if not isinstance(payload, dict):
        raise SceneImageError("image_preview_invalid")
    return payload


def _json_object(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    if isinstance(value, str):
        try:
            decoded = json.loads(value)
        except json.JSONDecodeError:
            return {}
        return decoded if isinstance(decoded, dict) else {}
    return {}


def _confidence(value: Any) -> float:
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return 0.0
