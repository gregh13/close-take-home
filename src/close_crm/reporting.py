"""Search leads by founded date, merge with import snapshots, write state report."""

from __future__ import annotations

import csv
import time
from datetime import date
from pathlib import Path
from typing import Any

from requests.exceptions import HTTPError

from close_crm.api import CloseAPI
from close_crm.config import LOG
from close_crm.importer import ImportedLeadSnapshot


def _custom_key(field_id: str) -> str:
    """API key for a custom field value on a lead row: custom.<cf_id>."""
    return f"custom.{field_id}" if not field_id.startswith("custom.") else field_id


def _lead_revenue_state(
    lead: dict[str, Any],
    revenue_id: str,
    state_id: str,
) -> tuple[float | None, str | None]:
    """Read revenue (number) and state (text) from search result row by field ids."""
    rev_key = _custom_key(revenue_id)
    st_key = _custom_key(state_id)
    rev = lead.get(rev_key)
    if isinstance(rev, (int, float)):
        revenue = float(rev)
    elif rev is None:
        revenue = None
    else:
        try:
            revenue = float(rev)
        except (TypeError, ValueError):
            revenue = None
    st = lead.get(st_key)
    state = str(st).strip() if st else None
    return revenue, state or None


def build_search_body(
    founded_field_id: str,
    revenue_id: str,
    state_id: str,
    start: date,
    end: date,
    cursor: str | None,
    limit: int = 200,
) -> dict[str, Any]:
    """Build Advanced Search body: leads whose *Company Founded* custom date falls in [start, end]."""
    return {
        "query": {
            "type": "and",
            "queries": [
                {"type": "object_type", "object_type": "lead"},
                {
                    "type": "field_condition",
                    "field": {
                        "type": "custom_field",
                        "custom_field_id": founded_field_id,
                    },
                    "condition": {
                        "type": "fixed_date_range",
                        "gte": start.isoformat(),
                        "lte": end.isoformat(),
                    },
                },
            ],
        },
        "_fields": {
            "lead": [
                "id",
                "display_name",
                _custom_key(revenue_id),
                _custom_key(state_id),
            ],
        },
        "_limit": limit,
        "sort": [
            {
                "direction": "asc",
                "field": {
                    "type": "regular_field",
                    "object_type": "lead",
                    "field_name": "date_created",
                },
            }
        ],
        **({"cursor": cursor} if cursor else {}),
    }


class LeadReporter:
    """Search leads in date range and write state aggregation CSV."""

    def __init__(self, revenue_field_id: str, state_field_id: str) -> None:
        """Ids for custom fields used when reading search rows and building the report."""
        self.revenue_field_id = revenue_field_id
        self.state_field_id = state_field_id

    def find_leads_in_date_range(
        self,
        api: CloseAPI,
        founded_field_id: str,
        start: date,
        end: date,
    ) -> list[dict[str, Any]]:
        """Paginate POST /data/search/ until cursor is exhausted."""
        all_rows: list[dict[str, Any]] = []
        cursor: str | None = None
        while True:
            body = build_search_body(
                founded_field_id,
                self.revenue_field_id,
                self.state_field_id,
                start,
                end,
                cursor,
            )
            LOG.debug("Search body: %s", body)
            resp = api.search_data(body)
            data = resp.get("data") or []
            for item in data:
                if isinstance(item, dict):
                    all_rows.append(item)
            cursor = resp.get("cursor")
            if not cursor:
                break
        return all_rows

    @staticmethod
    def median(values: list[float]) -> float | None:
        """Median of a non-empty list; None if empty."""
        if not values:
            return None
        s = sorted(values)
        n = len(s)
        mid = n // 2
        if n % 2:
            return s[mid]
        return (s[mid - 1] + s[mid]) / 2.0

    @staticmethod
    def format_currency(n: float | None) -> str:
        """US-style $x,xxx.xx for report cells; empty string if None."""
        if n is None:
            return ""
        return f"${n:,.2f}"

    def generate_report(
        self,
        leads: list[tuple[str, float | None, str | None]],
        output_path: Path,
    ) -> None:
        """Aggregate leads by US state: counts, top revenue lead, total and median revenue."""
        by_state: dict[str, list[tuple[str, float]]] = {}
        for name, rev, st in leads:
            key = (st or "").strip() or "(no state)"
            r = rev if rev is not None else 0.0
            by_state.setdefault(key, []).append((name, r))

        output_path.parent.mkdir(parents=True, exist_ok=True)
        fieldnames = [
            "US State",
            "Total number of leads",
            "The lead with most revenue",
            "Total revenue",
            "Median revenue",
        ]
        with output_path.open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=fieldnames)
            w.writeheader()
            for state in sorted(by_state.keys()):
                items = by_state[state]
                names_and_rev = [(n, r) for n, r in items]
                count = len(names_and_rev)
                revenues = [r for _, r in names_and_rev]
                total = sum(revenues)
                med = self.median(revenues)
                top_name = max(names_and_rev, key=lambda x: x[1])[0]
                w.writerow(
                    {
                        "US State": state,
                        "Total number of leads": count,
                        "The lead with most revenue": top_name,
                        "Total revenue": self.format_currency(total),
                        "Median revenue": self.format_currency(med),
                    }
                )


