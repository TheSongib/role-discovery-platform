import unittest
from datetime import datetime, timezone

from scheduled_scan import should_scan


class ScheduledScanEntrypointTests(unittest.TestCase):
    def test_runs_each_quarter_hour_during_weekday_business_hours(self):
        # 14:30 UTC is 10:30 AM EDT on this date.
        self.assertTrue(
            should_scan(datetime(2026, 9, 16, 14, 30, tzinfo=timezone.utc))
        )

    def test_runs_only_hourly_outside_business_hours(self):
        self.assertTrue(
            should_scan(datetime(2026, 9, 20, 14, 0, tzinfo=timezone.utc))
        )
        self.assertFalse(
            should_scan(datetime(2026, 9, 20, 14, 15, tzinfo=timezone.utc))
        )


if __name__ == "__main__":
    unittest.main()
