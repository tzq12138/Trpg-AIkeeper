from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import mimetypes
import re
import sys
import uuid
from pathlib import Path
from typing import Any

import psycopg2
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.server.db_adapter import PgDatabase
from src.server.engine.engine import Engine
from src.server.engine.resolution_pipeline import ResolutionPipeline
from src.server.engine.state_service import StateService
from src.server.main import app
from src.server.models import MechanicCompileResult
from src.server.router_auth import _hash_password
from src.server.scenario.content_package import build_content_package
from src.server.scenario.golden_suite import GoldenModuleSpec, iter_golden_module_specs


GOLDEN_MAX_FILE_BYTES = 100 * 1024 * 1024
GOLDEN_MAX_TOTAL_BYTES = 200 * 1024 * 1024


class GoldenSuiteError(RuntimeError):
    pass


class DeterministicGoldenGateway:
    async def structure_content_package(self, package):
        first_part = next((part for part in package.parts if part.source_ref), None)
        source_ref = first_part.source_ref if first_part else "inline"
        source_texts = [
            {
                "source_ref": part.source_ref,
                "text": part.text or f"已识别素材：{package.source_filename}",
            }
            for part in package.parts
            if part.kind == "image" and part.source_ref
        ]
        citation = {"source_ref": source_ref}
        return {
            "title": package.source_filename,
            "synopsis": "黄金样本隔离导入的可验证测试剧本。",
            "scenes": [{
                "scene_id": "golden-opening",
                "name": "测试开场",
                "description": "调查员抵达可检索的开场场景。",
                "order": 1,
                "citation": citation,
            }],
            "npcs": [{
                "npc_id": "golden-guide",
                "name": "线索见证人",
                "public_description": "掌握开场线索的见证人。",
                "description": "可引导调查员核验来源内容。",
                "personality": "谨慎",
                "motivation": "协助完成调查",
                "is_hidden": False,
                "citation": citation,
            }],
            "clues": [{
                "clue_id": "golden-source-clue",
                "name": "来源锚点",
                "description": "从导入来源中提取的可核验线索。",
                "location": "测试开场",
                "citation": citation,
            }],
            "truth": {
                "summary": "样本来源已被导入、编译并在隔离房间中验证。",
                "citation": citation,
            },
            "endings": [{
                "ending_id": "golden-complete",
                "name": "完成来源核验",
                "description": "调查员完成必要调查并结束本次黄金样本验收。",
                "type": "victory",
                "completion_conditions": {"all_clues": ["golden-source-clue"]},
                "citation": citation,
            }],
            "spoiler_boundaries": [{"id": "truth", "level": "keeper"}],
            "key_skills": ["侦查"],
            "rule_citations": [{"source_ref": "coc7-golden-suite#checks"}],
            "source_part_texts": source_texts,
        }

    async def analyze_director_action(
        self,
        context: dict[str, Any],
        room_id: str | None = None,
    ) -> dict[str, Any]:
        del room_id
        return {
            "context_version": context.get("context_version", 0),
            "actor_display_name": context.get("actor_display_name", ""),
            "declared_intent": context.get("declared_intent", ""),
            "interpreted_intent": "inspect the visible golden-sample evidence",
            "intent_type": "skill_check",
            "preconditions": [],
            "permissions": [],
            "mechanic_plan": {
                "mechanic": "skill_check",
                "skillName": "侦查",
                "difficulty": "regular",
            },
            "state_patch": [],
            "event_plan": [],
            "semantic_progression": {
                "targetNodeId": None,
                "fromNodeId": None,
                "citation": {"page_number": 1},
                "rationale": "golden-suite deterministic action",
            },
            "npc_reactions": [],
            "time_impact": {},
            "visibility": "public",
            "basis_refs": [{"source": "golden_suite", "citation": {"page_number": 1}}],
            "citations": [{"page_number": 1}],
            "confidence": 1.0,
            "requires_player_clarification": False,
            "clarification_options": [],
            "requires_host_exception": False,
            "exception_reason": None,
            "narration_mode": "summarize",
            "analysis_source": "fallback_provider",
        }


