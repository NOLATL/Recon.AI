"""
Export endpoint — Phase 8: final_consolidated → finalized

Flow:
  1. Guard: session exists
  2. Guard: state is exactly FINAL_CONSOLIDATED
     - If already FINALIZED → specific 409 "already finalized" message
     - Any other wrong state → generic 409 "requires final_consolidated"
  3. Pull matching buckets, residual, AI meta, and consolidation from runtime (read-only)
  4. Run export (pure function — generates files, no side effects on runtime)
  5. Write export metadata BEFORE state advance:
       - rm.write_export_meta(...) — file paths, hashes, timestamp
  6. Advance state to FINALIZED (snapshot fires automatically)
  7. Return ExportResponse

Architecture notes:
- FINALIZED is a terminal state — no further transitions after this endpoint.
- All CSV and PDF file generation occurs in the export service layer.
- Route reads from runtime; service writes to the filesystem only.
- No recomputation. This is a pure output generation step.
"""

import io
import os
import zipfile

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse, StreamingResponse

import src.core.runtime_manager as rm
from src.core.state_machine import ReconciliationState
from src.schemas.export import ExportFile, ExportResponse
from src.schemas.intake import SnapshotInfo
from src.services.export_service import run_export

router = APIRouter(prefix="/reconciliation", tags=["export"])


@router.post("/{session_id}/export", response_model=ExportResponse)
def run_finalization_export(session_id: str):
    """
    Generate all output files and advance session from
    'final_consolidated' to 'finalized'.

    Generates:
      - final_matches.csv          : All accepted matches
      - residual_unmatched_gl.csv  : Unmatched GL records
      - residual_unmatched_sub.csv : Unmatched subledger records
      - rejected_matches.csv       : All rejected matches
      - audit_log.csv              : Complete audit trail
      - reconciliation_report.pdf  : Executive summary and statistics

    FINALIZED is a terminal state — no further transitions are possible.

    Returns 409 if already FINALIZED.
    Returns 409 if session is in any other non-final_consolidated state.
    """
    # --- Guard: session existence ---
    if not rm.session_exists(session_id):
        raise HTTPException(status_code=404, detail=f"Session not found: {session_id}")

    current = rm.get_current_state(session_id)

    # --- Guard: already finalized ---
    if current == ReconciliationState.FINALIZED:
        raise HTTPException(
            status_code=409,
            detail=(
                "Session is already in 'finalized' state. "
                "Export has already been completed."
            ),
        )

    # --- Guard: correct pre-condition state ---
    if current != ReconciliationState.FINAL_CONSOLIDATED:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Export requires state 'final_consolidated'. "
                f"Current state is '{current.value}'."
            ),
        )

    # --- Pull inputs from runtime (read-only) ---
    runtime      = rm.get_runtime(session_id)
    matching     = runtime["matching"]
    pool         = runtime.get("residual_pool", {})

    det_matches  = matching.get("deterministic",  [])
    prob_matches = matching.get("probabilistic",  [])
    ai_final     = [m for m in matching.get("final", []) if "ai_confidence_score" in m]
    ai_suggested = matching.get("ai_suggested",   [])
    rejected     = matching.get("rejected",       [])

    residual_gl  = pool.get("gl",        None)
    residual_sub = pool.get("subledger", None)

    ai_meta       = runtime.get("ai_suggested_meta", {})
    consolidation = runtime.get("consolidation",     {})
    raw_data      = runtime.get("raw_data",          {})
    clean_data    = runtime.get("clean_data",        {})
    snapshots     = runtime.get("snapshots",         {})

    # --- Run export (pure, writes files to temp dir) ---
    manifest = run_export(
        det_matches=   det_matches,
        prob_matches=  prob_matches,
        ai_final=      ai_final,
        ai_suggested=  ai_suggested,
        rejected=      rejected,
        residual_gl=   residual_gl,
        residual_sub=  residual_sub,
        ai_meta=       ai_meta,
        consolidation= consolidation,
        raw_data=      raw_data,
        clean_data=    clean_data,
        snapshots=     snapshots,
        matching=      matching,
        session_id=    session_id,
    )

    # --- Write export metadata BEFORE state advance so snapshot captures it ---
    rm.write_export_meta(session_id, {
        "export_dir":  manifest.export_dir,
        "exported_at": manifest.exported_at,
        "files": [
            {
                "filename":   f.filename,
                "path":       f.path,
                "sha256":     f.sha256,
                "size_bytes": f.size_bytes,
            }
            for f in manifest.files
        ],
    })

    # --- Advance state to FINALIZED (snapshot fires automatically) ---
    try:
        rm.advance_state(
            session_id,
            ReconciliationState.FINALIZED,
            triggered_by="export",
        )
    except Exception as exc:
        raise HTTPException(status_code=409, detail=str(exc))

    # --- Build response ---
    snapshots = rm.get_session_snapshots(session_id)
    latest    = snapshots[-1] if snapshots else {}

    return ExportResponse(
        session_id=  session_id,
        state=       rm.get_current_state(session_id).value,
        export_dir=  manifest.export_dir,
        exported_at= manifest.exported_at,
        files=[
            ExportFile(
                filename=   f.filename,
                path=       f.path,
                sha256=     f.sha256,
                size_bytes= f.size_bytes,
            )
            for f in manifest.files
        ],
        snapshot=SnapshotInfo(
            key=            latest.get("pre_transition_state", ""),
            integrity_hash= latest.get("integrity_hash", ""),
        ),
    )


