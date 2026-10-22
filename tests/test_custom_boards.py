import json
import unittest
from unittest.mock import Mock, patch

import requests

from config import COMPANIES
from scraper import ScrapeError, scrape_amazon, scrape_company, scrape_google


AMAZON_URL = "https://www.amazon.jobs/en/search?country=USA&location%5B%5D=virtual-locations"
GOOGLE_URL = "https://www.google.com/about/careers/applications/jobs/results/?has_remote=true&location=United+States"


def amazon_job(job_id, locations=None, title="Security Engineer"):
    return {
        "id": str(job_id), "title": title,
        "job_path": f"/en/jobs/{job_id}/security-engineer",
        "posted_date": "October 20, 2026", "updated_time": "2 hours",
        "job_category": "Software Development",
        "locations": locations if locations is not None else [json.dumps({
            "type": "VIRTUAL", "countryIso2a": "US", "location": "US, Virtual",
        })],
    }


def amazon_response(jobs, total=None):
    response = Mock()
    response.json.return_value = {"jobs": jobs, "hits": len(jobs) if total is None else total, "error": None}
    return response


def google_job(job_id, title="Security Engineer", note=None, remote=1, locations=None):
    job = [None] * 21
    job[0] = str(job_id)
    job[1] = title
    job[9] = locations if locations is not None else [["United States", ["United States"], None, None, None, "US"]]
    job[16] = remote
    job[18] = [None, note if note is not None else "<b>Remote location: United States.</b>"]
    return job


def google_response(jobs, total=None):
    response = Mock()
    data = [jobs, None, len(jobs or []) if total is None else total, 20]
    response.text = "<script>AF_initDataCallback({key: 'ds:1', hash: '2', data:" + json.dumps(data) + ", sideChannel: {}});</script>"
    return response


