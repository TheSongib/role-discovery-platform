import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import api
import db
from scraper import ScrapeResult


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


def scrape_result(jobs):
    return ScrapeResult(
        jobs,
        total_found=len(jobs),
        not_remote=0,
        keyword_filtered=0,
    )


class JobLifecycleTests(unittest.TestCase):
    def test_legacy_hidden_job_can_use_first_persisted_ats_timestamp(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            database_path = Path(tmp_dir) / "jobs.db"
            original = job_payload(date_found="2026-08-01T12:00:00+00:00")
            refreshed = job_payload(
                date_found="2026-08-19T12:00:00+00:00",
                ats_updated_at="2026-08-18T08:30:00+00:00",
            )

            with patch.object(db, "DB_PATH", database_path):
                db.init_db()
                db.upsert_job(original)
                db.set_hidden(self._only_job()["id"], True)

                self.assertTrue(db.upsert_job(refreshed))
                resurfaced = self._only_job()

            self.assertEqual(resurfaced["hidden"], 0)
            self.assertEqual(resurfaced["date_found"], refreshed["date_found"])

    def test_hidden_job_with_changed_ats_timestamp_is_resurfaced(self):
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

                self.assertTrue(db.upsert_job(refreshed))
                resurfaced = self._only_job()

            self.assertEqual(resurfaced["id"], stored_id)
            self.assertEqual(resurfaced["hidden"], 0)
            self.assertEqual(resurfaced["date_found"], refreshed["date_found"])
            self.assertEqual(
                resurfaced["date_posted"], refreshed["ats_updated_at"]
            )
            self.assertEqual(
                resurfaced["ats_updated_at"], refreshed["ats_updated_at"]
            )

    def test_hidden_job_with_unchanged_ats_timestamp_stays_hidden(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            database_path = Path(tmp_dir) / "jobs.db"
            original = job_payload(
                date_found="2026-08-01T12:00:00+00:00",
                ats_updated_at="2026-07-15T10:00:00+00:00",
            )
            seen_again = job_payload(
                date_found="2026-08-18T12:00:00+00:00",
                ats_updated_at=original["ats_updated_at"],
            )

            with patch.object(db, "DB_PATH", database_path):
                db.init_db()
                db.upsert_job(original)
                db.set_hidden(self._only_job()["id"], True)

                self.assertFalse(db.upsert_job(seen_again))
                stored = self._only_job()

            self.assertEqual(stored["hidden"], 1)
            self.assertEqual(stored["date_found"], original["date_found"])
            self.assertEqual(stored["date_posted"], original["date_posted"])

    def test_hidden_job_with_older_ats_timestamp_stays_hidden(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            database_path = Path(tmp_dir) / "jobs.db"
            original = job_payload(
                date_found="2026-08-01T12:00:00+00:00",
                ats_updated_at="2026-07-15T10:00:00+00:00",
            )
            stale_signal = job_payload(
                date_found="2026-08-18T12:00:00+00:00",
                ats_updated_at="2026-07-14T10:00:00+00:00",
            )

            with patch.object(db, "DB_PATH", database_path):
                db.init_db()
                db.upsert_job(original)
                db.set_hidden(self._only_job()["id"], True)

                self.assertFalse(db.upsert_job(stale_signal))
                stored = self._only_job()

            self.assertEqual(stored["hidden"], 1)

    def test_same_day_ats_edit_does_not_resurface_later(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            database_path = Path(tmp_dir) / "jobs.db"
            original = job_payload(
                date_found="2026-08-18T12:00:00+00:00",
                ats_updated_at="2026-08-18T11:00:00+00:00",
            )
            edited = job_payload(
                date_found="2026-08-18T18:00:00+00:00",
                ats_updated_at="2026-08-18T17:00:00+00:00",
            )
            later_scan = job_payload(
                date_found="2026-08-22T12:00:00+00:00",
                ats_updated_at=edited["ats_updated_at"],
            )

            with patch.object(db, "DB_PATH", database_path):
                db.init_db()
                db.upsert_job(original)
                db.set_hidden(self._only_job()["id"], True)

                self.assertFalse(db.upsert_job(edited))
                self.assertFalse(db.upsert_job(later_scan))
                stored = self._only_job()

            self.assertEqual(stored["hidden"], 1)
            self.assertEqual(stored["ats_updated_at"], edited["ats_updated_at"])

    def test_three_consecutive_successful_misses_delete_and_repost_as_new(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            database_path = Path(tmp_dir) / "jobs.db"
            first_posting = job_payload()
            seen_again = job_payload(date_found="2026-08-19T12:00:00+00:00")
            reposted = job_payload(date_found="2026-09-01T12:00:00+00:00")
            empty = scrape_result([])

            scrape_results = [
                scrape_result([first_posting]),
                RuntimeError("ATS unavailable"),
                empty,
                empty,
                scrape_result([seen_again]),
                empty,
                empty,
                empty,
                scrape_result([reposted]),
            ]

            with (
                patch.object(db, "DB_PATH", database_path),
                patch.object(api, "COMPANIES", [{"name": "Acme", "ats": "test"}]),
                patch.object(api, "scrape_company", side_effect=scrape_results),
                patch.object(api, "_notify"),
            ):
                api._run_scan()
                original = self._only_job()
                original_id = original["id"]
                self.assertEqual(original["missed_scans"], 0)

                failed_scan = api._run_scan()
                self.assertEqual(failed_scan["status"], "failed")
                self.assertEqual(self._only_job()["missed_scans"], 0)

                api._run_scan()
                self.assertEqual(self._only_job()["missed_scans"], 1)

                api._run_scan()
                self.assertEqual(self._only_job()["missed_scans"], 2)

                api._run_scan()
                rediscovered = self._only_job()
                self.assertEqual(rediscovered["id"], original_id)
                self.assertEqual(rediscovered["missed_scans"], 0)
                self.assertEqual(rediscovered["date_found"], first_posting["date_found"])

                api._run_scan()
                api._run_scan()
                api._run_scan()
                self.assertIsNone(self._get_job())

                repost_scan = api._run_scan()
                new_record = self._only_job()

            self.assertEqual(repost_scan["new_jobs"], 1)
            self.assertGreater(new_record["id"], original_id)
            self.assertEqual(new_record["date_found"], reposted["date_found"])
            self.assertEqual(new_record["missed_scans"], 0)

    def test_reconciliation_only_changes_the_successfully_scanned_company(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            database_path = Path(tmp_dir) / "jobs.db"
            with patch.object(db, "DB_PATH", database_path):
                db.init_db()
                db.upsert_job(job_payload(company="Acme"))
                db.upsert_job(job_payload(company="Beta"))

                for _ in range(3):
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
