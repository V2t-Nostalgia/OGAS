#!/usr/bin/env python3
"""Archive long-running passive Stellaris command discovery captures."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
import re
import shutil
import signal
import time
import zipfile
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, BinaryIO


SCHEMA = "iag.stellaris.long_run_capture.v1"
COVERAGE_SCHEMA = "iag.stellaris.capture_coverage.v1"
AI_STACK_MARKER = "stellaris+0x238ebc5"
GAME_DATE_PATTERN = re.compile(
    r"(?:^|\s)date\s*=\s*\"?(\d{1,6}\.\d{1,2}\.\d{1,2})\"?",
    re.MULTILINE,
)


def utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def atomic_write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, sort_keys=True)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def append_jsonl(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(value, ensure_ascii=False, sort_keys=True))
        stream.write("\n")
        stream.flush()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_json(path: Path, fallback: dict[str, Any]) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return fallback
    return value if isinstance(value, dict) else fallback


def bounded_add(values: list[str], candidate: Any, limit: int = 16) -> None:
    if not isinstance(candidate, str) or not candidate or candidate in values:
        return
    if len(values) < limit:
        values.append(candidate)


LAYOUT_VOLATILE_FIELDS = {
    "sequence",
    "realtime_ns",
    "monotonic_ns",
    "pid",
    "tid",
    "caller",
    "first_seen_stack",
    "dropped_before",
    "writer_dropped_before",
    "known_command_hex",
    "known_nested_hex",
}


def _value_shape(value: Any, path: str, output: list[str], depth: int = 0) -> None:
    if depth > 4:
        output.append(f"{path}:depth_limit")
        return
    if isinstance(value, dict):
        output.append(f"{path}:object")
        for key in sorted(value):
            if key not in LAYOUT_VOLATILE_FIELDS:
                _value_shape(value[key], f"{path}.{key}", output, depth + 1)
    elif isinstance(value, list):
        output.append(f"{path}:list")
        for item in value[:4]:
            _value_shape(item, f"{path}[]", output, depth + 1)
    elif isinstance(value, bool):
        output.append(f"{path}:bool")
    elif isinstance(value, int):
        output.append(f"{path}:int")
    elif isinstance(value, float):
        output.append(f"{path}:float")
    elif isinstance(value, str):
        output.append(f"{path}:str")
    elif value is None:
        output.append(f"{path}:null")
    else:
        output.append(f"{path}:{type(value).__name__}")


def layout_signature(event: dict[str, Any]) -> dict[str, Any]:
    """Return a bounded structural fingerprint without preserving parameters."""
    shape: list[str] = []
    for key in sorted(event):
        if key not in LAYOUT_VOLATILE_FIELDS:
            _value_shape(event[key], key, shape)
    command_hex = event.get("known_command_hex")
    nested_hex = event.get("known_nested_hex")
    evidence = {
        "schema": event.get("schema"),
        "kind": event.get("kind"),
        "known_command_size": event.get("known_command_size"),
        "known_command_hex_bytes": len(command_hex) // 2
        if isinstance(command_hex, str)
        else None,
        "known_nested_size": event.get("known_nested_size"),
        "known_nested_hex_bytes": len(nested_hex) // 2
        if isinstance(nested_hex, str)
        else None,
        "known_nested_complete": event.get("known_nested_complete"),
        "command_vtable_methods": event.get("command_vtable_methods", []),
        "nested_vtable_methods": event.get("nested_vtable_methods", []),
        "field_shape": sorted(set(shape)),
    }
    encoded = json.dumps(evidence, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )
    return {
        "fingerprint": hashlib.sha256(encoded).hexdigest(),
        "count": 1,
        **evidence,
    }


def observe_layout_signature(record: dict[str, Any], event: dict[str, Any]) -> None:
    candidate = layout_signature(event)
    signatures = record.setdefault("layout_signatures", [])
    for existing in signatures:
        if existing.get("fingerprint") == candidate["fingerprint"]:
            existing["count"] = int(existing.get("count", 0)) + 1
            return
    if len(signatures) < 16:
        signatures.append(candidate)


def iter_jsonl(stream: BinaryIO) -> Iterator[tuple[dict[str, Any] | None, bytes]]:
    for raw_line in stream:
        if not raw_line.endswith(b"\n"):
            yield None, raw_line
            break
        try:
            value = json.loads(raw_line)
        except (json.JSONDecodeError, UnicodeDecodeError):
            yield None, raw_line
            continue
        yield value if isinstance(value, dict) else None, raw_line


@dataclass
class SegmentSummary:
    stream: str
    source: str
    raw_sha256: str = ""
    raw_bytes: int = 0
    records: int = 0
    malformed: int = 0
    dropped: int = 0
    writer_dropped: int = 0
    probe_pid: int | None = None
    min_sequence: int | None = None
    max_sequence: int | None = None
    min_realtime_ns: int | None = None
    max_realtime_ns: int | None = None

    def observe(self, event: dict[str, Any]) -> None:
        if event.get("kind") == "probe_started":
            pid = event.get("pid")
            if isinstance(pid, int):
                self.probe_pid = pid
            return
        self.records += 1
        self.dropped += int(event.get("dropped_before", 0) or 0)
        self.writer_dropped += int(event.get("writer_dropped_before", 0) or 0)
        sequence = event.get("sequence")
        if isinstance(sequence, int):
            self.min_sequence = (
                sequence
                if self.min_sequence is None
                else min(self.min_sequence, sequence)
            )
            self.max_sequence = (
                sequence
                if self.max_sequence is None
                else max(self.max_sequence, sequence)
            )
        realtime_ns = event.get("realtime_ns")
        if isinstance(realtime_ns, int):
            self.min_realtime_ns = (
                realtime_ns
                if self.min_realtime_ns is None
                else min(self.min_realtime_ns, realtime_ns)
            )
            self.max_realtime_ns = (
                realtime_ns
                if self.max_realtime_ns is None
                else max(self.max_realtime_ns, realtime_ns)
            )

    def as_dict(self) -> dict[str, Any]:
        return {
            "stream": self.stream,
            "source": self.source,
            "raw_sha256": self.raw_sha256,
            "raw_bytes": self.raw_bytes,
            "records": self.records,
            "malformed": self.malformed,
            "dropped": self.dropped,
            "writer_dropped": self.writer_dropped,
            "probe_pid": self.probe_pid,
            "min_sequence": self.min_sequence,
            "max_sequence": self.max_sequence,
            "min_realtime_ns": self.min_realtime_ns,
            "max_realtime_ns": self.max_realtime_ns,
        }


class CaptureCatalog:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.data = load_json(
            path,
            {
                "schema": SCHEMA,
                "updated_at": utc_now(),
                "totals": {
                    "command_records": 0,
                    "payload_records": 0,
                    "state_records": 0,
                    "malformed": 0,
                    "dropped": 0,
                    "writer_dropped": 0,
                },
                "command_types": {},
                "payload_types": {},
                "state_kinds": {},
                "event_definitions": {},
                "event_definition_ids": {},
                "situation_types": {},
                "situation_ids": {},
                "event_chains": {},
                "event_chain_definition_ids": {},
                "processed_segments": {},
            },
        )

    @property
    def processed_segments(self) -> dict[str, Any]:
        return self.data.setdefault("processed_segments", {})

    def observe(self, stream: str, event: dict[str, Any]) -> None:
        if event.get("kind") == "probe_started":
            return
        if stream == "commands":
            self._observe_command(event)
        elif stream == "payloads":
            self._observe_payload(event)
        else:
            self._observe_state(event)

    def _observe_command(self, event: dict[str, Any]) -> None:
        command_type = str(event.get("command_type") or "<unknown>")
        values = self.data.setdefault("command_types", {})
        record = values.setdefault(
            command_type,
            {
                "phases": {},
                "callers": [],
                "nested_types": [],
                "first_sequence": None,
                "last_sequence": None,
                "first_realtime_ns": None,
                "last_realtime_ns": None,
                "ai_origin_observed": False,
                "first_seen_stack": [],
            },
        )
        phase = str(event.get("phase") or "unknown")
        phases = record.setdefault("phases", {})
        phases[phase] = int(phases.get(phase, 0)) + 1
        bounded_add(record.setdefault("callers", []), event.get("caller"))
        bounded_add(
            record.setdefault("nested_types", []), event.get("nested_type")
        )
        stack = event.get("first_seen_stack")
        if isinstance(stack, list) and stack:
            record["first_seen_stack"] = [str(value) for value in stack[:32]]
            if AI_STACK_MARKER in stack:
                record["ai_origin_observed"] = True
        observe_layout_signature(record, event)
        self._observe_bounds(record, event)

    def _observe_payload(self, event: dict[str, Any]) -> None:
        object_type = str(event.get("object_type") or "<unknown>")
        values = self.data.setdefault("payload_types", {})
        record = values.setdefault(
            object_type,
            {
                "kinds": {},
                "labels": [],
                "first_sequence": None,
                "last_sequence": None,
                "first_realtime_ns": None,
                "last_realtime_ns": None,
            },
        )
        kind = str(event.get("kind") or "unknown")
        kinds = record.setdefault("kinds", {})
        kinds[kind] = int(kinds.get(kind, 0)) + 1
        label = event.get("label_or_type")
        if isinstance(label, int):
            bounded_add(record.setdefault("labels", []), str(label), limit=32)
        observe_layout_signature(record, event)
        self._observe_bounds(record, event)

    def _observe_state(self, event: dict[str, Any]) -> None:
        kind = str(event.get("kind") or "<unknown>")
        kinds = self.data.setdefault("state_kinds", {})
        kinds[kind] = int(kinds.get(kind, 0)) + 1
        key = str(event.get("event_or_type_key") or "")
        if kind.startswith("situation_"):
            values = self.data.setdefault("situation_types", {})
            object_id = event.get("situation_id")
            identities = self.data.setdefault("situation_ids", {})
            id_key = str(object_id)
            if key and isinstance(object_id, int) and object_id != 0xFFFFFFFF:
                identities[id_key] = key
            identity = key or str(identities.get(id_key) or f"#{id_key}")
        elif kind.startswith("event_chain_"):
            values = self.data.setdefault("event_chains", {})
            object_id = event.get("event_chain_definition_id")
            identities = self.data.setdefault("event_chain_definition_ids", {})
            id_key = str(object_id)
            if key and isinstance(object_id, int) and object_id != 0xFFFFFFFF:
                identities[id_key] = key
            identity = key or str(identities.get(id_key) or f"#{id_key}")
        else:
            values = self.data.setdefault("event_definitions", {})
            object_id = event.get("event_definition_id")
            identities = self.data.setdefault("event_definition_ids", {})
            id_key = str(object_id)
            if key and isinstance(object_id, int) and object_id != 0xFFFFFFFF:
                identities[id_key] = key
            identity = key or str(identities.get(id_key) or f"#{id_key}")
        record = values.setdefault(
            identity,
            {
                "kinds": {},
                "title_keys": [],
                "description_keys": [],
                "option_keys": [],
                "approach_keys": [],
                "content_observed": False,
                "first_sequence": None,
                "last_sequence": None,
                "first_realtime_ns": None,
                "last_realtime_ns": None,
            },
        )
        record_kinds = record.setdefault("kinds", {})
        record_kinds[kind] = int(record_kinds.get(kind, 0)) + 1
        bounded_add(record.setdefault("title_keys", []), event.get("title_key"), 32)
        bounded_add(
            record.setdefault("description_keys", []),
            event.get("description_key"),
            32,
        )
        bounded_add(
            record.setdefault("approach_keys", []), event.get("approach_key"), 32
        )
        options = event.get("options")
        if isinstance(options, list):
            for option in options:
                if isinstance(option, dict):
                    bounded_add(
                        record.setdefault("option_keys", []),
                        option.get("text_key"),
                        64,
                    )
        if event.get("content_included") is True:
            record["content_observed"] = True
        self._observe_bounds(record, event)

    @staticmethod
    def _observe_bounds(record: dict[str, Any], event: dict[str, Any]) -> None:
        sequence = event.get("sequence")
        if isinstance(sequence, int):
            first = record.get("first_sequence")
            last = record.get("last_sequence")
            record["first_sequence"] = sequence if first is None else min(first, sequence)
            record["last_sequence"] = sequence if last is None else max(last, sequence)
        realtime_ns = event.get("realtime_ns")
        if isinstance(realtime_ns, int):
            first_time = record.get("first_realtime_ns")
            last_time = record.get("last_realtime_ns")
            record["first_realtime_ns"] = (
                realtime_ns if first_time is None else min(first_time, realtime_ns)
            )
            record["last_realtime_ns"] = (
                realtime_ns if last_time is None else max(last_time, realtime_ns)
            )

    def commit_segment(self, summary: SegmentSummary) -> None:
        totals = self.data.setdefault("totals", {})
        key = {
            "commands": "command_records",
            "payloads": "payload_records",
            "states": "state_records",
        }[summary.stream]
        totals[key] = int(totals.get(key, 0)) + summary.records
        totals["malformed"] = int(totals.get("malformed", 0)) + summary.malformed
        totals["dropped"] = int(totals.get("dropped", 0)) + summary.dropped
        totals["writer_dropped"] = (
            int(totals.get("writer_dropped", 0)) + summary.writer_dropped
        )
        self.processed_segments[summary.raw_sha256] = summary.as_dict()
        self.data["updated_at"] = utc_now()
        atomic_write_json(self.path, self.data)


class LiveCoverage:
    STATE_TARGETS = (
        "event_executed",
        "event_content",
        "event_options",
        "open_event_added",
        "open_event_removed",
        "situation_created",
        "situation_destroyed",
        "situation_stage_changed",
        "situation_approach_changed",
        "situation_delayed_event",
        "event_chain_started",
        "event_chain_ended",
    )

    def __init__(self, path: Path, plateau_seconds: float) -> None:
        self.path = path
        self.plateau_seconds = plateau_seconds
        self.data = load_json(
            path,
            {
                "schema": COVERAGE_SCHEMA,
                "updated_at": utc_now(),
                "command_types": [],
                "nested_types": [],
                "payload_types": [],
                "state_kinds": [],
                "event_keys": [],
                "event_content_keys": [],
                "situation_type_keys": [],
                "event_chain_keys": [],
                "state_targets": {},
                "new_discoveries": 0,
                "last_new_at": None,
                "last_new_realtime_ns": None,
            },
        )

    def _add(self, name: str, value: Any) -> bool:
        if not isinstance(value, str) or not value:
            return False
        values = self.data.setdefault(name, [])
        if value in values:
            return False
        values.append(value)
        values.sort()
        return True

    def _mark(self, name: str) -> bool:
        targets = self.data.setdefault("state_targets", {})
        if targets.get(name) is True:
            return False
        targets[name] = True
        return True

    def observe(self, stream: str, event: dict[str, Any]) -> None:
        if event.get("kind") == "probe_started":
            return
        changed = False
        if stream == "commands":
            changed |= self._add("command_types", event.get("command_type"))
            changed |= self._add("nested_types", event.get("nested_type"))
        elif stream == "payloads":
            changed |= self._add("payload_types", event.get("object_type"))
        else:
            kind = str(event.get("kind") or "")
            key = event.get("event_or_type_key")
            changed |= self._add("state_kinds", kind)
            if kind in self.STATE_TARGETS:
                changed |= self._mark(kind)
            if kind == "event_executed":
                changed |= self._mark("event_executed")
            if kind.startswith("situation_"):
                changed |= self._add("situation_type_keys", key)
            elif kind.startswith("event_chain_"):
                changed |= self._add("event_chain_keys", key)
            else:
                changed |= self._add("event_keys", key)
            if event.get("content_included") is True:
                changed |= self._mark("event_content")
                changed |= self._add("event_content_keys", key)
                options = event.get("options")
                if isinstance(options, list) and options:
                    changed |= self._mark("event_options")
        realtime_ns = event.get("realtime_ns")
        if isinstance(realtime_ns, int):
            self.data["last_observed_realtime_ns"] = realtime_ns
        if changed:
            self.data["new_discoveries"] = int(
                self.data.get("new_discoveries", 0)
            ) + 1
            self.data["last_new_at"] = utc_now()
            self.data["last_new_realtime_ns"] = (
                realtime_ns if isinstance(realtime_ns, int) else time.time_ns()
            )

    def snapshot(self, now_realtime_ns: int | None = None) -> dict[str, Any]:
        now_ns = time.time_ns() if now_realtime_ns is None else now_realtime_ns
        targets = self.data.setdefault("state_targets", {})
        missing = [name for name in self.STATE_TARGETS if not targets.get(name)]
        last_new_ns = self.data.get("last_new_realtime_ns")
        plateau_seconds = 0.0
        if isinstance(last_new_ns, int) and now_ns >= last_new_ns:
            plateau_seconds = (now_ns - last_new_ns) / 1_000_000_000
        snapshot = dict(self.data)
        snapshot.update(
            {
                "schema": COVERAGE_SCHEMA,
                "updated_at": utc_now(),
                "counts": {
                    name: len(self.data.get(name, []))
                    for name in (
                        "command_types",
                        "nested_types",
                        "payload_types",
                        "state_kinds",
                        "event_keys",
                        "event_content_keys",
                        "situation_type_keys",
                        "event_chain_keys",
                    )
                },
                "missing_state_targets": missing,
                "all_state_targets_observed": not missing,
                "coverage_plateau_seconds": plateau_seconds,
                "coverage_plateau_required_seconds": self.plateau_seconds,
                "ready_for_early_review": (
                    not missing and plateau_seconds >= self.plateau_seconds
                ),
            }
        )
        return snapshot

    def write(self) -> dict[str, Any]:
        snapshot = self.snapshot()
        atomic_write_json(self.path, snapshot)
        return snapshot


class ActiveStreamTail:
    def __init__(self, name: str, path: Path, state: dict[str, Any]) -> None:
        self.name = name
        self.path = path
        self.state = state

    def poll(
        self,
        budget_bytes: int,
        observer: Callable[[str, dict[str, Any]], None] | None = None,
    ) -> None:
        try:
            status = self.path.stat()
        except FileNotFoundError:
            self.state["present"] = False
            return
        identity = f"{status.st_dev}:{status.st_ino}"
        if self.state.get("identity") != identity or status.st_size < int(
            self.state.get("offset", 0)
        ):
            self.state.update({"identity": identity, "offset": 0, "probe_pid": None})
        self.state["present"] = True
        self.state["size"] = status.st_size
        offset = int(self.state.get("offset", 0))
        with self.path.open("rb") as stream:
            stream.seek(offset)
            data = stream.read(budget_bytes)
        end = data.rfind(b"\n")
        if end < 0:
            return
        complete = data[: end + 1]
        for raw_line in complete.splitlines():
            try:
                event = json.loads(raw_line)
            except (json.JSONDecodeError, UnicodeDecodeError):
                self.state["malformed"] = int(self.state.get("malformed", 0)) + 1
                continue
            if not isinstance(event, dict):
                continue
            if observer is not None:
                observer(self.name, event)
            if event.get("kind") == "probe_started":
                pid = event.get("pid")
                if isinstance(pid, int):
                    self.state["probe_pid"] = pid
                    key = str(pid)
                    self.state["max_sequence"] = int(
                        self.state.setdefault("sequences_by_pid", {}).get(key, 0)
                    )
                    self.state["max_realtime_ns"] = int(
                        self.state.setdefault("realtime_by_pid", {}).get(key, 0)
                    )
                continue
            sequence = event.get("sequence")
            if isinstance(sequence, int):
                pid_key = str(self.state.get("probe_pid") or "unknown")
                sequences = self.state.setdefault("sequences_by_pid", {})
                sequences[pid_key] = max(int(sequences.get(pid_key, 0)), sequence)
                self.state["max_sequence"] = sequences[pid_key]
            realtime_ns = event.get("realtime_ns")
            if isinstance(realtime_ns, int):
                pid_key = str(self.state.get("probe_pid") or "unknown")
                realtime = self.state.setdefault("realtime_by_pid", {})
                realtime[pid_key] = max(int(realtime.get(pid_key, 0)), realtime_ns)
                self.state["max_realtime_ns"] = realtime[pid_key]
            self.state["last_event_at"] = utc_now()
        self.state["offset"] = offset + len(complete)


class SegmentArchiver:
    def __init__(
        self,
        output: Path,
        catalog: CaptureCatalog,
        manifest_hashes: set[str] | None = None,
    ) -> None:
        self.output = output
        self.catalog = catalog
        self.manifest_path = output / "segment_index.jsonl"
        self.manifest_hashes = manifest_hashes or self._load_manifest_hashes()

    def _load_manifest_hashes(self) -> set[str]:
        hashes: set[str] = set()
        try:
            lines = self.manifest_path.read_text(encoding="utf-8").splitlines()
        except FileNotFoundError:
            return hashes
        for line in lines:
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            digest = record.get("raw_sha256") if isinstance(record, dict) else None
            if isinstance(digest, str):
                hashes.add(digest)
        return hashes

    def process(
        self,
        stream_name: str,
        source: Path,
        observer: Callable[[str, dict[str, Any]], None] | None = None,
    ) -> SegmentSummary:
        summary = self._read_segment(stream_name, source)
        destination_directory = self.output / "segments" / stream_name
        destination_directory.mkdir(parents=True, exist_ok=True)
        destination = destination_directory / f"{source.name}.gz"
        if not destination.exists():
            temporary = destination.with_name(f".{destination.name}.{os.getpid()}.tmp")
            with source.open("rb") as input_stream, gzip.open(
                temporary, "wb", compresslevel=1
            ) as output_stream:
                shutil.copyfileobj(input_stream, output_stream, 1024 * 1024)
            os.replace(temporary, destination)

        already_processed = summary.raw_sha256 in self.catalog.processed_segments
        if not already_processed:
            with source.open("rb") as stream:
                for event, _ in iter_jsonl(stream):
                    if event is not None:
                        self.catalog.observe(stream_name, event)
                        if observer is not None:
                            observer(stream_name, event)
            self.catalog.commit_segment(summary)
        if summary.raw_sha256 not in self.manifest_hashes:
            record = summary.as_dict()
            record.update(
                {
                    "schema": SCHEMA,
                    "archived_at": utc_now(),
                    "archive": str(destination),
                    "archive_bytes": destination.stat().st_size,
                    "archive_sha256": sha256_file(destination),
                }
            )
            append_jsonl(self.manifest_path, record)
            self.manifest_hashes.add(summary.raw_sha256)
        source.unlink(missing_ok=True)
        return summary

    @staticmethod
    def _read_segment(stream_name: str, source: Path) -> SegmentSummary:
        summary = SegmentSummary(stream=stream_name, source=str(source))
        summary.raw_bytes = source.stat().st_size
        summary.raw_sha256 = sha256_file(source)
        with source.open("rb") as stream:
            for event, _ in iter_jsonl(stream):
                if event is None:
                    summary.malformed += 1
                    continue
                summary.observe(event)
        return summary


@dataclass
class SaveObservation:
    size: int
    mtime_ns: int
    stable_since: float
    archived_signature: tuple[int, int] | None = None


class SaveArchiver:
    def __init__(
        self,
        save_root: Path,
        output: Path,
        stable_seconds: float,
        session_started_ns: int,
        include_existing_newest: bool,
        disk_reserve_bytes: int,
    ) -> None:
        self.save_root = save_root
        self.output = output
        self.output.mkdir(parents=True, exist_ok=True)
        self.stable_seconds = stable_seconds
        self.session_started_ns = session_started_ns
        self.include_existing_newest = include_existing_newest
        self.disk_reserve_bytes = disk_reserve_bytes
        self.observations: dict[str, SaveObservation] = {}
        self.archived_hashes = self._load_archived_hashes()
        self.baseline_path: Path | None = None

    def _load_archived_hashes(self) -> set[str]:
        values: set[str] = set()
        path = self.output / "save_index.jsonl"
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except FileNotFoundError:
            return values
        for line in lines:
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            digest = record.get("sha256") if isinstance(record, dict) else None
            if isinstance(digest, str):
                values.add(digest)
        return values

    def scan(
        self, now_monotonic: float, stream_high_water: dict[str, Any]
    ) -> list[dict[str, Any]]:
        if not self.save_root.exists():
            return []
        candidates_with_mtime: list[tuple[int, Path]] = []
        for path in self.save_root.rglob("*.sav"):
            if path.is_relative_to(self.output):
                continue
            try:
                status = path.stat()
            except OSError:
                # Stellaris replaces rotating autosaves in place. A file found by
                # rglob can legitimately disappear before the directory scan ends.
                continue
            if not path.is_file():
                continue
            candidates_with_mtime.append((status.st_mtime_ns, path))
        candidates = [
            path for _, path in sorted(candidates_with_mtime, key=lambda item: item[0])
        ]
        if self.baseline_path is None and self.include_existing_newest and candidates:
            self.baseline_path = candidates[-1]
        archived: list[dict[str, Any]] = []
        for path in candidates:
            try:
                status = path.stat()
            except OSError:
                continue
            key = str(path.resolve())
            signature = (status.st_size, status.st_mtime_ns)
            observation = self.observations.get(key)
            if observation is None or (observation.size, observation.mtime_ns) != signature:
                self.observations[key] = SaveObservation(
                    size=status.st_size,
                    mtime_ns=status.st_mtime_ns,
                    stable_since=now_monotonic,
                )
                continue
            if observation.archived_signature == signature:
                continue
            eligible = (
                status.st_mtime_ns >= self.session_started_ns
                or path == self.baseline_path
            )
            if not eligible or now_monotonic - observation.stable_since < self.stable_seconds:
                continue
            record = self._archive(path, stream_high_water)
            if record is None:
                continue
            observation.archived_signature = signature
            archived.append(record)
        return archived

    def _archive(
        self, source: Path, stream_high_water: dict[str, Any]
    ) -> dict[str, Any] | None:
        if shutil.disk_usage(self.output).free < self.disk_reserve_bytes:
            return None
        try:
            with zipfile.ZipFile(source) as archive:
                members = set(archive.namelist())
                if not {"meta", "gamestate"}.issubset(members):
                    return None
                metadata_text = archive.read("meta").decode(
                    "utf-8-sig", errors="replace"
                )
                archive.getinfo("gamestate")
        except (FileNotFoundError, OSError, KeyError, zipfile.BadZipFile):
            return None
        try:
            digest = sha256_file(source)
        except FileNotFoundError:
            return None
        if digest in self.archived_hashes:
            return {
                "schema": SCHEMA,
                "duplicate": True,
                "source": str(source),
                "sha256": digest,
            }
        match = GAME_DATE_PATTERN.search(metadata_text)
        game_date = match.group(1) if match else "unknown-date"
        safe_date = game_date.replace(".", "-")
        destination_directory = self.output / "saves"
        destination_directory.mkdir(parents=True, exist_ok=True)
        destination = destination_directory / (
            f"{safe_date}__{source.stem}__{digest[:12]}.sav"
        )
        temporary = destination.with_name(f".{destination.name}.{os.getpid()}.tmp")
        try:
            shutil.copy2(source, temporary)
            copied_digest = sha256_file(temporary)
        except FileNotFoundError:
            temporary.unlink(missing_ok=True)
            return None
        if copied_digest != digest:
            temporary.unlink(missing_ok=True)
            return None
        os.replace(temporary, destination)
        record = {
            "schema": SCHEMA,
            "archived_at": utc_now(),
            "source": str(source),
            "archive": str(destination),
            "size": destination.stat().st_size,
            "sha256": digest,
            "game_date": game_date,
            "stream_high_water": stream_high_water,
        }
        append_jsonl(self.output / "save_index.jsonl", record)
        self.archived_hashes.add(digest)
        return record


@dataclass
class CaptureConfig:
    commands: Path
    payloads: Path
    states: Path
    save_root: Path
    output: Path
    poll_seconds: float = 1.0
    health_seconds: float = 10.0
    save_stable_seconds: float = 8.0
    save_scan_seconds: float = 5.0
    read_budget_bytes: int = 16 * 1024 * 1024
    disk_reserve_bytes: int = 5 * 1024 * 1024 * 1024
    include_existing_newest: bool = True
    nice: int = 10
    game_pid: int | None = None
    coverage_plateau_seconds: float = 2 * 60 * 60


class LongRunCapture:
    def __init__(
        self,
        config: CaptureConfig,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self.config = config
        self.monotonic = monotonic
        self.started_at = utc_now()
        self.stop_requested = False
        self.config.output.mkdir(parents=True, exist_ok=True)
        self.state_path = self.config.output / "runtime_state.json"
        self.state = load_json(
            self.state_path,
            {
                "schema": SCHEMA,
                "started_at": self.started_at,
                "started_realtime_ns": time.time_ns(),
                "streams": {"commands": {}, "payloads": {}, "states": {}},
                "segments_archived": 0,
                "saves_archived": 0,
                "errors": [],
            },
        )
        self.started_ns = int(self.state.setdefault("started_realtime_ns", time.time_ns()))
        self.catalog = CaptureCatalog(self.config.output / "catalog.json")
        self.coverage = LiveCoverage(
            self.config.output / "coverage.json",
            self.config.coverage_plateau_seconds,
        )
        self.segment_archiver = SegmentArchiver(self.config.output, self.catalog)
        streams = self.state.setdefault("streams", {})
        self.tails = {
            "commands": ActiveStreamTail(
                "commands", self.config.commands, streams.setdefault("commands", {})
            ),
            "payloads": ActiveStreamTail(
                "payloads", self.config.payloads, streams.setdefault("payloads", {})
            ),
            "states": ActiveStreamTail(
                "states", self.config.states, streams.setdefault("states", {})
            ),
        }
        self.save_archiver = SaveArchiver(
            self.config.save_root,
            self.config.output,
            self.config.save_stable_seconds,
            self.started_ns,
            self.config.include_existing_newest,
            self.config.disk_reserve_bytes,
        )
        self.last_health = 0.0
        self.last_save_scan = 0.0
        self._write_session_metadata()

    def _write_session_metadata(self) -> None:
        session_path = self.config.output / "session.json"
        if session_path.exists():
            return
        atomic_write_json(
            session_path,
            {
                "schema": SCHEMA,
                "started_at": self.started_at,
                "manager_pid": os.getpid(),
                "commands": str(self.config.commands),
                "payloads": str(self.config.payloads),
                "states": str(self.config.states),
                "save_root": str(self.config.save_root),
                "game_pid": self.config.game_pid,
                "policy": {
                    "passive_only": True,
                    "game_thread_backpressure": False,
                    "raw_events_preserved": True,
                    "archive_compression": "gzip-level-1",
                    "coverage_plateau_seconds": self.config.coverage_plateau_seconds,
                    "coverage_never_stops_game_automatically": True,
                },
            },
        )

    def request_stop(self, *_: Any) -> None:
        self.stop_requested = True

    def stream_high_water(self) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for name, tail in self.tails.items():
            result[name] = {
                "probe_pid": tail.state.get("probe_pid"),
                "max_sequence": tail.state.get("max_sequence"),
                "max_realtime_ns": tail.state.get("max_realtime_ns"),
                "sequences_by_pid": dict(
                    tail.state.get("sequences_by_pid", {})
                ),
            }
        return result

    def _ready_segments(self, path: Path) -> list[Path]:
        return sorted(path.parent.glob(f"{path.name}.*.ready"))

    def poll_once(self) -> None:
        for tail in self.tails.values():
            tail.poll(self.config.read_budget_bytes, self.coverage.observe)
        for name, tail in self.tails.items():
            for source in self._ready_segments(tail.path):
                try:
                    summary = self.segment_archiver.process(
                        name, source, self.coverage.observe
                    )
                    if summary.max_sequence is not None:
                        pid_key = str(summary.probe_pid or "unknown")
                        sequences = tail.state.setdefault("sequences_by_pid", {})
                        sequences[pid_key] = max(
                            int(sequences.get(pid_key, 0)), summary.max_sequence
                        )
                        if summary.probe_pid == tail.state.get("probe_pid"):
                            tail.state["max_sequence"] = sequences[pid_key]
                    if summary.max_realtime_ns is not None:
                        pid_key = str(summary.probe_pid or "unknown")
                        realtime = tail.state.setdefault("realtime_by_pid", {})
                        realtime[pid_key] = max(
                            int(realtime.get(pid_key, 0)), summary.max_realtime_ns
                        )
                        if summary.probe_pid == tail.state.get("probe_pid"):
                            tail.state["max_realtime_ns"] = realtime[pid_key]
                    if (
                        summary.probe_pid is not None
                        and tail.state.get("probe_pid") is None
                    ):
                        tail.state["probe_pid"] = summary.probe_pid
                except (OSError, ValueError) as error:
                    self._record_error(f"segment:{source}:{error}")
        now = self.monotonic()
        self.state["segments_archived"] = len(self.catalog.processed_segments)
        if now - self.last_save_scan >= self.config.save_scan_seconds:
            archived = self.save_archiver.scan(now, self.stream_high_water())
            self.state["saves_archived"] = int(
                self.state.get("saves_archived", 0)
            ) + sum(1 for record in archived if not record.get("duplicate"))
            self.last_save_scan = now
        if now - self.last_health >= self.config.health_seconds:
            self.write_health()
            self.last_health = now

    def _record_error(self, message: str) -> None:
        errors = self.state.setdefault("errors", [])
        errors.append({"at": utc_now(), "message": message})
        del errors[:-50]

    def write_health(self) -> None:
        disk = shutil.disk_usage(self.config.output)
        coverage = self.coverage.write()
        self.state.update(
            {
                "schema": SCHEMA,
                "updated_at": utc_now(),
                "manager_pid": os.getpid(),
                "disk": {
                    "total": disk.total,
                    "used": disk.used,
                    "free": disk.free,
                    "reserve": self.config.disk_reserve_bytes,
                },
                "stream_high_water": self.stream_high_water(),
                "game": {
                    "pid": self.config.game_pid,
                    "alive": self.config.game_pid is not None
                    and Path(f"/proc/{self.config.game_pid}").exists(),
                },
                "coverage": {
                    "path": str(self.coverage.path),
                    "ready_for_early_review": coverage[
                        "ready_for_early_review"
                    ],
                    "missing_state_targets": coverage[
                        "missing_state_targets"
                    ],
                    "counts": coverage["counts"],
                },
            }
        )
        atomic_write_json(self.state_path, self.state)
        atomic_write_json(self.config.output / "health.json", self.state)

    def run(self) -> None:
        if self.config.nice > 0 and hasattr(os, "nice"):
            try:
                os.nice(self.config.nice)
            except OSError as error:
                self._record_error(f"nice:{error}")
        signal.signal(signal.SIGTERM, self.request_stop)
        signal.signal(signal.SIGINT, self.request_stop)
        while not self.stop_requested:
            started = self.monotonic()
            self.poll_once()
            elapsed = self.monotonic() - started
            time.sleep(max(0.05, self.config.poll_seconds - elapsed))
        self.write_health()


def default_output() -> Path:
    suffix = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    return Path.home() / "iag-captures" / suffix


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
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
    parser.add_argument(
        "--save-root",
        type=Path,
        default=Path.home()
        / ".local/share/Paradox Interactive/Stellaris/save games",
    )
    parser.add_argument("--output", type=Path, default=default_output())
    parser.add_argument("--poll-seconds", type=float, default=1.0)
    parser.add_argument("--health-seconds", type=float, default=10.0)
    parser.add_argument("--save-stable-seconds", type=float, default=8.0)
    parser.add_argument("--save-scan-seconds", type=float, default=5.0)
    parser.add_argument("--read-budget-mb", type=int, default=16)
    parser.add_argument("--disk-reserve-gb", type=int, default=5)
    parser.add_argument("--nice", type=int, default=10)
    parser.add_argument("--game-pid", type=int)
    parser.add_argument(
        "--coverage-plateau-minutes",
        type=float,
        default=120.0,
        help=(
            "Mark coverage ready for early review after all state targets have "
            "been observed and no new type/key has appeared for this long."
        ),
    )
    parser.add_argument("--no-existing-baseline", action="store_true")
    parser.add_argument(
        "--once", action="store_true", help="Poll once, write health, and exit."
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    values = parse_args(argv)
    if (
        values.poll_seconds <= 0
        or values.save_stable_seconds < 0
        or values.save_scan_seconds <= 0
        or values.coverage_plateau_minutes < 0
    ):
        raise SystemExit("poll and stability intervals must be positive")
    config = CaptureConfig(
        commands=values.commands.expanduser().resolve(),
        payloads=values.payloads.expanduser().resolve(),
        states=values.states.expanduser().resolve(),
        save_root=values.save_root.expanduser().resolve(),
        output=values.output.expanduser().resolve(),
        poll_seconds=values.poll_seconds,
        health_seconds=values.health_seconds,
        save_stable_seconds=values.save_stable_seconds,
        save_scan_seconds=values.save_scan_seconds,
        read_budget_bytes=values.read_budget_mb * 1024 * 1024,
        disk_reserve_bytes=values.disk_reserve_gb * 1024 * 1024 * 1024,
        include_existing_newest=not values.no_existing_baseline,
        nice=values.nice,
        game_pid=values.game_pid,
        coverage_plateau_seconds=values.coverage_plateau_minutes * 60,
    )
    capture = LongRunCapture(config)
    if values.once:
        capture.poll_once()
        capture.write_health()
    else:
        capture.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
