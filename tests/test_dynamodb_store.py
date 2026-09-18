import os
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import boto3
from moto import mock_aws

import dynamodb_store
import keywords_store
from scripts import migrate_sqlite_to_dynamodb


def job_payload(
    *,
    company="Acme",
    date_found="2026-09-01T12:00:00+00:00",
    ats_updated_at=None,
):
    return {
        "title": "Software Engineer",
        "company": company,
        "location": "Remote - United States",
        "url": f"https://example.com/{company.lower()}/jobs/123",
        "is_remote": 1,
        "department": "Engineering",
        "description": None,
        "date_posted": "2026-08-31",
        "ats_updated_at": ats_updated_at,
        "date_found": date_found,
        "last_seen": date_found,
        "source_url": f"https://example.com/{company.lower()}/careers",
    }


class DynamoDBStoreTests(unittest.TestCase):
    def setUp(self):
        self.aws_mock = mock_aws()
        self.aws_mock.start()
        self.env = patch.dict(
            os.environ,
            {
                "AWS_REGION": "us-east-1",
                "DATABASE_BACKEND": "dynamodb",
                "DYNAMODB_JOBS_TABLE": "test-jobs",
                "DYNAMODB_STATE_TABLE": "test-state",
                "DYNAMODB_SCAN_RETENTION_DAYS": "90",
            },
        )
        self.env.start()
        dynamodb_store.reset_client_cache()
        dynamodb = boto3.resource("dynamodb", region_name="us-east-1")
        dynamodb.create_table(
            TableName="test-jobs",
            BillingMode="PAY_PER_REQUEST",
            KeySchema=[{"AttributeName": "job_key", "KeyType": "HASH"}],
            AttributeDefinitions=[
                {"AttributeName": "job_key", "AttributeType": "S"},
                {"AttributeName": "company", "AttributeType": "S"},
                {"AttributeName": "feed_bucket", "AttributeType": "S"},
                {"AttributeName": "feed_sort", "AttributeType": "S"},
            ],
            GlobalSecondaryIndexes=[
                {
                    "IndexName": "company-index",
                    "KeySchema": [
                        {"AttributeName": "company", "KeyType": "HASH"},
                        {"AttributeName": "job_key", "KeyType": "RANGE"},
                    ],
                    "Projection": {"ProjectionType": "ALL"},
                },
                {
                    "IndexName": "feed-index",
                    "KeySchema": [
                        {"AttributeName": "feed_bucket", "KeyType": "HASH"},
                        {"AttributeName": "feed_sort", "KeyType": "RANGE"},
                    ],
                    "Projection": {"ProjectionType": "ALL"},
                },
            ],
        )
        dynamodb.create_table(
            TableName="test-state",
            BillingMode="PAY_PER_REQUEST",
            KeySchema=[
                {"AttributeName": "pk", "KeyType": "HASH"},
                {"AttributeName": "sk", "KeyType": "RANGE"},
            ],
            AttributeDefinitions=[
                {"AttributeName": "pk", "AttributeType": "S"},
                {"AttributeName": "sk", "AttributeType": "S"},
            ],
        )

    def tearDown(self):
        dynamodb_store.reset_client_cache()
        self.env.stop()
        self.aws_mock.stop()

    def test_job_lifecycle_and_repost(self):
        original = job_payload(
            date_found="2026-08-01T12:00:00+00:00",
            ats_updated_at="2026-07-15T10:00:00+00:00",
        )
        self.assertTrue(dynamodb_store.upsert_job(original))
        stored = dynamodb_store.get_all_jobs()[0]
        self.assertEqual(len(stored["id"]), 64)

        dynamodb_store.set_hidden(stored["id"], True)
        refreshed = job_payload(
            date_found="2026-09-01T12:00:00+00:00",
            ats_updated_at="2026-08-31T10:00:00+00:00",
        )
        self.assertTrue(dynamodb_store.upsert_job(refreshed))
        resurfaced = dynamodb_store.get_all_jobs()[0]
        self.assertEqual(resurfaced["hidden"], 0)
        self.assertEqual(resurfaced["date_found"], refreshed["date_found"])
        self.assertEqual(resurfaced["date_posted"], refreshed["ats_updated_at"])

    def test_reconciliation_is_company_scoped(self):
        dynamodb_store.upsert_job(job_payload(company="Acme"))
        dynamodb_store.upsert_job(job_payload(company="Beta"))
        for _ in range(3):
            dynamodb_store.reconcile_company_jobs("Acme", [])

        jobs = dynamodb_store.get_all_jobs()
        self.assertEqual([job["company"] for job in jobs], ["Beta"])

    def test_scan_status_keywords_and_distributed_lock(self):
        scan_id = dynamodb_store.create_scan_run("scheduled", 1)
        dynamodb_store.record_company_scan_result(
            scan_id=scan_id,
            company="Acme",
            ats="greenhouse",
            status="success",
            jobs_found=10,
            jobs_seen=2,
            not_remote=7,
            keyword_filtered=1,
            new_jobs=2,
            error=None,
            started_at="2026-09-01T12:00:00+00:00",
        )
        running = dynamodb_store.get_latest_scan()
        self.assertEqual(running["total_seen"], 2)
        self.assertEqual(running["status"], "running")

        dynamodb_store.finish_scan_run(
            scan_id=scan_id,
            status="success",
            successful_companies=1,
            failed_companies=0,
            total_found=10,
            total_seen=2,
            not_remote=7,
            keyword_filtered=1,
            new_jobs=2,
        )
        self.assertEqual(dynamodb_store.get_latest_scan()["status"], "success")

        keywords_store.save_keywords(["platform"], ["staff"])
        self.assertEqual(
            keywords_store.get_keywords(),
            {"title_keywords": ["platform"], "title_exclude_keywords": ["staff"]},
        )

        self.assertTrue(dynamodb_store.acquire_scan_lock("first"))
        self.assertFalse(dynamodb_store.acquire_scan_lock("second"))
        dynamodb_store.release_scan_lock("first")
        self.assertTrue(dynamodb_store.acquire_scan_lock("second"))

    def test_sqlite_migration_writes_to_confirmed_account(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            database = Path(temp_dir) / "jobs.db"
            with sqlite3.connect(database) as connection:
                connection.execute(
                    """
                    CREATE TABLE jobs (
                        id INTEGER PRIMARY KEY,
                        title TEXT NOT NULL,
                        company TEXT NOT NULL,
                        location TEXT,
                        url TEXT NOT NULL,
                        is_remote INTEGER,
                        department TEXT,
                        description TEXT,
                        date_posted TEXT,
                        ats_updated_at TEXT,
                        date_found TEXT NOT NULL,
                        last_seen TEXT,
                        missed_scans INTEGER,
                        source_url TEXT,
                        hidden INTEGER
                    )
                    """
                )
                job = job_payload()
                connection.execute(
                    """
                    INSERT INTO jobs (
                        title, company, location, url, is_remote, department,
                        description, date_posted, ats_updated_at, date_found,
                        last_seen, missed_scans, source_url, hidden
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, 0)
                    """,
                    (
                        job["title"],
                        job["company"],
                        job["location"],
                        job["url"],
                        job["is_remote"],
                        job["department"],
                        job["description"],
                        job["date_posted"],
                        job["ats_updated_at"],
                        job["date_found"],
                        job["last_seen"],
                        job["source_url"],
                    ),
                )
                connection.commit()

            argv = [
                "migrate_sqlite_to_dynamodb.py",
                "--sqlite",
                str(database),
                "--jobs-table",
                "test-jobs",
                "--state-table",
                "test-state",
                "--region",
                "us-east-1",
                "--confirm-account",
                "123456789012",
            ]
            with patch.object(sys, "argv", argv):
                migrate_sqlite_to_dynamodb.main()

        self.assertEqual(dynamodb_store.job_count(), 1)


if __name__ == "__main__":
    unittest.main()
