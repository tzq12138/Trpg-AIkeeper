from __future__ import annotations

import hashlib
import json
import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .content_package import (
    ContentPackage,
    ContentPackageError,
    ContentPart,
    build_content_package,
)
from .content_projection import ContentProjectionService
from .module_compiler import ModuleCompiler, ModuleCompilerError
from .quality import QualityReportGenerator
from .review_service import review_publish_blockers
from .solo_adventure import extract_solo_adventure

logger = logging.getLogger(__name__)

MAX_SOURCE_FILES = 20
MAX_FILE_BYTES = 50 * 1024 * 1024
MAX_TOTAL_BYTES = 100 * 1024 * 1024
ALLOWED_LICENSE_TYPES = {"authorized", "open"}
STALE_IMPORT_SECONDS = 300
STALE_RETRYABLE_IMPORT_STATUSES = {"parsing", "structuring"}


def is_import_job_retryable(
    status: str | None,
    updated_at: Any,
    *,
    now: datetime | None = None,
) -> bool:
    if status == "awaiting_provider":
        return True
    if status not in STALE_RETRYABLE_IMPORT_STATUSES or not updated_at:
        return False
    timestamp = updated_at
    if isinstance(timestamp, str):
        try:
            timestamp = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        except ValueError:
            return False
    if not isinstance(timestamp, datetime):
        return False
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=timezone.utc)
    reference = now or datetime.now(timezone.utc)
    if reference.tzinfo is None:
        reference = reference.replace(tzinfo=timezone.utc)
    return (reference - timestamp).total_seconds() >= STALE_IMPORT_SECONDS


@dataclass(slots=True)
class UploadedSource:
    filename: str
    content: bytes
    mime_type: str = ""


class ScenarioImportFailure(Exception):
    def __init__(self, status_code: int, detail: dict[str, Any]):
        super().__init__(str(detail.get("message") or "scenario import failed"))
        self.status_code = status_code
        self.detail = detail


