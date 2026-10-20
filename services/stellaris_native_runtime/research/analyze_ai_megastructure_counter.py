#!/usr/bin/env python3
"""Summarize exact AI megastructure counter snapshots.

The counter log contains exact function-entry counts.  This analyzer keeps
those counts separate from sampled perf evidence and treats repeated opaque
input tuples only as a cacheability *upper bound*, never as proof that a
scripted trigger is pure.
"""

from __future__ import annotations

import argparse
import gzip
import json
from collections.abc import Iterable, Iterator
from pathlib import Path
from typing import Any


SCHEMA = "iag.stellaris.ai_megastructure_counter.v1"


def _open_text(path: Path):
    if path.suffix == ".gz":
        return gzip.open(path, "rt", encoding="utf-8")
    return path.open("r", encoding="utf-8")


def read_records(paths: Iterable[Path]) -> Iterator[dict[str, Any]]:
    for path in paths:
        with _open_text(path) as handle:
            for line_number, line in enumerate(handle, 1):
                if not line.strip():
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError as error:
                    raise ValueError(f"{path}:{line_number}: invalid JSON") from error
                if record.get("schema") != SCHEMA:
                    raise ValueError(
                        f"{path}:{line_number}: unexpected schema "
                        f"{record.get('schema')!r}"
                    )
                yield record


def _counter(snapshot: dict[str, Any], name: str) -> dict[str, int]:
    value = snapshot.get("counters", {}).get(name, {})
    return {
        "total": int(value.get("total", 0)),
        "path": int(value.get("path", 0)),
        "thread_cpu_ns": int(value.get("thread_cpu_ns", 0)),
        "max_thread_cpu_ns": int(value.get("max_thread_cpu_ns", 0)),
    }


def _safe_ratio(numerator: int, denominator: int) -> float | None:
    return numerator / denominator if denominator else None


def _mean_duration(counter: dict[str, int]) -> float | None:
    return _safe_ratio(counter["thread_cpu_ns"], counter["total"])


def _load_game_dates(path: Path | None) -> list[tuple[int, str]]:
    if path is None:
        return []
    raw = json.loads(path.read_text(encoding="utf-8"))
    values = raw if isinstance(raw, list) else raw.get("samples", [])
    result: list[tuple[int, str]] = []
    for value in values:
        realtime_ns = value.get("realtime_ns")
        game_date = value.get("game_date")
        if isinstance(realtime_ns, int) and isinstance(game_date, str):
            result.append((realtime_ns, game_date))
    return sorted(result)


def _nearest_game_date(timeline: list[tuple[int, str]], realtime_ns: int) -> str | None:
    result = None
    for timestamp, game_date in timeline:
        if timestamp > realtime_ns:
            break
        result = game_date
    return result


