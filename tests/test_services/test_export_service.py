"""
Unit tests for src/services/export_service.py

Tests every explicit requirement:

  [ExportManifest structure]
  - Contains export_dir, exported_at, files
  - exported_at is a non-empty ISO timestamp string
  - export_dir exists on disk after run_export

  [File set]
  - Exactly 6 files generated
  - Expected filenames: final_matches.csv, residual_unmatched_gl.csv,
    residual_unmatched_sub.csv, rejected_matches.csv, audit_log.csv,
    reconciliation_report.pdf
  - All files exist on disk

  [File metadata]
  - sha256 is 64 hex characters
  - size_bytes > 0 for each file
  - filename matches os.path.basename(path)

  [CSV content — final_matches.csv]
  - Row count == len(all_matches)
  - Contains match_id, source_layer, user_status columns
  - source_layer detected correctly (deterministic/probabilistic/ai)
  - Empty all_matches → header-only CSV (0 data rows)

  [CSV content — residual files]
  - residual_unmatched_gl.csv rows == len(residual_gl)
  - residual_unmatched_sub.csv rows == len(residual_sub)
  - Empty residual → header-only or empty file

  [CSV content — rejected_matches.csv]
  - Row count == len(rejected)
  - Empty rejected → 0 data rows

  [CSV content — audit_log.csv]
  - Audit log includes all_matches entries
  - Audit log includes rejected entries
  - Audit log includes pending prob entries
  - Audit log includes pending ai_suggested entries
  - Row count == accepted + pending_prob + pending_ai + rejected

  [PDF]
  - reconciliation_report.pdf exists and size_bytes > 0
  - PDF starts with %PDF magic bytes

  [Source layer detection]
  - detect_source_layer: scenario_id present → 'deterministic'
  - detect_source_layer: final_similarity present → 'probabilistic'
  - detect_source_layer: ai_confidence_score present → 'ai'
  - detect_source_layer: none of the above → 'unknown'

  [Edge cases]
  - All inputs empty → 6 files, 0 data rows in CSVs, non-empty PDF
  - Custom export_dir respected (no new tempdir created)
"""

import hashlib
import os

import pandas as pd
import pytest

from src.services.export_service import (
    ExportManifest,
    detect_source_layer,
    run_export,
)


# ---------------------------------------------------------------------------
# Match builders
# ---------------------------------------------------------------------------

def _det(match_id: str = "D1", gl_id: str = "GL1", sub_id: str = "S1") -> dict:
    return {
        "match_id":             match_id,
        "record_ids_A":         [gl_id],
        "record_ids_B":         [sub_id],
        "scenario_id":          1,
        "scenario_description": "Exact match",
        "confidence_score":     1.0,
        "grouping_type":        "one_to_one",
        "user_status":          "auto_confirmed",
        "override_flag":        False,
    }


def _prob(match_id: str = "P1", gl_id: str = "GL3", sub_id: str = "S3",
          user_status: str = "accepted") -> dict:
    return {
        "match_id":         match_id,
        "record_ids_A":     [gl_id],
        "record_ids_B":     [sub_id],
        "final_similarity": 0.92,
        "component_scores": {},
        "grouping_type":    "one_to_one",
        "user_status":      user_status,
        "override_flag":    False,
    }


def _ai(match_id: str = "A1", gl_id: str = "GL5", sub_id: str = "S5",
        user_status: str = "accepted") -> dict:
    return {
        "match_id":            match_id,
        "record_ids_A":        [gl_id],
        "record_ids_B":        [sub_id],
        "ai_confidence_score": 0.90,
        "materiality":         1000.0,
        "supporting_features": {},
        "reasoning_narrative": "Test narrative.",
        "grouping_type":       "one_to_one",
        "user_status":         user_status,
        "override_flag":       False,
    }


def _gl_df(*ids) -> pd.DataFrame:
    return pd.DataFrame([{"gl_id": i, "amount": 100.0} for i in ids])


def _sub_df(*ids) -> pd.DataFrame:
    return pd.DataFrame([{"subledger_id": i, "amount": 100.0} for i in ids])


# ---------------------------------------------------------------------------
# Run helper
# ---------------------------------------------------------------------------

def _run(
    all_matches=None,
    prob_matches=None,
    ai_suggested=None,
    rejected=None,
    residual_gl=None,
    residual_sub=None,
    ai_meta=None,
    consolidation=None,
    tmp_path=None,
) -> ExportManifest:
    return run_export(
        all_matches=   all_matches   or [],
        prob_matches=  prob_matches  or [],
        ai_suggested=  ai_suggested  or [],
        rejected=      rejected      or [],
        residual_gl=   residual_gl   if residual_gl  is not None else pd.DataFrame(),
        residual_sub=  residual_sub  if residual_sub is not None else pd.DataFrame(),
        ai_meta=       ai_meta       or {},
        consolidation= consolidation or {},
        session_id=    "test-session-id",
        export_dir=    str(tmp_path) if tmp_path is not None else None,
    )