class ScenarioImportService:
    def __init__(
        self,
        conn,
        gateway=None,
        rag=None,
        storage_root: Path | None = None,
        asset_root: Path | None = None,
        max_source_files: int = MAX_SOURCE_FILES,
        max_file_bytes: int = MAX_FILE_BYTES,
        max_total_bytes: int = MAX_TOTAL_BYTES,
    ):
        self.conn = conn
        self.gateway = gateway
        self.rag = rag
        self.storage_root = storage_root or (
            Path(__file__).resolve().parents[3] / "data" / "scenarios"
        )
        self.asset_root = asset_root or (
            Path(__file__).resolve().parents[3] / "data" / "scenario_assets"
        )
        self.max_source_files = max_source_files
        self.max_file_bytes = max_file_bytes
        self.max_total_bytes = max_total_bytes

    async def import_sources(
        self,
        sources: list[UploadedSource],
        *,
        title: str,
        license_type: str,
        license_ref: str | None,
        created_by: str,
        scenario_id: str | None = None,
    ) -> dict[str, Any]:
        self._validate_sources(sources, license_type)
        prepared = [self._prepare_source(source) for source in sources]

        existing_scenario = None
        if scenario_id:
            existing_scenario = self.conn.execute(
                "SELECT * FROM scenarios WHERE scenario_id = %s",
                (scenario_id,),
            ).fetchone()
            if not existing_scenario:
                raise ScenarioImportFailure(404, {"message": "目标剧本不存在"})

        if len(prepared) == 1:
            duplicate = self.conn.execute(
                """
                SELECT sd.scenario_id, s.title, s.import_status, s.publish_status,
                       s.published_version_id
                FROM source_documents sd
                JOIN scenarios s ON s.scenario_id = sd.scenario_id
                WHERE sd.source_sha256 = %s AND sd.source_kind = 'scenario'
                """,
                (prepared[0]["sha256"],),
            ).fetchone()
            if duplicate:
                latest_job = self.conn.execute(
                    "SELECT job_id, status, updated_at FROM import_jobs "
                    "WHERE scenario_id = %s ORDER BY updated_at DESC, created_at DESC LIMIT 1",
                    (duplicate["scenario_id"],),
                ).fetchone()
                return {
                    "scenario_id": duplicate["scenario_id"],
                    "scenario_version_id": duplicate.get("published_version_id"),
                    "status": "already_imported",
                    "title": duplicate["title"],
                    "import_status": duplicate["import_status"],
                    "publish_status": duplicate.get("publish_status", "draft"),
                    "job_id": latest_job.get("job_id") if latest_job else None,
                    "retryable": is_import_job_retryable(
                        latest_job.get("status") if latest_job else None,
                        latest_job.get("updated_at") if latest_job else None,
                    ),
                }

        duplicate_hashes = []
        for source in prepared:
            existing = self.conn.execute(
                "SELECT source_document_id FROM source_documents "
                "WHERE source_sha256 = %s AND source_kind = 'scenario'",
                (source["sha256"],),
            ).fetchone()
            if existing:
                duplicate_hashes.append(source["sha256"])
        if duplicate_hashes:
            raise ScenarioImportFailure(409, {
                "status": "duplicate_source",
                "message": "多文件导入中包含已存在的来源文件",
                "duplicate_sha256": duplicate_hashes,
            })

        is_new_scenario = existing_scenario is None
        scenario_id = scenario_id or str(uuid.uuid4())
        scenario_title = (
            title.strip()
            or (existing_scenario.get("title") if existing_scenario else "")
            or prepared[0]["filename"]
        )
        combined_sha = hashlib.sha256(
            "|".join(source["sha256"] for source in prepared).encode("ascii")
        ).hexdigest()
        import_batch_id = str(uuid.uuid4())
        source_rows = []
        for ordinal, source in enumerate(prepared, start=1):
            source_document_id = str(uuid.uuid4())
            job_id = str(uuid.uuid4())
            relative_path = (
                Path(scenario_id) / source_document_id / source["filename"]
            ).as_posix()
            source_rows.append({
                **source,
                "ordinal": ordinal,
                "source_document_id": source_document_id,
                "job_id": job_id,
                "relative_path": relative_path,
                "import_batch_id": import_batch_id,
            })

        with self.conn.transaction() as tx:
            if is_new_scenario:
                tx.execute(
                    """
                    INSERT INTO scenarios (
                        scenario_id, title, raw_text, knowledge_graph, import_status,
                        source_filename, source_sha256, original_file_path,
                        quality_report, publish_status
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        scenario_id,
                        scenario_title,
                        "",
                        json.dumps({}, ensure_ascii=False),
                        "parsing",
                        ", ".join(row["filename"] for row in source_rows),
                        combined_sha,
                        source_rows[0]["relative_path"],
                        json.dumps({}, ensure_ascii=False),
                        "draft",
                    ),
                )
            for row in source_rows:
                tx.execute(
                    """
                    INSERT INTO source_documents (
                        source_document_id, scenario_id, source_kind, title,
                        source_filename, mime_type, source_sha256, storage_path,
                        license_type, license_ref, status, metadata, created_by
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        row["source_document_id"], scenario_id, "scenario",
                        scenario_title, row["filename"], row["mime_type"],
                        row["sha256"], row["relative_path"], license_type,
                        license_ref, "pending", json.dumps({
                            "ordinal": row["ordinal"],
                            "import_batch_id": import_batch_id,
                        }),
                        created_by,
                    ),
                )
                tx.execute(
                    """
                    INSERT INTO import_jobs (
                        job_id, source_document_id, scenario_id, status, progress,
                        diagnostics
                    ) VALUES (%s, %s, %s, %s, %s, %s)
                    """,
                    (
                        row["job_id"], row["source_document_id"], scenario_id,
                        "parsing", 10, json.dumps({
                            "import_batch_id": import_batch_id,
                        }, ensure_ascii=False),
                    ),
                )

        try:
            packages = self._persist_and_parse_sources(source_rows)
        except Exception as exc:
            self._mark_import_failed(
                scenario_id, source_rows, exc, update_scenario=is_new_scenario
            )
            raise ScenarioImportFailure(422, {
                "status": "failed",
                "message": "来源文件解析失败",
                "scenario_id": scenario_id,
                "job_ids": [row["job_id"] for row in source_rows],
            }) from exc

        combined_package = self._combine_packages(scenario_title, combined_sha, packages)
        try:
            knowledge_graph = await self._structure_package(combined_package)
            knowledge_graph = await self._repair_runtime_contract_if_needed(
                combined_package,
                knowledge_graph,
            )
        except Exception as exc:
            status = (
                "awaiting_provider"
                if combined_package.requires_multimodal and not combined_package.canonical_text
                else "failed"
            )
            self._mark_import_failed(
                scenario_id,
                source_rows,
                exc,
                status=status,
                update_scenario=is_new_scenario,
            )
            if status == "awaiting_provider":
                return {
                    "scenario_id": scenario_id,
                    "status": status,
                    "job_ids": [row["job_id"] for row in source_rows],
                    "requires_multimodal": True,
                }
            raise ScenarioImportFailure(502, {
                "status": "failed",
                "message": "世界书结构化失败",
                "scenario_id": scenario_id,
                "job_ids": [row["job_id"] for row in source_rows],
            }) from exc

        return await self._create_draft_version(
            scenario_id=scenario_id,
            scenario_title=scenario_title,
            knowledge_graph=knowledge_graph,
            combined_package=combined_package,
            source_rows=source_rows,
            created_by=created_by,
            update_scenario=is_new_scenario,
        )

    async def retry_import(self, job_id: str, *, requested_by: str) -> dict[str, Any]:
        target = self.conn.execute(
            """
            SELECT ij.job_id, ij.source_document_id, ij.scenario_id,
                   ij.status AS job_status, ij.updated_at AS job_updated_at,
                   ij.diagnostics,
                   sd.metadata, s.title, s.import_status
            FROM import_jobs ij
            JOIN source_documents sd
              ON sd.source_document_id = ij.source_document_id
            JOIN scenarios s ON s.scenario_id = ij.scenario_id
            WHERE ij.job_id = %s
            """,
            (job_id,),
        ).fetchone()
        if not target:
            raise ScenarioImportFailure(404, {"message": "导入任务不存在"})
        if not is_import_job_retryable(
            target.get("job_status"), target.get("job_updated_at")
        ):
            raise ScenarioImportFailure(409, {
                "message": "该导入任务仍在处理中或不可重试",
                "status": target.get("job_status"),
            })

        target_diagnostics = _json_value(target.get("diagnostics"))
        target_metadata = _json_value(target.get("metadata"))
        import_batch_id = str(
            target_diagnostics.get("import_batch_id")
            or target_metadata.get("import_batch_id")
            or ""
        )
        candidates = self.conn.execute(
            """
            SELECT sd.source_document_id, sd.source_filename, sd.mime_type,
                   sd.source_sha256, sd.storage_path, sd.metadata,
                   ij.job_id, ij.status AS job_status, ij.diagnostics
            FROM source_documents sd
            JOIN import_jobs ij ON ij.source_document_id = sd.source_document_id
            WHERE sd.scenario_id = %s AND sd.source_kind = 'scenario'
            ORDER BY sd.created_at, sd.source_document_id
            """,
            (target["scenario_id"],),
        ).fetchall()
        source_rows = []
        for candidate in candidates:
            metadata = _json_value(candidate.get("metadata"))
            diagnostics = _json_value(candidate.get("diagnostics"))
            candidate_batch_id = str(
                diagnostics.get("import_batch_id")
                or metadata.get("import_batch_id")
                or ""
            )
            if import_batch_id:
                if candidate_batch_id != import_batch_id:
                    continue
            elif candidate["source_document_id"] != target["source_document_id"]:
                continue
            source_rows.append({
                "source_document_id": candidate["source_document_id"],
                "job_id": candidate["job_id"],
                "ordinal": int(metadata.get("ordinal") or 1),
                "filename": candidate["source_filename"],
                "mime_type": candidate["mime_type"],
                "sha256": candidate["source_sha256"],
                "relative_path": candidate["storage_path"],
                "import_batch_id": candidate_batch_id,
            })
        if not source_rows:
            raise ScenarioImportFailure(409, {"message": "导入任务缺少可重试来源"})

        packages = []
        storage_root = self.storage_root.resolve()
        for row in sorted(source_rows, key=lambda item: item["ordinal"]):
            source_path = (storage_root / Path(row["relative_path"])).resolve()
            if not source_path.is_relative_to(storage_root) or not source_path.is_file():
                raise ScenarioImportFailure(409, {"message": "导入来源文件不可用"})
            package = build_content_package(
                row["filename"], source_path.read_bytes(), row["mime_type"]
            )
            packages.append(package)
            self._persist_source_parts(row, package)

        combined_sha = hashlib.sha256(
            "|".join(row["sha256"] for row in source_rows).encode("ascii")
        ).hexdigest()
        combined_package = self._combine_packages(
            target["title"], combined_sha, packages
        )
        with self.conn.transaction() as tx:
            for row in source_rows:
                tx.execute(
                    "UPDATE import_jobs SET status = 'structuring', progress = 50, "
                    "error_message = NULL, updated_at = NOW() WHERE job_id = %s",
                    (row["job_id"],),
                )
        update_scenario = target.get("import_status") in {
            "awaiting_provider", "parsing", "structuring"
        }
        try:
            knowledge_graph = await self._structure_package(combined_package)
        except Exception as exc:
            self._mark_import_failed(
                target["scenario_id"],
                source_rows,
                exc,
                status="awaiting_provider",
                update_scenario=update_scenario,
            )
            return {
                "scenario_id": target["scenario_id"],
                "status": "awaiting_provider",
                "job_ids": [row["job_id"] for row in source_rows],
                "requires_multimodal": combined_package.requires_multimodal,
            }

        return await self._create_draft_version(
            scenario_id=target["scenario_id"],
            scenario_title=target["title"],
            knowledge_graph=knowledge_graph,
            combined_package=combined_package,
            source_rows=source_rows,
            created_by=requested_by,
            update_scenario=update_scenario,
        )

    async def rebuild_draft_from_sources(
        self,
        scenario_id: str,
        source_version_id: str,
        *,
        requested_by: str,
    ) -> dict[str, Any]:
        source_version = self.conn.execute(
            """
            SELECT sv.scenario_version_id, s.title
            FROM scenario_versions sv
            JOIN scenarios s ON s.scenario_id = sv.scenario_id
            WHERE sv.scenario_id = %s AND sv.scenario_version_id = %s
            """,
            (scenario_id, source_version_id),
        ).fetchone()
        if not source_version:
            raise ScenarioImportFailure(404, {"message": "剧本版本不存在"})
        source_rows = self.conn.execute(
            """
            SELECT svs.ordinal, sd.source_document_id, sd.source_filename,
                   sd.mime_type, sd.source_sha256, sd.storage_path
            FROM scenario_version_sources svs
            JOIN source_documents sd
              ON sd.source_document_id = svs.source_document_id
            WHERE svs.scenario_version_id = %s
            ORDER BY svs.ordinal
            """,
            (source_version_id,),
        ).fetchall()
        if not source_rows:
            raise ScenarioImportFailure(409, {
                "message": "剧本版本缺少可重建的原始来源",
            })

        normalized_rows = [dict(row) for row in source_rows]
        storage_root = self.storage_root.resolve()
        packages = []
        for row in normalized_rows:
            source_path = (storage_root / Path(row["storage_path"])).resolve()
            if not source_path.is_relative_to(storage_root) or not source_path.is_file():
                raise ScenarioImportFailure(409, {
                    "message": "剧本原始来源不可用",
                    "source_document_id": row["source_document_id"],
                })
            packages.append(build_content_package(
                row["source_filename"],
                source_path.read_bytes(),
                row["mime_type"],
            ))
        combined_sha = hashlib.sha256(
            "|".join(row["source_sha256"] for row in normalized_rows).encode("ascii")
        ).hexdigest()
        combined_package = self._combine_packages(
            source_version["title"], combined_sha, packages
        )
        try:
            knowledge_graph = await self._structure_package(combined_package)
        except Exception as exc:
            raise ScenarioImportFailure(502, {
                "status": "failed",
                "message": "剧本重建结构化失败",
            }) from exc
        return await self._create_draft_version(
            scenario_id=scenario_id,
            scenario_title=source_version["title"],
            knowledge_graph=knowledge_graph,
            combined_package=combined_package,
            source_rows=normalized_rows,
            created_by=requested_by,
            update_scenario=False,
            preserve_source_history=True,
        )

    def publish_version(
        self,
        scenario_id: str,
        scenario_version_id: str,
        *,
        reviewer: dict,
        confirm: bool,
        review_notes: str,
    ) -> dict[str, Any]:
        if not confirm:
            raise ScenarioImportFailure(400, {
                "status": "confirmation_required",
                "message": "发布前必须明确确认备团包",
            })
        row = self.conn.execute(
            """
            SELECT sv.*, s.title
            FROM scenario_versions sv
            JOIN scenarios s ON s.scenario_id = sv.scenario_id
            WHERE sv.scenario_version_id = %s AND sv.scenario_id = %s
            """,
            (scenario_version_id, scenario_id),
        ).fetchone()
        if not row:
            raise ScenarioImportFailure(404, {"message": "剧本版本不存在"})
        if row["status"] == "published":
            return {
                "scenario_id": scenario_id,
                "scenario_version_id": scenario_version_id,
                "status": "published",
                "rag_index_version": row.get("rag_index_version"),
            }
        review_blockers = review_publish_blockers(self.conn, scenario_version_id)
        if review_blockers:
            raise ScenarioImportFailure(409, {
                "status": "review_incomplete",
                "message": "Core review issues must be fixed before publishing.",
                "issues": review_blockers,
            })
        solo_adventure = _json_value(row.get("knowledge_graph")).get(
            "solo_adventure"
        )
        solo_integrity = (
            solo_adventure.get("integrity")
            if isinstance(solo_adventure, dict)
            else None
        )
        if isinstance(solo_integrity, dict) and not solo_integrity.get("is_valid", True):
            raise ScenarioImportFailure(409, {
                "status": "invalid_solo_adventure",
                "message": "编号单人冒险存在重复条目或无效跳转，不能发布",
                "duplicate_node_ids": solo_integrity.get("duplicate_node_ids") or [],
                "missing_target_node_ids": solo_integrity.get("missing_target_node_ids") or [],
            })
        quality_report = _json_value(row.get("quality_report"))
        if quality_report.get("level") == "blocked":
            raise ScenarioImportFailure(409, {
                "status": "quality_blocked",
                "message": "该版本存在阻塞质量问题，修复后才能发布",
                "issues": quality_report.get("issues") or [],
            })
        try:
            runtime_package = ModuleCompiler(self.conn).latest_ready_for_version(
                scenario_version_id
            )
        except ModuleCompilerError as exc:
            raise ScenarioImportFailure(409, {
                "status": "runtime_package_not_ready",
                "message": "发布前必须先生成并确认 ready 的运行包",
                "reason": str(exc),
            }) from exc
        if not self.rag:
            raise ScenarioImportFailure(503, {"message": "RAG not available"})

        part_rows = self.conn.execute(
            """
            SELECT sp.source_part_id, sp.part_kind, sp.page_number,
                   sp.text_content, sp.mime_type, sp.anchor, sd.source_filename
            FROM scenario_version_sources svs
            JOIN source_documents sd
              ON sd.source_document_id = svs.source_document_id
            JOIN source_parts sp
              ON sp.source_document_id = sd.source_document_id
            WHERE svs.scenario_version_id = %s
            ORDER BY svs.ordinal, sp.ordinal
            """,
            (scenario_version_id,),
        ).fetchall()
        index_parts = [_rag_part(row) for row in part_rows]
        canonical_text = "\n\n".join(
            str(part.get("text_content") or "")
            for part in part_rows
            if str(part.get("text_content") or "").strip()
        ).strip()
        rebuild_id = str(uuid.uuid4())
        embedding_model, embedding_dimensions = _rag_embedding_metadata(self.rag)
        self.conn.execute(
            """
            INSERT INTO rag_rebuild_records (
                rebuild_id, scenario_version_id, status, embedding_model,
                embedding_dimensions, requested_by
            ) VALUES (%s, %s, 'running', %s, %s, %s)
            """,
            (
                rebuild_id,
                scenario_version_id,
                embedding_model,
                embedding_dimensions,
                reviewer.get("account_id", "unknown"),
            ),
        )
        try:
            chunk_count = self.rag.index_scenario_version(
                scenario_id,
                scenario_version_id,
                index_parts,
                visibility="internal",
            )
            knowledge_graph = _json_value(row.get("knowledge_graph"))
            npc_count = 0
            if knowledge_graph.get("npcs"):
                npc_count = self.rag.index_npc_graph(
                    scenario_id,
                    knowledge_graph,
                    scenario_version_id=scenario_version_id,
                    visibility="internal",
                )
            content_count = 0
            if hasattr(self.rag, "index_content_projection"):
                content_items = ContentProjectionService(self.conn).items(
                    scenario_version_id
                )
                content_count = self.rag.index_content_projection(
                    scenario_id,
                    scenario_version_id,
                    content_items,
                )
            embedding_model, embedding_dimensions = _rag_embedding_metadata(self.rag)
        except Exception as exc:
            self.conn.execute(
                """
                UPDATE rag_rebuild_records
                SET status = 'failed', error_message = %s, completed_at = NOW()
                WHERE rebuild_id = %s
                """,
                (str(exc)[:1000], rebuild_id),
            )
            raise ScenarioImportFailure(500, {
                "status": "failed",
                "message": "版本索引构建失败",
                "rebuild_id": rebuild_id,
            }) from exc

        with self.conn.transaction() as tx:
            tx.execute(
                """
                UPDATE scenario_versions
                SET status = 'published', rag_index_version = %s,
                    reviewed_by = %s, reviewed_at = NOW(), review_notes = %s,
                    published_at = NOW()
                WHERE scenario_version_id = %s
                """,
                (
                    rebuild_id,
                    reviewer.get("account_id", "unknown"),
                    json.dumps({"notes": review_notes}, ensure_ascii=False),
                    scenario_version_id,
                ),
            )
            tx.execute(
                """
                UPDATE scenarios
                SET publish_status = 'published', published_version_id = %s,
                    import_status = 'structured', raw_text = %s,
                    knowledge_graph = %s, quality_report = %s, title = %s
                WHERE scenario_id = %s
                """,
                (
                    scenario_version_id,
                    canonical_text,
                    json.dumps(_json_value(row.get("knowledge_graph")), ensure_ascii=False),
                    json.dumps(quality_report, ensure_ascii=False),
                    _json_value(row.get("prep_package")).get("title") or row["title"],
                    scenario_id,
                ),
            )
            tx.execute(
                """
                UPDATE rag_rebuild_records
                SET status = 'complete', chunk_count = %s,
                    embedding_model = %s, embedding_dimensions = %s,
                    completed_at = NOW()
                WHERE rebuild_id = %s
                """,
                (
                    chunk_count + npc_count + content_count,
                    embedding_model,
                    embedding_dimensions,
                    rebuild_id,
                ),
            )
            self._bind_published_base_rules(tx, scenario_version_id)

        return {
            "scenario_id": scenario_id,
            "scenario_version_id": scenario_version_id,
            "status": "published",
            "rag_index_version": rebuild_id,
            "runtime_package_version_id": runtime_package["runtime_package_version_id"],
            "chunks_indexed": chunk_count + npc_count + content_count,
        }

    def activate_published_version(
        self,
        scenario_id: str,
        scenario_version_id: str,
        *,
        confirm: bool,
    ) -> dict[str, Any]:
        if not confirm:
            raise ScenarioImportFailure(400, {"message": "切换版本前必须明确确认"})
        row = self.conn.execute(
            """
            SELECT sv.status, sv.knowledge_graph, sv.quality_report,
                   sv.prep_package, s.title
            FROM scenario_versions sv
            JOIN scenarios s ON s.scenario_id = sv.scenario_id
            WHERE sv.scenario_id = %s AND sv.scenario_version_id = %s
            """,
            (scenario_id, scenario_version_id),
        ).fetchone()
        if not row:
            raise ScenarioImportFailure(404, {"message": "剧本版本不存在"})
        if row["status"] != "published":
            raise ScenarioImportFailure(409, {"message": "只能激活已发布版本"})
        text_rows = self.conn.execute(
            """
            SELECT sp.text_content
            FROM scenario_version_sources svs
            JOIN source_parts sp
              ON sp.source_document_id = svs.source_document_id
            WHERE svs.scenario_version_id = %s
            ORDER BY svs.ordinal, sp.ordinal
            """,
            (scenario_version_id,),
        ).fetchall()
        canonical_text = "\n\n".join(
            str(item.get("text_content") or "")
            for item in text_rows
            if str(item.get("text_content") or "").strip()
        ).strip()
        prep_package = _json_value(row.get("prep_package"))
        self.conn.execute(
            """
            UPDATE scenarios
            SET published_version_id = %s, publish_status = 'published',
                import_status = 'structured', raw_text = %s,
                knowledge_graph = %s, quality_report = %s, title = %s
            WHERE scenario_id = %s
            """,
            (
                scenario_version_id,
                canonical_text,
                json.dumps(_json_value(row.get("knowledge_graph")), ensure_ascii=False),
                json.dumps(_json_value(row.get("quality_report")), ensure_ascii=False),
                prep_package.get("title") or row["title"],
                scenario_id,
            ),
        )
        return {
            "scenario_id": scenario_id,
            "active_version_id": scenario_version_id,
            "status": "published",
        }

    def _validate_sources(self, sources: list[UploadedSource], license_type: str) -> None:
        if license_type not in ALLOWED_LICENSE_TYPES:
            raise ScenarioImportFailure(400, {
                "message": "license_type 必须为 authorized 或 open"
            })
        if not sources or len(sources) > self.max_source_files:
            raise ScenarioImportFailure(400, {"message": "来源文件数量不合法"})
        total = sum(len(source.content) for source in sources)
        if total > self.max_total_bytes:
            raise ScenarioImportFailure(413, {"message": "来源文件总大小超过限制"})
        if any(len(source.content) > self.max_file_bytes for source in sources):
            raise ScenarioImportFailure(413, {"message": "来源文件过大"})

    def _prepare_source(self, source: UploadedSource) -> dict[str, Any]:
        filename = Path(source.filename.replace("\\", "/")).name
        if not filename or filename in {".", ".."}:
            raise ScenarioImportFailure(400, {"message": "来源文件名不合法"})
        return {
            "filename": filename,
            "content": source.content,
            "mime_type": source.mime_type or "application/octet-stream",
            "sha256": hashlib.sha256(source.content).hexdigest(),
        }

    def _persist_and_parse_sources(self, source_rows: list[dict[str, Any]]) -> list[ContentPackage]:
        packages = []
        for row in source_rows:
            destination = self.storage_root / Path(row["relative_path"])
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(row["content"])
            package = build_content_package(
                row["filename"], row["content"], row["mime_type"]
            )
            packages.append(package)
            self._persist_source_parts(row, package)
        return packages

    def _persist_source_parts(
        self,
        source_row: dict[str, Any],
        package: ContentPackage,
    ) -> None:
        with self.conn.transaction() as tx:
            for part in package.parts:
                anchor = {
                    "source_ref": part.source_ref,
                    **(part.metadata if isinstance(part.metadata, dict) else {}),
                }
                checksum_payload = part.text or part.data_url or part.source_ref
                tx.execute(
                    """
                    INSERT INTO source_parts (
                        source_part_id, source_document_id, ordinal, part_kind,
                        page_number, text_content, mime_type, storage_path,
                        anchor, checksum
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (source_document_id, ordinal) DO UPDATE SET
                        part_kind = EXCLUDED.part_kind,
                        page_number = EXCLUDED.page_number,
                        text_content = EXCLUDED.text_content,
                        mime_type = EXCLUDED.mime_type,
                        storage_path = EXCLUDED.storage_path,
                        anchor = EXCLUDED.anchor,
                        checksum = EXCLUDED.checksum
                    """,
                    (
                        str(uuid.uuid4()),
                        source_row["source_document_id"],
                        part.ordinal,
                        part.kind,
                        part.page_number,
                        part.text or "",
                        part.mime_type or package.mime_type,
                        source_row["relative_path"],
                        json.dumps(anchor, ensure_ascii=False),
                        hashlib.sha256(checksum_payload.encode("utf-8")).hexdigest(),
                    ),
                )
            tx.execute(
                "UPDATE import_jobs SET status = 'structuring', progress = 50, "
                "updated_at = NOW() WHERE job_id = %s",
                (source_row["job_id"],),
            )

    def _combine_packages(
        self,
        title: str,
        combined_sha: str,
        packages: list[ContentPackage],
    ) -> ContentPackage:
        parts = []
        ordinal = 0
        for package in packages:
            for part in package.parts:
                ordinal += 1
                parts.append(ContentPart(
                    ordinal=ordinal,
                    kind=part.kind,
                    text=part.text,
                    mime_type=part.mime_type,
                    page_number=part.page_number,
                    data_url=part.data_url,
                    source_ref=f"{package.source_filename}#{part.source_ref}",
                    metadata={
                        "source_filename": package.source_filename,
                        **(part.metadata if isinstance(part.metadata, dict) else {}),
                    },
                ))
        return ContentPackage(
            source_filename=title,
            source_sha256=combined_sha,
            mime_type="application/x-aikeeper-content-package",
            parts=parts,
            canonical_text="\n\n".join(
                package.canonical_text for package in packages if package.canonical_text
            ).strip(),
            requires_multimodal=any(package.requires_multimodal for package in packages),
            metadata={"source_count": len(packages)},
        )

    async def _structure_package(self, package: ContentPackage) -> dict[str, Any]:
        from ..ai.ai_kp import normalize_knowledge_graph

        if self.gateway and hasattr(self.gateway, "structure_content_package"):
            return normalize_knowledge_graph(
                await self.gateway.structure_content_package(package)
            )
        if package.canonical_text:
            from ..ai.ai_kp import structure_scenario

            return normalize_knowledge_graph(
                await structure_scenario(package.canonical_text)
            )
        raise RuntimeError("multimodal_provider_unavailable")

    async def _repair_runtime_contract_if_needed(
        self,
        package: ContentPackage,
        knowledge_graph: dict[str, Any],
    ) -> dict[str, Any]:
        if not _needs_runtime_contract_repair(knowledge_graph):
            return knowledge_graph
        if not self.gateway or not hasattr(self.gateway, "repair_runtime_contract"):
            return knowledge_graph
        from ..ai.ai_kp import normalize_knowledge_graph

        try:
            repair = await self.gateway.repair_runtime_contract(package, knowledge_graph)
        except Exception as exc:
            logger.warning("Runtime contract repair failed: %s", type(exc).__name__)
            return knowledge_graph
        if not isinstance(repair, dict):
            return knowledge_graph
        merged = dict(knowledge_graph)
        for key in ("branches", "endings"):
            if key in repair:
                merged[key] = repair[key]
        return normalize_knowledge_graph(merged)

    async def _create_draft_version(
        self,
        *,
        scenario_id: str,
        scenario_title: str,
        knowledge_graph: Any,
        combined_package: ContentPackage,
        source_rows: list[dict[str, Any]],
        created_by: str,
        update_scenario: bool,
        preserve_source_history: bool = False,
    ) -> dict[str, Any]:
        if not isinstance(knowledge_graph, dict):
            knowledge_graph = {}
        else:
            knowledge_graph = dict(knowledge_graph)
        if not preserve_source_history:
            self._persist_multimodal_transcripts(source_rows, knowledge_graph)
        knowledge_graph.pop("source_part_texts", None)
        part_rows = self._load_version_parts(source_rows)
        solo_adventure = extract_solo_adventure([
            _rag_part(row) for row in part_rows
        ])
        detected_solo_adventure = solo_adventure["detected"]
        if detected_solo_adventure:
            if solo_adventure["integrity"]["is_valid"]:
                knowledge_graph["solo_adventure"] = solo_adventure
            else:
                knowledge_graph["solo_adventure"] = {
                    "root_node_id": solo_adventure["root_node_id"],
                    "nodes": [],
                    "integrity": solo_adventure["integrity"],
                }
        quality_report = QualityReportGenerator().evaluate(knowledge_graph).model_dump(
            mode="json"
        )
        prep_package = _build_prep_package(
            scenario_title,
            knowledge_graph,
            quality_report,
            part_rows,
        )
        scenario_version_id = str(uuid.uuid4())
        version_row = self.conn.execute(
            "SELECT COALESCE(MAX(version_number), 0) + 1 AS next_version "
            "FROM scenario_versions WHERE scenario_id = %s",
            (scenario_id,),
        ).fetchone()
        version_number = int(version_row["next_version"])

        with self.conn.transaction() as tx:
            tx.execute(
                """
                INSERT INTO scenario_versions (
                    scenario_version_id, scenario_id, version_number, status,
                    knowledge_graph, quality_report, prep_package, created_by
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    scenario_version_id, scenario_id, version_number, "draft",
                    json.dumps(knowledge_graph, ensure_ascii=False),
                    json.dumps(quality_report, ensure_ascii=False),
                    json.dumps(prep_package, ensure_ascii=False),
                    created_by,
                ),
            )
            for row in source_rows:
                tx.execute(
                    """
                    INSERT INTO scenario_version_sources (
                        scenario_version_id, source_document_id, ordinal
                    ) VALUES (%s, %s, %s)
                    """,
                    (
                        scenario_version_id,
                        row["source_document_id"],
                        row["ordinal"],
                    ),
                )
                if not preserve_source_history:
                    tx.execute(
                        "UPDATE source_documents SET status = 'ready', updated_at = NOW() "
                        "WHERE source_document_id = %s",
                        (row["source_document_id"],),
                    )
                    tx.execute(
                        """
                        UPDATE import_jobs
                        SET status = 'complete', progress = 100,
                            error_message = NULL, diagnostics = %s, updated_at = NOW()
                        WHERE job_id = %s
                        """,
                        (
                            json.dumps({
                                "import_batch_id": row.get("import_batch_id") or "",
                                "scenario_version_id": scenario_version_id,
                                "requires_multimodal": combined_package.requires_multimodal,
                                "part_count": len(part_rows),
                            }, ensure_ascii=False),
                            row["job_id"],
                        ),
                    )
            if update_scenario:
                tx.execute(
                    """
                    UPDATE scenarios
                    SET raw_text = %s, knowledge_graph = %s, quality_report = %s,
                        import_status = 'draft_review', publish_status = 'draft'
                    WHERE scenario_id = %s
                    """,
                    (
                        combined_package.canonical_text,
                        json.dumps(knowledge_graph, ensure_ascii=False),
                        json.dumps(quality_report, ensure_ascii=False),
                        scenario_id,
                    ),
                )
            if detected_solo_adventure:
                self._ensure_solo_character_template(tx, scenario_id)
            self._bind_published_base_rules(tx, scenario_version_id)

        content_projection = ContentProjectionService(self.conn).rebuild(
            scenario_version_id,
            knowledge_graph,
            requested_by=created_by,
        )
        try:
            from .asset_binding import ScenarioAssetBindingService

            binding_service = ScenarioAssetBindingService(
                self.conn,
                asset_root=self.asset_root,
                gateway=self.gateway,
            )
            binding_service.materialize_source_images(
                scenario_id,
                source_rows,
                self.storage_root,
            )
            await binding_service.generate_bindings(scenario_version_id)
        except Exception as exc:
            logger.exception(
                "Scenario asset binding generation failed for version %s",
                scenario_version_id,
            )
            diagnostic = {
                "code": "asset_binding_generation_failed",
                "message": f"{type(exc).__name__}: {exc}",
                "target_type": "asset_binding",
                "target_key": "source_images",
            }
            knowledge_graph.setdefault("runtime_diagnostics", []).append(diagnostic)
            with self.conn.transaction() as tx:
                tx.execute(
                    "UPDATE scenario_versions SET knowledge_graph = %s "
                    "WHERE scenario_version_id = %s",
                    (
                        json.dumps(knowledge_graph, ensure_ascii=False),
                        scenario_version_id,
                    ),
                )
                if update_scenario:
                    tx.execute(
                        "UPDATE scenarios SET knowledge_graph = %s WHERE scenario_id = %s",
                        (json.dumps(knowledge_graph, ensure_ascii=False), scenario_id),
                    )
        runtime_package = ModuleCompiler(self.conn).compile(
            scenario_version_id,
            requested_by=created_by,
        )

        return {
            "scenario_id": scenario_id,
            "scenario_version_id": scenario_version_id,
            "version_number": version_number,
            "status": "draft_ready",
            "job_ids": [row["job_id"] for row in source_rows if row.get("job_id")],
            "source_document_count": len(source_rows),
            "part_count": len(part_rows),
            "requires_multimodal": combined_package.requires_multimodal,
            "quality_report": quality_report,
            "prep_summary": _host_prep_projection(prep_package, quality_report),
            "content_projection": content_projection,
            "runtime_package": {
                "runtime_package_version_id": runtime_package["runtime_package_version_id"],
                "package_version_number": runtime_package["package_version_number"],
                "gate_status": runtime_package["gate_status"],
                "quality_exceptions": runtime_package["quality_exceptions"],
            },
        }

    def _persist_multimodal_transcripts(
        self,
        source_rows: list[dict[str, Any]],
        knowledge_graph: dict[str, Any],
    ) -> None:
        document_ids = [row["source_document_id"] for row in source_rows]
        if not document_ids:
            return
        placeholders = ",".join(["%s"] * len(document_ids))
        image_rows = self.conn.execute(
            f"""
            SELECT sp.source_part_id, sp.ordinal, sp.anchor, sd.source_filename
            FROM source_parts sp
            JOIN source_documents sd
              ON sd.source_document_id = sp.source_document_id
            WHERE sp.source_document_id IN ({placeholders})
              AND sp.part_kind = 'image'
            ORDER BY sd.created_at, sp.ordinal
            """,
            tuple(document_ids),
        ).fetchall()
        if not image_rows:
            return

        transcripts = {}
        raw_transcripts = knowledge_graph.get("source_part_texts")
        if isinstance(raw_transcripts, list):
            for item in raw_transcripts:
                if not isinstance(item, dict):
                    continue
                source_ref = str(item.get("source_ref") or "").strip()
                text = str(item.get("text") or "").strip()
                if source_ref and text:
                    transcripts[source_ref] = text
        fallback_text = _worldbook_search_text(knowledge_graph)

        with self.conn.transaction() as tx:
            for row in image_rows:
                anchor = _json_value(row.get("anchor"))
                local_ref = str(anchor.get("source_ref") or f"part:{row['ordinal']}")
                source_ref = f"{Path(str(row['source_filename'])).name}#{local_ref}"
                transcript = transcripts.get(source_ref) or transcripts.get(local_ref)
                transcript_status = "provider" if transcript else "derived_worldbook"
                if not transcript:
                    transcript = (
                        "该图像未返回独立 OCR，以下为同一导入批次的结构化世界书派生文本：\n"
                        + fallback_text
                    ).strip()
                if not transcript:
                    transcript = f"图像来源：{source_ref}"
                anchor.update({
                    "transcript_status": transcript_status,
                    "transcript_source_ref": source_ref,
                })
                tx.execute(
                    "UPDATE source_parts SET text_content = %s, anchor = %s "
                    "WHERE source_part_id = %s",
                    (
                        transcript[:12000],
                        json.dumps(anchor, ensure_ascii=False),
                        row["source_part_id"],
                    ),
                )

    def _mark_import_failed(
        self,
        scenario_id: str,
        source_rows: list[dict[str, Any]],
        exc: Exception,
        *,
        status: str = "failed",
        update_scenario: bool = True,
    ) -> None:
        error_message = f"{type(exc).__name__}: {exc}"[:1000]
        with self.conn.transaction() as tx:
            if update_scenario:
                tx.execute(
                    "UPDATE scenarios SET import_status = %s WHERE scenario_id = %s",
                    (status, scenario_id),
                )
            for row in source_rows:
                tx.execute(
                    "UPDATE source_documents SET status = %s, updated_at = NOW() "
                    "WHERE source_document_id = %s",
                    (status, row["source_document_id"]),
                )
                tx.execute(
                    """
                    UPDATE import_jobs
                    SET status = %s, error_message = %s, updated_at = NOW()
                    WHERE job_id = %s
                    """,
                    (status, error_message, row["job_id"]),
                )

    def _load_version_parts(self, source_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        document_ids = [row["source_document_id"] for row in source_rows]
        placeholders = ",".join(["%s"] * len(document_ids))
        return self.conn.execute(
            f"""
            SELECT sp.source_part_id, sp.source_document_id, sp.ordinal,
                   sp.part_kind, sp.page_number, sp.text_content, sp.mime_type,
                   sp.anchor, sd.source_filename
            FROM source_parts sp
            JOIN source_documents sd
              ON sd.source_document_id = sp.source_document_id
            WHERE sp.source_document_id IN ({placeholders})
            ORDER BY sd.created_at, sp.ordinal
            """,
            tuple(document_ids),
        ).fetchall()

    def _bind_published_base_rules(self, tx, scenario_version_id: str) -> None:
        tx.execute(
            """
            INSERT INTO scenario_rule_bindings (
                scenario_version_id, rule_set_version_id, priority
            )
            SELECT %s, rsv.rule_set_version_id, 100
            FROM rule_set_versions rsv
            JOIN rule_sets rs ON rs.rule_set_id = rsv.rule_set_id
            WHERE rs.system = 'coc7' AND rs.is_base = TRUE
              AND rs.status = 'published' AND rsv.status = 'published'
            ON CONFLICT (scenario_version_id, rule_set_version_id) DO NOTHING
            """,
            (scenario_version_id,),
        )

    def _ensure_solo_character_template(self, tx, scenario_id: str) -> None:
        existing = tx.execute(
            "SELECT 1 FROM character_templates WHERE scenario_id = %s LIMIT 1",
            (scenario_id,),
        ).fetchone()
        if existing:
            return
        tx.execute(
            """
            INSERT INTO character_templates (
                template_id, scenario_id, name, occupation, background, age,
                gender, attributes, skills, backstory
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                f"{scenario_id}-solo-investigator",
                scenario_id,
                "独行调查员",
                "旅行者",
                "可在开局前编辑的默认调查员。",
                30,
                "",
                json.dumps({
                    "str": 50,
                    "con": 50,
                    "pow": 50,
                    "dex": 50,
                    "app": 50,
                    "siz": 50,
                    "int": 60,
                    "edu": 60,
                    "luck": 50,
                }, ensure_ascii=False),
                json.dumps({
                    "侦查": 50,
                    "聆听": 40,
                    "图书馆使用": 40,
                    "心理学": 30,
                    "闪避": 25,
                }, ensure_ascii=False),
                json.dumps({
                    "initial_inventory": [
                        {
                            "name": "行李箱",
                            "description": "旅行随身行李。",
                            "quantity": 1,
                            "is_secret": False,
                        },
                        {
                            "name": "笔记本和钢笔",
                            "description": "用于记录见闻。",
                            "quantity": 1,
                            "is_secret": False,
                        },
                    ],
                }, ensure_ascii=False),
            ),
        )


