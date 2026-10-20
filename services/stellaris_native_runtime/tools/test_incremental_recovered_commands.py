from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
import zipfile
from dataclasses import replace
from pathlib import Path
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "src"))
spec = importlib.util.spec_from_file_location(
    "incremental_sdk_research",
    Path(__file__).with_name("incremental_recovered_commands.py"),
)
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)

from iag.stellaris.execution.native_runtime import (
    LINUX_NATIVE_RUNTIME_BUILD_ID,
    NativeCommandValidation,
    NativeRecoveredCommandCatalog,
)


def settings(**changes):
    value = module.Settings(
        123,
        "100",
        1000,
        "a" * 64,
        0x100,
        0xC0,
        "reviewed fixture",
        "baseline",
        "sdk",
        "saves",
        0,
        disk_reserve_bytes=0,
    )
    return replace(value, **changes)


def pending(name="waiting", **changes):
    value = module.Pending(name, "native_invalid", ("CFleet",), None, 10, 16, 0)
    return replace(value, **changes)


def snapshot(date=11, count=2, fingerprint="new"):
    return {
        "world_identity": 1000,
        "raw_game_date": date,
        "objects": {
            "CFleet": {
                "available": True,
                "nonnull_slots_in_scan": count,
                "slot_fingerprint": fingerprint,
            }
        },
    }


