import unittest
from unittest.mock import Mock, patch

from scraper import (
    _is_us_workable,
    scrape_ashby,
    scrape_eightfold,
    scrape_eightfold_v2,
    scrape_greenhouse,
)


class USLocationMatchingTests(unittest.TestCase):
    def test_recognizes_explicit_us_locations(self):
        for location in (
            "Remote - United States",
            "U.S. Remote",
            "US-based",
            "Remote, USA",
        ):
            with self.subTest(location=location):
                self.assertTrue(_is_us_workable(location))

    def test_does_not_match_us_inside_other_words(self):
        for location in (
            "Australia - Office - Sydney",
            "Australia - Remote - Queensland",
            "Campus - Toronto",
        ):
            with self.subTest(location=location):
                self.assertFalse(_is_us_workable(location))


class GreenhouseRemoteFilteringTests(unittest.TestCase):
    @staticmethod
    def _response(jobs):
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = {"jobs": jobs}
        return response

    @staticmethod
    def _job(job_id, location):
        return {
            "id": job_id,
            "title": "Security Engineer",
            "location": {"name": location},
            "absolute_url": f"https://example.com/jobs/{job_id}",
            "departments": [],
            "metadata": None,
            "first_published": "2026-07-06T11:43:23-04:00",
        }

    @patch("scraper.requests.get")
    def test_rejects_tenable_sydney_office_listing(self, mock_get):
        mock_get.return_value = self._response([
            self._job(5291393008, "Australia - Office - Sydney"),
        ])

        jobs = scrape_greenhouse("tenableinc", "Tenable", "https://tenable.com/careers")

        self.assertEqual(jobs, [])

    @patch("scraper.requests.get")
    def test_rejects_remote_listing_outside_us(self, mock_get):
        mock_get.return_value = self._response([
            self._job(5188571008, "Australia - Remote - Queensland"),
        ])

        jobs = scrape_greenhouse("tenableinc", "Tenable", "https://tenable.com/careers")

        self.assertEqual(jobs, [])

    @patch("scraper.requests.get")
    def test_keeps_listing_with_us_remote_option(self, mock_get):
        mock_get.return_value = self._response([
            self._job(
                4287386009,
                "Hybrid - San Francisco, California; Remote - United States",
            ),
        ])

        jobs = scrape_greenhouse("oura", "Oura", "https://ouraring.com/careers")

        self.assertEqual(len(jobs), 1)


class EightfoldNavigationTests(unittest.TestCase):
    @patch("playwright.sync_api.sync_playwright")
    def test_navigation_does_not_wait_for_network_idle(self, mock_playwright):
        position = {
            "name": "Software Engineer",
            "locations": ["United States"],
            "positionUrl": "/careers/job/123",
            "postedTs": 1745366400,
        }
        response = Mock()
        response.url = "https://apply.careers.microsoft.com/api/pcsx/search?start=0"
        response.json.return_value = {
            "data": {"count": 1, "positions": [position]},
        }

        page = Mock()
        page.on.side_effect = lambda event, handler: setattr(page, "response_handler", handler)
        page.wait_for_event.return_value = response
        browser = Mock()
        browser.new_page.return_value = page
        playwright = Mock()
        playwright.chromium.launch.return_value = browser
        context = Mock()
        context.__enter__ = Mock(return_value=playwright)
        context.__exit__ = Mock(return_value=False)
        mock_playwright.return_value = context

        jobs = scrape_eightfold(
            "https://apply.careers.microsoft.com/careers?location=United+States",
            "Microsoft",
        )

        page.goto.assert_called_once_with(
            "https://apply.careers.microsoft.com/careers?location=United+States",
            wait_until="domcontentloaded",
            timeout=30000,
        )
        page.wait_for_event.assert_called_once()
        self.assertEqual(page.wait_for_event.call_args.args, ("response",))
        self.assertEqual(page.wait_for_event.call_args.kwargs["timeout"], 30000)
        self.assertTrue(page.wait_for_event.call_args.kwargs["predicate"](response))
        self.assertEqual(len(jobs), 1)