def summarize(
    records: Iterable[dict[str, Any]],
    *,
    game_dates: list[tuple[int, str]] | None = None,
) -> dict[str, Any]:
    records = list(records)
    starts = [record for record in records if record.get("kind") == "probe_started"]
    snapshots = [record for record in records if record.get("kind") == "snapshot"]
    if not snapshots:
        raise ValueError("counter log contains no snapshots")
    if len(starts) > 1:
        raise ValueError("combine one probe instance at a time")

    snapshots.sort(key=lambda value: int(value["monotonic_ns"]))
    names = (
        "find_best_position",
        "calc_ai_weight",
        "trigger_evaluate",
        "owned_fleet_actual_evaluate",
        "owned_fleet_calculate_count",
    )
    previous = None
    intervals: list[dict[str, Any]] = []
    for snapshot in snapshots:
        if previous is not None:
            elapsed_ns = int(snapshot["monotonic_ns"]) - int(previous["monotonic_ns"])
            if elapsed_ns <= 0:
                raise ValueError("snapshot monotonic timestamps are not increasing")
            deltas: dict[str, Any] = {}
            for name in names:
                current_counter = _counter(snapshot, name)
                previous_counter = _counter(previous, name)
                total_delta = current_counter["total"] - previous_counter["total"]
                path_delta = current_counter["path"] - previous_counter["path"]
                if total_delta < 0 or path_delta < 0:
                    raise ValueError("cumulative counters moved backwards")
                seconds = elapsed_ns / 1_000_000_000
                deltas[name] = {
                    "total": total_delta,
                    "path": path_delta,
                    "total_per_second": total_delta / seconds,
                    "path_per_second": path_delta / seconds,
                }
            interval: dict[str, Any] = {
                "start_realtime_ns": int(previous.get("realtime_ns", 0)),
                "end_realtime_ns": int(snapshot.get("realtime_ns", 0)),
                "elapsed_seconds": elapsed_ns / 1_000_000_000,
                "counters": deltas,
            }
            if game_dates:
                interval["start_game_date"] = _nearest_game_date(
                    game_dates, interval["start_realtime_ns"]
                )
                interval["end_game_date"] = _nearest_game_date(
                    game_dates, interval["end_realtime_ns"]
                )
            intervals.append(interval)
        previous = snapshot

    latest = snapshots[-1]
    counters = {name: _counter(latest, name) for name in names}
    identities = list(latest.get("identities", []))
    calc_duplicates = sum(int(value.get("duplicate_calc_calls", 0)) for value in identities)
    trigger_duplicates = sum(
        int(value.get("duplicate_trigger_calls", 0)) for value in identities
    )
    owned_duplicates = sum(
        int(value.get("duplicate_owned_calls", 0)) for value in identities
    )
    key_overflow = int(latest.get("key_table_overflow", 0))

    return {
        "schema": "iag.stellaris.ai_megastructure_counter.summary.v1",
        "source_schema": SCHEMA,
        "mode": latest.get("mode"),
        "snapshot_count": len(snapshots),
        "exact_entry_counts": counters,
        "timing": {
            "unit": "thread_cpu_ns",
            "find_best_position_mean_ns": _mean_duration(
                counters["find_best_position"]
            ),
            "find_best_position_max_ns": counters["find_best_position"][
                "max_thread_cpu_ns"
            ],
            "calc_ai_weight_mean_ns": _mean_duration(counters["calc_ai_weight"]),
            "calc_ai_weight_max_ns": counters["calc_ai_weight"][
                "max_thread_cpu_ns"
            ],
            "warning": (
                "Inclusive hook duration, not self CPU. Perf samples remain a separate "
                "estimate."
            ),
        },
        "same_civilian_update_repetition": {
            "boundary": "one CAIInteriorMinister::HandleCivilianFleets invocation",
            "calc_duplicate_calls": calc_duplicates,
            "calc_duplicate_ratio": _safe_ratio(
                calc_duplicates, counters["calc_ai_weight"]["path"]
            ),
            "trigger_duplicate_calls": trigger_duplicates,
            "trigger_duplicate_ratio": _safe_ratio(
                trigger_duplicates, counters["trigger_evaluate"]["path"]
            ),
            "owned_fleet_duplicate_calls": owned_duplicates,
            "owned_fleet_duplicate_ratio": _safe_ratio(
                owned_duplicates,
                counters["owned_fleet_calculate_count"]["path"],
            ),
            "classification": "lower_bound" if key_overflow else "exact_for_opaque_tuple",
            "cacheability_warning": (
                "Equal opaque pointer tuples do not prove trigger purity, stable RNG, "
                "or unchanged mutable scope. Ratios are an upper bound on candidate "
                "cache savings, not a safe-cache claim."
            ),
        },
        "overflow": {
            "key_table": key_overflow,
            "identity_table": int(latest.get("identity_table_overflow", 0)),
            "signature_table": int(latest.get("signature_table_overflow", 0)),
        },
        "identity_distribution": identities,
        "representative_repeated_signatures": list(
            latest.get("repeated_signatures", [])
        ),
        "intervals": intervals,
        "limitations": [
            "country and input identities are process-lifetime opaque pointers",
            "fleet-list size is deliberately not dereferenced by the first probe",
            "game-date rates require a separately measured timestamp-to-date timeline",
            "full mode must pass isolated overhead validation before any long run",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("logs", nargs="+", type=Path)
    parser.add_argument("--game-date-timeline", type=Path)
    parser.add_argument("--output", type=Path)
    arguments = parser.parse_args()
    report = summarize(
        read_records(arguments.logs),
        game_dates=_load_game_dates(arguments.game_date_timeline),
    )
    encoded = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if arguments.output:
        arguments.output.write_text(encoded, encoding="utf-8")
    else:
        print(encoded, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