@router.get("/{session_id}/export", response_model=ExportResponse)
def get_export_manifest(session_id: str):
    """
    Return the stored export manifest for a finalized session.

    Allows the frontend to reload file metadata (e.g. after navigation or page refresh)
    without re-running the export.  Only available once the session is FINALIZED.
    """
    if not rm.session_exists(session_id):
        raise HTTPException(status_code=404, detail=f"Session not found: {session_id}")

    current = rm.get_current_state(session_id)
    if current != ReconciliationState.FINALIZED:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Export manifest is only available in 'finalized' state. "
                f"Current state is '{current.value}'."
            ),
        )

    runtime     = rm.get_runtime(session_id)
    export_meta = runtime.get("export", {})
    if not export_meta:
        raise HTTPException(status_code=404, detail="No export metadata found for this session.")

    snapshots = rm.get_session_snapshots(session_id)
    latest    = snapshots[-1] if snapshots else {}

    return ExportResponse(
        session_id=  session_id,
        state=       current.value,
        export_dir=  export_meta.get("export_dir",  ""),
        exported_at= export_meta.get("exported_at", ""),
        files=[
            ExportFile(
                filename=   f["filename"],
                path=       f["path"],
                sha256=     f["sha256"],
                size_bytes= f["size_bytes"],
            )
            for f in export_meta.get("files", [])
        ],
        snapshot=SnapshotInfo(
            key=            latest.get("pre_transition_state", ""),
            integrity_hash= latest.get("integrity_hash", ""),
        ),
    )


@router.get("/{session_id}/export/files/{filename}")
def download_export_file(session_id: str, filename: str):
    """
    Serve a single exported file for browser download.

    Only files that appear in this session's export manifest can be served,
    preventing path-traversal attacks.  Requires FINALIZED state.
    """
    if not rm.session_exists(session_id):
        raise HTTPException(status_code=404, detail=f"Session not found: {session_id}")

    current = rm.get_current_state(session_id)
    if current != ReconciliationState.FINALIZED:
        raise HTTPException(
            status_code=409,
            detail="File downloads are only available in 'finalized' state.",
        )

    runtime     = rm.get_runtime(session_id)
    export_meta = runtime.get("export", {})
    manifest_files = export_meta.get("files", [])

    # Validate filename against manifest (prevents path traversal)
    entry = next((f for f in manifest_files if f["filename"] == filename), None)
    if entry is None:
        raise HTTPException(
            status_code=404,
            detail=f"File '{filename}' is not part of this session's export.",
        )

    path = entry["path"]
    if not os.path.exists(path):
        raise HTTPException(
            status_code=410,
            detail=f"File has been removed from the server: {filename}",
        )

    media_type = "application/pdf" if filename.endswith(".pdf") else "text/csv"
    return FileResponse(
        path=       path,
        filename=   filename,
        media_type= media_type,
    )


@router.get("/{session_id}/export/zip")
def download_export_zip(
    session_id: str,
    files: str = Query(..., description="Comma-separated filenames to include in the ZIP"),
):
    """
    Stream a ZIP archive containing the requested exported files.

    Only filenames present in this session's export manifest are allowed,
    preventing path-traversal attacks.  Requires FINALIZED state.
    """
    if not rm.session_exists(session_id):
        raise HTTPException(status_code=404, detail=f"Session not found: {session_id}")

    current = rm.get_current_state(session_id)
    if current != ReconciliationState.FINALIZED:
        raise HTTPException(
            status_code=409,
            detail="ZIP downloads are only available in 'finalized' state.",
        )

    runtime        = rm.get_runtime(session_id)
    export_meta    = runtime.get("export", {})
    manifest_files = export_meta.get("files", [])
    manifest_map   = {f["filename"]: f["path"] for f in manifest_files}

    requested = [fn.strip() for fn in files.split(",") if fn.strip()]
    if not requested:
        raise HTTPException(status_code=400, detail="No filenames provided.")

    # Validate every requested filename against the manifest.
    for fn in requested:
        if fn not in manifest_map:
            raise HTTPException(
                status_code=404,
                detail=f"File '{fn}' is not part of this session's export.",
            )

    # Build an in-memory ZIP.
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        for fn in requested:
            path = manifest_map[fn]
            if not os.path.exists(path):
                raise HTTPException(
                    status_code=410,
                    detail=f"File has been removed from the server: {fn}",
                )
            zf.write(path, arcname=fn)
    buf.seek(0)

    zip_name = f"recon_export_{session_id[:8]}.zip"
    return StreamingResponse(
        buf,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{zip_name}"'},
    )
