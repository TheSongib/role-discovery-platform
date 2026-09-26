import asyncio
import hmac
import os
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import requests
from fastapi import BackgroundTasks, Depends, FastAPI, Query, Request, status
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from db import (
    acquire_scan_lock,
    create_scan_run,
    finish_scan_run,
    get_latest_scan,
    init_db,
    list_jobs as query_jobs,
    reconcile_company_jobs,
    record_company_scan_result,
    release_scan_lock,
    set_hidden,
    upsert_job,
)
from config import COMPANIES
from scraper import scrape_company
from keywords_store import get_keywords, save_keywords
from auth import (
    auth_status,
    begin_login,
    finish_login,
    logout,
    optional_admin,
    require_admin,
)

NTFY_TOPIC = os.getenv("NTFY_TOPIC", "")
ORIGIN_VERIFY_SECRET = os.getenv("ORIGIN_VERIFY_SECRET", "")
PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "").rstrip("/")

FRONTEND_DIST = Path(__file__).parent / "frontend" / "dist"

app = FastAPI(title="JobTracker API")

EASTERN_TIME = ZoneInfo("America/New_York")
WEEKDAY_SCAN_START_HOUR = 7
WEEKDAY_SCAN_END_HOUR = 20


@app.middleware("http")
async def enforce_origin_boundary(request: Request, call_next):
    """Reject direct-origin traffic and add browser security headers."""
    if ORIGIN_VERIFY_SECRET and request.url.path != "/api/health":
        supplied = request.headers.get("x-origin-verify", "")
        if not hmac.compare_digest(supplied, ORIGIN_VERIFY_SECRET):
            return JSONResponse(status_code=403, content={"detail": "Forbidden"})

    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; base-uri 'self'; frame-ancestors 'none'; "
        "form-action 'self'; img-src 'self' data:; script-src 'self'; "
        "style-src 'self' 'unsafe-inline'"
    )
    if PUBLIC_BASE_URL.startswith("https://"):
        response.headers["Strict-Transport-Security"] = (
            "max-age=31536000; includeSubDomains"
        )
    return response


@app.get("/api/health")
def health():
    """Lightweight Kubernetes liveness/readiness endpoint."""
    return {"status": "ok"}


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
    if os.getenv("ENABLE_SCHEDULER", "true").lower() not in {"1", "true", "yes"}:
        return

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


@app.get("/api/jobs")
def list_jobs(
    show_hidden: bool = False,
    max_age_days: int = 3,
    admin: dict | None = Depends(optional_admin),
):
    # Hidden jobs are private administrative state even though active jobs are
    # intentionally visible without an account.
    jobs = query_jobs(
        show_hidden=show_hidden and admin is not None,
        max_age_days=max_age_days,
    )
    company_colors = {
        company["name"]: company["brand_color"]
        for company in COMPANIES
        if company.get("brand_color")
    }
    return [
        {
            **job,
            "company_color": company_colors.get(job.get("company"), "#94A3B8"),
        }
        for job in jobs
    ]


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
    lock_owner = uuid.uuid4().hex
    if not acquire_scan_lock(lock_owner):
        return {
            "status": "already_running",
            "new_jobs": 0,
            "total_found": 0,
            "total_seen": 0,
            "not_remote": 0,
            "keyword_filtered": 0,
            "successful_companies": 0,
            "failed_companies": 0,
        }
    try:
        return _run_scan_unlocked(trigger)
    finally:
        release_scan_lock(lock_owner)


def _run_scan_unlocked(trigger: str = "manual") -> dict:
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
            removed_jobs = reconcile_company_jobs(company["name"], jobs)
            if removed_jobs:
                print(
                    f"[{company['name']}] removed {removed_jobs} job(s) "
                    "after 3 consecutive successful misses"
                )
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


@app.post("/api/scan", status_code=status.HTTP_202_ACCEPTED)
def run_scan(
    background_tasks: BackgroundTasks,
    _admin: dict = Depends(require_admin),
):
    # API Gateway has a 30-second integration timeout, while a complete scan
    # takes several minutes. DynamoDB's scan lock still prevents overlap.
    background_tasks.add_task(_run_scan, "manual")
    return {
        "status": "accepted",
        "accepted_at": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/api/scans/latest")
def latest_scan():
    init_db()
    return get_latest_scan()


class HidePayload(BaseModel):
    hidden: bool


@app.patch("/api/jobs/{job_id}")
def patch_job(
    job_id: str,
    payload: HidePayload,
    _admin: dict = Depends(require_admin),
):
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
def update_keyword_config(
    payload: KeywordsPayload,
    _admin: dict = Depends(require_admin),
):
    save_keywords(payload.title_keywords, payload.title_exclude_keywords)
    return {"ok": True}


@app.get("/api/auth/status")
def get_auth_status(request: Request):
    return auth_status(request)


@app.get("/api/auth/login", response_class=RedirectResponse)
def login():
    return begin_login()


@app.get("/api/auth/callback", response_class=RedirectResponse)
def auth_callback(
    request: Request,
    code: str = Query(min_length=1),
    state_value: str = Query(alias="state", min_length=1),
):
    return finish_login(request, code, state_value)


@app.get("/api/auth/logout", response_class=RedirectResponse)
def end_session():
    return logout()


# Serve built frontend in production (after `npm run build`)
if FRONTEND_DIST.exists():
    app.mount("/", StaticFiles(directory=FRONTEND_DIST, html=True), name="static")
