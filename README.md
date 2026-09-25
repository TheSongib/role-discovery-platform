# JobTracker

A personal job board scraper that monitors company career pages for remote US
engineering and security roles and displays them in a React web UI. Local
development uses SQLite; the AWS deployment uses DynamoDB so the Kubernetes
workloads are stateless.

## What it does

- Scrapes career pages from a configurable list of companies
- Filters for **remote US** roles in **software engineering, security engineering, SRE, DevOps, and IAM**
- Excludes senior/leadership titles (staff, principal, director, architect, manager)
- Stores results in SQLite locally or DynamoDB on AWS, with deduplication and repost detection
- Removes jobs after three consecutive successful company scans no longer find them
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
├── db.py          # Persistence facade (SQLite locally, DynamoDB on AWS)
├── dynamodb_store.py # DynamoDB persistence implementation
├── api.py         # FastAPI backend (serves job data + triggers scans)
├── auth.py        # Cognito OAuth/PKCE login and admin authorization
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

## AWS and k3s deployment

The repository includes a production container, a single-node k3s manifest,
Terraform for the AWS infrastructure, and automated GitHub Actions deployment.
The web pod and scan CronJob store durable state in two encrypted DynamoDB
tables, so neither workload depends on a particular pod or node disk.

Start with the step-by-step [AWS + k3s deployment guide](docs/AWS_K3S_DEPLOYMENT.md).
The deployed dashboard is public and read-only. Cognito login, mandatory TOTP
MFA, and `admins` group membership protect scans and configuration changes.
API Gateway provides HTTPS and verifies requests to the stable Elastic IP
origin with a generated secret. It is cost-optimized for a continuously
running personal portfolio: one Graviton `t4g.small`, a 20 GiB root disk, no
load balancer, and DynamoDB on-demand billing.

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

### Legacy home-server services

The former home-server deployment used two independent systemd units, which
remain in the repository only as a rollback reference:

- `jobtracker.service` runs the API and scheduler. Uvicorn is the directly
  supervised process and is restarted automatically if it exits.
- `jobtracker-frontend.service` serves the built frontend separately, so an API
  restart does not interrupt the frontend.

The current deployment workflow targets AWS k3s and does not use these units.

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

Local development stores jobs in `jobs.db` (SQLite). Set
`DATABASE_BACKEND=dynamodb` plus `DYNAMODB_JOBS_TABLE` and
`DYNAMODB_STATE_TABLE` to use the AWS backend; the Kubernetes ConfigMap does
this automatically. Key fields are consistent across both backends:

| Field | Description |
|---|---|
| `date_found` | First time this appearance was scraped; reset when a hidden job qualifies as a repost |
| `last_seen` | Last scrape run that found this job |
| `missed_scans` | Consecutive successful company scans that did not find this job |
| `date_posted` | When the company posted the job (if available) |
| `ats_updated_at` | ATS timestamp used to detect an updated/reposted listing (when available) |
| `hidden` | Set to 1 when hidden from the UI |

`jobs.db` is local only—do not commit it to git. The AWS tables use on-demand
capacity, server-side encryption, point-in-time recovery, and deletion
protection. See the deployment guide for the one-time SQLite migration command.

After each successful company scan, matching stored jobs that were not returned
have `missed_scans` incremented. Seeing a job again resets the counter to zero.
The row is deleted on the third consecutive miss. Failed company scans do not
advance the counter. If a deleted posting later returns, it is inserted as a new
row with a new ID and `date_found` value.

For ATSes with a usable refresh signal, a hidden row can also be resurfaced
without first disappearing. If the signal advances at least one day after the
row's current `date_found`, the row is unhidden, its `date_found` is reset, and
the ATS refresh time becomes its effective `date_posted`. Greenhouse supplies a
dedicated `updated_at`; Workday uses its derived posting date except for unstable
capped values such as `30+ days`; Ashby supplies its last-published time in
`publishedAt`.

## Scan status

The dashboard shows the latest manual, scheduled, or CLI scan as `running`,
`success`, `partial`, or `failed`. Expand **View details** to see each company's
ATS, filter counts, matching-job count, and error message. The same data is
available from:

```text
GET /api/scans/latest
```

For each successful company scan, the status reports the number of jobs returned
by the configured ATS query, the number removed by include/exclude title terms,
and the number removed by remote/US eligibility checks. Keyword filtering runs
first, so the categories are mutually exclusive:

```text
jobs found = removed by keywords + not remote + matching
```

Some company URLs already contain ATS-side location, department, or seniority
filters. Jobs excluded by those server-side filters are not returned to the app
and therefore cannot be included in these counts.
