import asyncio
import os
import sqlite3
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import requests
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from db import (
    create_scan_run,
    finish_scan_run,
    get_latest_scan,
    init_db,
    record_company_scan_result,
    set_hidden,
    upsert_job,
)
from config import COMPANIES
from scraper import scrape_company
from keywords_store import get_keywords, save_keywords

NTFY_TOPIC = os.getenv("NTFY_TOPIC", "")

DB_PATH = Path(__file__).parent / "jobs.db"
FRONTEND_DIST = Path(__file__).parent / "frontend" / "dist"

app = FastAPI(title="JobTracker API")

EASTERN_TIME = ZoneInfo("America/New_York")
WEEKDAY_SCAN_START_HOUR = 7
WEEKDAY_SCAN_END_HOUR = 20


def _is_frequent_scan_window(when: datetime) -> bool:
    """Return whether ``when`` falls in the weekday 7 AM-8 PM ET window."""
    eastern = when.astimezone(EASTERN_TIME)
    return (
        eastern.weekday() < 5
        and WEEKDAY_SCAN_START_HOUR <= eastern.hour < WEEKDAY_SCAN_END_HOUR
    )


def _next_scheduled_scan(when: datetime | None = None) -> datetime:
    """Return the next quarter-hour or hourly scan boundary in UTC."""
    if when is None:
        when = datetime.now(timezone.utc)
    if when.tzinfo is None:
        raise ValueError("Scheduler timestamps must be timezone-aware")

    # Search in UTC so daylight-saving transitions (including the repeated
    # fall-back hour) still produce one scan at every applicable ET boundary.
    candidate = when.astimezone(timezone.utc).replace(second=0, microsecond=0)
    candidate += timedelta(minutes=1)
    for _ in range(60):
        eastern = candidate.astimezone(EASTERN_TIME)
        if _is_frequent_scan_window(candidate):
            if eastern.minute % 15 == 0:
                return candidate
        elif eastern.minute == 0:
            return candidate
        candidate += timedelta(minutes=1)

    raise RuntimeError("Could not calculate the next scheduled scan")


@app.on_event("startup")
async def start_scheduler():
    async def scheduler():
        while True:
            now = datetime.now(timezone.utc)
            next_scan = _next_scheduled_scan(now)
            await asyncio.sleep((next_scan - now).total_seconds())
            try:
                loop = asyncio.get_event_loop()
                await loop.run_in_executor(None, _run_scan, "scheduled")
            except Exception as exc:
                print(f"[scheduler] scan failed, will retry next cycle: {exc}")

    asyncio.create_task(scheduler())


app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "PATCH", "POST", "PUT"],
    allow_headers=["*"],
)


