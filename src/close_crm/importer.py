"""Load CSV, normalize, group by company, ensure custom fields, create leads."""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from close_crm.api import CloseAPI
from close_crm.config import CUSTOM_FIELD_SPECS, LOG
from close_crm.normalization import (
    CleanRow,
    ContactPayload,
    GroupedCompany,
    format_phone_for_close,
    normalize_field_key,
    normalize_row,
)


class CSVImporter:
    """Load CSV, normalize rows, group by company, write normalized CSV, import to Close."""

    def __init__(self, input_path: Path) -> None:
        self.input_path = Path(input_path)

    def load(self) -> list[dict[str, str]]:
        """Read CSV as dict rows (UTF-8); empty list if no header."""
        with self.input_path.open(newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            if reader.fieldnames is None:
                return []
            return [dict(row) for row in reader]

    def normalize_all(self, rows: list[dict[str, str]]) -> list[CleanRow]:
        """Apply normalize_row per row; row numbers start at 2 (header is row 1)."""
        cleaned: list[CleanRow] = []
        for i, row in enumerate(rows, start=2):
            c = normalize_row(row, i)
            if c:
                cleaned.append(c)
        return cleaned

    def group_by_company(self, rows: list[CleanRow]) -> dict[str, GroupedCompany]:
        """Preserve first-seen company order; merge contacts; warn on conflicting attributes."""
        order: list[str] = []
        buckets: dict[str, GroupedCompany] = {}

        for r in rows:
            key = r.company.strip()
            if key not in buckets:
                buckets[key] = GroupedCompany(display_name=key)
                order.append(key)
            g = buckets[key]
            g.contacts.append(
                ContactPayload(name=r.contact_name, emails=list(r.emails), phones=list(r.phones))
            )
            if g.founded is None and r.founded:
                g.founded = r.founded
            elif g.founded is not None and r.founded is not None and g.founded != r.founded:
                LOG.warning(
                    "Company %r: conflicting founded %r vs %r (keeping first)",
                    key,
                    g.founded,
                    r.founded,
                )
            if g.revenue is None and r.revenue is not None:
                g.revenue = r.revenue
            elif (
                g.revenue is not None
                and r.revenue is not None
                and g.revenue != r.revenue
            ):
                LOG.warning(
                    "Company %r: conflicting revenue %r vs %r (keeping first)",
                    key,
                    g.revenue,
                    r.revenue,
                )
            if g.state is None and r.state:
                g.state = r.state
            elif g.state is not None and r.state is not None and g.state != r.state:
                LOG.warning(
                    "Company %r: conflicting state %r vs %r (keeping first)",
                    key,
                    g.state,
                    r.state,
                )

        return {k: buckets[k] for k in order}

    def write_normalized_csv(self, grouped: dict[str, GroupedCompany], out_path: Path) -> None:
        """Write one row per contact with company-level custom fields repeated."""
        out_path.parent.mkdir(parents=True, exist_ok=True)
        fieldnames = [
            "Company",
            "Contact Name",
            "Contact Emails",
            "Contact Phones",
            "Company Founded",
            "Company Revenue",
            "Company US State",
        ]
        with out_path.open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=fieldnames)
            w.writeheader()
            for _key, g in grouped.items():
                for c in g.contacts:
                    w.writerow(
                        {
                            "Company": g.display_name,
                            "Contact Name": c.name,
                            "Contact Emails": ";".join(c.emails),
                            "Contact Phones": "\n".join(c.phones),
                            "Company Founded": g.founded or "",
                            "Company Revenue": "" if g.revenue is None else str(g.revenue),
                            "Company US State": g.state or "",
                        }
                    )

    def ensure_custom_fields(self, api: CloseAPI) -> dict[str, str]:
        """Ensure CUSTOM_FIELD_SPECS exist in Close; return csv column key -> custom field id."""
        existing = api.list_lead_custom_fields()
        by_norm: dict[str, dict[str, Any]] = {}
        for item in existing:
            n = item.get("name")
            if isinstance(n, str) and n.strip():
                by_norm[normalize_field_key(n)] = item

        csv_to_id: dict[str, str] = {}
        for csv_col, close_name, want_type in CUSTOM_FIELD_SPECS:
            norm = normalize_field_key(close_name)
            row = by_norm.get(norm)
            if row:
                fid = row.get("id")
                et = row.get("type")
                if not isinstance(fid, str):
                    raise ValueError(f"Custom field {close_name!r} has no id")
                if isinstance(et, str) and et != want_type:
                    raise ValueError(
                        f"Field {close_name!r} exists with type {et!r}, need {want_type!r}"
                    )
                csv_to_id[csv_col] = fid
                LOG.info("Using existing Lead Custom Field %r -> %s", close_name, fid)
            else:
                created = api.create_lead_custom_field(close_name, want_type)
                fid = created.get("id")
                if not isinstance(fid, str):
                    raise ValueError(f"Created field {close_name!r} has no id")
                by_norm[norm] = created
                csv_to_id[csv_col] = fid
                LOG.info("Created Lead Custom Field %r (%s) -> %s", close_name, want_type, fid)
        return csv_to_id

    def build_lead_payload(
        self, g: GroupedCompany, field_map: dict[str, str]
    ) -> dict[str, Any]:
        """JSON body for POST /lead/: name, contacts, and custom.cf_<id> from field_map."""
        contacts: list[dict[str, Any]] = []
        for c in g.contacts:
            entry: dict[str, Any] = {"name": c.name}
            if c.emails:
                entry["emails"] = [{"email": e, "type": "office"} for e in c.emails]
            if c.phones:
                entry["phones"] = [
                    {"phone": format_phone_for_close(p), "type": "office"} for p in c.phones
                ]
            contacts.append(entry)
        payload: dict[str, Any] = {"name": g.display_name, "contacts": contacts}
        if g.founded and "custom.Company Founded" in field_map:
            payload[f"custom.{field_map['custom.Company Founded']}"] = g.founded
        if g.revenue is not None and "custom.Company Revenue" in field_map:
            payload[f"custom.{field_map['custom.Company Revenue']}"] = g.revenue
        if g.state and "Company US State" in field_map:
            payload[f"custom.{field_map['Company US State']}"] = g.state
        return payload


@dataclass
class ImportedLeadSnapshot:
    """In-memory record for search lag fallback."""

    lead_id: str
    display_name: str
    founded: str | None
    revenue: float | None
    state: str | None


def import_leads(
    api: CloseAPI,
    importer: CSVImporter,
    grouped: dict[str, GroupedCompany],
    field_map: dict[str, str],
) -> list[ImportedLeadSnapshot]:
    """Create one Close lead per grouped company; return ids and fields for reporting."""
    snapshots: list[ImportedLeadSnapshot] = []
    for _k, g in grouped.items():
        payload = importer.build_lead_payload(g, field_map)
        resp = api.create_lead(payload)
        lid = resp.get("id")
        dname = resp.get("display_name") or resp.get("name") or g.display_name
        if not isinstance(lid, str):
            raise RuntimeError(f"No lead id in response for {g.display_name!r}")
        snapshots.append(
            ImportedLeadSnapshot(
                lead_id=lid,
                display_name=str(dname),
                founded=g.founded,
                revenue=g.revenue,
                state=g.state,
            )
        )
        LOG.info("Created lead %r (%s contacts) -> %s", g.display_name, len(g.contacts), lid)
    return snapshots
