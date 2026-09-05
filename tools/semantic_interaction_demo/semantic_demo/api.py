from fastapi import FastAPI, HTTPException

from .compiler import SemanticCompiler
from .model_adapter import DemoSemanticModel
from .models import CompileRequest, CompileResponse, ConfirmSemanticRequest

app = FastAPI(title="Semantic Interaction Demo", version="1.0.0")
compiler = SemanticCompiler(DemoSemanticModel())


@app.post("/semantic/compile", response_model=CompileResponse)
def compile_semantics(request: CompileRequest) -> CompileResponse:
    try:
        return compiler.compile(request)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/semantic/confirm", response_model=CompileResponse)
def confirm_semantics(request: ConfirmSemanticRequest) -> CompileResponse:
    try:
        return compiler.confirm(request)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
