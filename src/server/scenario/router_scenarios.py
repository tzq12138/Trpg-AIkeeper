import uuid
import json
import logging
from pathlib import Path
from fastapi import APIRouter, Request, HTTPException, UploadFile, File, Form
from fastapi.responses import FileResponse
from .quality import QualityReportGenerator
from .import_service import (
    ScenarioImportFailure,
    ScenarioImportService,
    UploadedSource,
    _host_prep_projection,
    _json_value,
)
from .module_compiler import ModuleCompiler, ModuleCompilerError
from .review_service import ScenarioReviewError, ScenarioReviewService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/scenarios")


def _require_host_or_admin(request: Request) -> dict:
    from ..router_auth import get_account_from_token

    account = get_account_from_token(request)
    if not account:
        raise HTTPException(401, "请先登录")
    if account.get("role") not in {"admin", "host"}:
        raise HTTPException(403, "仅房主或管理员可访问")
    return dict(account)


def _require_admin_account(request: Request) -> dict:
    account = _require_host_or_admin(request)
    if account.get("role") != "admin":
        raise HTTPException(403, "仅管理员可导入剧本")
    return account


def _import_service(request: Request) -> ScenarioImportService:
    storage_root = getattr(request.app.state, "scenario_storage_root", None)
    asset_root = getattr(request.app.state, "scenario_asset_root", None)
    configured_limits = getattr(request.app.state, "scenario_import_limits", {})
    if not isinstance(configured_limits, dict):
        configured_limits = {}
    limit_kwargs = {
        key: value
        for key, value in configured_limits.items()
        if key in {"max_source_files", "max_file_bytes", "max_total_bytes"}
        and isinstance(value, int)
        and value > 0
    }
    return ScenarioImportService(
        request.app.state.db,
        gateway=getattr(request.app.state, "gateway", None),
        rag=getattr(request.app.state, "rag", None),
        storage_root=Path(storage_root) if storage_root else None,
        asset_root=Path(asset_root) if asset_root else None,
        **limit_kwargs,
    )


def _module_compiler(request: Request) -> ModuleCompiler:
    return ModuleCompiler(request.app.state.db)


def _review_service(request: Request) -> ScenarioReviewService:
    return ScenarioReviewService(
        request.app.state.db,
        gateway=getattr(request.app.state, "gateway", None),
        rag=getattr(request.app.state, "rag", None),
    )


def _verify_scenario_version(conn, scenario_id: str, scenario_version_id: str) -> None:
    row = conn.execute(
        "SELECT 1 FROM scenario_versions WHERE scenario_id = %s AND scenario_version_id = %s",
        (scenario_id, scenario_version_id),
    ).fetchone()
    if not row:
        raise HTTPException(404, "scenario version not found")


def _module_compiler_error(exc: ModuleCompilerError) -> HTTPException:
    code = str(exc)
    status_code = 404 if code in {
        "runtime_package_not_found",
        "scenario_version_not_found",
        "quality_exception_not_found",
    } else 409
    return HTTPException(status_code, code)


def _review_error(exc: ScenarioReviewError) -> HTTPException:
    code = str(exc)
    if code in {"scenario_version_not_found", "scenario_review_draft_not_found"}:
        return HTTPException(404, code)
    if code.startswith("review_patch_"):
        return HTTPException(400, code)
    return HTTPException(409, code)


async def _run_import(
    request: Request,
    uploads: list[UploadedSource],
    *,
    title: str,
    license_type: str,
    license_ref: str | None,
    created_by: str,
    scenario_id: str | None = None,
) -> dict:
    try:
        return await _import_service(request).import_sources(
            uploads,
            title=title,
            license_type=license_type,
            license_ref=license_ref,
            created_by=created_by,
            scenario_id=scenario_id,
        )
    except ScenarioImportFailure as exc:
        raise HTTPException(exc.status_code, exc.detail) from exc


