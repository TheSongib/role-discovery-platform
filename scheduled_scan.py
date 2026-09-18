#!/usr/bin/env python3
"""Kubernetes CronJob entry point for the production scan schedule."""

from datetime import datetime, timezone

from api import _is_frequent_scan_window, _run_scan


def should_scan(when: datetime) -> bool:
    """Run every 15 minutes in business hours and hourly at other times."""
    return _is_frequent_scan_window(when) or when.minute < 5


def main() -> None:
    now = datetime.now(timezone.utc)
    if not should_scan(now):
        print("Outside the active quarter-hour schedule; skipping this run")
        return
    result = _run_scan("scheduled")
    print(f"Scheduled scan finished with status={result['status']}")


if __name__ == "__main__":
    main()
