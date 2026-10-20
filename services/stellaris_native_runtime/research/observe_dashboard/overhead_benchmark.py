from __future__ import annotations

import argparse
import json
import statistics
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Sequence

import psutil

from .capture_adapter import CaptureStatusReader
from .common import atomic_write_json, game_date_ordinal, utc_now


def _mean(values: list[float]) -> float | None:
    return statistics.fmean(values) if values else None


def measure(
    *,
    label: str,
    game_pid: int,
    duration_seconds: float,
    capture_root: Path | None,
    dashboard_url: str | None,
    poll_seconds: float = 1.0,
    dashboard_poll_seconds: float = 3.0,
) -> dict[str, Any]:
    """Measure one explicitly configured phase without changing that phase."""
    game = psutil.Process(game_pid)
    game.cpu_percent(interval=None)
    capture = CaptureStatusReader(capture_root)
    before = capture.snapshot()
    started_at = utc_now()
    started_epoch = time.time()
    game_cpu: list[float] = []
    system_cpu: list[float] = []
    rss: list[int] = []
    thread_counts: list[int] = []
    dashboard_latency_ms: list[float] = []
    dashboard_errors: list[str] = []
    dashboard_states: list[str] = []
    dashboard_cpu: list[float] = []
    dashboard_rss: list[int] = []
    dashboard_process: psutil.Process | None = None
    last_dashboard_poll = 0.0
    last_slow_dashboard_poll = 0.0
    deadline = time.monotonic() + duration_seconds
    while time.monotonic() < deadline:
        time.sleep(min(poll_seconds, max(0.0, deadline - time.monotonic())))
        try:
            game_cpu.append(game.cpu_percent(interval=None))
            rss.append(game.memory_info().rss)
            thread_counts.append(game.num_threads())
            system_cpu.append(psutil.cpu_percent(interval=None))
        except (psutil.NoSuchProcess, psutil.AccessDenied) as error:
            raise RuntimeError(f"Stellaris process became unavailable: {error}") from error
        now = time.monotonic()
        if dashboard_url and now - last_dashboard_poll >= dashboard_poll_seconds:
            request_started = time.monotonic()
            try:
                with urllib.request.urlopen(
                    dashboard_url.rstrip("/") + "/api/status", timeout=3
                ) as response:
                    value = json.load(response)
                dashboard_latency_ms.append(
                    1000.0 * (time.monotonic() - request_started)
                )
                dashboard_states.append(str(value.get("profiler", {}).get("state")))
                service_pid = value.get("service", {}).get("pid")
                if isinstance(service_pid, int) and dashboard_process is None:
                    dashboard_process = psutil.Process(service_pid)
                    dashboard_process.cpu_percent(interval=None)
                if dashboard_process is not None:
                    dashboard_cpu.append(dashboard_process.cpu_percent(interval=None))
                    dashboard_rss.append(dashboard_process.memory_info().rss)
            except (OSError, ValueError, urllib.error.URLError) as error:
                dashboard_errors.append(str(error))
            last_dashboard_poll = now
        if dashboard_url and now - last_slow_dashboard_poll >= 15.0:
            for suffix in ("/api/windows?limit=160", "/api/history?limit=300"):
                try:
                    with urllib.request.urlopen(
                        dashboard_url.rstrip("/") + suffix, timeout=3
                    ) as response:
                        response.read()
                except (OSError, urllib.error.URLError) as error:
                    dashboard_errors.append(str(error))
            last_slow_dashboard_poll = now
    ended_epoch = time.time()
    after = capture.snapshot()
    before_ordinal = game_date_ordinal(before.get("game_date"))
    after_ordinal = game_date_ordinal(after.get("game_date"))
    game_days = (
        after_ordinal - before_ordinal
        if before_ordinal is not None and after_ordinal is not None
        else None
    )
    elapsed = ended_epoch - started_epoch
    seconds_per_game_year = (
        elapsed / (game_days / 360.0) if game_days is not None and game_days > 0 else None
    )
    before_totals = before.get("totals", {})
    after_totals = after.get("totals", {})
    return {
        "schema": "iag.stellaris.observer_overhead_phase.v1",
        "label": label,
        "started_at": started_at,
        "duration_seconds": elapsed,
        "game_pid": game_pid,
        "dashboard_url": dashboard_url,
        "samples": len(game_cpu),
        "game": {
            "cpu_percent_mean": _mean(game_cpu),
            "cpu_percent_max": max(game_cpu) if game_cpu else None,
            "rss_bytes_mean": _mean([float(value) for value in rss]),
            "thread_count_mean": _mean([float(value) for value in thread_counts]),
        },
        "host": {"cpu_percent_mean": _mean(system_cpu)},
        "progress": {
            "from_game_date": before.get("game_date"),
            "to_game_date": after.get("game_date"),
            "game_days": game_days,
            "seconds_per_game_year": seconds_per_game_year,
            "basis": "capture save-index wall-clock delta",
        },
        "capture_delta": {
            key: int(after_totals.get(key, 0) or 0)
            - int(before_totals.get(key, 0) or 0)
            for key in (
                "command_records",
                "payload_records",
                "state_records",
                "dropped",
                "writer_dropped",
            )
        },
        "dashboard": {
            "request_latency_ms_mean": _mean(dashboard_latency_ms),
            "request_errors": dashboard_errors[-20:],
            "profiler_states_observed": sorted(set(dashboard_states)),
            "process_cpu_percent_mean": _mean(dashboard_cpu),
            "rss_bytes_mean": _mean([float(value) for value in dashboard_rss]),
        },
        "interpretation": (
            "A phase measurement is observational. Compare phases at the same game "
            "speed and similar GameDate; non-simultaneous differences are not proof "
            "of causality."
        ),
    }


