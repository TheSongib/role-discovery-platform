import unittest
from unittest.mock import call, patch

import api


class RunScanTests(unittest.TestCase):
    @patch("api._notify")
    @patch("api.upsert_job", return_value=True)
    @patch("api.init_db")
    @patch("api.scrape_company")
    def test_company_failure_does_not_abort_remaining_scans(
        self,
        mock_scrape_company,
        _mock_init_db,
        mock_upsert_job,
        mock_notify,
    ):
        failed_company = {"name": "Microsoft"}
        healthy_company = {"name": "Airbnb"}
        airbnb_job = {
            "title": "Software Engineer",
            "company": "Airbnb",
            "url": "https://example.com/airbnb-job",
        }
        mock_scrape_company.side_effect = [TimeoutError("navigation timeout"), [airbnb_job]]

        with patch.object(api, "COMPANIES", [failed_company, healthy_company]):
            result = api._run_scan()

        self.assertEqual(
            mock_scrape_company.call_args_list,
            [call(failed_company), call(healthy_company)],
        )
        mock_upsert_job.assert_called_once_with(airbnb_job)
        mock_notify.assert_called_once_with([airbnb_job])
        self.assertEqual(result, {"new_jobs": 1, "total_seen": 1})


if __name__ == "__main__":
    unittest.main()
