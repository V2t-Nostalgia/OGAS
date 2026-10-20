#!/usr/bin/env python3
"""Summarize and correlate Stellaris command-discovery probe captures."""

from __future__ import annotations

import argparse
import bisect
import collections
import datetime as dt
import json
from pathlib import Path
from typing import Any, Iterable


DEFAULT_AI_STACK_MARKER = "stellaris+0x238ebc5"
COMMAND_WRAPPERS = frozenset(
    {
        "CQueueFleetOrderCommand",
        "CQueueFleetsOrderCommand",
        "CAddBuildableToQueueCommand",
    }
)


def load_jsonl(path: Path) -> tuple[list[dict[str, Any]], int]:
    events: list[dict[str, Any]] = []
    malformed = 0
    with path.open("r", encoding="utf-8", errors="replace") as stream:
        for line in stream:
            try:
                value = json.loads(line)
            except json.JSONDecodeError:
                malformed += 1
                continue
            if isinstance(value, dict):
                events.append(value)
            else:
                malformed += 1
    return events, malformed


def load_jsonl_optional(path: Path) -> tuple[list[dict[str, Any]], int, bool]:
    try:
        events, malformed = load_jsonl(path)
    except FileNotFoundError:
        return [], 0, False
    return events, malformed, True


def dropped_event_count(events: Iterable[dict[str, Any]]) -> int:
    return sum(
        int(event.get("dropped_before", 0) or 0)
        + int(event.get("writer_dropped_before", 0) or 0)
        for event in events
    )


def infer_game_thread(commands: Iterable[dict[str, Any]]) -> int | None:
    tick_threads: collections.Counter[int] = collections.Counter()
    execute_threads: collections.Counter[int] = collections.Counter()
    for event in commands:
        thread_id = event.get("thread_id")
        if not isinstance(thread_id, int):
            continue
        if event.get("phase") == "execute_sync":
            execute_threads[thread_id] += 1
            if event.get("command_type") == "CTurnTickCommand":
                tick_threads[thread_id] += 1
    counts = tick_threads or execute_threads
    return counts.most_common(1)[0][0] if counts else None


def ai_origin_types(
    commands: Iterable[dict[str, Any]], marker: str
) -> set[str]:
    result: set[str] = set()
    for event in commands:
        stack = event.get("first_seen_stack")
        command_type = event.get("command_type")
        if isinstance(stack, list) and marker in stack and isinstance(command_type, str):
            result.add(command_type)
    return result


def payload_matches_wrapper(wrapper: str, event: dict[str, Any]) -> bool:
    object_type = str(event.get("object_type", ""))
    if wrapper == "CAddBuildableToQueueCommand":
        return event.get("kind") == "buildable"
    return "FleetOrder" in object_type and not object_type.endswith("Command")


def correlate_payloads(
    commands: list[dict[str, Any]],
    payloads: list[dict[str, Any]],
    game_thread: int,
) -> tuple[
    collections.Counter[tuple[str, str]],
    collections.Counter[str],
    collections.Counter[tuple[str, ...]],
]:
    payload_events = sorted(
        (
            event
            for event in payloads
            if event.get("thread_id") == game_thread
            and isinstance(event.get("monotonic_ns"), int)
        ),
        key=lambda event: event["monotonic_ns"],
    )
    if not payload_events:
        return collections.Counter(), collections.Counter(), collections.Counter()

    payload_times = [event["monotonic_ns"] for event in payload_events]
    low, high = payload_times[0], payload_times[-1]
    posts = sorted(
        (
            event
            for event in commands
            if event.get("phase") == "session_post"
            and event.get("thread_id") == game_thread
            and isinstance(event.get("monotonic_ns"), int)
            and event["monotonic_ns"] <= high
        ),
        key=lambda event: event["monotonic_ns"],
    )

    correlations: collections.Counter[tuple[str, str]] = collections.Counter()
    missing: collections.Counter[str] = collections.Counter()
    scripted_sequences: collections.Counter[tuple[str, ...]] = collections.Counter()
    for index, post in enumerate(posts):
        wrapper = str(post.get("command_type", ""))
        if wrapper not in COMMAND_WRAPPERS:
            continue
        start = post["monotonic_ns"]
        end = posts[index + 1]["monotonic_ns"] if index + 1 < len(posts) else high + 1
        if end <= low:
            continue
        begin_index = bisect.bisect_left(payload_times, start)
        end_index = bisect.bisect_left(payload_times, end, lo=begin_index)
        window = payload_events[begin_index:end_index]
        match = next(
            (
                event
                for event in window
                if payload_matches_wrapper(wrapper, event)
            ),
            None,
        )
        if match is None:
            missing[wrapper] += 1
            continue
        correlations[(wrapper, str(match.get("object_type", "<unknown>")))] += 1
        if match.get("object_type") == "CScriptedFleetOrder":
            nested_types = tuple(
                str(event["object_type"])
                for event in window
                if isinstance(event.get("object_type"), str)
                and (
                    "FleetOrder" in event["object_type"]
                    or "FleetAction" in event["object_type"]
                )
                and not event["object_type"].endswith("Command")
            )
            scripted_sequences[nested_types] += 1
    return correlations, missing, scripted_sequences


