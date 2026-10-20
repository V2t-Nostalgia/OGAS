from __future__ import annotations

import os
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .capture_adapter import CaptureStatusReader
from .common import atomic_write_json, load_json, utc_now
from .mod_inventory import ModInventoryCollector
from .process_monitor import ProcessMonitor
from .profiler import ProfilerConfig, ProfilerController, diagnose_perf
from .storage import ObservationStore


@dataclass(frozen=True)
class DashboardConfig:
    output: Path
    capture_root: Path | None
    baseline_catalog: Path | None
    user_data: Path
    game_binary: Path | None
    game_pid: int | None = None
    status_interval_seconds: float = 3.0
    scale_metrics_json: Path | None = None
    nice: int = 10


class ObservationService:
    def __init__(
        self,
        config: DashboardConfig,
        profiler_config: ProfilerConfig | None = None,
        *,
        perf_availability: dict[str, Any] | None = None,
    ) -> None:
        self.config = config
        self.config.output.mkdir(parents=True, exist_ok=True)
        self.store = ObservationStore(config.output)
        self.process_monitor = ProcessMonitor(config.game_pid)
        self.capture_reader = CaptureStatusReader(
            config.capture_root, config.baseline_catalog
        )
        self.mod_collector = ModInventoryCollector(
            config.user_data,
            game_binary=config.game_binary,
            capture_root=config.capture_root,
        )
        self.lock = threading.RLock()
        self.latest_status: dict[str, Any] = {
            "observed_at": utc_now(),
            "service": {"live": False, "reason": "service is starting"},
        }
        self.latest_mods: dict[str, Any] | None = self.store.latest_mod_snapshot()
        self.mod_scan_running = False
        self.mod_thread: threading.Thread | None = None
        self.stop_event = threading.Event()
        self.status_thread: threading.Thread | None = None
        self.profiler = ProfilerController(
            self.store,
            self.current_pid,
            self.profiler_context,
            profiler_config,
            perf_availability or diagnose_perf(),
        )
        self._write_session()
        self.last_status_file_write = 0.0

    def _write_session(self) -> None:
        path = self.config.output / "session.json"
        if path.exists():
            return
        atomic_write_json(
            path,
            {
                "schema": "iag.stellaris.observe_dashboard_session.v1",
                "started_at": utc_now(),
                "output": str(self.config.output),
                "capture_root": str(self.config.capture_root)
                if self.config.capture_root
                else None,
                "baseline_catalog": str(self.config.baseline_catalog)
                if self.config.baseline_catalog
                else None,
                "game_binary": str(self.config.game_binary)
                if self.config.game_binary
                else None,
                "policy": {
                    "passive_only": True,
                    "does_not_inject": True,
                    "does_not_change_system_security_policy": True,
                    "browser_never_reads_raw_capture_logs": True,
                    "raw_perf_and_aggregates_separate": True,
                },
            },
        )

    def start(self) -> None:
        if self.status_thread is not None and self.status_thread.is_alive():
            return
        if self.config.nice > 0 and hasattr(os, "nice"):
            try:
                os.nice(self.config.nice)
            except OSError:
                pass
        self.stop_event.clear()
        self.status_thread = threading.Thread(
            target=self._status_loop, name="iag-observe-status", daemon=True
        )
        self.status_thread.start()
        self.refresh_mods()

    def stop(self) -> None:
        self.profiler.stop()
        self.stop_event.set()
        if self.status_thread is not None:
            self.status_thread.join(10)
        if self.mod_thread is not None:
            self.mod_thread.join(30)
        with self.lock:
            self.latest_status.setdefault("service", {})["live"] = False
            self.latest_status["service"]["stopped_at"] = utc_now()
            final_status = self.latest_status
        atomic_write_json(self.config.output / "status.json", final_status)
        self.store.close()

    def current_pid(self) -> int | None:
        with self.lock:
            process = self.latest_status.get("process", {})
            pid = process.get("pid") if isinstance(process, dict) else None
        if isinstance(pid, int):
            return pid
        return self.process_monitor.pid

    def profiler_context(self) -> dict[str, Any]:
        with self.lock:
            capture = self.latest_status.get("capture", {})
            mods = self.latest_mods or {}
        return {
            "game_date": capture.get("game_date")
            if isinstance(capture, dict)
            else None,
            "capture_totals": capture.get("totals", {})
            if isinstance(capture, dict)
            else {},
            "mod_inventory_fingerprint": mods.get("inventory_fingerprint_sha256"),
            "elf_build_id": mods.get("elf_build_id"),
        }

    def _scale_metrics(self) -> dict[str, Any]:
        if self.config.scale_metrics_json is None:
            return {
                "available": False,
                "reason": "no evidence-producing scale metric provider is configured",
            }
        value = load_json(self.config.scale_metrics_json, None)
        if not isinstance(value, dict) or not value.get("provenance"):
            return {
                "available": False,
                "reason": "scale metric file lacks explicit provenance",
            }
        return {"available": True, **value}

    def _status_loop(self) -> None:
        while not self.stop_event.is_set():
            started = time.monotonic()
            observed_epoch = time.time()
            process = self.process_monitor.snapshot()
            capture = self.capture_reader.snapshot()
            progress = self.store.game_progress(capture.get("game_date_ordinal"))
            profiler = self.profiler.status()
            value = {
                "schema": "iag.stellaris.observe_dashboard_status.v1",
                "observed_at": utc_now(),
                "observed_epoch": observed_epoch,
                "service": {
                    "live": True,
                    "pid": os.getpid(),
                    "status_interval_seconds": self.config.status_interval_seconds,
                    "data_age_seconds": 0.0,
                },
                "process": process,
                "capture": capture,
                "game_progress": progress,
                "profiler": profiler,
                "latest_window": self.store.list_windows(1),
                "scale_metrics": self._scale_metrics(),
                "measurement_boundaries": {
                    "function_call_counts": "unavailable",
                    "lock_wait_analysis": profiler.get("availability", {}).get(
                        "wait_analysis", {"available": False}
                    ),
                    "flame_graph": "available only for successful perf stack windows",
                },
            }
            with self.lock:
                self.latest_status = value
            self.store.record_status(value, observed_epoch)
            if observed_epoch - self.last_status_file_write >= 15.0:
                atomic_write_json(self.config.output / "status.json", value)
                self.last_status_file_write = observed_epoch
            elapsed = time.monotonic() - started
            self.stop_event.wait(
                max(0.1, self.config.status_interval_seconds - elapsed)
            )
        with self.lock:
            self.latest_status.setdefault("service", {})["live"] = False

    def status(self) -> dict[str, Any]:
        with self.lock:
            value = dict(self.latest_status)
        observed_epoch = value.get("observed_epoch")
        service = dict(value.get("service", {}))
        if isinstance(observed_epoch, (int, float)):
            service["data_age_seconds"] = max(0.0, time.time() - observed_epoch)
            service["live"] = bool(
                service.get("live")
                and service["data_age_seconds"]
                <= self.config.status_interval_seconds * 3
            )
        value["service"] = service
        return value

    def refresh_mods(self) -> dict[str, Any]:
        with self.lock:
            if self.stop_event.is_set():
                return {"accepted": False, "reason": "service is stopping"}
            if self.mod_scan_running:
                return {"accepted": False, "reason": "mod scan is already running"}
            self.mod_scan_running = True
        thread = threading.Thread(
            target=self._collect_mods, name="iag-mod-inventory", daemon=True
        )
        self.mod_thread = thread
        thread.start()
        return {"accepted": True, "state": "scanning"}

    def _collect_mods(self) -> None:
        try:
            value = self.mod_collector.collect()
            self.store.store_mod_snapshot(value)
            atomic_write_json(self.config.output / "mod_inventory.json", value)
            with self.lock:
                self.latest_mods = value
        except Exception as error:  # research service must keep status alive
            with self.lock:
                self.latest_mods = {
                    "observed_at": utc_now(),
                    "available": False,
                    "error": str(error),
                }
        finally:
            with self.lock:
                self.mod_scan_running = False

    def mods(self) -> dict[str, Any]:
        with self.lock:
            value = self.latest_mods
            scanning = self.mod_scan_running
        return {
            "scanning": scanning,
            "inventory": value,
        }

    def correlation(self) -> dict[str, Any]:
        status = self.status()
        capture = status.get("capture", {})
        mods = self.mods().get("inventory") or {}
        external_counts: dict[str, int] = {}
        for mod in mods.get("mods", []):
            for category, count in mod.get("external_definitions", {}).get(
                "counts", {}
            ).items():
                external_counts[category] = external_counts.get(category, 0) + int(
                    count
                )
        return {
            "observed_at": status.get("observed_at"),
            "mod_inventory_fingerprint": mods.get("inventory_fingerprint_sha256"),
            "elf_build_id": mods.get("elf_build_id"),
            "game_date": capture.get("game_date"),
            "command_diff": capture.get("command_diff"),
            "external_definition_counts": external_counts,
            "native_content_family_evidence": capture.get(
                "native_content_family_evidence", {}
            ),
            "causality": "not_established",
            "explanation": (
                "This joins observations by time and complete mod set. It does not "
                "attribute a command or CPU hotspot to an individual mod."
            ),
        }
