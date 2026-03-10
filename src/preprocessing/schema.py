"""
Schema validation module — strict, row-level, no silent coercion.

Design rules:
- validate_file() is the primary entry point; returns (clean_df | None, FileValidationResult)
- Validation is always exhaustive: ALL column errors collected before returning
- Missing columns are a hard stop — dtype checks are skipped for that file
- NaN / empty cells are allowed (represent missing data, not bad data)
- Non-null values that cannot be cast to the declared type are row-level errors
- apply_X_schema() wrappers preserve backward-compatibility for non-intake callers
"""

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd


# ---------------------------------------------------------------------------
# Schema definitions
# ---------------------------------------------------------------------------

GL_REQUIRED_COLUMNS: List[str] = [
    "gl_id", "entity", "account_code", "vendor_name",
    "transaction_date", "amount", "currency", "exception_flag",
]
GL_DTYPES: Dict[str, str] = {
    "gl_id": "string",
    "entity": "string",
    "account_code": "string",
    "vendor_name": "string",
    "transaction_date": "datetime64[ns]",
    "amount": "float64",
    "currency": "string",
    "exception_flag": "bool",
}

SUB_REQUIRED_COLUMNS: List[str] = [
    "subledger_id", "entity", "vendor_name",
    "transaction_date", "amount", "currency", "reference_id",
]
SUB_DTYPES: Dict[str, str] = {
    "subledger_id": "string",
    "entity": "string",
    "vendor_name": "string",
    "transaction_date": "datetime64[ns]",
    "amount": "float64",
    "currency": "string",
    "reference_id": "string",
}

COA_REQUIRED_COLUMNS: List[str] = [
    "account_code", "account_name", "account_type", "materiality_threshold",
]
COA_DTYPES: Dict[str, str] = {
    "account_code": "string",
    "account_name": "string",
    "account_type": "string",
    "materiality_threshold": "float64",
}

GT_REQUIRED_COLUMNS: List[str] = [
    "gl_id", "true_exception_type", "risk_level",
    "materiality_flag", "human_override_classification", "final_classification",
]
GT_DTYPES: Dict[str, str] = {
    "gl_id": "string",
    "true_exception_type": "string",
    "risk_level": "string",
    "materiality_flag": "bool",
    "human_override_classification": "string",
    "final_classification": "string",
}

# Central registry — keyed by the file_key used in runtime["raw_data"]
SCHEMAS: Dict[str, Dict] = {
    "gl": {
        "expected_filename": "GL.csv",
        "required_columns": GL_REQUIRED_COLUMNS,
        "dtypes": GL_DTYPES,
    },
    "subledger": {
        "expected_filename": "Subledger.csv",
        "required_columns": SUB_REQUIRED_COLUMNS,
        "dtypes": SUB_DTYPES,
    },
    "chart_of_accounts": {
        "expected_filename": "Chart_of_Accounts.csv",
        "required_columns": COA_REQUIRED_COLUMNS,
        "dtypes": COA_DTYPES,
    },
    "ground_truth": {
        "expected_filename": "Ground_Truth_Exceptions.csv",
        "required_columns": GT_REQUIRED_COLUMNS,
        "dtypes": GT_DTYPES,
    },
}

# Values accepted as valid boolean representations in CSV data
_VALID_BOOL_VALUES = frozenset({
    True, False, 1, 0,
    "true", "false", "True", "False", "1", "0",
    "Y", "N", "y", "n",
})

# Canonical mapping used when casting a validated bool column
_BOOL_CAST_MAP = {
    True: True,   False: False,
    1: True,      0: False,
    "true": True,  "false": False,
    "True": True,  "False": False,
    "1": True,     "0": False,
    "Y": True,     "N": False,
    "y": True,     "n": False,
}


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------

@dataclass
class ColumnValidationError:
    column: str
    expected_dtype: str
    failing_row_count: int
    failing_row_indices: List[int]       # capped at 20 for readability
    sample_bad_values: List[str]         # capped at 5

    def to_dict(self) -> Dict[str, Any]:
        return {
            "column": self.column,
            "expected_dtype": self.expected_dtype,
            "failing_row_count": self.failing_row_count,
            "failing_row_indices": self.failing_row_indices,
            "sample_bad_values": self.sample_bad_values,
        }


