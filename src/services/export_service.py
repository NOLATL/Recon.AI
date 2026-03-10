"""
Export Service — Phase 8: final_consolidated → finalized

Generates 15 output files:

  uploaded_gl.csv             — Original GL data (all input columns)
  uploaded_subledger.csv      — Original Subledger data (all input columns)
  preprocessing_output.csv    — GL + Sub with Vendor_Normalized (source column added)
  deterministic_matches.csv   — Deterministic matches; one row per GL–Sub pair with all GL + Sub columns
  probabilistic_matches.csv   — Accepted probabilistic matches; one row per GL–Sub pair
  ai_matches.csv              — Accepted AI matches; one row per GL–Sub pair
  final_results.csv           — ALL accepted matches (det + prob + ai); one row per GL–Sub pair with all GL + Sub columns
  residual_unmatched_gl.csv   — Unmatched GL records (all columns)
  residual_unmatched_sub.csv  — Unmatched Subledger records (all columns)
  rejected_matches.csv        — Rejected matches; one row per GL–Sub pair with all GL + Sub columns
  audit_log.csv               — Complete audit trail (match-level metadata, no row expansion)
  process_log_run.csv         — Run-level process log (1 row)
  process_log_steps.csv       — Step-level process log (4 rows: preprocessing/det/prob/ai)
  process_log_ai.csv          — AI step metrics (1 row)
  reconciliation_report.pdf   — Executive summary PDF

Row-level match files (det/prob/ai/final/rejected) join GL and Sub data from clean_data:
  - GL columns are prefixed with 'gl_'
  - Sub columns are prefixed with 'sub_'
  - N:M matches expand to (len(gl_ids) × len(sub_ids)) rows

Source layer detection:
  'scenario_id' present       → deterministic
  'final_similarity' present  → probabilistic
  'ai_confidence_score' present → ai
"""

import hashlib
import os
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

import pandas as pd
from fpdf import FPDF


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class ExportFile:
    """Metadata for one generated file."""
    filename:   str
    path:       str
    sha256:     str
    size_bytes: int


@dataclass
class ExportManifest:
    """Output of run_export()."""
    export_dir:  str
    exported_at: str
    files:       List[ExportFile] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_MATCH_META_COLUMNS = [
    "match_id", "source_layer", "grouping_type",
    "user_status", "confidence", "override_flag",
]

_AUDIT_COLUMNS = [
    "match_id", "source_layer", "user_status",
    "record_ids_A", "record_ids_B",
    "confidence", "grouping_type", "override_flag",
]


# ---------------------------------------------------------------------------
# Source layer detection
# ---------------------------------------------------------------------------

def detect_source_layer(match: dict) -> str:
    """Determine the originating layer of a match dict by field presence."""
    if "scenario_id" in match:
        return "deterministic"
    if "final_similarity" in match:
        return "probabilistic"
    if "ai_confidence_score" in match:
        return "ai"
    return "unknown"


# ---------------------------------------------------------------------------
# File I/O helpers
# ---------------------------------------------------------------------------

def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _write_file(path: str, content: bytes) -> ExportFile:
    with open(path, "wb") as fh:
        fh.write(content)
    return ExportFile(
        filename=   os.path.basename(path),
        path=       path,
        sha256=     _sha256(content),
        size_bytes= len(content),
    )


def _write_dataframe_csv(df: pd.DataFrame, path: str) -> ExportFile:
    """Write a DataFrame to CSV. An empty DataFrame writes a header-only file."""
    if len(df.columns) == 0:
        content = b""
    else:
        content = df.to_csv(index=False).encode("utf-8")
    return _write_file(path, content)


# ---------------------------------------------------------------------------
# Lookup helpers
# ---------------------------------------------------------------------------

