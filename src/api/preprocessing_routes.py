"""
Preprocessing endpoint — Phase 3: profiled → preprocessed

Flow:
  1. Guard: session exists
  2. Guard: state is exactly PROFILED
     - If already PREPROCESSED → specific 409 "no recomputation" message
     - Any other wrong state → generic 409
  3. Pull raw GL + Subledger DataFrames and config from runtime
  4. Run 3-tier vendor normalization (pure, no side effects on runtime)
  5. Write results to runtime BEFORE state advance:
       - rm.write_vendor_normalization_map()  — authoritative mapping list
       - rm.write_clean_data()                — GL + Subledger with Vendor_Normalized
       - rm.write_preprocessing()             — threshold used, alias version, tier counts
  6. Advance state to PREPROCESSED (snapshot fires automatically inside transition)
  7. Return PreprocessingResponse

Apply vendor overrides:
  POST /{session_id}/preprocess/vendor_overrides — apply manual overrides to
  Vendor_Normalized in clean_data. Keys: original GL vendor_name for GL rows;
  "__sub__" + subledger vendor_name for Sub rows. Used for matching and output;
  vendor_name (original) is preserved for display.
"""

import pandas as pd
from fastapi import APIRouter, HTTPException

import src.core.runtime_manager as rm
from src.core.state_machine import InvalidStateTransition, ReconciliationState
from src.schemas.preprocessing import (
    NormalizationEntrySchema,
    NormalizationSummary,
    PreprocessingResponse,
    VendorOverridesRequest,
)
from src.schemas.intake import SnapshotInfo
from src.services.vendor_normalization import run_normalization

router = APIRouter(prefix="/reconciliation", tags=["preprocessing"])


def _normalized_dist(df: "pd.DataFrame", top_n: int = 15) -> tuple[dict, dict]:
    """Return (row_dist, amt_dist) keyed by Vendor_Normalized."""
    if df is None or df.empty or "Vendor_Normalized" not in df.columns:
        return {}, {}
    row_dist = df["Vendor_Normalized"].value_counts().head(top_n).astype(int).to_dict()
    if "amount" in df.columns:
        amounts = pd.to_numeric(df["amount"], errors="coerce")
        temp = pd.DataFrame({"vendor": df["Vendor_Normalized"], "amount": amounts}).dropna()
        amt_dist = (
            temp.groupby("vendor")["amount"].sum().abs().nlargest(top_n).apply(float).to_dict()
        )
    else:
        amt_dist = {}
    return row_dist, amt_dist


@router.get("/{session_id}/preprocess", response_model=PreprocessingResponse)
def get_preprocess(session_id: str):
    """
    Return stored preprocessing results for a session that is already preprocessed
    (or further along the pipeline).  Allows the frontend to reload the vendor
    normalization map after a page refresh without re-running preprocessing.

    Returns 409 if the session has not yet been preprocessed.
    """
    if not rm.session_exists(session_id):
        raise HTTPException(status_code=404, detail=f"Session not found: {session_id}")

    current = rm.get_current_state(session_id)

    # Any state before PREPROCESSED means we have no stored data yet
    pre_states = {
        ReconciliationState.INITIALIZED,
        ReconciliationState.FILES_LOADED,
        ReconciliationState.PROFILED,
    }
    if current in pre_states:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Preprocessing results are not yet available. "
                f"Current state is '{current.value}'."
            ),
        )

    runtime = rm.get_runtime(session_id)
    norm_map_raw   = runtime.get("vendor_normalization_map", []) or []
    preprocessing  = runtime.get("preprocessing", {}) or {}
    snapshots      = rm.get_session_snapshots(session_id)
    latest         = snapshots[-1] if snapshots else {}

    return PreprocessingResponse(
        session_id=session_id,
        state=current.value,
        normalization_summary=NormalizationSummary(
            total_unique_gl_vendors=preprocessing.get("total_gl_vendors", len(norm_map_raw)),
            tier1_count=            preprocessing.get("tier1_count",  0),
            tier2_count=            preprocessing.get("tier2_count",  0),
            tier3_count=            preprocessing.get("tier3_count",  0),
            threshold_used=         preprocessing.get("threshold_used", 0.9),
            alias_version=          preprocessing.get("alias_version", "v1.0.0"),
        ),
        vendor_normalization_map=[
            NormalizationEntrySchema(**e) if isinstance(e, dict) else e
            for e in norm_map_raw
        ],
        unmatched_sub_vendors=preprocessing.get("unmatched_sub_vendors", []),
        unmatched_sub_normalized=preprocessing.get("unmatched_sub_normalized", {}),
        gl_normalized_vendor_row_distribution=preprocessing.get("gl_normalized_vendor_row_distribution", {}),
        gl_normalized_vendor_amt_distribution=preprocessing.get("gl_normalized_vendor_amt_distribution", {}),
        sl_normalized_vendor_row_distribution=preprocessing.get("sl_normalized_vendor_row_distribution", {}),
        sl_normalized_vendor_amt_distribution=preprocessing.get("sl_normalized_vendor_amt_distribution", {}),
        snapshot=SnapshotInfo(
            key=            latest.get("pre_transition_state", ""),
            integrity_hash= latest.get("integrity_hash", ""),
        ),
    )