@router.get("/available")
async def list_available_scenarios(request: Request):
    """List scenarios that a host or admin can use to create rooms.
    Excludes blocked scenarios. Includes quality diagnostics."""
    from ..router_auth import get_account_from_token
    account = get_account_from_token(request)
    if not account:
        raise HTTPException(401, "请先登录")
    if account.get("role") not in ("admin", "host"):
        raise HTTPException(403, "仅房主或管理员可访问")
    conn = request.app.state.db
    rows = conn.execute(
        "SELECT scenario_id, title, import_status, quality_report, publish_status, "
        "published_version_id, created_at FROM scenarios "
        "WHERE publish_status = 'published' AND published_version_id IS NOT NULL "
        "ORDER BY created_at DESC"
    ).fetchall()
    result = []
    for r in rows:
        quality_level = "unknown"
        completeness = 0.0
        if r.get("quality_report"):
            qr = r["quality_report"]
            if isinstance(qr, str):
                try:
                    qr = json.loads(qr)
                except json.JSONDecodeError:
                    qr = {}
            quality_level = qr.get("level", "unknown")
            completeness = qr.get("completeness", 0.0)
        # Exclude blocked scenarios from available list
        if quality_level == "blocked":
            continue
        entry = {
            "scenario_id": r["scenario_id"],
            "title": r["title"],
            "status": r["import_status"],
            "quality_level": quality_level,
            "completeness": completeness,
            "created_at": str(r.get("created_at", "")),
        }
        # Add risk warning for highRisk scenarios
        if quality_level == "highRisk":
            entry["risk_warning"] = "该剧本质量评级为高风险，开房需显式确认"
        elif quality_level == "warning":
            entry["risk_warning"] = "该剧本存在质量警告"
        result.append(entry)
    return result


@router.get("/{scenario_id}/templates")
async def list_scenario_character_templates(request: Request, scenario_id: str):
    conn = request.app.state.db
    scenario = conn.execute(
        "SELECT 1 FROM scenarios WHERE scenario_id = %s",
        (scenario_id,),
    ).fetchone()
    if not scenario:
        raise HTTPException(404, "scenario not found")
    rows = conn.execute(
        """
        SELECT template_id, name, occupation, background, age, gender,
               attributes, skills
        FROM character_templates
        WHERE scenario_id = %s
        ORDER BY created_at, template_id
        """,
        (scenario_id,),
    ).fetchall()
    return [
        {
            "template_id": row["template_id"],
            "name": row.get("name") or "",
            "occupation": row.get("occupation") or "",
            "background": row.get("background") or "",
            "age": int(row.get("age") or 25),
            "gender": row.get("gender") or "",
            "attributes": _json_value(row.get("attributes")) or {},
            "skills": _json_value(row.get("skills")) or {},
        }
        for row in rows
    ]


@router.post("/import")
async def import_scenario_sources(
    request: Request,
    files: list[UploadFile] = File(...),
    title: str = Form(""),
    license_type: str = Form("authorized"),
    license_ref: str | None = Form(None),
    scenario_id: str | None = Form(None),
):
    account = _require_admin_account(request)
    uploads = [
        UploadedSource(
            filename=file.filename or "source",
            content=await file.read(),
            mime_type=file.content_type or "",
        )
        for file in files
    ]
    return await _run_import(
        request,
        uploads,
        title=title,
        license_type=license_type,
        license_ref=license_ref,
        created_by=account.get("account_id", "unknown"),
        scenario_id=scenario_id,
    )


@router.post("/import-pdf")
async def import_pdf(request: Request, file: UploadFile = File(...)):
    """Upload and structure a scenario PDF. Admin-only."""
    from ..router_auth import get_account_from_token
    account = get_account_from_token(request)
    if not account:
        raise HTTPException(401, "请先登录")
    if account.get("role") != "admin":
        raise HTTPException(403, "仅管理员可导入剧本")

    if not file.filename or not file.filename.endswith(".pdf"):
        raise HTTPException(400, "Only PDF files supported")

    content = await file.read()
    return await _run_import(
        request,
        [UploadedSource(
            filename=file.filename,
            content=content,
            mime_type=file.content_type or "application/pdf",
        )],
        title=file.filename,
        license_type="authorized",
        license_ref=None,
        created_by=account.get("account_id", "unknown"),
        scenario_id=None,
    )

