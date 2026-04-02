"""Paths, API constants, and shared logging."""

from __future__ import annotations

import logging
from pathlib import Path

# Defaults relative to src/ (parent of this package)
_SRC_DIR = Path(__file__).resolve().parent.parent

DEFAULT_INPUT = (
    _SRC_DIR
    / "data"
    / "input"
    / "Customer Support Engineer Take Home Project - Import File - MOCK_DATA.csv"
)
DEFAULT_OUTPUT = _SRC_DIR / "data" / "output" / "report.csv"
DEFAULT_NORMALIZED = _SRC_DIR / "data" / "normalized" / "normalized_import.csv"
API_BASE = "https://api.close.com/api/v1"

# CSV column -> Close Lead Custom Field (name, type)
CUSTOM_FIELD_SPECS: list[tuple[str, str, str]] = [
    ("custom.Company Founded", "Company Founded", "date"),
    ("custom.Company Revenue", "Company Revenue", "number"),
    ("Company US State", "Company US State", "text"),
]

LOG = logging.getLogger("close_import")
