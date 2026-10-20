from __future__ import annotations

import json
import ast
import tempfile
import time
import unittest
import zipfile
from pathlib import Path

from services.stellaris_native_runtime.research.observe_dashboard.capture_adapter import (
    CaptureStatusReader,
)
from services.stellaris_native_runtime.research.observe_dashboard.mod_inventory import (
    ModInventoryCollector,
    read_save_mod_evidence,
)
from services.stellaris_native_runtime.research.observe_dashboard.overhead_benchmark import (
    compare_reports,
)
from services.stellaris_native_runtime.research.observe_dashboard.perf_parser import (
    aggregate_samples,
    build_diff_flame_tree,
    build_flame_tree,
    parse_perf_script,
)
from services.stellaris_native_runtime.research.observe_dashboard.profiler import (
    ProfilerConfig,
    ProfilerController,
)
from services.stellaris_native_runtime.research.observe_dashboard.storage import (
    ObservationStore,
)


PERF_SCRIPT = """\
stellaris 100/101 1234.100000: cpu-clock:u: 7f001 CCountryAI::Think() (stellaris)
        7f001 CCountryAI::Think() (stellaris)
        7f002 CGameState::ProcessAI() (stellaris)
        7f003 CGameState::Update() (stellaris)

AI Worker 100/102 1234.120000: cpu-clock:u: 7f004 CPathFinder::Search() (stellaris)
        7f004 CPathFinder::Search() (stellaris)
        7f002 CGameState::ProcessAI() (stellaris)
        7f003 CGameState::Update() (stellaris)

"""


class PerfParserTests(unittest.TestCase):
    def test_parses_threads_and_builds_real_stack_hierarchy(self) -> None:
        samples = parse_perf_script(PERF_SCRIPT)
        self.assertEqual(len(samples), 2)
        self.assertEqual(samples[0].tid, 101)
        self.assertEqual(samples[0].frames[0].symbol, "CGameState::Update()")
        self.assertEqual(samples[0].frames[-1].symbol, "CCountryAI::Think()")

        aggregate = aggregate_samples(
            samples, frequency_hz=50, duration_seconds=1.0
        )
        self.assertEqual(aggregate["sample_count"], 2)
        self.assertFalse(aggregate["call_counts_available"])
        self.assertEqual(aggregate["views"]["workers"]["sample_count"], 2)
        common = next(
            value
            for value in aggregate["views"]["all"]["hotspots"]
            if value["symbol"] == "CGameState::ProcessAI()"
        )
        self.assertEqual(common["inclusive_samples"], 2)
        self.assertEqual(common["self_samples"], 0)
        self.assertIsNone(common["actual_call_count"])
        tree = build_flame_tree(aggregate)
        self.assertEqual(tree["samples"], 2)
        self.assertEqual(tree["children"][0]["name"], "CGameState::Update()")

    def test_builds_differential_flame_tree(self) -> None:
        before = aggregate_samples(
            parse_perf_script(PERF_SCRIPT.split("AI Worker", 1)[0]),
            frequency_hz=50,
            duration_seconds=1,
        )
        after = aggregate_samples(
            parse_perf_script(PERF_SCRIPT), frequency_hz=50, duration_seconds=1
        )
        tree = build_diff_flame_tree(before, after)
        self.assertEqual(tree["baseline_samples"], 1)
        self.assertEqual(tree["comparison_samples"], 2)
        self.assertEqual(tree["delta_samples"], 1)


class ArchitectureBoundaryTests(unittest.TestCase):
    def test_observer_package_does_not_import_execution_or_injection_layers(self) -> None:
        root = Path(__file__).with_name("observe_dashboard")
        forbidden = (
            "iag.stellaris.execution",
            "inject_passive_probes",
            "observer_takeover",
            "ctypes",
        )
        for path in root.glob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            imports: list[str] = []
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    imports.extend(alias.name for alias in node.names)
                elif isinstance(node, ast.ImportFrom) and node.module:
                    imports.append(node.module)
            for name in imports:
                self.assertFalse(
                    name.startswith(forbidden),
                    f"{path.name} crosses the read-only research boundary: {name}",
                )