@router.get("/import-jobs/{job_id}")
async def get_import_status(request: Request, job_id: str):
    account = _require_host_or_admin(request)
    conn = request.app.state.db
    job = conn.execute(
        "SELECT job_id, source_document_id, scenario_id, status, progress, "
        "error_message, diagnostics, created_at, updated_at "
        "FROM import_jobs WHERE job_id = %s",
        (job_id,),
    ).fetchone()
    if job:
        result = dict(job)
        result["diagnostics"] = _json_value(result.get("diagnostics"))
        result["created_at"] = str(result.get("created_at", ""))
        result["updated_at"] = str(result.get("updated_at", ""))
        if account.get("role") != "admin":
            result.pop("error_message", None)
        return result
    scenario = conn.execute(
        "SELECT scenario_id, import_status FROM scenarios WHERE scenario_id = %s",
        (job_id,),
    ).fetchone()
    if scenario:
        return {"scenario_id": scenario["scenario_id"], "status": scenario["import_status"]}
    raise HTTPException(404, "Import job not found")


@router.post("/import-jobs/{job_id}/retry")
async def retry_import_job(request: Request, job_id: str):
    account = _require_admin_account(request)
    try:
        return await _import_service(request).retry_import(
            job_id,
            requested_by=account.get("account_id", "unknown"),
        )
    except ScenarioImportFailure as exc:
        raise HTTPException(exc.status_code, exc.detail) from exc


@router.get("/{scenario_id}/versions")
async def list_scenario_versions(request: Request, scenario_id: str):
    account = _require_host_or_admin(request)
    scenario = request.app.state.db.execute(
        "SELECT published_version_id FROM scenarios WHERE scenario_id = %s",
        (scenario_id,),
    ).fetchone()
    if not scenario:
        raise HTTPException(404, "剧本不存在")
    rows = request.app.state.db.execute(
        """
        SELECT scenario_version_id, version_number, status, quality_report,
               rag_index_version, created_by, created_at, reviewed_by,
               reviewed_at, review_notes, published_at
        FROM scenario_versions
        WHERE scenario_id = %s
        ORDER BY version_number DESC
        """,
        (scenario_id,),
    ).fetchall()
    result = []
    for row in rows:
        item = {
            "scenario_version_id": row["scenario_version_id"],
            "version_number": row["version_number"],
            "status": row["status"],
            "created_at": str(row.get("created_at") or ""),
            "reviewed_at": str(row.get("reviewed_at") or ""),
            "published_at": str(row.get("published_at") or ""),
            "is_active": row["scenario_version_id"] == scenario.get("published_version_id"),
        }
        if account.get("role") == "admin":
            item.update({
                "quality_report": _json_value(row.get("quality_report")),
                "rag_index_version": row.get("rag_index_version"),
                "created_by": row.get("created_by"),
                "reviewed_by": row.get("reviewed_by"),
                "review_notes": _json_value(row.get("review_notes")),
            })
        result.append(item)
    return result


@router.get("/{scenario_id}/versions/{scenario_version_id}/prep")
async def get_prep_package(
    request: Request, scenario_id: str, scenario_version_id: str
):
    account = _require_host_or_admin(request)
    row = request.app.state.db.execute(
        """
        SELECT sv.status, sv.quality_report, sv.prep_package, s.title
        FROM scenario_versions sv
        JOIN scenarios s ON s.scenario_id = sv.scenario_id
        WHERE sv.scenario_id = %s AND sv.scenario_version_id = %s
        """,
        (scenario_id, scenario_version_id),
    ).fetchone()
    if not row:
        raise HTTPException(404, "剧本版本不存在")
    quality_report = _json_value(row.get("quality_report"))
    prep_package = _json_value(row.get("prep_package"))
    if account.get("role") == "admin":
        return {
            "scenario_id": scenario_id,
            "scenario_version_id": scenario_version_id,
            "status": row["status"],
            "quality_report": quality_report,
            "prep_package": prep_package,
        }
    return {
        "scenario_id": scenario_id,
        "scenario_version_id": scenario_version_id,
        "status": row["status"],
        **_host_prep_projection(prep_package, quality_report),
    }


@router.get("/{scenario_id}/versions/{scenario_version_id}/review-workbench")
async def get_review_workbench(
    request: Request, scenario_id: str, scenario_version_id: str
):
    _require_admin_account(request)
    try:
        return _review_service(request).get_workbench(scenario_id, scenario_version_id)
    except ScenarioReviewError as exc:
        raise _review_error(exc) from exc


