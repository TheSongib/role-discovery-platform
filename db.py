import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Iterator

DB_PATH = Path(__file__).parent / "jobs.db"
MISSED_SCAN_DELETE_THRESHOLD = 3
REPOST_MIN_AGE = timedelta(days=1)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@contextmanager
def get_conn() -> Iterator[sqlite3.Connection]:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
    finally:
        conn.close()


def init_db():
    with get_conn() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS jobs (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                title       TEXT NOT NULL,
                company     TEXT NOT NULL,
                location    TEXT,
                url         TEXT,
                is_remote   INTEGER DEFAULT 0,
                department  TEXT,
                description TEXT,
                date_posted TEXT,
                ats_updated_at TEXT,
                date_found  TEXT NOT NULL,
                last_seen   TEXT NOT NULL,
                missed_scans INTEGER NOT NULL DEFAULT 0,
                source_url  TEXT,
                UNIQUE(title, company, url)
            )
        """)
        # Migrate existing DBs that predate these columns
        for sql in [
            "ALTER TABLE jobs ADD COLUMN last_seen TEXT",
            "ALTER TABLE jobs ADD COLUMN hidden INTEGER NOT NULL DEFAULT 0",
            "ALTER TABLE jobs ADD COLUMN missed_scans INTEGER NOT NULL DEFAULT 0",
            "ALTER TABLE jobs ADD COLUMN ats_updated_at TEXT",
        ]:
            try:
                conn.execute(sql)
            except sqlite3.OperationalError:
                pass  # Column already exists
        conn.execute("UPDATE jobs SET last_seen = date_found WHERE last_seen IS NULL")
        conn.execute("UPDATE jobs SET missed_scans = 0 WHERE missed_scans IS NULL")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS scan_runs (
                id                   INTEGER PRIMARY KEY AUTOINCREMENT,
                trigger              TEXT NOT NULL,
                status               TEXT NOT NULL DEFAULT 'running',
                started_at           TEXT NOT NULL,
                finished_at          TEXT,
                total_companies      INTEGER NOT NULL DEFAULT 0,
                successful_companies INTEGER NOT NULL DEFAULT 0,
                failed_companies     INTEGER NOT NULL DEFAULT 0,
                total_found          INTEGER NOT NULL DEFAULT 0,
                total_seen           INTEGER NOT NULL DEFAULT 0,
                not_remote           INTEGER NOT NULL DEFAULT 0,
                keyword_filtered     INTEGER NOT NULL DEFAULT 0,
                new_jobs             INTEGER NOT NULL DEFAULT 0
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS company_scan_results (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                scan_id     INTEGER NOT NULL,
                company     TEXT NOT NULL,
                ats         TEXT,
                status      TEXT NOT NULL,
                jobs_found  INTEGER NOT NULL DEFAULT 0,
                jobs_seen   INTEGER NOT NULL DEFAULT 0,
                not_remote  INTEGER NOT NULL DEFAULT 0,
                keyword_filtered INTEGER NOT NULL DEFAULT 0,
                new_jobs    INTEGER NOT NULL DEFAULT 0,
                error       TEXT,
                started_at  TEXT NOT NULL,
                finished_at TEXT NOT NULL,
                FOREIGN KEY (scan_id) REFERENCES scan_runs(id) ON DELETE CASCADE,
                UNIQUE(scan_id, company)
            )
        """)
        for sql in [
            "ALTER TABLE scan_runs ADD COLUMN total_found INTEGER NOT NULL DEFAULT 0",
            "ALTER TABLE scan_runs ADD COLUMN not_remote INTEGER NOT NULL DEFAULT 0",
            "ALTER TABLE scan_runs ADD COLUMN keyword_filtered INTEGER NOT NULL DEFAULT 0",
            "ALTER TABLE company_scan_results ADD COLUMN jobs_found INTEGER NOT NULL DEFAULT 0",
            "ALTER TABLE company_scan_results ADD COLUMN not_remote INTEGER NOT NULL DEFAULT 0",
            "ALTER TABLE company_scan_results ADD COLUMN keyword_filtered INTEGER NOT NULL DEFAULT 0",
        ]:
            try:
                conn.execute(sql)
            except sqlite3.OperationalError:
                pass  # Column already exists
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_company_scan_results_scan_id "
            "ON company_scan_results(scan_id)"
        )
        conn.commit()


