import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import db


class ScanStatusPersistenceTests(unittest.TestCase):
    def test_persists_latest_scan_and_company_results(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            database_path = Path(tmp_dir) / "jobs.db"
            with patch.object(db, "DB_PATH", database_path):
                db.init_db()
                scan_id = db.create_scan_run("manual", 2)
                db.record_company_scan_result(
                    scan_id=scan_id,
                    company="Airbnb",
                    ats="greenhouse",
                    status="success",
                    jobs_found=12,
                    jobs_seen=3,
                    not_remote=7,
                    keyword_filtered=2,
                    new_jobs=1,
                    error=None,
                    started_at="2026-08-14T12:00:00+00:00",
                )
                db.record_company_scan_result(
                    scan_id=scan_id,
                    company="Microsoft",
                    ats="eightfold",
                    status="failed",
                    jobs_found=0,
                    jobs_seen=0,
                    not_remote=0,
                    keyword_filtered=0,
                    new_jobs=0,
                    error="TimeoutError: navigation timeout",
                    started_at="2026-08-14T12:00:01+00:00",
                )
                db.finish_scan_run(
                    scan_id=scan_id,
                    status="partial",
                    successful_companies=1,
                    failed_companies=1,
                    total_found=12,
                    total_seen=3,
                    not_remote=7,
                    keyword_filtered=2,
                    new_jobs=1,
                )

                latest = db.get_latest_scan()

        self.assertEqual(latest["id"], scan_id)
        self.assertEqual(latest["status"], "partial")
        self.assertEqual(latest["successful_companies"], 1)
        self.assertEqual(latest["failed_companies"], 1)
        self.assertEqual(latest["total_found"], 12)
        self.assertEqual(latest["not_remote"], 7)
        self.assertEqual(latest["keyword_filtered"], 2)
        self.assertEqual(len(latest["companies"]), 2)
        airbnb = next(
            company for company in latest["companies"]
            if company["company"] == "Airbnb"
        )
        self.assertEqual(airbnb["jobs_found"], 12)
        self.assertEqual(airbnb["not_remote"], 7)
        self.assertEqual(airbnb["keyword_filtered"], 2)
        microsoft = next(
            company for company in latest["companies"]
            if company["company"] == "Microsoft"
        )
        self.assertEqual(microsoft["status"], "failed")
        self.assertIn("navigation timeout", microsoft["error"])

    def test_running_scan_aggregates_completed_company_filter_counts(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            database_path = Path(tmp_dir) / "jobs.db"
            with patch.object(db, "DB_PATH", database_path):
                db.init_db()
                scan_id = db.create_scan_run("scheduled", 2)
                db.record_company_scan_result(
                    scan_id=scan_id,
                    company="Airbnb",
                    ats="greenhouse",
                    status="success",
                    jobs_found=20,
                    jobs_seen=4,
                    not_remote=11,
                    keyword_filtered=5,
                    new_jobs=2,
                    error=None,
                    started_at="2026-08-14T12:00:00+00:00",
                )

                latest = db.get_latest_scan()

        self.assertEqual(latest["status"], "running")
        self.assertEqual(latest["total_found"], 20)
        self.assertEqual(latest["not_remote"], 11)
        self.assertEqual(latest["keyword_filtered"], 5)
        self.assertEqual(latest["total_seen"], 4)

    def test_migrates_filter_counts_onto_existing_scan_tables(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            database_path = Path(tmp_dir) / "jobs.db"
            with sqlite3.connect(database_path) as conn:
                conn.execute(
                    """
                    CREATE TABLE scan_runs (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        trigger TEXT NOT NULL,
                        status TEXT NOT NULL DEFAULT 'running',
                        started_at TEXT NOT NULL,
                        finished_at TEXT,
                        total_companies INTEGER NOT NULL DEFAULT 0,
                        successful_companies INTEGER NOT NULL DEFAULT 0,
                        failed_companies INTEGER NOT NULL DEFAULT 0,
                        total_seen INTEGER NOT NULL DEFAULT 0,
                        new_jobs INTEGER NOT NULL DEFAULT 0
                    )
                    """
                )
                conn.execute(
                    """
                    CREATE TABLE company_scan_results (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        scan_id INTEGER NOT NULL,
                        company TEXT NOT NULL,
                        ats TEXT,
                        status TEXT NOT NULL,
                        jobs_seen INTEGER NOT NULL DEFAULT 0,
                        new_jobs INTEGER NOT NULL DEFAULT 0,
                        error TEXT,
                        started_at TEXT NOT NULL,
                        finished_at TEXT NOT NULL,
                        FOREIGN KEY (scan_id) REFERENCES scan_runs(id) ON DELETE CASCADE,
                        UNIQUE(scan_id, company)
                    )
                    """
                )

            with patch.object(db, "DB_PATH", database_path):
                db.init_db()
                with db.get_conn() as conn:
                    run_columns = {
                        row["name"]
                        for row in conn.execute("PRAGMA table_info(scan_runs)")
                    }
                    company_columns = {
                        row["name"]
                        for row in conn.execute(
                            "PRAGMA table_info(company_scan_results)"
                        )
                    }

        self.assertTrue(
            {"total_found", "not_remote", "keyword_filtered"} <= run_columns
        )
        self.assertTrue(
            {"jobs_found", "not_remote", "keyword_filtered"}
            <= company_columns
        )


if __name__ == "__main__":
    unittest.main()
