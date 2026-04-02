"""Date parsing and range validation."""

from __future__ import annotations

from datetime import date, datetime


def parse_iso_date(s: str) -> date:
    """Parse YYYY-MM-DD; raise ValueError with a clear message if invalid."""
    s = s.strip()
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except ValueError as e:
        raise ValueError(f"Invalid date {s!r} (expected YYYY-MM-DD)") from e


def validate_date_range(start: date, end: date) -> None:
    if start > end:
        raise ValueError(f"start date {start} must be on or before end date {end}")
