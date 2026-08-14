from __future__ import annotations

import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from nas_control.database import Database


class DatabaseTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.database = Database(Path(self.temporary.name) / "test.sqlite3")

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_schedule_crud_and_next_run(self) -> None:
        item = self.database.create_schedule({"name": "평일 아침", "action": "wake", "time": "07:00", "weekdays": [0, 1, 2, 3, 4], "enabled": True})
        now = datetime(2026, 8, 2, 12, 0, tzinfo=ZoneInfo("Asia/Seoul"))
        schedules = self.database.list_schedules(now)
        self.assertEqual(schedules[0]["id"], item["id"])
        self.assertEqual(schedules[0]["next_run"], "2026-08-03T07:00:00+09:00")
        self.database.delete_schedule(item["id"])
        self.assertEqual(self.database.list_schedules(now), [])

    def test_due_schedule_only_once_per_minute(self) -> None:
        self.database.create_schedule({"name": "매일", "action": "wake", "time": "07:00", "weekdays": list(range(7)), "enabled": True})
        now = datetime(2026, 8, 3, 7, 0, tzinfo=ZoneInfo("Asia/Seoul"))
        self.assertEqual(len(self.database.due_schedules(now)), 1)
        self.assertEqual(self.database.due_schedules(now), [])

    def test_rejects_invalid_schedule(self) -> None:
        with self.assertRaises(ValueError):
            self.database.create_schedule({"action": "cut-power", "time": "07:00", "weekdays": [0]})

    def test_records_metrics_by_minute_and_reports_peaks(self) -> None:
        activity = {
            "available": True,
            "checked_at": 1_800_000_001,
            "pools": [{"allocated": 400, "size": 1000}],
            "io": {"disk_read_bps": 10, "disk_write_bps": 20, "network_rx_bps": 30, "network_tx_bps": 40},
            "resources": {
                "cpu_percent": 55,
                "memory": {"used_bytes": 750, "total_bytes": 1000, "arc_bytes": 500},
                "temperatures": {"cpu_c": 48, "max_c": 52, "disks": {"sda": 52}},
            },
        }
        self.database.record_metrics(activity)
        activity["resources"]["cpu_percent"] = 10
        self.database.record_metrics(activity, sampled_at=1_800_000_020)
        activity["resources"]["cpu_percent"] = 80
        self.database.record_metrics(activity, sampled_at=1_800_000_301)
        history = self.database.metrics_history("24h", now=1_800_000_360)

        self.assertEqual(len(history["samples"]), 2)
        self.assertEqual(history["peaks"]["cpu"]["value"], 80)
        self.assertEqual(history["peaks"]["memory"]["value"], 75)
        self.assertEqual(history["peaks"]["arc_memory"]["value"], 50)
        self.assertEqual(history["peaks"]["network"]["value"], 70)


if __name__ == "__main__":
    unittest.main()
