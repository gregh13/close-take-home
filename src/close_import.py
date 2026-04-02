#!/usr/bin/env python3
"""
Close CRM: CSV import, normalization, lead creation, date-range search, state report.

Single entry point — see README.md for usage.
"""

from __future__ import annotations

import argparse
import logging
import os
import time
from pathlib import Path

from dotenv import load_dotenv

from close_crm.config import (
    DEFAULT_INPUT,
    DEFAULT_NORMALIZED,
    DEFAULT_OUTPUT,
    LOG,
)
from close_crm.dates import parse_iso_date, validate_date_range
from close_crm.api import CloseAPI
from close_crm.importer import CSVImporter, import_leads
from close_crm.reporting import (
    LeadReporter,
    merge_search_with_snapshots,
    run_search_with_retries,
)


def main() -> None:
    """Parse CLI, import CSV into Close, run founded-date search, write state report CSV."""
    parser = argparse.ArgumentParser(
        description="Import CSV into Close, then write state revenue report for a founded-date range."
    )
    parser.add_argument("--start-date", required=True, help="Start date YYYY-MM-DD (inclusive)")
    parser.add_argument("--end-date", required=True, help="End date YYYY-MM-DD (inclusive)")
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT, help="Input CSV path")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help="Report CSV path")
    parser.add_argument(
        "--normalized",
        type=Path,
        default=DEFAULT_NORMALIZED,
        help="Normalized CSV output path",
    )
    parser.add_argument(
        "--search-delay",
        type=float,
        default=3.0,
        help="Seconds to wait after import before searching (default 3)",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="Debug logging")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(message)s",
    )

    load_dotenv()
    api_key = (os.environ.get("CLOSE_API_KEY") or "").strip()
    if not api_key:
        raise SystemExit("CLOSE_API_KEY is not set. Add it to .env or the environment.")

    start_d = parse_iso_date(args.start_date)
    end_d = parse_iso_date(args.end_date)
    validate_date_range(start_d, end_d)

    importer = CSVImporter(args.input)
    raw_rows = importer.load()
    cleaned = importer.normalize_all(raw_rows)
    grouped = importer.group_by_company(cleaned)
    importer.write_normalized_csv(grouped, args.normalized)
    LOG.info("Wrote normalized CSV: %s", args.normalized)

    api = CloseAPI(api_key)
    field_map = importer.ensure_custom_fields(api)
    founded_id = field_map["custom.Company Founded"]
    revenue_id = field_map["custom.Company Revenue"]
    state_id = field_map["Company US State"]

    snapshots = import_leads(api, importer, grouped, field_map)

    reporter = LeadReporter(revenue_field_id=revenue_id, state_field_id=state_id)
    time.sleep(args.search_delay)
    search_rows = run_search_with_retries(
        api, reporter, founded_id, start_d, end_d
    )
    report_rows = merge_search_with_snapshots(
        reporter, search_rows, snapshots, start_d, end_d
    )
    reporter.generate_report(report_rows, args.output)
    LOG.info("Wrote report: %s", args.output)


if __name__ == "__main__":
    main()