_EXPECTED_FILENAMES = {
    "final_matches.csv",
    "residual_unmatched_gl.csv",
    "residual_unmatched_sub.csv",
    "rejected_matches.csv",
    "audit_log.csv",
    "reconciliation_report.pdf",
}


# ===========================================================================
# ExportManifest structure
# ===========================================================================

class TestManifestStructure:
    def test_export_dir_present(self, tmp_path):
        m = _run(tmp_path=tmp_path)
        assert m.export_dir == str(tmp_path)

    def test_exported_at_non_empty(self, tmp_path):
        m = _run(tmp_path=tmp_path)
        assert len(m.exported_at) > 0

    def test_exported_at_is_iso_string(self, tmp_path):
        m = _run(tmp_path=tmp_path)
        # Should contain a 'T' separator and '+' or 'Z' timezone
        assert "T" in m.exported_at

    def test_export_dir_exists_on_disk(self, tmp_path):
        m = _run(tmp_path=tmp_path)
        assert os.path.isdir(m.export_dir)


# ===========================================================================
# File set
# ===========================================================================

class TestFileSet:
    def test_exactly_six_files(self, tmp_path):
        m = _run(tmp_path=tmp_path)
        assert len(m.files) == 6

    def test_expected_filenames_present(self, tmp_path):
        m = _run(tmp_path=tmp_path)
        names = {f.filename for f in m.files}
        assert names == _EXPECTED_FILENAMES

    def test_all_files_exist_on_disk(self, tmp_path):
        m = _run(tmp_path=tmp_path)
        for ef in m.files:
            assert os.path.isfile(ef.path), f"Missing: {ef.path}"


# ===========================================================================
# File metadata
# ===========================================================================

class TestFileMetadata:
    def test_sha256_is_64_hex_chars(self, tmp_path):
        m = _run(tmp_path=tmp_path)
        for ef in m.files:
            assert len(ef.sha256) == 64, f"{ef.filename}: sha256 wrong length"
            int(ef.sha256, 16)  # must parse as hex

    def test_size_bytes_positive(self, tmp_path):
        """All files have content when every input has at least one record."""
        m = _run(
            all_matches=  [_det()],
            residual_gl=  _gl_df("GL_R1"),
            residual_sub= _sub_df("S_R1"),
            rejected=     [_prob("P_R1", user_status="rejected")],
            tmp_path=tmp_path,
        )
        for ef in m.files:
            assert ef.size_bytes > 0, f"{ef.filename}: size_bytes == 0"

    def test_sha256_matches_file_content(self, tmp_path):
        m = _run(all_matches=[_det()], tmp_path=tmp_path)
        for ef in m.files:
            with open(ef.path, "rb") as fh:
                computed = hashlib.sha256(fh.read()).hexdigest()
            assert ef.sha256 == computed, f"{ef.filename}: sha256 mismatch"

    def test_filename_matches_basename(self, tmp_path):
        m = _run(tmp_path=tmp_path)
        for ef in m.files:
            assert ef.filename == os.path.basename(ef.path)


# ===========================================================================
# CSV content — final_matches.csv
# ===========================================================================

class TestFinalMatchesCsv:
    def _get_df(self, manifest) -> pd.DataFrame:
        path = next(f.path for f in manifest.files if f.filename == "final_matches.csv")
        return pd.read_csv(path)

    def test_row_count_matches_all_matches(self, tmp_path):
        m = _run(all_matches=[_det("D1"), _det("D2"), _prob("P1")], tmp_path=tmp_path)
        df = self._get_df(m)
        assert len(df) == 3

    def test_contains_match_id_column(self, tmp_path):
        m = _run(all_matches=[_det()], tmp_path=tmp_path)
        df = self._get_df(m)
        assert "match_id" in df.columns

    def test_contains_source_layer_column(self, tmp_path):
        m = _run(all_matches=[_det()], tmp_path=tmp_path)
        df = self._get_df(m)
        assert "source_layer" in df.columns

    def test_contains_user_status_column(self, tmp_path):
        m = _run(all_matches=[_det()], tmp_path=tmp_path)
        df = self._get_df(m)
        assert "user_status" in df.columns

    def test_deterministic_layer_detected(self, tmp_path):
        m = _run(all_matches=[_det("D1")], tmp_path=tmp_path)
        df = self._get_df(m)
        assert df.loc[df["match_id"] == "D1", "source_layer"].iloc[0] == "deterministic"

    def test_probabilistic_layer_detected(self, tmp_path):
        m = _run(all_matches=[_prob("P1")], tmp_path=tmp_path)
        df = self._get_df(m)
        assert df.loc[df["match_id"] == "P1", "source_layer"].iloc[0] == "probabilistic"

    def test_ai_layer_detected(self, tmp_path):
        m = _run(all_matches=[_ai("A1")], tmp_path=tmp_path)
        df = self._get_df(m)
        assert df.loc[df["match_id"] == "A1", "source_layer"].iloc[0] == "ai"

    def test_empty_all_matches_zero_rows(self, tmp_path):
        m = _run(tmp_path=tmp_path)
        df = self._get_df(m)
        assert len(df) == 0


