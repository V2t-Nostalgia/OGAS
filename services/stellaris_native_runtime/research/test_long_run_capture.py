from __future__ import annotations

import gzip
import json
import tempfile
import unittest
import zipfile
from pathlib import Path

try:
    from services.stellaris_native_runtime.research.long_run_capture import (
        ActiveStreamTail,
        CaptureCatalog,
        LiveCoverage,
        SaveArchiver,
        SegmentArchiver,
        layout_signature,
    )
except ModuleNotFoundError:
    from long_run_capture import (  # type: ignore[no-redef]
        ActiveStreamTail,
        CaptureCatalog,
        LiveCoverage,
        SaveArchiver,
        SegmentArchiver,
        layout_signature,
    )


def write_jsonl(path: Path, values: list[dict[str, object]]) -> None:
    path.write_text(
        "".join(json.dumps(value) + "\n" for value in values),
        encoding="utf-8",
    )


class SegmentArchiverTests(unittest.TestCase):
    def test_layout_signature_tracks_structure_not_parameter_bytes(self) -> None:
        first = layout_signature(
            {
                "schema": "test.v1",
                "kind": "command",
                "known_command_size": 8,
                "known_command_hex": "0102030405060708",
                "sequence": 1,
                "target": {"id": 7},
            }
        )
        second = layout_signature(
            {
                "schema": "test.v1",
                "kind": "command",
                "known_command_size": 8,
                "known_command_hex": "ffffffffffffffff",
                "sequence": 2,
                "target": {"id": 99},
            }
        )
        self.assertEqual(first["fingerprint"], second["fingerprint"])

    def test_archives_raw_segment_and_builds_idempotent_catalog(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "capture"
            source = root / "commands.jsonl.42.000001.ready"
            values = [
                {
                    "schema": "iag.stellaris.command_probe.v2",
                    "kind": "probe_started",
                    "pid": 42,
                },
                {
                    "kind": "command",
                    "sequence": 7,
                    "phase": "session_post",
                    "realtime_ns": 100,
                    "command_type": "CBuildStarbaseCommand",
                    "caller": "stellaris+0x123",
                    "nested_type": "",
                    "dropped_before": 0,
                    "writer_dropped_before": 0,
                    "first_seen_stack": ["stellaris+0x238ebc5"],
                },
            ]
            write_jsonl(source, values)
            catalog = CaptureCatalog(output / "catalog.json")
            archiver = SegmentArchiver(output, catalog)

            summary = archiver.process("commands", source)

            self.assertEqual(summary.probe_pid, 42)
            self.assertEqual(summary.max_sequence, 7)
            self.assertFalse(source.exists())
            archives = list((output / "segments" / "commands").glob("*.gz"))
            self.assertEqual(len(archives), 1)
            with gzip.open(archives[0], "rt", encoding="utf-8") as stream:
                self.assertIn("CBuildStarbaseCommand", stream.read())
            command = catalog.data["command_types"]["CBuildStarbaseCommand"]
            self.assertEqual(command["phases"], {"session_post": 1})
            self.assertTrue(command["ai_origin_observed"])
            self.assertEqual(len(command["layout_signatures"]), 1)
            self.assertEqual(command["layout_signatures"][0]["count"], 1)

            write_jsonl(source, values)
            archiver.process("commands", source)
            self.assertEqual(
                catalog.data["command_types"]["CBuildStarbaseCommand"]["phases"],
                {"session_post": 1},
            )

    def test_counts_pipe_and_writer_drops(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "capture"
            source = root / "payloads.jsonl.42.000001.ready"
            write_jsonl(
                source,
                [
                    {"kind": "probe_started", "pid": 42},
                    {
                        "kind": "buildable",
                        "sequence": 3,
                        "object_type": "CShipDesign",
                        "dropped_before": 2,
                        "writer_dropped_before": 5,
                    },
                ],
            )
            catalog = CaptureCatalog(output / "catalog.json")
            summary = SegmentArchiver(output, catalog).process("payloads", source)
            self.assertEqual(summary.dropped, 2)
            self.assertEqual(summary.writer_dropped, 5)
            self.assertEqual(catalog.data["totals"]["dropped"], 2)
            self.assertEqual(catalog.data["totals"]["writer_dropped"], 5)

    def test_catalogs_event_situation_and_chain_state(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "capture"
            source = root / "states.jsonl.42.000001.ready"
            write_jsonl(
                source,
                [
                    {"kind": "probe_started", "pid": 42},
                    {
                        "kind": "event_executed",
                        "sequence": 1,
                        "event_definition_id": 17,
                        "event_or_type_key": "test.17",
                        "title_key": "test_title",
                        "description_key": "test_desc",
                        "content_included": True,
                        "options": [{"option_index": 0, "text_key": "test_ok"}],
                    },
                    {
                        "kind": "situation_stage_changed",
                        "sequence": 2,
                        "situation_id": 8,
                        "event_or_type_key": "situation_test",
                        "approach_key": "approach_fast",
                    },
                    {
                        "kind": "situation_destroyed",
                        "sequence": 3,
                        "situation_id": 8,
                        "event_or_type_key": "",
                    },
                    {
                        "kind": "event_chain_started",
                        "sequence": 4,
                        "event_chain_definition_id": 4,
                        "event_or_type_key": "chain_test",
                    },
                ],
            )
            catalog = CaptureCatalog(output / "catalog.json")

            SegmentArchiver(output, catalog).process("states", source)

            self.assertEqual(catalog.data["totals"]["state_records"], 4)
            event = catalog.data["event_definitions"]["test.17"]
            self.assertTrue(event["content_observed"])
            self.assertEqual(event["option_keys"], ["test_ok"])
            self.assertIn("situation_test", catalog.data["situation_types"])
            self.assertEqual(
                catalog.data["situation_types"]["situation_test"]["kinds"],
                {"situation_stage_changed": 1, "situation_destroyed": 1},
            )
            self.assertIn("chain_test", catalog.data["event_chains"])


class LiveCoverageTests(unittest.TestCase):
    def test_reports_missing_targets_then_plateau_readiness(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            coverage = LiveCoverage(Path(directory) / "coverage.json", 60.0)
            realtime_ns = 1_000_000_000
            coverage.observe(
                "commands",
                {
                    "kind": "command",
                    "command_type": "CSelectEventOptionCommand",
                    "nested_type": "CDeclareWarAction",
                    "realtime_ns": realtime_ns,
                },
            )
            coverage.observe(
                "payloads",
                {
                    "kind": "fleet_order",
                    "object_type": "CMoveOrder",
                    "realtime_ns": realtime_ns,
                },
            )
            coverage.observe(
                "states",
                {
                    "kind": "event_executed",
                    "event_or_type_key": "test.1",
                    "content_included": True,
                    "options": [{"text_key": "test_ok"}],
                    "realtime_ns": realtime_ns,
                },
            )
            for kind in LiveCoverage.STATE_TARGETS:
                if kind in {"event_executed", "event_content", "event_options"}:
                    continue
                coverage.observe(
                    "states",
                    {
                        "kind": kind,
                        "event_or_type_key": f"key_{kind}",
                        "realtime_ns": realtime_ns,
                    },
                )

            early = coverage.snapshot(now_realtime_ns=30_000_000_000)
            ready = coverage.snapshot(now_realtime_ns=62_000_000_000)

            self.assertFalse(early["ready_for_early_review"])
            self.assertEqual(ready["missing_state_targets"], [])
            self.assertTrue(ready["ready_for_early_review"])
            self.assertEqual(ready["counts"]["command_types"], 1)
            self.assertEqual(ready["counts"]["event_content_keys"], 1)


class ActiveStreamTailTests(unittest.TestCase):
    def test_preserves_partial_line_until_complete(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "commands.jsonl"
            path.write_bytes(
                b'{"kind":"probe_started","pid":9}\n'
                b'{"kind":"command","sequence":1'
            )
            state: dict[str, object] = {}
            tail = ActiveStreamTail("commands", path, state)
            tail.poll(4096)
            first_offset = int(state["offset"])
            self.assertEqual(state["probe_pid"], 9)
            self.assertEqual(state["max_sequence"], 0)

            with path.open("ab") as stream:
                stream.write(b',"realtime_ns":12}\n')
            tail.poll(4096)
            self.assertGreater(int(state["offset"]), first_offset)
            self.assertEqual(state["max_sequence"], 1)
            self.assertEqual(state["max_realtime_ns"], 12)

    def test_tracks_restarted_probe_sequences_per_pid(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "commands.jsonl"
            write_jsonl(
                path,
                [
                    {"kind": "probe_started", "pid": 9},
                    {"kind": "command", "sequence": 90, "realtime_ns": 100},
                    {"kind": "probe_started", "pid": 10},
                    {"kind": "command", "sequence": 2, "realtime_ns": 200},
                ],
            )
            state: dict[str, object] = {}
            ActiveStreamTail("commands", path, state).poll(4096)
            self.assertEqual(state["probe_pid"], 10)
            self.assertEqual(state["max_sequence"], 2)
            self.assertEqual(state["sequences_by_pid"], {"9": 90, "10": 2})


class SaveArchiverTests(unittest.TestCase):
    @staticmethod
    def make_save(path: Path, date: str = "2200.02.01") -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr("meta", f'date="{date}"\nname="test"\n')
            archive.writestr("gamestate", "country={}\n")

    def test_archives_stable_save_with_stream_high_water(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            save = root / "saves" / "campaign" / "autosave.sav"
            output = root / "capture"
            self.make_save(save)
            archiver = SaveArchiver(
                save.parent.parent,
                output,
                stable_seconds=1.0,
                session_started_ns=0,
                include_existing_newest=True,
                disk_reserve_bytes=0,
            )
            self.assertEqual(archiver.scan(1.0, {}), [])
            records = archiver.scan(
                2.1,
                {"commands": {"probe_pid": 9, "max_sequence": 77}},
            )
            self.assertEqual(len(records), 1)
            self.assertEqual(records[0]["game_date"], "2200.02.01")
            self.assertEqual(
                records[0]["stream_high_water"]["commands"]["max_sequence"],
                77,
            )
            self.assertTrue(Path(records[0]["archive"]).is_file())

    def test_incomplete_save_is_never_archived(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            save = root / "autosave.sav"
            save.write_bytes(b"not a complete save")
            archiver = SaveArchiver(
                root,
                root / "capture",
                stable_seconds=0,
                session_started_ns=0,
                include_existing_newest=True,
                disk_reserve_bytes=0,
            )
            archiver.scan(1.0, {})
            self.assertEqual(archiver.scan(2.0, {}), [])

    def test_disappearing_rotating_save_does_not_stop_capture(self) -> None:
        class VanishingSaveRoot:
            def __init__(self, path: Path) -> None:
                self.path = path

            def exists(self) -> bool:
                return True

            def rglob(self, pattern: str):
                self.assert_pattern(pattern)
                return iter((self.path / "autosave.sav",))

            @staticmethod
            def assert_pattern(pattern: str) -> None:
                if pattern != "*.sav":
                    raise AssertionError(pattern)

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archiver = SaveArchiver(
                VanishingSaveRoot(root),  # type: ignore[arg-type]
                root / "capture",
                stable_seconds=0,
                session_started_ns=0,
                include_existing_newest=False,
                disk_reserve_bytes=0,
            )
            self.assertEqual(archiver.scan(1.0, {}), [])


if __name__ == "__main__":
    unittest.main()