def _build_gl_sub_lookups(
    clean_data: dict,
) -> Tuple[Dict[str, dict], Dict[str, dict]]:
    """Build ID-keyed row dicts from clean_data for joining into match rows."""
    gl_df  = clean_data.get("gl")
    sub_df = clean_data.get("subledger")

    gl_lookup: Dict[str, dict] = {}
    if gl_df is not None and not gl_df.empty and "gl_id" in gl_df.columns:
        for _, row in gl_df.iterrows():
            gid = str(row["gl_id"])
            gl_lookup[gid] = {
                k: (None if (isinstance(v, float) and pd.isna(v)) else v)
                for k, v in row.items()
            }

    sub_lookup: Dict[str, dict] = {}
    if sub_df is not None and not sub_df.empty and "subledger_id" in sub_df.columns:
        for _, row in sub_df.iterrows():
            sid = str(row["subledger_id"])
            sub_lookup[sid] = {
                k: (None if (isinstance(v, float) and pd.isna(v)) else v)
                for k, v in row.items()
            }

    return gl_lookup, sub_lookup


# ---------------------------------------------------------------------------
# Match row expansion
# ---------------------------------------------------------------------------

def _confidence_value(match: dict):
    return (
        match.get("confidence_score")
        or match.get("final_similarity")
        or match.get("ai_confidence_score")
        or ""
    )


def _expand_matches_with_data(
    matches:    List[dict],
    source_layer: str,
    gl_lookup:  Dict[str, dict],
    sub_lookup: Dict[str, dict],
) -> pd.DataFrame:
    """
    Expand each match to one row per GL–Sub ID pair, joining all original data columns.
    GL columns are prefixed with 'gl_'; Subledger columns with 'sub_'.
    N:M matches produce (len(gl_ids) × len(sub_ids)) rows.
    Returns an empty DataFrame with metadata columns when matches is empty.
    """
    if not matches:
        return pd.DataFrame(columns=_MATCH_META_COLUMNS)

    rows = []
    for match in matches:
        gl_ids  = [str(x) for x in match.get("record_ids_A", [])]
        sub_ids = [str(x) for x in match.get("record_ids_B", [])]
        meta = {
            "match_id":      match.get("match_id", ""),
            "source_layer":  source_layer,
            "grouping_type": match.get("grouping_type", ""),
            "user_status":   match.get("user_status", ""),
            "confidence":    _confidence_value(match),
            "override_flag": match.get("override_flag", False),
        }
        for gl_id in (gl_ids or [""]):
            for sub_id in (sub_ids or [""]):
                row = dict(meta)
                for k, v in gl_lookup.get(str(gl_id), {}).items():
                    row[f"gl_{k}"] = v
                for k, v in sub_lookup.get(str(sub_id), {}).items():
                    row[f"sub_{k}"] = v
                rows.append(row)

    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Audit log (match-level metadata — no GL/Sub expansion)
# ---------------------------------------------------------------------------

def _normalise_match_for_audit(match: dict) -> dict:
    layer = detect_source_layer(match)
    confidence = _confidence_value(match)
    return {
        "match_id":      match.get("match_id", ""),
        "source_layer":  layer,
        "user_status":   match.get("user_status", ""),
        "record_ids_A":  ",".join(str(x) for x in match.get("record_ids_A", [])),
        "record_ids_B":  ",".join(str(x) for x in match.get("record_ids_B", [])),
        "confidence":    confidence,
        "grouping_type": match.get("grouping_type", ""),
        "override_flag": match.get("override_flag", False),
    }


def _matches_to_audit_df(matches: List[dict]) -> pd.DataFrame:
    if not matches:
        return pd.DataFrame(columns=_AUDIT_COLUMNS)
    return pd.DataFrame([_normalise_match_for_audit(m) for m in matches], columns=_AUDIT_COLUMNS)


# ---------------------------------------------------------------------------
# Preprocessing output
# ---------------------------------------------------------------------------