# ===========================================================================
# CSV content — residual files
# ===========================================================================

class TestResidualCsvs:
    def _get_gl_df(self, manifest) -> pd.DataFrame:
        path = next(f.path for f in manifest.files if f.filename == "residual_unmatched_gl.csv")
        try:
            return pd.read_csv(path)
        except pd.errors.EmptyDataError:
            return pd.DataFrame()

    def _get_sub_df(self, manifest) -> pd.DataFrame:
        path = next(f.path for f in manifest.files if f.filename == "residual_unmatched_sub.csv")
        try:
            return pd.read_csv(path)
        except pd.errors.EmptyDataError:
            return pd.DataFrame()

    def test_gl_row_count(self, tmp_path):
        m = _run(residual_gl=_gl_df("GL_R1", "GL_R2"), tmp_path=tmp_path)
        assert len(self._get_gl_df(m)) == 2

    def test_sub_row_count(self, tmp_path):
        m = _run(residual_sub=_sub_df("S_R1", "S_R2", "S_R3"), tmp_path=tmp_path)
        assert len(self._get_sub_df(m)) == 3

    def test_empty_residual_zero_rows(self, tmp_path):
        m = _run(tmp_path=tmp_path)
        assert len(self._get_gl_df(m)) == 0
        assert len(self._get_sub_df(m)) == 0


# ===========================================================================
# CSV content — rejected_matches.csv
# ===========================================================================

class TestRejectedCsv:
    def _get_df(self, manifest) -> pd.DataFrame:
        path = next(f.path for f in manifest.files if f.filename == "rejected_matches.csv")
        return pd.read_csv(path)

    def test_row_count(self, tmp_path):
        m = _run(
            rejected=[
                _prob("P_R1", user_status="rejected"),
                _ai("A_R1", user_status="rejected"),
            ],
            tmp_path=tmp_path,
        )
        assert len(self._get_df(m)) == 2

    def test_empty_rejected_zero_rows(self, tmp_path):
        m = _run(tmp_path=tmp_path)
        assert len(self._get_df(m)) == 0


# ===========================================================================
# CSV content — audit_log.csv
# ===========================================================================

class TestAuditLogCsv:
    def _get_df(self, manifest) -> pd.DataFrame:
        path = next(f.path for f in manifest.files if f.filename == "audit_log.csv")
        return pd.read_csv(path)

    def test_includes_accepted_matches(self, tmp_path):
        m = _run(all_matches=[_det("D1"), _ai("A1")], tmp_path=tmp_path)
        df = self._get_df(m)
        ids = set(df["match_id"].astype(str))
        assert "D1" in ids
        assert "A1" in ids

    def test_includes_rejected_matches(self, tmp_path):
        m = _run(rejected=[_prob("P_R1", user_status="rejected")], tmp_path=tmp_path)
        df = self._get_df(m)
        assert "P_R1" in set(df["match_id"].astype(str))

    def test_includes_pending_prob(self, tmp_path):
        m = _run(prob_matches=[_prob("P_PEND", user_status="pending")], tmp_path=tmp_path)
        df = self._get_df(m)
        assert "P_PEND" in set(df["match_id"].astype(str))

    def test_includes_pending_ai(self, tmp_path):
        m = _run(ai_suggested=[_ai("A_PEND", user_status="pending")], tmp_path=tmp_path)
        df = self._get_df(m)
        assert "A_PEND" in set(df["match_id"].astype(str))

    def test_row_count_is_all_sources(self, tmp_path):
        m = _run(
            all_matches=  [_det("D1")],
            prob_matches= [_prob("P1", user_status="accepted"),
                           _prob("P2", user_status="pending")],
            ai_suggested= [_ai("A_PEND", user_status="pending")],
            rejected=     [_ai("A_REJ", user_status="rejected")],
            tmp_path=tmp_path,
        )
        df = self._get_df(m)
        # D1 (accepted det) + P2 (pending prob) + A_PEND (pending ai) + A_REJ (rejected)
        # P1 is accepted so in all_matches already via caller; but audit includes all
        # Note: accepted prob P1 should be in all_matches, and prob_matches contains P1+P2
        # pending_prob filtered in service = [P2]
        # audit = all_matches[D1] + pending_prob[P2] + ai_suggested[A_PEND] + rejected[A_REJ]
        assert len(df) == 4

    def test_audit_accepted_prob_not_duplicated(self, tmp_path):
        """Accepted prob is in all_matches; prob_matches accepted is NOT added again."""
        accepted_prob = _prob("P1", user_status="accepted")
        m = _run(
            all_matches=  [accepted_prob],
            prob_matches= [accepted_prob],   # same match, user_status=accepted → not pending
            tmp_path=tmp_path,
        )
        df = self._get_df(m)
        # P1 appears only once (from all_matches; pending filter skips it)
        p1_rows = df[df["match_id"] == "P1"]
        assert len(p1_rows) == 1