@router.get("/{scenario_id}/versions/{scenario_version_id}/review-sources/{source_document_id}")
async def get_review_source_document(
    request: Request,
    scenario_id: str,
    scenario_version_id: str,
    source_document_id: str,
):
    _require_admin_account(request)
    row = request.app.state.db.execute(
        """
        SELECT sd.source_filename, sd.mime_type, sd.storage_path
        FROM scenario_version_sources svs
        JOIN source_documents sd ON sd.source_document_id = svs.source_document_id
        WHERE svs.scenario_version_id = %s
          AND svs.source_document_id = %s
          AND sd.scenario_id = %s
        """,
        (scenario_version_id, source_document_id, scenario_id),
    ).fetchone()
    if not row:
        raise HTTPException(404, "review source not found")
    storage_root = _import_service(request).storage_root.resolve()
    source_path = (storage_root / Path(str(row.get("storage_path") or ""))).resolve()
    if not source_path.is_relative_to(storage_root) or not source_path.is_file():
        raise HTTPException(404, "review source unavailable")
    return FileResponse(
        source_path,
        media_type=str(row.get("mime_type") or "application/octet-stream"),
        filename=str(row.get("source_filename") or "source"),
    )


@router.post("/{scenario_id}/versions/{scenario_version_id}/review-drafts")
async def create_review_draft(
    request: Request, scenario_id: str, scenario_version_id: str
):
    account = _require_admin_account(request)
    try:
        return _review_service(request).create_review_draft(
            scenario_id,
            scenario_version_id,
            created_by=account.get("account_id", "unknown"),
        )
    except ScenarioReviewError as exc:
        raise _review_error(exc) from exc


@router.post("/{scenario_id}/versions/{scenario_version_id}/review-patches")
async def create_review_patch(
    request: Request, scenario_id: str, scenario_version_id: str
):
    account = _require_admin_account(request)
    _verify_scenario_version(request.app.state.db, scenario_id, scenario_version_id)
    body = await request.json()
    try:
        return _review_service(request).add_patch(
            scenario_version_id,
            target_type=str(body.get("target_type") or ""),
            target_key=str(body.get("target_key") or ""),
            payload=body.get("payload") if isinstance(body.get("payload"), dict) else {},
            provenance=str(body.get("provenance") or ""),
            citation=body.get("citation") if isinstance(body.get("citation"), dict) else {},
            rationale=str(body.get("rationale") or ""),
            created_by=account.get("account_id", "unknown"),
        )
    except ScenarioReviewError as exc:
        raise _review_error(exc) from exc


@router.post("/{scenario_id}/versions/{scenario_version_id}/review-issues/resolve")
async def resolve_review_issue(
    request: Request, scenario_id: str, scenario_version_id: str
):
    account = _require_admin_account(request)
    _verify_scenario_version(request.app.state.db, scenario_id, scenario_version_id)
    body = await request.json()
    try:
        return _review_service(request).resolve_issue(
            scenario_version_id,
            issue_id=str(body.get("issue_id") or ""),
            resolution=str(body.get("resolution") or ""),
            rationale=str(body.get("rationale") or ""),
            created_by=account.get("account_id", "unknown"),
        )
    except ScenarioReviewError as exc:
        raise _review_error(exc) from exc


@router.post("/{scenario_id}/versions/{scenario_version_id}/review-rebuild")
async def rebuild_review_draft(
    request: Request, scenario_id: str, scenario_version_id: str
):
    account = _require_admin_account(request)
    _verify_scenario_version(request.app.state.db, scenario_id, scenario_version_id)
    try:
        return _review_service(request).rebuild_review_draft(
            scenario_version_id,
            requested_by=account.get("account_id", "unknown"),
        )
    except ScenarioReviewError as exc:
        raise _review_error(exc) from exc


@router.post("/{scenario_id}/versions/{scenario_version_id}/review-ai/issue")
async def suggest_review_issue_drafts(
    request: Request, scenario_id: str, scenario_version_id: str
):
    _require_admin_account(request)
    body = await request.json()
    try:
        return await _review_service(request).suggest_issue_drafts(
            scenario_id,
            scenario_version_id,
            issue_id=str(body.get("issue_id") or ""),
        )
    except ScenarioReviewError as exc:
        raise _review_error(exc) from exc


