# JobTracker

A personal job board scraper that monitors company career pages for remote US engineering and security roles, stores them in a local SQLite database, and displays them in a React web UI.

## What it does

- Scrapes career pages from a configurable list of companies
- Filters for **remote US** roles in **software engineering, security engineering, SRE, DevOps, and IAM**
- Excludes senior/leadership titles (staff, principal, director, architect, manager)
- Stores results in a local SQLite database with deduplication — `date_found` is never overwritten on re-runs
- Tracks `last_seen` so you know if a job is still active
- Records every scan and each company's success or failure so broken sources are visible
- Scans every 15 minutes on weekdays from 7 AM to 8 PM Eastern and hourly at all other times
- Serves a React frontend with live data, a one-click scan button, and the ability to hide jobs you've already applied to or aren't interested in

## Companies tracked

| Company | ATS |
|---|---|
| Affirm | Greenhouse |
| Airbnb | Greenhouse |
| Coinbase | Greenhouse |
| Dropbox | Greenhouse |
| GitLab | Greenhouse |
| Reddit | Greenhouse |
| Stripe | Greenhouse |
| Microsoft | Eightfold (Playwright) |
| Netflix | Eightfold v2 |
| CrowdStrike | Workday |
| GitHub | iCIMS / Phenom |
| Mozilla | Greenhouse |
| Circle | Workday |
| NerdWallet | Ashby |
| Confluent | Ashby |
| Zillow | Workday |
| Instacart | Greenhouse |
| Quora | Ashby |
| Twilio | Greenhouse |
| Zoom | ClinchTalent (Playwright) |
| Zscaler | Greenhouse |

## Project structure

```
JobTracker/
├── config.py      # Company list and keyword filters
├── scraper.py     # ATS scrapers (Greenhouse, Lever, Eightfold, Eightfold v2, Workday)
├── db.py          # SQLite schema and queries
├── api.py         # FastAPI backend (serves job data + triggers scans)
├── main.py        # CLI scraper entrypoint
├── export.py      # CSV/JSON export
├── dev.sh         # One-command dev server startup
├── requirements.txt
└── frontend/      # React + Vite + Tailwind UI
    └── src/
        └── App.jsx
```

## Setup

**Requirements:** Python 3.11+, Node.js 18+

```bash
# Python dependencies
pip3 install -r requirements.txt

# Install Playwright's Chromium browser (needed for Microsoft/Eightfold sites)
python3 -m playwright install chromium

# Frontend dependencies
cd frontend && npm install
```

## Running

```bash
./dev.sh
```

This starts both servers:
- API → `http://localhost:8000`
- UI  → `http://localhost:5173`

Open `http://localhost:5173` in your browser. Use the **Scan Now** button to trigger a scrape from the UI, or run it from the CLI:

```bash
python3 main.py
```

## CLI usage

```bash
python3 main.py                    # scrape all companies
python3 main.py --export csv       # scrape then export to CSV
python3 main.py --export json      # scrape then export to JSON
python3 main.py --export-only csv  # export existing DB without scraping
python3 main.py --list             # print stored jobs to terminal
```

Exported files only include jobs posted within the last **3 days** (jobs with no posting date are always included).

## Adding a company

In `config.py`, add an entry to `COMPANIES`:

```python
# Greenhouse (most common)
{
    "name": "Stripe",
    "careers_url": "https://stripe.com/jobs",
    "ats": "greenhouse",
    "board_id": "stripe",
}

# Lever
{
    "name": "Acme",
    "careers_url": "https://jobs.lever.co/acme",
    "ats": "lever",
    "board_id": "acme",
}

# Eightfold v2 (public API, e.g. Netflix)
{
    "name": "Acme",
    "careers_url": "https://jobs.acme.com/careers?location=Remote&domain=acme.com",
    "ats": "eightfold_v2",
}

# Eightfold with browser auth (e.g. Microsoft)
{
    "name": "Acme",
    "careers_url": "https://careers.acme.com/careers?...",
    "ats": "eightfold",
}

# Workday (e.g. CrowdStrike) — include filter facets in the URL
{
    "name": "Acme",
    "careers_url": "https://acme.wd5.myworkdayjobs.com/en-US/careers?locationCountry=<id>&Job_Family=<id>",
    "ats": "workday",
}
```

**Finding the board ID:** For Greenhouse, try `https://boards-api.greenhouse.io/v1/boards/{company}/jobs` where `{company}` is a lowercase slug of the company name. If it returns JSON with a `jobs` array, that's the correct ID.

## Filters

All filters live in `config.py` and take effect immediately on the next scan — no DB wipe needed.

| Setting | Purpose |
|---|---|
| `TITLE_KEYWORDS` | Job title must match at least one |
| `TITLE_EXCLUDE_KEYWORDS` | Job title must not match any |
| `REMOTE_KEYWORDS` | Location/title must indicate remote work |

Location is additionally required to indicate **US** (checked separately from `REMOTE_KEYWORDS`).

## ATS support

| ATS | Method | Notes |
|---|---|---|
| **Greenhouse** | Public REST API | Fast, no browser needed |
| **Lever** | Public REST API | Fast, no browser needed |
| **Eightfold v2** | Public REST API | Used by Netflix; parses `domain=` from the careers URL |
| **Eightfold** | Playwright (headless Chromium) | Used by Microsoft; requires browser session for API auth |
| **Workday** | Public REST API (POST) | Parses facet filters from the careers URL query string |
| **iCIMS / Phenom** | Public REST API (GET) | Used by GitHub; pagination via `page=` param |
| **Ashby** | Public REST API (GET) | Single-call response, no pagination; US filtered via `addressCountry` field |
| **ClinchTalent** | Playwright (headless Chromium) | Used by Zoom; AWS WAF requires browser to solve challenge |

## Database

Jobs are stored in `jobs.db` (SQLite). Key fields:

| Field | Description |
|---|---|
| `date_found` | First time this job was scraped — never updated |
| `last_seen` | Last scrape run that found this job |
| `date_posted` | When the company posted the job (if available) |
| `hidden` | Set to 1 when hidden from the UI |

`jobs.db` is local only — do not commit it to git.

## Scan status

The dashboard shows the latest manual, scheduled, or CLI scan as `running`,
`success`, `partial`, or `failed`. Expand **View details** to see each company's
ATS, matching-job count, and error message. The same data is available from:

```text
GET /api/scans/latest
```
