"""DynamoDB persistence used by the AWS deployment.

The application keeps SQLite as its zero-setup local backend.  This module is
loaded only when DATABASE_BACKEND=dynamodb, so local development does not need
AWS credentials or tables.
"""

from __future__ import annotations

import hashlib
import os
import time
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from functools import lru_cache
from typing import Any, Iterable, Mapping

import boto3
from boto3.dynamodb.conditions import Key
from botocore.exceptions import ClientError


MISSED_SCAN_DELETE_THRESHOLD = 3
REPOST_MIN_AGE = timedelta(days=1)
_JOB_FIELDS = (
    "title",
    "company",
    "location",
    "url",
    "is_remote",
    "department",
    "description",
    "date_posted",
    "ats_updated_at",
    "date_found",
    "last_seen",
    "source_url",
    "hidden",
    "missed_scans",
)
_INTERNAL_JOB_FIELDS = {"job_key", "feed_bucket", "feed_sort"}


def _region() -> str:
    return os.getenv("AWS_REGION") or os.getenv("AWS_DEFAULT_REGION") or "us-east-1"


def _required_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"{name} is required when DATABASE_BACKEND=dynamodb")
    return value


@lru_cache(maxsize=None)
def _dynamodb_resource(region: str):
    return boto3.resource("dynamodb", region_name=region)


def _jobs_table():
    return _dynamodb_resource(_region()).Table(_required_env("DYNAMODB_JOBS_TABLE"))


def _state_table():
    return _dynamodb_resource(_region()).Table(_required_env("DYNAMODB_STATE_TABLE"))


def reset_client_cache() -> None:
    """Clear cached boto3 resources, primarily for tests and migration tools."""
    _dynamodb_resource.cache_clear()


def validate_tables() -> None:
    """Verify both configured tables exist and are accessible."""
    _jobs_table().load()
    _state_table().load()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _ttl_epoch() -> int:
    retention_days = int(os.getenv("DYNAMODB_SCAN_RETENTION_DAYS", "90"))
    return int(time.time()) + retention_days * 86400


def _native(value: Any) -> Any:
    """Convert DynamoDB Decimal values into JSON-serializable Python numbers."""
    if isinstance(value, Decimal):
        return int(value) if value % 1 == 0 else float(value)
    if isinstance(value, list):
        return [_native(item) for item in value]
    if isinstance(value, dict):
        return {key: _native(item) for key, item in value.items()}
    return value


def _job_key(job: Mapping[str, Any]) -> str:
    identity = "\x1f".join(
        str(job.get(field, "")) for field in ("company", "title", "url")
    )
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()


def _feed_keys(date_found: str, hidden: bool, job_key: str) -> tuple[str, str]:
    bucket = date_found[:7] if len(date_found) >= 7 else "unknown"
    visibility = "HIDDEN" if hidden else "VISIBLE"
    return f"{visibility}#{bucket}", f"{date_found}#{job_key}"


def build_job_item(job: Mapping[str, Any]) -> dict[str, Any]:
    """Create the canonical DynamoDB representation of a job record."""
    key = _job_key(job)
    date_found = str(job["date_found"])
    hidden = bool(job.get("hidden", 0))
    feed_bucket, feed_sort = _feed_keys(date_found, hidden, key)
    item = {field: job.get(field) for field in _JOB_FIELDS}
    item.update(
        {
            "job_key": key,
            "id": key,
            "title": str(job["title"]),
            "company": str(job["company"]),
            "url": str(job["url"]),
            "date_found": date_found,
            "last_seen": str(job.get("last_seen") or date_found),
            "hidden": int(hidden),
            "missed_scans": int(job.get("missed_scans") or 0),
            "is_remote": int(bool(job.get("is_remote", 0))),
            "feed_bucket": feed_bucket,
            "feed_sort": feed_sort,
        }
    )
    return item


def _public_job(item: Mapping[str, Any]) -> dict[str, Any]:
    result = {
        key: _native(value)
        for key, value in item.items()
        if key not in _INTERNAL_JOB_FIELDS
    }
    result["id"] = result.get("id") or item["job_key"]
    return result


def _parse_datetime(value: str | None) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _is_qualifying_repost(existing: Mapping[str, Any], job: Mapping[str, Any]) -> bool:
    if not existing.get("hidden"):
        return False

    incoming_update = job.get("ats_updated_at")
    if not incoming_update:
        return False

    stored_update = existing.get("ats_updated_at")
    if not stored_update:
        ats_update = _parse_datetime(str(incoming_update))
        first_found = _parse_datetime(existing.get("date_found"))
        signal_changed = bool(
            ats_update and first_found and ats_update > first_found
        )
    else:
        incoming_time = _parse_datetime(str(incoming_update))
        stored_time = _parse_datetime(str(stored_update))
        if incoming_time and stored_time:
            signal_changed = incoming_time > stored_time
        else:
            signal_changed = incoming_update != stored_update

    first_found = _parse_datetime(existing.get("date_found"))
    seen_now = _parse_datetime(job.get("date_found"))
    old_enough = bool(
        first_found and seen_now and seen_now - first_found >= REPOST_MIN_AGE
    )
    return signal_changed and old_enough


