import uuid
import json
import tempfile
import os
import logging
from fastapi import APIRouter, Request, HTTPException, UploadFile, File
from .pdf_parser import extract_text_from_pdf, is_scanned_pdf, chunk_text
from .ai_kp import structure_scenario
from .quality import QualityReportGenerator

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/scenarios")


@router.post("/import-pdf")
async def import_pdf(request: Request, file: UploadFile = File(...)):
    if not file.filename or not file.filename.endswith(".pdf"):
        raise HTTPException(400, "Only PDF files supported")

    conn = request.app.state.db
    scenario_id = str(uuid.uuid4())[:8]

    content = await file.read()
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

    from .config import Settings
    settings = Settings.from_env()
    try:
        knowledge_graph = await structure_scenario(
            full_text,
            api_key=settings.deepseek_api_key,
            api_base="https://api.deepseek.com",
            model=settings.deepseek_model,
        )
    except Exception as e:
        logger.warning(f"AI structuring failed, using mock: {e}")
        knowledge_graph = await structure_scenario(full_text)

    conn.execute(
        "INSERT INTO scenarios (scenario_id, title, raw_text, knowledge_graph, import_status) VALUES (%s, %s, %s, %s, %s)",
        (scenario_id, file.filename, full_text, json.dumps(knowledge_graph, ensure_ascii=False), "structured"),
    )
    conn.commit()

    if hasattr(request.app.state, 'rag') and request.app.state.rag and knowledge_graph:
        try:
            request.app.state.rag.index_npc_graph(scenario_id, knowledge_graph)
        except Exception as e:
            logger.warning('NPC RAG indexing failed: %s', e)

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
    conn = request.app.state.db
    scenario = conn.execute(
        "SELECT * FROM scenarios WHERE scenario_id = %s", (scenario_id,)
    ).fetchone()
    if not scenario:
        raise HTTPException(404, "Scenario not found")
    room_id = str(uuid.uuid4())[:8]
    owner_token = str(uuid.uuid4())
    conn.execute(
        "INSERT INTO rooms (room_id, scenario_id, owner_token) VALUES (%s, %s, %s)",
        (room_id, scenario_id, owner_token),
    )
    conn.commit()
    return {"room_id": room_id, "owner_token": owner_token}