@dataclass
class FileValidationResult:
    file_key: str
    expected_filename: str
    is_valid: bool
    row_count: int
    columns_validated: List[str]
    schema_hash: str
    missing_columns: List[str] = field(default_factory=list)
    column_errors: List[ColumnValidationError] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "file_key": self.file_key,
            "expected_filename": self.expected_filename,
            "is_valid": self.is_valid,
            "row_count": self.row_count,
            "columns_validated": self.columns_validated,
            "schema_hash": self.schema_hash,
            "missing_columns": self.missing_columns,
            "column_errors": [e.to_dict() for e in self.column_errors],
        }

    def to_error_message(self) -> str:
        parts = [f"[{self.file_key}]"]
        if self.missing_columns:
            parts.append(f"Missing columns: {self.missing_columns}")
        for err in self.column_errors:
            parts.append(
                f"Column '{err.column}' ({err.expected_dtype}): "
                f"{err.failing_row_count} invalid row(s) — "
                f"samples: {err.sample_bad_values}"
            )
        return " | ".join(parts)


# ---------------------------------------------------------------------------
# Schema hash
# ---------------------------------------------------------------------------

def _compute_schema_hash(
    file_key: str,
    columns: List[str],
    dtypes: Dict[str, str],
    row_count: int,
) -> str:
    """
    Deterministic fingerprint of a file's structure at validation time.
    Same columns + same dtypes + same row count → same hash.
    """
    payload = {
        "file_key": file_key,
        "columns": sorted(columns),
        "dtypes": {k: dtypes[k] for k in sorted(columns) if k in dtypes},
        "row_count": row_count,
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True).encode("utf-8")
    ).hexdigest()


# ---------------------------------------------------------------------------
# Per-type strict validators (return ColumnValidationError or None)
# ---------------------------------------------------------------------------

def _validate_float(series: pd.Series, col: str) -> Optional[ColumnValidationError]:
    """Non-null values that cannot be parsed as a number are errors."""
    numeric = pd.to_numeric(series, errors="coerce")
    bad_mask = numeric.isna() & series.notna()
    if not bad_mask.any():
        return None
    bad_idx = list(bad_mask[bad_mask].index[:20])
    sample = [str(series.loc[i]) for i in bad_idx[:5]]
    return ColumnValidationError(
        column=col,
        expected_dtype="float64",
        failing_row_count=int(bad_mask.sum()),
        failing_row_indices=bad_idx,
        sample_bad_values=sample,
    )


def _validate_datetime(series: pd.Series, col: str) -> Optional[ColumnValidationError]:
    """Non-null values that cannot be parsed as a date are errors."""
    parsed = pd.to_datetime(series, errors="coerce")
    bad_mask = parsed.isna() & series.notna()
    if not bad_mask.any():
        return None
    bad_idx = list(bad_mask[bad_mask].index[:20])
    sample = [str(series.loc[i]) for i in bad_idx[:5]]
    return ColumnValidationError(
        column=col,
        expected_dtype="datetime64[ns]",
        failing_row_count=int(bad_mask.sum()),
        failing_row_indices=bad_idx,
        sample_bad_values=sample,
    )


def _validate_bool(series: pd.Series, col: str) -> Optional[ColumnValidationError]:
    """
    Non-null values not in _VALID_BOOL_VALUES are errors.
    Accepted: True/False (bool), 1/0 (int), 'True'/'False'/'true'/'false'/'1'/'0' (str).
    Rejected: 'yes', 'no', 'enabled', arbitrary strings.
    NaN (empty cell) is allowed — treated as missing, not bad data.
    """
    non_null = series.dropna()
    bad_mask = ~non_null.isin(_VALID_BOOL_VALUES)
    if not bad_mask.any():
        return None
    bad_idx = list(bad_mask[bad_mask].index[:20])
    sample = [str(non_null[i]) for i in bad_idx[:5]]
    return ColumnValidationError(
        column=col,
        expected_dtype="bool",
        failing_row_count=int(bad_mask.sum()),
        failing_row_indices=bad_idx,
        sample_bad_values=sample,
    )


# ---------------------------------------------------------------------------
# Column-level cast (only called after validation passes)
# ---------------------------------------------------------------------------

def _cast_column(series: pd.Series, dtype: str) -> pd.Series:
    """Apply type cast. Called only when validation has confirmed no bad values."""
    if dtype == "float64":
        return pd.to_numeric(series, errors="raise")
    if dtype == "datetime64[ns]":
        return pd.to_datetime(series, errors="raise")
    if dtype == "bool":
        non_null = series.dropna().map(_BOOL_CAST_MAP)
        return series.where(series.isna(), non_null)
    if dtype == "string":
        return series.astype("string")
    return series


