from __future__ import annotations

import unittest

from nas_control.truenas import summarize_activity


class TrueNASActivityTests(unittest.TestCase):
    def test_summarizes_only_safe_activity_fields(self) -> None:
        result = summarize_activity(
            [{"id": 7, "method": "pool.scrub", "description": "Scrub", "state": "RUNNING", "progress": {"percent": 42}, "arguments": ["secret"]}],
            [{"name": "tank", "status": "ONLINE", "scan": {"function": "SCRUB", "state": "SCANNING", "percentage": 51.5}}],
            [{"target": "backup", "initiator_addr": "192.0.2.20", "extra": "hidden"}],
            {
                "disks": {"read_bytes": 1000, "write_bytes": 2000},
                "interfaces": {
                    "up": {"link_state": "LINK_STATE_UP", "received_bytes_rate": 3000, "sent_bytes_rate": 4000},
                    "down": {"link_state": "LINK_STATE_DOWN", "received_bytes_rate": 9000, "sent_bytes_rate": 9000},
                },
            },
        )

        self.assertEqual(result["summary"]["active_jobs"], 1)
        self.assertEqual(result["summary"]["active_scans"], 1)
        self.assertEqual(result["summary"]["iscsi_sessions"], 1)
        self.assertEqual(result["summary"]["smb_sessions"], 0)
        self.assertEqual(result["io"]["network_rx_bps"], 3000)
        self.assertEqual(result["active_scans"][0]["pool"], "tank")
        self.assertNotIn("arguments", result["jobs"][0])
        self.assertNotIn("extra", result["iscsi_sessions"][0])

    def test_summarizes_capacity_resources_and_temperatures(self) -> None:
        result = summarize_activity(
            [],
            [{"name": "tank", "status": "ONLINE", "size": 1000, "allocated": 600, "free": 400, "healthy": True}],
            [],
            {
                "cpu": {"cpu": {"usage": 25, "temp": 44}},
                "memory": {"physical_memory_total": 1000, "physical_memory_available": 250, "arc_size": 500},
                "disks": {}, "interfaces": {},
            },
            disk_temperatures={"sda": 41, "sdb": 48},
            system_info={"model": "Test CPU", "cores": 4, "loadavg": [1, 2, 3], "uptime_seconds": 90},
        )

        self.assertEqual(result["pools"][0]["allocated"], 600)
        self.assertEqual(result["resources"]["cpu_percent"], 25)
        self.assertEqual(result["resources"]["memory"]["used_bytes"], 750)
        self.assertEqual(result["resources"]["temperatures"]["max_c"], 48)

    def test_summarizes_time_machine_from_smb_locks(self) -> None:
        result = summarize_activity(
            [], [], [], {},
            [{"session_id": "42", "username": "backup-user", "remote_machine": "100.64.0.10"}],
            [{"session_id": "42", "service": "Mac-Time-Machine", "machine": "100.64.0.10", "connected_at": "2026-08-03T10:00:00+09:00"}],
            [
                {"service_path": "/mnt/tank/mac-time-machine", "filename": "macbook.sparsebundle/bands/1", "opens": {"1/1": {}}},
                {"service_path": "/mnt/tank/mac-time-machine", "filename": "macbook.sparsebundle/mapped/2", "opens": {"1/2": {}}},
                {"service_path": "/mnt/tank/shared", "filename": "project/file.txt", "opens": {"1/3": {}}},
            ],
        )

        self.assertEqual(result["summary"]["smb_sessions"], 1)
        self.assertEqual(result["summary"]["smb_open_files"], 3)
        self.assertEqual(result["summary"]["time_machine_backups"], 1)
        self.assertEqual(result["time_machine_backups"][0]["name"], "macbook")
        self.assertEqual(result["time_machine_backups"][0]["share"], "Mac-Time-Machine")
        self.assertEqual(result["time_machine_backups"][0]["open_files"], 2)
        self.assertEqual(result["time_machine_backups"][0]["usernames"], ["backup-user"])


if __name__ == "__main__":
    unittest.main()
