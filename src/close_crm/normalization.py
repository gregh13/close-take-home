"""CSV validation, parsing helpers, and row/company dataclasses."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date

from close_crm.config import LOG

# Email token validation and splitting (parse_emails).
_EMAIL_RE = re.compile(r"^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$")
_SPLIT_TOKENS = re.compile(r"[\s,;]+")


def title_case_name(s: str) -> str:
    """Title-case a person/company string without breaking apostrophes."""
    if not s:
        return s
    # --- Preserve whitespace runs; upper first letter of each word token ---
    parts = re.split(r"(\s+)", s.strip())
    out: list[str] = []
    for p in parts:
        if p.isspace():
            out.append(p)
        elif not p:
            continue
        else:
            out.append(p[:1].upper() + p[1:].lower() if len(p) > 1 else p.upper())
    return "".join(out)


def parse_emails(raw: str | None) -> list[str]:
    """Split on whitespace/commas/semicolons; keep valid-looking emails; dedupe case-insensitively."""
    if not raw or not str(raw).strip():
        return []
    # -------------------------------------------------------------------------
    # Tokenize (newlines flattened to spaces), match _EMAIL_RE, skip placeholders.
    # -------------------------------------------------------------------------
    seen: set[str] = set()
    out: list[str] = []
    for part in _SPLIT_TOKENS.split(str(raw).replace("\n", " ")):
        p = part.strip()
        if not p or "??" in p:
            continue
        if _EMAIL_RE.match(p):
            k = p.casefold()
            if k not in seen:
                seen.add(k)
                out.append(p)
    return out


def parse_phones(raw: str | None) -> list[str]:
    """One phone per line; strip noise; skip junk; require enough digits; dedupe."""
    if not raw or not str(raw).strip():
        return []
    lines = re.split(r"[\r\n]+", str(raw))
    seen: set[str] = set()
    out: list[str] = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        # --- Strip leading junk (e.g. emoji) before first digit or + ---
        line = re.sub(r"^[^\d+]*", "", line)
        low = line.casefold()
        if low in ("unknown", "n/a", "none"):
            continue
        # --- Drop placeholder-heavy junk lines ---
        if "??" in line and sum(c.isdigit() for c in line) < 5:
            continue
        digits = sum(c.isdigit() for c in line)
        if digits < 7:
            continue
        if line not in seen:
            seen.add(line)
            out.append(line)
    return out


def format_phone_for_close(phone: str) -> str:
    """Normalize to +<digits> for API validation (strips hyphens/spaces after the +)."""
    # Called when building POST /lead/ payloads (Close is strict about E.164-style strings).
    s = phone.strip()
    if not s:
        return s
    if s.startswith("+"):
        rest = "".join(ch for ch in s[1:] if ch.isdigit())
        return f"+{rest}" if rest else s
    return s


def parse_money(raw: str | None) -> float | None:
    """Parse currency-like strings; return None if empty or unparseable."""
    if raw is None:
        return None
    s = str(raw).strip()
    if not s:
        return None
    # --- Strip quotes, thousands separators, optional leading $ ---
    s = s.replace('"', "").replace("'", "").replace(",", "")
    s = re.sub(r"^\$\s*", "", s)
    try:
        return float(s)
    except ValueError:
        return None


def parse_founded(raw: str | None) -> str | None:
    """DD.MM.YYYY -> YYYY-MM-DD."""
    if raw is None:
        return None
    s = str(raw).strip()
    if not s:
        return None
    # --- European date in CSV; emit ISO date for Close custom date fields ---
    m = re.match(r"^(\d{1,2})\.(\d{1,2})\.(\d{4})$", s)
    if not m:
        return None
    d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
    try:
        return date(y, mo, d).isoformat()
    except ValueError:
        return None


@dataclass
class CleanRow:
    """One validated CSV row (from normalize_row): company, contact, channels, custom fields."""

    company: str
    contact_name: str
    emails: list[str]
    phones: list[str]
    founded: str | None
    revenue: float | None
    state: str | None


def normalize_row(row: dict[str, str], row_num: int) -> CleanRow | None:
    """Map a CSV row to CleanRow; return None if company empty or no contact identity."""
    # -------------------------------------------------------------------------
    # 1. Company is required.
    # -------------------------------------------------------------------------
    company = (row.get("Company") or "").strip()
    if not company:
        LOG.warning("Row %s: discarded — empty company", row_num)
        return None

    # -------------------------------------------------------------------------
    # 2. Contact channels and display name rules.
    # -------------------------------------------------------------------------
    raw_name = (row.get("Contact Name") or "").strip()
    emails = parse_emails(row.get("Contact Emails"))
    phones = parse_phones(row.get("Contact Phones"))

    if not raw_name:
        # --- Allow missing name when at least one channel exists; else discard row ---
        if emails or phones:
            name = "Unknown"
        else:
            LOG.warning("Row %s: discarded — no contact identity", row_num)
            return None
    else:
        name = title_case_name(raw_name)

    # -------------------------------------------------------------------------
    # 3. Lead-level custom columns (shared across contacts for this company later).
    # -------------------------------------------------------------------------
    founded = parse_founded(row.get("custom.Company Founded"))
    revenue = parse_money(row.get("custom.Company Revenue"))
    st = (row.get("Company US State") or "").strip() or None

    return CleanRow(
        company=company,
        contact_name=name,
        emails=emails,
        phones=phones,
        founded=founded,
        revenue=revenue,
        state=st,
    )


@dataclass
class ContactPayload:
    """One contact nested under a GroupedCompany (built in importer.group_by_company)."""

    name: str
    emails: list[str]
    phones: list[str]


@dataclass
class GroupedCompany:
    """One company: merged contacts plus founded/revenue/state (first wins; conflicts logged)."""

    display_name: str
    contacts: list[ContactPayload] = field(default_factory=list)
    founded: str | None = None
    revenue: float | None = None
    state: str | None = None


def normalize_field_key(name: str) -> str:
    """Compare Close custom field names case-insensitively (used when matching API field list)."""
    return name.strip().casefold()