class AshbyRemoteFilteringTests(unittest.TestCase):
    @patch("scraper.requests.get")
    def test_explicit_non_remote_workplace_overrides_remote_flag(self, mock_get):
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = {
            "jobs": [
                {
                    "title": "Software Engineer - Backend",
                    "location": "US-CA-Menlo Park",
                    "workplaceType": "Hybrid",
                    "isRemote": True,
                    "address": {
                        "postalAddress": {"addressCountry": "United States"},
                    },
                    "jobUrl": "https://example.com/jobs/hybrid",
                },
                {
                    "title": "Platform Engineer",
                    "location": "US-CA-Menlo Park",
                    "workplaceType": "Onsite",
                    "isRemote": True,
                    "address": {
                        "postalAddress": {"addressCountry": "United States"},
                    },
                    "jobUrl": "https://example.com/jobs/onsite",
                },
            ],
        }
        mock_get.return_value = response

        jobs = scrape_ashby("example", "Example", "https://example.com/careers")

        self.assertEqual(jobs, [])

    @patch("scraper.requests.get")
    def test_keeps_explicit_remote_workplace(self, mock_get):
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = {
            "jobs": [{
                "title": "Platform Engineer",
                "location": "US-CA-Menlo Park",
                "workplaceType": "Remote",
                "isRemote": True,
                "address": {
                    "postalAddress": {"addressCountry": "United States"},
                },
                "jobUrl": "https://example.com/jobs/remote",
            }],
        }
        mock_get.return_value = response

        jobs = scrape_ashby("example", "Example", "https://example.com/careers")

        self.assertEqual(len(jobs), 1)


class EightfoldV2RemoteFilteringTests(unittest.TestCase):
    @staticmethod
    def _response(positions):
        response = Mock()
        response.status_code = 200
        response.json.return_value = {
            "count": len(positions),
            "positions": positions,
        }
        return response

    @staticmethod
    def _detail_response(position, work_type):
        response = Mock()
        response.raise_for_status.return_value = None
        detail = dict(position)
        if work_type is not None:
            detail["custom_JD"] = {
                "data_fields": {"work_type": [work_type]},
            }
        response.json.return_value = detail
        return response

    @staticmethod
    def _position(job_id, work_option=None, locations=None):
        return {
            "id": job_id,
            "name": "Machine Learning Engineer 5 - Ads Platform Engineering",
            "locations": locations or [
                "Los Gatos,California,United States of America",
            ],
            "work_location_option": work_option,
            "canonicalPositionUrl": (
                f"https://explore.jobs.netflix.net/careers/job/{job_id}"
            ),
            "t_create": 1745366400,
        }

    @patch("scraper._matches_role", return_value=True)
    @patch("scraper.requests.get")
    def test_rejects_netflix_onsite_listing(self, mock_get, _mock_matches_role):
        position = self._position(790302428788, work_option="remote_local")
        mock_get.side_effect = [
            self._response([position]),
            self._detail_response(position, "Onsite"),
        ]

        jobs = scrape_eightfold_v2(
            "https://explore.jobs.netflix.net/careers"
            "?location=Remote&domain=netflix.com",
            "Netflix",
        )

        self.assertEqual(jobs, [])

    @patch("scraper._matches_role", return_value=True)
    @patch("scraper.requests.get")
    def test_detail_work_type_overrides_stale_remote_location(
        self,
        mock_get,
        _mock_matches_role,
    ):
        position = self._position(
            790303283925,
            locations=["Washington - Remote,United States of America"],
        )
        mock_get.side_effect = [
            self._response([position]),
            self._detail_response(position, "Onsite"),
        ]

        jobs = scrape_eightfold_v2(
            "https://explore.jobs.netflix.net/careers"
            "?location=Remote&domain=netflix.com",
            "Netflix",
        )

        self.assertEqual(jobs, [])

    @patch("scraper._matches_role", return_value=True)
    @patch("scraper.requests.get")
    def test_keeps_listing_with_structured_remote_option(
        self,
        mock_get,
        _mock_matches_role,
    ):
        position = self._position(790317580317, work_option="remote_local")
        mock_get.side_effect = [
            self._response([position]),
            self._detail_response(position, "Remote"),
        ]

        jobs = scrape_eightfold_v2(
            "https://explore.jobs.netflix.net/careers"
            "?location=Remote&domain=netflix.com",
            "Netflix",
        )

        self.assertEqual(len(jobs), 1)

    @patch("scraper._matches_role", return_value=True)
    @patch("scraper.requests.get")
    def test_keeps_older_payload_with_remote_location_text(
        self,
        mock_get,
        _mock_matches_role,
    ):
        position = self._position(
            123,
            locations=["USA - Remote"],
        )
        mock_get.side_effect = [
            self._response([position]),
            self._detail_response(position, None),
        ]

        jobs = scrape_eightfold_v2(
            "https://explore.jobs.netflix.net/careers"
            "?location=Remote&domain=netflix.com",
            "Netflix",
        )

        self.assertEqual(len(jobs), 1)


if __name__ == "__main__":
    unittest.main()
