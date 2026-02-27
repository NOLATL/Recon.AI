"""
Export Service — Phase 8: final_consolidated → finalized

Pure function that generates all output files from the finalized reconciliation.

Generated files:
  final_matches.csv          — All accepted matches (det + accepted_prob + ai_accepted)
  residual_unmatched_gl.csv  — Unmatched GL records remaining after all phases
  residual_unmatched_sub.csv — Unmatched subledger records remaining after all phases
  rejected_matches.csv       — All rejected matches from Phases 5A and 6A
  audit_log.csv              — Complete audit trail: every match that entered the system
  reconciliation_report.pdf  — Executive summary, statistics, override summary, AI insights

Storage: Local temp directory (MVP).
Future-ready: swap _write_file() for blob upload calls (Azure Blob Storage).

Source layer detection:
  'scenario_id' present    → deterministic
  'final_similarity' present → probabilistic
  'ai_confidence_score' present → ai
"""

import hashlib
import os
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import List, Optional

import pandas as pd
from fpdf import FPDF


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class ExportFile:
    """Metadata for one generated file."""
    filename:   str
    path:       str   # absolute local path (swap for blob URL in production)
    sha256:     str   # hex digest
    size_bytes: int


@dataclass
class ExportManifest:
    """Output of run_export()."""
    export_dir:  str
    exported_at: str          # ISO-8601 UTC timestamp
    files:       List[ExportFile] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Source layer detection (pure utility)
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
# CSV builders
# ---------------------------------------------------------------------------

_AUDIT_COLUMNS = [
    "match_id",
    "source_layer",
    "user_status",
    "record_ids_A",
    "record_ids_B",
    "confidence",
    "grouping_type",
    "override_flag",
]

_MATCH_COLUMNS = [
    "match_id",
    "source_layer",
    "user_status",
    "record_ids_A",
    "record_ids_B",
    "confidence",
    "grouping_type",
    "override_flag",
]


def _normalise_match(match: dict) -> dict:
    """Flatten a heterogeneous match dict to a canonical row."""
    layer = detect_source_layer(match)
    confidence = (
        match.get("confidence_score")
        or match.get("final_similarity")
        or match.get("ai_confidence_score")
        or ""
    )
    return {
        "match_id":     match.get("match_id", ""),
        "source_layer": layer,
        "user_status":  match.get("user_status", ""),
        "record_ids_A": ",".join(str(x) for x in match.get("record_ids_A", [])),
        "record_ids_B": ",".join(str(x) for x in match.get("record_ids_B", [])),
        "confidence":   confidence,
        "grouping_type": match.get("grouping_type", ""),
        "override_flag": match.get("override_flag", False),
    }


def _matches_to_df(matches: List[dict], columns: List[str]) -> pd.DataFrame:
    if not matches:
        return pd.DataFrame(columns=columns)
    rows = [_normalise_match(m) for m in matches]
    return pd.DataFrame(rows, columns=columns)


# ---------------------------------------------------------------------------
# File I/O helpers (Future-ready: swap for blob upload)
# ---------------------------------------------------------------------------

def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _write_file(path: str, content: bytes) -> ExportFile:
    """Write bytes to path, return ExportFile metadata."""
    with open(path, "wb") as fh:
        fh.write(content)
    return ExportFile(
        filename=   os.path.basename(path),
        path=       path,
        sha256=     _sha256(content),
        size_bytes= len(content),
    )


def _write_dataframe_csv(df: pd.DataFrame, path: str) -> ExportFile:
    # A truly columnless DataFrame produces "\n" which pd.read_csv cannot parse.
    # Write empty bytes so callers can detect and handle an empty file cleanly.
    if len(df.columns) == 0:
        content = b""
    else:
        content = df.to_csv(index=False).encode("utf-8")
    return _write_file(path, content)


# ---------------------------------------------------------------------------
# PDF builder
# ---------------------------------------------------------------------------

