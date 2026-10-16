import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

import db
from analytics import discovery_series


class DiscoverySeriesTests(unittest.TestCase):
    def test_groups_new_roles_by_eastern_day_and_fills_zero_days(self):
        runs = [
            {"started_at": "2026-11-01T03:30:00+00:00", "new_jobs": 2},
            {"started_at": "2026-11-01T05:30:00+00:00", "new_jobs": 3},
            {"started_at": "2026-11-01T06:30:00+00:00", "new_jobs": 1},
        ]
        self.assertEqual(
            discovery_series(runs, 3, today=date(2026, 11, 2)),
            [
                {"date": "2026-10-31", "count": 2},
                {"date": "2026-11-01", "count": 4},
                {"date": "2026-11-02", "count": 0},
            ],
        )

    def test_all_time_starts_at_first_scan(self):
        self.assertEqual(
            discovery_series(
                [{"started_at": "2026-10-01T12:00:00+00:00", "new_jobs": 1}],
                0,
                today=date(2026, 10, 2),
            ),
            [{"date": "2026-10-01", "count": 1}, {"date": "2026-10-02", "count": 0}],
        )

    def test_uses_role_discovery_day_when_scan_crosses_midnight(self):
        self.assertEqual(
            discovery_series(
                [{
                    "started_at": "2026-10-17T03:55:00+00:00",
                    "new_jobs": 1,
                    "daily_counts": {"2026-10-17": 1},
                }],
                2,
                today=date(2026, 10, 17),
            ),
            [{"date": "2026-10-16", "count": 0}, {"date": "2026-10-17", "count": 1}],
        )

    def test_initial_inventory_is_excluded_without_changing_later_days(self):
        runs = [
            {"started_at": "2026-09-17T12:00:00+00:00", "new_jobs": 145},
            {"started_at": "2026-09-18T12:00:00+00:00", "new_jobs": 5},
        ]
        self.assertEqual(
            discovery_series(runs, 3, today=date(2026, 9, 19)),
            [
                {"date": "2026-09-18", "count": 5},
                {"date": "2026-09-19", "count": 0},
            ],
        )
        self.assertEqual(
            discovery_series(runs, 0, today=date(2026, 9, 19)),
            [{"date": "2026-09-18", "count": 5}, {"date": "2026-09-19", "count": 0}],
        )
        self.assertEqual(
            discovery_series(
                [{
                    "started_at": "2026-09-18T03:59:00+00:00",
                    "new_jobs": 1,
                    "daily_counts": {"2026-09-18": 1},
                }],
                0,
                today=date(2026, 9, 18),
            ),
            [{"date": "2026-09-18", "count": 1}],
        )

    def test_fixed_range_starts_at_later_of_baseline_and_normal_cutoff(self):
        before_anniversary = discovery_series([], 365, today=date(2027, 1, 1))
        self.assertEqual(before_anniversary[0], {"date": "2026-09-18", "count": 0})
        self.assertEqual(before_anniversary[-1], {"date": "2027-01-01", "count": 0})

        after_anniversary = discovery_series([], 365, today=date(2027, 10, 16))
        self.assertEqual(after_anniversary[0], {"date": "2026-10-17", "count": 0})
        self.assertEqual(len(after_anniversary), 365)


class DiscoveryHistoryTests(unittest.TestCase):
    def test_completed_scan_count_remains_after_role_is_removed(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            with patch.object(db, "DB_PATH", Path(tmp_dir) / "jobs.db"):
                db.init_db()
                scan_id = db.create_scan_run("manual", 1)
                db.upsert_job({
                    "title": "Engineer",
                    "company": "Acme",
                    "url": "https://example.com/jobs/1",
                    "date_found": "2026-10-01T12:00:00+00:00",
                    "last_seen": "2026-10-01T12:00:00+00:00",
                })
                db.finish_scan_run(
                    scan_id, "success", 1, 0, 1, 1, 0, 0, 1,
                )
                with db.get_conn() as conn:
                    conn.execute("DELETE FROM jobs")
                    conn.commit()
                runs = db.list_discovery_runs()

        self.assertEqual(len(runs), 1)
        self.assertEqual(runs[0]["new_jobs"], 1)


if __name__ == "__main__":
    unittest.main()