def _build_preprocessing_output(clean_data: dict) -> pd.DataFrame:
    """Combine clean GL and Sub DataFrames with a 'source' indicator column."""
    gl_df  = clean_data.get("gl")
    sub_df = clean_data.get("subledger")

    frames = []
    if gl_df is not None and not gl_df.empty:
        df = gl_df.copy()
        df.insert(0, "source", "GL")
        frames.append(df)
    if sub_df is not None and not sub_df.empty:
        df = sub_df.copy()
        df.insert(0, "source", "Subledger")
        frames.append(df)

    if frames:
        return pd.concat(frames, ignore_index=True)
    return pd.DataFrame(columns=["source"])


# ---------------------------------------------------------------------------
# Process log helpers
# ---------------------------------------------------------------------------

def _snap_time(snapshots: dict, pre_state: str) -> str:
    """Return captured_at from the snapshot for a given pre-transition state."""
    entry = snapshots.get(pre_state)
    if isinstance(entry, dict):
        return entry.get("captured_at", "")
    # Handle suffixed collision keys (e.g. "profiled_1")
    for k, v in snapshots.items():
        if k.startswith(pre_state + "_") and isinstance(v, dict):
            return v.get("captured_at", "")
    return ""


def _duration_secs(start_ts: str, end_ts: str) -> float:
    if not start_ts or not end_ts:
        return 0.0
    try:
        start = datetime.fromisoformat(start_ts)
        end   = datetime.fromisoformat(end_ts)
        return round(abs((end - start).total_seconds()), 1)
    except ValueError:
        return 0.0


def _build_process_log_run(
    session_id:  str,
    raw_data:    dict,
    snapshots:   dict,
    exported_at: str,
) -> pd.DataFrame:
    gl_df  = raw_data.get("gl")
    sub_df = raw_data.get("subledger")

    snap_times = sorted(
        v.get("captured_at", "")
        for v in snapshots.values()
        if isinstance(v, dict) and v.get("captured_at")
    )
    start_ts = snap_times[0] if snap_times else ""

    return pd.DataFrame([{
        "session_id":             session_id,
        "run_timestamp_start":    start_ts,
        "run_timestamp_end":      exported_at,
        "run_duration_seconds":   _duration_secs(start_ts, exported_at),
        "user_id":                "N/A",
        "input_gl_file":          "GL.csv",
        "input_subledger_file":   "Subledger.csv",
        "gl_record_count":        len(gl_df)  if gl_df  is not None else 0,
        "subledger_record_count": len(sub_df) if sub_df is not None else 0,
        "status":                 "success",
    }])


