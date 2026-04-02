# Close CRM CSV import and report

This project reads a CSV of companies and contacts, cleans the data, creates **leads** in [Close](https://close.com/) (with the right custom fields), then writes a **summary report** by US state for leads whose **company founded** date falls in a date range you choose. The report **searches your whole Close organization** for that founded-date range (not only rows from this CSV), then merges in any leads from this import that search has not indexed yet. By default, leads with a **blank US state** are **left out** of the report; use **`--include-no-state`** to add a single **`(no state)`** aggregate row for them.

---

## What you need

- **Python 3.10+** (3.11+ recommended)
- A Close account with an **API key** ([Settings → API Keys](https://app.close.com/settings/api/))

---

## Step-by-step: run the script

### 1. Open a terminal in the project folder

```bash
cd /path/to/close-take-home
```

### 2. Create a virtual environment (recommended)

This keeps dependencies out of your system Python.

```bash
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

### 4. Add your Close API key

Create a file named `.env` in the **project root** (same folder as `requirements.txt`) with:

```
CLOSE_API_KEY=your_api_key_here
```

Alternatively, you can export the variable in your shell: `export CLOSE_API_KEY=your_api_key_here`.

### 5. Run the import and report

From the project root, run:

```bash
python src/close_import.py --start-date 2020-01-01 --end-date 2024-12-31
```

- **`--start-date`** and **`--end-date`** are required. Use `YYYY-MM-DD`. The report includes leads whose **Company Founded** date is **on or after** the start date and **on or before** the end date (inclusive).

The script will:

1. Read the input CSV (see default path below).
2. Normalize rows and write a cleaned CSV.
3. Ensure the required lead custom fields exist in Close (or use existing ones).
4. Create one lead per company in your Close organization.
5. After a short pause, search Close **org-wide** for leads in that founded-date range, merge with this run’s imports (covers search lag), and write the state report (default filename includes the date range; blank-state leads omitted unless you pass **`--include-no-state`**).

### 6. Find your outputs

By default (no extra flags):

| Output | Location |
|--------|----------|
| Normalized CSV | `src/data/normalized/normalized_import.csv` |
| State report CSV | `src/data/output/report_<start-date>_<end-date>.csv` (from your `--start-date` / `--end-date`, e.g. `report_2020-01-01_2024-12-31.csv`) |

---

## Optional command-line flags

| Flag | Meaning |
|------|--------|
| `--input PATH` | Input CSV (default: mock file under `src/data/input/`) |
| `--output PATH` | Report CSV path (default encodes the date range in the filename under `src/data/output/`) |
| `--normalized PATH` | Normalized intermediate CSV path |
| `--search-delay SECONDS` | Wait after import before searching Close (default: `3`; helps if search lags) |
| `--include-no-state` | Put leads with a blank US state into a `(no state)` row (default: **omit** those leads from the report) |
| `-v` / `--verbose` | More detailed logs |

Example with custom files:

```bash
python src/close_import.py \
  --start-date 2015-01-01 \
  --end-date 2020-12-31 \
  --input /path/to/my_import.csv \
  --output /path/to/my_report.csv
```

Show all options:

```bash
python src/close_import.py --help
```

---

## Project layout

- **`src/close_import.py`** — run this script (command-line entry point).
- **`src/close_crm/`** — library code: API client, CSV normalization, import, reporting.

---

## Notes

- Running the script **creates real leads** in the Close organization tied to your API key (one lead per distinct company in the CSV). Use a test org or sandbox if you are experimenting.
- If a custom field already exists but with the **wrong type**, the script stops with an error so you can fix it in Close.
- If **every** lead in range has a blank US state and you did **not** pass **`--include-no-state`**, the report file will contain **headers only** and the run logs a warning.
- Run from the **project root** with `python src/close_import.py` so `src` is on the import path (or set `PYTHONPATH=src`).
