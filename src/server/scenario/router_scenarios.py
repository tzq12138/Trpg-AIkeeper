import uuid
import json
import tempfile
import os
import logging
from fastapi import APIRouter, Request, HTTPException, UploadFile, File
from .pdf_parser import extract_text_from_pdf, is_scanned_pdf, chunk_text
from ..ai.ai_kp import structure_scenario
from .quality import QualityReportGenerator

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/scenarios")


@router.get("/available")
async def list_available_scenarios(request: Request):
    """List scenarios that a host or admin can use to create rooms."""
    from ..router_auth import get_account_from_token
    account = get_account_from_token(request)
    if not account:
        raise HTTPException(401, "请先登录")
    if account.get("role") not in ("admin", "host"):
        raise HTTPException(403, "仅房主或管理员可访问")
    conn = request.app.state.db
    rows = conn.execute(
        "SELECT scenario_id, title, import_status, created_at "
        "FROM scenarios WHERE import_status = 'structured' ORDER BY created_at DESC"
    ).fetchall()
    return [{
        "scenario_id": r["scenario_id"],
        "title": r["title"],
        "status": r["import_status"],
        "created_at": str(r.get("created_at", "")),
    } for r in rows]


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

    conn = request.app.state.db
    content = await file.read()

    # SHA256 dedup — skip re-import of identical PDF
    import hashlib
    sha256_hash = hashlib.sha256(content).hexdigest()
    existing = conn.execute(
        "SELECT scenario_id, title, import_status FROM scenarios WHERE source_sha256 = %s",
        (sha256_hash,)
    ).fetchone()
    if existing:
        return {
            "scenario_id": existing["scenario_id"],
            "status": "already_imported",
            "title": existing["title"],
            "import_status": existing["import_status"],
        }

    scenario_id = str(uuid.uuid4())[:8]

    tmp_path = os.path.join(tempfile.gettempdir(), f"{scenario_id}.pdf")
    with open(tmp_path, "wb") as f:
        f.write(content)

    pages = extract_text_from_pdf(tmp_path)
    if is_scanned_pdf(pages):
        conn.execute(
            "INSERT INTO scenarios (scenario_id, title, import_status) VALUES (%s, %s, %s)",
            (scenario_id, file.filename, "requires_ocr"),
        )
        conn.commit()
        return {"scenario_id": scenario_id, "status": "requires_ocr"}

    full_text = "\n\n".join(p.text for p in pages)
    chunks = chunk_text(pages)

    from ..config import Settings
    settings = Settings.from_env()
    knowledge_graph = None
    gateway = getattr(request.app.state, "gateway", None)
    if gateway:
        try:
            knowledge_graph = await gateway.structure_scenario(full_text)
        except Exception as e:
            logger.warning("Gateway structure_scenario failed: %s", e)
    if not knowledge_graph:
        try:
            knowledge_graph = await structure_scenario(full_text,
                api_key=settings.deepseek_api_key, api_base="https://api.deepseek.com",
                model=settings.deepseek_model)
        except Exception as e:
            logger.warning("AI structuring failed, using mock: %s", e)
            knowledge_graph = await structure_scenario(full_text)

    # Persist original PDF
    import shutil
    scenarios_dir = os.path.join(os.path.dirname(__file__), "..", "..", "..", "data", "scenarios", scenario_id)
    os.makedirs(scenarios_dir, exist_ok=True)
    dest_path = os.path.join(scenarios_dir, "original.pdf")
    shutil.copy2(tmp_path, dest_path)

    conn.execute(
        "INSERT INTO scenarios (scenario_id, title, raw_text, knowledge_graph, import_status, "
        "source_filename, source_sha256, original_file_path) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
        (scenario_id, file.filename, full_text,
         json.dumps(knowledge_graph, ensure_ascii=False), "structured",
         file.filename, sha256_hash, dest_path),
    )
    conn.commit()

    # Persist quality report
    if knowledge_graph:
        try:
            from ..scenario.quality import QualityReportGenerator
            report = QualityReportGenerator.evaluate(knowledge_graph)
            conn.execute(
                "UPDATE scenarios SET quality_report = %s WHERE scenario_id = %s",
                (json.dumps(report.model_dump(), ensure_ascii=False), scenario_id),
            )
            conn.commit()
        except Exception as e:
            logger.warning("Failed to save quality report for %s: %s", scenario_id, e)

    if hasattr(request.app.state, 'rag') and request.app.state.rag and knowledge_graph:
        try:
            request.app.state.rag.index_npc_graph(scenario_id, knowledge_graph)
        except Exception as e:
            logger.warning('NPC RAG indexing failed: %s', e)

    # Build spoiler sensitive index
    try:
        from ..engine.spoiler_guard import SpoilerGuard
        sg = SpoilerGuard(conn)
        sg.build_sensitive_index(scenario_id, knowledge_graph, {})
        logger.info("Spoiler index built for scenario %s", scenario_id)
    except Exception as e:
        logger.warning("Spoiler index build failed for %s: %s", scenario_id, e)

    return {
        "scenario_id": scenario_id,
        "status": "structured",
        "pages": len(pages),
        "chunks": len(chunks),
    }


@router.get("/import-jobs/{job_id}")
async def get_import_status(request: Request, job_id: str):
    conn = request.app.state.db
    scenario = conn.execute(
        "SELECT * FROM scenarios WHERE scenario_id = %s", (job_id,)
    ).fetchone()
    if not scenario:
        raise HTTPException(404, "Import job not found")
    return {
        "scenario_id": scenario["scenario_id"],
        "status": scenario["import_status"],
    }


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
    """Create a room from a scenario. Host or admin required."""
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
    room_id = str(uuid.uuid4())[:8]
    owner_token = str(uuid.uuid4())
    owner_account_id = account["account_id"]
    conn.execute(
        "INSERT INTO rooms (room_id, scenario_id, owner_token, owner_account_id) VALUES (%s, %s, %s, %s)",
        (room_id, scenario_id, owner_token, owner_account_id),
    )
    conn.commit()
    return {"room_id": room_id, "owner_token": owner_token, "status": "lobby"}