def _build_process_log_steps(
    snapshots:    dict,
    matching:     dict,
    consolidation: dict,
    raw_data:     dict,
) -> pd.DataFrame:
    gl_df  = raw_data.get("gl")
    sub_df = raw_data.get("subledger")
    gl_total  = len(gl_df)  if gl_df  is not None else 0
    sub_total = len(sub_df) if sub_df is not None else 0

    det_matches   = len(matching.get("deterministic", []))
    prob_accepted = consolidation.get("probabilistic_match_count", 0)
    residual_gl   = consolidation.get("residual_gl_count",  0)
    residual_sub  = consolidation.get("residual_sub_count", 0)

    prob_all      = matching.get("probabilistic", [])
    prob_created  = len(prob_all)
    ai_all        = (
        matching.get("ai_suggested", []) +
        [m for m in matching.get("final",     []) if "ai_confidence_score" in m] +
        [m for m in matching.get("rejected",  []) if "ai_confidence_score" in m]
    )
    ai_created = len(ai_all)

    steps = [
        {
            "step_name":           "preprocessing",
            "step_start_time":     _snap_time(snapshots, "profiled"),
            "step_end_time":       _snap_time(snapshots, "preprocessed"),
            "input_record_count":  gl_total + sub_total,
            "output_record_count": gl_total + sub_total,
            "matches_created":     0,
            "residual_records":    gl_total + sub_total,
            "status":              "success",
            "error_message":       "",
        },
        {
            "step_name":           "deterministic",
            "step_start_time":     _snap_time(snapshots, "preprocessed"),
            "step_end_time":       _snap_time(snapshots, "deterministic_complete"),
            "input_record_count":  gl_total + sub_total,
            "output_record_count": (gl_total - det_matches) + (sub_total - det_matches),
            "matches_created":     det_matches,
            "residual_records":    (gl_total - det_matches) + (sub_total - det_matches),
            "status":              "success",
            "error_message":       "",
        },
        {
            "step_name":           "probabilistic",
            "step_start_time":     _snap_time(snapshots, "deterministic_review_complete"),
            "step_end_time":       _snap_time(snapshots, "probabilistic_complete"),
            "input_record_count":  (gl_total - det_matches) + (sub_total - det_matches),
            "output_record_count": residual_gl + residual_sub + (prob_accepted * 2),
            "matches_created":     prob_created,
            "residual_records":    residual_gl + residual_sub + (prob_accepted * 2),
            "status":              "success",
            "error_message":       "",
        },
        {
            "step_name":           "ai",
            "step_start_time":     _snap_time(snapshots, "probabilistic_review_complete"),
            "step_end_time":       _snap_time(snapshots, "ai_suggested"),
            "input_record_count":  residual_gl + residual_sub,
            "output_record_count": residual_gl + residual_sub,
            "matches_created":     ai_created,
            "residual_records":    residual_gl + residual_sub,
            "status":              "success",
            "error_message":       "",
        },
    ]

    for s in steps:
        s["step_duration_seconds"] = _duration_secs(s["step_start_time"], s["step_end_time"])

    cols = [
        "step_name", "step_start_time", "step_end_time", "step_duration_seconds",
        "input_record_count", "output_record_count", "matches_created",
        "residual_records", "status", "error_message",
    ]
    return pd.DataFrame(steps, columns=cols)


def _build_process_log_ai(
    session_id: str,
    ai_meta:    dict,
    matching:   dict,
) -> pd.DataFrame:
    all_ai = (
        matching.get("ai_suggested", []) +
        [m for m in matching.get("final",    []) if "ai_confidence_score" in m] +
        [m for m in matching.get("rejected", []) if "ai_confidence_score" in m]
    )
    scores = [m.get("ai_confidence_score", 0) for m in all_ai]
    avg_conf = round(sum(scores) / len(scores), 4) if scores else 0.0

    records_sent = (
        ai_meta.get("total_residual_gl",  0) +
        ai_meta.get("total_residual_sub", 0)
    )

    return pd.DataFrame([{
        "session_id":           session_id,
        "model_name":           ai_meta.get("model_used",      ""),
        "prompt_version":       ai_meta.get("prompt_version",  ""),
        "records_sent_to_ai":   records_sent,
        "tokens_input":         0,
        "tokens_output":        0,
        "ai_runtime_seconds":   0,
        "avg_confidence_score": avg_conf,
        "ai_failures":          0,
    }])


# ---------------------------------------------------------------------------
# PDF builder
# ---------------------------------------------------------------------------

