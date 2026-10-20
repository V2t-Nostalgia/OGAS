from __future__ import annotations

import gzip
import json
import os
import sqlite3
import threading
from pathlib import Path
from typing import Any

from .common import utc_now
from .perf_parser import build_diff_flame_tree, build_flame_tree


SCHEMA_VERSION = 1


class ObservationStore:
    def __init__(
        self,
        root: Path,
        *,
        max_raw_bytes: int = 8 * 1024 * 1024 * 1024,
        max_raw_windows: int = 2_000,
        max_aggregate_windows: int = 50_000,
        max_status_rows: int = 250_000,
        max_window_rows: int = 100_000,
        max_mod_snapshots: int = 1_000,
    ) -> None:
        self.root = root
        self.raw_root = root / "raw"
        self.aggregate_root = root / "aggregates"
        self.raw_root.mkdir(parents=True, exist_ok=True)
        self.aggregate_root.mkdir(parents=True, exist_ok=True)
        self.max_raw_bytes = max_raw_bytes
        self.max_raw_windows = max_raw_windows
        self.max_aggregate_windows = max_aggregate_windows
        self.max_status_rows = max_status_rows
        self.max_window_rows = max_window_rows
        self.max_mod_snapshots = max_mod_snapshots
        self.lock = threading.RLock()
        self.connection = sqlite3.connect(
            root / "history.sqlite3", check_same_thread=False
        )
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA journal_mode=WAL")
        self.connection.execute("PRAGMA synchronous=NORMAL")
        self._create_schema()

    def _create_schema(self) -> None:
        with self.connection:
            self.connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS metadata (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS status_samples (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    observed_epoch REAL NOT NULL,
                    observed_at TEXT NOT NULL,
                    pid INTEGER,
                    game_date TEXT,
                    game_ordinal INTEGER,
                    process_cpu_percent REAL,
                    rss_bytes INTEGER,
                    thread_count INTEGER,
                    host_cpu_percent REAL,
                    seconds_per_game_year REAL,
                    game_days_per_real_second REAL,
                    command_records INTEGER,
                    payload_records INTEGER,
                    state_records INTEGER,
                    dropped_records INTEGER,
                    backlog_bytes INTEGER,
                    profiler_state TEXT,
                    detail_json TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS status_observed_idx
                    ON status_samples(observed_epoch);
                CREATE TABLE IF NOT EXISTS game_date_points (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    observed_epoch REAL NOT NULL,
                    game_date TEXT NOT NULL,
                    game_ordinal INTEGER NOT NULL UNIQUE
                );
                CREATE TABLE IF NOT EXISTS perf_windows (
                    id TEXT PRIMARY KEY,
                    started_epoch REAL NOT NULL,
                    ended_epoch REAL NOT NULL,
                    started_at TEXT NOT NULL,
                    ended_at TEXT NOT NULL,
                    pid INTEGER NOT NULL,
                    game_date TEXT,
                    frequency_hz INTEGER NOT NULL,
                    duration_seconds REAL NOT NULL,
                    sample_count INTEGER NOT NULL,
                    complete INTEGER NOT NULL,
                    error TEXT,
                    raw_path TEXT,
                    raw_bytes INTEGER NOT NULL DEFAULT 0,
                    raw_retained INTEGER NOT NULL DEFAULT 0,
                    aggregate_path TEXT NOT NULL,
                    aggregate_retained INTEGER NOT NULL DEFAULT 1,
                    context_json TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS perf_windows_started_idx
                    ON perf_windows(started_epoch DESC);
                CREATE TABLE IF NOT EXISTS mod_snapshots (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    observed_at TEXT NOT NULL,
                    fingerprint TEXT NOT NULL,
                    data_json TEXT NOT NULL,
                    UNIQUE(fingerprint)
                );
                """
            )
            self.connection.execute(
                "INSERT OR REPLACE INTO metadata(key, value) VALUES(?, ?)",
                ("schema_version", str(SCHEMA_VERSION)),
            )

    def close(self) -> None:
        with self.lock:
            self.connection.close()

    def record_status(self, value: dict[str, Any], observed_epoch: float) -> None:
        process = value.get("process", {})
        capture = value.get("capture", {})
        totals = capture.get("totals", {})
        backlog = capture.get("backlog", {})
        progress = value.get("game_progress", {})
        host = process.get("host", {})
        game_date = capture.get("game_date")
        game_ordinal = capture.get("game_date_ordinal")
        with self.lock, self.connection:
            self.connection.execute(
                """
                INSERT INTO status_samples(
                    observed_epoch, observed_at, pid, game_date, game_ordinal,
                    process_cpu_percent, rss_bytes, thread_count, host_cpu_percent,
                    seconds_per_game_year, game_days_per_real_second,
                    command_records, payload_records, state_records,
                    dropped_records, backlog_bytes, profiler_state, detail_json
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    observed_epoch,
                    value.get("observed_at", utc_now()),
                    process.get("pid"),
                    game_date,
                    game_ordinal,
                    process.get("cpu_percent"),
                    process.get("rss_bytes"),
                    process.get("thread_count"),
                    host.get("system_cpu_percent"),
                    progress.get("seconds_per_game_year"),
                    progress.get("game_days_per_real_second"),
                    totals.get("command_records"),
                    totals.get("payload_records"),
                    totals.get("state_records"),
                    int(totals.get("dropped", 0) or 0)
                    + int(totals.get("writer_dropped", 0) or 0),
                    int(backlog.get("ready_bytes", 0) or 0)
                    + int(backlog.get("unread_bytes", 0) or 0),
                    value.get("profiler", {}).get("state"),
                    json.dumps(value, ensure_ascii=False, sort_keys=True),
                ),
            )
            if isinstance(game_date, str) and isinstance(game_ordinal, int):
                self.connection.execute(
                    """
                    INSERT OR IGNORE INTO game_date_points(
                        observed_epoch, game_date, game_ordinal
                    ) VALUES(?,?,?)
                    """,
                    (observed_epoch, game_date, game_ordinal),
                )
            self._prune_status_locked()

    def game_progress(self, current_ordinal: int | None) -> dict[str, Any]:
        if current_ordinal is None:
            return {"available": False, "reason": "GameDate is unavailable"}
        with self.lock:
            rows = self.connection.execute(
                """
                SELECT observed_epoch, game_date, game_ordinal
                FROM game_date_points
                ORDER BY observed_epoch DESC LIMIT 20
                """
            ).fetchall()
        if len(rows) < 2:
            return {
                "available": False,
                "reason": "at least two distinct saved GameDates are required",
            }
        newest = rows[0]
        oldest = rows[-1]
        real_seconds = float(newest["observed_epoch"] - oldest["observed_epoch"])
        game_days = int(newest["game_ordinal"] - oldest["game_ordinal"])
        if real_seconds <= 0 or game_days <= 0:
            return {"available": False, "reason": "GameDate did not advance"}
        days_per_second = game_days / real_seconds
        return {
            "available": True,
            "from_game_date": oldest["game_date"],
            "to_game_date": newest["game_date"],
            "real_seconds": real_seconds,
            "game_days": game_days,
            "game_days_per_real_second": days_per_second,
            "seconds_per_game_year": 360.0 / days_per_second,
            "basis": "distinct archived-save GameDates",
        }

    def store_mod_snapshot(self, value: dict[str, Any]) -> int:
        fingerprint = str(value.get("inventory_fingerprint_sha256") or "unknown")
        with self.lock, self.connection:
            self.connection.execute(
                """
                INSERT INTO mod_snapshots(observed_at, fingerprint, data_json)
                VALUES(?,?,?)
                ON CONFLICT(fingerprint) DO UPDATE SET
                    observed_at=excluded.observed_at,
                    data_json=excluded.data_json
                """,
                (
                    value.get("observed_at", utc_now()),
                    fingerprint,
                    json.dumps(value, ensure_ascii=False, sort_keys=True),
                ),
            )
            row = self.connection.execute(
                "SELECT id FROM mod_snapshots WHERE fingerprint=?", (fingerprint,)
            ).fetchone()
            self.connection.execute(
                """
                DELETE FROM mod_snapshots WHERE id IN (
                    SELECT id FROM mod_snapshots ORDER BY observed_at DESC
                    LIMIT -1 OFFSET ?
                )
                """,
                (self.max_mod_snapshots,),
            )
        return int(row["id"])

    def latest_mod_snapshot(self) -> dict[str, Any] | None:
        with self.lock:
            row = self.connection.execute(
                "SELECT data_json FROM mod_snapshots ORDER BY observed_at DESC LIMIT 1"
            ).fetchone()
        return json.loads(row["data_json"]) if row else None

    def store_perf_window(
        self,
        metadata: dict[str, Any],
        aggregate: dict[str, Any],
        raw_path: Path | None,
    ) -> dict[str, Any]:
        window_id = str(metadata["id"])
        aggregate_path = self.aggregate_root / f"{window_id}.json.gz"
        temporary = aggregate_path.with_name(f".{aggregate_path.name}.{os.getpid()}.tmp")
        with gzip.open(temporary, "wt", encoding="utf-8", compresslevel=3) as stream:
            json.dump(aggregate, stream, ensure_ascii=False, separators=(",", ":"))
        os.replace(temporary, aggregate_path)
        raw_bytes = 0
        raw_retained = 0
        if raw_path is not None and raw_path.is_file():
            raw_bytes = raw_path.stat().st_size
            raw_retained = 1
        with self.lock, self.connection:
            self.connection.execute(
                """
                INSERT OR REPLACE INTO perf_windows(
                    id, started_epoch, ended_epoch, started_at, ended_at, pid,
                    game_date, frequency_hz, duration_seconds, sample_count,
                    complete, error, raw_path, raw_bytes, raw_retained,
                    aggregate_path, aggregate_retained, context_json
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    window_id,
                    metadata["started_epoch"],
                    metadata["ended_epoch"],
                    metadata["started_at"],
                    metadata["ended_at"],
                    metadata["pid"],
                    metadata.get("game_date"),
                    aggregate["frequency_hz"],
                    aggregate["duration_seconds"],
                    aggregate["sample_count"],
                    1 if metadata.get("complete", True) else 0,
                    metadata.get("error"),
                    str(raw_path) if raw_path else None,
                    raw_bytes,
                    raw_retained,
                    str(aggregate_path),
                    1,
                    json.dumps(metadata.get("context", {}), sort_keys=True),
                ),
            )
            self._prune_windows_locked()
        return self.get_window(window_id) or {}

    @staticmethod
    def _window_row(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": row["id"],
            "started_epoch": row["started_epoch"],
            "ended_epoch": row["ended_epoch"],
            "started_at": row["started_at"],
            "ended_at": row["ended_at"],
            "pid": row["pid"],
            "game_date": row["game_date"],
            "frequency_hz": row["frequency_hz"],
            "duration_seconds": row["duration_seconds"],
            "sample_count": row["sample_count"],
            "complete": bool(row["complete"]),
            "error": row["error"],
            "raw_retained": bool(row["raw_retained"]),
            "raw_bytes": row["raw_bytes"],
            "aggregate_retained": bool(row["aggregate_retained"]),
            "context": json.loads(row["context_json"] or "{}"),
        }

    def get_window(self, window_id: str) -> dict[str, Any] | None:
        with self.lock:
            row = self.connection.execute(
                "SELECT * FROM perf_windows WHERE id=?", (window_id,)
            ).fetchone()
        return self._window_row(row) if row else None

    def list_windows(self, limit: int = 100) -> list[dict[str, Any]]:
        limit = max(1, min(limit, 1_000))
        with self.lock:
            rows = self.connection.execute(
                "SELECT * FROM perf_windows ORDER BY started_epoch DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [self._window_row(row) for row in rows]

    def load_aggregate(self, window_id: str) -> dict[str, Any]:
        with self.lock:
            row = self.connection.execute(
                "SELECT aggregate_path, aggregate_retained FROM perf_windows WHERE id=?",
                (window_id,),
            ).fetchone()
        if row is None or not row["aggregate_retained"]:
            raise KeyError(f"Aggregate is not retained for window {window_id}")
        with gzip.open(row["aggregate_path"], "rt", encoding="utf-8") as stream:
            return json.load(stream)

    def hotspots(
        self, window_id: str, thread: str = "all", sort: str = "self"
    ) -> list[dict[str, Any]]:
        aggregate = self.load_aggregate(window_id)
        view = aggregate.get("views", {}).get(thread)
        if view is None:
            raise KeyError(f"Unknown sampled thread: {thread}")
        key = "inclusive_samples" if sort == "inclusive" else "self_samples"
        return sorted(
            view.get("hotspots", []),
            key=lambda value: (-int(value.get(key, 0)), value.get("symbol", "")),
        )

    def flame(self, window_id: str, thread: str = "all") -> dict[str, Any]:
        return build_flame_tree(self.load_aggregate(window_id), thread)

    def compare(
        self, baseline_id: str, comparison_id: str, thread: str = "all"
    ) -> dict[str, Any]:
        baseline = self.load_aggregate(baseline_id)
        comparison = self.load_aggregate(comparison_id)
        return build_diff_flame_tree(baseline, comparison, thread)

    def history(self, limit: int = 2_000) -> list[dict[str, Any]]:
        limit = max(1, min(limit, 10_000))
        with self.lock:
            rows = self.connection.execute(
                """
                SELECT observed_epoch, observed_at, pid, game_date,
                       process_cpu_percent, rss_bytes, thread_count,
                       host_cpu_percent, seconds_per_game_year,
                       game_days_per_real_second, command_records,
                       dropped_records, backlog_bytes, profiler_state
                FROM status_samples ORDER BY observed_epoch DESC LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [dict(row) for row in reversed(rows)]

    def hotspot_history(
        self, *, window_limit: int = 60, top: int = 6, thread: str = "all"
    ) -> dict[str, Any]:
        windows = list(reversed(self.list_windows(max(1, min(window_limit, 240)))))
        aggregates: list[tuple[dict[str, Any], dict[str, Any]]] = []
        for window in windows:
            if not window.get("aggregate_retained"):
                continue
            try:
                aggregate = self.load_aggregate(window["id"])
            except (KeyError, OSError):
                continue
            if thread in aggregate.get("views", {}):
                aggregates.append((window, aggregate))
        if not aggregates:
            return {"thread": thread, "series": [], "points": []}
        score: dict[str, int] = {}
        frame_metadata: dict[str, dict[str, str]] = {}
        for _, aggregate in aggregates[-10:]:
            frame_metadata.update(aggregate.get("frames", {}))
            for item in aggregate["views"][thread].get("hotspots", []):
                identifier = item["frame_id"]
                score[identifier] = score.get(identifier, 0) + int(
                    item.get("inclusive_samples", 0)
                )
        selected = [
            identifier
            for identifier, _ in sorted(score.items(), key=lambda item: -item[1])[:top]
        ]
        points: list[dict[str, Any]] = []
        for window, aggregate in aggregates:
            by_id = {
                item["frame_id"]: item
                for item in aggregate["views"][thread].get("hotspots", [])
            }
            points.append(
                {
                    "window_id": window["id"],
                    "started_epoch": window["started_epoch"],
                    "game_date": window.get("game_date"),
                    "values": {
                        identifier: {
                            "self_percent": by_id.get(identifier, {}).get(
                                "self_percent", 0.0
                            ),
                            "inclusive_percent": by_id.get(identifier, {}).get(
                                "inclusive_percent", 0.0
                            ),
                            "self_cpu_seconds_estimate": by_id.get(identifier, {}).get(
                                "self_cpu_seconds_estimate", 0.0
                            ),
                            "inclusive_cpu_seconds_estimate": by_id.get(
                                identifier, {}
                            ).get("inclusive_cpu_seconds_estimate", 0.0),
                        }
                        for identifier in selected
                    },
                }
            )
        return {
            "thread": thread,
            "series": [
                {
                    "frame_id": identifier,
                    **frame_metadata.get(
                        identifier, {"symbol": "[unknown]", "module": "[unknown]"}
                    ),
                }
                for identifier in selected
            ],
            "points": points,
            "metric_note": "CPU seconds are estimates from software sampling frequency",
        }

    def _prune_status_locked(self) -> None:
        self.connection.execute(
            """
            DELETE FROM status_samples WHERE id IN (
                SELECT id FROM status_samples ORDER BY id DESC LIMIT -1 OFFSET ?
            )
            """,
            (self.max_status_rows,),
        )

    def _prune_windows_locked(self) -> None:
        raw_rows = self.connection.execute(
            """
            SELECT id, raw_path, raw_bytes FROM perf_windows
            WHERE raw_retained=1 ORDER BY started_epoch DESC
            """
        ).fetchall()
        total = 0
        for index, row in enumerate(raw_rows):
            total += int(row["raw_bytes"] or 0)
            if index < self.max_raw_windows and total <= self.max_raw_bytes:
                continue
            path = Path(row["raw_path"]) if row["raw_path"] else None
            if path is not None:
                path.unlink(missing_ok=True)
            self.connection.execute(
                "UPDATE perf_windows SET raw_retained=0 WHERE id=?", (row["id"],)
            )
        aggregate_rows = self.connection.execute(
            """
            SELECT id, aggregate_path FROM perf_windows
            WHERE aggregate_retained=1 ORDER BY started_epoch DESC
            LIMIT -1 OFFSET ?
            """,
            (self.max_aggregate_windows,),
        ).fetchall()
        for row in aggregate_rows:
            Path(row["aggregate_path"]).unlink(missing_ok=True)
            self.connection.execute(
                "UPDATE perf_windows SET aggregate_retained=0 WHERE id=?",
                (row["id"],),
            )
        self.connection.execute(
            """
            DELETE FROM perf_windows WHERE id IN (
                SELECT id FROM perf_windows ORDER BY started_epoch DESC
                LIMIT -1 OFFSET ?
            )
            """,
            (self.max_window_rows,),
        )
