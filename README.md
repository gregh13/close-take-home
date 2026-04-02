# Close CRM CSV import and report

This project reads a CSV of companies and contacts, cleans the data, creates **leads** in [Close](https://close.com/) (with the right custom fields), then writes a **summary report** by US state for leads whose **company founded** date falls in a date range you choose.

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
5. After a short pause, search Close for leads in that founded-date range and write the state report.

### 6. Find your outputs

By default (no extra flags):

| Output | Location |
|--------|----------|
| Normalized CSV | `src/data/normalized/normalized_import.csv` |
| State report CSV | `src/data/output/report.csv` |

---

## Optional command-line flags

| Flag | Meaning |
|------|--------|
| `--input PATH` | Input CSV (default: mock file under `src/data/input/`) |
| `--output PATH` | Report CSV path |
| `--normalized PATH` | Normalized intermediate CSV path |
| `--search-delay SECONDS` | Wait after import before searching Close (default: `3`; helps if search lags) |
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

- Running the script **creates real leads** in the Close organization tied to your API key. Use a test org or sandbox if you are experimenting.
- If a custom field already exists but with the **wrong type**, the script stops with an error so you can fix it in Close.
