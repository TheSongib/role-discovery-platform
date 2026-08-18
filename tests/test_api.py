import unittest
from datetime import datetime
from unittest.mock import call, patch

import api
from scraper import ScrapeResult


class SchedulerTests(unittest.TestCase):
    @staticmethod
    def eastern(year, month, day, hour, minute=0, second=0, fold=0):
        return datetime(
            year,
            month,
            day,
            hour,
            minute,
            second,
            tzinfo=api.EASTERN_TIME,
            fold=fold,
        )

    def assert_next_scan(self, current, expected):
        actual = api._next_scheduled_scan(current).astimezone(api.EASTERN_TIME)
        self.assertEqual(actual, expected)

    def test_weekday_daytime_scans_on_quarter_hours(self):
        self.assert_next_scan(
            self.eastern(2026, 8, 17, 7, 1),
            self.eastern(2026, 8, 17, 7, 15),
        )
        self.assert_next_scan(
            self.eastern(2026, 8, 17, 12, 15),
            self.eastern(2026, 8, 17, 12, 30),
        )

    def test_weekday_schedule_transitions_at_7_am_and_8_pm(self):
        self.assert_next_scan(
            self.eastern(2026, 8, 17, 6, 30),
            self.eastern(2026, 8, 17, 7, 0),
        )
        self.assert_next_scan(
            self.eastern(2026, 8, 17, 19, 50),
            self.eastern(2026, 8, 17, 20, 0),
        )
        self.assert_next_scan(
            self.eastern(2026, 8, 17, 20, 0),
            self.eastern(2026, 8, 17, 21, 0),
        )

    def test_weekends_scan_hourly(self):
        self.assert_next_scan(
            self.eastern(2026, 8, 22, 10, 5),
            self.eastern(2026, 8, 22, 11, 0),
        )

    def test_hourly_schedule_handles_repeated_dst_hour(self):
        self.assert_next_scan(
            self.eastern(2026, 11, 1, 1, 30, fold=0),
            self.eastern(2026, 11, 1, 1, 0, fold=1),
        )

    def test_rejects_naive_timestamps(self):
        with self.assertRaisesRegex(ValueError, "timezone-aware"):
            api._next_scheduled_scan(datetime(2026, 8, 17, 12, 0))


class RunScanTests(unittest.TestCase):
    @patch("api._notify")
    @patch("api.finish_scan_run")
    @patch("api.record_company_scan_result")
    @patch("api.create_scan_run", return_value=42)
    @patch("api.upsert_job", return_value=True)
    @patch("api.reconcile_company_jobs", return_value=0)
    @patch("api.init_db")
    @patch("api.scrape_company")
    def test_company_failure_does_not_abort_remaining_scans(
        self,
        mock_scrape_company,
        _mock_init_db,
        mock_reconcile_company_jobs,
        mock_upsert_job,
        mock_create_scan_run,
        mock_record_company_result,
        mock_finish_scan_run,
        mock_notify,
    ):
        failed_company = {"name": "Microsoft"}
        healthy_company = {"name": "Airbnb"}
        airbnb_job = {
            "title": "Software Engineer",
            "company": "Airbnb",
            "url": "https://example.com/airbnb-job",
        }
        airbnb_jobs = ScrapeResult(
            [airbnb_job],
            total_found=10,
            not_remote=6,
            keyword_filtered=3,
        )
        mock_scrape_company.side_effect = [TimeoutError("navigation timeout"), airbnb_jobs]

        with patch.object(api, "COMPANIES", [failed_company, healthy_company]):
            result = api._run_scan()

        self.assertEqual(
            mock_scrape_company.call_args_list,
            [call(failed_company), call(healthy_company)],
        )
        mock_upsert_job.assert_called_once_with(airbnb_job)
        mock_reconcile_company_jobs.assert_called_once_with("Airbnb", airbnb_jobs)
        mock_notify.assert_called_once_with([airbnb_job])
        mock_create_scan_run.assert_called_once_with("manual", 2)
        self.assertEqual(mock_record_company_result.call_count, 2)
        failed_result = mock_record_company_result.call_args_list[0].kwargs
        self.assertEqual(failed_result["company"], "Microsoft")
        self.assertEqual(failed_result["status"], "failed")
        self.assertIn("navigation timeout", failed_result["error"])
        successful_result = mock_record_company_result.call_args_list[1].kwargs
        self.assertEqual(successful_result["company"], "Airbnb")
        self.assertEqual(successful_result["status"], "success")
        self.assertEqual(successful_result["jobs_found"], 10)
        self.assertEqual(successful_result["not_remote"], 6)
        self.assertEqual(successful_result["keyword_filtered"], 3)
        mock_finish_scan_run.assert_called_once_with(
            scan_id=42,
            status="partial",
            successful_companies=1,
            failed_companies=1,
            total_found=10,
            total_seen=1,
            not_remote=6,
            keyword_filtered=3,
            new_jobs=1,
        )
        self.assertEqual(result, {
            "scan_id": 42,
            "status": "partial",
            "new_jobs": 1,
            "total_found": 10,
            "total_seen": 1,
            "not_remote": 6,
            "keyword_filtered": 3,
            "successful_companies": 1,
            "failed_companies": 1,
        })


class LatestScanTests(unittest.TestCase):
    @patch("api.get_latest_scan", return_value={"id": 7, "status": "success"})
    @patch("api.init_db")
    def test_returns_latest_persisted_scan(self, mock_init_db, mock_get_latest_scan):
        self.assertEqual(api.latest_scan(), {"id": 7, "status": "success"})
        mock_init_db.assert_called_once_with()
        mock_get_latest_scan.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