def create_scan_run(trigger: str, total_companies: int) -> int:
    with get_conn() as conn:
        cursor = conn.execute(
            """
            INSERT INTO scan_runs (trigger, status, started_at, total_companies)
            VALUES (?, 'running', ?, ?)
            """,
            (trigger, _utc_now(), total_companies),
        )
        conn.commit()
        return cursor.lastrowid


def record_company_scan_result(
    scan_id: int,
    company: str,
    ats: str,
    status: str,
    jobs_found: int,
    jobs_seen: int,
    not_remote: int,
    keyword_filtered: int,
    new_jobs: int,
    error: str | None,
    started_at: str,
):
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO company_scan_results
                (scan_id, company, ats, status, jobs_found, jobs_seen,
                 not_remote, keyword_filtered, new_jobs, error, started_at,
                 finished_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                scan_id,
                company,
                ats,
                status,
                jobs_found,
                jobs_seen,
                not_remote,
                keyword_filtered,
                new_jobs,
                error,
                started_at,
                _utc_now(),
            ),
        )
        conn.commit()


def finish_scan_run(
    scan_id: int,
    status: str,
    successful_companies: int,
    failed_companies: int,
    total_found: int,
    total_seen: int,
    not_remote: int,
    keyword_filtered: int,
    new_jobs: int,
):
    with get_conn() as conn:
        conn.execute(
            """
            UPDATE scan_runs
            SET status = ?, finished_at = ?, successful_companies = ?,
                failed_companies = ?, total_found = ?, total_seen = ?,
                not_remote = ?, keyword_filtered = ?, new_jobs = ?
            WHERE id = ?
            """,
            (
                status,
                _utc_now(),
                successful_companies,
                failed_companies,
                total_found,
                total_seen,
                not_remote,
                keyword_filtered,
                new_jobs,
                scan_id,
            ),
        )
        conn.commit()


def get_latest_scan() -> dict | None:
    with get_conn() as conn:
        run = conn.execute(
            "SELECT * FROM scan_runs ORDER BY id DESC LIMIT 1"
        ).fetchone()
        if run is None:
            return None

        companies = conn.execute(
            """
            SELECT company, ats, status, jobs_found, jobs_seen, not_remote,
                   keyword_filtered, new_jobs, error, started_at, finished_at
            FROM company_scan_results
            WHERE scan_id = ?
            ORDER BY CASE WHEN status = 'failed' THEN 0 ELSE 1 END,
                     company COLLATE NOCASE
            """,
            (run["id"],),
        ).fetchall()

        result = dict(run)
        result["companies"] = [dict(company) for company in companies]
        if result["status"] == "running":
            result["successful_companies"] = sum(
                company["status"] == "success" for company in companies
            )
            result["failed_companies"] = sum(
                company["status"] == "failed" for company in companies
            )
            result["total_seen"] = sum(
                company["jobs_seen"] for company in companies
            )
            result["total_found"] = sum(
                company["jobs_found"] for company in companies
            )
            result["not_remote"] = sum(
                company["not_remote"] for company in companies
            )
            result["keyword_filtered"] = sum(
                company["keyword_filtered"] for company in companies
            )
            result["new_jobs"] = sum(
                company["new_jobs"] for company in companies
            )
        return result


def _parse_datetime(value: str | None) -> datetime | None:
    """Parse an ISO date or datetime into a timezone-aware datetime."""
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _is_qualifying_repost(existing: sqlite3.Row, job: dict) -> bool:
    """Return whether a hidden job has a sufficiently old, advanced ATS signal."""
    if not existing["hidden"]:
        return False

    incoming_update = job.get("ats_updated_at")
    if not incoming_update:
        return False

    stored_update = existing["ats_updated_at"]
    if not stored_update:
        # Existing databases have no historical ATS baseline. Only bootstrap a
        # repost when the current ATS update is demonstrably newer than when we
        # first found the job; otherwise establish the baseline without surfacing.
        ats_update = _parse_datetime(incoming_update)
        first_found = _parse_datetime(existing["date_found"])
        signal_changed = bool(
            ats_update and first_found and ats_update > first_found
        )
    else:
        incoming_time = _parse_datetime(incoming_update)
        stored_time = _parse_datetime(stored_update)
        if incoming_time and stored_time:
            signal_changed = incoming_time > stored_time
        else:
            signal_changed = incoming_update != stored_update

    first_found = _parse_datetime(existing["date_found"])
    seen_now = _parse_datetime(job.get("date_found"))
    old_enough = bool(
        first_found
        and seen_now
        and seen_now - first_found >= REPOST_MIN_AGE
    )
    return signal_changed and old_enough


