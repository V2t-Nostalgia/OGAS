#!/usr/bin/env python3
"""Batch SDK construction/IsValid research in one already-loaded runtime.

Never loads a save, injects a library, submits a command or enables an action.
Each request consumes at most one native validator call on an existing Idle.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import time
import uuid
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "src"))

from iag.stellaris.execution.native_runtime import NativeRuntimeClient


def write_new_json(path: Path, data: object) -> None:
    with path.open("x", encoding="utf-8") as stream:
        json.dump(data, stream, ensure_ascii=True, indent=2)
        stream.write("\n")


def run_batch(
    client: NativeRuntimeClient,
    output: Path,
    *,
    candidates: int = 16,
    country_id: int | None = None,
    interval: float = 0.05,
    batch_size: int = 16,
    max_seconds: float = 900.0,
    command_names: tuple[str, ...] | None = None,
    candidate_source: str = "legacy_bounded",
    require_fixed_date: bool = False,
    exhaust_candidates: bool = False,
    expected_catalog=None,
    expected_world: int | None = None,
    expected_date: int | None = None,
) -> dict:
    if (
        not 1 <= candidates <= 16
        or not 1 <= batch_size <= 64
        or not math.isfinite(interval)
        or interval < 0
        or not math.isfinite(max_seconds)
        or max_seconds <= 0
        or candidate_source not in {"legacy_bounded", "native_domain"}
        or command_names == ()
        or (command_names is not None and len(command_names) != len(set(command_names)))
    ):
        raise ValueError("Invalid bounded batch configuration.")
    output.mkdir(parents=True, exist_ok=False)
    run_id = f"sdk-batch-{uuid.uuid4().hex}"
    started = time.monotonic()
    catalog = client.describe_recovered_commands(request_id=f"{run_id}-catalog")
    write_new_json(output / "catalog.json", catalog.model_dump(mode="json"))
    selected = (
        command_names
        if command_names is not None
        else (
            catalog.native_candidate_commands
            if candidate_source == "native_domain"
            else catalog.commands
        )
    )
    entries = [
        {
            "index": index,
            "command_name": name,
            "status": "not_tested",
            "reason": "batch_not_reached",
            "attempts": [],
        }
        for index, name in enumerate(selected)
    ]
    aborted = None
    end_catalog = None
    world_identity = expected_world
    pending_entry = None
    pending_request_id = None
    fixed_date = expected_date

    def check_session(suffix: str):
        observed = client.describe_recovered_commands(request_id=f"{run_id}-{suffix}")
        if observed != catalog:
            raise RuntimeError(
                "Runtime process, instance, build or SDK catalog changed."
            )
        return observed

    with (output / "progress.jsonl").open("x", encoding="utf-8") as journal:

        def record(value: dict) -> None:
            journal.write(json.dumps(value, ensure_ascii=True) + "\n")
            journal.flush()

        try:
            if expected_catalog is not None and catalog != expected_catalog:
                raise RuntimeError(
                    "Runtime identity changed before the batch; no native requests sent."
                )
            if catalog.probe_revision < 2:
                raise ValueError(
                    "Expanded batch requires research probe revision 2; no native requests sent."
                )
            if not selected or not set(selected).issubset(catalog.commands):
                raise ValueError(
                    "Selected command list is empty or absent from this SDK."
                )
            if candidate_source == "native_domain" and (
                catalog.probe_revision < 5
                or not set(selected).issubset(catalog.native_candidate_commands)
            ):
                raise ValueError(
                    "Exact-build native domain providers require probe revision 5 with native pause-state checks; no fallback."
                )
            for index, entry in enumerate(entries):
                if time.monotonic() - started >= max_seconds:
                    aborted = "batch_wall_clock_budget_exhausted"
                    break
                if index and index % batch_size == 0:
                    check_session(f"health-{index}")
                for candidate in range(candidates):
                    if time.monotonic() - started >= max_seconds:
                        aborted = "batch_wall_clock_budget_exhausted"
                        break
                    request_id = f"{run_id}-{index}-{candidate}"
                    pending_entry = entry
                    pending_request_id = request_id
                    record(
                        {
                            "event": "started",
                            "request_id": request_id,
                            "command_name": entry["command_name"],
                            "candidate_index": candidate,
                            "candidate_source": candidate_source,
                            "at": datetime.now(UTC).isoformat(),
                        }
                    )
                    source_arguments = (
                        {"candidate_source": candidate_source}
                        if candidate_source == "native_domain"
                        else {}
                    )
                    result = client.validate_recovered_command(
                        request_id=request_id,
                        command_name=entry["command_name"],
                        country_id=country_id,
                        candidate_index=candidate,
                        **source_arguments,
                    )
                    attempt = result.model_dump(mode="json")
                    entry["attempts"].append(attempt)
                    entry.update(status=result.status, reason=result.reason)
                    record(
                        {
                            "event": "completed",
                            "request_id": request_id,
                            "result": attempt,
                            "at": datetime.now(UTC).isoformat(),
                        }
                    )
                    pending_entry = None
                    pending_request_id = None
                    if result.candidate_source != candidate_source:
                        raise RuntimeError(
                            "Candidate source changed; refusing silent fallback."
                        )
                    if require_fixed_date:
                        if candidate_source == "native_domain" and result.fixture_paused is not True:
                            raise RuntimeError("Native paused fixture was not established.")
                        dates = (result.game_date_before, result.game_date_after)
                        # Idle(true) also runs while the simulation is paused.
                        # Keep its diagnostic flag separate from fixture time.
                        if None in dates or dates[0] != dates[1]:
                            raise RuntimeError(
                                "Fixed GameDate was not established."
                            )
                        if fixed_date is not None and fixed_date != dates[0]:
                            raise RuntimeError(
                                "GameDate changed within the fixture batch."
                            )
                        fixed_date = dates[0]
                    if result.world_identity:
                        if world_identity not in (None, result.world_identity):
                            raise RuntimeError(
                                "Loaded game state changed within the batch."
                            )
                        world_identity = result.world_identity
                    if (
                        result.status == "call_exception"
                        or result.reason == "native_factory_vtable_mismatch"
                        or result.reason
                        in {
                            "native_slot_relationship_mismatch",
                            "native_building_producer_branch_or_identity_mismatch",
                        }
                    ):
                        raise RuntimeError(
                            f"Unsafe native call stopped the batch: {result.reason}"
                        )
                    if interval:
                        time.sleep(interval)
                    if (
                        result.status != "native_invalid"
                        and not (exhaust_candidates and result.status == "native_valid")
                        and not (
                            candidate_source == "native_domain"
                            and result.reason == "native_building_subtype_not_covered"
                        )
                    ) or candidate + 1 >= result.candidate_count:
                        break
                entry["has_native_valid_candidate"] = any(
                    a["native_is_valid"] is True for a in entry["attempts"]
                )
                entry["native_validation_attempted"] = any(
                    a["native_is_valid"] is not None for a in entry["attempts"]
                )
                write_new_json(output / f"command-{index:04d}.json", entry)
                print(
                    f"[{index + 1}/{len(entries)}] {entry['command_name']}: "
                    f"{entry['status']} ({len(entry['attempts'])} candidates)",
                    flush=True,
                )
                if aborted:
                    break
            end_catalog = check_session("finished")
        except (RuntimeError, OSError, ValueError, KeyboardInterrupt) as error:
            aborted = f"{type(error).__name__}: {error}"
            # A disconnect is not proof of a native fault. The started record
            # identifies the interrupted stage; remaining commands stay untested.
            if pending_entry is not None:
                pending_entry.update(
                    status="interrupted",
                    reason="request_started_without_result",
                    interrupted_request_id=pending_request_id,
                )
            record({"event": "batch_interrupted", "error": aborted})
        finally:
            attempts = [attempt for entry in entries for attempt in entry["attempts"]]
            summary = {
                "catalog_commands": len(catalog.commands),
                "selected_commands": len(entries),
                "command_status_counts": dict(
                    Counter(entry["status"] for entry in entries)
                ),
                "structure_checked_commands": sum(
                    any(a["structure_checked"] for a in entry["attempts"])
                    for entry in entries
                ),
                "constructed_commands": sum(
                    any(
                        a["constructed_from_generated_metadata"]
                        for a in entry["attempts"]
                    )
                    for entry in entries
                ),
                "native_validator_calls": sum(
                    a["native_is_valid"] is not None for a in attempts
                ),
                "native_validated_commands": sum(
                    any(a["native_is_valid"] is not None for a in e["attempts"])
                    for e in entries
                ),
                "is_valid_true_commands": sum(
                    any(a["native_is_valid"] is True for a in e["attempts"])
                    for e in entries
                ),
                "negative_only_commands": sum(
                    any(a["native_is_valid"] is False for a in e["attempts"])
                    and not any(a["native_is_valid"] is True for a in e["attempts"])
                    for e in entries
                ),
                "populated_commands": sum(
                    any(a["parameters_populated"] for a in entry["attempts"])
                    for entry in entries
                ),
                "lifecycle_only_commands": sum(
                    any(
                        a["constructed_from_generated_metadata"]
                        for a in entry["attempts"]
                    )
                    and not any(
                        a["native_is_valid"] is not None for a in entry["attempts"]
                    )
                    for entry in entries
                ),
                "unclassified_native_rejections": sum(
                    a["native_is_valid"] is False for a in attempts
                ),
                "is_valid_true_calls": sum(
                    a["native_is_valid"] is True for a in attempts
                ),
                "context_free_true_calls": sum(
                    a["native_is_valid"] is True
                    and a["validator_kind"] == "context_free_constant"
                    for a in attempts
                ),
                "native_predicate_true_calls": sum(
                    a["native_is_valid"] is True
                    and a["validator_kind"] == "native_predicate"
                    for a in attempts
                ),
                "is_valid_false_calls": sum(
                    a["native_is_valid"] is False for a in attempts
                ),
                "non_updating_idle_native_calls": sum(
                    a["native_is_valid"] is not None and not a["run_game_update"]
                    for a in attempts
                ),
                "native_validate_us": sum(a["validate_us"] for a in attempts),
                "native_probe_us": sum(a["elapsed_us"] for a in attempts),
                "game_dates_observed": sorted(
                    {
                        date
                        for a in attempts
                        for date in (a["game_date_before"], a["game_date_after"])
                        if date is not None
                    }
                ),
                "skip_reasons": dict(
                    Counter(
                        entry["reason"]
                        for entry in entries
                        if entry["status"]
                        in {"missing_parameters", "not_tested", "structure_failed"}
                    )
                ),
            }
            report = {
                "schema_version": "iag.recovered_command_batch.v1",
                "run_id": run_id,
                "finished_at": datetime.now(UTC).isoformat(),
                "elapsed_seconds": round(time.monotonic() - started, 3),
                "process_id": catalog.process_id,
                "instance_id": catalog.instance_id,
                "build_id": catalog.build_id,
                "probe_revision": catalog.probe_revision,
                "same_session_confirmed": end_catalog == catalog,
                "world_identity": world_identity,
                "aborted": aborted,
                "submitted": False,
                "execution_verified": False,
                "candidate_limit_per_command": candidates,
                "candidate_source": candidate_source,
                "require_fixed_date": require_fixed_date,
                "fixed_game_date": fixed_date,
                "candidate_policy": "native_correlated_domain_queries"
                if candidate_source == "native_domain"
                else "fixed_actor_bounded_diagonal_native_refs_definitions_enums_owned_arrays",
                "summary": summary,
                "commands": entries,
            }
            write_new_json(output / "report.json", report)
            lines = [
                "# Recovered Command Batch",
                "",
                f"- PID: {catalog.process_id}",
                f"- Build: `{catalog.build_id}`",
                f"- Same session: {end_catalog == catalog}",
                f"- Aborted: {aborted}",
                "- No command submission; no live_verified promotion.",
                "",
                "```json",
                json.dumps(summary, indent=2),
                "```",
                "",
                "IsValid=false is an unclassified native rejection; retain native_reason where available.",
                "It alone cannot distinguish unsuitable candidates, world prerequisites, or a recovery defect.",
                "Candidate search is bounded, not an exhaustive legality proof.",
                "",
                "| Command | Result | Reason | Attempts |",
                "|---|---|---|---|",
            ]
            lines += [
                f"| {e['command_name']} | {e['status']} | {e['reason']} | {len(e['attempts'])} |"
                for e in entries
            ]
            with (output / "report.md").open("x", encoding="utf-8") as stream:
                stream.write("\n".join(lines) + "\n")
    return report


def compare_fixture_rounds(rounds: list[dict]) -> dict:
    """Compare semantic inputs, their native traversal order, and rule results.

    This is same-world repeatability evidence, not independent save-reload
    determinism, actual execution, complete legality, or multiplayer proof.
    """

    def signature(report: dict) -> list:
        return [
            [
                entry["command_name"],
                [
                    [
                        a["country_id"],
                        a["candidate_index"],
                        a["candidate_count"],
                        a.get("candidate_identity", ""),
                        a.get("parameter_source", ""),
                        a.get("native_rule_valid"),
                        a["native_is_valid"],
                        a["status"],
                        a["reason"],
                        a["bindings"],
                    ]
                    for a in entry["attempts"]
                ],
            ]
            for entry in report["commands"]
        ]

    complete = len(rounds) >= 2 and all(
        r["aborted"] is None and r["same_session_confirmed"] for r in rounds
    )
    identities = {
        (
            r["process_id"],
            r["instance_id"],
            r["build_id"],
            r["world_identity"],
            r["fixed_game_date"],
        )
        for r in rounds
    }
    same_fixture = (
        complete and len(identities) == 1 and rounds[0]["fixed_game_date"] is not None
    )
    has_calls = all(r["summary"]["native_validator_calls"] > 0 for r in rounds)
    comparable = same_fixture and has_calls
    return {
        "scope": "same_session_fixed_date_not_independent_reload",
        "comparable": comparable,
        "same_ordered_parameters_and_results": (
            all(signature(r) == signature(rounds[0]) for r in rounds[1:])
            if comparable
            else None
        ),
        "independent_reload_determinism_proven": False,
        "execution_verified": False,
        "promotions": 0,
    }


def run_validation_window(
    client: NativeRuntimeClient,
    output: Path,
    *,
    repeats: int = 2,
    command_names: tuple[str, ...] | None = None,
    country_id: int | None = None,
    candidates: int = 16,
    interval: float = 0.1,
    max_seconds: float = 900.0,
    plan: dict | None = None,
) -> dict:
    """A bounded window on the same endpoint, never a loader or game controller."""
    if not 1 <= repeats <= 3 or not math.isfinite(max_seconds) or max_seconds <= 0:
        raise ValueError("Invalid validation window limits.")
    output.mkdir(parents=True, exist_ok=False)
    started = time.monotonic()
    catalog = client.describe_recovered_commands(
        request_id=f"window-{uuid.uuid4().hex}"
    )
    write_new_json(output / "catalog.json", catalog.model_dump(mode="json"))
    if plan is not None:
        if (
            plan.get("schema_version") != "iag.producer_validation_preparation.v1"
            or plan.get("build_id") != catalog.build_id
            or not catalog.sdk_fingerprint
            or plan.get("sdk_fingerprint") != catalog.sdk_fingerprint
        ):
            write_new_json(
                output / "preflight-rejection.json",
                {
                    "reason": "preparation_plan_sdk_mismatch",
                    "new_native_requests": 0,
                    "loaded_sdk_fingerprint": catalog.sdk_fingerprint,
                    "plan_sdk_fingerprint": plan.get("sdk_fingerprint"),
                },
            )
            raise ValueError(
                "Preparation plan does not match the loaded generated SDK; no native requests sent."
            )
        planned = plan.get("native_domain_commands", []) + plan.get(
            "legacy_selected_commands", []
        )
        if not set(planned).issubset(catalog.commands):
            raise ValueError(
                "Prepared command names are absent from the loaded SDK; no native requests sent."
            )
        write_new_json(output / "accepted-plan.json", plan)
        if command_names is None:
            command_names = tuple(plan["native_domain_commands"])
    rounds = []
    abort = None
    for index in range(repeats):
        budget = max_seconds - (time.monotonic() - started)
        if budget <= 0:
            abort = "window_wall_clock_budget_exhausted"
            break
        report = run_batch(
            client,
            output / f"round-{index + 1:02d}",
            candidates=candidates,
            country_id=country_id,
            interval=interval,
            max_seconds=budget,
            command_names=command_names,
            candidate_source="native_domain",
            require_fixed_date=True,
            exhaust_candidates=True,
            expected_catalog=catalog,
            expected_world=rounds[0]["world_identity"] if rounds else None,
            expected_date=rounds[0]["fixed_game_date"] if rounds else None,
        )
        rounds.append(report)
        if report["aborted"]:
            abort = report["aborted"]
            break  # Never replay interrupted/pending calls.
    legacy_report = None
    if not abort and plan is not None and plan.get("legacy_selected_commands"):
        budget = max_seconds - (time.monotonic() - started)
        if budget <= 0:
            abort = "window_wall_clock_budget_exhausted"
        else:
            legacy_report = run_batch(
                client,
                output / "selected-sdk-backfill",
                candidates=candidates,
                country_id=country_id,
                interval=interval,
                max_seconds=budget,
                command_names=tuple(plan["legacy_selected_commands"]),
                require_fixed_date=True,
                expected_catalog=catalog,
                expected_world=rounds[0]["world_identity"],
                expected_date=rounds[0]["fixed_game_date"],
            )
            abort = legacy_report["aborted"]
    result = {
        "schema_version": "iag.native_producer_validation_window.v1",
        "finished_at": datetime.now(UTC).isoformat(),
        "requested_rounds": repeats,
        "completed_rounds": len(rounds),
        "aborted": abort,
        "submitted": False,
        "execution_verified": False,
        "comparison": compare_fixture_rounds(rounds),
        "round_reports": [f"round-{i + 1:02d}/report.json" for i in range(len(rounds))],
        "summaries": [r["summary"] for r in rounds],
        "selected_sdk_backfill": "selected-sdk-backfill/report.json"
        if legacy_report
        else None,
        "selected_sdk_summary": legacy_report["summary"] if legacy_report else None,
    }
    write_new_json(output / "window-report.json", result)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--endpoint")
    parser.add_argument(
        "--output",
        type=Path,
        required=True,
        help="New, non-existing evidence directory",
    )
    parser.add_argument(
        "--country",
        type=int,
        default=None,
        help="Default: observed/live native country",
    )
    parser.add_argument("--candidates", type=int, default=16)
    parser.add_argument("--interval", type=float, default=0.05)
    parser.add_argument("--batch-size", type=int, default=16)
    parser.add_argument("--max-seconds", type=float, default=900.0)
    parser.add_argument(
        "--command",
        action="append",
        dest="commands",
        help="Exact catalog name; repeat to select a bounded subset",
    )
    parser.add_argument(
        "--native-domain",
        action="store_true",
        help="Use only exact-build domain providers, no legacy fallback",
    )
    parser.add_argument(
        "--plan",
        type=Path,
        help="Immutable offline preparation plan; bind the loaded SDK and backfill only selected unproven commands",
    )
    parser.add_argument(
        "--repeat",
        type=int,
        default=1,
        choices=range(1, 4),
        help="Native domain window repetitions at one fixed GameDate",
    )
    args = parser.parse_args()
    if args.native_domain:
        report = run_validation_window(
            NativeRuntimeClient(args.endpoint),
            args.output,
            repeats=args.repeat,
            command_names=tuple(args.commands) if args.commands else None,
            country_id=args.country,
            candidates=args.candidates,
            interval=args.interval,
            max_seconds=args.max_seconds,
            plan=json.loads(args.plan.read_text(encoding="utf8"))
            if args.plan
            else None,
        )
        print(json.dumps(report, indent=2))
        return 1 if report["aborted"] else 0
    if args.repeat != 1:
        parser.error(
            "--repeat requires --native-domain; old validation is not silently replayed"
        )
    if args.plan:
        parser.error("--plan requires --native-domain")
    report = run_batch(
        NativeRuntimeClient(args.endpoint),
        args.output,
        candidates=args.candidates,
        country_id=args.country,
        interval=args.interval,
        batch_size=args.batch_size,
        max_seconds=args.max_seconds,
        command_names=tuple(args.commands) if args.commands else None,
    )
    print(json.dumps(report["summary"], indent=2))
    return 1 if report["aborted"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
