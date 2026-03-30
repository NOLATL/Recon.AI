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
import json
import os
import tempfile
from collections import defaultdict
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
# Chart helpers — pure FPDF drawing primitives (no external image libraries)
# ---------------------------------------------------------------------------

# RGB colour palette
_SEG_COLORS: List[Tuple[int, int, int]] = [
    (76, 175, 80),    # green  — Deterministic
    (33, 150, 243),   # blue   — Probabilistic
    (156, 39, 176),   # purple — AI Matches
    (255, 152, 0),    # orange — Unmatched
]
_MATCHED_RGB:   Tuple[int, int, int] = (76, 175, 80)
_UNMATCHED_RGB: Tuple[int, int, int] = (255, 152, 0)


def _fill_rect(pdf: FPDF, x: float, y: float, w: float, h: float,
               r: int, g: int, b: int) -> None:
    """Draw a filled rectangle without border."""
    pdf.set_fill_color(r, g, b)
    pdf.set_draw_color(r, g, b)
    pdf.rect(x, y, w, h, style="F")


def _draw_breakdown_bar(
    pdf:      FPDF,
    segments: List[Tuple],  # [(label, count, dollars, (r,g,b)), ...]
    gl_total: int,
    x:        float,
    y:        float,
    bar_w:    float,
    bar_h:    float = 10.0,
) -> float:
    """
    Draw a horizontal stacked bar + legend directly on the PDF.
    Returns total height consumed (mm).
    """
    if gl_total == 0:
        return 0.0

    left = x
    for label, count, dollars, color in segments:
        if count <= 0:
            continue
        seg_w = bar_w * count / gl_total
        _fill_rect(pdf, left, y, seg_w, bar_h, *color)
        pct = count / gl_total * 100
        if pct > 5 and seg_w > 8:
            pdf.set_font("Helvetica", "B", 7)
            pdf.set_text_color(255, 255, 255)
            pdf.set_xy(left, y + (bar_h - 3.5) / 2)
            pdf.cell(seg_w, 3.5, f"{pct:.0f}%", align="C")
        left += seg_w

    pdf.set_text_color(0, 0, 0)

    # Legend row
    legend_y = y + bar_h + 3
    sq       = 4.0
    col_w    = bar_w / len(segments)
    for i, (label, count, dollars, color) in enumerate(segments):
        lx = x + i * col_w
        _fill_rect(pdf, lx, legend_y + 0.5, sq, sq, *color)
        dollar_str = f"${dollars / 1000:.1f}K" if dollars >= 1000 else f"${dollars:,.0f}"
        pdf.set_font("Helvetica", "", 7)
        pdf.set_text_color(40, 40, 40)
        pdf.set_xy(lx + sq + 1, legend_y)
        pdf.cell(col_w - sq - 2, 5, f"{label}  {count:,}  {dollar_str}")

    pdf.set_text_color(0, 0, 0)
    return bar_h + 3 + 5 + 2  # bar + gap + legend + bottom margin


