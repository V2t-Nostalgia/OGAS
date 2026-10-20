from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "src"))

from iag.stellaris.execution.native_runtime import (
    LINUX_NATIVE_RUNTIME_BUILD_ID,
    NativeCommandValidation,
    NativeRecoveredCommandCatalog,
    NativeRuntimeError,
    NativeRuntimeOutcome,
)

spec = importlib.util.spec_from_file_location(
    "sdk_batch_tool", Path(__file__).with_name("validate_recovered_commands.py")
)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def result(
    command: str, status: str, index: int = 0, count: int = 1
) -> NativeCommandValidation:
    called = status in {"native_valid", "native_invalid"}
    return NativeCommandValidation.model_validate_json(
        json.dumps(
            {
                "schema_version": "iag.native_command_validation.v2",
                "command_name": command,
                "class_name": "CFixtureCommand",
                "build_id": LINUX_NATIVE_RUNTIME_BUILD_ID,
                "status": status,
                "reason": "fixture",
                "country_id": 7,
                "candidate_index": index,
                "candidate_count": count,
                "candidate_scan_truncated": False,
                "structure_checked": True,
                "constructed_from_generated_metadata": called,
                "native_is_valid": (status == "native_valid") if called else None,
                "parameters_populated": called,
                "factory_rva": 123,
                "vtable_rva": 456,
                "object_size": 0x28,
                "submitted": False,
                "execution_verified": False,
                "destroyed": called,
                "run_game_update": False,
                "elapsed_us": 10,
                "create_us": 1,
                "populate_us": 1,
                "validate_us": 6,
                "destroy_us": 1,
                "bindings": [],
            }
        )
    )


