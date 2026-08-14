import asyncio
import os
import sqlite3
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

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

SCAN_INTERVAL_SECONDS = 15 * 60  # 15 minutes


@app.on_event("startup")
async def start_scheduler():
    async def scheduler():
        while True:
            await asyncio.sleep(SCAN_INTERVAL_SECONDS)
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
    total_seen = 0
    successful_companies = 0
    failed_companies = 0
    new_jobs = []
    for company in COMPANIES:
        company_started_at = datetime.now(timezone.utc).isoformat()
        company_new = 0
        try:
            jobs = scrape_company(company)
            for job in jobs:
                total_seen += 1
                if upsert_job(job):
                    total_new += 1
                    company_new += 1
                    new_jobs.append(job)
        except Exception as exc:
            failed_companies += 1
            error = f"{type(exc).__name__}: {exc}"
            print(f"[{company['name']}] scan failed, continuing: {error}")
            record_company_scan_result(
                scan_id=scan_id,
                company=company["name"],
                ats=company.get("ats", "unknown"),
                status="failed",
                jobs_seen=0,
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
            jobs_seen=len(jobs),
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
        total_seen=total_seen,
        new_jobs=total_new,
    )
    if new_jobs:
        _notify(new_jobs)
    return {
        "scan_id": scan_id,
        "status": status,
        "new_jobs": total_new,
        "total_seen": total_seen,
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