def upsert_job(job: Mapping[str, Any]) -> bool:
    table = _jobs_table()
    key = _job_key(job)
    existing = table.get_item(Key={"job_key": key}, ConsistentRead=True).get("Item")

    if existing:
        if _is_qualifying_repost(existing, job):
            date_found = str(job["date_found"])
            feed_bucket, feed_sort = _feed_keys(date_found, False, key)
            table.update_item(
                Key={"job_key": key},
                UpdateExpression=(
                    "SET last_seen = :last_seen, missed_scans = :zero, "
                    "#hidden = :zero, date_found = :date_found, "
                    "date_posted = :date_posted, ats_updated_at = :ats, "
                    "feed_bucket = :feed_bucket, feed_sort = :feed_sort"
                ),
                ExpressionAttributeNames={"#hidden": "hidden"},
                ExpressionAttributeValues={
                    ":last_seen": str(job["last_seen"]),
                    ":zero": 0,
                    ":date_found": date_found,
                    ":date_posted": str(job["ats_updated_at"]),
                    ":ats": str(job["ats_updated_at"]),
                    ":feed_bucket": feed_bucket,
                    ":feed_sort": feed_sort,
                },
            )
            return True

        expression = "SET last_seen = :last_seen, missed_scans = :zero"
        values: dict[str, Any] = {
            ":last_seen": str(job["last_seen"]),
            ":zero": 0,
        }
        if job.get("ats_updated_at"):
            expression += ", ats_updated_at = :ats"
            values[":ats"] = str(job["ats_updated_at"])
        table.update_item(
            Key={"job_key": key},
            UpdateExpression=expression,
            ExpressionAttributeValues=values,
        )
        return False

    try:
        table.put_item(
            Item=build_job_item(job),
            ConditionExpression="attribute_not_exists(job_key)",
        )
        return True
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") != "ConditionalCheckFailedException":
            raise
        # Another worker inserted the deterministic key first. Re-run the
        # update path so last_seen and ATS metadata are not lost.
        return upsert_job(job)


def _query_all(table, **kwargs) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    while True:
        response = table.query(**kwargs)
        items.extend(response.get("Items", []))
        last_key = response.get("LastEvaluatedKey")
        if not last_key:
            return items
        kwargs["ExclusiveStartKey"] = last_key


def _scan_all(table, **kwargs) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    while True:
        response = table.scan(**kwargs)
        items.extend(response.get("Items", []))
        last_key = response.get("LastEvaluatedKey")
        if not last_key:
            return items
        kwargs["ExclusiveStartKey"] = last_key


def reconcile_company_jobs(company: str, seen_jobs: list[dict]) -> int:
    table = _jobs_table()
    stored_jobs = _query_all(
        table,
        IndexName="company-index",
        KeyConditionExpression=Key("company").eq(company),
        ConsistentRead=False,
    )
    seen_keys = {
        _job_key(job) for job in seen_jobs if job.get("company") == company
    }

    deleted = 0
    for stored_job in stored_jobs:
        key = stored_job["job_key"]
        if key in seen_keys:
            table.update_item(
                Key={"job_key": key},
                UpdateExpression="SET missed_scans = :zero",
                ExpressionAttributeValues={":zero": 0},
            )
            continue

        missed_scans = int(stored_job.get("missed_scans", 0)) + 1
        if missed_scans >= MISSED_SCAN_DELETE_THRESHOLD:
            table.delete_item(Key={"job_key": key})
            deleted += 1
        else:
            table.update_item(
                Key={"job_key": key},
                UpdateExpression="SET missed_scans = :missed",
                ExpressionAttributeValues={":missed": missed_scans},
            )
    return deleted


def _month_buckets(start: date, end: date) -> list[str]:
    buckets = []
    year, month = start.year, start.month
    while (year, month) <= (end.year, end.month):
        buckets.append(f"{year:04d}-{month:02d}")
        if month == 12:
            year, month = year + 1, 1
        else:
            month += 1
    return buckets