def upsert_job(job: dict) -> bool:
    """
    Insert a job or update scan metadata on an existing one.

    Return True for a newly inserted or newly resurfaced job. A qualifying
    repost gets fresh found/posted dates so the dashboard and notification path
    treat it as a new appearance.
    """
    with get_conn() as conn:
        existing = conn.execute(
            """
            SELECT id, hidden, date_found, ats_updated_at
            FROM jobs
            WHERE title = ? AND company = ? AND url = ?
            """,
            (job["title"], job["company"], job["url"]),
        ).fetchone()

        if existing:
            if _is_qualifying_repost(existing, job):
                conn.execute(
                    """
                    UPDATE jobs
                    SET last_seen = ?, missed_scans = 0, hidden = 0,
                        date_found = ?, date_posted = ?, ats_updated_at = ?
                    WHERE id = ?
                    """,
                    (
                        job["last_seen"],
                        job["date_found"],
                        job["ats_updated_at"],
                        job["ats_updated_at"],
                        existing["id"],
                    ),
                )
                conn.commit()
                return True

            conn.execute(
                """
                UPDATE jobs
                SET last_seen = ?, missed_scans = 0,
                    ats_updated_at = COALESCE(?, ats_updated_at)
                WHERE id = ?
                """,
                (job["last_seen"], job.get("ats_updated_at"), existing["id"]),
            )
            conn.commit()
            return False
        else:
            conn.execute(
                """
                INSERT INTO jobs
                    (title, company, location, url, is_remote, department,
                     description, date_posted, ats_updated_at, date_found,
                     last_seen, source_url)
                VALUES
                    (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    job["title"],
                    job["company"],
                    job.get("location"),
                    job["url"],
                    job.get("is_remote", 0),
                    job.get("department"),
                    job.get("description"),
                    job.get("date_posted"),
                    job.get("ats_updated_at"),
                    job["date_found"],
                    job["last_seen"],
                    job.get("source_url"),
                ),
            )
            conn.commit()
            return True


def reconcile_company_jobs(company: str, seen_jobs: list[dict]) -> int:
    """Advance missed-scan counts after a successful company scrape.

    Jobs returned by the scrape have their counter reset. Stored jobs absent
    from the result are deleted on their third consecutive successful miss.
    The caller must not invoke this after a failed or incomplete scrape.
    """
    seen_keys = {
        (job.get("title"), job.get("url"))
        for job in seen_jobs
        if job.get("company") == company
    }

    with get_conn() as conn:
        stored_jobs = conn.execute(
            """
            SELECT id, title, url, missed_scans
            FROM jobs
            WHERE company = ?
            """,
            (company,),
        ).fetchall()

        seen_ids = []
        missed_updates = []
        delete_ids = []
        for stored_job in stored_jobs:
            if (stored_job["title"], stored_job["url"]) in seen_keys:
                seen_ids.append((stored_job["id"],))
                continue

            missed_scans = stored_job["missed_scans"] + 1
            if missed_scans >= MISSED_SCAN_DELETE_THRESHOLD:
                delete_ids.append((stored_job["id"],))
            else:
                missed_updates.append((missed_scans, stored_job["id"]))

        if seen_ids:
            conn.executemany(
                "UPDATE jobs SET missed_scans = 0 WHERE id = ?",
                seen_ids,
            )
        if missed_updates:
            conn.executemany(
                "UPDATE jobs SET missed_scans = ? WHERE id = ?",
                missed_updates,
            )
        if delete_ids:
            conn.executemany("DELETE FROM jobs WHERE id = ?", delete_ids)

        conn.commit()
        return len(delete_ids)


def get_all_jobs(remote_only: bool = False, max_age_days: int = None) -> list[sqlite3.Row]:
    conditions = []
    if remote_only:
        conditions.append("is_remote = 1")
    if max_age_days is not None:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=max_age_days)).date().isoformat()
        conditions.append(f"date_found >= '{cutoff}'")

    with get_conn() as conn:
        query = "SELECT * FROM jobs"
        if conditions:
            query += " WHERE " + " AND ".join(conditions)
        query += " ORDER BY date_found DESC"
        return conn.execute(query).fetchall()


def set_hidden(job_id: int, hidden: bool):
    with get_conn() as conn:
        conn.execute("UPDATE jobs SET hidden = ? WHERE id = ?", (int(hidden), job_id))
        conn.commit()


def job_count() -> int:
    with get_conn() as conn:
        return conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