@router.post("/{session_id}/preprocess", response_model=PreprocessingResponse)
def run_preprocess(session_id: str):
    """
    Run vendor normalization and advance session from 'profiled' to 'preprocessed'.

    Returns 409 with a specific "no recomputation" message if already preprocessed.
    Returns 409 if session is in any other non-profiled state.
    """
    # --- Guard: session existence ---
    if not rm.session_exists(session_id):
        raise HTTPException(status_code=404, detail=f"Session not found: {session_id}")

    current = rm.get_current_state(session_id)

    # --- Guard: already preprocessed (explicit, distinct from generic wrong-state) ---
    if current == ReconciliationState.PREPROCESSED:
        raise HTTPException(
            status_code=409,
            detail=(
                "Session is already in 'preprocessed' state. "
                "No recomputation is permitted once preprocessing is complete."
            ),
        )

    # --- Guard: correct pre-condition state ---
    if current != ReconciliationState.PROFILED:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Preprocessing requires state 'profiled'. "
                f"Current state is '{current.value}'."
            ),
        )

    # --- Pull inputs from runtime ---
    runtime = rm.get_runtime(session_id)
    config  = runtime["config"]

    gl_df  = runtime["raw_data"]["gl"]
    sub_df = runtime["raw_data"]["subledger"]

    nlp_threshold = config.get("vendor_nlp_threshold", 0.90)
    alias_map     = config.get("alias_map", {})
    alias_version = config.get("alias_version", "v1.0.0")
    column_map    = config.get("column_map")

    # --- Run normalization pipeline (pure, no side effects) ---
    try:
        result = run_normalization(
            gl_df=         gl_df,
            sub_df=        sub_df,
            nlp_threshold= nlp_threshold,
            alias_map=     alias_map,
            alias_version= alias_version,
            column_map=    column_map,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    # --- Write results BEFORE state advance so snapshot captures everything ---
    rm.write_vendor_normalization_map(session_id, result.to_map_list())

    rm.write_clean_data(session_id, {
        "gl":       result.gl_df,
        "subledger": result.sub_df,
    })

    gl_norm_row, gl_norm_amt = _normalized_dist(result.gl_df)
    sl_norm_row, sl_norm_amt = _normalized_dist(result.sub_df)

    rm.write_preprocessing(session_id, {
        "threshold_used":               result.threshold_used,
        "alias_version":                result.alias_version,
        "tier1_count":                  result.tier1_count,
        "tier2_count":                  result.tier2_count,
        "tier3_count":                  result.tier3_count,
        "total_gl_vendors":             len(result.entries),
        "unmatched_sub_vendors":        result.unmatched_sub_vendors,
        "unmatched_sub_normalized":     result.unmatched_sub_normalized,
        "gl_normalized_vendor_row_distribution": gl_norm_row,
        "gl_normalized_vendor_amt_distribution": gl_norm_amt,
        "sl_normalized_vendor_row_distribution": sl_norm_row,
        "sl_normalized_vendor_amt_distribution": sl_norm_amt,
    })

    # --- Advance state (snapshot fires automatically) ---
    try:
        rm.advance_state(
            session_id,
            ReconciliationState.PREPROCESSED,
            triggered_by="preprocess",
        )
    except InvalidStateTransition as exc:
        raise HTTPException(status_code=409, detail=str(exc))

    # --- Build response ---
    snapshots = rm.get_session_snapshots(session_id)
    latest    = snapshots[-1] if snapshots else {}

    return PreprocessingResponse(
        session_id=session_id,
        state=rm.get_current_state(session_id).value,
        normalization_summary=NormalizationSummary(
            total_unique_gl_vendors=len(result.entries),
            tier1_count=            result.tier1_count,
            tier2_count=            result.tier2_count,
            tier3_count=            result.tier3_count,
            threshold_used=         result.threshold_used,
            alias_version=          result.alias_version,
        ),
        vendor_normalization_map=[
            NormalizationEntrySchema(**e.to_dict()) for e in result.entries
        ],
        unmatched_sub_vendors=result.unmatched_sub_vendors,
        unmatched_sub_normalized=result.unmatched_sub_normalized,
        gl_normalized_vendor_row_distribution=gl_norm_row,
        gl_normalized_vendor_amt_distribution=gl_norm_amt,
        sl_normalized_vendor_row_distribution=sl_norm_row,
        sl_normalized_vendor_amt_distribution=sl_norm_amt,
        snapshot=SnapshotInfo(
            key=             latest.get("pre_transition_state", ""),
            integrity_hash=  latest.get("integrity_hash", ""),
        ),
    )


# ---------------------------------------------------------------------------
# Apply vendor overrides (manual edits from Vendor Preprocessing UI)
# ---------------------------------------------------------------------------

_SUB_PREFIX = "__sub__"


def _apply_vendor_overrides(clean_data: dict, overrides: dict, column_map: dict | None = None) -> None:
    """
    Apply manual vendor overrides to Vendor_Normalized in clean_data.
    - GL: key = original vendor value (from vendor_normalization_map)
    - Sub: key = "__sub__" + subledger vendor value
    Override values become the final Vendor_Normalized for matching and output.
    Empty overrides are ignored (keep existing). Original vendor column is unchanged (display only).

    column_map is used to resolve the actual vendor column name for each side.
    Falls back to "vendor_name" if column_map is absent or the role is unmapped.
    Both matched AND unmatched vendors receive their override (no distinction by match status).
    """
    if not overrides:
        return

    gl_df = clean_data.get("gl")
    sub_df = clean_data.get("subledger")

    # Resolve vendor column names from column_map (same logic as run_normalization)
    cm = column_map or {}
    gl_vendor_col  = cm.get("side_a", {}).get("vendor") or "vendor_name"
    sub_vendor_col = cm.get("side_b", {}).get("vendor") or "vendor_name"

    if gl_df is not None and not gl_df.empty and gl_vendor_col in gl_df.columns and "Vendor_Normalized" in gl_df.columns:
        def gl_override(row):
            v = row[gl_vendor_col]
            if pd.isna(v):
                return row["Vendor_Normalized"]
            sv = str(v)
            if sv in overrides:
                override_val = overrides[sv]
                if override_val is not None and str(override_val).strip():
                    return str(override_val).strip()
            return row["Vendor_Normalized"]

        gl_df["Vendor_Normalized"] = gl_df.apply(gl_override, axis=1)

    if sub_df is not None and not sub_df.empty and sub_vendor_col in sub_df.columns and "Vendor_Normalized" in sub_df.columns:
        def sub_override(row):
            v = row[sub_vendor_col]
            if pd.isna(v):
                return row["Vendor_Normalized"]
            key = _SUB_PREFIX + str(v)
            if key in overrides:
                override_val = overrides[key]
                if override_val is not None and str(override_val).strip():
                    return str(override_val).strip()
            return row["Vendor_Normalized"]

        sub_df["Vendor_Normalized"] = sub_df.apply(sub_override, axis=1)


@router.post("/{session_id}/preprocess/vendor_overrides")
def apply_vendor_overrides(session_id: str, body: VendorOverridesRequest):
    """
    Apply manual vendor overrides to clean_data.Vendor_Normalized.

    Body: { "vendor_overrides": { "GL Vendor LLC": "override name", "__sub__Sub Vendor": "override" } }

    Requires state >= preprocessed (clean_data must exist).
    Overrides become the final preprocessed name for matching and output.
    Original vendor_name is preserved for display throughout the app.
    """
    if not rm.session_exists(session_id):
        raise HTTPException(status_code=404, detail=f"Session not found: {session_id}")

    current = rm.get_current_state(session_id)
    if current.value not in (
        "preprocessed",
        "matching_configured",
        "deterministic_complete",
        "deterministic_review_complete",
        "probabilistic_complete",
        "probabilistic_review_complete",
        "ai_suggested",
        "ai_review_complete",
        "final_consolidated",
        "finalized",
    ):
        raise HTTPException(
            status_code=409,
            detail=(
                f"Vendor overrides require session to be preprocessed or later. "
                f"Current state is '{current.value}'."
            ),
        )

    overrides = body.vendor_overrides or {}
    if not overrides:
        return {"status": "ok", "applied_count": 0}

    runtime = rm.get_runtime(session_id)
    clean_data = runtime.get("clean_data")
    if not clean_data:
        raise HTTPException(
            status_code=409,
            detail="clean_data not available. Run preprocessing first.",
        )

    column_map = runtime.get("config", {}).get("column_map")
    _apply_vendor_overrides(clean_data, overrides, column_map)
    return {"status": "ok", "applied_count": len(overrides)}
