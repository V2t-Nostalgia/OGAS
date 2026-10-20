from __future__ import annotations

import os
import platform
import shutil
import signal
import subprocess
import tempfile
import threading
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable

from .common import utc_now
from .perf_parser import aggregate_samples, parse_perf_script
from .storage import ObservationStore


def _read_int(path: Path) -> int | None:
    try:
        return int(path.read_text(encoding="ascii").strip())
    except (OSError, ValueError):
        return None


def _effective_capabilities() -> int:
    try:
        for line in Path("/proc/self/status").read_text(encoding="ascii").splitlines():
            if line.startswith("CapEff:"):
                return int(line.split(":", 1)[1].strip(), 16)
    except (OSError, ValueError):
        pass
    return 0


def diagnose_perf(run_self_test: bool = False) -> dict[str, Any]:
    executable = shutil.which("perf")
    result: dict[str, Any] = {
        "checked_at": utc_now(),
        "platform": platform.system(),
        "perf_path": executable,
        "available": False,
        "software_sampling": False,
        "call_stacks": False,
        "wait_analysis": {
            "available": False,
            "reason": "off-CPU/lock tracing is not enabled by this low-overhead profile",
        },
    }
    if platform.system() != "Linux":
        result["reason"] = "Linux perf is only available on Linux"
        return result
    if executable is None:
        result["reason"] = "perf executable was not found"
        return result
    try:
        version = subprocess.run(
            [executable, "--version"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        result["version"] = version.stdout.strip() or version.stderr.strip()
    except (OSError, subprocess.TimeoutExpired) as error:
        result["reason"] = str(error)
        return result
    paranoid = _read_int(Path("/proc/sys/kernel/perf_event_paranoid"))
    result["perf_event_paranoid"] = paranoid
    result["kptr_restrict"] = _read_int(Path("/proc/sys/kernel/kptr_restrict"))
    capabilities = _effective_capabilities()
    has_perfmon = bool(capabilities & (1 << 38))
    has_sys_admin = bool(capabilities & (1 << 21))
    result["has_cap_perfmon"] = has_perfmon
    result["has_cap_sys_admin"] = has_sys_admin
    if (
        os.geteuid() != 0
        and not has_perfmon
        and not has_sys_admin
        and paranoid is not None
        and paranoid >= 3
    ):
        result["reason"] = (
            f"kernel.perf_event_paranoid={paranoid} blocks unprivileged perf; "
            "the observer will not change this system policy"
        )
        return result
    if run_self_test:
        with tempfile.TemporaryDirectory() as directory:
            data = Path(directory) / "perf.data"
            command = [
                executable,
                "record",
                "--quiet",
                "--event",
                "cpu-clock:u",
                "--freq",
                "19",
                "--call-graph",
                "dwarf,8192",
                "--output",
                str(data),
                "--",
                "sleep",
                "0.1",
            ]
            try:
                probe = subprocess.run(
                    command,
                    capture_output=True,
                    text=True,
                    timeout=10,
                    check=False,
                )
            except (OSError, subprocess.TimeoutExpired) as error:
                result["reason"] = f"perf self-test failed: {error}"
                return result
            result["self_test_returncode"] = probe.returncode
            if probe.returncode != 0:
                result["reason"] = (probe.stderr or probe.stdout).strip()
                return result
    result.update(
        {
            "available": True,
            "software_sampling": True,
            "call_stacks": True,
            "event": "cpu-clock:u",
            "reason": None,
        }
    )
    return result


@dataclass(frozen=True)
class ProfilerConfig:
    frequency_hz: int = 19
    window_seconds: float = 5.0
    interval_seconds: float = 60.0
    call_graph: str = "dwarf,8192"
    nice: int = 10

    def validate(self) -> None:
        if not 1 <= self.frequency_hz <= 499:
            raise ValueError("frequency_hz must be between 1 and 499")
        if not 0.5 <= self.window_seconds <= 300:
            raise ValueError("window_seconds must be between 0.5 and 300")
        if self.interval_seconds < self.window_seconds:
            raise ValueError("interval_seconds must be at least window_seconds")
        if not 0 <= self.nice <= 19:
            raise ValueError("nice must be between 0 and 19")


class PerfCollector:
    def __init__(self, perf_path: str, config: ProfilerConfig) -> None:
        self.perf_path = perf_path
        self.config = config
        self.lock = threading.Lock()
        self.process: subprocess.Popen[str] | None = None

    def _interrupt(self) -> None:
        with self.lock:
            process = self.process
        if process is None or process.poll() is not None:
            return
        try:
            if os.name == "posix":
                os.killpg(process.pid, signal.SIGINT)
            else:
                process.send_signal(signal.CTRL_BREAK_EVENT)
        except (OSError, ProcessLookupError):
            return

    @staticmethod
    def _kill_process_group(process: subprocess.Popen[str]) -> None:
        try:
            if os.name == "posix":
                os.killpg(process.pid, signal.SIGKILL)
            else:
                process.kill()
        except (OSError, ProcessLookupError):
            return

    def collect(
        self,
        pid: int,
        raw_path: Path,
        interrupt: threading.Event,
    ) -> tuple[dict[str, Any], bool, str | None]:
        raw_path.parent.mkdir(parents=True, exist_ok=True)
        command: list[str] = []
        if self.config.nice and shutil.which("nice"):
            command.extend(["nice", "-n", str(self.config.nice)])
        command.extend(
            [
                self.perf_path,
                "record",
                "--quiet",
                "--event",
                "cpu-clock:u",
                "--freq",
                str(self.config.frequency_hz),
                "--call-graph",
                self.config.call_graph,
                "--pid",
                str(pid),
                "--output",
                str(raw_path),
                "--",
                "sleep",
                str(self.config.window_seconds),
            ]
        )
        environment = os.environ.copy()
        environment["LC_ALL"] = "C"
        started = time.monotonic()
        try:
            process = subprocess.Popen(
                command,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                text=True,
                env=environment,
                start_new_session=True,
            )
        except OSError as error:
            return {}, False, str(error)
        with self.lock:
            self.process = process
        interrupted = False
        timed_out = False
        deadline = time.monotonic() + self.config.window_seconds + 15.0
        while process.poll() is None:
            if interrupt.wait(0.1):
                interrupted = True
                self._interrupt()
                break
            if time.monotonic() >= deadline:
                interrupted = True
                timed_out = True
                self._interrupt()
                break
        try:
            _, stderr = process.communicate(timeout=10)
        except subprocess.TimeoutExpired:
            self._kill_process_group(process)
            _, stderr = process.communicate()
            interrupted = True
        with self.lock:
            self.process = None
        elapsed = max(0.001, time.monotonic() - started)
        if process.returncode not in {0, -signal.SIGINT, 130} and not interrupted:
            return {}, False, stderr.strip() or f"perf record exited {process.returncode}"
        if timed_out:
            return {}, False, "perf sampling window exceeded its bounded deadline"
        if not raw_path.is_file() or raw_path.stat().st_size == 0:
            return {}, False, "perf produced no sampling data"
        script_command = [
            self.perf_path,
            "script",
            "--input",
            str(raw_path),
            "--demangle",
            "-F",
            "comm,pid,tid,time,event,ip,sym,dso",
        ]
        try:
            script = subprocess.run(
                script_command,
                capture_output=True,
                text=True,
                env=environment,
                timeout=max(60.0, self.config.window_seconds * 6),
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            return {}, False, f"perf script failed: {error}"
        if script.returncode != 0:
            return {}, False, script.stderr.strip() or "perf script failed"
        samples = parse_perf_script(script.stdout)
        aggregate = aggregate_samples(
            samples,
            frequency_hz=self.config.frequency_hz,
            duration_seconds=elapsed,
        )
        return aggregate, not interrupted, stderr.strip() or None


class ProfilerController:
    def __init__(
        self,
        store: ObservationStore,
        pid_provider: Callable[[], int | None],
        context_provider: Callable[[], dict[str, Any]],
        config: ProfilerConfig | None = None,
        availability: dict[str, Any] | None = None,
    ) -> None:
        self.store = store
        self.pid_provider = pid_provider
        self.context_provider = context_provider
        self.config = config or ProfilerConfig()
        self.config.validate()
        self.availability = availability or diagnose_perf()
        self.state_lock = threading.RLock()
        self.state = "stopped"
        self.last_error: str | None = None
        self.current_window: str | None = None
        self.last_window: str | None = None
        self.started_at: str | None = None
        self.stop_event = threading.Event()
        self.interrupt_event = threading.Event()
        self.wake_event = threading.Event()
        self.thread: threading.Thread | None = None
        perf_path = self.availability.get("perf_path") or "perf"
        self.collector = PerfCollector(str(perf_path), self.config)

    def status(self) -> dict[str, Any]:
        with self.state_lock:
            if (
                self.state in {"running", "waiting_for_game", "paused"}
                and self.thread is not None
                and not self.thread.is_alive()
            ):
                self.state = "failed"
                self.last_error = self.last_error or "profiler worker exited unexpectedly"
            return {
                "state": self.state,
                "started_at": self.started_at,
                "current_window": self.current_window,
                "last_window": self.last_window,
                "last_error": self.last_error,
                "config": {
                    "frequency_hz": self.config.frequency_hz,
                    "window_seconds": self.config.window_seconds,
                    "interval_seconds": self.config.interval_seconds,
                    "event": "cpu-clock:u",
                    "call_graph": self.config.call_graph,
                },
                "availability": self.availability,
                "data_valid": self.state in {"running", "paused"}
                and self.last_error is None,
            }

    def start(self) -> dict[str, Any]:
        with self.state_lock:
            if not self.availability.get("available"):
                self.state = "unavailable"
                self.last_error = str(self.availability.get("reason"))
                return self.status()
            if self.state == "paused":
                return self.resume()
            if self.thread is not None and self.thread.is_alive():
                return self.status()
            if self.pid_provider() is None:
                self.state = "waiting_for_game"
            else:
                self.state = "running"
            self.last_error = None
            self.started_at = utc_now()
            self.stop_event.clear()
            self.interrupt_event.clear()
            self.wake_event.clear()
            self.thread = threading.Thread(
                target=self._run, name="iag-perf-profiler", daemon=True
            )
            self.thread.start()
            return self.status()

    def pause(self) -> dict[str, Any]:
        with self.state_lock:
            if self.state not in {"running", "waiting_for_game"}:
                return self.status()
            self.state = "paused"
            self.interrupt_event.set()
            self.wake_event.set()
            return self.status()

    def resume(self) -> dict[str, Any]:
        with self.state_lock:
            if self.state != "paused":
                return self.status()
            self.state = "running"
            self.interrupt_event.clear()
            self.wake_event.set()
            return self.status()

    def stop(self, timeout: float = 15.0) -> dict[str, Any]:
        with self.state_lock:
            if self.thread is None or not self.thread.is_alive():
                self.state = "stopped"
                return self.status()
            self.state = "stopping"
            self.stop_event.set()
            self.interrupt_event.set()
            self.wake_event.set()
            thread = self.thread
        thread.join(timeout)
        with self.state_lock:
            if thread.is_alive():
                self.last_error = "profiler worker did not stop within timeout"
            else:
                self.state = "stopped"
                self.current_window = None
            return self.status()

    def _run(self) -> None:
        while not self.stop_event.is_set():
            with self.state_lock:
                state = self.state
            if state == "paused":
                self.wake_event.wait(1.0)
                self.wake_event.clear()
                continue
            pid = self.pid_provider()
            if pid is None:
                with self.state_lock:
                    self.state = "waiting_for_game"
                self.wake_event.wait(2.0)
                self.wake_event.clear()
                continue
            with self.state_lock:
                if self.state == "waiting_for_game":
                    self.state = "running"
            self.interrupt_event.clear()
            window_id = (
                datetime.now(UTC).strftime("%Y%m%dT%H%M%S.%fZ")
                + "-"
                + uuid.uuid4().hex[:8]
            )
            raw_path = self.store.raw_root / f"{window_id}.perf.data"
            started_epoch = time.time()
            started_at = utc_now()
            with self.state_lock:
                self.current_window = window_id
            try:
                aggregate, complete, warning = self.collector.collect(
                    pid, raw_path, self.interrupt_event
                )
            except Exception as error:
                aggregate, complete, warning = {}, False, str(error)
            ended_epoch = time.time()
            ended_at = utc_now()
            if aggregate:
                context = self.context_provider()
                metadata = {
                    "id": window_id,
                    "pid": pid,
                    "started_epoch": started_epoch,
                    "ended_epoch": ended_epoch,
                    "started_at": started_at,
                    "ended_at": ended_at,
                    "complete": complete,
                    "error": warning,
                    "game_date": context.get("game_date"),
                    "context": context,
                }
                try:
                    self.store.store_perf_window(metadata, aggregate, raw_path)
                except Exception as error:
                    with self.state_lock:
                        self.last_error = f"failed to store perf window: {error}"
                        self.state = "failed"
                    self.stop_event.set()
                else:
                    with self.state_lock:
                        self.last_window = window_id
                        self.last_error = warning if not complete else None
            else:
                raw_path.unlink(missing_ok=True)
                with self.state_lock:
                    self.last_error = warning or "sampling window failed"
            with self.state_lock:
                self.current_window = None
            if self.stop_event.is_set():
                break
            delay = max(0.0, self.config.interval_seconds - (ended_epoch - started_epoch))
            self.wake_event.wait(delay)
            self.wake_event.clear()
        with self.state_lock:
            if self.state == "stopping":
                self.state = "stopped"
