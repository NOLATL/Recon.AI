"""
FastAPI application entry point.

Uvicorn invocation:
    uvicorn src.api.main:app --reload --port 8000
"""

import os

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from src.core.state_machine import InvalidStateTransition, ReviewPhaseViolation, TerminalStateError
from src.exceptions import SessionNotFound, SnapshotNotFound, FileValidationError, LayerNotReady
from src.api.routes import router as session_router
from src.api.intake_routes import router as intake_router
from src.api.profiling_routes import router as profiling_router
from src.api.preprocessing_routes import router as preprocessing_router
from src.api.deterministic_routes import router as deterministic_router
from src.api.probabilistic_routes import router as probabilistic_router
from src.api.ai_routes import router as ai_router
from src.api.snapshot_routes import router as snapshot_router
from src.api.layer_routes import router as layer_router
from src.api.final_consolidation_routes import router as consolidation_router
from src.api.export_routes import router as export_router
from src.api.override_routes import router as override_router
from src.api.chat_routes import router as chat_router

app = FastAPI(
    title="AI Reconciliation Engine",
    version="0.1.0",
    description=(
        "Forward-only, API-driven reconciliation engine with deterministic authority, "
        "probabilistic augmentation, and AI advisory assistance."
    ),
)

# ---------------------------------------------------------------------------
# CORS — origins come from ALLOWED_ORIGINS (comma-separated); "*" for local dev
# ---------------------------------------------------------------------------
_allowed_origins = [
    o.strip() for o in os.getenv("ALLOWED_ORIGINS", "*").split(",") if o.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    # Wildcard origins cannot be combined with credentials per the CORS spec
    allow_credentials=_allowed_origins != ["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Exception handlers — typed exceptions → consistent HTTP responses
# ---------------------------------------------------------------------------

@app.exception_handler(SessionNotFound)
async def session_not_found_handler(request: Request, exc: SessionNotFound):
    return JSONResponse(status_code=404, content={"detail": str(exc)})


@app.exception_handler(SnapshotNotFound)
async def snapshot_not_found_handler(request: Request, exc: SnapshotNotFound):
    return JSONResponse(status_code=404, content={"detail": str(exc)})


@app.exception_handler(InvalidStateTransition)
async def invalid_transition_handler(request: Request, exc: InvalidStateTransition):
    return JSONResponse(status_code=409, content={"detail": str(exc)})


@app.exception_handler(ReviewPhaseViolation)
async def review_violation_handler(request: Request, exc: ReviewPhaseViolation):
    return JSONResponse(status_code=409, content={"detail": str(exc)})


@app.exception_handler(TerminalStateError)
async def terminal_state_handler(request: Request, exc: TerminalStateError):
    return JSONResponse(status_code=409, content={"detail": str(exc)})


@app.exception_handler(FileValidationError)
async def file_validation_handler(request: Request, exc: FileValidationError):
    return JSONResponse(status_code=422, content={"detail": exc.to_detail()})


@app.exception_handler(LayerNotReady)
async def layer_not_ready_handler(request: Request, exc: LayerNotReady):
    return JSONResponse(status_code=409, content={"detail": str(exc)})


# ---------------------------------------------------------------------------
# Routers
# ---------------------------------------------------------------------------

app.include_router(session_router)
app.include_router(intake_router)
app.include_router(profiling_router)
app.include_router(preprocessing_router)
app.include_router(deterministic_router)
app.include_router(probabilistic_router)
app.include_router(ai_router)
app.include_router(snapshot_router)
app.include_router(layer_router)
app.include_router(consolidation_router)
app.include_router(export_router)
app.include_router(override_router)
app.include_router(chat_router)


@app.get("/health", tags=["health"])
def health_check():
    return {"status": "ok"}