def compare_reports(values: list[dict[str, Any]]) -> dict[str, Any]:
    by_label = {str(value.get("label")): value for value in values}
    baseline = by_label.get("observe") or by_label.get("baseline")
    comparisons: list[dict[str, Any]] = []
    if baseline:
        base_cpu = baseline.get("game", {}).get("cpu_percent_mean")
        base_speed = baseline.get("progress", {}).get("seconds_per_game_year")
        for label, value in by_label.items():
            cpu = value.get("game", {}).get("cpu_percent_mean")
            speed = value.get("progress", {}).get("seconds_per_game_year")
            comparisons.append(
                {
                    "label": label,
                    "game_cpu_delta_percent_points": cpu - base_cpu
                    if cpu is not None and base_cpu is not None
                    else None,
                    "seconds_per_game_year_delta": speed - base_speed
                    if speed is not None and base_speed is not None
                    else None,
                    "seconds_per_game_year_delta_percent": 100.0
                    * (speed - base_speed)
                    / base_speed
                    if speed is not None and base_speed
                    else None,
                }
            )
    return {
        "schema": "iag.stellaris.observer_overhead_comparison.v1",
        "generated_at": utc_now(),
        "phases": values,
        "comparisons_to_observe": comparisons,
        "required_labels": ["observe", "observe_perf", "observe_perf_web"],
        "validity_warning": (
            "Use the same save, game speed, phase duration, and comparable GameDate. "
            "This comparison reports measured deltas but does not establish causality."
        ),
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    phase = commands.add_parser("measure")
    phase.add_argument("--label", required=True)
    phase.add_argument("--game-pid", type=int, required=True)
    phase.add_argument("--duration", type=float, default=180.0)
    phase.add_argument("--capture-root", type=Path)
    phase.add_argument("--dashboard-url")
    phase.add_argument("--dashboard-poll-seconds", type=float, default=3.0)
    phase.add_argument("--output", type=Path, required=True)
    compare = commands.add_parser("compare")
    compare.add_argument("reports", nargs="+", type=Path)
    compare.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.command == "measure":
        if args.duration <= 0:
            raise SystemExit("--duration must be positive")
        result = measure(
            label=args.label,
            game_pid=args.game_pid,
            duration_seconds=args.duration,
            capture_root=args.capture_root,
            dashboard_url=args.dashboard_url,
            dashboard_poll_seconds=args.dashboard_poll_seconds,
        )
    else:
        reports = [json.loads(path.read_text(encoding="utf-8")) for path in args.reports]
        result = compare_reports(reports)
    atomic_write_json(args.output, result)
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