class CaptureAdapterTests(unittest.TestCase):
    def test_reads_compact_state_and_reports_baseline_diff_and_backlog(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            stream = root / "commands.jsonl"
            stream.write_text("1234567890", encoding="ascii")
            (root / "commands.jsonl.1.ready").write_bytes(b"ready")
            (root / "session.json").write_text(
                json.dumps(
                    {
                        "commands": str(stream),
                        "payloads": str(root / "payloads.jsonl"),
                        "states": str(root / "states.jsonl"),
                    }
                ),
                encoding="utf-8",
            )
            (root / "health.json").write_text(
                json.dumps(
                    {
                        "updated_at": "2099-01-01T00:00:00Z",
                        "streams": {"commands": {"offset": 4, "max_sequence": 9}},
                    }
                ),
                encoding="utf-8",
            )
            (root / "catalog.json").write_text(
                json.dumps(
                    {
                        "totals": {"command_records": 12, "dropped": 0},
                        "command_types": {
                            "CMoveFleetCommand": {"nested_types": ["CMoveOrder"]},
                            "CAddBuildableToQueueCommand": {
                                "nested_types": ["CBuildableBuilding"],
                                "phases": {"session_post": 3},
                            },
                            "CModCommand": {"nested_types": ["CModOrder"]},
                        },
                        "payload_types": {"CModObject": {}},
                    }
                ),
                encoding="utf-8",
            )
            baseline = root / "baseline.json"
            baseline.write_text(
                json.dumps(
                    {
                        "command_types": {
                            "CMoveFleetCommand": {"nested_types": ["CMoveOrder"]},
                            "CAddBuildableToQueueCommand": {
                                "nested_types": ["CBuildableBuilding"]
                            },
                        },
                        "payload_types": {},
                    }
                ),
                encoding="utf-8",
            )
            (root / "coverage.json").write_text(
                json.dumps({"counts": {"nested_types": 2}}), encoding="utf-8"
            )
            (root / "save_index.jsonl").write_text(
                json.dumps({"game_date": "2300.01.01", "archive": "x.sav"}) + "\n",
                encoding="utf-8",
            )

            result = CaptureStatusReader(root, baseline).snapshot()

            self.assertTrue(result["available"])
            self.assertEqual(result["game_date"], "2300.01.01")
            self.assertEqual(result["backlog"]["ready_segments"], 1)
            self.assertEqual(result["backlog"]["unread_bytes"], 6)
            self.assertEqual(result["command_diff"]["new_command_types"], ["CModCommand"])
            self.assertEqual(result["command_diff"]["new_nested_types"], ["CModOrder"])
            self.assertEqual(result["source_semantics"]["causal_mod_attribution"], "unknown")
            self.assertTrue(
                result["native_content_family_evidence"]["building"]["observed"]
            )


class ModInventoryTests(unittest.TestCase):
    def test_distinguishes_launcher_files_and_save_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            user_data = root / "user"
            mod_root = root / "workshop" / "42"
            descriptor = user_data / "mod" / "ugc_42.mod"
            descriptor.parent.mkdir(parents=True)
            mod_root.joinpath("common", "buildings").mkdir(parents=True)
            mod_root.joinpath("events").mkdir(parents=True)
            mod_root.joinpath("common", "buildings", "test.txt").write_text(
                "mod_building = { cost = { minerals = 100 } }\n", encoding="utf-8"
            )
            mod_root.joinpath("events", "test.txt").write_text(
                "namespace = mod\ncountry_event = { id = mod.1 }\n", encoding="utf-8"
            )
            descriptor.write_text(
                f'name="Test Mod"\npath="{mod_root.as_posix()}"\nremote_file_id="42"\n',
                encoding="utf-8",
            )
            user_data.joinpath("dlc_load.json").write_text(
                json.dumps({"enabled_mods": ["mod/ugc_42.mod"], "disabled_dlcs": []}),
                encoding="utf-8",
            )
            capture = root / "capture"
            capture.mkdir()
            save = capture / "saves" / "test.sav"
            save.parent.mkdir()
            with zipfile.ZipFile(save, "w") as archive:
                archive.writestr(
                    "meta",
                    'version="4.4.6"\ndate="2300.01.01"\nmods={\n"mod/ugc_42.mod"\n}\n',
                )
            capture.joinpath("save_index.jsonl").write_text(
                json.dumps({"archive": str(save)}) + "\n", encoding="utf-8"
            )

            inventory = ModInventoryCollector(user_data, capture_root=capture).collect()

            self.assertEqual(inventory["mods"][0]["name"], "Test Mod")
            self.assertEqual(
                inventory["launcher_configuration"]["enabled_mods_in_load_order"],
                ["mod/ugc_42.mod"],
            )
            self.assertEqual(inventory["save_evidence"]["declared_mods"], ["mod/ugc_42.mod"])
            self.assertFalse(inventory["actual_loaded_definitions"]["available"])
            definitions = inventory["mods"][0]["external_definitions"]
            self.assertEqual(definitions["counts"]["building"], 1)
            self.assertEqual(definitions["counts"]["event"], 1)
            self.assertFalse(definitions["engine_loaded"])

    def test_save_reader_refuses_to_imply_runtime_definitions(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            save = Path(directory) / "a.sav"
            with zipfile.ZipFile(save, "w") as archive:
                archive.writestr("meta", 'mods={"mod/a.mod"}\n')
            result = read_save_mod_evidence(save)
            self.assertTrue(result["available"])
            self.assertEqual(result["provenance"], "save_meta")


class StoreAndControllerTests(unittest.TestCase):
    def test_store_retains_flame_and_historical_progress(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = ObservationStore(Path(directory), max_raw_bytes=1024)
            status = {
                "observed_at": "2026-01-01T00:00:00Z",
                "process": {"pid": 1, "cpu_percent": 20, "rss_bytes": 3, "thread_count": 1, "host": {}},
                "capture": {
                    "game_date": "2200.01.01",
                    "game_date_ordinal": 2200 * 360,
                    "totals": {},
                    "backlog": {},
                },
                "game_progress": {},
                "profiler": {"state": "stopped"},
            }
            store.record_status(status, 100.0)
            status["capture"]["game_date"] = "2201.01.01"
            status["capture"]["game_date_ordinal"] = 2201 * 360
            store.record_status(status, 200.0)
            self.assertAlmostEqual(store.game_progress(2201 * 360)["seconds_per_game_year"], 100.0)
            aggregate = aggregate_samples(
                parse_perf_script(PERF_SCRIPT), frequency_hz=50, duration_seconds=1
            )
            raw = store.raw_root / "x.perf.data"
            raw.write_bytes(b"raw")
            store.store_perf_window(
                {
                    "id": "x",
                    "pid": 1,
                    "started_epoch": 1.0,
                    "ended_epoch": 2.0,
                    "started_at": "a",
                    "ended_at": "b",
                    "game_date": "2201.01.01",
                    "context": {},
                },
                aggregate,
                raw,
            )
            self.assertEqual(store.flame("x")["samples"], 2)
            self.assertTrue(store.hotspot_history()["series"])
            store.close()

    def test_overhead_comparison_keeps_missing_progress_explicit(self) -> None:
        value = compare_reports(
            [
                {
                    "label": "observe",
                    "game": {"cpu_percent_mean": 100.0},
                    "progress": {"seconds_per_game_year": 20.0},
                },
                {
                    "label": "observe_perf",
                    "game": {"cpu_percent_mean": 104.0},
                    "progress": {"seconds_per_game_year": 21.0},
                },
                {
                    "label": "observe_perf_web",
                    "game": {"cpu_percent_mean": 105.0},
                    "progress": {"seconds_per_game_year": None},
                },
            ]
        )
        perf = next(
            item
            for item in value["comparisons_to_observe"]
            if item["label"] == "observe_perf"
        )
        web = next(
            item
            for item in value["comparisons_to_observe"]
            if item["label"] == "observe_perf_web"
        )
        self.assertEqual(perf["game_cpu_delta_percent_points"], 4.0)
        self.assertEqual(perf["seconds_per_game_year_delta_percent"], 5.0)
        self.assertIsNone(web["seconds_per_game_year_delta"])

    def test_unavailable_profiler_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = ObservationStore(Path(directory))
            controller = ProfilerController(
                store,
                lambda: 123,
                lambda: {},
                ProfilerConfig(window_seconds=0.5, interval_seconds=0.5),
                {"available": False, "reason": "permission denied", "perf_path": "perf"},
            )
            result = controller.start()
            self.assertEqual(result["state"], "unavailable")
            self.assertIn("permission", result["last_error"])
            self.assertEqual(controller.stop()["state"], "stopped")
            store.close()

    def test_profiler_start_pause_resume_and_stop_are_bounded(self) -> None:
        class FakeCollector:
            def collect(self, pid, raw_path, interrupt):
                self.pid = pid
                raw_path.write_bytes(b"perf-data")
                return (
                    aggregate_samples(
                        parse_perf_script(PERF_SCRIPT),
                        frequency_hz=10,
                        duration_seconds=0.5,
                    ),
                    True,
                    None,
                )

        with tempfile.TemporaryDirectory() as directory:
            store = ObservationStore(Path(directory))
            controller = ProfilerController(
                store,
                lambda: 123,
                lambda: {"game_date": "2200.01.01"},
                ProfilerConfig(
                    frequency_hz=10,
                    window_seconds=0.5,
                    interval_seconds=0.5,
                ),
                {"available": True, "reason": None, "perf_path": "perf"},
            )
            controller.collector = FakeCollector()  # type: ignore[assignment]
            self.assertEqual(controller.start()["state"], "running")
            deadline = time.monotonic() + 2.0
            while controller.status()["last_window"] is None:
                if time.monotonic() >= deadline:
                    self.fail("fake profiler did not produce a bounded window")
                time.sleep(0.02)
            self.assertEqual(controller.pause()["state"], "paused")
            self.assertEqual(controller.resume()["state"], "running")
            self.assertEqual(controller.stop()["state"], "stopped")
            self.assertEqual(len(store.list_windows()), 1)
            store.close()


if __name__ == "__main__":
    unittest.main()
