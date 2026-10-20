from __future__ import annotations

import os
import platform
import time
from pathlib import Path
from typing import Any

import psutil

from .common import utc_now


def discover_stellaris_pid(explicit_pid: int | None = None) -> int | None:
    if explicit_pid is not None:
        try:
            process = psutil.Process(explicit_pid)
            return explicit_pid if process.is_running() else None
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            return None
    candidates: list[tuple[float, int]] = []
    for process in psutil.process_iter(["pid", "name", "exe", "create_time"]):
        try:
            name = str(process.info.get("name") or "").lower()
            executable = Path(str(process.info.get("exe") or "")).name.lower()
            if name == "stellaris" or executable == "stellaris":
                candidates.append(
                    (float(process.info.get("create_time") or 0.0), process.pid)
                )
        except (psutil.NoSuchProcess, psutil.AccessDenied, OSError):
            continue
    return max(candidates)[1] if candidates else None


class ProcessMonitor:
    def __init__(self, pid: int | None = None) -> None:
        self.explicit_pid = pid
        self.pid: int | None = None
        self.process: psutil.Process | None = None
        self.previous_threads: dict[int, float] = {}
        self.previous_time: float | None = None

    def _attach(self) -> bool:
        pid = discover_stellaris_pid(self.explicit_pid)
        if pid is None:
            self.pid = None
            self.process = None
            return False
        if self.pid == pid and self.process is not None:
            return True
        try:
            self.process = psutil.Process(pid)
            self.process.cpu_percent(interval=None)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            self.process = None
            self.pid = None
            return False
        self.pid = pid
        self.previous_threads = {}
        self.previous_time = None
        return True

    @staticmethod
    def _thread_name(pid: int, tid: int) -> str | None:
        try:
            return (Path(f"/proc/{pid}/task/{tid}/comm")).read_text(
                encoding="utf-8", errors="replace"
            ).strip()
        except OSError:
            return None

    def snapshot(self) -> dict[str, Any]:
        observed_at = utc_now()
        if not self._attach() or self.process is None or self.pid is None:
            return {
                "available": False,
                "observed_at": observed_at,
                "pid": None,
                "reason": "no running Stellaris process was found",
            }
        try:
            process = self.process
            now = time.monotonic()
            memory = process.memory_info()
            threads = process.threads()
            elapsed = now - self.previous_time if self.previous_time is not None else None
            current_threads = {
                thread.id: thread.user_time + thread.system_time for thread in threads
            }
            thread_values: list[dict[str, Any]] = []
            for tid, cpu_time in current_threads.items():
                previous = self.previous_threads.get(tid)
                cpu_percent = (
                    100.0 * max(0.0, cpu_time - previous) / elapsed
                    if previous is not None and elapsed and elapsed > 0
                    else None
                )
                thread_values.append(
                    {
                        "tid": tid,
                        "name": self._thread_name(self.pid, tid),
                        "cpu_time_seconds": cpu_time,
                        "cpu_percent_one_core": cpu_percent,
                        "role": "main" if tid == self.pid else "worker_or_auxiliary",
                    }
                )
            thread_values.sort(
                key=lambda item: item["cpu_percent_one_core"] or -1.0, reverse=True
            )
            self.previous_threads = current_threads
            self.previous_time = now
            create_time = process.create_time()
            return {
                "available": True,
                "observed_at": observed_at,
                "pid": self.pid,
                "name": process.name(),
                "executable": process.exe(),
                "create_time_epoch": create_time,
                "uptime_seconds": max(0.0, time.time() - create_time),
                "cpu_percent": process.cpu_percent(interval=None),
                "cpu_count_logical": psutil.cpu_count(logical=True),
                "rss_bytes": memory.rss,
                "vms_bytes": memory.vms,
                "memory_percent": process.memory_percent(),
                "thread_count": len(threads),
                "threads": thread_values,
                "host": {
                    "platform": platform.platform(),
                    "system_cpu_percent": psutil.cpu_percent(interval=None),
                    "system_memory_percent": psutil.virtual_memory().percent,
                    "load_average": list(os.getloadavg()) if hasattr(os, "getloadavg") else None,
                },
            }
        except (psutil.NoSuchProcess, psutil.AccessDenied, OSError) as error:
            self.process = None
            self.pid = None
            return {
                "available": False,
                "observed_at": observed_at,
                "pid": None,
                "reason": str(error),
            }