def list_jobs(show_hidden: bool = False, max_age_days: int = 3) -> list[dict]:
    table = _jobs_table()
    if max_age_days <= 0:
        items = _scan_all(table)
    else:
        today = datetime.now(timezone.utc).date()
        cutoff = today - timedelta(days=max_age_days)
        items = []
        visibilities = ["VISIBLE", "HIDDEN"] if show_hidden else ["VISIBLE"]
        for bucket in _month_buckets(cutoff, today):
            for visibility in visibilities:
                items.extend(
                    _query_all(
                        table,
                        IndexName="feed-index",
                        KeyConditionExpression=(
                            Key("feed_bucket").eq(f"{visibility}#{bucket}")
                            & Key("feed_sort").gte(cutoff.isoformat())
                        ),
                        ConsistentRead=False,
                    )
                )

    public_jobs = [
        _public_job(item)
        for item in items
        if show_hidden or not bool(item.get("hidden", 0))
    ]
    public_jobs.sort(
        key=lambda item: (item.get("date_found") or "", item.get("date_posted") or ""),
        reverse=True,
    )
    return public_jobs


def get_all_jobs(
    remote_only: bool = False,
    max_age_days: int | None = None,
) -> list[dict]:
    jobs = list_jobs(show_hidden=True, max_age_days=max_age_days or 0)
    if remote_only:
        jobs = [job for job in jobs if bool(job.get("is_remote"))]
    return jobs


def set_hidden(job_id: str, hidden: bool) -> None:
    table = _jobs_table()
    response = table.get_item(Key={"job_key": str(job_id)}, ConsistentRead=True)
    existing = response.get("Item")
    if not existing:
        return
    feed_bucket, feed_sort = _feed_keys(
        str(existing["date_found"]), hidden, str(job_id)
    )
    table.update_item(
        Key={"job_key": str(job_id)},
        UpdateExpression=(
            "SET #hidden = :hidden, feed_bucket = :bucket, feed_sort = :sort"
        ),
        ExpressionAttributeNames={"#hidden": "hidden"},
        ExpressionAttributeValues={
            ":hidden": int(hidden),
            ":bucket": feed_bucket,
            ":sort": feed_sort,
        },
    )


def job_count() -> int:
    table = _jobs_table()
    total = 0
    kwargs: dict[str, Any] = {"Select": "COUNT"}
    while True:
        response = table.scan(**kwargs)
        total += int(response.get("Count", 0))
        last_key = response.get("LastEvaluatedKey")
        if not last_key:
            return total
        kwargs["ExclusiveStartKey"] = last_key


def create_scan_run(trigger: str, total_companies: int) -> str:
    started_at = _utc_now()
    scan_id = f"{started_at}#{uuid.uuid4().hex}"
    _state_table().put_item(
        Item={
            "pk": "SCANS",
            "sk": scan_id,
            "id": scan_id,
            "trigger": trigger,
            "status": "running",
            "started_at": started_at,
            "finished_at": None,
            "total_companies": total_companies,
            "successful_companies": 0,
            "failed_companies": 0,
            "total_found": 0,
            "total_seen": 0,
            "not_remote": 0,
            "keyword_filtered": 0,
            "new_jobs": 0,
            "expires_at": _ttl_epoch(),
        }
    )
    return scan_id


def record_company_scan_result(
    scan_id: str,
    company: str,
    ats: str,
    status: str,
    jobs_found: int,
    jobs_seen: int,
    not_remote: int,
    keyword_filtered: int,
    new_jobs: int,
    error: str | None,
    started_at: str,
) -> None:
    _state_table().put_item(
        Item={
            "pk": f"SCAN#{scan_id}",
            "sk": f"COMPANY#{company.casefold()}#{company}",
            "company": company,
            "ats": ats,
            "status": status,
            "jobs_found": jobs_found,
            "jobs_seen": jobs_seen,
            "not_remote": not_remote,
            "keyword_filtered": keyword_filtered,
            "new_jobs": new_jobs,
            "error": error,
            "started_at": started_at,
            "finished_at": _utc_now(),
            "expires_at": _ttl_epoch(),
        }
    )


def finish_scan_run(
    scan_id: str,
    status: str,
    successful_companies: int,
    failed_companies: int,
    total_found: int,
    total_seen: int,
    not_remote: int,
    keyword_filtered: int,
    new_jobs: int,
) -> None:
    _state_table().update_item(
        Key={"pk": "SCANS", "sk": scan_id},
        UpdateExpression=(
            "SET #status = :status, finished_at = :finished_at, "
            "successful_companies = :successful, failed_companies = :failed, "
            "total_found = :found, total_seen = :seen, not_remote = :remote, "
            "keyword_filtered = :filtered, new_jobs = :new_jobs"
        ),
        ExpressionAttributeNames={"#status": "status"},
        ExpressionAttributeValues={
            ":status": status,
            ":finished_at": _utc_now(),
            ":successful": successful_companies,
            ":failed": failed_companies,
            ":found": total_found,
            ":seen": total_seen,
            ":remote": not_remote,
            ":filtered": keyword_filtered,
            ":new_jobs": new_jobs,
        },
    )