def _build_prep_package(
    title: str,
    knowledge_graph: dict[str, Any],
    quality_report: dict[str, Any],
    part_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    scenes = list(knowledge_graph.get("scenes") or [])
    npcs = list(knowledge_graph.get("npcs") or [])
    clues = list(knowledge_graph.get("clues") or [])
    solo_adventure = _json_value(knowledge_graph.get("solo_adventure"))
    solo_integrity = _json_value(solo_adventure.get("integrity"))
    citations = []
    maps = []
    for row in part_rows:
        anchor = _json_value(row.get("anchor"))
        source_ref = str(anchor.get("source_ref") or "")
        if row.get("page_number") is not None:
            source_ref = f"{row.get('source_filename', 'source')}#page={row['page_number']}"
        elif not source_ref:
            source_ref = f"{row.get('source_filename', 'source')}#part={row['ordinal']}"
        citation = {
            "source_part_id": row["source_part_id"],
            "source_ref": source_ref,
            "page_number": row.get("page_number"),
            "anchor": anchor,
        }
        citations.append(citation)
        if row.get("part_kind") == "image":
            maps.append({"source_part_id": row["source_part_id"], "citation": citation})

    return {
        "title": title,
        "summary": (
            knowledge_graph.get("synopsis")
            or (scenes[0].get("description") if scenes else "")
            or title
        ),
        "scenes": scenes,
        "npcs": npcs,
        "clues": clues,
        "maps": maps,
        "timeline": [
            {
                "order": scene.get("order", index + 1),
                "scene": scene.get("name", f"场景 {index + 1}"),
            }
            for index, scene in enumerate(scenes)
        ],
        "recommended_skills": list(knowledge_graph.get("key_skills") or []),
        "rule_basis": list(knowledge_graph.get("rule_citations") or []),
        "quality_risks": list(quality_report.get("issues") or []),
        "solo_adventure": {
            "root_node_id": solo_adventure.get("root_node_id") or "",
            "node_count": solo_integrity.get("node_count", 0),
            "edge_count": solo_integrity.get("edge_count", 0),
            "is_valid": solo_integrity.get("is_valid"),
            "duplicate_node_ids": solo_integrity.get("duplicate_node_ids") or [],
            "missing_target_node_ids": solo_integrity.get("missing_target_node_ids") or [],
        } if solo_adventure else {},
        "citations": citations,
        "review_status": "pending_host_confirmation",
    }


def _host_prep_projection(
    prep_package: dict[str, Any], quality_report: dict[str, Any]
) -> dict[str, Any]:
    return {
        "title": prep_package.get("title", ""),
        "summary": prep_package.get("summary", ""),
        "scene_count": len(prep_package.get("scenes") or []),
        "npc_count": len(prep_package.get("npcs") or []),
        "clue_count": len(prep_package.get("clues") or []),
        "recommended_skills": prep_package.get("recommended_skills") or [],
        "rule_basis": prep_package.get("rule_basis") or [],
        "quality_report": quality_report,
        "solo_adventure": prep_package.get("solo_adventure") or {},
        "citations": prep_package.get("citations") or [],
        "review_status": prep_package.get("review_status", "pending_host_confirmation"),
    }


def _rag_part(row: dict[str, Any]) -> dict[str, Any]:
    filename = Path(str(row.get("source_filename") or "source")).name
    page_number = row.get("page_number")
    source_ref = filename
    if page_number is not None:
        source_ref = f"{filename}#page={page_number}"
    return {
        "source_part_id": row["source_part_id"],
        "text": row.get("text_content") or "",
        "part_kind": row.get("part_kind") or "text",
        "mime_type": row.get("mime_type") or "",
        "page_number": page_number,
        "source_ref": source_ref,
        "anchor": _json_value(row.get("anchor")),
    }


def _json_value(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            return {}
    return {}


def _rag_embedding_metadata(rag: Any) -> tuple[str | None, int | None]:
    embedding = getattr(rag, "embedding", None)
    if embedding is None:
        return None, None
    model_name = str(
        getattr(embedding, "model_name", "")
        or type(embedding).__name__
    )
    raw_dimensions = getattr(embedding, "dimension", None)
    try:
        dimensions = int(raw_dimensions) if raw_dimensions is not None else None
    except (TypeError, ValueError):
        dimensions = None
    return model_name, dimensions


def _needs_runtime_contract_repair(knowledge_graph: dict[str, Any]) -> bool:
    branches = knowledge_graph.get("branches")
    has_cited_branch = isinstance(branches, list) and any(
        isinstance(branch, dict)
        and str(branch.get("from_scene_id") or branch.get("from") or "").strip()
        and str(branch.get("to_scene_id") or branch.get("to") or "").strip()
        and isinstance(branch.get("citation"), dict)
        and bool(
            branch["citation"].get("source_part_id")
            or branch["citation"].get("source_ref")
        )
        for branch in branches
    )
    endings = knowledge_graph.get("endings")
    has_executable_ending = isinstance(endings, list) and any(
        isinstance(ending, dict)
        and str(ending.get("ending_id") or ending.get("id") or "").strip()
        and isinstance(ending.get("citation"), dict)
        and bool(
            ending["citation"].get("source_part_id")
            or ending["citation"].get("source_ref")
        )
        and isinstance(ending.get("completion_conditions"), dict)
        and bool(ending["completion_conditions"])
        for ending in endings
    )
    return not has_cited_branch or not has_executable_ending


def _worldbook_search_text(knowledge_graph: dict[str, Any]) -> str:
    lines = []
    synopsis = str(knowledge_graph.get("synopsis") or "").strip()
    if synopsis:
        lines.append(synopsis)
    for key in ("scenes", "npcs", "clues", "endings"):
        items = knowledge_graph.get(key)
        if not isinstance(items, list):
            continue
        for item in items:
            if not isinstance(item, dict):
                continue
            text = "；".join(
                str(item.get(field) or "").strip()
                for field in (
                    "name", "description", "public_description", "role",
                    "location", "motivation", "type",
                )
                if str(item.get(field) or "").strip()
            )
            if text:
                lines.append(text)
    truth = knowledge_graph.get("truth")
    if isinstance(truth, dict) and truth.get("summary"):
        lines.append(str(truth["summary"]).strip())
    return "\n".join(lines)[:12000]


__all__ = [
    "ScenarioImportFailure",
    "ScenarioImportService",
    "UploadedSource",
    "_host_prep_projection",
    "_json_value",
]