# ---------------------------------------------------------------------------
# Core validator
# ---------------------------------------------------------------------------

def validate_file(
    df: pd.DataFrame,
    file_key: str,
) -> Tuple[Optional[pd.DataFrame], FileValidationResult]:
    """
    Validate a DataFrame against the schema registered for `file_key`.

    Returns (clean_df, result) on success — clean_df has casts applied.
    Returns (None,   result) on failure — result.column_errors is populated.

    Never raises; all errors are captured in FileValidationResult.
    """
    schema = SCHEMAS[file_key]
    required: List[str] = schema["required_columns"]
    dtypes: Dict[str, str] = schema["dtypes"]
    expected_filename: str = schema["expected_filename"]

    row_count = len(df)
    columns_found = list(df.columns)
    schema_hash = _compute_schema_hash(file_key, columns_found, dtypes, row_count)

    # --- Step 1: required column check ---
    missing = [c for c in required if c not in df.columns]
    if missing:
        return None, FileValidationResult(
            file_key=file_key,
            expected_filename=expected_filename,
            is_valid=False,
            row_count=row_count,
            columns_validated=[],
            schema_hash=schema_hash,
            missing_columns=missing,
            column_errors=[],
        )

    # --- Step 2: per-column type validation (collect ALL errors) ---
    column_errors: List[ColumnValidationError] = []
    for col, dtype in dtypes.items():
        if col not in df.columns:
            continue
        error: Optional[ColumnValidationError] = None
        if dtype == "float64":
            error = _validate_float(df[col], col)
        elif dtype == "datetime64[ns]":
            error = _validate_datetime(df[col], col)
        elif dtype == "bool":
            error = _validate_bool(df[col], col)
        # "string" columns: any value is accepted
        if error is not None:
            column_errors.append(error)

    if column_errors:
        return None, FileValidationResult(
            file_key=file_key,
            expected_filename=expected_filename,
            is_valid=False,
            row_count=row_count,
            columns_validated=list(dtypes.keys()),
            schema_hash=schema_hash,
            missing_columns=[],
            column_errors=column_errors,
        )

    # --- Step 3: apply casts (validation confirmed clean) ---
    df_clean = df.copy()
    for col, dtype in dtypes.items():
        if col in df_clean.columns:
            df_clean[col] = _cast_column(df_clean[col], dtype)

    return df_clean, FileValidationResult(
        file_key=file_key,
        expected_filename=expected_filename,
        is_valid=True,
        row_count=row_count,
        columns_validated=list(dtypes.keys()),
        schema_hash=schema_hash,
        missing_columns=[],
        column_errors=[],
    )


# ---------------------------------------------------------------------------
# Backward-compatible wrappers (used by test_schema.py and non-intake callers)
# These raise ValueError on failure; use validate_file() for structured errors.
# ---------------------------------------------------------------------------

def _apply_schema(df: pd.DataFrame, file_key: str) -> pd.DataFrame:
    df_clean, result = validate_file(df, file_key)
    if not result.is_valid:
        raise ValueError(result.to_error_message())
    return df_clean


def apply_gl_schema(df: pd.DataFrame) -> pd.DataFrame:
    return _apply_schema(df, "gl")


def apply_subledger_schema(df: pd.DataFrame) -> pd.DataFrame:
    return _apply_schema(df, "subledger")


def apply_coa_schema(df: pd.DataFrame) -> pd.DataFrame:
    return _apply_schema(df, "chart_of_accounts")


def apply_ground_truth_schema(df: pd.DataFrame) -> pd.DataFrame:
    return _apply_schema(df, "ground_truth")


# ---------------------------------------------------------------------------
# Legacy functions preserved for any callers outside the intake path
# ---------------------------------------------------------------------------

def validate_columns(df: pd.DataFrame, required_columns: List[str]) -> None:
    missing = [col for col in required_columns if col not in df.columns]
    if missing:
        raise ValueError(f"Missing required columns: {missing}")


def enforce_dtypes(df: pd.DataFrame, dtype_map: Dict[str, str]) -> pd.DataFrame:
    """Legacy: applies casts directly. Use validate_file() for strict validation."""
    for col, dtype in dtype_map.items():
        if col not in df.columns:
            continue
        df[col] = _cast_column(df[col], dtype)
    return df