def _draw_vendor_chart(
    pdf:         FPDF,
    vendor_data: List[Tuple],   # [(name, matched_val, unmatched_val), ...] ascending
    title:       str,
    x:           float,
    y:           float,
    w:           float,
    dollar:      bool  = False,
    max_vendors: int   = 12,
    bar_h:       float = 5.0,
    gap:         float = 1.5,
) -> float:
    """
    Draw a horizontal stacked bar chart by vendor at (x, y).
    Returns total height consumed (mm).
    """
    vendor_data = vendor_data[-max_vendors:]
    if not vendor_data:
        return 0.0

    label_w  = 38.0
    bar_area = w - label_w
    total_h  = 0.0

    # Title
    pdf.set_font("Helvetica", "B", 8)
    pdf.set_text_color(30, 30, 30)
    pdf.set_xy(x, y)
    pdf.cell(w, 6, title, align="C")
    total_h += 7

    max_val = max((v[1] + v[2]) for v in vendor_data) or 1

    for vd in reversed(vendor_data):   # largest at bottom
        name      = str(vd[0])[:20]
        matched   = vd[1]
        unmatched = vd[2]
        row_y     = y + total_h

        # Label
        pdf.set_font("Helvetica", "", 6.5)
        pdf.set_text_color(40, 40, 40)
        pdf.set_xy(x, row_y + (bar_h - 3) / 2)
        pdf.cell(label_w - 1, 3, name, align="R")

        # Background track
        _fill_rect(pdf, x + label_w, row_y, bar_area, bar_h, 235, 235, 235)

        # Matched segment
        m_w = bar_area * matched / max_val
        if m_w > 0:
            _fill_rect(pdf, x + label_w, row_y, m_w, bar_h, *_MATCHED_RGB)

        # Unmatched segment
        u_w = bar_area * unmatched / max_val
        if u_w > 0:
            _fill_rect(pdf, x + label_w + m_w, row_y, u_w, bar_h, *_UNMATCHED_RGB)

        total_h += bar_h + gap

    # Scale labels
    ax_y = y + total_h
    pdf.set_font("Helvetica", "", 6)
    pdf.set_text_color(120, 120, 120)
    pdf.set_xy(x + label_w, ax_y)
    pdf.cell(bar_area / 2, 4, "0", align="L")
    max_label = (
        f"${max_val / 1000:.1f}K" if dollar and max_val >= 1000
        else f"${max_val:,.0f}" if dollar
        else str(int(max_val))
    )
    pdf.set_xy(x + label_w, ax_y)
    pdf.cell(bar_area, 4, max_label, align="R")
    total_h += 5

    # Legend
    leg_y = y + total_h
    _fill_rect(pdf, x + label_w, leg_y + 0.5, 4, 4, *_MATCHED_RGB)
    pdf.set_font("Helvetica", "", 6.5)
    pdf.set_text_color(40, 40, 40)
    pdf.set_xy(x + label_w + 5, leg_y)
    pdf.cell(20, 4, "Matched")
    _fill_rect(pdf, x + label_w + 28, leg_y + 0.5, 4, 4, *_UNMATCHED_RGB)
    pdf.set_xy(x + label_w + 33, leg_y)
    pdf.cell(20, 4, "Unmatched")

    pdf.set_text_color(0, 0, 0)
    total_h += 8
    return total_h


def _add_vendor_detail_section(
    pdf: FPDF,
    title: str,
    total_count: int,
    total_amount: float,
    vendor_counts: dict,
    vendor_dollars: dict,
    page_w: float,
) -> None:
    """Render a rejected/override vendor breakdown section into the PDF."""
    pdf.set_font("Helvetica", "B", 11)
    pdf.set_text_color(0, 0, 0)
    pdf.cell(0, 7, title, ln=True)
    pdf.set_font("Helvetica", "", 9)
    pdf.cell(0, 5, f"Total: {total_count:,} records   ${total_amount:,.2f}", ln=True)

    if not vendor_counts:
        pdf.set_font("Helvetica", "I", 9)
        pdf.cell(0, 5, "None.", ln=True)
        return

    col1 = page_w * 0.55
    col2 = page_w * 0.18
    col3 = page_w * 0.27
    pdf.set_font("Helvetica", "B", 8)
    pdf.cell(col1, 5, "Vendor", border=1)
    pdf.cell(col2, 5, "Count", border=1, align="C")
    pdf.cell(col3, 5, "Dollar Total", border=1, align="R", ln=True)

    pdf.set_font("Helvetica", "", 8)
    sorted_vendors = sorted(vendor_counts.items(), key=lambda x: -x[1])[:10]
    for vendor, count in sorted_vendors:
        dollars = vendor_dollars.get(vendor, 0.0)
        v_name  = str(vendor)[:42] if len(str(vendor)) > 42 else str(vendor)
        pdf.cell(col1, 5, v_name, border=1)
        pdf.cell(col2, 5, str(count), border=1, align="C")
        pdf.cell(col3, 5, f"${dollars:,.2f}", border=1, align="R", ln=True)


# ---------------------------------------------------------------------------
# PDF subclass — auto-renders footer with page numbers on every page
# ---------------------------------------------------------------------------

class _ReconPDF(FPDF):
    _session_id: str = ""
    _exported_at: str = ""
    _ai_model: str = ""

    def footer(self) -> None:
        self.set_y(-15)
        self.set_font("Helvetica", "", 7)
        self.set_text_color(120, 120, 120)
        ts = self._exported_at[:19].replace("T", " ") if self._exported_at else ""
        text = (
            f"Timestamp of report generation: {ts} UTC   |   "
            f"Session ID: {self._session_id}   |   "
            f"AI Model: {self._ai_model}   |   "
            f"Page {self.page_no()} of {{nb}}"
        )
        self.cell(0, 5, text, align="C")


# ---------------------------------------------------------------------------
# PDF builder
# ---------------------------------------------------------------------------