# ===========================================================================
# PDF
# ===========================================================================

class TestPdf:
    def _get_pdf_file(self, manifest):
        return next(f for f in manifest.files if f.filename == "reconciliation_report.pdf")

    def test_pdf_exists(self, tmp_path):
        m = _run(tmp_path=tmp_path)
        ef = self._get_pdf_file(m)
        assert os.path.isfile(ef.path)

    def test_pdf_size_positive(self, tmp_path):
        m = _run(tmp_path=tmp_path)
        ef = self._get_pdf_file(m)
        assert ef.size_bytes > 0

    def test_pdf_magic_bytes(self, tmp_path):
        m = _run(tmp_path=tmp_path)
        ef = self._get_pdf_file(m)
        with open(ef.path, "rb") as fh:
            header = fh.read(5)
        assert header == b"%PDF-"

    def test_pdf_is_non_trivial_size(self, tmp_path):
        """PDF with real content should be substantially larger than a blank page."""
        m = run_export(
            all_matches=[], prob_matches=[], ai_suggested=[], rejected=[],
            residual_gl=pd.DataFrame(), residual_sub=pd.DataFrame(),
            ai_meta={}, consolidation={"total_match_count": 0},
            session_id="UNIQSESSID",
            export_dir=str(tmp_path),
        )
        ef = next(f for f in m.files if f.filename == "reconciliation_report.pdf")
        # A real multi-section report should exceed 500 bytes.
        assert ef.size_bytes > 500


# ===========================================================================
# Source layer detection
# ===========================================================================

class TestDetectSourceLayer:
    def test_scenario_id_is_deterministic(self):
        assert detect_source_layer({"scenario_id": 1}) == "deterministic"

    def test_final_similarity_is_probabilistic(self):
        assert detect_source_layer({"final_similarity": 0.9}) == "probabilistic"

    def test_ai_confidence_score_is_ai(self):
        assert detect_source_layer({"ai_confidence_score": 0.8}) == "ai"

    def test_no_known_field_is_unknown(self):
        assert detect_source_layer({"match_id": "X1"}) == "unknown"

    def test_scenario_id_takes_precedence(self):
        """If both scenario_id and final_similarity present → deterministic."""
        assert detect_source_layer({"scenario_id": 1, "final_similarity": 0.9}) == "deterministic"


# ===========================================================================
# Edge cases
# ===========================================================================

class TestEdgeCases:
    def test_all_empty_no_error(self, tmp_path):
        m = _run(tmp_path=tmp_path)
        assert len(m.files) == 6

    def test_custom_export_dir_respected(self, tmp_path):
        m = _run(tmp_path=tmp_path)
        assert m.export_dir == str(tmp_path)

    def test_auto_tempdir_created_when_no_dir_given(self):
        """Without export_dir, service creates a temp directory."""
        m = run_export(
            all_matches=[], prob_matches=[], ai_suggested=[], rejected=[],
            residual_gl=pd.DataFrame(), residual_sub=pd.DataFrame(),
            ai_meta={}, consolidation={},
            session_id="auto-dir-test",
        )
        try:
            assert os.path.isdir(m.export_dir)
        finally:
            # Clean up temp dir
            import shutil
            if os.path.isdir(m.export_dir):
                shutil.rmtree(m.export_dir, ignore_errors=True)

    def test_large_match_list(self, tmp_path):
        """100 matches should export without error."""
        matches = [_det(f"D{i}", f"GL{i}", f"S{i}") for i in range(100)]
        m = _run(all_matches=matches, tmp_path=tmp_path)
        path = next(f.path for f in m.files if f.filename == "final_matches.csv")
        df = pd.read_csv(path)
        assert len(df) == 100
