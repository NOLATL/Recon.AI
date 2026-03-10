"""
Intake service — validates and loads the three required CSV files.

Responsibilities:
- Enforce filename contract
- Run strict schema validation via validate_file()
- Collect ALL validation errors across ALL files before raising
- Raise FileValidationError (structured) if any file is invalid
- Return IntakeResult on success — DataFrames + per-file validation metadata

Architecture note: this module has no knowledge of sessions or state.
The route handler owns the session interaction.
"""

import io
from dataclasses import dataclass
from typing import Dict, Optional

import pandas as pd
from fastapi import UploadFile

from src.preprocessing.schema import FileValidationResult, validate_file
from src.exceptions import FileValidationError


REQUIRED_FILES: Dict[str, str] = {
    "gl":        "GL.csv",
    "subledger": "Subledger.csv",
}

# Optional files — validated if provided, skipped if absent
OPTIONAL_FILES: Dict[str, str] = {
    "chart_of_accounts": "Chart_of_Accounts.csv",
}


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------

@dataclass
class IntakeResult:
    """
    Returned by validate_and_load() when all three files pass validation.

    DataFrames have types fully applied (float64, datetime, bool, string).
    validation_results carries per-file metadata for the API response.
    """
    dataframes: Dict[str, pd.DataFrame]
    validation_results: Dict[str, FileValidationResult]

    @property
    def row_counts(self) -> Dict[str, int]:
        return {key: len(df) for key, df in self.dataframes.items()}

    @property
    def schema_hashes(self) -> Dict[str, str]:
        return {key: r.schema_hash for key, r in self.validation_results.items()}


# ---------------------------------------------------------------------------
# Service function
# ---------------------------------------------------------------------------

def validate_and_load(files: Dict[str, UploadFile]) -> IntakeResult:
    """
    Validate all three uploaded CSV files against their registered schemas.

    Processing order:
      1. Presence check — all three keys must be provided
      2. Filename contract — each UploadFile must have the expected filename
      3. CSV parse — read into DataFrame
      4. Schema validation — strict, row-level, exhaustive
      5. Collect all errors; raise FileValidationError if any file fails
      6. Return IntakeResult with clean DataFrames on full success

    Raises:
        FileValidationError — one or more files failed validation;
                              carries structured per-file error data
        ValueError          — a required file key is missing from `files`
    """
    # Step 1: presence check for required files
    for key, expected_name in REQUIRED_FILES.items():
        if key not in files:
            raise ValueError(f"Missing required file: '{expected_name}' (key: '{key}')")

    # Steps 2–4: parse and validate each file (required + any provided optional files)
    files_to_process = {**REQUIRED_FILES}
    for key, expected_name in OPTIONAL_FILES.items():
        if key in files:
            files_to_process[key] = expected_name

    dataframes: Dict[str, Optional[pd.DataFrame]] = {}
    results: Dict[str, FileValidationResult] = {}
    errors: list = []

    for key, expected_name in files_to_process.items():
        upload: UploadFile = files[key]

        # Filename contract — exact match required
        if upload.filename != expected_name:
            raise ValueError(
                f"Expected filename '{expected_name}', received '{upload.filename}'"
            )

        # Parse CSV
        raw_bytes = upload.file.read()
        df_raw = pd.read_csv(io.BytesIO(raw_bytes))

        # Strict schema validation
        df_clean, result = validate_file(df_raw, key)

        results[key] = result
        if result.is_valid:
            dataframes[key] = df_clean
        else:
            errors.append(result.to_dict())

    # Step 5: raise if any file failed
    if errors:
        raise FileValidationError(errors)

    # Step 6: all valid — return typed DataFrames with validation metadata
    return IntakeResult(
        dataframes=dataframes,
        validation_results=results,
    )
