"""Administrator-facing scenario review workspace services."""

from __future__ import annotations

import json
import uuid
from typing import Any

from .content_projection import ContentProjectionService
from .module_compiler import ModuleCompiler
from .quality import QualityReportGenerator, _is_complete_spoiler_boundary


class ScenarioReviewError(Exception):
    """Raised when a requested review workspace cannot be loaded."""


def review_publish_blockers(conn, scenario_version_id: str) -> list[dict[str, Any]]:
    """Return unwaivable quality issues for an administrator review draft."""
    draft = conn.execute(
        "SELECT 1 FROM scenario_review_drafts WHERE scenario_version_id = %s",
        (scenario_version_id,),
    ).fetchone()
    if not draft:
        return []
    row = conn.execute(
        "SELECT quality_report FROM scenario_versions WHERE scenario_version_id = %s",
        (scenario_version_id,),
    ).fetchone()
    if not row:
        return []
    return [
        issue
        for raw_issue in _json_object(row.get("quality_report")).get("issues") or []
        if (issue := _json_object(raw_issue)).get("blocking")
    ]


class ScenarioReviewService:
    def __init__(self, conn, *, gateway=None, rag=None):
        self.conn = conn
        self.gateway = gateway
        self.rag = rag

    def get_workbench(self, scenario_id: str, scenario_version_id: str) -> dict[str, Any]:
        version = self.conn.execute(
            """
            SELECT sv.scenario_version_id, sv.scenario_id, sv.version_number, sv.status,
                   sv.knowledge_graph, sv.quality_report, sv.prep_package, s.title
            FROM scenario_versions sv
            JOIN scenarios s ON s.scenario_id = sv.scenario_id
            WHERE sv.scenario_id = %s AND sv.scenario_version_id = %s
            """,
            (scenario_id, scenario_version_id),
        ).fetchone()
        if not version:
            raise ScenarioReviewError("scenario_version_not_found")
        review_draft = self.conn.execute(
            "SELECT 1 FROM scenario_review_drafts WHERE scenario_version_id = %s",
            (scenario_version_id,),
        ).fetchone()

        parts = self.conn.execute(
            """
            SELECT sp.source_part_id, sd.source_document_id, sd.title AS source_title,
                   sd.source_filename, sd.mime_type AS source_mime_type,
                   sp.ordinal, sp.part_kind, sp.page_number, sp.text_content,
                   sp.mime_type, sp.storage_path, sp.anchor
            FROM scenario_version_sources svs
            JOIN source_documents sd ON sd.source_document_id = svs.source_document_id
            JOIN source_parts sp ON sp.source_document_id = sd.source_document_id
            WHERE svs.scenario_version_id = %s
            ORDER BY svs.ordinal, sp.ordinal
            """,
            (scenario_version_id,),
        ).fetchall()
        quality_report = _json_object(version.get("quality_report"))
        resolutions = self._issue_resolutions(scenario_version_id)
        issues = []
        for index, raw_issue in enumerate(quality_report.get("issues") or [], start=1):
            issue = _json_object(raw_issue)
            code = str(issue.get("code") or f"legacy-{index}")
            resolution = resolutions.get(code, {})
            issues.append({
                "issue_id": f"quality:{code}",
                "code": code,
                "category": str(issue.get("category") or "completeness"),
                "severity": str(issue.get("severity") or "warning"),
                "message": str(issue.get("message") or "待复核问题"),
                "blocking": bool(issue.get("blocking")),
                "target_type": str(issue.get("target_type") or ""),
                "target_key": str(issue.get("target_key") or ""),
                "resolution_hint": str(issue.get("resolution_hint") or "查看原文并补充结构化内容"),
                "status": resolution.get("status") or "open",
                "resolution_rationale": resolution.get("rationale") or "",
            })

        return {
            "scenario_id": scenario_id,
            "scenario_version_id": scenario_version_id,
            "scenario_title": version.get("title") or "",
            "version_number": int(version.get("version_number") or 0),
            "status": version.get("status") or "draft",
            "is_review_draft": bool(review_draft),
            "quality_report": quality_report,
            "issues": issues,
            "source_parts": [_source_part(row) for row in parts],
            "knowledge_graph": _json_object(version.get("knowledge_graph")),
            "prep_package": _json_object(version.get("prep_package")),
        }

    def create_review_draft(
        self,
        scenario_id: str,
        parent_version_id: str,
        *,
        created_by: str,
    ) -> dict[str, Any]:
        parent = self.conn.execute(
            """
            SELECT scenario_version_id, scenario_id, knowledge_graph, quality_report,
                   prep_package, rag_index_version
            FROM scenario_versions
            WHERE scenario_id = %s AND scenario_version_id = %s
            """,
            (scenario_id, parent_version_id),
        ).fetchone()
        if not parent:
            raise ScenarioReviewError("scenario_version_not_found")

        next_row = self.conn.execute(
            "SELECT COALESCE(MAX(version_number), 0) + 1 AS version_number "
            "FROM scenario_versions WHERE scenario_id = %s",
            (scenario_id,),
        ).fetchone()
        scenario_version_id = str(uuid.uuid4())
        version_number = int(next_row["version_number"])
        draft_graph = _json_object(parent.get("knowledge_graph"))
        draft_quality = QualityReportGenerator().evaluate(
            draft_graph,
            require_complete_spoiler_boundaries=True,
        ).model_dump(mode="json")
        with self.conn.transaction() as tx:
            tx.execute(
                """
                INSERT INTO scenario_versions (
                    scenario_version_id, scenario_id, version_number, status,
                    knowledge_graph, quality_report, prep_package, rag_index_version, created_by
                ) VALUES (%s, %s, %s, 'draft_review', %s, %s, %s, %s, %s)
                """,
                (
                    scenario_version_id,
                    scenario_id,
                    version_number,
                    json.dumps(draft_graph, ensure_ascii=False),
                    json.dumps(draft_quality, ensure_ascii=False),
                    json.dumps(_json_object(parent.get("prep_package")), ensure_ascii=False),
                    parent.get("rag_index_version"),
                    created_by,
                ),
            )
            tx.execute(
                """
                INSERT INTO scenario_version_sources (scenario_version_id, source_document_id, ordinal)
                SELECT %s, source_document_id, ordinal
                FROM scenario_version_sources
                WHERE scenario_version_id = %s
                ORDER BY ordinal
                """,
                (scenario_version_id, parent_version_id),
            )
            tx.execute(
                """
                INSERT INTO scenario_review_drafts (scenario_version_id, parent_version_id, created_by)
                VALUES (%s, %s, %s)
                """,
                (scenario_version_id, parent_version_id, created_by),
            )
        return {
            "scenario_id": scenario_id,
            "scenario_version_id": scenario_version_id,
            "parent_version_id": parent_version_id,
            "version_number": version_number,
            "status": "draft_review",
        }

    def add_patch(
        self,
        scenario_version_id: str,
        *,
        target_type: str,
        target_key: str,
        payload: dict[str, Any],
        provenance: str,
        citation: dict[str, Any],
        rationale: str,
        created_by: str,
    ) -> dict[str, Any]:
        self._require_review_draft(scenario_version_id)
        target_type = target_type.strip()
        target_key = target_key.strip()
        if target_type not in _PATCH_TARGET_TYPES or not target_key or not isinstance(payload, dict):
            raise ScenarioReviewError("review_patch_invalid")
        citation = _json_object(citation)
        rationale = rationale.strip()
        if provenance == "source":
            source_part_id = str(citation.get("source_part_id") or "")
            if not source_part_id:
                raise ScenarioReviewError("review_patch_evidence_required")
            source = self.conn.execute(
                """
                SELECT 1
                FROM scenario_version_sources svs
                JOIN source_parts sp ON sp.source_document_id = svs.source_document_id
                WHERE svs.scenario_version_id = %s AND sp.source_part_id = %s
                """,
                (scenario_version_id, source_part_id),
            ).fetchone()
            if not source:
                raise ScenarioReviewError("review_patch_citation_not_in_version")
        elif provenance == "curator":
            if not rationale:
                raise ScenarioReviewError("review_patch_evidence_required")
        else:
            raise ScenarioReviewError("review_patch_invalid_provenance")

        review_patch_id = str(uuid.uuid4())
        self.conn.execute(
            """
            INSERT INTO scenario_review_patches (
                review_patch_id, scenario_version_id, target_type, target_key,
                payload, provenance, citation, rationale, created_by
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                review_patch_id,
                scenario_version_id,
                target_type,
                target_key,
                json.dumps(payload, ensure_ascii=False),
                provenance,
                json.dumps(citation, ensure_ascii=False),
                rationale,
                created_by,
            ),
        )
        self.conn.commit()
        return {
            "review_patch_id": review_patch_id,
            "scenario_version_id": scenario_version_id,
            "target_type": target_type,
            "target_key": target_key,
            "payload": payload,
            "provenance": provenance,
            "citation": citation,
            "rationale": rationale,
            "status": "accepted",
        }

    def resolve_issue(
        self,
        scenario_version_id: str,
        *,
        issue_id: str,
        resolution: str,
        rationale: str,
        created_by: str,
    ) -> dict[str, Any]:
        self._require_review_draft(scenario_version_id)
        issue_code = issue_id.removeprefix("quality:").strip()
        rationale = rationale.strip()
        if resolution != "not_applicable" or not issue_code:
            raise ScenarioReviewError("review_issue_invalid_resolution")
        if not rationale:
            raise ScenarioReviewError("review_issue_rationale_required")
        issue = self._current_quality_issue(scenario_version_id, issue_code)
        if not issue:
            raise ScenarioReviewError("review_issue_not_found")
        if bool(issue.get("blocking")):
            raise ScenarioReviewError("review_issue_cannot_be_waived")
        self.conn.execute(
            """
            INSERT INTO scenario_review_issue_resolutions (
                scenario_version_id, issue_code, status, rationale, resolved_by
            ) VALUES (%s, %s, 'not_applicable', %s, %s)
            ON CONFLICT (scenario_version_id, issue_code)
            DO UPDATE SET status = EXCLUDED.status,
                          rationale = EXCLUDED.rationale,
                          resolved_by = EXCLUDED.resolved_by,
                          resolved_at = NOW()
            """,
            (scenario_version_id, issue_code, rationale, created_by),
        )
        self.conn.commit()
        return {
            "scenario_version_id": scenario_version_id,
            "issue_id": f"quality:{issue_code}",
            "status": "not_applicable",
            "resolution_rationale": rationale,
        }

    async def suggest_issue_drafts(
        self,
        scenario_id: str,
        scenario_version_id: str,
        *,
        issue_id: str,
    ) -> dict[str, Any]:
        workbench = self.get_workbench(scenario_id, scenario_version_id)
        self._require_review_draft(scenario_version_id)
        issue = next(
            (item for item in workbench["issues"] if item["issue_id"] == issue_id),
            None,
        )
        if not issue:
            raise ScenarioReviewError("review_issue_not_found")
        return await self._request_ai_drafts(workbench, mode="issue", issue=issue)

    async def reread_drafts(
        self,
        scenario_id: str,
        scenario_version_id: str,
    ) -> dict[str, Any]:
        workbench = self.get_workbench(scenario_id, scenario_version_id)
        self._require_review_draft(scenario_version_id)
        return await self._request_ai_drafts(workbench, mode="whole", issue=None)

    def rebuild_review_draft(
        self,
        scenario_version_id: str,
        *,
        requested_by: str,
    ) -> dict[str, Any]:
        self._require_review_draft(scenario_version_id)
        version = self.conn.execute(
            """
            SELECT sv.scenario_id, sv.knowledge_graph, s.title
            FROM scenario_versions sv
            JOIN scenarios s ON s.scenario_id = sv.scenario_id
            WHERE sv.scenario_version_id = %s
            """,
            (scenario_version_id,),
        ).fetchone()
        if not version:
            raise ScenarioReviewError("scenario_version_not_found")
        graph = _json_object(version.get("knowledge_graph"))
        patches = self._accepted_patches(scenario_version_id)
        for patch in patches:
            _apply_patch(graph, patch)
        quality_report = QualityReportGenerator().evaluate(
            graph,
            require_complete_spoiler_boundaries=True,
        ).model_dump(mode="json")
        prep_package = _build_prep_package(
            version.get("title") or "",
            graph,
            quality_report,
            self._source_part_rows(scenario_version_id),
        )
        with self.conn.transaction() as tx:
            tx.execute(
                """
                UPDATE scenario_versions
                SET knowledge_graph = %s, quality_report = %s, prep_package = %s
                WHERE scenario_version_id = %s
                """,
                (
                    json.dumps(graph, ensure_ascii=False),
                    json.dumps(quality_report, ensure_ascii=False),
                    json.dumps(prep_package, ensure_ascii=False),
                    scenario_version_id,
                ),
            )
        projection = ContentProjectionService(self.conn).rebuild(
            scenario_version_id,
            graph,
            requested_by=requested_by,
        )
        runtime_package = ModuleCompiler(self.conn).compile(
            scenario_version_id,
            requested_by=requested_by,
        )
        return {
            "scenario_version_id": scenario_version_id,
            "knowledge_graph": graph,
            "quality_report": quality_report,
            "prep_package": prep_package,
            "projection": projection,
            "runtime_package": runtime_package,
            "applied_patch_count": len(patches),
        }

    def _require_review_draft(self, scenario_version_id: str) -> None:
        row = self.conn.execute(
            "SELECT 1 FROM scenario_review_drafts WHERE scenario_version_id = %s",
            (scenario_version_id,),
        ).fetchone()
        if not row:
            raise ScenarioReviewError("scenario_review_draft_not_found")

    def _accepted_patches(self, scenario_version_id: str) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            """
            SELECT review_patch_id, target_type, target_key, operation, payload,
                   provenance, citation, rationale
            FROM scenario_review_patches
            WHERE scenario_version_id = %s AND status = 'accepted'
            ORDER BY created_at, review_patch_id
            """,
            (scenario_version_id,),
        ).fetchall()
        return [{
            **dict(row),
            "payload": _json_object(row.get("payload")),
            "citation": _json_object(row.get("citation")),
        } for row in rows]

    def _issue_resolutions(self, scenario_version_id: str) -> dict[str, dict[str, str]]:
        rows = self.conn.execute(
            """
            SELECT issue_code, status, rationale
            FROM scenario_review_issue_resolutions
            WHERE scenario_version_id = %s
            """,
            (scenario_version_id,),
        ).fetchall()
        return {
            str(row.get("issue_code") or ""): {
                "status": str(row.get("status") or ""),
                "rationale": str(row.get("rationale") or ""),
            }
            for row in rows
        }

    def _current_quality_issue(
        self, scenario_version_id: str, issue_code: str
    ) -> dict[str, Any] | None:
        row = self.conn.execute(
            "SELECT quality_report FROM scenario_versions WHERE scenario_version_id = %s",
            (scenario_version_id,),
        ).fetchone()
        if not row:
            return None
        for raw_issue in _json_object(row.get("quality_report")).get("issues") or []:
            issue = _json_object(raw_issue)
            if str(issue.get("code") or "") == issue_code:
                return issue
        return None

    async def _request_ai_drafts(
        self,
        workbench: dict[str, Any],
        *,
        mode: str,
        issue: dict[str, Any] | None,
    ) -> dict[str, Any]:
        if not self.gateway or not hasattr(self.gateway, "review_scenario"):
            raise ScenarioReviewError("review_provider_unavailable")
        source_parts = _review_source_excerpt(workbench.get("source_parts") or [])
        try:
            response = await self.gateway.review_scenario({
                "mode": mode,
                "issue": issue,
                "knowledge_graph": workbench.get("knowledge_graph") or {},
                "source_parts": source_parts,
            })
        except Exception as exc:
            raise ScenarioReviewError("review_provider_unavailable") from exc
        if not isinstance(response, dict):
            raise ScenarioReviewError("review_provider_unavailable")
        allowed_part_ids = {part["source_part_id"] for part in source_parts}
        target_type = str((issue or {}).get("target_type") or "")
        suggestions = []
        for raw_suggestion in response.get("suggestions") or []:
            suggestion = _json_object(raw_suggestion)
            if str(suggestion.get("provenance") or "") != "source":
                continue
            citation = _json_object(suggestion.get("citation"))
            if str(citation.get("source_part_id") or "") not in allowed_part_ids:
                continue
            suggestion_target_type = str(suggestion.get("target_type") or "")
            if suggestion_target_type not in _PATCH_TARGET_TYPES:
                continue
            if target_type and suggestion_target_type != target_type:
                continue
            if not str(suggestion.get("target_key") or ""):
                continue
            payload = _json_object(suggestion.get("payload"))
            if not payload:
                continue
            if (
                suggestion_target_type == "spoiler_boundary"
                and not _is_complete_spoiler_boundary({
                    **payload,
                    "citation": citation,
                })
            ):
                continue
            suggestions.append({
                "target_type": suggestion_target_type,
                "target_key": str(suggestion["target_key"]),
                "payload": payload,
                "provenance": "source",
                "citation": citation,
                "rationale": str(suggestion.get("rationale") or ""),
                "confidence": _confidence(suggestion.get("confidence")),
            })
        return {
            "mode": mode,
            "issue_id": (issue or {}).get("issue_id"),
            "summary": str(response.get("summary") or ""),
            "suggestions": suggestions,
        }

    def _source_part_rows(self, scenario_version_id: str) -> list[dict[str, Any]]:
        return [dict(row) for row in self.conn.execute(
            """
            SELECT sp.source_part_id, sp.ordinal, sp.part_kind, sp.page_number,
                   sp.text_content, sp.mime_type, sp.anchor, sd.source_filename
            FROM scenario_version_sources svs
            JOIN source_documents sd ON sd.source_document_id = svs.source_document_id
            JOIN source_parts sp ON sp.source_document_id = sd.source_document_id
            WHERE svs.scenario_version_id = %s
            ORDER BY svs.ordinal, sp.ordinal
            """,
            (scenario_version_id,),
        ).fetchall()]


def _source_part(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "source_part_id": row["source_part_id"],
        "source_document_id": row["source_document_id"],
        "source_title": row.get("source_title") or "",
        "source_filename": row.get("source_filename") or "",
        "source_mime_type": row.get("source_mime_type") or "",
        "ordinal": int(row.get("ordinal") or 0),
        "part_kind": row.get("part_kind") or "text",
        "page_number": row.get("page_number"),
        "text_content": row.get("text_content") or "",
        "mime_type": row.get("mime_type") or "",
        "storage_path": row.get("storage_path") or "",
        "anchor": _json_object(row.get("anchor")),
    }


def _review_source_excerpt(parts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    remaining = 24_000
    excerpts = []
    for part in parts:
        if remaining <= 0:
            break
        text = str(part.get("text_content") or "").strip()
        excerpt = text[: min(4_000, remaining)]
        remaining -= len(excerpt)
        excerpts.append({
            "source_part_id": str(part.get("source_part_id") or ""),
            "page_number": part.get("page_number"),
            "anchor": _json_object(part.get("anchor")),
            "text_content": excerpt,
        })
    return excerpts


def _confidence(value: Any) -> float:
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return 0.0


def _json_object(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    if isinstance(value, str):
        try:
            decoded = json.loads(value)
        except json.JSONDecodeError:
            return {}
        return dict(decoded) if isinstance(decoded, dict) else {}
    return {}


_PATCH_TARGET_TYPES = {
    "scene", "npc", "clue", "truth", "ending", "branch", "item",
    "rule", "map_mode", "character_mode", "spoiler_boundary",
}

_LIST_PATCH_TARGETS = {
    "scene": ("scenes", ("scene_id", "id", "name")),
    "npc": ("npcs", ("npc_id", "id", "name")),
    "clue": ("clues", ("clue_id", "id", "name")),
    "ending": ("endings", ("ending_id", "id", "name")),
    "branch": ("branches", ("branch_id", "id", "name")),
    "item": ("items", ("item_id", "id", "name")),
    "rule": ("rule_citations", ("rule_id", "id", "source_ref", "name")),
    "spoiler_boundary": ("spoiler_boundaries", ("id", "name")),
}


def _apply_patch(graph: dict[str, Any], patch: dict[str, Any]) -> None:
    target_type = str(patch.get("target_type") or "")
    payload = _json_object(patch.get("payload"))
    if patch.get("provenance") == "source":
        payload.setdefault("citation", _json_object(patch.get("citation")))
    else:
        payload.setdefault("review_provenance", {
            "kind": "curator_supplement",
            "rationale": str(patch.get("rationale") or ""),
            "review_patch_id": patch.get("review_patch_id") or "",
        })

    if target_type == "truth":
        graph["truth"] = payload
        return
    if target_type == "map_mode":
        graph["map_mode"] = payload
        return
    if target_type == "character_mode":
        graph["character_mode"] = payload
        return
    target = _LIST_PATCH_TARGETS.get(target_type)
    if not target:
        return
    graph_key, identifier_keys = target
    values = graph.setdefault(graph_key, [])
    if not isinstance(values, list):
        values = []
        graph[graph_key] = values
    target_key = str(patch.get("target_key") or "")
    for index, value in enumerate(values):
        if not isinstance(value, dict):
            continue
        if any(str(value.get(key) or "") == target_key for key in identifier_keys):
            values[index] = {**value, **payload}
            return
    values.append(payload)


def _build_prep_package(
    title: str,
    graph: dict[str, Any],
    quality_report: dict[str, Any],
    part_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    from .import_service import _build_prep_package as build_prep_package

    return build_prep_package(title, graph, quality_report, part_rows)