def get_latest_scan() -> dict | None:
    table = _state_table()
    runs = table.query(
        KeyConditionExpression=Key("pk").eq("SCANS"),
        ScanIndexForward=False,
        Limit=1,
        ConsistentRead=True,
    ).get("Items", [])
    if not runs:
        return None

    run = _native(runs[0])
    companies = [
        _native(item)
        for item in _query_all(
            table,
            KeyConditionExpression=Key("pk").eq(f"SCAN#{run['id']}"),
            ConsistentRead=True,
        )
    ]
    companies.sort(
        key=lambda company: (
            0 if company.get("status") == "failed" else 1,
            str(company.get("company", "")).casefold(),
        )
    )
    for company in companies:
        company.pop("pk", None)
        company.pop("sk", None)
        company.pop("expires_at", None)

    result = {
        key: value
        for key, value in run.items()
        if key not in {"pk", "sk", "expires_at"}
    }
    result["companies"] = companies
    if result["status"] == "running":
        result["successful_companies"] = sum(
            company["status"] == "success" for company in companies
        )
        result["failed_companies"] = sum(
            company["status"] == "failed" for company in companies
        )
        aggregate_fields = {
            "total_found": "jobs_found",
            "total_seen": "jobs_seen",
            "not_remote": "not_remote",
            "keyword_filtered": "keyword_filtered",
            "new_jobs": "new_jobs",
        }
        for result_field, company_field in aggregate_fields.items():
            result[result_field] = sum(
                int(company.get(company_field, 0)) for company in companies
            )
    return result


def get_keywords(defaults: Mapping[str, list[str]]) -> dict[str, list[str]]:
    item = _state_table().get_item(
        Key={"pk": "CONFIG", "sk": "KEYWORDS"},
        ConsistentRead=True,
    ).get("Item")
    if not item:
        return {key: list(value) for key, value in defaults.items()}
    return {
        "title_keywords": list(item.get("title_keywords", defaults["title_keywords"])),
        "title_exclude_keywords": list(
            item.get("title_exclude_keywords", defaults["title_exclude_keywords"])
        ),
    }


def save_keywords(title_keywords: list[str], title_exclude_keywords: list[str]) -> None:
    _state_table().put_item(
        Item={
            "pk": "CONFIG",
            "sk": "KEYWORDS",
            "title_keywords": title_keywords,
            "title_exclude_keywords": title_exclude_keywords,
            "updated_at": _utc_now(),
        }
    )


def acquire_scan_lock(owner: str, timeout_seconds: int = 3600) -> bool:
    now = int(time.time())
    try:
        _state_table().put_item(
            Item={
                "pk": "LOCK",
                "sk": "SCAN",
                "owner": owner,
                "expires_at": now + timeout_seconds,
            },
            ConditionExpression=(
                "attribute_not_exists(#owner) OR #expires_at < :now"
            ),
            ExpressionAttributeNames={
                "#owner": "owner",
                "#expires_at": "expires_at",
            },
            ExpressionAttributeValues={":now": now},
        )
        return True
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") == "ConditionalCheckFailedException":
            return False
        raise


def release_scan_lock(owner: str) -> None:
    try:
        _state_table().delete_item(
            Key={"pk": "LOCK", "sk": "SCAN"},
            ConditionExpression="#owner = :owner",
            ExpressionAttributeNames={"#owner": "owner"},
            ExpressionAttributeValues={":owner": owner},
        )
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") != "ConditionalCheckFailedException":
            raise


def import_jobs(records: Iterable[Mapping[str, Any]]) -> int:
    """Idempotently import SQLite job records for the migration command."""
    count = 0
    with _jobs_table().batch_writer(overwrite_by_pkeys=["job_key"]) as batch:
        for record in records:
            batch.put_item(Item=build_job_item(record))
            count += 1
    return count


def import_scan_run(
    run: Mapping[str, Any],
    company_results: Iterable[Mapping[str, Any]],
) -> str:
    started_at = str(run["started_at"])
    scan_id = f"{started_at}#legacy-{int(run['id']):012d}"
    run_item = {
        key: value
        for key, value in run.items()
        if key != "id" and value is not None
    }
    run_item.update(
        {
            "pk": "SCANS",
            "sk": scan_id,
            "id": scan_id,
            "expires_at": _ttl_epoch(),
        }
    )
    _state_table().put_item(Item=run_item)
    for result in company_results:
        item = {key: value for key, value in result.items() if value is not None}
        company = str(result["company"])
        item.update(
            {
                "pk": f"SCAN#{scan_id}",
                "sk": f"COMPANY#{company.casefold()}#{company}",
                "expires_at": _ttl_epoch(),
            }
        )
        item.pop("id", None)
        item.pop("scan_id", None)
        _state_table().put_item(Item=item)
    return scan_id
