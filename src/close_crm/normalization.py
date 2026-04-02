"""CSV validation, parsing helpers, and row/company dataclasses."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date

from close_crm.config import LOG

_EMAIL_RE = re.compile(r"^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$")
_SPLIT_TOKENS = re.compile(r"[\s,;]+")


def title_case_name(s: str) -> str:
    """Title-case a person/company string without breaking apostrophes."""
    if not s:
        return s
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
    if not raw or not str(raw).strip():
        return []
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
    if not raw or not str(raw).strip():
        return []
    lines = re.split(r"[\r\n]+", str(raw))
    seen: set[str] = set()
    out: list[str] = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        line = re.sub(r"^[^\d+]*", "", line)
        low = line.casefold()
        if low in ("unknown", "n/a", "none"):
            continue
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
    """
    Close validates contact phones strictly (E.164-style: + and digits).
    Hyphenated numbers like +86-173-158-4533 may be rejected; normalize before POST.
    """
    s = phone.strip()
    if not s:
        return s
    if s.startswith("+"):
        rest = "".join(ch for ch in s[1:] if ch.isdigit())
        return f"+{rest}" if rest else s
    return s


def parse_money(raw: str | None) -> float | None:
    if raw is None:
        return None
    s = str(raw).strip()
    if not s:
        return None
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
    company: str
    contact_name: str
    emails: list[str]
    phones: list[str]
    founded: str | None
    revenue: float | None
    state: str | None


def normalize_row(row: dict[str, str], row_num: int) -> CleanRow | None:
    company = (row.get("Company") or "").strip()
    if not company:
        LOG.warning("Row %s: discarded — empty company", row_num)
        return None

    raw_name = (row.get("Contact Name") or "").strip()
    emails = parse_emails(row.get("Contact Emails"))
    phones = parse_phones(row.get("Contact Phones"))

    if not raw_name:
        if emails or phones:
            name = "Unknown"
        else:
            LOG.warning("Row %s: discarded — no contact identity", row_num)
            return None
    else:
        name = title_case_name(raw_name)

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
    name: str
    emails: list[str]
    phones: list[str]


@dataclass
class GroupedCompany:
    display_name: str
    contacts: list[ContactPayload] = field(default_factory=list)
    founded: str | None = None
    revenue: float | None = None
    state: str | None = None


def normalize_field_key(name: str) -> str:
    return name.strip().casefold()