def format_time_ns(value: int | None) -> str:
    if value is None:
        return "unknown"
    instant = dt.datetime.fromtimestamp(value / 1_000_000_000, tz=dt.timezone.utc)
    return instant.isoformat().replace("+00:00", "Z")


def print_counter(
    counter: collections.Counter[Any], *, limit: int, formatter: Any
) -> None:
    items = counter.most_common(None if limit == 0 else limit)
    if not items:
        print("  (none)")
        return
    for key, count in items:
        print(f"  {count:7d}  {formatter(key)}")


def summarize_states(states: Iterable[dict[str, Any]]) -> dict[str, Any]:
    kinds: collections.Counter[str] = collections.Counter()
    event_content: dict[str, dict[str, Any]] = {}
    situations: collections.Counter[str] = collections.Counter()
    approaches: collections.Counter[tuple[str, str]] = collections.Counter()
    chains: collections.Counter[tuple[str, str]] = collections.Counter()
    selected_options: collections.Counter[tuple[str, int]] = collections.Counter()
    for event in states:
        kind = str(event.get("kind") or "<unknown>")
        if kind == "probe_started":
            continue
        kinds[kind] += 1
        key = str(event.get("event_or_type_key") or "<unknown>")
        if kind.startswith("situation_"):
            situations[key] += 1
            approach = str(event.get("approach_key") or "")
            if approach:
                approaches[(key, approach)] += 1
        elif kind.startswith("event_chain_"):
            chains[(kind, key)] += 1
        else:
            option_index = event.get("option_index")
            if kind == "event_executed" and isinstance(option_index, int):
                selected_options[(key, option_index)] += 1
            if event.get("content_included") is True:
                options = event.get("options")
                option_values = options if isinstance(options, list) else []
                option_keys = [
                    str(option.get("text_key"))
                    for option in option_values
                    if isinstance(option, dict) and option.get("text_key")
                ]
                event_content[key] = {
                    "title_key": str(event.get("title_key") or ""),
                    "description_key": str(event.get("description_key") or ""),
                    "option_keys": option_keys,
                    "text_truncated": event.get("text_truncated") is True,
                }
    return {
        "kinds": kinds,
        "event_content": event_content,
        "situations": situations,
        "approaches": approaches,
        "chains": chains,
        "selected_options": selected_options,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--commands",
        type=Path,
        default=Path("/tmp/iag-stellaris-command-probe.jsonl"),
    )
    parser.add_argument(
        "--payloads",
        type=Path,
        default=Path("/tmp/iag-stellaris-payload-probe.jsonl"),
    )
    parser.add_argument(
        "--states",
        type=Path,
        default=Path("/tmp/iag-stellaris-state-probe.jsonl"),
    )
    parser.add_argument("--game-thread", type=int)
    parser.add_argument("--ai-stack-marker", default=DEFAULT_AI_STACK_MARKER)
    parser.add_argument(
        "--top",
        type=int,
        default=50,
        help="Maximum rows per section; use 0 for all rows.",
    )
    parser.add_argument(
        "--require-zero-drops",
        action="store_true",
        help="Return a non-zero status when either probe reports dropped events.",
    )
    args = parser.parse_args()

    commands, malformed_commands = load_jsonl(args.commands)
    payloads, malformed_payloads = load_jsonl(args.payloads)
    states, malformed_states, states_present = load_jsonl_optional(args.states)
    command_drops = dropped_event_count(commands)
    payload_drops = dropped_event_count(payloads)
    state_drops = dropped_event_count(states)
    game_thread = args.game_thread or infer_game_thread(commands)
    ai_types = ai_origin_types(commands, args.ai_stack_marker)

    realtime_values = [
        int(event["realtime_ns"])
        for event in commands + payloads + states
        if isinstance(event.get("realtime_ns"), int)
    ]
    print("CAPTURE HEALTH")
    print(f"  command events: {len(commands)}")
    print(f"  payload events: {len(payloads)}")
    print(
        f"  state events: {len(states)}"
        + ("" if states_present else " (state stream not present)")
    )
    print(
        "  malformed lines: "
        f"commands={malformed_commands}, payloads={malformed_payloads}, "
        f"states={malformed_states}"
    )
    print(
        "  dropped events: "
        f"commands={command_drops}, payloads={payload_drops}, states={state_drops}"
    )
    print(f"  game thread: {game_thread if game_thread is not None else 'unknown'}")
    if realtime_values:
        print(
            "  UTC window: "
            f"{format_time_ns(min(realtime_values))} .. {format_time_ns(max(realtime_values))}"
        )

    phase_counts: collections.Counter[tuple[str, str]] = collections.Counter()
    for event in commands:
        command_type = event.get("command_type")
        phase = event.get("phase")
        if command_type in ai_types and phase in {"session_post", "execute_sync"}:
            phase_counts[(str(command_type), str(phase))] += 1

    print(f"\nAI-ORIGIN COMMANDS ({len(ai_types)} TYPES)")
    post_counts: collections.Counter[str] = collections.Counter(
        {
            command_type: phase_counts[(command_type, "session_post")]
            for command_type in ai_types
            if phase_counts[(command_type, "session_post")]
        }
    )
    print_counter(post_counts, limit=args.top, formatter=str)

    state = summarize_states(states)
    print("\nEVENT / SITUATION STATE KINDS")
    print_counter(state["kinds"], limit=args.top, formatter=str)
    print("\nEVENT CONTENT KEYS")
    content_items = sorted(state["event_content"].items())
    if args.top:
        content_items = content_items[: args.top]
    if not content_items:
        print("  (none)")
    for key, content in content_items:
        options = ",".join(content["option_keys"]) or "-"
        suffix = " [truncated]" if content["text_truncated"] else ""
        print(
            f"  {key}: title={content['title_key'] or '-'} "
            f"desc={content['description_key'] or '-'} options={options}{suffix}"
        )
    print("\nSITUATION TYPES")
    print_counter(state["situations"], limit=args.top, formatter=str)
    print("\nSITUATION APPROACHES")
    print_counter(
        state["approaches"],
        limit=args.top,
        formatter=lambda value: f"{value[0]} -> {value[1]}",
    )
    print("\nEVENT CHAINS")
    print_counter(
        state["chains"],
        limit=args.top,
        formatter=lambda value: f"{value[0]}: {value[1]}",
    )
    print("\nEXECUTED EVENT OPTIONS")
    print_counter(
        state["selected_options"],
        limit=args.top,
        formatter=lambda value: f"{value[0]} option={value[1]}",
    )

    if game_thread is None:
        print("\nPAYLOAD CORRELATION\n  unavailable: game thread could not be inferred")
        return 2

    correlations, missing, scripted_sequences = correlate_payloads(
        commands, payloads, game_thread
    )
    print("\nFINAL MAIN-THREAD PAYLOAD CORRELATION")
    print_counter(
        correlations,
        limit=args.top,
        formatter=lambda key: f"{key[0]} -> {key[1]}",
    )
    print("\nUNMATCHED WRAPPERS")
    print_counter(missing, limit=args.top, formatter=str)

    print("\nFINAL SCRIPTED FLEET-ORDER SEQUENCES")
    print_counter(
        scripted_sequences,
        limit=args.top,
        formatter=lambda sequence: " -> ".join(sequence),
    )

    worker_payloads: collections.Counter[str] = collections.Counter()
    main_payloads: collections.Counter[str] = collections.Counter()
    for event in payloads:
        object_type = event.get("object_type")
        if not isinstance(object_type, str):
            continue
        if event.get("thread_id") == game_thread:
            main_payloads[object_type] += 1
        else:
            worker_payloads[object_type] += 1
    worker_only = collections.Counter(
        {
            object_type: count
            for object_type, count in worker_payloads.items()
            if main_payloads[object_type] == 0
        }
    )
    print("\nWORKER-ONLY PAYLOAD CANDIDATES (NOT FINAL SUBMISSIONS)")
    print_counter(worker_only, limit=args.top, formatter=str)

    if args.require_zero_drops and (command_drops or payload_drops or state_drops):
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