class DeterministicGoldenRag:
    def __init__(self, conn):
        self.conn = conn
        self.embedding = type(
            "GoldenEmbeddingMetadata",
            (),
            {"model_name": "golden-suite-fixture", "dimension": 1536},
        )()

    def index_scenario_version(self, _scenario_id, _version_id, parts, **_kwargs):
        return len(parts)

    def index_npc_graph(self, _scenario_id, graph, **_kwargs):
        return len(graph.get("npcs") or [])

    def index_content_projection(self, _scenario_id, _version_id, items, **_kwargs):
        return len(items)

    def index_rules(
        self,
        doc_id: str,
        title: str,
        category: str,
        content: str,
        *,
        rule_set_version_id: str | None = None,
        source_document_id: str | None = None,
        source_part_id: str | None = None,
        visibility: str = "host_only",
        license_type: str = "authorized",
        source_ref: str = "",
        citation_base: dict[str, Any] | None = None,
    ) -> int:
        chunks = _chunk_rule_content(content)
        with self.conn.transaction() as tx:
            tx.execute(
                "DELETE FROM document_chunks WHERE source_type = %s AND source_id = %s",
                ("rule", doc_id),
            )
            tx.execute(
                """
                INSERT INTO rule_documents (
                    doc_id, rule_set_version_id, source_document_id, title, category,
                    content, visibility, license_type, source_ref
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (doc_id) DO UPDATE SET
                    rule_set_version_id = EXCLUDED.rule_set_version_id,
                    source_document_id = EXCLUDED.source_document_id,
                    title = EXCLUDED.title,
                    category = EXCLUDED.category,
                    content = EXCLUDED.content,
                    visibility = EXCLUDED.visibility,
                    license_type = EXCLUDED.license_type,
                    source_ref = EXCLUDED.source_ref
                """,
                (
                    doc_id,
                    rule_set_version_id,
                    source_document_id,
                    title,
                    category,
                    content,
                    visibility,
                    license_type,
                    source_ref,
                ),
            )
            for index, (chunk, start_offset, end_offset) in enumerate(chunks):
                citation = dict(citation_base or {})
                citation.update({
                    "source_ref": source_ref,
                    "start_offset": start_offset,
                    "end_offset": end_offset,
                })
                tx.execute(
                    """
                    INSERT INTO document_chunks (
                        chunk_id, source_type, source_id, room_id, content, metadata,
                        source_part_id, rule_set_version_id, visibility, citation,
                        embedding_model, embedding_dimensions, embedding
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        str(uuid.uuid4()),
                        "rule",
                        doc_id,
                        None,
                        chunk,
                        json.dumps({"title": title, "category": category, "index": index}),
                        source_part_id,
                        rule_set_version_id,
                        visibility,
                        json.dumps(citation),
                        self.embedding.model_name,
                        self.embedding.dimension,
                        None,
                    ),
                )
        return len(chunks)


class _NoopDispatcher:
    async def emit(self, *_args, **_kwargs):
        return None


class _GoldenSkillCheckCompiler:
    async def compile(self, *_args, **_kwargs):
        return MechanicCompileResult(
            triggeredMechanic="skill_check",
            skillName="侦查",
            difficulty="regular",
        )


class GoldenModuleSuiteRunner:
    def __init__(
        self,
        client: TestClient,
        conn,
        *,
        storage_root: Path,
        asset_root: Path,
    ):
        self.client = client
        self.conn = conn
        self.storage_root = storage_root
        self.asset_root = asset_root
        self.client.app.state.db = conn
        self.client.app.state.engine = Engine(conn)
        self.client.app.state.gateway = DeterministicGoldenGateway()
        self.client.app.state.rag = DeterministicGoldenRag(conn)
        self.client.app.state.scenario_storage_root = storage_root
        self.client.app.state.scenario_asset_root = asset_root
        self.client.app.state.scenario_import_limits = {
            "max_file_bytes": GOLDEN_MAX_FILE_BYTES,
            "max_total_bytes": GOLDEN_MAX_TOTAL_BYTES,
        }

    def run_spec(self, spec: GoldenModuleSpec) -> dict[str, Any]:
        admin_token, host_token = self._ensure_accounts_and_login()
        imported = self._import_spec(spec, admin_token)
        scenario_id = imported["scenario_id"]
        scenario_version_id = imported["scenario_version_id"]
        self._add_preset_template(scenario_id)
        runtime = self._prepare_runtime_package(
            scenario_id, scenario_version_id, admin_token
        )
        if runtime["gate_status"] != "ready":
            raise GoldenSuiteError(
                f"{spec.slug} runtime package not ready: {runtime['quality_exceptions']}"
            )
        self._publish(scenario_id, scenario_version_id, host_token)
        room = self._create_room(scenario_id, host_token)
        player = self._join_and_start(room, self._ensure_player_login(spec.slug))
        action_id, action_status = self._run_player_action(player["player_token"])
        ending = self._end_room(room, scenario_version_id, spec.source_mode)
        room_status = self.conn.execute(
            "SELECT status FROM rooms WHERE room_id = %s", (room["room_id"],)
        ).fetchone()["status"]
        source_rows = self.conn.execute(
            "SELECT source_filename, source_sha256, mime_type, status "
            "FROM source_documents WHERE scenario_id = %s ORDER BY source_filename",
            (scenario_id,),
        ).fetchall()
        return {
            "slug": spec.slug,
            "title": spec.title,
            "source_mode": spec.source_mode,
            "scenario_id": scenario_id,
            "scenario_version_id": scenario_version_id,
            "room_id": room["room_id"],
            "import_status": imported["status"],
            "runtime_gate_status": runtime["gate_status"],
            "action_id": action_id,
            "action_status": action_status,
            "room_status": room_status,
            "ending": ending,
            "sources": [dict(row) for row in source_rows],
        }

    def run_all(self, root: Path) -> list[dict[str, Any]]:
        results = []
        for spec in iter_golden_module_specs(root):
            try:
                results.append(self.run_spec(spec))
            except Exception as exc:
                results.append({
                    "slug": spec.slug,
                    "title": spec.title,
                    "source_mode": spec.source_mode,
                    "status": "failed",
                    "error_type": type(exc).__name__,
                    "error_code": _safe_error_code(exc),
                })
        return results

    def run_supporting_assets(self, root: Path) -> dict[str, Any]:
        admin_token, _ = self._ensure_accounts_and_login()
        rule_directory = root / "规则书"
        rule_paths = sorted(rule_directory.glob("*.pdf"))
        if len(rule_paths) != 9:
            raise GoldenSuiteError("expected nine golden rulebook PDFs")

        rule_set_response = self.client.post(
            "/api/rag/rule-sets",
            json={
                "name": "Golden-suite CoC7 rules",
                "slug": "golden-suite-coc7",
                "system": "coc7",
                "description": "Isolated acceptance import of local golden rulebooks.",
                "license_type": "authorized",
            },
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        self._require(rule_set_response, 200, "create golden rule set")
        rule_set_id = rule_set_response.json()["rule_set_id"]
        version_response = self.client.post(
            f"/api/rag/rule-sets/{rule_set_id}/versions",
            json={"label": "golden-suite-import"},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        self._require(version_response, 200, "create golden rule version")
        rule_set_version_id = version_response.json()["rule_set_version_id"]

        rule_results: list[dict[str, Any]] = []
        doc_ids: set[str] = set()
        for path in rule_paths:
            content = path.read_bytes()
            package = build_content_package(path.name, content, _mime_type(path))
            if not package.canonical_text.strip():
                raise GoldenSuiteError(f"rulebook has no extracted text: {path.name}")
            doc_id = f"golden-rule-{hashlib.sha256(content).hexdigest()[:16]}"
            source_ref = next(
                (part.source_ref for part in package.parts if part.source_ref),
                f"{path.name}#page:1",
            )
            response = self.client.post(
                "/api/rag/index-rules",
                json={
                    "doc_id": doc_id,
                    "title": path.stem,
                    "category": "coc7-golden-sample",
                    "content": package.canonical_text,
                    "rule_set_version_id": rule_set_version_id,
                    "source_ref": f"{path.name}#{source_ref}",
                    "citation": {"page_number": 1},
                },
                headers={"Authorization": f"Bearer {admin_token}"},
            )
            self._require(response, 200, f"index rulebook {path.name}")
            chunks = int(response.json().get("chunks") or 0)
            if chunks <= 0:
                raise GoldenSuiteError(f"rulebook created no chunks: {path.name}")
            doc_ids.add(doc_id)
            rule_results.append({
                "filename": path.name,
                "parts": len(package.parts),
                "text_chars": len(package.canonical_text),
                "chunks": chunks,
                "status": "indexed",
            })

        rule_docs_response = self.client.get(
            "/api/rag/rule-docs",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        self._require(rule_docs_response, 200, "list golden rule documents")
        indexed_doc_ids = {
            str(item.get("doc_id")) for item in rule_docs_response.json()
        }
        if not doc_ids.issubset(indexed_doc_ids):
            raise GoldenSuiteError("indexed golden rule documents are missing")
        publish_response = self.client.post(
            f"/api/rag/rule-set-versions/{rule_set_version_id}/publish",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        self._require(publish_response, 200, "publish golden rule version")

        character_directory = root / "角色卡模板"
        character_pdf_results = []
        for path in sorted(character_directory.glob("*.pdf")):
            package = build_content_package(path.name, path.read_bytes(), _mime_type(path))
            if not package.parts:
                raise GoldenSuiteError(f"character PDF has no extracted parts: {path.name}")
            character_pdf_results.append({
                "filename": path.name,
                "parts": len(package.parts),
                "requires_multimodal": package.requires_multimodal,
                "status": "parsed",
            })
        character_xlsx_results = []
        for path in sorted(character_directory.glob("*.xlsx")):
            response = self.client.post(
                "/api/player/character/preview-xlsx",
                files={"file": (path.name, path.read_bytes(), _mime_type(path))},
            )
            self._require(response, 200, f"preview character xlsx {path.name}")
            preview = response.json()
            character_xlsx_results.append({
                "filename": path.name,
                "status": "previewed",
                "skill_count": int(preview.get("skill_count") or 0),
            })

        return {
            "rule_set_version_id": rule_set_version_id,
            "rulebooks": rule_results,
            "character_pdfs": character_pdf_results,
            "character_xlsx": character_xlsx_results,
        }

    def _ensure_accounts_and_login(self) -> tuple[str, str]:
        accounts = (
            ("golden-admin", "golden-admin", "admin"),
            ("golden-host", "golden-host", "host"),
        )
        for account_id, username, role in accounts:
            self.conn.execute(
                "INSERT INTO accounts (account_id, username, password_hash, display_name, role) "
                "VALUES (%s, %s, %s, %s, %s) "
                "ON CONFLICT (username) DO UPDATE SET "
                "account_id = EXCLUDED.account_id, role = EXCLUDED.role, password_hash = EXCLUDED.password_hash",
                (account_id, username, _hash_password("golden-suite"), username, role),
            )
        self.conn.commit()
        return self._login("golden-admin"), self._login("golden-host")

    def _login(self, username: str) -> str:
        response = self.client.post(
            "/api/auth/login",
            json={"username": username, "password": "golden-suite"},
        )
        self._require(response, 200, "login")
        return response.json()["token"]

    def _ensure_player_login(self, slug: str) -> str:
        username = f"golden-player-{slug}"
        self.conn.execute(
            "INSERT INTO accounts (account_id, username, password_hash, display_name, role) "
            "VALUES (%s, %s, %s, %s, %s) "
            "ON CONFLICT (username) DO UPDATE SET "
            "account_id = EXCLUDED.account_id, role = EXCLUDED.role, password_hash = EXCLUDED.password_hash",
            (username, username, _hash_password("golden-suite"), username, "player"),
        )
        self.conn.commit()
        return self._login(username)

    def _import_spec(self, spec: GoldenModuleSpec, admin_token: str) -> dict[str, Any]:
        files = [
            ("files", (path.name, path.read_bytes(), _mime_type(path)))
            for path in spec.source_paths
        ]
        response = self.client.post(
            "/api/scenarios/import",
            files=files,
            data={
                "title": spec.title,
                "license_type": "authorized",
                "license_ref": "local-golden-suite-test-only",
            },
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        self._require(response, 200, f"import {spec.slug}")
        payload = response.json()
        if payload.get("status") != "draft_ready":
            raise GoldenSuiteError(f"{spec.slug} import status {payload.get('status')}")
        return payload

    def _add_preset_template(self, scenario_id: str) -> None:
        self.conn.execute(
            "INSERT INTO character_templates "
            "(template_id, scenario_id, name, occupation, attributes, skills, backstory) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s)",
            (
                f"{scenario_id}-golden-template",
                scenario_id,
                "黄金样本调查员",
                "研究员",
                json.dumps({"pow": 50}),
                json.dumps({"侦查": 60}),
                json.dumps({"initial_inventory": [{"name": "笔记本", "quantity": 1}]}),
            ),
        )
        self.conn.commit()

    def _prepare_runtime_package(
        self, scenario_id: str, scenario_version_id: str, admin_token: str
    ) -> dict[str, Any]:
        bindings = self.client.get(
            f"/api/admin/scenarios/{scenario_id}/versions/{scenario_version_id}/asset-bindings",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        if bindings.status_code == 200:
            for binding in bindings.json().get("bindings", []):
                if binding.get("status") == "confirmed":
                    continue
                response = self.client.patch(
                    f"/api/admin/scenarios/{scenario_id}/versions/{scenario_version_id}"
                    f"/asset-bindings/{binding['binding_id']}",
                    json={
                        "target_type": binding["target_type"],
                        "target_key": binding["target_key"],
                        "status": "confirmed",
                    },
                    headers={"Authorization": f"Bearer {admin_token}"},
                )
                self._require(response, 200, "confirm asset binding")
        response = self.client.post(
            f"/api/scenarios/{scenario_id}/versions/{scenario_version_id}/runtime-package/recompile",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        self._require(response, 200, "compile runtime package")
        runtime = response.json()
        for issue in list(runtime.get("quality_exceptions", [])):
            if not issue.get("waivable"):
                continue
            response = self.client.post(
                f"/api/scenarios/{scenario_id}/versions/{scenario_version_id}"
                "/runtime-package/exceptions/confirm",
                json={
                    "runtime_package_version_id": runtime["runtime_package_version_id"],
                    "exception_key": issue["exception_key"],
                    "note": "isolated golden-suite acceptance run",
                },
                headers={"Authorization": f"Bearer {admin_token}"},
            )
            self._require(response, 200, "confirm runtime exception")
            runtime = response.json()
        return runtime

    def _publish(
        self, scenario_id: str, scenario_version_id: str, host_token: str
    ) -> None:
        response = self.client.post(
            f"/api/scenarios/{scenario_id}/versions/{scenario_version_id}/publish",
            json={"confirm": True, "review_notes": "isolated golden-suite acceptance run"},
            headers={"Authorization": f"Bearer {host_token}"},
        )
        self._require(response, 200, "publish scenario version")

    def _create_room(self, scenario_id: str, host_token: str) -> dict[str, Any]:
        response = self.client.post(
            "/api/rooms",
            json={"scenario_id": scenario_id},
            headers={"Authorization": f"Bearer {host_token}"},
        )
        self._require(response, 200, "create room")
        return response.json()

    def _join_and_start(self, room: dict[str, Any], player_access_token: str) -> dict[str, Any]:
        room_id = room["room_id"]
        response = self.client.post(
            f"/api/player/rooms/{room_id}/join",
            headers={"Authorization": f"Bearer {player_access_token}"},
        )
        self._require(response, 200, "join player")
        player = response.json()
        response = self.client.post(
            f"/api/rooms/{room_id}/start",
            json={
                "force_start": True,
                "reason": "isolated golden-suite acceptance run",
                "confirm": True,
            },
            headers={"X-Owner-Token": room["owner_token"]},
        )
        self._require(response, 200, "start room")
        return player

    def _run_player_action(self, player_token: str) -> tuple[str, str]:
        headers = {"X-Room-Token": player_token}
        response = self.client.post(
            "/api/player/action-drafts/analyze",
            json={"declared_intent": "我调查当前场景，并核验已经发现的线索。"},
            headers=headers,
        )
        self._require(response, 200, "analyze player action")
        draft = response.json()
        response = self.client.post(
            f"/api/player/action-drafts/{draft['draft_id']}/confirm",
            json={"confirmations": draft.get("confirmation_requirements", [])},
            headers={
                **headers,
                "Idempotency-Key": f"golden-{uuid.uuid4()}",
                "X-Device-Id": "golden-suite-device",
            },
        )
        self._require(response, 200, "confirm player action")
        action_id = response.json()["action_id"]
        status = self.conn.execute(
            "SELECT status FROM actions WHERE action_id = %s", (action_id,)
        ).fetchone()["status"]
        if status == "queued":
            asyncio.run(ResolutionPipeline(
                self.conn,
                compiler=_GoldenSkillCheckCompiler(),
                dispatcher=_NoopDispatcher(),
                state_service=StateService(self.conn),
            ).resolve_action(action_id))
            status = self.conn.execute(
                "SELECT status FROM actions WHERE action_id = %s", (action_id,)
            ).fetchone()["status"]
        if status != "completed":
            action = self.conn.execute(
                "SELECT result FROM actions WHERE action_id = %s", (action_id,)
            ).fetchone()
            raise GoldenSuiteError(
                f"player action did not complete: {status}; "
                f"result={_json_object(action.get('result') if action else {})}"
            )
        return action_id, status

    def _end_room(
        self,
        room: dict[str, Any],
        scenario_version_id: str,
        source_mode: str,
    ) -> dict[str, Any]:
        row = self.conn.execute(
            "SELECT knowledge_graph FROM scenario_versions WHERE scenario_version_id = %s",
            (scenario_version_id,),
        ).fetchone()
        graph = _json_object(row["knowledge_graph"] if row else {})
        ending = next(iter(graph.get("endings") or []), {})
        citation = ending.get("citation") if isinstance(ending, dict) else {}
        if not isinstance(citation, dict) or not citation.get("source_ref"):
            raise GoldenSuiteError("compiled ending is missing a source citation")
        ending_type = str(ending.get("type") or "mixed")
        ending_name = str(ending.get("name") or "完成黄金样本验收")
        response = self.client.post(
            f"/api/rooms/{room['room_id']}/end",
            json={
                "ending_type": ending_type,
                "ending_name": ending_name,
                "text": str(ending.get("description") or "黄金样本验收完成。"),
            },
            headers={"X-Owner-Token": room["owner_token"]},
        )
        self._require(response, 200, "end campaign")
        return {
            "name": ending_name,
            "ending_type": ending_type,
            "citation": citation,
            "source_mode": source_mode,
            "derived_from_materials_only": source_mode == "materials_only",
        }

    @staticmethod
    def _require(response, status_code: int, operation: str) -> None:
        if response.status_code != status_code:
            raise GoldenSuiteError(
                f"{operation} failed with HTTP {response.status_code} "
                f"({ _response_error_code(response) })"
            )


def _mime_type(path: Path) -> str:
    if path.suffix.lower() == ".doc":
        return "application/msword"
    return mimetypes.guess_type(path.name)[0] or "application/octet-stream"


def _json_object(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            loaded = json.loads(value)
        except json.JSONDecodeError:
            return {}
        return loaded if isinstance(loaded, dict) else {}
    return {}


def _chunk_rule_content(content: str, max_chars: int = 500) -> list[tuple[str, int, int]]:
    return [
        (content[offset:offset + max_chars], offset, min(offset + max_chars, len(content)))
        for offset in range(0, len(content), max_chars)
        if content[offset:offset + max_chars]
    ]


def _response_error_code(response) -> str:
    try:
        payload = response.json()
    except ValueError:
        return "non_json_error"
    detail = payload.get("detail") if isinstance(payload, dict) else None
    if isinstance(detail, dict):
        code = detail.get("code")
        return str(code) if code else "structured_error"
    if isinstance(detail, list):
        return "validation_error"
    return "request_failed"


def _safe_error_code(exc: Exception) -> str:
    message = str(exc)
    operation = re.match(r"^(?P<operation>[a-z_ ]+) failed with HTTP \d+", message)
    match = re.search(r"\(([^()]+)\)$", message)
    if operation and match:
        return f"{operation.group('operation').replace(' ', '_')}:{match.group(1)}"
    return match.group(1) if match else type(exc).__name__


def _test_database_url(value: str) -> str:
    match = re.search(r"/([^/?]+)(?:\?|$)", value)
    if not match or "test" not in match.group(1).lower():
        raise GoldenSuiteError("database URL must target a database whose name contains test")
    return value


def _ensure_database_exists(url: str) -> None:
    maintenance_url = re.sub(r"/[^/?]+(\?|$)", r"/postgres\1", url)
    database_name = url.rsplit("/", 1)[-1].split("?", 1)[0]
    connection = psycopg2.connect(maintenance_url)
    connection.autocommit = True
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1 FROM pg_database WHERE datname = %s", (database_name,))
            if cursor.fetchone() is None:
                cursor.execute(f'CREATE DATABASE "{database_name}"')
    finally:
        connection.close()


def _reset_database(conn) -> None:
    conn.execute(
        "TRUNCATE TABLE scenarios, accounts, rule_sets, rule_documents, "
        "document_chunks RESTART IDENTITY CASCADE"
    )
    conn.commit()


def _write_report(
    path: Path,
    results: list[dict[str, Any]],
    supporting_assets: dict[str, Any] | None = None,
) -> None:
    passed = [item for item in results if item.get("room_status") == "completed"]
    lines = [
        "# 六类黄金样本批量导入与通关报告",
        "",
        f"- 模组目录：{len(results)}",
        f"- 已完成房间：{len(passed)}",
        "- 执行模式：隔离 PostgreSQL 测试库 + 确定性结构化/规则夹具 + 正式 FastAPI 路由。",
        "- 素材包结局标为 `derived_from_materials_only`，不主张为原文结局。",
        "",
        "## 结果",
        "",
        "| 模组 | 导入 | 运行包 | 动作 | 房间 | 结局来源 |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for item in results:
        if item.get("status") == "failed":
            lines.append(
                f"| {item['slug']} | failed | - | - | - | {item['error_type']} ({item['error_code']}) |"
            )
            continue
        ending = item["ending"]
        source_mode = "derived_from_materials_only" if ending["derived_from_materials_only"] else "source_backed"
        lines.append(
            f"| {item['slug']} | {item['import_status']} | {item['runtime_gate_status']} | "
            f"{item['action_status']} | {item['room_status']} | {source_mode} ({ending['citation']['source_ref']}) |"
        )
    if supporting_assets:
        lines.extend([
            "",
            "## 规则书与角色卡",
            "",
            "- 规则书通过正式 `/api/rag` 接口写入隔离的版本化规则集；使用确定性分片夹具验证持久化链，不代表真实 embedding 召回质量。",
            f"- 已发布规则版本：`{supporting_assets['rule_set_version_id']}`",
            "",
            "| 规则书 | 文本字符 | 分片 | 状态 |",
            "| --- | ---: | ---: | --- |",
        ])
        for item in supporting_assets["rulebooks"]:
            lines.append(
                f"| {item['filename']} | {item['text_chars']} | {item['chunks']} | {item['status']} |"
            )
        lines.extend([
            "",
            "| 角色卡素材 | 类型 | 状态 | 详情 |",
            "| --- | --- | --- | --- |",
        ])
        for item in supporting_assets["character_pdfs"]:
            lines.append(
                f"| {item['filename']} | PDF | {item['status']} | parts={item['parts']}, multimodal={item['requires_multimodal']} |"
            )
        for item in supporting_assets["character_xlsx"]:
            lines.append(
                f"| {item['filename']} | XLSX | {item['status']} | skills={item['skill_count']} |"
            )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument(
        "--database-url",
        default="postgresql://aikeeper:aikeeper123@localhost:5432/aikeeper_golden_test",
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=ROOT / "docs" / "loop_runs" / "2026-07-16-golden-module-suite-report.md",
    )
    args = parser.parse_args()
    database_url = _test_database_url(args.database_url)
    _ensure_database_exists(database_url)
    database = PgDatabase(dsn=database_url)
    database.connect()
    database.initialize()
    conn = database.get_connection()
    try:
        _reset_database(conn)
        with TestClient(app) as client:
            runner = GoldenModuleSuiteRunner(
                client,
                conn,
                storage_root=ROOT / ".runtime" / "golden-suite" / "sources",
                asset_root=ROOT / ".runtime" / "golden-suite" / "assets",
            )
            results = runner.run_all(args.root)
            supporting_assets = runner.run_supporting_assets(args.root)
        _write_report(args.report, results, supporting_assets)
        return 0 if all(item.get("room_status") == "completed" for item in results) else 1
    finally:
        conn.close()
        database.close()


if __name__ == "__main__":
    raise SystemExit(main())
