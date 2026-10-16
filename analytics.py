"""Daily counts of roles first surfaced by completed scans."""

import json
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo


EASTERN = ZoneInfo("America/New_York")
# The first tracked day captured the inventory of roles already open when the
# tracker started. Keep its source records, but omit that bootstrap count from
# trends and summary metrics.
BASELINE_DAY = date(2026, 9, 17)
FIRST_TREND_DAY = BASELINE_DAY + timedelta(days=1)


def discovery_day(timestamp: str) -> str:
    found_at = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    if found_at.tzinfo is None:
        found_at = found_at.replace(tzinfo=EASTERN)
    return found_at.astimezone(EASTERN).date().isoformat()


def discovery_series(runs: list[dict], days: int, *, today: date | None = None) -> list[dict]:
    """Group discoveries by Eastern day and add a seven-day moving average."""
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
            if found_day < FIRST_TREND_DAY or found_day > today:
                continue
            counts[found_day] = counts.get(found_day, 0) + int(count)
            first_day = min(first_day, found_day) if first_day else found_day
        if FIRST_TREND_DAY <= scan_day <= today:
            first_day = min(first_day, scan_day) if first_day else scan_day

    start = cutoff or first_day
    if start is None or today < FIRST_TREND_DAY:
        return []
    start = max(start, FIRST_TREND_DAY)
    series = []
    history_start = first_day or FIRST_TREND_DAY
    for offset in range((today - start).days + 1):
        day = start + timedelta(days=offset)
        window_start = max(history_start, day - timedelta(days=6))
        window_days = (day - window_start).days + 1
        average = (
            round(
                sum(counts.get(day - timedelta(days=ago), 0) for ago in range(window_days))
                / window_days,
                2,
            )
            if window_days > 0 else 0
        )
        series.append({"date": day.isoformat(), "count": counts.get(day, 0), "average_7_day": average})
    return series
