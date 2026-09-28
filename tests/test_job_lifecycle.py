import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import db


def job_payload(
    *,
    company="Acme",
    date_found="2026-08-18T12:00:00+00:00",
    date_posted="2026-08-17",
    ats_updated_at=None,
):
    return {
        "title": "Software Engineer",
        "company": company,
        "location": "Remote - United States",
        "url": f"https://example.com/{company.lower()}/jobs/123",
        "is_remote": 1,
        "department": "Engineering",
        "description": None,
        "date_posted": date_posted,
        "ats_updated_at": ats_updated_at,
        "date_found": date_found,
        "last_seen": date_found,
        "source_url": f"https://example.com/{company.lower()}/careers",
    }


class JobLifecycleTests(unittest.TestCase):
    def test_hidden_job_with_changed_ats_timestamp_stays_hidden(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            database_path = Path(tmp_dir) / "jobs.db"
            original = job_payload(
                date_found="2026-08-01T12:00:00+00:00",
                date_posted="2026-07-15T09:00:00+00:00",
                ats_updated_at="2026-07-15T10:00:00+00:00",
            )
            refreshed = job_payload(
                date_found="2026-08-18T12:00:00+00:00",
                date_posted="2026-07-15T09:00:00+00:00",
                ats_updated_at="2026-08-18T08:30:00+00:00",
            )

            with patch.object(db, "DB_PATH", database_path):
                db.init_db()
                self.assertTrue(db.upsert_job(original))
                stored_id = self._only_job()["id"]
                db.set_hidden(stored_id, True)

                self.assertFalse(db.upsert_job(refreshed))
                stored = self._only_job()

            self.assertEqual(stored["id"], stored_id)
            self.assertEqual(stored["hidden"], 1)
            self.assertEqual(stored["date_found"], original["date_found"])
            self.assertEqual(stored["date_posted"], original["date_posted"])
            self.assertEqual(stored["ats_updated_at"], refreshed["ats_updated_at"])

    def test_job_is_removed_after_24_hours_absent_and_repost_is_new(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            database_path = Path(tmp_dir) / "jobs.db"
            first_posting = job_payload()
            reposted = job_payload(date_found="2026-09-01T12:00:00+00:00")
            with patch.object(db, "DB_PATH", database_path):
                db.init_db()
                self.assertTrue(db.upsert_job(first_posting))
                original_id = self._only_job()["id"]

                with patch.object(db, "_utc_now", return_value="2026-09-02T12:00:00+00:00"):
                    self.assertEqual(db.reconcile_company_jobs("Acme", []), 0)
                self.assertEqual(
                    self._only_job()["missing_since"],
                    "2026-09-02T12:00:00+00:00",
                )

                with patch.object(db, "_utc_now", return_value="2026-09-03T11:59:59+00:00"):
                    self.assertEqual(db.reconcile_company_jobs("Acme", []), 0)
                self.assertIsNotNone(self._get_job())

                with patch.object(db, "_utc_now", return_value="2026-09-03T12:00:00+00:00"):
                    self.assertEqual(db.reconcile_company_jobs("Acme", []), 1)
                self.assertIsNone(self._get_job())

                self.assertTrue(db.upsert_job(reposted))
                new_record = self._only_job()

            self.assertGreater(new_record["id"], original_id)
            self.assertEqual(new_record["date_found"], reposted["date_found"])
            self.assertEqual(new_record["missed_scans"], 0)

    def test_reappearance_before_24_hours_resets_absence(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            database_path = Path(tmp_dir) / "jobs.db"
            original = job_payload()
            seen_again = job_payload(date_found="2026-09-03T11:00:00+00:00")
            with patch.object(db, "DB_PATH", database_path):
                db.init_db()
                db.upsert_job(original)
                original_id = self._only_job()["id"]
                with patch.object(db, "_utc_now", return_value="2026-09-02T12:00:00+00:00"):
                    db.reconcile_company_jobs("Acme", [])

                self.assertFalse(db.upsert_job(seen_again))
                stored = self._only_job()

            self.assertEqual(stored["id"], original_id)
            self.assertIsNone(stored["missing_since"])
            self.assertEqual(stored["missed_scans"], 0)

    def test_permanently_ignored_job_is_retained_and_never_listed(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            database_path = Path(tmp_dir) / "jobs.db"
            original = job_payload()
            with patch.object(db, "DB_PATH", database_path):
                db.init_db()
                db.upsert_job(original)
                job_id = self._only_job()["id"]
                db.set_ignored_permanently(job_id)

                self.assertEqual(db.list_jobs(show_hidden=False, max_age_days=0), [])
                self.assertEqual(db.list_jobs(show_hidden=True, max_age_days=0), [])
                self.assertEqual(db.get_all_jobs(), [])
                with patch.object(db, "_utc_now", return_value="2026-10-01T12:00:00+00:00"):
                    self.assertEqual(db.reconcile_company_jobs("Acme", []), 0)
                self.assertFalse(db.upsert_job(original))
                stored = self._only_job()

            self.assertEqual(stored["ignored_permanently"], 1)
            self.assertEqual(stored["hidden"], 1)

    def test_reconciliation_only_changes_the_successfully_scanned_company(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            database_path = Path(tmp_dir) / "jobs.db"
            with patch.object(db, "DB_PATH", database_path):
                db.init_db()
                db.upsert_job(job_payload(company="Acme"))
                db.upsert_job(job_payload(company="Beta"))

                with patch.object(db, "_utc_now", return_value="2026-09-02T12:00:00+00:00"):
                    db.reconcile_company_jobs("Acme", [])
                with patch.object(db, "_utc_now", return_value="2026-09-03T12:00:00+00:00"):
                    db.reconcile_company_jobs("Acme", [])

                with db.get_conn() as conn:
                    companies = [
                        row["company"]
                        for row in conn.execute(
                            "SELECT company FROM jobs ORDER BY company"
                        )
                    ]

            self.assertEqual(companies, ["Beta"])

    def test_init_db_migrates_existing_jobs_with_zero_misses(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            database_path = Path(tmp_dir) / "jobs.db"
            with sqlite3.connect(database_path) as conn:
                conn.execute(
                    """
                    CREATE TABLE jobs (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        title TEXT NOT NULL,
                        company TEXT NOT NULL,
                        location TEXT,
                        url TEXT,
                        is_remote INTEGER DEFAULT 0,
                        department TEXT,
                        description TEXT,
                        date_posted TEXT,
                        date_found TEXT NOT NULL,
                        last_seen TEXT NOT NULL,
                        source_url TEXT,
                        hidden INTEGER NOT NULL DEFAULT 0,
                        UNIQUE(title, company, url)
                    )
                    """
                )
                conn.execute(
                    """
                    INSERT INTO jobs
                        (title, company, url, date_found, last_seen)
                    VALUES ('Engineer', 'Acme', 'https://example.com/job',
                            '2026-08-01', '2026-08-01')
                    """
                )
            conn.close()

            with patch.object(db, "DB_PATH", database_path):
                db.init_db()
                with db.get_conn() as conn:
                    columns = {
                        row["name"] for row in conn.execute("PRAGMA table_info(jobs)")
                    }
                    missed_scans = conn.execute(
                        "SELECT missed_scans FROM jobs"
                    ).fetchone()["missed_scans"]

            self.assertIn("missed_scans", columns)
            self.assertIn("ats_updated_at", columns)
            self.assertIn("missing_since", columns)
            self.assertIn("ignored_permanently", columns)
            self.assertEqual(missed_scans, 0)

    @staticmethod
    def _get_job():
        with db.get_conn() as conn:
            row = conn.execute("SELECT * FROM jobs").fetchone()
            return dict(row) if row else None

    def _only_job(self):
        job = self._get_job()
        self.assertIsNotNone(job)
        return job


if __name__ == "__main__":
    unittest.main()
