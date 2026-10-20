#!/usr/bin/env python3
"""Bounded, non-submitting SDK research alongside an existing game/runtime.

No injection, process control, gameplay submission, or verification promotion.
Native calls use the existing game-thread endpoint; process memory is read-only.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import signal
import struct
import sys
import time
import uuid
import zipfile
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "src"))

from iag.stellaris.execution.native_runtime import (
    LINUX_NATIVE_RUNTIME_BUILD_ID,
    NativeRuntimeClient,
)
from iag.stellaris.state.extract_game_state import (
    construction_item_profile,
    load_save_metadata,
)
from iag.stellaris.state.state_index import WorldStateIndex


def digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def write_new(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=True, indent=2)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())


def append(path: Path, value: object) -> None:
    with path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(value, ensure_ascii=True) + "\n")
        stream.flush()


class SessionChanged(RuntimeError):
    """Native research must not follow a new process, runtime or world."""


@dataclass(frozen=True)
class Settings:
    pid: int
    process_start_ticks: str
    world_identity: int
    binary_sha256: str
    world_global_rva: int
    date_offset: int
    layout_source: str
    baseline: str
    sdk: str
    save_root: str
    started_ns: int
    endpoint: str = "/tmp/iag-stellaris-native.sock"
    poll_seconds: float = 30.0
    max_hours: float = 12.0
    commands_per_round: int = 3
    candidates_per_command: int = 4
    cooldown_seconds: float = 600.0
    fallback_seconds: float = 1800.0
    max_backoff_seconds: float = 7200.0
    archive_limit_bytes: int = 2 * 1024**3
    disk_reserve_bytes: int = 2 * 1024**3

    def __post_init__(self) -> None:
        if (
            self.pid <= 0
            or self.world_identity <= 0
            or not 0 < self.world_global_rva < 0x10000000
            or not 0 < self.date_offset < 0x10000
            or not 10 <= self.poll_seconds <= 3600
            or not 0 < self.max_hours <= 24
            or not 1 <= self.commands_per_round <= 4
            or not 1 <= self.candidates_per_command <= 4
            or not 120 <= self.cooldown_seconds <= self.max_backoff_seconds
            or self.fallback_seconds < self.cooldown_seconds
        ):
            raise ValueError("Unsafe incremental research bounds")


class ProcessObservation:
    """Exact-build observations; never calls native functions or writes memory."""

    def __init__(self, settings: Settings, sdk: dict) -> None:
        self.s = settings
        self.process = Path("/proc") / str(settings.pid)
        executable = (self.process / "exe").resolve(strict=True)
        with executable.open("rb") as stream:
            actual = hashlib.file_digest(stream, "sha256").hexdigest()
        if actual != settings.binary_sha256:
            raise SessionChanged("Executable fingerprint changed")
        self.executable = str(executable)
        self.databases = sdk.get("object_databases", [])

    def snapshot(self, relevant_types: set[str]) -> dict:
        if (self.process / "stat").read_text().split()[
            21
        ] != self.s.process_start_ticks:
            raise SessionChanged("PID identity changed")
        mappings = (self.process / "maps").read_text().splitlines()
        bases = {
            int(line.split()[0].split("-")[0], 16)
            for line in mappings
            if line.split()[-1] == self.executable and int(line.split()[2], 16) == 0
        }
        if len(bases) != 1:
            raise SessionChanged("ELF image mapping changed")
        base = bases.pop()
        fd = os.open(self.process / "mem", os.O_RDONLY)

        def read(address: int, size: int) -> bytes:
            data = os.pread(fd, size, address)
            if len(data) != size:
                raise OSError("Short process-memory read")
            return data

        def u64(address: int) -> int:
            return struct.unpack("<Q", read(address, 8))[0]

        def u32(address: int) -> int:
            return struct.unpack("<I", read(address, 4))[0]

        try:
            world = u64(base + self.s.world_global_rva)
            if world != self.s.world_identity:
                raise SessionChanged("Loaded world changed")
            date = u32(world + self.s.date_offset)
            objects = {}
            for db in self.databases:
                cls = db["class"]
                if cls not in relevant_types:
                    continue
                try:
                    database = u64(base + db["database_rva"])
                    if database == 0:
                        objects[cls] = {"available": False}
                        continue
                    count = u32(database + 0x20)
                    entries = u64(database + 0x18)
                    if count > 1000000 or count and entries == 0:
                        raise OSError("Invalid database bounds")
                    slots = read(entries, min(count, 16384) * 16) if count else b""
                    null_object = u64(base + db["null_rva"])
                    occupied = sum(
                        struct.unpack_from("<Q", slots, i + 8)[0]
                        not in (0, null_object)
                        and struct.unpack_from("<I", slots, i)[0] != 0xFFFFFFFF
                        for i in range(0, len(slots), 16)
                    )
                    objects[cls] = {
                        "available": True,
                        "slots": count,
                        "nonnull_slots_in_scan": occupied,
                        "scan_truncated": count > 16384,
                        "slot_fingerprint": hashlib.sha256(slots).hexdigest(),
                    }
                except (OSError, OverflowError, struct.error) as error:
                    objects[cls] = {"available": False, "error": type(error).__name__}
            if u64(base + self.s.world_global_rva) != world:
                raise SessionChanged("World changed during observation")
            if u32(world + self.s.date_offset) != date:
                raise OSError("GameDate advanced during observation; defer this sample")
            return {"world_identity": world, "raw_game_date": date, "objects": objects}
        finally:
            os.close(fd)


SAVE_FAMILIES = {
    "countries": ("country",),
    "fleets": ("fleet", "ships", "fleet_template"),
    "planets": ("planets", "colony", "colonies"),
    "queues": ("construction",),
    "leaders": ("leaders", "leader"),
    "wars": ("war", "wars"),
    "community": ("galactic_community", "galactic_community_manager"),
    "situations": ("situations", "situation_manager"),
    "operations": ("espionage", "espionage_operation", "spy_network"),
    "federations": ("federation", "federations"),
}


def family_for_type(cls: str) -> str:
    if any(
        word in cls
        for word in ("Colony", "Planet", "Building", "District", "Zone", "Pop")
    ):
        return "planets"
    if "Construction" in cls:
        return "queues"
    if any(word in cls for word in ("Fleet", "Ship", "Starbase", "Army")):
        return "fleets"
    if "Leader" in cls or "CouncilPosition" in cls:
        return "leaders"
    if "Resolution" in cls:
        return "community"
    if "Federation" in cls:
        return "federations"
    if "Espionage" in cls or "SpyNetwork" in cls:
        return "operations"
    if "Situation" in cls or "Mission" in cls:
        return "situations"
    if cls == "CWar":
        return "wars"
    return "countries"


class SaveEvidence:
    def __init__(self, settings: Settings, output: Path) -> None:
        self.s, self.output = settings, output
        self.seen: dict[str, tuple[int, int, float]] = {}
        self.archived: set[tuple[str, int, int]] = set()
        self.hashes: set[str] = set()
        self.bytes = 0
        self.latest: dict = {}

    def scan(self, now: float) -> list[dict]:
        candidates = []
        for path in Path(self.s.save_root).rglob("*.sav"):
            try:
                st = path.stat()
                if (
                    st.st_mtime_ns >= self.s.started_ns
                    and (str(path), st.st_mtime_ns, st.st_size) not in self.archived
                ):
                    candidates.append((st.st_mtime_ns, path, st.st_size))
            except OSError:
                continue
        records = []
        for mtime, path, size in sorted(candidates)[:32]:
            key = str(path)
            signature = (key, mtime, size)
            if signature in self.archived:
                continue
            previous = self.seen.get(key)
            self.seen[key] = (
                mtime,
                size,
                now
                if previous is None or previous[:2] != (mtime, size)
                else previous[2],
            )
            if (
                previous is None
                or previous[:2] != (mtime, size)
                or now - previous[2] < 5
            ):
                continue
            if (
                self.bytes + size > self.s.archive_limit_bytes
                or shutil.disk_usage(self.output).free < self.s.disk_reserve_bytes
            ):
                break
            target = self.output / "saves" / f"{mtime}-{uuid.uuid4().hex}.sav"
            target.parent.mkdir(exist_ok=True)
            try:
                before = path.stat()
                with path.open("rb") as source, target.open("xb") as destination:
                    shutil.copyfileobj(source, destination, 1024 * 1024)
                after = path.stat()
                with target.open("rb") as stream:
                    sha = hashlib.file_digest(stream, "sha256").hexdigest()
                self.bytes += target.stat().st_size
                stable = (
                    (before.st_mtime_ns, before.st_size)
                    == (after.st_mtime_ns, after.st_size)
                    == (mtime, size)
                )
                record = {
                    "source": key,
                    "source_mtime_ns": mtime,
                    "size": size,
                    "archive": str(target),
                    "sha256": sha,
                    "source_stable": stable,
                    "observed_at": now,
                    "evidence_level": "save_state_only_temporal_association",
                }
                if not stable:
                    records.append(record)
                    continue
                metadata = load_save_metadata(target)
                if not metadata or metadata.get("version") != "Cygnus v4.5.2":
                    record["error"] = "save_version_unconfirmed"
                    self.archived.add(signature)
                    records.append(record)
                    continue
                record["metadata"] = metadata
                if sha not in self.hashes:
                    with zipfile.ZipFile(target) as archive:
                        if archive.getinfo("gamestate").file_size > 256 * 1024**2:
                            raise ValueError(
                                "Save facts exceed bounded decompression size"
                            )
                        text = archive.read("gamestate").decode(
                            "utf-8-sig", errors="replace"
                        )
                    index = WorldStateIndex(text)
                    facts = {}
                    for family, names in SAVE_FAMILIES.items():
                        sections = [
                            index.optional_section(name, allow_indent=True)
                            for name in names
                        ]
                        if any(sections):
                            facts[family] = digest(sections)
                    record["family_fingerprints"] = facts
                    try:
                        items = index.construction_items()
                        queue_facts = {
                            str(key): construction_item_profile(key, value)
                            for key, value in list(items.items())[:256]
                        }
                        previous = self.latest.get("construction_items", {})
                        record["construction_items"] = queue_facts
                        record["construction_items_truncated"] = len(items) > 256
                        record["queue_state_delta"] = {
                            "added": sorted(set(queue_facts) - set(previous)),
                            "removed": sorted(set(previous) - set(queue_facts)),
                            "changed": sorted(
                                key
                                for key in queue_facts.keys() & previous.keys()
                                if queue_facts[key] != previous[key]
                            ),
                            "interpretation": "state_change_only; removal_is_not_proof_of_completion_or_cancellation",
                        }
                    except ValueError as error:
                        record["construction_facts_error"] = str(error)
                    self.latest = record
                    self.hashes.add(sha)
                self.archived.add(signature)
                records.append(record)
            except (OSError, ValueError, KeyError, zipfile.BadZipFile) as error:
                records.append(
                    {
                        "source": key,
                        "archive": str(target),
                        "error": f"{type(error).__name__}:{error}",
                        "evidence_level": "untrusted_save_copy",
                    }
                )
            if len(records) >= 1:
                break
        return records


@dataclass
class Pending:
    name: str
    status: str
    dependencies: tuple[str, ...]
    missing_type: str | None
    baseline_date: int | None
    candidate_count: int
    last_attempt: float
    last_date: int | None = None
    last_signature: str | None = None
    cursor: int = 0
    no_progress_rounds: int = 0
    attempts: int = 0
    positive: bool = False
    quarantined: bool = False


def pending_commands(baseline: dict, sdk: dict) -> list[Pending]:
    descriptions = {c["class"]: c for c in sdk["commands"]}
    finished = datetime.fromisoformat(baseline["finished_at"]).timestamp()
    pending = []
    for row in baseline["commands"]:
        if row["status"] not in {"native_invalid", "missing_parameters"}:
            continue
        attempts = row["attempts"]
        if not attempts:
            continue
        command = descriptions.get(attempts[0]["class_name"])
        if command is None:
            continue
        fields = command.get("population_fields", command["fields"])
        refs = tuple(sorted({f["ref"] for f in fields if f.get("ref")}))
        missing = (
            row["reason"].split(":", 1)[1]
            if row["reason"].startswith("no_live_candidate:")
            else None
        )
        dates = [
            a["game_date_after"]
            for a in attempts
            if a.get("game_date_after") is not None
        ]
        pending.append(
            Pending(
                row["command_name"],
                row["status"],
                refs,
                missing,
                max(dates) if dates else None,
                max(1, max(a["candidate_count"] for a in attempts)),
                finished,
            )
        )
    return pending


def select_due(
    pending: list[Pending], snapshot: dict, save: dict, now: float, settings: Settings
) -> list[tuple[Pending, str]]:
    due = []
    date = snapshot.get("raw_game_date")
    for item in pending:
        if item.positive or item.quarantined or date is None:
            continue
        previous_date = (
            item.last_date if item.last_date is not None else item.baseline_date
        )
        if previous_date is not None and date <= previous_date:
            continue
        objects = snapshot.get("objects", {})
        if item.missing_type:
            obj = objects.get(item.missing_type, {})
            if not obj.get("available") or not obj.get("nonnull_slots_in_scan"):
                continue
        signature = digest(
            {
                "objects": {t: objects.get(t) for t in item.dependencies},
                "save": {
                    family_for_type(t): save.get("family_fingerprints", {}).get(
                        family_for_type(t)
                    )
                    for t in item.dependencies
                },
            }
        )
        backoff = min(
            settings.max_backoff_seconds,
            settings.cooldown_seconds * 2 ** min(item.no_progress_rounds, 4),
        )
        elapsed = now - item.last_attempt
        changed = signature != item.last_signature
        if (
            elapsed < backoff
            or not changed
            and elapsed < max(backoff, settings.fallback_seconds)
        ):
            continue
        due.append((item, signature))
    due.sort(
        key=lambda pair: (
            pair[0].missing_type is None,
            pair[0].attempts,
            pair[0].last_attempt,
            pair[0].name,
        )
    )
    return due[: settings.commands_per_round]


class IncrementalRun:
    def __init__(self, settings: Settings, output: Path, client=None) -> None:
        self.s, self.output = settings, output
        self.baseline = json.loads(Path(settings.baseline).read_text())
        self.sdk = json.loads(Path(settings.sdk).read_text())
        if (
            self.baseline["build_id"] != LINUX_NATIVE_RUNTIME_BUILD_ID
            or self.sdk["build_id"] != self.baseline["build_id"]
        ):
            raise ValueError("Incremental inputs must match the exact live Linux build")
        if (
            self.baseline["process_id"] != settings.pid
            or self.baseline["world_identity"] != settings.world_identity
        ):
            raise ValueError("Baseline process/world does not match")
        self.client = client or NativeRuntimeClient(settings.endpoint)
        self.pending = pending_commands(self.baseline, self.sdk)
        self.catalog = None
        self.native_suspended: str | None = None
        self.round_number = 0
        self.total_calls = 0
        self.request_sequence = 0
        self.last_observation: str | None = None
        self.countries = {
            a["country_id"]
            for row in self.baseline["commands"]
            for a in row["attempts"]
            if a.get("native_is_valid") is not None
        }
        if len(self.countries) != 1:
            raise ValueError("Baseline must have one reviewed actor")
        self.country = self.countries.pop()

    def health(self) -> None:
        catalog = self.client.describe_recovered_commands(
            request_id=f"inc-health-{uuid.uuid4().hex}"
        )
        if (
            catalog.process_id != self.s.pid
            or catalog.instance_id != self.baseline["instance_id"]
            or catalog.probe_revision < 2
            or catalog.build_id != self.baseline["build_id"]
        ):
            raise SessionChanged("Runtime session identity changed")
        if catalog.commands != tuple(
            row["command_name"] for row in self.baseline["commands"]
        ):
            raise SessionChanged("Catalog no longer agrees with the reviewed baseline")
        if self.catalog is not None and catalog != self.catalog:
            raise SessionChanged("Runtime catalog changed")
        self.catalog = catalog

    def probe_round(self, snapshot: dict, save: dict, now: float) -> dict:
        self.round_number += 1
        directory = (
            self.output / "rounds" / f"{self.round_number:06d}-{uuid.uuid4().hex}"
        )
        directory.mkdir(parents=True, exist_ok=False)
        write_new(
            directory / "observation.json",
            {
                "observed_at": now,
                "snapshot": snapshot,
                "save": save,
                "save_association": "temporal_only_not_a_native_command_capture",
            },
        )
        observation_signal = digest(snapshot)
        selected = (
            select_due(self.pending, snapshot, save, now, self.s)
            if observation_signal != self.last_observation
            else []
        )
        self.last_observation = observation_signal
        completed = []
        if selected and not self.native_suspended:
            self.health()
        for item, signature in selected:
            if self.native_suspended:
                break
            item.last_attempt, item.last_date, item.last_signature = (
                now,
                snapshot["raw_game_date"],
                signature,
            )
            item.attempts += 1
            results = []
            for _ in range(min(self.s.candidates_per_command, item.candidate_count)):
                candidate = item.cursor % item.candidate_count
                self.request_sequence += 1
                request = f"inc-{self.s.pid}-{uuid.uuid4().hex}"
                started = {
                    "event": "started",
                    "request_id": request,
                    "command_name": item.name,
                    "candidate_index": candidate,
                    "round": self.round_number,
                }
                append(self.output / "requests.jsonl", started)
                try:
                    result = self.client.validate_recovered_command(
                        request_id=request,
                        command_name=item.name,
                        country_id=self.country,
                        candidate_index=candidate,
                    )
                except (OSError, RuntimeError, ValueError) as error:
                    append(
                        self.output / "requests.jsonl",
                        {
                            **started,
                            "event": "interrupted_no_replay",
                            "error": f"{type(error).__name__}:{error}",
                        },
                    )
                    write_new(
                        directory / f"{item.name}.json",
                        {
                            "results": results,
                            "interrupted": True,
                            "pending_request_id": request,
                        },
                    )
                    raise
                value = result.model_dump(mode="json")
                append(
                    self.output / "requests.jsonl",
                    {**started, "event": "completed", "result": value},
                )
                results.append(value)
                self.total_calls += result.native_is_valid is not None
                if (
                    result.world_identity
                    and result.world_identity != self.s.world_identity
                ):
                    self.native_suspended = "world_changed_during_native_request"
                    break
                if (
                    result.status == "call_exception"
                    or result.reason == "native_factory_vtable_mismatch"
                ):
                    self.native_suspended = "unsafe_native_call_requires_future_review"
                    item.quarantined = True
                    break
                if result.native_is_valid is True:
                    item.positive = True
                    break
                if result.status == "structure_failed":
                    item.quarantined = True
                    break
                if result.status != "native_invalid":
                    break
                item.candidate_count = max(1, result.candidate_count)
                item.cursor = (candidate + 1) % item.candidate_count
                time.sleep(0.1)
            if not item.positive:
                item.no_progress_rounds += 1
            write_new(
                directory / f"{item.name}.json",
                {
                    "results": results,
                    "ever_positive": item.positive,
                    "production_verification_unchanged": True,
                },
            )
            completed.append(
                {
                    "command_name": item.name,
                    "attempts": len(results),
                    "positive": item.positive,
                }
            )
        report = {
            "round": self.round_number,
            "selected": len(selected),
            "completed": completed,
            "new_positive_commands": sum(p.positive for p in self.pending),
            "total_native_calls": self.total_calls,
            "native_suspended": self.native_suspended,
            "paired_capture_promotions": 0,
            "capture_status": "no_current_version_passive_command_capture_attached",
            "submitted": False,
        }
        write_new(directory / "report.json", report)
        return report

    def checkpoint(self, reason: str) -> None:
        write_new(
            self.output / "checkpoints" / f"{time.time_ns()}-{uuid.uuid4().hex}.json",
            {
                "reason": reason,
                "round": self.round_number,
                "total_calls": self.total_calls,
                "pending": [asdict(p) for p in self.pending],
                "native_suspended": self.native_suspended,
                "last_observation": self.last_observation,
                "resume_policy": "load_into_a_new_output_directory_never_replay_pending_requests",
                "settings": asdict(self.s),
            },
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--resume", type=Path)
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    settings = Settings(**json.loads(args.config.read_text()))
    args.output.mkdir(parents=True, exist_ok=False)
    run = IncrementalRun(settings, args.output)
    window_started = datetime.now(UTC).isoformat()
    if args.resume:
        old = json.loads(args.resume.read_text())
        if old["settings"] != asdict(settings):
            raise ValueError("Resume configuration differs from the saved session")
        run.pending = [
            Pending(**{**p, "dependencies": tuple(p["dependencies"])})
            for p in old["pending"]
        ]
        run.total_calls = old["total_calls"]
        run.native_suspended = old["native_suspended"]
        run.last_observation = old.get("last_observation")
        old_output = args.resume.parent.parent
        original_run = json.loads((old_output / "run.json").read_text())
        window_started = original_run.get(
            "window_started_at", original_run["started_at"]
        )
        if run.last_observation is None:
            previous_observations = sorted(
                (old_output / "rounds").glob("*/observation.json")
            )
            if previous_observations:
                previous = json.loads(previous_observations[-1].read_text())
                run.last_observation = digest(previous["snapshot"])
    write_new(
        args.output / "run.json",
        {
            "schema_version": "iag.incremental_sdk_validation.v1",
            "pid": os.getpid(),
            "started_at": datetime.now(UTC).isoformat(),
            "window_started_at": window_started,
            "settings": asdict(settings),
            "baseline_counts": run.baseline["summary"],
            "eligible_pending_commands": len(run.pending),
            "static_blocked_commands_not_retested": sum(
                c["status"] == "not_tested" for c in run.baseline["commands"]
            ),
            "submitted": False,
            "capture_promotions": 0,
        },
    )
    observer = None
    saves = SaveEvidence(settings, args.output)
    if args.resume:
        old_output = args.resume.parent.parent
        old_index = old_output / "save_index.jsonl"
        if old_index.is_file():
            for line in old_index.read_text().splitlines():
                record = json.loads(line)
                if record.get("source_stable") and record.get("sha256"):
                    saves.hashes.add(record["sha256"])
                    saves.archived.add(
                        (record["source"], record["source_mtime_ns"], record["size"])
                    )
                    saves.bytes += record["size"]
                    if record.get("family_fingerprints"):
                        saves.latest = record
    relevant = {t for p in run.pending for t in p.dependencies}
    stopping = False

    def stop(_signum, _frame) -> None:
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    remaining = (
        datetime.fromisoformat(window_started).timestamp()
        + settings.max_hours * 3600
        - time.time()
    )
    deadline = time.monotonic() + max(0, remaining)
    failures = 0
    while (
        not stopping
        and time.monotonic() < deadline
        and not (args.output / "STOP").exists()
    ):
        begin, cpu = time.monotonic(), time.process_time()
        now = time.time()
        try:
            for record in saves.scan(now):
                append(args.output / "save_index.jsonl", record)
            if observer is None:
                observer = ProcessObservation(settings, run.sdk)
            snapshot = observer.snapshot(relevant)
            report = run.probe_round(snapshot, saves.latest, now)
            failures = 0
            append(
                args.output / "activity.jsonl",
                {
                    "observed_at": now,
                    "raw_game_date": snapshot["raw_game_date"],
                    "report": report,
                    "observer_cpu_seconds": time.process_time() - cpu,
                    "cycle_elapsed_seconds": time.monotonic() - begin,
                    "archived_save_bytes": saves.bytes,
                },
            )
        except SessionChanged as error:
            run.native_suspended = f"session_changed:{error}"
            failures += 1
            append(
                args.output / "activity.jsonl",
                {
                    "observed_at": now,
                    "event": "native_research_suspended",
                    "error": str(error),
                },
            )
        except (OSError, RuntimeError, ValueError) as error:
            failures += 1
            append(
                args.output / "activity.jsonl",
                {
                    "observed_at": now,
                    "event": "transient_observation_failure",
                    "error": f"{type(error).__name__}:{error}",
                    "consecutive_failures": failures,
                },
            )
        run.checkpoint("cycle_finished_or_deferred")
        if args.once:
            break
        delay = min(900.0, settings.poll_seconds * 2 ** min(failures, 5))
        until = time.monotonic() + delay
        while not stopping and time.monotonic() < until:
            time.sleep(min(1, max(0, until - time.monotonic())))
    run.checkpoint("safe_stop")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
