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
from datetime import datetime, timezone

from config import COMPANIES
from db import (
    create_scan_run,
    finish_scan_run,
    get_all_jobs,
    init_db,
    record_company_scan_result,
    upsert_job,
)
from export import export_csv, export_json
from scraper import scrape_company


def cmd_scrape(export_fmt: str | None):
    init_db()
    scan_id = create_scan_run("cli", len(COMPANIES))
    total_new = 0
    total_found = 0
    total_seen = 0
    total_not_remote = 0
    total_keyword_filtered = 0
    successful_companies = 0
    failed_companies = 0

    for company in COMPANIES:
        company_started_at = datetime.now(timezone.utc).isoformat()
        new_count = 0
        try:
            jobs = scrape_company(company)
            company_found = getattr(jobs, "total_found", len(jobs))
            company_not_remote = getattr(jobs, "not_remote", 0)
            company_keyword_filtered = getattr(jobs, "keyword_filtered", 0)
            for job in jobs:
                if upsert_job(job):
                    new_count += 1
                    print(f"    + {job['title']}  |  {job['location']}")
        except Exception as exc:
            failed_companies += 1
            error = f"{type(exc).__name__}: {exc}"
            print(f"  Scan failed: {error}")
            record_company_scan_result(
                scan_id=scan_id,
                company=company["name"],
                ats=company.get("ats", "unknown"),
                status="failed",
                jobs_found=0,
                jobs_seen=0,
                not_remote=0,
                keyword_filtered=0,
                new_jobs=0,
                error=error[:2000],
                started_at=company_started_at,
            )
            continue

        skipped = len(jobs) - new_count
        print(
            f"  {company_found} found, "
            f"{company_keyword_filtered} removed by keywords, "
            f"{company_not_remote} not remote, "
            f"{len(jobs)} matching, {new_count} new, {skipped} already stored."
        )
        total_new += new_count
        total_found += company_found
        total_seen += len(jobs)
        total_not_remote += company_not_remote
        total_keyword_filtered += company_keyword_filtered
        successful_companies += 1
        record_company_scan_result(
            scan_id=scan_id,
            company=company["name"],
            ats=company.get("ats", "unknown"),
            status="success",
            jobs_found=company_found,
            jobs_seen=len(jobs),
            not_remote=company_not_remote,
            keyword_filtered=company_keyword_filtered,
            new_jobs=new_count,
            error=None,
            started_at=company_started_at,
        )

    if failed_companies == 0:
        status = "success"
    elif successful_companies == 0:
        status = "failed"
    else:
        status = "partial"

    finish_scan_run(
        scan_id=scan_id,
        status=status,
        successful_companies=successful_companies,
        failed_companies=failed_companies,
        total_found=total_found,
        total_seen=total_seen,
        not_remote=total_not_remote,
        keyword_filtered=total_keyword_filtered,
        new_jobs=total_new,
    )

    print(
        f"\nDone ({status}). {total_found} found, "
        f"{total_keyword_filtered} removed by keywords, "
        f"{total_not_remote} not remote, "
        f"{total_seen} matching, {total_new} new. "
        f"Companies: {successful_companies} succeeded, {failed_companies} failed."
    )

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