@app.get("/api/jobs")
def list_jobs(show_hidden: bool = False, max_age_days: int = 3):
    if not DB_PATH.exists():
        return []
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    if max_age_days > 0:
        cutoff = (date.today() - timedelta(days=max_age_days)).isoformat()
        rows = conn.execute(
            """
            SELECT * FROM jobs
            WHERE date_found >= ?
              AND (hidden = 0 OR ? = 1)
            ORDER BY DATE(date_found) DESC, date_posted DESC
            """,
            (cutoff, int(show_hidden)),
        ).fetchall()
    else:
        # max_age_days=0 means all time — no date filter
        rows = conn.execute(
            """
            SELECT * FROM jobs
            WHERE (hidden = 0 OR ? = 1)
            ORDER BY DATE(date_found) DESC, date_posted DESC
            """,
            (int(show_hidden),),
        ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def _notify(new_jobs: list[dict]):
    if not NTFY_TOPIC:
        return
    lines = [f"{j['company']} — {j['title']}" for j in new_jobs[:10]]
    if len(new_jobs) > 10:
        lines.append(f"... and {len(new_jobs) - 10} more")
    body = "\n".join(lines)
    try:
        requests.post(
            f"https://ntfy.sh/{NTFY_TOPIC}",
            data=body.encode("utf-8"),
            headers={
                "Title": f"{len(new_jobs)} new job{'s' if len(new_jobs) != 1 else ''} found",
                "Priority": "default",
                "Tags": "briefcase",
            },
            timeout=10,
        )
    except Exception:
        pass


def _run_scan(trigger: str = "manual") -> dict:
    init_db()
    scan_id = create_scan_run(trigger, len(COMPANIES))
    total_new = 0
    total_found = 0
    total_seen = 0
    total_not_remote = 0
    total_keyword_filtered = 0
    successful_companies = 0
    failed_companies = 0
    new_jobs = []
    for company in COMPANIES:
        company_started_at = datetime.now(timezone.utc).isoformat()
        company_new = 0
        try:
            jobs = scrape_company(company)
            company_found = getattr(jobs, "total_found", len(jobs))
            company_not_remote = getattr(jobs, "not_remote", 0)
            company_keyword_filtered = getattr(jobs, "keyword_filtered", 0)
            for job in jobs:
                if upsert_job(job):
                    total_new += 1
                    company_new += 1
                    new_jobs.append(job)
            total_found += company_found
            total_seen += len(jobs)
            total_not_remote += company_not_remote
            total_keyword_filtered += company_keyword_filtered
        except Exception as exc:
            failed_companies += 1
            error = f"{type(exc).__name__}: {exc}"
            print(f"[{company['name']}] scan failed, continuing: {error}")
            record_company_scan_result(
                scan_id=scan_id,
                company=company["name"],
                ats=company.get("ats", "unknown"),
                status="failed",
                jobs_found=0,
                jobs_seen=0,
                not_remote=0,
                keyword_filtered=0,
                new_jobs=0,
                error=error[:2000],
                started_at=company_started_at,
            )
            continue

        successful_companies += 1
        record_company_scan_result(
            scan_id=scan_id,
            company=company["name"],
            ats=company.get("ats", "unknown"),
            status="success",
            jobs_found=company_found,
            jobs_seen=len(jobs),
            not_remote=company_not_remote,
            keyword_filtered=company_keyword_filtered,
            new_jobs=company_new,
            error=None,
            started_at=company_started_at,
        )

    if failed_companies == 0:
        status = "success"
    elif successful_companies == 0:
        status = "failed"
    else:
        status = "partial"

    finish_scan_run(
        scan_id=scan_id,
        status=status,
        successful_companies=successful_companies,
        failed_companies=failed_companies,
        total_found=total_found,
        total_seen=total_seen,
        not_remote=total_not_remote,
        keyword_filtered=total_keyword_filtered,
        new_jobs=total_new,
    )
    if new_jobs:
        _notify(new_jobs)
    return {
        "scan_id": scan_id,
        "status": status,
        "new_jobs": total_new,
        "total_found": total_found,
        "total_seen": total_seen,
        "not_remote": total_not_remote,
        "keyword_filtered": total_keyword_filtered,
        "successful_companies": successful_companies,
        "failed_companies": failed_companies,
    }


@app.post("/api/scan")
async def run_scan():
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(None, _run_scan, "manual")
    return result


@app.get("/api/scans/latest")
def latest_scan():
    init_db()
    return get_latest_scan()


class HidePayload(BaseModel):
    hidden: bool


@app.patch("/api/jobs/{job_id}")
def patch_job(job_id: int, payload: HidePayload):
    init_db()
    set_hidden(job_id, payload.hidden)
    return {"ok": True}


@app.get("/api/config/keywords")
def get_keyword_config():
    return get_keywords()


class KeywordsPayload(BaseModel):
    title_keywords: list[str]
    title_exclude_keywords: list[str]


@app.put("/api/config/keywords")
def update_keyword_config(payload: KeywordsPayload):
    save_keywords(payload.title_keywords, payload.title_exclude_keywords)
    return {"ok": True}


# Serve built frontend in production (after `npm run build`)
if FRONTEND_DIST.exists():
    app.mount("/", StaticFiles(directory=FRONTEND_DIST, html=True), name="static")