class IncrementalPlanningTests(unittest.TestCase):
    def test_no_date_change_no_native_retest(self):
        self.assertEqual(
            module.select_due([pending()], snapshot(10), {}, 10000, settings()), []
        )

    def test_missing_objects_wait_without_repeated_factory_calls(self):
        item = pending(missing_type="CFleet")
        self.assertEqual(
            module.select_due([item], snapshot(count=0), {}, 10000, settings()), []
        )
        self.assertEqual(
            module.select_due([item], snapshot(), {}, 10000, settings())[0][0], item
        )

    def test_bounded_fairness_backoff_and_unchanged_state(self):
        values = [pending(str(i)) for i in range(8)]
        self.assertEqual(
            len(module.select_due(values, snapshot(), {}, 10000, settings())), 3
        )
        item, signature = module.select_due(
            [pending()], snapshot(), {}, 10000, settings()
        )[0]
        item.last_signature, item.last_attempt, item.last_date = signature, 10000, 11
        item.no_progress_rounds = 2
        self.assertEqual(
            module.select_due([item], snapshot(12), {}, 11000, settings()), []
        )
        self.assertEqual(
            len(module.select_due([item], snapshot(12), {}, 13000, settings())), 1
        )

    def test_already_positive_and_quarantined_are_not_retested(self):
        self.assertEqual(
            module.select_due(
                [pending(positive=True), pending(quarantined=True)],
                snapshot(),
                {},
                10000,
                settings(),
            ),
            [],
        )

    def test_positive_and_static_blocked_rows_are_not_pending(self):
        baseline = {
            "finished_at": "2026-10-19T00:00:00+00:00",
            "commands": [
                {"command_name": "positive", "status": "native_valid", "attempts": []},
                {"command_name": "unknown", "status": "not_tested", "attempts": []},
                {
                    "command_name": "negative",
                    "status": "native_invalid",
                    "reason": "rule",
                    "attempts": [
                        {
                            "class_name": "CNegative",
                            "candidate_count": 16,
                            "game_date_after": 10,
                        }
                    ],
                },
            ],
        }
        sdk = {"commands": [{"class": "CNegative", "fields": [{"ref": "CFleet"}]}]}
        self.assertEqual(
            [p.name for p in module.pending_commands(baseline, sdk)], ["negative"]
        )

    def test_new_json_never_overwrites_checkpoint(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "checkpoint.json"
            module.write_new(path, {"original": True})
            with self.assertRaises(FileExistsError):
                module.write_new(path, {"original": False})
            self.assertTrue(json.loads(path.read_text())["original"])


class IncrementalEvidenceTests(unittest.TestCase):
    def test_save_is_stable_copied_and_not_promoted(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "source"
            source.mkdir()
            path = source / "autosave.sav"
            with zipfile.ZipFile(path, "w") as z:
                z.writestr(
                    "meta",
                    'version="Cygnus v4.5.2"\ndate="2233.07.01"\nname="Fixture"\n',
                )
                z.writestr("gamestate", "country={\n 0={\n value=1\n }\n}\n")
            original = path.read_bytes()
            output = root / "evidence"
            output.mkdir()
            collector = module.SaveEvidence(settings(save_root=str(source)), output)
            self.assertEqual(collector.scan(0), [])
            records = collector.scan(6)
            self.assertEqual(len(records), 1)
            self.assertTrue(records[0]["source_stable"])
            self.assertEqual(
                records[0]["evidence_level"], "save_state_only_temporal_association"
            )
            self.assertEqual(path.read_bytes(), original)
            self.assertEqual(Path(records[0]["archive"]).read_bytes(), original)
            self.assertEqual(collector.scan(30), [])

    def test_archive_disk_budget_preserves_source_without_copy(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "source"
            source.mkdir()
            (source / "x.sav").write_bytes(b"fixture")
            collector = module.SaveEvidence(
                settings(save_root=str(source), archive_limit_bytes=0), root
            )
            collector.scan(0)
            self.assertEqual(collector.scan(6), [])
            self.assertEqual((source / "x.sav").read_bytes(), b"fixture")


class IncrementalRuntimeTests(unittest.TestCase):
    def fixture(self, folder):
        root = Path(folder)
        baseline = {
            "build_id": LINUX_NATIVE_RUNTIME_BUILD_ID,
            "process_id": 123,
            "world_identity": 1000,
            "instance_id": 456,
            "finished_at": "2026-10-19T00:00:00+00:00",
            "commands": [
                {
                    "command_name": "waiting",
                    "status": "native_invalid",
                    "reason": "native_rule",
                    "attempts": [
                        {
                            "class_name": "CWaiting",
                            "country_id": 7,
                            "native_is_valid": False,
                            "candidate_count": 16,
                            "game_date_after": 10,
                        }
                    ],
                }
            ],
        }
        sdk = {
            "build_id": LINUX_NATIVE_RUNTIME_BUILD_ID,
            "commands": [{"class": "CWaiting", "fields": [{"ref": "CFleet"}]}],
        }
        module.write_new(root / "baseline.json", baseline)
        module.write_new(root / "sdk.json", sdk)
        client = Mock()
        client.describe_recovered_commands.return_value = (
            NativeRecoveredCommandCatalog.model_validate_json(
                json.dumps(
                    {
                        "schema_version": "iag.recovered_command_catalog.v1",
                        "build_id": LINUX_NATIVE_RUNTIME_BUILD_ID,
                        "process_id": 123,
                        "instance_id": 456,
                        "probe_revision": 2,
                        "commands": ["waiting"],
                    }
                )
            )
        )
        run = module.IncrementalRun(
            settings(baseline=str(root / "baseline.json"), sdk=str(root / "sdk.json")),
            root / "output",
            client,
        )
        run.pending[0].last_attempt = 0
        return run, client

    def result(self, status="native_invalid", world=1000):
        return NativeCommandValidation.model_validate_json(
            json.dumps(
                {
                    "schema_version": "iag.native_command_validation.v2",
                    "command_name": "waiting",
                    "class_name": "CWaiting",
                    "build_id": LINUX_NATIVE_RUNTIME_BUILD_ID,
                    "status": status,
                    "reason": "fixture",
                    "country_id": 7,
                    "world_identity": world,
                    "candidate_index": 0,
                    "candidate_count": 16,
                    "candidate_scan_truncated": False,
                    "structure_checked": True,
                    "constructed_from_generated_metadata": True,
                    "parameters_populated": True,
                    "native_is_valid": status == "native_valid",
                    "factory_rva": 123,
                    "vtable_rva": 456,
                    "object_size": 40,
                    "submitted": False,
                    "execution_verified": False,
                    "destroyed": True,
                    "run_game_update": True,
                    "elapsed_us": 1,
                    "create_us": 0,
                    "populate_us": 0,
                    "validate_us": 0,
                    "destroy_us": 0,
                    "bindings": [],
                }
            )
        )

    def test_budget_and_native_positive_are_not_execution_proof(self):
        with tempfile.TemporaryDirectory() as folder:
            run, client = self.fixture(folder)
            client.validate_recovered_command.side_effect = [
                self.result(),
                self.result("native_valid"),
            ]
            report = run.probe_round(snapshot(), {}, 10000)
            self.assertEqual(client.validate_recovered_command.call_count, 2)
            self.assertFalse(report["submitted"])
            self.assertEqual(report["paired_capture_promotions"], 0)
            run.probe_round(snapshot(12), {}, 20000)
            self.assertEqual(client.validate_recovered_command.call_count, 2)
            client.execute.assert_not_called()

    def test_transport_failure_retains_pending_and_does_not_replay(self):
        with tempfile.TemporaryDirectory() as folder:
            run, client = self.fixture(folder)
            client.validate_recovered_command.side_effect = OSError(
                "temporary disconnect"
            )
            with self.assertRaises(OSError):
                run.probe_round(snapshot(), {}, 10000)
            text = (run.output / "requests.jsonl").read_text()
            self.assertIn("interrupted_no_replay", text)
            run.probe_round(snapshot(12), {}, 10001)
            self.assertEqual(client.validate_recovered_command.call_count, 1)

    def test_runtime_change_is_rejected_before_any_candidate(self):
        with tempfile.TemporaryDirectory() as folder:
            run, client = self.fixture(folder)
            client.describe_recovered_commands.return_value = (
                client.describe_recovered_commands.return_value.model_copy(
                    update={"instance_id": 789}
                )
            )
            with self.assertRaises(module.SessionChanged):
                run.probe_round(snapshot(), {}, 10000)
            client.validate_recovered_command.assert_not_called()

    def test_unchanged_world_does_not_drain_remaining_negative_commands(self):
        with tempfile.TemporaryDirectory() as folder:
            run, client = self.fixture(folder)
            run.s = replace(run.s, commands_per_round=1, candidates_per_command=1)
            run.pending.append(pending("other"))
            client.validate_recovered_command.return_value = self.result()
            run.probe_round(snapshot(), {}, 10000)
            self.assertEqual(client.validate_recovered_command.call_count, 1)
            report = run.probe_round(
                snapshot(), {"family_fingerprints": {"fleets": "old_save"}}, 20000
            )
            self.assertEqual(report["selected"], 0)
            self.assertEqual(client.validate_recovered_command.call_count, 1)


if __name__ == "__main__":
    unittest.main()