def _build_pdf(
    session_id:    str,
    consolidation: dict,
    ai_meta:       dict,
    exported_at:   str,
    gl_df:         pd.DataFrame,
    final_matches: List[dict],
    residual_gl_df: pd.DataFrame,
    all_rejected:  List[dict],
    gl_lookup:     Dict[str, dict],
    manual_overrides: Optional[Dict[str, List[str]]],
    det_matches:   List[dict],
    prob_accepted: List[dict],
    ai_final:      List[dict],
    narrative:     str,
) -> bytes:
    # ---- Compute KPI metrics ------------------------------------------------
    _gl_df = gl_df if gl_df is not None and not gl_df.empty else pd.DataFrame()
    gl_total = len(_gl_df)

    # Amount map: gl_id → float amount
    amount_col = "amount"
    gl_amount_map: Dict[str, float] = {}
    if not _gl_df.empty and "gl_id" in _gl_df.columns and amount_col in _gl_df.columns:
        gl_amount_map = dict(zip(
            _gl_df["gl_id"].astype(str),
            pd.to_numeric(_gl_df[amount_col], errors="coerce").fillna(0.0),
        ))

    def _sum_amt(id_set: set) -> float:
        return sum(gl_amount_map.get(gid, 0.0) for gid in id_set)

    # Rejected GL IDs first — needed to exclude from matched sets below
    rej_gl_ids = {str(x) for m in all_rejected for x in m.get("record_ids_A", [])}
    rej_amount = _sum_amt(rej_gl_ids)

    # GL IDs matched by each layer (mutually exclusive sets, rejected IDs excluded)
    det_ids  = {str(x) for m in det_matches  for x in m.get("record_ids_A", [])} - rej_gl_ids
    prob_ids = {str(x) for m in prob_accepted for x in m.get("record_ids_A", [])} - rej_gl_ids - det_ids
    ai_ids   = {str(x) for m in ai_final     for x in m.get("record_ids_A", [])} - rej_gl_ids - det_ids - prob_ids
    man_ids  = {str(gid) for gid in (manual_overrides or {})} - det_ids - prob_ids - ai_ids
    all_matched_ids = det_ids | prob_ids | ai_ids | man_ids

    res_gl_ids: set = set()
    if residual_gl_df is not None and not residual_gl_df.empty and "gl_id" in residual_gl_df.columns:
        res_gl_ids = set(residual_gl_df["gl_id"].astype(str))

    gl_matched_count   = len(all_matched_ids)
    gl_unmatched_count = len(res_gl_ids)
    match_rate         = gl_matched_count / gl_total * 100 if gl_total else 0.0

    matched_amount   = _sum_amt(all_matched_ids)
    unmatched_amount = _sum_amt(res_gl_ids)
    det_amount       = _sum_amt(det_ids)
    prob_amount      = _sum_amt(prob_ids)
    ai_amount        = _sum_amt(ai_ids | man_ids)

    override_count  = len(man_ids)
    override_amount = _sum_amt(man_ids)

    # ---- Vendor breakdown ---------------------------------------------------
    vendor_col = "vendor_name"
    vendor_map: Dict[str, str] = {}
    if not _gl_df.empty and "gl_id" in _gl_df.columns and vendor_col in _gl_df.columns:
        for _, row in _gl_df.iterrows():
            vendor_map[str(row["gl_id"])] = str(row.get(vendor_col, "Unknown"))

    v_matched_count:    Dict[str, int]   = defaultdict(int)
    v_unmatched_count:  Dict[str, int]   = defaultdict(int)
    v_matched_dollars:  Dict[str, float] = defaultdict(float)
    v_unmatched_dollars: Dict[str, float] = defaultdict(float)

    for gid in all_matched_ids:
        v = vendor_map.get(gid, "Unknown")
        v_matched_count[v]   += 1
        v_matched_dollars[v] += gl_amount_map.get(gid, 0.0)
    for gid in res_gl_ids:
        v = vendor_map.get(gid, "Unknown")
        v_unmatched_count[v]   += 1
        v_unmatched_dollars[v] += gl_amount_map.get(gid, 0.0)

    all_vendors = set(v_matched_count) | set(v_unmatched_count)
    vendor_data = sorted(
        [(v, v_matched_count[v], v_unmatched_count[v],
          v_matched_dollars[v], v_unmatched_dollars[v])
         for v in all_vendors],
        key=lambda x: x[1] + x[2],  # ascending by total count
    )

    v_rej_count:    Dict[str, int]   = defaultdict(int)
    v_rej_dollars:  Dict[str, float] = defaultdict(float)
    for gid in rej_gl_ids:
        v = vendor_map.get(gid, "Unknown")
        v_rej_count[v]   += 1
        v_rej_dollars[v] += gl_amount_map.get(gid, 0.0)

    v_over_count:    Dict[str, int]   = defaultdict(int)
    v_over_dollars:  Dict[str, float] = defaultdict(float)
    for gid in man_ids:
        v = vendor_map.get(gid, "Unknown")
        v_over_count[v]   += 1
        v_over_dollars[v] += gl_amount_map.get(gid, 0.0)

    # ---- BUILD PDF ----------------------------------------------------------
    pdf = _ReconPDF()
    pdf._session_id = session_id
    pdf._exported_at = exported_at
    pdf._ai_model = ai_meta.get("model_used", "N/A")
    pdf.alias_nb_pages()
    pdf.set_auto_page_break(auto=True, margin=20)
    pdf.add_page()
    page_w = pdf.w - pdf.l_margin - pdf.r_margin  # usable width (mm)

    # -- Title ----------------------------------------------------------------
    pdf.set_font("Helvetica", "B", 20)
    pdf.cell(0, 10, "RECONCILIATION REPORT", ln=True, align="C")
    pdf.set_font("Helvetica", "", 10)
    pdf.cell(0, 6, exported_at[:10], ln=True, align="C")
    pdf.ln(5)

    # -- KPI Cards (5 across) -------------------------------------------------
    card_w = page_w / 5
    card_h = 20.0
    y_cards = pdf.get_y()

    kpi_items = [
        ("GL ROWS MATCHED",     f"{gl_matched_count:,}"),
        ("GL ROWS NOT MATCHED", f"{gl_unmatched_count:,}"),
        ("MATCH RATE",          f"{match_rate:.1f}%"),
        ("MATCHED AMOUNT",      f"${matched_amount:,.2f}"),
        ("UNMATCHED AMOUNT",    f"${unmatched_amount:,.2f}"),
    ]
    for i, (label, value) in enumerate(kpi_items):
        cx = pdf.l_margin + i * card_w
        pdf.set_fill_color(245, 245, 245)
        pdf.rect(cx, y_cards, card_w - 1, card_h, style="FD")
        pdf.set_font("Helvetica", "", 6)
        pdf.set_text_color(100, 100, 100)
        pdf.set_xy(cx + 1, y_cards + 2)
        pdf.cell(card_w - 2, 4, label, align="C")
        pdf.set_font("Helvetica", "B", 10)
        pdf.set_text_color(0, 0, 0)
        pdf.set_xy(cx + 1, y_cards + 8)
        pdf.cell(card_w - 2, 9, value, align="C")

    pdf.set_y(y_cards + card_h + 5)

    # -- Match Breakdown ------------------------------------------------------
    pdf.set_font("Helvetica", "B", 12)
    pdf.set_text_color(0, 0, 0)
    pdf.cell(0, 8, "Match Breakdown", ln=True)
    pdf.set_font("Helvetica", "I", 8)
    pdf.set_text_color(100, 100, 100)
    pdf.cell(0, 4, f"GL row distribution across match layers (total: {gl_total:,} GL rows)", ln=True)
    pdf.set_text_color(0, 0, 0)
    pdf.ln(2)

    segments = [
        ("Deterministic", len(det_ids),         det_amount,       _SEG_COLORS[0]),
        ("Probabilistic", len(prob_ids),         prob_amount,      _SEG_COLORS[1]),
        ("AI Matches",    len(ai_ids | man_ids), ai_amount,        _SEG_COLORS[2]),
        ("Unmatched",     len(res_gl_ids),       unmatched_amount, _SEG_COLORS[3]),
    ]
    breakdown_h = _draw_breakdown_bar(pdf, segments, gl_total,
                                      pdf.l_margin, pdf.get_y(), page_w)
    pdf.set_y(pdf.get_y() + breakdown_h)
    pdf.ln(3)

    # -- Summary --------------------------------------------------------------
    pdf.set_font("Helvetica", "B", 12)
    pdf.cell(0, 8, "Summary", ln=True)
    pdf.set_font("Helvetica", "", 9)
    safe_narrative = (narrative or "No narrative available.").encode("latin-1", errors="replace").decode("latin-1")
    pdf.multi_cell(0, 5, safe_narrative)
    pdf.ln(5)

    # -- Charts ---------------------------------------------------------------
    pdf.set_font("Helvetica", "B", 12)
    pdf.cell(0, 8, "Charts", ln=True)
    pdf.set_font("Helvetica", "I", 8)
    pdf.set_text_color(100, 100, 100)
    pdf.cell(0, 4, "Left side of page: GL record count by vendor   |   Right side of page: GL dollar amount by vendor", ln=True)
    pdf.set_text_color(0, 0, 0)
    pdf.ln(2)

    chart_w = page_w / 2 - 2.0
    y_charts = pdf.get_y()

    count_vendor_data  = [(v[0], v[1], v[2]) for v in vendor_data]
    dollar_vendor_data = [(v[0], v[3], v[4]) for v in vendor_data]

    h_left  = _draw_vendor_chart(pdf, count_vendor_data,  "GL Record Count by Vendor",
                                 pdf.l_margin, y_charts, chart_w, dollar=False, max_vendors=5)
    h_right = _draw_vendor_chart(pdf, dollar_vendor_data, "GL Dollar Amount by Vendor",
                                 pdf.l_margin + chart_w + 4, y_charts, chart_w, dollar=True, max_vendors=5)

    pdf.set_y(y_charts + max(h_left, h_right) + 3)

    # -- Rejected & Override Detail -------------------------------------------
    pdf.ln(2)
    _add_vendor_detail_section(
        pdf, "Rejected Matches",
        len(rej_gl_ids), rej_amount,
        v_rej_count, v_rej_dollars, page_w,
    )
    pdf.ln(4)
    _add_vendor_detail_section(
        pdf, "Manual Overrides",
        override_count, override_amount,
        v_over_count, v_over_dollars, page_w,
    )

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
    manual_rejected:  Optional[List[dict]] = None,            # [{match_id, record_ids_A, record_ids_B}]
    matching_config:  Optional[dict] = None,                  # runtime["config"]["matching_config"]
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

    # -- 0. recon_criteria.json ────────────────────────────────────────────
    criteria_payload = matching_config or {}
    criteria_content = json.dumps(criteria_payload, indent=2, default=str).encode("utf-8")
    manifest.files.append(
        _write_file(os.path.join(export_dir, "recon_criteria.json"), criteria_content)
    )

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

    # Collect GL/Sub IDs from manually-rejected matches that are NOT overridden.
    manually_rejected_gl_ids:  List[str] = []
    manually_rejected_sub_ids: List[str] = []
    for entry in (manual_rejected or []):
        for gid in entry.get("record_ids_A", []):
            s = str(gid)
            if s and s not in overridden_gl_ids:
                manually_rejected_gl_ids.append(s)
        for sid in entry.get("record_ids_B", []):
            s = str(sid)
            if s and s not in overridden_sub_ids:
                manually_rejected_sub_ids.append(s)

    # -- 8. residual_unmatched_gl.csv ──────────────────────────────────────
    # Backend residuals + manually-rejected GL rows (minus overrides).
    gl_res = residual_gl if residual_gl is not None else pd.DataFrame()
    if overridden_gl_ids and not gl_res.empty and "gl_id" in gl_res.columns:
        gl_res = gl_res[~gl_res["gl_id"].astype(str).isin(overridden_gl_ids)].copy()
    if manually_rejected_gl_ids:
        extra_gl_rows = [
            gl_lookup[gid] for gid in manually_rejected_gl_ids
            if gid in gl_lookup
            and (gl_res.empty or gid not in gl_res.get("gl_id", pd.Series(dtype=str)).astype(str).values)
        ]
        if extra_gl_rows:
            extra_gl_df = pd.DataFrame(extra_gl_rows)
            gl_res = pd.concat([gl_res, extra_gl_df], ignore_index=True) if not gl_res.empty else extra_gl_df
    manifest.files.append(
        _write_dataframe_csv(gl_res, os.path.join(export_dir, "residual_unmatched_gl.csv"))
    )

    # -- 9. residual_unmatched_sub.csv ─────────────────────────────────────
    # Backend residuals + manually-rejected Sub rows (minus overrides).
    sub_res = residual_sub if residual_sub is not None else pd.DataFrame()
    if overridden_sub_ids and not sub_res.empty and "subledger_id" in sub_res.columns:
        sub_res = sub_res[~sub_res["subledger_id"].astype(str).isin(overridden_sub_ids)].copy()
    if manually_rejected_sub_ids:
        extra_sub_rows = [
            sub_lookup[sid] for sid in manually_rejected_sub_ids
            if sid in sub_lookup
            and (sub_res.empty or sid not in sub_res.get("subledger_id", pd.Series(dtype=str)).astype(str).values)
        ]
        if extra_sub_rows:
            extra_sub_df = pd.DataFrame(extra_sub_rows)
            sub_res = pd.concat([sub_res, extra_sub_df], ignore_index=True) if not sub_res.empty else extra_sub_df
    manifest.files.append(
        _write_dataframe_csv(sub_res, os.path.join(export_dir, "residual_unmatched_sub.csv"))
    )

    # -- 10. rejected_matches.csv ──────────────────────────────────────────
    # Pipeline-rejected + UI-manually-rejected matches.
    ui_rejected_synthetic = [
        {
            "match_id":      entry.get("match_id", f"UI_REJECTED_{i}"),
            "record_ids_A":  entry.get("record_ids_A", []),
            "record_ids_B":  entry.get("record_ids_B", []),
            "user_status":   "ui_rejected",
            "grouping_type": "one_to_one",
            "override_flag": False,
        }
        for i, entry in enumerate(manual_rejected or [])
    ]
    all_rejected = rejected + ui_rejected_synthetic
    rej_df = _expand_matches_with_data(all_rejected, "rejected", gl_lookup, sub_lookup)
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
    # Build amount map for narrative stats (rejected/override amounts only known here).
    _gl_df_exp = clean_data.get("gl")
    if _gl_df_exp is None:
        _gl_df_exp = pd.DataFrame()
    _gl_amt_map: Dict[str, float] = {}
    if not _gl_df_exp.empty and "gl_id" in _gl_df_exp.columns and "amount" in _gl_df_exp.columns:
        _gl_amt_map = dict(zip(
            _gl_df_exp["gl_id"].astype(str),
            pd.to_numeric(_gl_df_exp["amount"], errors="coerce").fillna(0.0),
        ))

    def _amt(ids: set) -> float:
        return sum(_gl_amt_map.get(gid, 0.0) for gid in ids)

    _det_ids  = {str(x) for m in det_matches  for x in m.get("record_ids_A", [])}
    _prob_ids = {str(x) for m in prob_accepted for x in m.get("record_ids_A", [])}
    _ai_ids   = {str(x) for m in ai_final      for x in m.get("record_ids_A", [])}
    _man_ids  = {str(gid) for gid in (manual_overrides or {})}
    _matched  = _det_ids | _prob_ids | _ai_ids | _man_ids
    _rej_ids  = {str(x) for m in all_rejected  for x in m.get("record_ids_A", [])}
    _res_ids  = (
        set(gl_res["gl_id"].astype(str))
        if not gl_res.empty and "gl_id" in gl_res.columns
        else set()
    )
    _gl_total = len(_gl_df_exp)

    from src.services.summary_narrative_service import generate_summary_narrative
    _narrative = generate_summary_narrative({
        "perspective": "GL",
        "note": "All counts are GL row counts from the General Ledger perspective.",
        "summary": {
            "gl_total_rows":         _gl_total,
            "gl_matched_rows":       len(_matched),
            "gl_unmatched_rows":     len(_res_ids),
            "match_rate_pct":        round(len(_matched) / _gl_total * 100, 1) if _gl_total else 0.0,
            "gl_rows_deterministic": len(_det_ids),
            "gl_rows_probabilistic": len(_prob_ids),
            "gl_rows_ai":            len(_ai_ids) + len(_man_ids),
            "rejected_count":        len(_rej_ids),
            "rejected_amount":       round(_amt(_rej_ids), 2),
            "override_count":        len(_man_ids),
            "override_amount":       round(_amt(_man_ids), 2),
            "matched_amount":        round(_amt(_matched), 2),
            "unmatched_amount":      round(_amt(_res_ids), 2),
        },
    })

    pdf_bytes = _build_pdf(
        session_id=session_id,
        consolidation=consolidation,
        ai_meta=ai_meta,
        exported_at=exported_at,
        gl_df=_gl_df_exp,
        final_matches=det_matches + prob_accepted + ai_final,
        residual_gl_df=gl_res,
        all_rejected=all_rejected,
        gl_lookup=gl_lookup,
        manual_overrides=manual_overrides,
        det_matches=det_matches,
        prob_accepted=prob_accepted,
        ai_final=ai_final,
        narrative=_narrative,
    )
    manifest.files.append(
        _write_file(os.path.join(export_dir, "reconciliation_report.pdf"), pdf_bytes)
    )

    return manifest