def _build_pdf(
    session_id:   str,
    consolidation: dict,
    ai_meta:      dict,
    exported_at:  str,
) -> bytes:
    """Generate a PDF reconciliation report using fpdf2."""
    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()

    # ── Title ──────────────────────────────────────────────────────────────
    pdf.set_font("Helvetica", "B", 18)
    pdf.cell(0, 12, "Reconciliation Report", ln=True, align="C")
    pdf.set_font("Helvetica", "", 10)
    pdf.cell(0, 6, f"Generated: {exported_at}", ln=True, align="C")
    pdf.ln(6)

    # ── Executive Summary ──────────────────────────────────────────────────
    pdf.set_font("Helvetica", "B", 13)
    pdf.cell(0, 9, "Executive Summary", ln=True)
    pdf.set_font("Helvetica", "", 10)
    pdf.cell(0, 6, f"Session ID : {session_id}", ln=True)
    pdf.cell(0, 6, f"Final State: finalized", ln=True)
    pdf.cell(0, 6, f"Report Date: {exported_at[:10]}", ln=True)
    pdf.ln(4)

    # ── Reconciliation Statistics ──────────────────────────────────────────
    pdf.set_font("Helvetica", "B", 13)
    pdf.cell(0, 9, "Reconciliation Statistics", ln=True)

    stats = [
        ("Deterministic Matches",    consolidation.get("deterministic_match_count", 0)),
        ("Probabilistic Matches (accepted)", consolidation.get("probabilistic_match_count", 0)),
        ("AI-Assisted Matches (accepted)",   consolidation.get("ai_match_count", 0)),
        ("Total Accepted Matches",   consolidation.get("total_match_count", 0)),
        ("Residual GL Records",      consolidation.get("residual_gl_count", 0)),
        ("Residual Subledger Records", consolidation.get("residual_sub_count", 0)),
        ("Rejected Matches",         consolidation.get("rejected_count", 0)),
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

    # ── Override Summary ───────────────────────────────────────────────────
    pdf.set_font("Helvetica", "B", 13)
    pdf.cell(0, 9, "Override Summary", ln=True)
    pdf.set_font("Helvetica", "", 10)
    override_count = consolidation.get("override_count", 0)
    if override_count == 0:
        pdf.cell(0, 6, "No manual overrides were applied in this reconciliation run.", ln=True)
    else:
        pdf.cell(0, 6, f"{override_count} manual override(s) were applied.", ln=True)
    pdf.ln(4)

    # ── AI Narrative Insights ──────────────────────────────────────────────
    pdf.set_font("Helvetica", "B", 13)
    pdf.cell(0, 9, "AI Narrative Insights", ln=True)
    pdf.set_font("Helvetica", "", 10)

    model_used = ai_meta.get("model_used", "")
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
        accepted_ai = consolidation.get("ai_match_count", 0)
        rejected_ai = consolidation.get("rejected_count", 0)
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
    all_matches:  List[dict],        # runtime["matching"]["final"] — accepted matches
    prob_matches: List[dict],        # runtime["matching"]["probabilistic"] — all prob
    ai_suggested: List[dict],        # runtime["matching"]["ai_suggested"] — pending AI
    rejected:     List[dict],        # runtime["matching"]["rejected"]
    residual_gl:  pd.DataFrame,      # runtime["residual_pool"]["gl"]
    residual_sub: pd.DataFrame,      # runtime["residual_pool"]["subledger"]
    ai_meta:      dict,              # runtime["ai_suggested_meta"]
    consolidation: dict,             # runtime["consolidation"]
    session_id:   str,
    export_dir:   Optional[str] = None,
) -> ExportManifest:
    """
    Generate all output files and return an ExportManifest.

    Args:
        all_matches:   Complete consolidated match list (det + accepted_prob + ai_accepted).
        prob_matches:  Full probabilistic bucket (accepted + pending).
        ai_suggested:  Remaining pending AI suggestions.
        rejected:      All rejected matches from any phase.
        residual_gl:   Unmatched GL records.
        residual_sub:  Unmatched subledger records.
        ai_meta:       AI suggestion metadata (model_used, suggestion_count, narrative).
        consolidation: Consolidation summary metrics.
        session_id:    Session identifier (used in PDF report).
        export_dir:    Optional override for output directory (used in tests).

    Returns:
        ExportManifest with file paths, hashes, and sizes.
    """
    if export_dir is None:
        export_dir = tempfile.mkdtemp(prefix=f"recon_{session_id[:8]}_")

    exported_at = datetime.now(timezone.utc).isoformat()
    manifest = ExportManifest(export_dir=export_dir, exported_at=exported_at)

    # ── 1. final_matches.csv ───────────────────────────────────────────────
    final_df = _matches_to_df(all_matches, _MATCH_COLUMNS)
    manifest.files.append(
        _write_dataframe_csv(final_df, os.path.join(export_dir, "final_matches.csv"))
    )

    # ── 2. residual_unmatched_gl.csv ───────────────────────────────────────
    # Pass the DataFrame through as-is (preserving columns on 0-row DataFrames).
    # Only substitute None with an empty DataFrame.
    gl_df = residual_gl if residual_gl is not None else pd.DataFrame()
    manifest.files.append(
        _write_dataframe_csv(gl_df, os.path.join(export_dir, "residual_unmatched_gl.csv"))
    )

    # ── 3. residual_unmatched_sub.csv ──────────────────────────────────────
    sub_df = residual_sub if residual_sub is not None else pd.DataFrame()
    manifest.files.append(
        _write_dataframe_csv(sub_df, os.path.join(export_dir, "residual_unmatched_sub.csv"))
    )

    # ── 4. rejected_matches.csv ────────────────────────────────────────────
    rejected_df = _matches_to_df(rejected, _MATCH_COLUMNS)
    manifest.files.append(
        _write_dataframe_csv(rejected_df, os.path.join(export_dir, "rejected_matches.csv"))
    )

    # ── 5. audit_log.csv ───────────────────────────────────────────────────
    # Full audit trail: accepted + pending prob + pending AI + rejected
    pending_prob = [m for m in prob_matches if m.get("user_status") == "pending"]
    all_audit = all_matches + pending_prob + ai_suggested + rejected
    audit_df = _matches_to_df(all_audit, _AUDIT_COLUMNS)
    manifest.files.append(
        _write_dataframe_csv(audit_df, os.path.join(export_dir, "audit_log.csv"))
    )

    # ── 6. reconciliation_report.pdf ──────────────────────────────────────
    pdf_bytes = _build_pdf(session_id, consolidation, ai_meta, exported_at)
    manifest.files.append(
        _write_file(os.path.join(export_dir, "reconciliation_report.pdf"), pdf_bytes)
    )

    return manifest
