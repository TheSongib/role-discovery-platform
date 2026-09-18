#!/usr/bin/env python3
"""Copy an existing JobTracker SQLite database into the AWS DynamoDB tables."""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
from pathlib import Path


def _rows(connection: sqlite3.Connection, table: str) -> list[dict]:
    exists = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table,),
    ).fetchone()
    if not exists:
        return []
    return [dict(row) for row in connection.execute(f"SELECT * FROM {table}")]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Migrate JobTracker jobs, scan history, and keywords to DynamoDB."
    )
    parser.add_argument("--sqlite", required=True, type=Path)
    parser.add_argument("--keywords", type=Path)
    parser.add_argument("--jobs-table", required=True)
    parser.add_argument("--state-table", required=True)
    parser.add_argument("--region", default="us-east-1")
    parser.add_argument("--profile")
    parser.add_argument(
        "--confirm-account",
        required=True,
        help="AWS account ID expected to own the destination tables.",
    )
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if not args.sqlite.is_file():
        raise SystemExit(f"SQLite database not found: {args.sqlite}")

    if args.profile:
        os.environ["AWS_PROFILE"] = args.profile
    os.environ["AWS_REGION"] = args.region
    os.environ["DYNAMODB_JOBS_TABLE"] = args.jobs_table
    os.environ["DYNAMODB_STATE_TABLE"] = args.state_table

    import boto3
    import dynamodb_store

    identity = boto3.client("sts", region_name=args.region).get_caller_identity()
    if identity["Account"] != args.confirm_account:
        raise SystemExit(
            f"Refusing migration: authenticated to account {identity['Account']}, "
            f"expected {args.confirm_account}"
        )

    with sqlite3.connect(args.sqlite) as connection:
        connection.row_factory = sqlite3.Row
        jobs = _rows(connection, "jobs")
        scan_runs = _rows(connection, "scan_runs")
        company_results = _rows(connection, "company_scan_results")

    print(
        f"Source contains {len(jobs)} jobs, {len(scan_runs)} scan runs, "
        f"and {len(company_results)} company results"
    )

    # Fail before writing if the names, region, credentials, or table access
    # are wrong. A dry run therefore validates both source and destination.
    dynamodb_store.validate_tables()
    if args.dry_run:
        print("Dry run complete; DynamoDB was not modified")
        return

    imported_jobs = dynamodb_store.import_jobs(jobs)
    results_by_scan: dict[int, list[dict]] = {}
    for result in company_results:
        results_by_scan.setdefault(int(result["scan_id"]), []).append(result)
    for run in scan_runs:
        dynamodb_store.import_scan_run(
            run,
            results_by_scan.get(int(run["id"]), []),
        )

    if args.keywords and args.keywords.is_file():
        keyword_data = json.loads(args.keywords.read_text())
        dynamodb_store.save_keywords(
            keyword_data.get("title_keywords", []),
            keyword_data.get("title_exclude_keywords", []),
        )

    print(
        f"Migration complete: {imported_jobs} jobs and "
        f"{len(scan_runs)} scan runs written to account {identity['Account']}"
    )


if __name__ == "__main__":
    main()