@router.post("/{scenario_id}/versions/{scenario_version_id}/review-ai/reread")
async def reread_review_drafts(
    request: Request, scenario_id: str, scenario_version_id: str
):
    _require_admin_account(request)
    try:
        return await _review_service(request).reread_drafts(
            scenario_id,
            scenario_version_id,
        )
    except ScenarioReviewError as exc:
        raise _review_error(exc) from exc


@router.get("/{scenario_id}/versions/{scenario_version_id}/runtime-package")
async def get_runtime_package(
    request: Request, scenario_id: str, scenario_version_id: str
):
    _require_host_or_admin(request)
    _verify_scenario_version(request.app.state.db, scenario_id, scenario_version_id)
    try:
        return _module_compiler(request).preview_latest(scenario_version_id)
    except ModuleCompilerError as exc:
        raise _module_compiler_error(exc) from exc


@router.post("/{scenario_id}/versions/{scenario_version_id}/runtime-package/recompile")
async def recompile_runtime_package(
    request: Request, scenario_id: str, scenario_version_id: str
):
    account = _require_host_or_admin(request)
    _verify_scenario_version(request.app.state.db, scenario_id, scenario_version_id)
    try:
        return _module_compiler(request).compile(
            scenario_version_id,
            requested_by=account.get("account_id", "unknown"),
        )
    except ModuleCompilerError as exc:
        raise _module_compiler_error(exc) from exc


@router.post("/{scenario_id}/versions/{scenario_version_id}/rebuild-from-sources")
async def rebuild_scenario_draft_from_sources(
    request: Request, scenario_id: str, scenario_version_id: str
):
    account = _require_admin_account(request)
    try:
        return await _import_service(request).rebuild_draft_from_sources(
            scenario_id,
            scenario_version_id,
            requested_by=account.get("account_id", "unknown"),
        )
    except ScenarioImportFailure as exc:
        raise HTTPException(exc.status_code, exc.detail) from exc


@router.post("/{scenario_id}/versions/{scenario_version_id}/runtime-package/exceptions/confirm")
async def confirm_runtime_package_exception(
    request: Request, scenario_id: str, scenario_version_id: str
):
    account = _require_host_or_admin(request)
    _verify_scenario_version(request.app.state.db, scenario_id, scenario_version_id)
    body = await request.json()
    runtime_package_version_id = str(body.get("runtime_package_version_id") or "")
    exception_key = str(body.get("exception_key") or "")
    if not runtime_package_version_id or not exception_key:
        raise HTTPException(400, "runtime_package_version_id and exception_key required")
    compiler = _module_compiler(request)
    try:
        preview = compiler.preview(runtime_package_version_id)
        if preview["scenario_version_id"] != scenario_version_id:
            raise HTTPException(404, "runtime package version not found")
        return compiler.confirm_quality_exception(
            runtime_package_version_id,
            exception_key,
            confirmed_by=account.get("account_id", "unknown"),
            note=str(body.get("note") or ""),
        )
    except ModuleCompilerError as exc:
        raise _module_compiler_error(exc) from exc


@router.post("/{scenario_id}/versions/{scenario_version_id}/publish")
async def publish_scenario_version(
    request: Request, scenario_id: str, scenario_version_id: str
):
    account = _require_host_or_admin(request)
    body = await request.json()
    service = _import_service(request)
    try:
        return service.publish_version(
            scenario_id,
            scenario_version_id,
            reviewer=account,
            confirm=body.get("confirm") is True,
            review_notes=str(body.get("review_notes") or ""),
        )
    except ScenarioImportFailure as exc:
        raise HTTPException(exc.status_code, exc.detail) from exc


@router.post("/{scenario_id}/versions/{scenario_version_id}/activate")
async def activate_scenario_version(
    request: Request, scenario_id: str, scenario_version_id: str
):
    _require_host_or_admin(request)
    body = await request.json()
    try:
        return _import_service(request).activate_published_version(
            scenario_id,
            scenario_version_id,
            confirm=body.get("confirm") is True,
        )
    except ScenarioImportFailure as exc:
        raise HTTPException(exc.status_code, exc.detail) from exc


