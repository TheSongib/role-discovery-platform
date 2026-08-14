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
                    jobs_seen=3,
                    new_jobs=1,
                    error=None,
                    started_at="2026-08-14T12:00:00+00:00",
                )
                db.record_company_scan_result(
                    scan_id=scan_id,
                    company="Microsoft",
                    ats="eightfold",
                    status="failed",
                    jobs_seen=0,
                    new_jobs=0,
                    error="TimeoutError: navigation timeout",
                    started_at="2026-08-14T12:00:01+00:00",
                )
                db.finish_scan_run(
                    scan_id=scan_id,
                    status="partial",
                    successful_companies=1,
                    failed_companies=1,
                    total_seen=3,
                    new_jobs=1,
                )

                latest = db.get_latest_scan()

        self.assertEqual(latest["id"], scan_id)
        self.assertEqual(latest["status"], "partial")
        self.assertEqual(latest["successful_companies"], 1)
        self.assertEqual(latest["failed_companies"], 1)
        self.assertEqual(len(latest["companies"]), 2)
        microsoft = next(
            company for company in latest["companies"]
            if company["company"] == "Microsoft"
        )
        self.assertEqual(microsoft["status"], "failed")
        self.assertIn("navigation timeout", microsoft["error"])


if __name__ == "__main__":
    unittest.main()