def _build_pdf(
    session_id:    str,
    consolidation: dict,
    ai_meta:       dict,
    exported_at:   str,
) -> bytes:
    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()

    pdf.set_font("Helvetica", "B", 18)
    pdf.cell(0, 12, "Reconciliation Report", ln=True, align="C")
    pdf.set_font("Helvetica", "", 10)
    pdf.cell(0, 6, f"Generated: {exported_at}", ln=True, align="C")
    pdf.ln(6)

    pdf.set_font("Helvetica", "B", 13)
    pdf.cell(0, 9, "Executive Summary", ln=True)
    pdf.set_font("Helvetica", "", 10)
    pdf.cell(0, 6, f"Session ID : {session_id}", ln=True)
    pdf.cell(0, 6, "Final State: finalized", ln=True)
    pdf.cell(0, 6, f"Report Date: {exported_at[:10]}", ln=True)
    pdf.ln(4)

    pdf.set_font("Helvetica", "B", 13)
    pdf.cell(0, 9, "Reconciliation Statistics", ln=True)

    stats = [
        ("Deterministic Matches",              consolidation.get("deterministic_match_count", 0)),
        ("Probabilistic Matches (accepted)",   consolidation.get("probabilistic_match_count", 0)),
        ("AI-Assisted Matches (accepted)",     consolidation.get("ai_match_count",            0)),
        ("Total Accepted Matches",             consolidation.get("total_match_count",         0)),
        ("Residual GL Records",                consolidation.get("residual_gl_count",         0)),
        ("Residual Subledger Records",         consolidation.get("residual_sub_count",        0)),
        ("Rejected Matches",                   consolidation.get("rejected_count",            0)),
    ]

    pdf.set_font("Helvetica", "B", 10)
    col_w, val_w = 110, 40
    pdf.cell(col_w, 7, "Metric", border=1)
    pdf.cell(val_w, 7, "Count", border=1, ln=True)
    pdf.set_font("Helvetica", "", 10)
    for label, value in stats:
        pdf.cell(col_w, 7, label, border=1)
        pdf.cell(val_w, 7, str(value), border=1, align="R", ln=True)
    pdf.ln(4)

    pdf.set_font("Helvetica", "B", 13)
    pdf.cell(0, 9, "Override Summary", ln=True)
    pdf.set_font("Helvetica", "", 10)
    override_count = consolidation.get("override_count", 0)
    if override_count == 0:
        pdf.cell(0, 6, "No manual overrides were applied in this reconciliation run.", ln=True)
    else:
        pdf.cell(0, 6, f"{override_count} manual override(s) were applied.", ln=True)
    pdf.ln(4)

    pdf.set_font("Helvetica", "B", 13)
    pdf.cell(0, 9, "AI Narrative Insights", ln=True)
    pdf.set_font("Helvetica", "", 10)
    model_used       = ai_meta.get("model_used", "")
    suggestion_count = ai_meta.get("suggestion_count", 0)
    if model_used:
        pdf.cell(0, 6, f"AI Model    : {model_used}", ln=True)
    if suggestion_count:
        pdf.cell(0, 6, f"Suggestions : {suggestion_count} AI match(es) proposed", ln=True)
    narrative = ai_meta.get("narrative", "")
    if narrative:
        pdf.ln(2)
        pdf.set_font("Helvetica", "I", 10)
        pdf.multi_cell(0, 6, narrative)
    else:
        accepted_ai  = consolidation.get("ai_match_count", 0)
        summary_line = (
            f"The AI advisory layer proposed {suggestion_count} match(es). "
            f"{accepted_ai} were accepted and incorporated into the final dataset."
        )
        pdf.multi_cell(0, 6, summary_line)

    return bytes(pdf.output())


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def run_export(
    det_matches:      List[dict],       # runtime["matching"]["deterministic"]
    prob_matches:     List[dict],       # runtime["matching"]["probabilistic"] — all (accepted+pending)
    ai_final:         List[dict],       # runtime["matching"]["final"] — AI-accepted only
    ai_suggested:     List[dict],       # runtime["matching"]["ai_suggested"] — pending suggestions
    rejected:         List[dict],       # runtime["matching"]["rejected"]
    residual_gl:      pd.DataFrame,
    residual_sub:     pd.DataFrame,
    ai_meta:          dict,
    consolidation:    dict,
    raw_data:         dict,             # runtime["raw_data"]
    clean_data:       dict,             # runtime["clean_data"]
    snapshots:        dict,             # runtime["snapshots"]
    matching:         dict,             # runtime["matching"] — for audit/process logs
    session_id:       str,
    manual_overrides: Optional[Dict[str, List[str]]] = None,  # {gl_id: [sub_id, ...]}
    export_dir:       Optional[str] = None,
) -> ExportManifest:
    """
    Generate all 15 output files and return an ExportManifest.

    Row-level match files join GL and Sub data from clean_data so each row
    contains all original source columns (prefixed gl_ / sub_).
    N:M matches expand to one row per GL–Sub pair.
    """
    if export_dir is None:
        export_dir = tempfile.mkdtemp(prefix=f"recon_{session_id[:8]}_")

    exported_at = datetime.now(timezone.utc).isoformat()
    manifest    = ExportManifest(export_dir=export_dir, exported_at=exported_at)

    # Build per-ID row lookups for GL/Sub join.
    gl_lookup, sub_lookup = _build_gl_sub_lookups(clean_data)

    # Accepted probabilistic subset.
    prob_accepted = [m for m in prob_matches if m.get("user_status") == "accepted"]

    # -- 1. uploaded_gl.csv ────────────────────────────────────────────────
    gl_raw = raw_data.get("gl") if raw_data.get("gl") is not None else pd.DataFrame()
    manifest.files.append(
        _write_dataframe_csv(gl_raw, os.path.join(export_dir, "uploaded_gl.csv"))
    )

    # -- 2. uploaded_subledger.csv ─────────────────────────────────────────
    sub_raw = raw_data.get("subledger") if raw_data.get("subledger") is not None else pd.DataFrame()
    manifest.files.append(
        _write_dataframe_csv(sub_raw, os.path.join(export_dir, "uploaded_subledger.csv"))
    )

    # -- 3. preprocessing_output.csv ───────────────────────────────────────
    preprocess_df = _build_preprocessing_output(clean_data)
    manifest.files.append(
        _write_dataframe_csv(preprocess_df, os.path.join(export_dir, "preprocessing_output.csv"))
    )

    # -- 4. deterministic_matches.csv ──────────────────────────────────────
    det_df = _expand_matches_with_data(det_matches, "deterministic", gl_lookup, sub_lookup)
    manifest.files.append(
        _write_dataframe_csv(det_df, os.path.join(export_dir, "deterministic_matches.csv"))
    )

    # -- 5. probabilistic_matches.csv (accepted only) ──────────────────────
    prob_df = _expand_matches_with_data(prob_accepted, "probabilistic", gl_lookup, sub_lookup)
    manifest.files.append(
        _write_dataframe_csv(prob_df, os.path.join(export_dir, "probabilistic_matches.csv"))
    )

    # -- 6. ai_matches.csv (accepted only — from final bucket) ─────────────
    ai_df = _expand_matches_with_data(ai_final, "ai", gl_lookup, sub_lookup)
    manifest.files.append(
        _write_dataframe_csv(ai_df, os.path.join(export_dir, "ai_matches.csv"))
    )

    # -- 7. final_results.csv — all accepted matches (incl. manual overrides) ─
    final_parts = []
    for layer_matches, layer_name in [
        (det_matches,   "deterministic"),
        (prob_accepted, "probabilistic"),
        (ai_final,      "ai"),
    ]:
        part = _expand_matches_with_data(layer_matches, layer_name, gl_lookup, sub_lookup)
        if not part.empty:
            final_parts.append(part)

    # Append manual override rows: one row per GL–Sub pair, source_layer="manual".
    if manual_overrides:
        manual_rows = []
        for gl_id, sub_ids in manual_overrides.items():
            gl_data  = gl_lookup.get(str(gl_id), {})
            n_sub    = len(sub_ids)
            grouping = "one_to_one" if n_sub == 1 else "one_to_many"
            for sub_id in sub_ids:
                sub_data = sub_lookup.get(str(sub_id), {})
                row = {
                    "match_id":      f"MANUAL_{gl_id}_{sub_id}",
                    "source_layer":  "manual",
                    "grouping_type": grouping,
                    "user_status":   "manual_override",
                    "confidence":    1.0,
                    "override_flag": True,
                }
                for k, v in gl_data.items():
                    row[f"gl_{k}"] = v
                for k, v in sub_data.items():
                    row[f"sub_{k}"] = v
                manual_rows.append(row)
        if manual_rows:
            final_parts.append(pd.DataFrame(manual_rows))

    final_df = pd.concat(final_parts, ignore_index=True) if final_parts else pd.DataFrame(columns=_MATCH_META_COLUMNS)
    manifest.files.append(
        _write_dataframe_csv(final_df, os.path.join(export_dir, "final_results.csv"))
    )

    # Pre-compute overridden ID sets so residuals exclude manually matched rows.
    overridden_gl_ids  = set((manual_overrides or {}).keys())
    overridden_sub_ids = {
        sid
        for sub_ids in (manual_overrides or {}).values()
        for sid in sub_ids
    }

    # -- 8. residual_unmatched_gl.csv — exclude manually overridden GL rows ─
    gl_res = residual_gl if residual_gl is not None else pd.DataFrame()
    if overridden_gl_ids and not gl_res.empty and "gl_id" in gl_res.columns:
        gl_res = gl_res[~gl_res["gl_id"].astype(str).isin(overridden_gl_ids)].copy()
    manifest.files.append(
        _write_dataframe_csv(gl_res, os.path.join(export_dir, "residual_unmatched_gl.csv"))
    )

    # -- 9. residual_unmatched_sub.csv — exclude manually overridden Sub rows
    sub_res = residual_sub if residual_sub is not None else pd.DataFrame()
    if overridden_sub_ids and not sub_res.empty and "subledger_id" in sub_res.columns:
        sub_res = sub_res[~sub_res["subledger_id"].astype(str).isin(overridden_sub_ids)].copy()
    manifest.files.append(
        _write_dataframe_csv(sub_res, os.path.join(export_dir, "residual_unmatched_sub.csv"))
    )

    # -- 10. rejected_matches.csv ──────────────────────────────────────────
    rej_df = _expand_matches_with_data(rejected, "rejected", gl_lookup, sub_lookup)
    manifest.files.append(
        _write_dataframe_csv(rej_df, os.path.join(export_dir, "rejected_matches.csv"))
    )

    # -- 11. audit_log.csv — match-level metadata for all entries ──────────
    pending_prob = [m for m in prob_matches if m.get("user_status") == "pending"]
    all_accepted = det_matches + prob_accepted + ai_final
    all_audit    = all_accepted + pending_prob + ai_suggested + rejected
    audit_df = _matches_to_audit_df(all_audit)
    manifest.files.append(
        _write_dataframe_csv(audit_df, os.path.join(export_dir, "audit_log.csv"))
    )

    # -- 12. process_log_run.csv ───────────────────────────────────────────
    run_log_df = _build_process_log_run(session_id, raw_data, snapshots, exported_at)
    manifest.files.append(
        _write_dataframe_csv(run_log_df, os.path.join(export_dir, "process_log_run.csv"))
    )

    # -- 13. process_log_steps.csv ─────────────────────────────────────────
    steps_log_df = _build_process_log_steps(snapshots, matching, consolidation, raw_data)
    manifest.files.append(
        _write_dataframe_csv(steps_log_df, os.path.join(export_dir, "process_log_steps.csv"))
    )

    # -- 14. process_log_ai.csv ────────────────────────────────────────────
    ai_log_df = _build_process_log_ai(session_id, ai_meta, matching)
    manifest.files.append(
        _write_dataframe_csv(ai_log_df, os.path.join(export_dir, "process_log_ai.csv"))
    )

    # -- 15. reconciliation_report.pdf ─────────────────────────────────────
    pdf_bytes = _build_pdf(session_id, consolidation, ai_meta, exported_at)
    manifest.files.append(
        _write_file(os.path.join(export_dir, "reconciliation_report.pdf"), pdf_bytes)
    )

    return manifest
