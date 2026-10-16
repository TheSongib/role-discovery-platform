"""Daily counts of roles first surfaced by completed scans."""

import json
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo


EASTERN = ZoneInfo("America/New_York")
# The first tracked day captured the inventory of roles already open when the
# tracker started. Keep its source records, but omit that bootstrap count from
# trends and summary metrics.
BASELINE_DAY = date(2026, 9, 17)


def discovery_day(timestamp: str) -> str:
    found_at = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    if found_at.tzinfo is None:
        found_at = found_at.replace(tzinfo=EASTERN)
    return found_at.astimezone(EASTERN).date().isoformat()


def discovery_series(runs: list[dict], days: int, *, today: date | None = None) -> list[dict]:
    """Group scan insert counts by Eastern calendar day, including empty days."""
    today = today or datetime.now(EASTERN).date()
    cutoff = today - timedelta(days=days - 1) if days else None
    counts: dict[date, int] = {}
    first_day = None

    for run in runs:
        try:
            scan_day = date.fromisoformat(discovery_day(run["started_at"]))
        except (KeyError, AttributeError, ValueError):
            continue
        daily_counts = run.get("daily_counts")
        if isinstance(daily_counts, str):
            daily_counts = json.loads(daily_counts)
        if not isinstance(daily_counts, dict):
            daily_counts = {scan_day.isoformat(): run.get("new_jobs") or 0}
        for day_text, count in daily_counts.items():
            found_day = date.fromisoformat(day_text)
            if found_day == BASELINE_DAY or found_day > today or (cutoff and found_day < cutoff):
                continue
            counts[found_day] = counts.get(found_day, 0) + int(count)
            first_day = min(first_day, found_day) if first_day else found_day
        if scan_day != BASELINE_DAY and scan_day <= today and (cutoff is None or scan_day >= cutoff):
            first_day = min(first_day, scan_day) if first_day else scan_day

    start = cutoff or first_day
    if start is None:
        return []
    series = []
    for offset in range((today - start).days + 1):
        day = start + timedelta(days=offset)
        series.append(
            {"date": day.isoformat(), "count": None, "excluded": True}
            if day == BASELINE_DAY
            else {"date": day.isoformat(), "count": counts.get(day, 0)}
        )
    return series