@router.get("/{scenario_id}/quality-report")
async def get_quality_report(request: Request, scenario_id: str):
    conn = request.app.state.db
    scenario = conn.execute(
        "SELECT * FROM scenarios WHERE scenario_id = %s", (scenario_id,)
    ).fetchone()
    if not scenario:
        raise HTTPException(404, "Scenario not found")

    knowledge_graph = {}
    if scenario["knowledge_graph"]:
        try:
            knowledge_graph = json.loads(scenario["knowledge_graph"])
        except json.JSONDecodeError:
            pass
    generator = QualityReportGenerator()
    report = generator.evaluate(knowledge_graph)
    return report.model_dump()


@router.post("/{scenario_id}/create-room")
async def create_room_from_scenario(request: Request, scenario_id: str):
    """Create a room from a scenario. Host or admin required.

    Quality gate:
    - blocked scenarios: rejected (403)
    - highRisk scenarios: require confirm_quality_risk=true in body
    - Admin can override any quality gate
    """
    from ..router_auth import get_account_from_token
    account = get_account_from_token(request)
    if not account:
        raise HTTPException(401, "请先登录")
    role = account.get("role", "")
    if role not in ("admin", "host"):
        raise HTTPException(403, "仅房主或管理员可创建房间")

    conn = request.app.state.db
    scenario = conn.execute(
        "SELECT * FROM scenarios WHERE scenario_id = %s", (scenario_id,)
    ).fetchone()
    if not scenario:
        raise HTTPException(404, "Scenario not found")

    scenario_version_id = scenario.get("published_version_id")
    if scenario.get("publish_status") != "published" or not scenario_version_id:
        raise HTTPException(409, "剧本尚未确认发布，不能开房")
    runtime_package_row = conn.execute(
        "SELECT runtime_package_version_id FROM runtime_package_versions "
        "WHERE scenario_version_id = %s AND gate_status = 'ready' "
        "ORDER BY package_version_number DESC LIMIT 1",
        (scenario_version_id,),
    ).fetchone()
    runtime_package_version_id = (
        str(runtime_package_row["runtime_package_version_id"])
        if runtime_package_row else None
    )

    # Quality gate check
    body = None
    try:
        body = await request.json()
    except Exception:
        body = {}
    quality_level = "unknown"
    if scenario.get("quality_report"):
        qr = scenario["quality_report"]
        if isinstance(qr, str):
            try:
                qr = json.loads(qr)
            except json.JSONDecodeError:
                qr = {}
        quality_level = qr.get("level", "unknown")

    if quality_level == "blocked" and role != "admin":
        raise HTTPException(403, "该剧本质量评级为 blocked，无法创建房间。请联系管理员检查剧本。")
    if quality_level == "highRisk" and role != "admin":
        if body.get("confirm_quality_risk") is not True:
            raise HTTPException(400, "该剧本质量评级为 highRisk，请确认风险后重试 (confirm_quality_risk: true)")

    room_id = str(uuid.uuid4())[:8]
    owner_token = str(uuid.uuid4())
    owner_account_id = account["account_id"]
    conn.execute(
        "INSERT INTO rooms (room_id, scenario_id, scenario_version_id, runtime_package_version_id, "
        "owner_token, owner_account_id) VALUES (%s, %s, %s, %s, %s, %s)",
        (
            room_id,
            scenario_id,
            scenario_version_id,
            runtime_package_version_id,
            owner_token,
            owner_account_id,
        ),
    )
    conn.commit()

    # Write audit event for highRisk/blocked override
    if quality_level in ("highRisk", "blocked") and role == "admin":
        try:
            from ..events.event_log import EventLog
            el = EventLog(conn)
            el.write_event(room_id, "admin_quality_override", {
                "scenario_id": scenario_id,
                "quality_level": quality_level,
                "action": "create_room",
                "admin_account_id": account["account_id"],
            }, audience="system")
        except Exception as e:
            logger.warning("Failed to write quality override audit: %s", e)

    return {
        "room_id": room_id,
        "owner_token": owner_token,
        "status": "lobby",
        "quality_level": quality_level,
        "scenario_version_id": scenario_version_id,
        "runtime_package_version_id": runtime_package_version_id,
    }
