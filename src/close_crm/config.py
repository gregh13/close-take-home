"""Default file paths, Close API base URL, custom-field mapping, and module logger."""

from __future__ import annotations

import logging
from datetime import date
from pathlib import Path

# Defaults relative to src/ (parent of this package)
_SRC_DIR = Path(__file__).resolve().parent.parent


def default_report_output_path(start: date, end: date) -> Path:
    """Report CSV under data/output/; filename encodes the founded-date search range."""
    return _SRC_DIR / "data" / "output" / f"report_{start.isoformat()}_{end.isoformat()}.csv"


DEFAULT_INPUT = (
    _SRC_DIR
    / "data"
    / "input"
    / "Customer Support Engineer Take Home Project - Import File - MOCK_DATA.csv"
)
DEFAULT_NORMALIZED = _SRC_DIR / "data" / "normalized" / "normalized_import.csv"
API_BASE = "https://api.close.com/api/v1"

# (csv_column_key, Close field label, Close field type) — used when creating/finding fields
CUSTOM_FIELD_SPECS: list[tuple[str, str, str]] = [
    ("custom.Company Founded", "Company Founded", "date"),
    ("custom.Company Revenue", "Company Revenue", "number"),
    ("Company US State", "Company US State", "text"),
]

LOG = logging.getLogger("close_import")
