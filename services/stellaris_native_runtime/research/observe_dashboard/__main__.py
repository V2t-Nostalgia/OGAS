from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Sequence

from .mod_inventory import ModInventoryCollector
from .profiler import ProfilerConfig, diagnose_perf


def default_output() -> Path:
    suffix = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    return Path.home() / "iag-observability" / suffix


def default_user_data() -> Path:
    return Path.home() / ".local/share/Paradox Interactive/Stellaris"


def find_game_binary() -> Path | None:
    candidates = (
        Path.home() / ".steam/steam/steamapps/common/Stellaris/stellaris",
        Path.home() / ".local/share/Steam/steamapps/common/Stellaris/stellaris",
    )
    return next((path for path in candidates if path.is_file()), None)


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(
        description="Read-only Stellaris Observe performance dashboard"
    )
    commands = root.add_subparsers(dest="command", required=True)
    doctor = commands.add_parser("doctor", help="Diagnose perf without changing policy")
    doctor.add_argument("--self-test", action="store_true")
    inventory = commands.add_parser("inventory", help="Print current mod evidence")
    inventory.add_argument("--user-data", type=Path, default=default_user_data())
    inventory.add_argument("--game-binary", type=Path, default=find_game_binary())
    inventory.add_argument("--capture-root", type=Path)
    serve_parser = commands.add_parser("serve", help="Run the dashboard")
    serve_parser.add_argument("--host", default="127.0.0.1")
    serve_parser.add_argument("--port", type=int, default=8765)
    serve_parser.add_argument("--output", type=Path, default=default_output())
    serve_parser.add_argument("--capture-root", type=Path)
    serve_parser.add_argument("--baseline-catalog", type=Path)
    serve_parser.add_argument("--user-data", type=Path, default=default_user_data())
    serve_parser.add_argument("--game-binary", type=Path, default=find_game_binary())
    serve_parser.add_argument("--game-pid", type=int)
    serve_parser.add_argument("--status-interval", type=float, default=3.0)
    serve_parser.add_argument("--frequency", type=int, default=19)
    serve_parser.add_argument("--sample-window", type=float, default=5.0)
    serve_parser.add_argument("--sample-interval", type=float, default=60.0)
    serve_parser.add_argument("--nice", type=int, default=10)
    serve_parser.add_argument("--scale-metrics-json", type=Path)
    serve_parser.add_argument("--auto-start-profiler", action="store_true")
    return root


def main(argv: Sequence[str] | None = None) -> int:
    values = parser().parse_args(argv)
    if values.command == "doctor":
        print(json.dumps(diagnose_perf(values.self_test), indent=2, sort_keys=True))
        return 0
    if values.command == "inventory":
        result = ModInventoryCollector(
            values.user_data.expanduser().resolve(),
            game_binary=values.game_binary,
            capture_root=values.capture_root,
        ).collect()
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    if values.status_interval <= 0:
        raise SystemExit("--status-interval must be positive")
    from .server import serve
    from .service import DashboardConfig, ObservationService

    dashboard_config = DashboardConfig(
        output=values.output.expanduser().resolve(),
        capture_root=values.capture_root.expanduser().resolve()
        if values.capture_root
        else None,
        baseline_catalog=values.baseline_catalog.expanduser().resolve()
        if values.baseline_catalog
        else None,
        user_data=values.user_data.expanduser().resolve(),
        game_binary=values.game_binary.expanduser().resolve()
        if values.game_binary
        else None,
        game_pid=values.game_pid,
        status_interval_seconds=values.status_interval,
        scale_metrics_json=values.scale_metrics_json.expanduser().resolve()
        if values.scale_metrics_json
        else None,
        nice=values.nice,
    )
    profiler_config = ProfilerConfig(
        frequency_hz=values.frequency,
        window_seconds=values.sample_window,
        interval_seconds=values.sample_interval,
        nice=values.nice,
    )
    service = ObservationService(dashboard_config, profiler_config)
    if values.auto_start_profiler:
        service.profiler.start()
    print(f"OGAS Observe dashboard: http://{values.host}:{values.port}")
    print(f"Evidence directory: {dashboard_config.output}")
    serve(service, values.host, values.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
