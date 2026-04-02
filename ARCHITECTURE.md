# Architecture

This document describes how the Close CSV import tool is split into modules, how data flows through it, and why it is structured this way.

## Purpose

The tool does four things in sequence:

1. **Read and clean** a CSV of companies and contacts.
2. **Write** a normalized CSV and **ensure** the right lead custom fields exist in Close.
3. **Create leads** in Close (one lead per company, contacts nested).
4. **Search** Close **org-wide** for leads in a **founded-date range**, merge results with what was just imported (to handle search index lag), and **write** an aggregated report by US state. By default, leads with no **US State** value are **excluded** from that report; the CLI can include them in a **`(no state)`** bucket.

The **entry point** is `src/close_import.py`. All reusable logic lives in the **`close_crm`** package under `src/close_crm/`.

---

## Component overview

| Module | Role |
|--------|------|
| **`close_import.py`** | CLI (`argparse`), env (`CLOSE_API_KEY`), logging, default report path from date range (`default_report_output_path`), and the ordered call chain. |
| **`close_crm/config.py`** | Default input/normalized paths, `default_report_output_path`, API base URL, `CUSTOM_FIELD_SPECS`, shared logger name. |
| **`close_crm/dates.py`** | Parse CLI dates (`YYYY-MM-DD`) and validate an inclusive range. |
| **`close_crm/api.py`** | `CloseAPI`: HTTP session (Basic auth), retries on 429/5xx, wrappers for REST endpoints used by the tool. |
| **`close_crm/normalization.py`** | Parse emails, phones, money, founded dates; title-case names; `CleanRow` / `GroupedCompany` structures; row-level validation. |
| **`close_crm/importer.py`** | `CSVImporter`: load CSV, normalize, group by company, write normalized file, build `POST /lead/` payloads, `import_leads()` loop and `ImportedLeadSnapshot` records. |
| **`close_crm/reporting.py`** | Advanced Search query for founded-date range, `LeadReporter` (pagination, aggregates), merge search + snapshots, CSV report (optional inclusion of blank-state leads). |

There is no separate `close_import` **package**: that name is reserved for the script file. The library package is named **`close_crm`** to avoid import clashes (`close_import.py` vs `close_import/`).

---

## How components interact

Execution is a **pipeline**: each stage runs **in order** in `main()` (not three parallel branches). The API client is created once, then reused for custom fields, lead creation, and search.

```
close_import.py (main): argparse, logging, load_dotenv, CLOSE_API_KEY
                                    |
                                    v
                    +---------------+---------------+
                    | dates: parse_iso_date,        |
                    | validate_date_range           |
                    +---------------+---------------+
                                    |
                                    v
                    +---------------+---------------+
                    | CSVImporter: load,            |
                    | normalize_all, group_by_      |
                    | company, write_normalized_csv |
                    +---------------+---------------+
                                    |
                         input CSV / normalized CSV (files)
                                    |
                                    v
                    +---------------+---------------+
                    | CloseAPI(api_key)             |
                    | ensure_custom_fields(api)     |
                    +---------------+---------------+
                                    |
                                    v   Close REST: GET/POST /custom_field/lead/
                    +---------------+---------------+
                    | import_leads(...)             |
                    +---------------+---------------+
                                    |
                                    v   Close REST: POST /lead/ (per company)
                    +---------------+---------------+
                    | sleep(search_delay)           |
                    | LeadReporter,                 |
                    | run_search_with_retries,      |
                    | merge_search_with_snapshots,  |
                    | generate_report               |
                    +---------------+---------------+
                                    |
                                    v
              Close REST: POST /data/search/  +  write report CSV (file)
```

`normalization` runs inside `CSVImporter` (not a separate top-level step). `merge_search_with_snapshots` needs both search results and the `ImportedLeadSnapshot` list from `import_leads`.

**Dependency direction (high level):**

- `config` is depended on by almost everything (paths, constants, logging).
- `dates` has no dependency on CRM logic.
- `api` depends only on `config` (and `requests`).
- `normalization` depends on `config` (logger).
- `importer` depends on `api` + `normalization` + `config`.
- `reporting` depends on `api` + `config` + types from `importer` (`ImportedLeadSnapshot`) for the merge step.

So layers are: **config → (dates | api | normalization) → importer → reporting**, with **`close_import.py`** sitting on top and wiring CLI arguments to that graph.

---

## Why it is separated this way

1. **Single responsibility** — HTTP retries and auth stay in `api.py`; string/CSV rules stay in `normalization.py`; Close search/report math stays in `reporting.py`. That makes each file easier to test and change without touching unrelated behavior.

2. **Stable boundaries** — `CloseAPI` hides URL construction, error logging, and retry policy. If Close changes rate limits or auth, edits are localized. Normalization does not need to know about HTTP.

3. **Reusability** — `normalize_row`, `build_search_body`, or `CloseAPI` can be imported from another script or tests without pulling in the full CLI.

4. **Readable orchestration** — `close_import.py` reads as a short script: parse args → validate dates → resolve default report path → import CSV → create leads → search → merge → report. Details live in `close_crm`, not in a single large file.

5. **Package vs script naming** — Using a distinct package name (`close_crm`) keeps `src/close_import.py` as a runnable entry point while still allowing `import close_crm` from `PYTHONPATH=src`.

---

## Data artifacts

| Artifact | Produced by | Consumed by |
|----------|-------------|-------------|
| Raw CSV rows | `CSVImporter.load` | `normalize_all` → `group_by_company` |
| `GroupedCompany` map | `CSVImporter` | Normalized CSV writer, `build_lead_payload`, `import_leads` |
| `field_map` (csv column → `cf_*` id) | `ensure_custom_fields` | Payload builder + reporting (`_custom_key` / search fields) |
| `ImportedLeadSnapshot` list | `import_leads` | `merge_search_with_snapshots` |
| Search rows | `LeadReporter.find_leads_in_date_range` | `merge_search_with_snapshots`, then `generate_report` |
| Report row tuples | `merge_search_with_snapshots` | `generate_report` (optional filter for blank US state) |

---

## Extension points

- **New CSV columns** — extend `normalization` + `CUSTOM_FIELD_SPECS` + payload building in `importer`.
- **Different report** — change `LeadReporter.generate_report` (e.g. `include_leads_without_state`) or the merge logic in `reporting` without touching API or CSV parsing.
- **Alternate transports** — swap or subclass `CloseAPI` if mocking or a different base URL is needed.

For day-to-day usage, see [README.md](README.md).
