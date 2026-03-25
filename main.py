#!/usr/bin/env python3
"""
JobTracker — scrape career pages for matching remote roles.

Usage:
  python main.py                        # scrape all companies
  python main.py --export csv           # scrape then export to CSV
  python main.py --export json          # scrape then export to JSON
  python main.py --export-only csv      # export existing DB without scraping
  python main.py --list                 # print all stored jobs to terminal
"""
import argparse

from config import COMPANIES
from db import init_db, upsert_job, get_all_jobs
from export import export_csv, export_json
from scraper import scrape_company


def cmd_scrape(export_fmt: str | None):
    init_db()
    total_new = 0

    for company in COMPANIES:
        jobs = scrape_company(company)
        new_count = 0
        for job in jobs:
            if upsert_job(job):
                new_count += 1
                print(f"    + {job['title']}  |  {job['location']}")
        skipped = len(jobs) - new_count
        print(f"  {len(jobs)} matching, {new_count} new, {skipped} already stored.")
        total_new += new_count

    print(f"\nDone. Total new jobs added: {total_new}")

    if export_fmt == "csv":
        export_csv()
    elif export_fmt == "json":
        export_json()


def cmd_export_only(fmt: str):
    init_db()
    if fmt == "csv":
        export_csv()
    else:
        export_json()


def cmd_list():
    init_db()
    jobs = get_all_jobs()
    if not jobs:
        print("No jobs stored yet. Run without --list to scrape.")
        return
    print(f"\n{'#':<4} {'Company':<15} {'Title':<50} {'Location':<25} {'Posted':<12} {'Found'}")
    print("-" * 120)
    for job in jobs:
        posted = (job['date_posted'] or '')[:10]
        print(f"{job['id']:<4} {job['company']:<15} {job['title'][:48]:<50} {(job['location'] or '')[:23]:<25} {posted:<12} {job['date_found'][:10]}")
    print(f"\nTotal: {len(jobs)} jobs")


def main():
    parser = argparse.ArgumentParser(description="Scan career pages for matching remote roles.")
    parser.add_argument("--export", choices=["csv", "json"], metavar="FORMAT",
                        help="Export results after scraping (csv or json)")
    parser.add_argument("--export-only", choices=["csv", "json"], metavar="FORMAT",
                        help="Only export existing DB data, skip scraping")
    parser.add_argument("--list", action="store_true",
                        help="Print all stored jobs to the terminal")
    args = parser.parse_args()

    if args.list:
        cmd_list()
    elif args.export_only:
        cmd_export_only(args.export_only)
    else:
        cmd_scrape(args.export)


if __name__ == "__main__":
    main()