class RecoveredBatchTests(unittest.TestCase):
    def client(self) -> Mock:
        client = Mock()
        catalog = NativeRecoveredCommandCatalog.model_validate_json(
            json.dumps(
                {
                    "schema_version": "iag.recovered_command_catalog.v1",
                    "build_id": LINUX_NATIVE_RUNTIME_BUILD_ID,
                    "process_id": 123,
                    "instance_id": 456,
                    "probe_revision": 2,
                    "commands": ["first", "second", "third", "fourth"],
                }
            )
        )
        client.describe_recovered_commands.return_value = catalog
        return client

    def test_one_session_full_directory_rule_rejections_and_skips(self) -> None:
        client = self.client()
        client.validate_recovered_command.side_effect = [
            result("first", "native_invalid", 0, 2),
            result("first", "native_valid", 1, 2),
            result("second", "native_invalid"),
            result("third", "missing_parameters"),
            result("fourth", "not_tested"),
        ]
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / "new-evidence"
            report = module.run_batch(client, output, interval=0, batch_size=2)
            self.assertIsNone(report["aborted"])
            self.assertTrue(report["same_session_confirmed"])
            self.assertEqual(report["summary"]["catalog_commands"], 4)
            self.assertEqual(report["summary"]["constructed_commands"], 2)
            self.assertEqual(report["summary"]["populated_commands"], 2)
            self.assertEqual(report["summary"]["native_validator_calls"], 3)
            self.assertEqual(report["summary"]["is_valid_false_calls"], 2)
            self.assertTrue((output / "report.json").is_file())
            self.assertEqual(
                len((output / "progress.jsonl").read_text().splitlines()), 10
            )
            with self.assertRaises(FileExistsError):
                module.run_batch(client, output, interval=0)
        client.execute.assert_not_called()
        client.ensure_available.assert_not_called()

    def test_old_runtime_is_not_silently_reused_for_expanded_acceptance(self) -> None:
        client = self.client()
        client.describe_recovered_commands.return_value = (
            client.describe_recovered_commands.return_value.model_copy(
                update={"probe_revision": 1}
            )
        )
        with tempfile.TemporaryDirectory() as folder:
            report = module.run_batch(client, Path(folder) / "evidence", interval=0)
        self.assertIn("probe revision 2", report["aborted"])
        self.assertEqual(report["summary"]["native_validator_calls"], 0)
        client.validate_recovered_command.assert_not_called()

    def test_lifecycle_only_is_not_counted_as_population_or_validation(self) -> None:
        client = self.client()
        data = result("first", "not_tested").model_dump(mode="json")
        data.update(constructed_from_generated_metadata=True, destroyed=True)
        lifecycle = NativeCommandValidation.model_validate_json(json.dumps(data))
        client.validate_recovered_command.side_effect = [lifecycle] + [
            result(n, "not_tested") for n in ("second", "third", "fourth")
        ]
        with tempfile.TemporaryDirectory() as folder:
            report = module.run_batch(client, Path(folder) / "evidence", interval=0)
        self.assertEqual(report["summary"]["lifecycle_only_commands"], 1)
        self.assertEqual(report["summary"]["populated_commands"], 0)
        self.assertEqual(report["summary"]["native_validator_calls"], 0)
        data = result("first", "native_valid").model_dump(mode="json")
        data["parameters_populated"] = False
        with self.assertRaises(ValueError):
            NativeCommandValidation.model_validate_json(json.dumps(data))

    def test_transport_failure_retains_completed_and_untested_evidence(self) -> None:
        client = self.client()
        client.validate_recovered_command.side_effect = [
            result("first", "native_valid"),
            OSError("lost socket"),
        ]
        with tempfile.TemporaryDirectory() as folder:
            report = module.run_batch(client, Path(folder) / "evidence", interval=0)
        self.assertIn("lost socket", report["aborted"])
        self.assertFalse(report["same_session_confirmed"])
        self.assertEqual(report["commands"][0]["status"], "native_valid")
        self.assertEqual(report["commands"][1]["status"], "interrupted")
        self.assertIn("interrupted_request_id", report["commands"][1])
        self.assertEqual(report["commands"][-1]["status"], "not_tested")
        self.assertEqual(client.validate_recovered_command.call_count, 2)

    def test_runtime_replacement_stops_batch(self) -> None:
        client = self.client()
        catalog = client.describe_recovered_commands.return_value
        client.describe_recovered_commands.side_effect = [
            catalog,
            catalog.model_copy(update={"process_id": 124}),
        ]
        client.validate_recovered_command.side_effect = [
            result("first", "native_valid"),
            result("second", "native_valid"),
        ]
        with tempfile.TemporaryDirectory() as folder:
            report = module.run_batch(
                client, Path(folder) / "evidence", interval=0, batch_size=2
            )
        self.assertIn("instance", report["aborted"])
        self.assertEqual(client.validate_recovered_command.call_count, 2)

    def test_lifecycle_claims_are_validated(self) -> None:
        payload = result("first", "native_valid").model_dump(mode="json")
        for changed in (
            {"submitted": True},
            {"destroyed": False},
            {"native_is_valid": False},
        ):
            with self.assertRaises(ValueError):
                NativeCommandValidation.model_validate_json(
                    json.dumps({**payload, **changed})
                )

    def test_probe_has_no_submission_or_arbitrary_field_api(self) -> None:
        source = (ROOT / "services/stellaris_native_runtime/sdk_probe.cpp").read_text()
        self.assertNotIn("PostCommand(", source)
        self.assertNotIn("ReleaseForSubmission(", source)
        self.assertNotIn("->Execute(", source)
        for platform in ("runtime.cpp", "runtime_windows.cpp"):
            runtime = (
                ROOT / "services/stellaris_native_runtime" / platform
            ).read_text()
            self.assertIn("ShouldDispatchPending(", runtime)
            self.assertIn("ProcessPendingBeforeUpdate(run_game_update)", runtime)

    def native_client(self) -> Mock:
        client = self.client()
        client.describe_recovered_commands.return_value = (
            client.describe_recovered_commands.return_value.model_copy(
                update={
                    "probe_revision": 5,
                    "native_candidate_commands": ("first", "second"),
                }
            )
        )
        return client

    def native_result(self, command: str, index=0, count=1, date=123, identity=None):
        data = result(command, "native_valid", index, count).model_dump(mode="json")
        data.update(
            candidate_source="native_domain",
            parameter_source="fixture_native_query",
            candidate_identity=identity or f"country=7;target={command}-{index}",
            fixture_paused=True,
            game_date_before=date,
            game_date_after=date,
            world_identity=45678,
        )
        return NativeCommandValidation.model_validate_json(json.dumps(data))

    def test_subset_does_not_repeat_full_sdk(self) -> None:
        client = self.client()
        client.validate_recovered_command.return_value = result(
            "second", "native_valid"
        )
        with tempfile.TemporaryDirectory() as folder:
            report = module.run_batch(
                client, Path(folder) / "evidence", command_names=("second",), interval=0
            )
        self.assertIsNone(report["aborted"])
        self.assertEqual(report["summary"]["catalog_commands"], 4)
        self.assertEqual(report["summary"]["selected_commands"], 1)
        self.assertEqual(client.validate_recovered_command.call_count, 1)

    def test_native_domain_requires_current_catalog_without_fallback(self) -> None:
        client = self.client()
        with tempfile.TemporaryDirectory() as folder:
            report = module.run_batch(
                client,
                Path(folder) / "evidence",
                command_names=("first",),
                candidate_source="native_domain",
                interval=0,
            )
        self.assertIn("revision 5", report["aborted"])
        client.validate_recovered_command.assert_not_called()

    def test_revision_four_provider_is_not_reused_after_pause_fix(self) -> None:
        client = self.native_client()
        client.describe_recovered_commands.return_value = client.describe_recovered_commands.return_value.model_copy(
            update={"probe_revision": 4}
        )
        with tempfile.TemporaryDirectory() as folder:
            report = module.run_batch(
                client, Path(folder) / "evidence", command_names=("first",),
                candidate_source="native_domain", interval=0,
            )
        self.assertIn("revision 5", report["aborted"])
        client.validate_recovered_command.assert_not_called()

    def test_native_pause_evidence_is_required_independently_of_idle_flag(self) -> None:
        client = self.native_client()
        data = self.native_result("first").model_dump(mode="json")
        data.update(fixture_paused=False, run_game_update=False)
        client.validate_recovered_command.return_value = NativeCommandValidation.model_validate_json(json.dumps(data))
        with tempfile.TemporaryDirectory() as folder:
            report = module.run_batch(
                client, Path(folder) / "evidence", command_names=("first",),
                candidate_source="native_domain", interval=0, require_fixed_date=True,
            )
        self.assertIn("Native paused fixture", report["aborted"])

    def test_native_paused_fixture_can_validate_on_idle_true(self) -> None:
        client = self.native_client()
        data = self.native_result("first").model_dump(mode="json")
        data["run_game_update"] = True
        client.validate_recovered_command.return_value = NativeCommandValidation.model_validate_json(json.dumps(data))
        with tempfile.TemporaryDirectory() as folder:
            report = module.run_batch(
                client, Path(folder) / "evidence", command_names=("first",),
                candidate_source="native_domain", interval=0, require_fixed_date=True,
            )
        self.assertIsNone(report["aborted"])

    def test_selected_unknown_name_never_reaches_runtime(self) -> None:
        client = self.native_client()
        with tempfile.TemporaryDirectory() as folder:
            report = module.run_batch(
                client,
                Path(folder) / "evidence",
                command_names=("unknown",),
                interval=0,
            )
        self.assertIn("absent", report["aborted"])
        client.validate_recovered_command.assert_not_called()

    def test_repeated_native_window_exhausts_candidates_on_same_session(self) -> None:
        client = self.native_client()
        client.validate_recovered_command.side_effect = [
            self.native_result("first", i, 2) for _ in range(2) for i in range(2)
        ]
        with tempfile.TemporaryDirectory() as folder:
            report = module.run_validation_window(
                client,
                Path(folder) / "new-window",
                command_names=("first",),
                interval=0,
            )
        self.assertIsNone(report["aborted"])
        self.assertTrue(report["comparison"]["same_ordered_parameters_and_results"])
        self.assertFalse(report["comparison"]["independent_reload_determinism_proven"])
        self.assertEqual(client.validate_recovered_command.call_count, 4)
        client.ensure_available.assert_not_called()
        client.execute.assert_not_called()
        self.assertTrue(
            all(
                c.kwargs["candidate_source"] == "native_domain"
                for c in client.validate_recovered_command.call_args_list
            )
        )

    def test_changed_date_stops_window_without_third_round(self) -> None:
        client = self.native_client()
        client.validate_recovered_command.side_effect = [
            self.native_result("first"),
            self.native_result("first", date=124),
        ]
        with tempfile.TemporaryDirectory() as folder:
            report = module.run_validation_window(
                client,
                Path(folder) / "evidence",
                command_names=("first",),
                interval=0,
                repeats=3,
            )
        self.assertIn("GameDate changed", report["aborted"])
        self.assertFalse(report["comparison"]["comparable"])
        self.assertEqual(client.validate_recovered_command.call_count, 2)

    def test_idle_update_flag_is_not_fixture_pause_state(self) -> None:
        client = self.client()
        data = result("first", "native_valid").model_dump(mode="json")
        data.update(run_game_update=True, game_date_before=123,
                    game_date_after=123, world_identity=45678)
        client.validate_recovered_command.return_value = NativeCommandValidation.model_validate_json(json.dumps(data))
        with tempfile.TemporaryDirectory() as folder:
            report = module.run_batch(
                client, Path(folder) / "evidence", command_names=("first",),
                interval=0, require_fixed_date=True, expected_date=123,
                expected_world=45678,
            )
        self.assertIsNone(report["aborted"])
        self.assertEqual(report["summary"]["native_validator_calls"], 1)
        self.assertEqual(report["summary"]["non_updating_idle_native_calls"], 0)

    def test_changing_date_inside_call_still_stops_fixed_fixture(self) -> None:
        client = self.client()
        data = result("first", "native_valid").model_dump(mode="json")
        data.update(run_game_update=True, game_date_before=123,
                    game_date_after=124, world_identity=45678)
        client.validate_recovered_command.return_value = NativeCommandValidation.model_validate_json(json.dumps(data))
        with tempfile.TemporaryDirectory() as folder:
            report = module.run_batch(
                client, Path(folder) / "evidence", command_names=("first", "second"),
                interval=0, require_fixed_date=True,
            )
        self.assertIn("Fixed GameDate", report["aborted"])
        self.assertEqual(client.validate_recovered_command.call_count, 1)

    def test_parameter_drift_is_reported_not_hidden_by_true_results(self) -> None:
        client = self.native_client()
        client.validate_recovered_command.side_effect = [
            self.native_result("first"),
            self.native_result("first", identity="country=7;target=different"),
        ]
        with tempfile.TemporaryDirectory() as folder:
            report = module.run_validation_window(
                client, Path(folder) / "evidence", command_names=("first",), interval=0
            )
        self.assertTrue(report["comparison"]["comparable"])
        self.assertFalse(report["comparison"]["same_ordered_parameters_and_results"])
        self.assertFalse(report["execution_verified"])

    def test_pending_request_is_not_replayed_in_later_window_round(self) -> None:
        client = self.native_client()
        client.validate_recovered_command.side_effect = OSError("fixture disconnect")
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / "evidence"
            report = module.run_validation_window(
                client, output, command_names=("first",), interval=0
            )
            journal = (output / "round-01/progress.jsonl").read_text(encoding="utf8")
        self.assertEqual(client.validate_recovered_command.call_count, 1)
        self.assertEqual(report["completed_rounds"], 1)
        self.assertIn("started", journal)
        self.assertNotIn('"event": "completed"', journal)

    def test_expected_runtime_changed_before_round_calls_no_native(self) -> None:
        client = self.native_client()
        expected = client.describe_recovered_commands.return_value.model_copy(
            update={"instance_id": 999}
        )
        with tempfile.TemporaryDirectory() as folder:
            report = module.run_batch(
                client, Path(folder) / "evidence", expected_catalog=expected, interval=0
            )
        self.assertIn("before the batch", report["aborted"])
        client.validate_recovered_command.assert_not_called()

    def test_domain_result_requires_input_identity(self) -> None:
        data = self.native_result("first").model_dump(mode="json")
        data["candidate_identity"] = ""
        with self.assertRaises(ValueError):
            NativeCommandValidation.model_validate_json(json.dumps(data))

    def test_native_producer_never_posts_or_registers_actions(self) -> None:
        source = (
            ROOT / "services/stellaris_native_runtime/command_producers.cpp"
        ).read_text(encoding="utf8")
        for forbidden in (
            "PostCommand(",
            "ReleaseForSubmission(",
            "ActionRegistration",
            "->Execute(",
        ):
            self.assertNotIn(forbidden, source)

    def test_wrong_sdk_plan_cannot_send_native_requests(self):
        client = self.native_client()
        plan = {
            "schema_version": "iag.producer_validation_preparation.v1",
            "build_id": LINUX_NATIVE_RUNTIME_BUILD_ID,
            "sdk_fingerprint": "not-the-loaded-sdk",
        }
        with tempfile.TemporaryDirectory() as folder, self.assertRaises(ValueError):
            module.run_validation_window(client, Path(folder) / "new", plan=plan)
        client.validate_recovered_command.assert_not_called()

    def test_one_window_backfills_selected_commands_not_whole_directory(self):
        client = self.native_client()
        catalog = client.describe_recovered_commands.return_value.model_copy(
            update={"sdk_fingerprint": "a" * 64}
        )
        client.describe_recovered_commands.return_value = catalog
        legacy = result("third", "native_invalid").model_copy(
            update={
                "world_identity": 45678,
                "game_date_before": 123,
                "game_date_after": 123,
            }
        )
        client.validate_recovered_command.side_effect = [
            self.native_result("first"),
            legacy,
        ]
        plan = {
            "schema_version": "iag.producer_validation_preparation.v1",
            "build_id": catalog.build_id,
            "sdk_fingerprint": catalog.sdk_fingerprint,
            "native_domain_commands": ["first"],
            "legacy_selected_commands": ["third"],
        }
        with tempfile.TemporaryDirectory() as folder:
            report = module.run_validation_window(
                client, Path(folder) / "new", repeats=1, plan=plan, interval=0
            )
        self.assertIsNone(report["aborted"])
        self.assertEqual(report["selected_sdk_summary"]["selected_commands"], 1)
        self.assertEqual(client.validate_recovered_command.call_count, 2)
        client.execute.assert_not_called()

    def test_candidate_history_keeps_true_when_last_candidate_is_false(self):
        client = self.native_client()
        negative = self.native_result("first", 1, 2).model_copy(
            update={"status": "native_invalid", "native_is_valid": False}
        )
        client.validate_recovered_command.side_effect = [
            self.native_result("first", 0, 2),
            negative,
        ]
        with tempfile.TemporaryDirectory() as folder:
            report = module.run_batch(
                client,
                Path(folder) / "new",
                command_names=("first",),
                candidate_source="native_domain",
                exhaust_candidates=True,
                interval=0,
            )
        self.assertTrue(report["commands"][0]["has_native_valid_candidate"])
        self.assertEqual(report["summary"]["is_valid_true_commands"], 1)
        self.assertEqual(report["summary"]["native_validated_commands"], 1)
        self.assertEqual(report["summary"]["negative_only_commands"], 0)

    def test_client_sends_only_typed_source_selector_and_checks_echo(self):
        client = module.NativeRuntimeClient("/tmp/not-connected.sock")
        value = self.native_result("first")
        response = Mock(
            outcome=NativeRuntimeOutcome.CONFIRMED,
            target_echo=value.model_dump_json(),
            build_id=value.build_id,
        )
        client._request = Mock(return_value=response)
        observed = client.validate_recovered_command(
            request_id="fixture", command_name="first", candidate_source="native_domain"
        )
        self.assertEqual(observed, value)
        self.assertEqual(
            client._request.call_args.kwargs["target_fields"],
            ("first", "auto", "0", "native_domain"),
        )
        client._request.reset_mock()
        with self.assertRaises(NativeRuntimeError):
            client.validate_recovered_command(
                request_id="fixture",
                command_name="first",
                candidate_source="native_domain",
                leader_id=42,
            )
        client._request.assert_not_called()
        with self.assertRaises(NativeRuntimeError):
            client.validate_recovered_command(request_id="legacy", command_name="first")


if __name__ == "__main__":
    unittest.main()
