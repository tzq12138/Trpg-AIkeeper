from __future__ import annotations

import hashlib
import json
import re
import uuid
from typing import Any


class ModuleCompilerError(ValueError):
    pass


class ModuleCompiler:
    def __init__(self, conn):
        self.conn = conn

    def compile(self, scenario_version_id: str, *, requested_by: str) -> dict[str, Any]:
        version = self._load_version(scenario_version_id)
        graph = _json_object(version.get("knowledge_graph"))
        prep_package = _json_object(version.get("prep_package"))
        items = self._load_content_items(scenario_version_id)
        source_text_parts = self._load_source_text_parts(scenario_version_id)
        items = _backfill_item_citations(items, source_text_parts)
        edges = self._load_content_edges(scenario_version_id)
        projection_diagnostics = self._load_projection_diagnostics(scenario_version_id)
        source_image_documents = self._load_source_image_documents(scenario_version_id)
        asset_bindings = self._load_asset_bindings(
            version["scenario_id"],
            scenario_version_id,
        )
        character_templates = self._load_character_templates(version["scenario_id"])
        runtime_package = _build_runtime_package(
            version,
            graph,
            prep_package,
            items,
            edges,
            asset_bindings,
            character_templates,
        )
        quality_exceptions = _quality_exceptions(
            graph,
            items,
            edges,
            asset_bindings,
            projection_diagnostics,
            source_image_documents,
            character_templates,
        )
        input_checksum = _checksum({
            "graph": graph,
            "prep_package": prep_package,
            "items": items,
            "source_text_parts": source_text_parts,
            "edges": edges,
            "projection_diagnostics": projection_diagnostics,
            "source_image_documents": source_image_documents,
            "asset_bindings": asset_bindings,
            "character_templates": character_templates,
        })
        gate_status = _gate_status(quality_exceptions, set())
        next_row = self.conn.execute(
            "SELECT COALESCE(MAX(package_version_number), 0) + 1 AS next_version "
            "FROM runtime_package_versions WHERE scenario_version_id = %s",
            (scenario_version_id,),
        ).fetchone()
        runtime_package_version_id = str(uuid.uuid4())
        package_version_number = int(next_row["next_version"])
        self.conn.execute(
            """
            INSERT INTO runtime_package_versions (
                runtime_package_version_id, scenario_version_id, package_version_number,
                gate_status, input_checksum, runtime_package, quality_exceptions,
                created_by
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                runtime_package_version_id,
                scenario_version_id,
                package_version_number,
                gate_status,
                input_checksum,
                json.dumps(runtime_package, ensure_ascii=False),
                json.dumps(quality_exceptions, ensure_ascii=False),
                requested_by,
            ),
        )
        self.conn.commit()
        return self.preview(runtime_package_version_id)

    def preview_latest(self, scenario_version_id: str) -> dict[str, Any]:
        row = self.conn.execute(
            """
            SELECT runtime_package_version_id
            FROM runtime_package_versions
            WHERE scenario_version_id = %s
            ORDER BY package_version_number DESC, created_at DESC
            LIMIT 1
            """,
            (scenario_version_id,),
        ).fetchone()
        if not row:
            raise ModuleCompilerError("runtime_package_not_found")
        return self.preview(row["runtime_package_version_id"])

    def preview(self, runtime_package_version_id: str) -> dict[str, Any]:
        row = self.conn.execute(
            "SELECT * FROM runtime_package_versions WHERE runtime_package_version_id = %s",
            (runtime_package_version_id,),
        ).fetchone()
        if not row:
            raise ModuleCompilerError("runtime_package_not_found")
        confirmed_keys = self._confirmed_exception_keys(runtime_package_version_id)
        exceptions = [
            {**issue, "confirmed": issue["exception_key"] in confirmed_keys}
            for issue in _json_list(row.get("quality_exceptions"))
            if isinstance(issue, dict)
        ]
        gate_status = _gate_status(exceptions, confirmed_keys)
        return {
            "runtime_package_version_id": row["runtime_package_version_id"],
            "scenario_version_id": row["scenario_version_id"],
            "package_version_number": row["package_version_number"],
            "gate_status": gate_status,
            "input_checksum": row["input_checksum"],
            "runtime_package": _json_object(row.get("runtime_package")),
            "quality_exceptions": exceptions,
            "created_by": row.get("created_by"),
            "created_at": str(row.get("created_at") or ""),
        }

    def confirm_quality_exception(
        self,
        runtime_package_version_id: str,
        exception_key: str,
        *,
        confirmed_by: str,
        note: str = "",
    ) -> dict[str, Any]:
        preview = self.preview(runtime_package_version_id)
        target = next(
            (
                issue
                for issue in preview["quality_exceptions"]
                if issue["exception_key"] == exception_key
            ),
            None,
        )
        if not target:
            raise ModuleCompilerError("quality_exception_not_found")
        if not target.get("waivable"):
            raise ModuleCompilerError("quality_exception_not_waivable")
        self.conn.execute(
            """
            INSERT INTO runtime_package_exception_confirmations (
                runtime_package_version_id, exception_key, confirmed_by, note
            ) VALUES (%s, %s, %s, %s)
            ON CONFLICT (runtime_package_version_id, exception_key)
            DO UPDATE SET confirmed_by = EXCLUDED.confirmed_by,
                          note = EXCLUDED.note,
                          confirmed_at = NOW()
            """,
            (runtime_package_version_id, exception_key, confirmed_by, note),
        )
        updated = self.preview(runtime_package_version_id)
        self.conn.execute(
            "UPDATE runtime_package_versions SET gate_status = %s "
            "WHERE runtime_package_version_id = %s",
            (updated["gate_status"], runtime_package_version_id),
        )
        self.conn.commit()
        return self.preview(runtime_package_version_id)

    def latest_ready_for_version(self, scenario_version_id: str) -> dict[str, Any]:
        preview = self.preview_latest(scenario_version_id)
        if preview["gate_status"] != "ready":
            raise ModuleCompilerError("runtime_package_not_ready")
        return preview

    def _load_version(self, scenario_version_id: str) -> dict[str, Any]:
        row = self.conn.execute(
            """
            SELECT sv.*, s.title AS scenario_title
            FROM scenario_versions sv
            JOIN scenarios s ON s.scenario_id = sv.scenario_id
            WHERE sv.scenario_version_id = %s
            """,
            (scenario_version_id,),
        ).fetchone()
        if not row:
            raise ModuleCompilerError("scenario_version_not_found")
        return dict(row)

    def _load_content_items(self, scenario_version_id: str) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            """
            SELECT content_item_id, item_type, logical_key, title, visibility,
                   payload, citation, ordinal
            FROM content_items
            WHERE scenario_version_id = %s
            ORDER BY item_type, ordinal, logical_key
            """,
            (scenario_version_id,),
        ).fetchall()
        return [
            {
                **dict(row),
                "payload": _json_object(row.get("payload")),
                "citation": _json_object(row.get("citation")),
            }
            for row in rows
        ]

    def _load_content_edges(self, scenario_version_id: str) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            """
            SELECT content_item_edge_id, from_content_item_id, to_content_item_id,
                   relation_type, conditions, citation, ordinal
            FROM content_item_edges
            WHERE scenario_version_id = %s
            ORDER BY relation_type, ordinal, content_item_edge_id
            """,
            (scenario_version_id,),
        ).fetchall()
        return [
            {
                **dict(row),
                "conditions": _json_list(row.get("conditions")),
                "citation": _json_object(row.get("citation")),
            }
            for row in rows
        ]

    def _load_source_text_parts(self, scenario_version_id: str) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            """
            SELECT sp.source_part_id, sp.page_number, sp.text_content, sp.anchor,
                   svs.ordinal AS source_ordinal, sp.ordinal AS part_ordinal
            FROM scenario_version_sources svs
            JOIN source_parts sp
              ON sp.source_document_id = svs.source_document_id
            WHERE svs.scenario_version_id = %s
              AND sp.part_kind = 'text'
              AND sp.text_content <> ''
            ORDER BY svs.ordinal, sp.ordinal
            """,
            (scenario_version_id,),
        ).fetchall()
        return [
            {
                **dict(row),
                "anchor": _json_object(row.get("anchor")),
            }
            for row in rows
        ]

    def _load_asset_bindings(
        self,
        scenario_id: str,
        scenario_version_id: str,
    ) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            """
            SELECT sa.asset_id, sa.source_document_id, sa.original_name,
                   sa.mime_type, sa.relative_path,
                   sab.binding_id, sab.target_type, sab.target_key, sab.status,
                   sab.confidence, sab.evidence
            FROM scenario_assets sa
            LEFT JOIN scenario_asset_bindings sab
              ON sab.asset_id = sa.asset_id AND sab.scenario_version_id = %s
            WHERE sa.scenario_id = %s AND sa.mime_type LIKE 'image/%%'
            ORDER BY sa.created_at, sa.asset_id
            """,
            (scenario_version_id, scenario_id),
        ).fetchall()
        return [
            {
                **dict(row),
                "evidence": _json_object(row.get("evidence")),
            }
            for row in rows
        ]

    def _load_projection_diagnostics(self, scenario_version_id: str) -> dict[str, Any]:
        row = self.conn.execute(
            """
            SELECT diagnostics
            FROM content_projection_runs
            WHERE scenario_version_id = %s AND projection_kind = 'canonical_content'
            ORDER BY started_at DESC, completed_at DESC
            LIMIT 1
            """,
            (scenario_version_id,),
        ).fetchone()
        return _json_object(row.get("diagnostics")) if row else {}

    def _load_character_templates(self, scenario_id: str) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            """
            SELECT template_id, name, occupation, background, age, gender,
                   attributes, skills, backstory
            FROM character_templates
            WHERE scenario_id = %s
            ORDER BY created_at, template_id
            """,
            (scenario_id,),
        ).fetchall()
        return [
            {
                **dict(row),
                "attributes": _json_object(row.get("attributes")),
                "skills": _json_object(row.get("skills")),
                "backstory": _json_object(row.get("backstory")),
            }
            for row in rows
        ]

    def _load_source_image_documents(self, scenario_version_id: str) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            """
            SELECT sd.source_document_id, sd.source_filename, sd.mime_type
            FROM scenario_version_sources svs
            JOIN source_documents sd
              ON sd.source_document_id = svs.source_document_id
            WHERE svs.scenario_version_id = %s
              AND sd.mime_type LIKE 'image/%%'
            ORDER BY svs.ordinal, sd.source_document_id
            """,
            (scenario_version_id,),
        ).fetchall()
        return [dict(row) for row in rows]

    def _confirmed_exception_keys(self, runtime_package_version_id: str) -> set[str]:
        rows = self.conn.execute(
            "SELECT exception_key FROM runtime_package_exception_confirmations "
            "WHERE runtime_package_version_id = %s",
            (runtime_package_version_id,),
        ).fetchall()
        return {row["exception_key"] for row in rows}


def _build_runtime_package(
    version: dict[str, Any],
    graph: dict[str, Any],
    prep_package: dict[str, Any],
    items: list[dict[str, Any]],
    edges: list[dict[str, Any]],
    asset_bindings: list[dict[str, Any]],
    character_templates: list[dict[str, Any]],
) -> dict[str, Any]:
    from ..engine.risk_contract import normalize_risk_contract

    citations = _collect_citations(graph, prep_package, items, edges)
    confirmed_assets = [
        _asset_payload(binding)
        for binding in asset_bindings
        if binding.get("status") == "confirmed"
    ]
    item_by_id = {
        str(item.get("content_item_id") or ""): item
        for item in items
    }
    progression_edges = []
    for edge in edges:
        payload = {
            "from_content_item_id": edge["from_content_item_id"],
            "to_content_item_id": edge["to_content_item_id"],
            "relation_type": edge["relation_type"],
            "conditions": edge["conditions"],
            "citation": edge["citation"],
        }
        from_item = item_by_id.get(str(edge.get("from_content_item_id") or ""), {})
        to_item = item_by_id.get(str(edge.get("to_content_item_id") or ""), {})
        if from_item.get("item_type") == "scene" and to_item.get("item_type") == "scene":
            payload["from_scene_id"] = str(from_item.get("logical_key") or "")
            payload["to_scene_id"] = str(to_item.get("logical_key") or "")
        progression_edges.append(payload)
    risk_contract = graph.get("risk_contract")
    return {
        "package_kind": "aikeeper_runtime_package",
        "schema_version": "runtime_package.v1",
        "scenario_version_id": version["scenario_version_id"],
        "scenario_title": version.get("scenario_title") or "",
        "world_book": {
            "synopsis": graph.get("synopsis") or prep_package.get("summary") or "",
            "truth": graph.get("truth") if isinstance(graph.get("truth"), dict) else {},
        },
        "semantic_scenes": _collection(graph, "scenes", items, "scene"),
        "npc_states": _collection(graph, "npcs", items, "npc"),
        "character_and_items": {
            "characters": _list(graph.get("characters")),
            "templates": character_templates,
            "items": _list(graph.get("items")),
            "confirmed_assets": confirmed_assets,
        },
        "clue_dependencies": _collection(graph, "clues", items, "clue"),
        "rule_triggers": _list(graph.get("rule_triggers")) or _list(graph.get("rule_citations")),
        "runtime_policy": _json_object(graph.get("runtime_policy")),
        "character_control": _character_control_package(graph),
        **(
            {"risk_contract": normalize_risk_contract(risk_contract)}
            if isinstance(risk_contract, dict) and risk_contract
            else {}
        ),
        "semantic_map": {
            "assets": [
                asset for asset in confirmed_assets if asset["target_type"] == "map"
            ],
            "locations": _list(graph.get("locations")),
        },
        "ending_conditions": _runtime_ending_conditions(
            _collection(graph, "endings", items, "ending")
        ),
        "style_pack": _json_object(graph.get("style_pack")),
        "story_evidence_nodes": [
            {
                "content_item_id": item["content_item_id"],
                "item_type": item["item_type"],
                "logical_key": item["logical_key"],
                "title": item["title"],
                "citation": item["citation"],
            }
            for item in items
        ],
        "semantic_progression_rules": {
            "edges": progression_edges,
            "solo_adventure": _json_object(graph.get("solo_adventure")),
        },
        "citations": citations,
    }


def _quality_exceptions(
    graph: dict[str, Any],
    items: list[dict[str, Any]],
    edges: list[dict[str, Any]],
    asset_bindings: list[dict[str, Any]],
    projection_diagnostics: dict[str, Any],
    source_image_documents: list[dict[str, Any]],
    character_templates: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    issues.extend(_runtime_diagnostic_issues(graph))
    issues.extend(_source_image_issues(source_image_documents, asset_bindings))
    if not character_templates:
        issues.append(_issue(
            "missing_character_template",
            "Ready-to-play scenarios require at least one preset character.",
            target_type="character_template",
            target_key="scenario",
            waivable=False,
        ))
    for binding in asset_bindings:
        if binding.get("status") != "confirmed":
            issues.append(_issue(
                "asset_binding_not_confirmed",
                "Asset binding must be confirmed before runtime use.",
                target_type=str(binding.get("target_type") or "asset"),
                target_key=str(binding.get("target_key") or binding.get("asset_id") or ""),
                waivable=False,
                details={"asset_id": binding.get("asset_id"), "status": binding.get("status") or "unbound"},
            ))
    for item in items:
        if item["item_type"] in {"scene", "npc", "clue", "ending", "branch_node", "truth"}:
            if not _has_citation(item.get("citation")):
                issues.append(_issue(
                    "missing_citation",
                    "Critical runtime content must cite a source part.",
                    target_type=item["item_type"],
                    target_key=item["logical_key"],
                    waivable=True,
                ))
    issues.extend(_branch_issues_from_graph(graph, items))
    issues.extend(_projection_diagnostic_issues(projection_diagnostics))
    issues.extend(_runtime_citation_issues(graph))
    issues.extend(_ending_condition_issues(graph))
    issues.extend(_character_control_issues(graph, items))
    for edge in edges:
        if not edge.get("from_content_item_id") or not edge.get("to_content_item_id"):
            issues.append(_issue(
                "invalid_branch_reference",
                "Progression edge references missing content.",
                target_type="edge",
                target_key=edge.get("content_item_edge_id") or "",
                waivable=False,
            ))
    solo = _json_object(graph.get("solo_adventure"))
    integrity = _json_object(solo.get("integrity"))
    if integrity and integrity.get("is_valid") is False:
        issues.append(_issue(
            "invalid_solo_integrity",
            "Solo adventure has invalid branches or duplicate nodes.",
            target_type="solo_adventure",
            target_key=str(solo.get("root_node_id") or ""),
            waivable=False,
            details={
                "duplicate_node_ids": integrity.get("duplicate_node_ids") or [],
                "missing_target_node_ids": integrity.get("missing_target_node_ids") or [],
            },
        ))
    deduped = {}
    for issue in issues:
        deduped[issue["exception_key"]] = issue
    return sorted(deduped.values(), key=lambda issue: issue["exception_key"])


def _character_control_package(graph: dict[str, Any]) -> dict[str, Any]:
    runtime_policy = _json_object(graph.get("runtime_policy"))
    raw = _json_object(graph.get("character_control")) or _json_object(
        runtime_policy.get("character_control")
    )
    if not raw:
        return {}
    safe_scene_ids = raw.get("safe_replacement_scene_ids")
    if not isinstance(safe_scene_ids, list):
        safe_scene_ids = raw.get("safeReplacementSceneIds")
    normalized_safe_scenes = []
    for value in safe_scene_ids if isinstance(safe_scene_ids, list) else []:
        scene_id = str(value or "").strip()
        if scene_id and scene_id not in normalized_safe_scenes:
            normalized_safe_scenes.append(scene_id)

    recovery_nodes = raw.get("recovery_nodes")
    if not isinstance(recovery_nodes, list):
        recovery_nodes = raw.get("recoveryNodes")
    normalized_recovery_nodes = []
    for value in recovery_nodes if isinstance(recovery_nodes, list) else []:
        if not isinstance(value, dict):
            continue
        node_id = str(value.get("node_id") or value.get("nodeId") or "").strip()
        scene_id = str(value.get("scene_id") or value.get("sceneId") or "").strip()
        if not node_id:
            continue
        normalized_recovery_nodes.append({
            "node_id": node_id,
            "scene_id": scene_id,
            "citation": _json_object(value.get("citation")),
        })
    return {
        "safe_replacement_scene_ids": normalized_safe_scenes,
        "recovery_nodes": normalized_recovery_nodes,
    }


def _character_control_issues(
    graph: dict[str, Any],
    items: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    control = _character_control_package(graph)
    if not control:
        return []
    scene_ids = {
        str(scene.get("scene_id") or scene.get("id") or "").strip()
        for scene in _json_list(graph.get("scenes"))
        if isinstance(scene, dict)
    }
    scene_ids.update(
        str(item.get("logical_key") or "").strip()
        for item in items
        if item.get("item_type") == "scene"
    )
    issues = []
    for scene_id in control["safe_replacement_scene_ids"]:
        if scene_id not in scene_ids:
            issues.append(_issue(
                "invalid_character_control_safe_scene",
                "Replacement investigators require a compiled scene target.",
                target_type="character_control",
                target_key=scene_id,
                waivable=False,
            ))
    for node in control["recovery_nodes"]:
        node_id = node["node_id"]
        if not _has_citation(node.get("citation")):
            issues.append(_issue(
                "invalid_character_control_recovery_citation",
                "Insanity recovery nodes require a traceable citation.",
                target_type="character_control",
                target_key=node_id,
                waivable=False,
            ))
        scene_id = node.get("scene_id") or ""
        if not scene_id or scene_id not in scene_ids:
            issues.append(_issue(
                "invalid_character_control_recovery_scene",
                "Insanity recovery nodes require a compiled scene target.",
                target_type="character_control",
                target_key=node_id,
                waivable=False,
            ))
    return issues


def _runtime_diagnostic_issues(graph: dict[str, Any]) -> list[dict[str, Any]]:
    diagnostics = _json_list(graph.get("runtime_diagnostics"))
    if not diagnostics:
        diagnostics = _json_list(graph.get("compile_diagnostics"))
    issues = []
    for index, diagnostic in enumerate(diagnostics):
        if not isinstance(diagnostic, dict):
            continue
        code = str(diagnostic.get("code") or "runtime_compile_diagnostic")
        if code not in {"asset_binding_generation_failed"}:
            continue
        issues.append(_issue(
            code,
            str(diagnostic.get("message") or "Runtime package prerequisite failed."),
            target_type=str(diagnostic.get("target_type") or "asset_binding"),
            target_key=str(diagnostic.get("target_key") or f"diagnostic-{index + 1}"),
            waivable=False,
            details=diagnostic,
        ))
    return issues


def _source_image_issues(
    source_image_documents: list[dict[str, Any]],
    asset_bindings: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    asset_source_ids = {
        str(binding.get("source_document_id") or "")
        for binding in asset_bindings
        if binding.get("source_document_id")
    }
    issues = []
    for source in source_image_documents:
        source_document_id = str(source.get("source_document_id") or "")
        if source_document_id and source_document_id not in asset_source_ids:
            issues.append(_issue(
                "source_image_asset_missing",
                "Imported source image was not materialized as a scenario asset.",
                target_type="source_image",
                target_key=source_document_id,
                waivable=False,
                details={
                    "source_document_id": source_document_id,
                    "source_filename": source.get("source_filename") or "",
                },
            ))
    return issues


def _branch_issues_from_graph(
    graph: dict[str, Any],
    items: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    scene_keys = {
        item["logical_key"]
        for item in items
        if item.get("item_type") == "scene"
    }
    branches = graph.get("branches") or []
    if not isinstance(branches, list):
        return []
    issues = []
    for index, branch in enumerate(branches):
        if not isinstance(branch, dict):
            continue
        branch_key = str(
            branch.get("branch_id")
            or branch.get("id")
            or branch.get("name")
            or f"branch-{index + 1}"
        ).strip()
        from_key = str(branch.get("from_scene_id") or branch.get("from") or "").strip()
        to_key = str(branch.get("to_scene_id") or branch.get("to") or "").strip()
        if (from_key and from_key not in scene_keys) or (to_key and to_key not in scene_keys):
            issues.append(_issue(
                "invalid_branch_reference",
                "Branch references a missing scene target.",
                target_type="branch",
                target_key=branch_key,
                waivable=False,
                details={"from_scene_id": from_key, "to_scene_id": to_key},
            ))
    return issues


def _projection_diagnostic_issues(diagnostics: dict[str, Any]) -> list[dict[str, Any]]:
    warnings = diagnostics.get("warnings") or []
    if not isinstance(warnings, list):
        return []
    issues = []
    for warning in warnings:
        text = str(warning)
        if "missing_scene_target" not in text and "missing_target" not in text:
            continue
        parts = text.split(":")
        target_key = parts[1] if len(parts) > 1 and parts[1] else text
        issues.append(_issue(
            "invalid_branch_reference",
            "Projection skipped an invalid branch reference.",
            target_type="branch",
            target_key=target_key,
            waivable=False,
            details={"projection_warning": text},
        ))
    return issues


def _runtime_citation_issues(graph: dict[str, Any]) -> list[dict[str, Any]]:
    issues = []
    rule_triggers = _list(graph.get("rule_triggers"))
    if not rule_triggers:
        rule_triggers = _list(graph.get("rule_citations"))
    for index, trigger in enumerate(rule_triggers):
        if not _has_citation(trigger.get("citation")):
            target_key = str(
                trigger.get("trigger")
                or trigger.get("rule")
                or trigger.get("source_ref")
                or trigger.get("id")
                or index
            )
            issues.append(_issue(
                "missing_runtime_citation",
                "Rule trigger must cite its source.",
                target_type="rule_trigger",
                target_key=target_key,
                waivable=True,
            ))
    style_pack = _json_object(graph.get("style_pack"))
    if _has_semantic_style(style_pack) and not _has_citation(style_pack.get("citation")):
        issues.append(_issue(
            "missing_runtime_citation",
            "Style pack must cite its source.",
            target_type="style_pack",
            target_key="style_pack",
            waivable=True,
        ))
    for index, branch in enumerate(_list(graph.get("branches"))):
        if not _has_citation(branch.get("citation")):
            target_key = str(
                branch.get("branch_id")
                or branch.get("id")
                or branch.get("name")
                or index
            )
            issues.append(_issue(
                "missing_runtime_citation",
                "Semantic progression rule must cite its source.",
                target_type="semantic_progression_rule",
                target_key=target_key,
                waivable=True,
            ))
    return issues


def _has_semantic_style(style_pack: dict[str, Any]) -> bool:
    return any(
        key in style_pack and style_pack.get(key) not in (None, "", [], {})
        for key in ("tone", "style", "voice", "pacing", "language")
    )


def _issue(
    code: str,
    message: str,
    *,
    target_type: str,
    target_key: str,
    waivable: bool,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    exception_key = hashlib.sha256(
        f"{code}:{target_type}:{target_key}".encode("utf-8")
    ).hexdigest()[:24]
    return {
        "exception_key": exception_key,
        "code": code,
        "message": message,
        "target_type": target_type,
        "target_key": target_key,
        "blocking": True,
        "waivable": waivable,
        "details": details or {},
    }


def _gate_status(
    quality_exceptions: list[dict[str, Any]],
    confirmed_keys: set[str],
) -> str:
    for issue in quality_exceptions:
        if not issue.get("blocking"):
            continue
        if issue.get("waivable") and issue.get("exception_key") in confirmed_keys:
            continue
        return "blocked"
    return "ready"


def _collection(
    graph: dict[str, Any],
    key: str,
    items: list[dict[str, Any]],
    item_type: str,
) -> list[dict[str, Any]]:
    graph_items = _list(graph.get(key))
    if graph_items:
        item_index = {
            str(item.get("logical_key") or item.get("title") or ""): item
            for item in items
            if item.get("item_type") == item_type
        }
        title_index = {
            str(item.get("title") or ""): item
            for item in items
            if item.get("item_type") == item_type
        }
        enriched = []
        for graph_item in graph_items:
            result = dict(graph_item)
            if not _has_citation(result.get("citation")):
                keys = (
                    result.get(f"{item_type}_id"),
                    result.get("id"),
                    result.get("name"),
                    result.get("title"),
                )
                matched = next(
                    (
                        item_index.get(str(value)) or title_index.get(str(value))
                        for value in keys
                        if value not in (None, "")
                        and (item_index.get(str(value)) or title_index.get(str(value)))
                    ),
                    None,
                )
                if matched and _has_citation(matched.get("citation")):
                    result["citation"] = matched["citation"]
            enriched.append(result)
        return enriched
    return [
        {
            "id": item["logical_key"],
            "title": item["title"],
            "payload": item["payload"],
            "citation": item["citation"],
        }
        for item in items
        if item["item_type"] == item_type
    ]


def _runtime_ending_conditions(endings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [ending for ending in endings if _valid_ending_conditions(ending)]


def _ending_condition_issues(graph: dict[str, Any]) -> list[dict[str, Any]]:
    solo = _json_object(graph.get("solo_adventure"))
    if _json_object(solo.get("integrity")).get("is_valid") is True:
        return []
    issues = []
    for ordinal, ending in enumerate(_list(graph.get("endings"))):
        if _valid_ending_conditions(ending):
            continue
        target_key = str(
            ending.get("ending_id") or ending.get("id") or ending.get("name") or ordinal
        )
        issues.append(_issue(
            "invalid_ending_conditions",
            "Runtime endings require cited declarative completion conditions.",
            target_type="ending",
            target_key=target_key,
            waivable=False,
        ))
    return issues


def _valid_ending_conditions(ending: dict[str, Any]) -> bool:
    if not _has_citation(ending.get("citation")):
        return False
    ending_id = str(ending.get("ending_id") or ending.get("id") or "").strip()
    conditions = ending.get("completion_conditions")
    allowed_keys = {"all_clues", "any_clues", "entered_scenes", "event_types", "room_status"}
    if not ending_id or not isinstance(conditions, dict) or not conditions:
        return False
    if set(conditions) - allowed_keys:
        return False
    for key, expected in conditions.items():
        if key == "room_status":
            if not isinstance(expected, str) or not expected.strip():
                return False
        elif not isinstance(expected, list) or not expected or not all(
            isinstance(item, str) and item.strip() for item in expected
        ):
            return False
    return True


def _collect_citations(
    graph: dict[str, Any],
    prep_package: dict[str, Any],
    items: list[dict[str, Any]],
    edges: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    citations = []
    for citation in _list(prep_package.get("citations")):
        if isinstance(citation, dict):
            citations.append(citation)
    for item in items:
        if _has_citation(item.get("citation")):
            citations.append(item["citation"])
    for edge in edges:
        if _has_citation(edge.get("citation")):
            citations.append(edge["citation"])
    _walk_citations(graph, citations)
    deduped = {}
    for citation in citations:
        key = json.dumps(citation, ensure_ascii=False, sort_keys=True, default=str)
        deduped[key] = citation
    return list(deduped.values())


def _backfill_item_citations(
    items: list[dict[str, Any]],
    source_parts: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if not source_parts:
        return items
    normalized_parts = [
        (part, _normalize_evidence_text(str(part.get("text_content") or "")))
        for part in source_parts
    ]
    result = []
    for item in items:
        if _has_citation(item.get("citation")):
            result.append(item)
            continue
        title = str(item.get("title") or "")
        payload = _json_object(item.get("payload"))
        candidates = [
            title,
            str(payload.get("name") or ""),
            str(payload.get("description") or ""),
            str(payload.get("summary") or ""),
            str(payload.get("text") or ""),
        ]
        best_part = None
        best_score = 0
        for part, normalized_text in normalized_parts:
            score = _evidence_match_score(candidates, normalized_text)
            if score > best_score:
                best_score = score
                best_part = part
        if best_part is None or best_score < 20:
            result.append(item)
            continue
        anchor = _json_object(best_part.get("anchor"))
        citation = {
            "source_part_id": best_part["source_part_id"],
            "source_ref": anchor.get("source_ref") or "",
            "page_number": best_part.get("page_number"),
            "evidence_method": "deterministic_text_match",
            "evidence_score": best_score,
        }
        result.append({**item, "citation": citation})
    return result


def _evidence_match_score(candidates: list[str], normalized_text: str) -> int:
    score = 0
    matched_ngrams: set[str] = set()
    for index, candidate in enumerate(candidates):
        normalized = _normalize_evidence_text(candidate)
        if len(normalized) < 2:
            continue
        if normalized in normalized_text:
            score = max(score, 100 - index * 5)
        for ngram in _evidence_ngrams(normalized):
            if ngram in normalized_text:
                matched_ngrams.add(ngram)
    return max(score, min(60, len(matched_ngrams) * 10))


def _normalize_evidence_text(value: str) -> str:
    return re.sub(r"[^0-9a-zA-Z\u3400-\u9fff]+", "", value).lower()


def _evidence_ngrams(value: str) -> set[str]:
    if re.search(r"[\u3400-\u9fff]", value):
        return {
            value[index:index + 2]
            for index in range(len(value) - 1)
            if re.fullmatch(r"[\u3400-\u9fff]{2}", value[index:index + 2])
        }
    if len(value) < 4:
        return {value} if len(value) >= 2 else set()
    return {value[index:index + 4] for index in range(0, len(value) - 3, 2)}


def _walk_citations(value: Any, citations: list[dict[str, Any]]) -> None:
    if isinstance(value, dict):
        citation = value.get("citation")
        if isinstance(citation, dict) and _has_citation(citation):
            citations.append(citation)
        for item in value.values():
            _walk_citations(item, citations)
    elif isinstance(value, list):
        for item in value:
            _walk_citations(item, citations)


def _asset_payload(binding: dict[str, Any]) -> dict[str, Any]:
    return {
        "asset_id": binding["asset_id"],
        "target_type": binding.get("target_type") or "",
        "target_key": binding.get("target_key") or "",
        "original_name": binding.get("original_name") or "",
        "mime_type": binding.get("mime_type") or "",
        "relative_path": binding.get("relative_path") or "",
        "confidence": float(binding.get("confidence") or 0),
        "evidence": _json_object(binding.get("evidence")),
    }


def _has_citation(value: Any) -> bool:
    citation = _json_object(value)
    return bool(citation.get("source_part_id") or citation.get("source_ref"))


def _json_object(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def _json_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return list(value)
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return []
        return parsed if isinstance(parsed, list) else []
    return []


def _list(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    if isinstance(value, dict):
        return [dict(item, id=key) for key, item in value.items() if isinstance(item, dict)]
    return []


def _checksum(value: Any) -> str:
    serialized = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


__all__ = ["ModuleCompiler", "ModuleCompilerError"]
