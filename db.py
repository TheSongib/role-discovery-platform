import sqlite3
from datetime import datetime, timezone, timedelta
from pathlib import Path

DB_PATH = Path("jobs.db")


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


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
                date_found  TEXT NOT NULL,
                last_seen   TEXT NOT NULL,
                source_url  TEXT,
                UNIQUE(title, company, url)
            )
        """)
        # Migrate existing DBs that predate these columns
        for sql in [
            "ALTER TABLE jobs ADD COLUMN last_seen TEXT",
            "ALTER TABLE jobs ADD COLUMN hidden INTEGER NOT NULL DEFAULT 0",
        ]:
            try:
                conn.execute(sql)
            except sqlite3.OperationalError:
                pass  # Column already exists
        conn.execute("UPDATE jobs SET last_seen = date_found WHERE last_seen IS NULL")
        conn.commit()


def upsert_job(job: dict) -> bool:
    """
    Insert a new job or update last_seen on an existing one.
    Returns True if the job was new, False if it already existed.
    date_found is never overwritten — it always reflects the first time we saw the job.
    """
    with get_conn() as conn:
        existing = conn.execute(
            "SELECT id FROM jobs WHERE title = ? AND company = ? AND url = ?",
            (job["title"], job["company"], job["url"]),
        ).fetchone()

        if existing:
            conn.execute(
                "UPDATE jobs SET last_seen = ? WHERE id = ?",
                (job["last_seen"], existing["id"]),
            )
            conn.commit()
            return False
        else:
            conn.execute(
                """
                INSERT INTO jobs
                    (title, company, location, url, is_remote, department,
                     description, date_posted, date_found, last_seen, source_url)
                VALUES
                    (:title, :company, :location, :url, :is_remote, :department,
                     :description, :date_posted, :date_found, :last_seen, :source_url)
                """,
                job,
            )
            conn.commit()
            return True


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
