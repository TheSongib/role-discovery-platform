import unittest
from unittest.mock import patch

from config import COMPANIES
from scraper import scrape_company


NEW_COMPANIES = {
    "DoorDash": ("greenhouse", "doordashusa"),
    "OpenAI": ("ashby", "openai"),
    "Tailscale": ("greenhouse", "tailscale"),
    "MongoDB": ("greenhouse", "mongodb"),
    "Chime": ("greenhouse", "chime"),
    "Discord": ("greenhouse", "discord"),
    "Samsara": ("greenhouse", "samsara"),
    "Temporal": ("greenhouse", "temporaltechnologies"),
    "Mercury": ("greenhouse", "mercury"),
}


class NewCompanyConfigTests(unittest.TestCase):
    def test_all_candidates_have_the_expected_ats_configuration(self):
        companies_by_name = {company["name"]: company for company in COMPANIES}

        for name, (ats, board_id) in NEW_COMPANIES.items():
            with self.subTest(company=name):
                company = companies_by_name[name]
                self.assertEqual(company["ats"], ats)
                self.assertEqual(company["board_id"], board_id)
                self.assertTrue(company["careers_url"].startswith("https://"))

    def test_company_names_are_unique(self):
        names = [company["name"] for company in COMPANIES]

        self.assertEqual(len(names), len(set(names)))

    @patch("scraper.scrape_ashby", return_value=[])
    @patch("scraper.scrape_greenhouse", return_value=[])
    def test_candidates_route_to_their_configured_scraper(
        self,
        mock_greenhouse,
        mock_ashby,
    ):
        companies_by_name = {company["name"]: company for company in COMPANIES}

        for name, (ats, board_id) in NEW_COMPANIES.items():
            with self.subTest(company=name):
                company = companies_by_name[name]
                scrape_company(company)
                expected_call = (board_id, name, company["careers_url"])
                if ats == "ashby":
                    self.assertEqual(mock_ashby.call_args.args, expected_call)
                else:
                    self.assertEqual(mock_greenhouse.call_args.args, expected_call)
                    self.assertFalse(mock_greenhouse.call_args.kwargs["us_only"])


if __name__ == "__main__":
    unittest.main()