class CustomBoardTests(unittest.TestCase):
    def test_configured_companies_route_to_custom_connectors(self):
        for name, ats in (("Amazon", "amazon"), ("Google", "google")):
            with self.subTest(company=name), patch(f"scraper.scrape_{ats}", return_value=[]) as scrape:
                company = next(company for company in COMPANIES if company["name"] == name)
                self.assertEqual(company["ats"], ats)
                scrape_company(company)
                scrape.assert_called_once_with(company["careers_url"], name)

    @patch("scraper.requests.get")
    def test_amazon_paginates_and_applies_existing_filters(self, get):
        get.side_effect = [
            amazon_response([amazon_job(1), amazon_job(2, title="Product Manager")], 3),
            amazon_response([amazon_job(3, locations=[{
                "type": "ONSITE", "countryIso2a": "US", "location": "US, WA, Seattle",
            }])], 3),
            amazon_response([]),
        ]
        jobs = scrape_amazon(AMAZON_URL, "Amazon")
        self.assertEqual((jobs.total_found, jobs.keyword_filtered, jobs.not_remote, len(jobs)), (3, 1, 1, 1))
        self.assertEqual(jobs[0]["url"], "https://www.amazon.jobs/en/jobs/1/security-engineer")
        self.assertEqual(jobs[0]["date_posted"], "2026-10-20")
        self.assertIsNone(jobs[0]["ats_updated_at"])
        self.assertEqual(get.call_args_list[1].kwargs["params"]["offset"], 2)
        self.assertEqual(get.call_args_list[0].kwargs["params"]["country"], "USA")
        self.assertEqual(get.call_args_list[0].kwargs["params"]["location[]"], "virtual-locations")

    @patch("scraper.requests.get")
    def test_amazon_pairs_remote_workplace_with_its_country(self, get):
        get.return_value = amazon_response([
            amazon_job(1, locations=[
                {"type": "ONSITE", "countryIso2a": "US", "location": "US, Seattle"},
                {"type": "VIRTUAL", "countryIso2a": "CA", "location": "Canada, Remote"},
            ]),
            amazon_job(2, title="Software Engineer, Distributed Systems", locations=[]),
            amazon_job(3, locations=[
                {"type": "ONSITE", "countryIso2a": "CA", "location": "Canada, Toronto"},
                {"type": "VIRTUAL", "normalizedCountryCode": "USA", "location": "US, Virtual"},
            ]),
        ])
        jobs = scrape_amazon(AMAZON_URL, "Amazon")
        self.assertEqual((len(jobs), jobs.not_remote), (1, 2))
        self.assertTrue(jobs[0]["url"].endswith("/3/security-engineer"))

    @patch("scraper.requests.get")
    def test_amazon_invalid_locations_fail_the_scan(self, get):
        get.return_value = amazon_response([amazon_job(1, locations=["invalid JSON"])])
        with self.assertRaisesRegex(ScrapeError, "location data"):
            scrape_amazon(AMAZON_URL, "Amazon")

    @patch("scraper.requests.get")
    def test_google_paginates_and_uses_only_us_remote_options(self, get):
        get.side_effect = [
            google_response([google_job(1, note="<b>In-office locations: London, UK.</b><br><b>Remote location(s): Ohio, USA; United States.</b>")], 3),
            google_response([
                google_job(2, title="Principal Security Engineer"),
                google_job(3, note="<b>In-office location: Seattle, WA, USA.</b><br><b>Remote location: Toronto, Canada.</b>"),
            ], 3),
            google_response(None, 0),
        ]
        jobs = scrape_google(GOOGLE_URL, "Google")
        self.assertEqual((jobs.total_found, jobs.keyword_filtered, jobs.not_remote, len(jobs)), (3, 1, 1, 1))
        self.assertEqual(jobs[0]["location"], "Remote - Ohio, USA; United States")
        self.assertEqual(jobs[0]["url"], "https://www.google.com/about/careers/applications/jobs/results/1")
        self.assertIsNone(jobs[0]["date_posted"])
        self.assertEqual(get.call_args_list[1].kwargs["params"]["page"], 2)
        self.assertEqual(get.call_args_list[0].kwargs["params"]["has_remote"], "true")

    @patch("scraper.requests.get")
    def test_amazon_adds_onsite_and_hybrid_pittsburgh_locations_case_insensitively(self, get):
        get.side_effect = [
            amazon_response([amazon_job(1)]),
            amazon_response([
                amazon_job(2, locations=[
                    {"type": "ONSITE", "countryIso2a": "US", "location": "US, WA, Seattle"},
                    {"type": "ONSITE", "countryIso2a": "US", "location": "US, PA, pItTsBuRgH"},
                ]),
                amazon_job(3, locations=[{
                    "type": "HYBRID", "countryIso2a": "US", "location": "PITTSBURGH, PA",
                }]),
                amazon_job(4, title="Senior Security Engineer", locations=[{
                    "type": "ONSITE", "countryIso2a": "US", "location": "Pittsburgh, PA",
                }]),
                amazon_job(5, title="Security Engineer, Pittsburgh Team", locations=[{
                    "type": "ONSITE", "countryIso2a": "US", "location": "US, WA, Seattle",
                }]),
            ]),
        ]
        jobs = scrape_amazon(AMAZON_URL, "Amazon")
        self.assertEqual([job["is_remote"] for job in jobs], [1, 0, 0])
        self.assertEqual(jobs[1]["location"], "US, PA, pItTsBuRgH")
        self.assertEqual((jobs.total_found, jobs.keyword_filtered, jobs.not_remote), (5, 1, 1))
        params = get.call_args_list[1].kwargs["params"]
        self.assertEqual(params["city"], "Pittsburgh")
        self.assertNotIn("location[]", params)

    @patch("scraper.requests.get")
    def test_google_adds_pittsburgh_secondary_locations_without_remote_eligibility(self, get):
        get.side_effect = [
            google_response([google_job(1)]),
            google_response([
                google_job(2, remote=None, note="", locations=[
                    ["Mountain View, CA, USA"], ["pItTsBuRgH, PA, USA"],
                ]),
                google_job(3, remote=None, note="", locations=[["PITTSBURGH, PA, USA"]]),
                google_job(4, title="Principal Security Engineer", remote=None, note="", locations=[["Pittsburgh, PA, USA"]]),
                google_job(5, title="Security Engineer, Pittsburgh Team", remote=None, note="", locations=[["Seattle, WA, USA"]]),
            ]),
        ]
        jobs = scrape_google(GOOGLE_URL, "Google")
        self.assertEqual([job["is_remote"] for job in jobs], [1, 0, 0])
        self.assertEqual(jobs[1]["location"], "pItTsBuRgH, PA, USA")
        self.assertEqual((jobs.total_found, jobs.keyword_filtered, jobs.not_remote), (5, 1, 1))
        params = get.call_args_list[1].kwargs["params"]
        self.assertEqual(params["location"], "Pittsburgh, PA, USA")
        self.assertNotIn("has_remote", params)

    @patch("scraper.requests.get")
    def test_overlapping_searches_deduplicate_before_counting_and_title_filtering(self, get):
        for scrape, response, job, url, name in (
            (scrape_amazon, amazon_response, amazon_job, AMAZON_URL, "Amazon"),
            (scrape_google, google_response, google_job, GOOGLE_URL, "Google"),
        ):
            with self.subTest(company=name):
                postings = [job(1), job(2, title="Product Manager")]
                get.side_effect = [response(postings), response(postings)]
                jobs = scrape(url, name)
                self.assertEqual((jobs.total_found, len(jobs), jobs.keyword_filtered), (2, 1, 1))

    @patch("scraper.requests.get")
    def test_local_search_failure_fails_the_whole_company_scan(self, get):
        for scrape, response, job, url, name in (
            (scrape_amazon, amazon_response, amazon_job, AMAZON_URL, "Amazon"),
            (scrape_google, google_response, google_job, GOOGLE_URL, "Google"),
        ):
            with self.subTest(company=name):
                get.side_effect = [response([job(1)]), requests.Timeout("local search timed out")]
                with self.assertRaisesRegex(ScrapeError, "local search timed out"):
                    scrape(url, name)

    @patch("scraper.requests.get")
    def test_each_search_paginates_independently(self, get):
        for scrape, response, job, url, name, page_key, expected in (
            (scrape_amazon, amazon_response, amazon_job, AMAZON_URL, "Amazon", "offset", [0, 1, 0, 1]),
            (scrape_google, google_response, google_job, GOOGLE_URL, "Google", "page", [1, 2, 1, 2]),
        ):
            with self.subTest(company=name):
                get.reset_mock()
                get.side_effect = [response([job(1)], 2), response([job(2)], 2),
                                   response([job(2)], 2), response([job(3)], 2)]
                jobs = scrape(url, name)
                self.assertEqual(len(jobs), 3)
                self.assertEqual([call.kwargs["params"][page_key] for call in get.call_args_list], expected)

    @patch("scraper.requests.get")
    def test_other_boards_do_not_run_pittsburgh_searches(self, get):
        greenhouse = next(company for company in COMPANIES if company["ats"] == "greenhouse")
        get.return_value = amazon_response([])
        scrape_company(greenhouse)
        get.assert_called_once()

    @patch("scraper.requests.get")
    def test_google_requires_remote_flag_and_location_note(self, get):
        get.return_value = google_response([
            google_job(1, remote=None),
            google_job(2, note="", title="Software Engineer, Distributed Systems"),
            google_job(3, note="<b>Remote locations: Texas, USA; Canada.</b>"),
        ])
        jobs = scrape_google(GOOGLE_URL, "Google")
        self.assertEqual((len(jobs), jobs.not_remote), (1, 2))
        self.assertEqual(jobs[0]["location"], "Remote - Texas, USA")

    @patch("scraper.requests.get")
    def test_confirmed_empty_results_are_successful(self, get):
        for scrape, response, url, name in (
            (scrape_amazon, amazon_response([]), AMAZON_URL, "Amazon"),
            (scrape_google, google_response(None, 0), GOOGLE_URL, "Google"),
        ):
            with self.subTest(company=name):
                get.return_value = response
                jobs = scrape(url, name)
                self.assertEqual(jobs, [])
                self.assertEqual(jobs.total_found, 0)

    @patch("scraper.requests.get")
    def test_incomplete_repeated_and_changing_pages_fail_the_scan(self, get):
        for scrape, response, job, url, name in (
            (scrape_amazon, amazon_response, amazon_job, AMAZON_URL, "Amazon"),
            (scrape_google, google_response, google_job, GOOGLE_URL, "Google"),
        ):
            for second_page, error in (
                (response([], 2), "ended before"),
                (response([job(1)], 2), "duplicate"),
                (response([job(2)], 3), "count changed"),
            ):
                with self.subTest(company=name, error=error):
                    get.side_effect = [response([job(1)], 2), second_page]
                    with self.assertRaisesRegex(ScrapeError, error):
                        scrape(url, name)

    @patch("scraper.requests.get")
    def test_later_request_failure_does_not_return_partial_jobs(self, get):
        for scrape, response, job, url, name in (
            (scrape_amazon, amazon_response, amazon_job, AMAZON_URL, "Amazon"),
            (scrape_google, google_response, google_job, GOOGLE_URL, "Google"),
        ):
            with self.subTest(company=name):
                get.side_effect = [response([job(1)], 2), requests.Timeout("timed out")]
                with self.assertRaisesRegex(ScrapeError, "timed out"):
                    scrape(url, name)

    @patch("scraper.requests.get")
    def test_unexpected_pages_and_api_errors_fail_the_scan(self, get):
        for scrape, response, url, name in (
            (scrape_amazon, Mock(), AMAZON_URL, "Amazon"),
            (scrape_google, Mock(text="<html>Challenge or redesigned page</html>"), GOOGLE_URL, "Google"),
        ):
            with self.subTest(company=name):
                get.return_value = response
                with self.assertRaises(ScrapeError):
                    scrape(url, name)
        get.return_value = amazon_response([])
        get.return_value.json.return_value["error"] = "Search unavailable"
        with self.assertRaises(ScrapeError):
            scrape_amazon(AMAZON_URL, "Amazon")

    @patch("scraper.requests.get")
    def test_amazon_search_result_cap_is_a_failure(self, get):
        get.return_value = amazon_response([amazon_job(1)], 10000)
        with self.assertRaisesRegex(ScrapeError, "search result cap"):
            scrape_amazon(AMAZON_URL, "Amazon")


if __name__ == "__main__":
    unittest.main()
