from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Iterator
from zoneinfo import ZoneInfo


class Database:
    def __init__(self, path: Path, timezone: str = "Asia/Seoul") -> None:
        self.path = path
        self.timezone = ZoneInfo(timezone)
        self._lock = threading.RLock()
        path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        try:
            yield connection
            connection.commit()
        finally:
            connection.close()

    def _initialize(self) -> None:
        with self.connect() as connection:
            connection.executescript(
                """
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS schedules (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    action TEXT NOT NULL CHECK(action IN ('wake', 'shutdown')),
                    time TEXT NOT NULL,
                    weekdays TEXT NOT NULL,
                    enabled INTEGER NOT NULL DEFAULT 1,
                    last_run_key TEXT,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    started_at TEXT NOT NULL,
                    finished_at TEXT,
                    source TEXT NOT NULL,
                    action TEXT NOT NULL,
                    status TEXT NOT NULL,
                    detail TEXT NOT NULL DEFAULT '',
                    duration_seconds REAL
                );
                CREATE INDEX IF NOT EXISTS history_started_at ON history(started_at DESC);
                CREATE TABLE IF NOT EXISTS metrics (
                    sampled_at INTEGER PRIMARY KEY,
                    cpu_percent REAL NOT NULL DEFAULT 0,
                    memory_used_bytes REAL NOT NULL DEFAULT 0,
                    memory_total_bytes REAL NOT NULL DEFAULT 0,
                    memory_arc_bytes REAL NOT NULL DEFAULT 0,
                    disk_read_bps REAL NOT NULL DEFAULT 0,
                    disk_write_bps REAL NOT NULL DEFAULT 0,
                    network_rx_bps REAL NOT NULL DEFAULT 0,
                    network_tx_bps REAL NOT NULL DEFAULT 0,
                    pool_used_bytes REAL NOT NULL DEFAULT 0,
                    pool_total_bytes REAL NOT NULL DEFAULT 0,
                    cpu_temp_c REAL,
                    max_temp_c REAL,
                    disk_temperatures TEXT NOT NULL DEFAULT '{}'
                );
                CREATE INDEX IF NOT EXISTS metrics_sampled_at ON metrics(sampled_at DESC);
                """
            )
            columns = {row["name"] for row in connection.execute("PRAGMA table_info(metrics)").fetchall()}
            if "memory_arc_bytes" not in columns:
                connection.execute("ALTER TABLE metrics ADD COLUMN memory_arc_bytes REAL NOT NULL DEFAULT 0")

    def record_metrics(self, activity: dict[str, Any], sampled_at: int | None = None) -> None:
        if not activity.get("available"):
            return
        timestamp = int(sampled_at or activity.get("checked_at") or datetime.now(self.timezone).timestamp())
        timestamp -= timestamp % 60
        resources = activity.get("resources") if isinstance(activity.get("resources"), dict) else {}
        memory = resources.get("memory") if isinstance(resources.get("memory"), dict) else {}
        temperatures = resources.get("temperatures") if isinstance(resources.get("temperatures"), dict) else {}
        io = activity.get("io") if isinstance(activity.get("io"), dict) else {}
        pools = activity.get("pools") if isinstance(activity.get("pools"), list) else []
        pool_used = sum(float(pool.get("allocated") or 0) for pool in pools if isinstance(pool, dict))
        pool_total = sum(float(pool.get("size") or 0) for pool in pools if isinstance(pool, dict))
        disk_temperatures = temperatures.get("disks") if isinstance(temperatures.get("disks"), dict) else {}
        values = (
            timestamp,
            float(resources.get("cpu_percent") or 0),
            float(memory.get("used_bytes") or 0),
            float(memory.get("total_bytes") or 0),
            float(memory.get("arc_bytes") or 0),
            float(io.get("disk_read_bps") or 0),
            float(io.get("disk_write_bps") or 0),
            float(io.get("network_rx_bps") or 0),
            float(io.get("network_tx_bps") or 0),
            pool_used,
            pool_total,
            temperatures.get("cpu_c"),
            temperatures.get("max_c"),
            json.dumps(disk_temperatures, ensure_ascii=False, separators=(",", ":")),
        )
        with self._lock, self.connect() as connection:
            connection.execute(
                """
                INSERT INTO metrics (
                    sampled_at, cpu_percent, memory_used_bytes, memory_total_bytes, memory_arc_bytes,
                    disk_read_bps, disk_write_bps, network_rx_bps, network_tx_bps,
                    pool_used_bytes, pool_total_bytes, cpu_temp_c, max_temp_c, disk_temperatures
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(sampled_at) DO UPDATE SET
                    cpu_percent=MAX(metrics.cpu_percent, excluded.cpu_percent),
                    memory_used_bytes=MAX(metrics.memory_used_bytes, excluded.memory_used_bytes),
                    memory_total_bytes=excluded.memory_total_bytes,
                    memory_arc_bytes=MAX(metrics.memory_arc_bytes, excluded.memory_arc_bytes),
                    disk_read_bps=MAX(metrics.disk_read_bps, excluded.disk_read_bps),
                    disk_write_bps=MAX(metrics.disk_write_bps, excluded.disk_write_bps),
                    network_rx_bps=MAX(metrics.network_rx_bps, excluded.network_rx_bps),
                    network_tx_bps=MAX(metrics.network_tx_bps, excluded.network_tx_bps),
                    pool_used_bytes=excluded.pool_used_bytes,
                    pool_total_bytes=excluded.pool_total_bytes,
                    cpu_temp_c=CASE WHEN excluded.cpu_temp_c IS NULL THEN metrics.cpu_temp_c WHEN metrics.cpu_temp_c IS NULL THEN excluded.cpu_temp_c ELSE MAX(metrics.cpu_temp_c, excluded.cpu_temp_c) END,
                    max_temp_c=CASE WHEN excluded.max_temp_c IS NULL THEN metrics.max_temp_c WHEN metrics.max_temp_c IS NULL THEN excluded.max_temp_c ELSE MAX(metrics.max_temp_c, excluded.max_temp_c) END,
                    disk_temperatures=excluded.disk_temperatures
                """,
                values,
            )
            connection.execute("DELETE FROM metrics WHERE sampled_at < ?", (timestamp - 90 * 86400,))

    def metrics_history(self, range_name: str = "24h", now: int | None = None) -> dict[str, Any]:
        ranges = {"24h": 86400, "7d": 7 * 86400, "30d": 30 * 86400, "90d": 90 * 86400}
        if range_name not in ranges:
            raise ValueError("조회 범위가 올바르지 않습니다.")
        end = int(now or datetime.now(self.timezone).timestamp())
        start = end - ranges[range_name]
        bucket = max(60, (ranges[range_name] + 359) // 360)
        bucket = ((bucket + 59) // 60) * 60
        fields = (
            "cpu_percent", "memory_used_bytes", "memory_total_bytes", "memory_arc_bytes", "disk_read_bps", "disk_write_bps",
            "network_rx_bps", "network_tx_bps", "pool_used_bytes", "pool_total_bytes", "cpu_temp_c", "max_temp_c",
        )
        averages = ", ".join(f"AVG({field}) AS {field}" for field in fields)
        with self.connect() as connection:
            rows = connection.execute(
                f"SELECT (sampled_at / ?) * ? AS sampled_at, {averages} FROM metrics WHERE sampled_at >= ? GROUP BY sampled_at / ? ORDER BY sampled_at",
                (bucket, bucket, start, bucket),
            ).fetchall()
            peak_rows = connection.execute("SELECT * FROM metrics WHERE sampled_at >= ? ORDER BY sampled_at", (start,)).fetchall()
        samples = [dict(row) for row in rows]
        peak_specs = {
            "cpu": (lambda row: float(row["cpu_percent"] or 0), "%"),
            "memory": (lambda row: 100 * float(row["memory_used_bytes"] or 0) / max(1, float(row["memory_total_bytes"] or 0)), "%"),
            "arc_memory": (lambda row: 100 * float(row["memory_arc_bytes"] or 0) / max(1, float(row["memory_total_bytes"] or 0)), "%"),
            "temperature": (lambda row: float(row["max_temp_c"] or 0), "°C"),
            "network": (lambda row: float(row["network_rx_bps"] or 0) + float(row["network_tx_bps"] or 0), "B/s"),
            "disk": (lambda row: float(row["disk_read_bps"] or 0) + float(row["disk_write_bps"] or 0), "B/s"),
        }
        peaks: dict[str, Any] = {}
        for name, (value_for, unit) in peak_specs.items():
            if peak_rows:
                row = max(peak_rows, key=value_for)
                peaks[name] = {"value": value_for(row), "unit": unit, "sampled_at": row["sampled_at"]}
        return {"range": range_name, "start": start, "end": end, "bucket_seconds": bucket, "samples": samples, "peaks": peaks}

    def list_schedules(self, now: datetime | None = None) -> list[dict[str, Any]]:
        now = now or datetime.now(self.timezone)
        with self.connect() as connection:
            rows = connection.execute("SELECT * FROM schedules ORDER BY time, id").fetchall()
        result = []
        for row in rows:
            item = dict(row)
            item["weekdays"] = json.loads(item["weekdays"])
            item["enabled"] = bool(item["enabled"])
            item["next_run"] = self.next_run(item, now).isoformat() if item["enabled"] else None
            result.append(item)
        return result

    def create_schedule(self, payload: dict[str, Any]) -> dict[str, Any]:
        item = self._validate_schedule(payload)
        now = datetime.now(self.timezone).isoformat()
        with self._lock, self.connect() as connection:
            cursor = connection.execute(
                "INSERT INTO schedules(name, action, time, weekdays, enabled, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (item["name"], item["action"], item["time"], json.dumps(item["weekdays"]), int(item["enabled"]), now),
            )
            item["id"] = cursor.lastrowid
        return item

    def update_schedule(self, schedule_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        item = self._validate_schedule(payload)
        with self._lock, self.connect() as connection:
            cursor = connection.execute(
                "UPDATE schedules SET name=?, action=?, time=?, weekdays=?, enabled=?, last_run_key=NULL WHERE id=?",
                (item["name"], item["action"], item["time"], json.dumps(item["weekdays"]), int(item["enabled"]), schedule_id),
            )
            if cursor.rowcount != 1:
                raise KeyError("예약을 찾을 수 없습니다.")
        item["id"] = schedule_id
        return item

    def delete_schedule(self, schedule_id: int) -> None:
        with self._lock, self.connect() as connection:
            cursor = connection.execute("DELETE FROM schedules WHERE id=?", (schedule_id,))
            if cursor.rowcount != 1:
                raise KeyError("예약을 찾을 수 없습니다.")

    def due_schedules(self, now: datetime | None = None) -> list[dict[str, Any]]:
        now = (now or datetime.now(self.timezone)).astimezone(self.timezone)
        run_key = now.strftime("%Y-%m-%d %H:%M")
        due = []
        with self._lock, self.connect() as connection:
            rows = connection.execute("SELECT * FROM schedules WHERE enabled=1").fetchall()
            for row in rows:
                weekdays = json.loads(row["weekdays"])
                if row["time"] == now.strftime("%H:%M") and now.weekday() in weekdays and row["last_run_key"] != run_key:
                    connection.execute("UPDATE schedules SET last_run_key=? WHERE id=?", (run_key, row["id"]))
                    item = dict(row)
                    item["weekdays"] = weekdays
                    due.append(item)
        return due

    def begin_history(self, source: str, action: str) -> int:
        with self._lock, self.connect() as connection:
            cursor = connection.execute(
                "INSERT INTO history(started_at, source, action, status) VALUES (?, ?, ?, 'running')",
                (datetime.now(self.timezone).isoformat(), source, action),
            )
            return int(cursor.lastrowid)

    def finish_history(self, history_id: int, status: str, detail: str, duration_seconds: float) -> None:
        with self._lock, self.connect() as connection:
            connection.execute(
                "UPDATE history SET finished_at=?, status=?, detail=?, duration_seconds=? WHERE id=?",
                (datetime.now(self.timezone).isoformat(), status, detail[:2000], round(duration_seconds, 2), history_id),
            )
            connection.execute(
                "DELETE FROM history WHERE id NOT IN (SELECT id FROM history ORDER BY id DESC LIMIT 1000)"
            )

    def list_history(self, limit: int = 100) -> list[dict[str, Any]]:
        limit = max(1, min(int(limit), 500))
        with self.connect() as connection:
            rows = connection.execute("SELECT * FROM history ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        return [dict(row) for row in rows]

    @staticmethod
    def _validate_schedule(payload: dict[str, Any]) -> dict[str, Any]:
        action = str(payload.get("action", ""))
        if action not in {"wake", "shutdown"}:
            raise ValueError("동작은 켜기 또는 끄기여야 합니다.")
        time_value = str(payload.get("time", ""))
        try:
            datetime.strptime(time_value, "%H:%M")
        except ValueError as error:
            raise ValueError("시간은 HH:MM 형식이어야 합니다.") from error
        weekdays = sorted({int(day) for day in payload.get("weekdays", [])})
        if not weekdays or any(day < 0 or day > 6 for day in weekdays):
            raise ValueError("실행할 요일을 하나 이상 선택하세요.")
        name = str(payload.get("name") or ("NAS 켜기" if action == "wake" else "NAS 끄기")).strip()[:80]
        return {"name": name, "action": action, "time": time_value, "weekdays": weekdays, "enabled": bool(payload.get("enabled", True))}

    def next_run(self, schedule: dict[str, Any], now: datetime) -> datetime:
        now = now.astimezone(self.timezone)
        hour, minute = (int(part) for part in schedule["time"].split(":"))
        for offset in range(8):
            candidate_date = now.date() + timedelta(days=offset)
            candidate = datetime(candidate_date.year, candidate_date.month, candidate_date.day, hour, minute, tzinfo=self.timezone)
            if candidate.weekday() in schedule["weekdays"] and candidate > now:
                return candidate
        raise ValueError("다음 실행 시각을 계산할 수 없습니다.")