def filter_snapshots_by_date_range(
    snaps: list[ImportedLeadSnapshot],
    start: date,
    end: date,
) -> list[ImportedLeadSnapshot]:
    """Keep snapshots whose founded date (ISO) is within [start, end]."""
    out: list[ImportedLeadSnapshot] = []
    for s in snaps:
        if not s.founded:
            continue
        try:
            d = date.fromisoformat(s.founded)
        except ValueError:
            continue
        if start <= d <= end:
            out.append(s)
    return out


def merge_search_with_snapshots(
    reporter: LeadReporter,
    search_rows: list[dict[str, Any]],
    snapshots: list[ImportedLeadSnapshot],
    start: date,
    end: date,
) -> list[tuple[str, float | None, str | None]]:
    """Rows (name, revenue, state) from search, plus in-range imports absent from search."""
    tuples: list[tuple[str, float | None, str | None]] = []
    seen_ids: set[str] = set()
    for row in search_rows:
        if row.get("__object_type") != "lead":
            continue
        lid = row.get("id")
        if not isinstance(lid, str):
            continue
        seen_ids.add(lid)
        name = row.get("display_name") or row.get("name") or ""
        rev, st = _lead_revenue_state(
            row, reporter.revenue_field_id, reporter.state_field_id
        )
        tuples.append((str(name), rev, st))

    ours_in_range = filter_snapshots_by_date_range(snapshots, start, end)
    for s in ours_in_range:
        if s.lead_id in seen_ids:
            continue
        LOG.warning(
            "Search missing imported lead %s (%r); supplementing from snapshot (index lag)",
            s.lead_id,
            s.display_name,
        )
        tuples.append((s.display_name, s.revenue, s.state))
    return tuples


def run_search_with_retries(
    api: CloseAPI,
    reporter: LeadReporter,
    founded_field_id: str,
    start: date,
    end: date,
    max_attempts: int = 5,
) -> list[dict[str, Any]]:
    """Call find_leads_in_date_range with backoff on HTTP errors (e.g. transient failures)."""
    last_err: Exception | None = None
    for attempt in range(max_attempts):
        try:
            return reporter.find_leads_in_date_range(api, founded_field_id, start, end)
        except HTTPError as e:
            last_err = e
            LOG.error("Search failed (attempt %s): %s", attempt + 1, e)
            if e.response is not None:
                LOG.error("Response body: %s", e.response.text[:2000])
            time.sleep(2.0 * (attempt + 1))
    raise last_err if last_err else RuntimeError("search failed")
