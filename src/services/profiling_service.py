"""
Profiling service — Phase 2: files_loaded → profiled

Generates deterministic metrics from the three validated DataFrames stored in
runtime["raw_data"]. This module has no session or state awareness; it receives
raw data and returns a structured result.

Metric categories per file:
  - row_count
  - null_counts / null_percentages (all columns)
  - duplicate_row_count (exact full-row duplicates)
  - numeric_distributions (min, max, mean, median, std, sum, null_count)
  - date_ranges (min, max as ISO date strings)
  - entity_distribution (value counts on the 'entity' column, if present)

Cross-file summary:
  - GL vs Subledger row delta (absolute and percentage)
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import pandas as pd


# ---------------------------------------------------------------------------
# Schema-aware column registries
# ---------------------------------------------------------------------------

# Columns to compute numeric distributions for, per file
_NUMERIC_COLUMNS: Dict[str, List[str]] = {
    "gl":                ["amount"],
    "subledger":         ["amount"],
    "chart_of_accounts": ["materiality_threshold"],
}

# Columns to compute date ranges for, per file
_DATE_COLUMNS: Dict[str, List[str]] = {
    "gl":                ["transaction_date"],
    "subledger":         ["transaction_date"],
    "chart_of_accounts": [],
}

# Column to use for entity distribution, per file (None = skip)
_ENTITY_COLUMN: Dict[str, Optional[str]] = {
    "gl":                "entity",
    "subledger":         "entity",
    "chart_of_accounts": None,
}


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------

@dataclass
class NumericDistribution:
    min: Optional[float]
    max: Optional[float]
    mean: Optional[float]
    median: Optional[float]
    std: Optional[float]
    sum: Optional[float]
    null_count: int

    def to_dict(self) -> Dict[str, Any]:
        return {
            "min":        self.min,
            "max":        self.max,
            "mean":       self.mean,
            "median":     self.median,
            "std":        self.std,
            "sum":        self.sum,
            "null_count": self.null_count,
        }


@dataclass
class DateRange:
    min: Optional[str]    # ISO date string or None
    max: Optional[str]

    def to_dict(self) -> Dict[str, Optional[str]]:
        return {"min": self.min, "max": self.max}


@dataclass
class FileProfilingResult:
    file_key: str
    row_count: int
    null_counts: Dict[str, int]
    null_percentages: Dict[str, float]
    duplicate_row_count: int
    numeric_distributions: Dict[str, NumericDistribution]
    date_ranges: Dict[str, DateRange]
    entity_distribution: Dict[str, int]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "file_key":               self.file_key,
            "row_count":              self.row_count,
            "null_counts":            self.null_counts,
            "null_percentages":       self.null_percentages,
            "duplicate_row_count":    self.duplicate_row_count,
            "numeric_distributions":  {
                k: v.to_dict() for k, v in self.numeric_distributions.items()
            },
            "date_ranges":            {
                k: v.to_dict() for k, v in self.date_ranges.items()
            },
            "entity_distribution":    self.entity_distribution,
        }


@dataclass
class CrossFileSummary:
    gl_row_count: int
    subledger_row_count: int
    row_count_delta: int
    row_count_delta_pct: float

    def to_dict(self) -> Dict[str, Any]:
        return {
            "gl_row_count":         self.gl_row_count,
            "subledger_row_count":  self.subledger_row_count,
            "row_count_delta":      self.row_count_delta,
            "row_count_delta_pct":  self.row_count_delta_pct,
        }


@dataclass
class ProfilingResult:
    files: Dict[str, FileProfilingResult]
    cross_file: CrossFileSummary

    def to_dict(self) -> Dict[str, Any]:
        return {
            "files":      {k: v.to_dict() for k, v in self.files.items()},
            "cross_file": self.cross_file.to_dict(),
        }


# ---------------------------------------------------------------------------
# Per-metric helpers
# ---------------------------------------------------------------------------

def _null_metrics(df: pd.DataFrame) -> tuple[Dict[str, int], Dict[str, float]]:
    """Return null counts and null percentages (rounded to 4 dp) for all columns."""
    row_count = max(len(df), 1)  # avoid /0 on empty frames
    null_counts = df.isna().sum().astype(int).to_dict()
    null_pct = {
        col: round(count / row_count * 100, 4)
        for col, count in null_counts.items()
    }
    return null_counts, null_pct


def _duplicate_count(df: pd.DataFrame) -> int:
    """Count exact full-row duplicates (rows where every column value is identical)."""
    return int(df.duplicated().sum())


def _numeric_distribution(series: pd.Series) -> NumericDistribution:
    """Compute distribution stats for a numeric series. None where all values are null."""
    non_null = series.dropna()
    null_count = int(series.isna().sum())

    if non_null.empty:
        return NumericDistribution(
            min=None, max=None, mean=None, median=None, std=None, sum=None,
            null_count=null_count,
        )

    return NumericDistribution(
        min=    round(float(non_null.min()),    4),
        max=    round(float(non_null.max()),    4),
        mean=   round(float(non_null.mean()),   4),
        median= round(float(non_null.median()), 4),
        std=    round(float(non_null.std()),    4) if len(non_null) > 1 else 0.0,
        sum=    round(float(non_null.sum()),    4),
        null_count=null_count,
    )


def _date_range(series: pd.Series) -> DateRange:
    """
    Return min/max of a datetime series as ISO date strings.
    Returns None for both if the series is all-null.
    """
    try:
        parsed = pd.to_datetime(series, errors="coerce").dropna()
    except Exception:
        return DateRange(min=None, max=None)

    if parsed.empty:
        return DateRange(min=None, max=None)

    return DateRange(
        min=parsed.min().date().isoformat(),
        max=parsed.max().date().isoformat(),
    )


def _entity_distribution(df: pd.DataFrame, entity_col: Optional[str]) -> Dict[str, int]:
    """Return value counts for the entity column. Empty dict if column absent or None."""
    if entity_col is None or entity_col not in df.columns:
        return {}
    return df[entity_col].value_counts().astype(int).to_dict()


# ---------------------------------------------------------------------------
# Per-file profiler
# ---------------------------------------------------------------------------

def _profile_file(df: pd.DataFrame, file_key: str) -> FileProfilingResult:
    null_counts, null_pct = _null_metrics(df)

    numeric_dists: Dict[str, NumericDistribution] = {}
    for col in _NUMERIC_COLUMNS.get(file_key, []):
        if col in df.columns:
            numeric_dists[col] = _numeric_distribution(df[col])

    date_ranges: Dict[str, DateRange] = {}
    for col in _DATE_COLUMNS.get(file_key, []):
        if col in df.columns:
            date_ranges[col] = _date_range(df[col])

    return FileProfilingResult(
        file_key=file_key,
        row_count=len(df),
        null_counts=null_counts,
        null_percentages=null_pct,
        duplicate_row_count=_duplicate_count(df),
        numeric_distributions=numeric_dists,
        date_ranges=date_ranges,
        entity_distribution=_entity_distribution(df, _ENTITY_COLUMN.get(file_key)),
    )


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def run_profiling(raw_data: Dict[str, Any]) -> ProfilingResult:
    """
    Profile all three DataFrames in raw_data.

    Args:
        raw_data: runtime["raw_data"] — must contain 'gl', 'subledger',
                  'chart_of_accounts' as non-None DataFrames.

    Returns:
        ProfilingResult with per-file metrics and a cross-file summary.
    """
    file_results: Dict[str, FileProfilingResult] = {}

    for file_key in ("gl", "subledger", "chart_of_accounts"):
        df = raw_data.get(file_key)
        if df is None or not isinstance(df, pd.DataFrame):
            raise ValueError(
                f"raw_data['{file_key}'] is not available. "
                "Ensure Phase 1 (upload) completed successfully before profiling."
            )
        file_results[file_key] = _profile_file(df, file_key)

    gl_n  = file_results["gl"].row_count
    sub_n = file_results["subledger"].row_count
    delta = abs(gl_n - sub_n)

    cross = CrossFileSummary(
        gl_row_count=gl_n,
        subledger_row_count=sub_n,
        row_count_delta=delta,
        row_count_delta_pct=round(delta / max(gl_n, 1) * 100, 4),
    )

    return ProfilingResult(files=file_results, cross_file=cross)
