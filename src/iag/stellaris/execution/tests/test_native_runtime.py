from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from iag.stellaris.execution.native_runtime import (
    NATIVE_RUNTIME_BUILD_ID,
    WINDOWS_NATIVE_RUNTIME_BUILD_ID,
    NativeCommandValidation,
    NativeProbeBinding,
    NativeRuntimeClient,
    NativeRuntimeError,
    NativeRuntimeManifest,
    NativeRuntimeOutcome,
    NativeRuntimeParameter,
)


class NativeRuntimeClientTests(unittest.TestCase):
    def test_scoped_probe_evidence_is_typed_and_never_execution(self) -> None:
        from pydantic import ValidationError

        binding = NativeProbeBinding(
            field="id", storage_kind="u32", reference_type="", value=0xFFFFFFFF
        )
        self.assertEqual(binding.storage_kind, "u32")
        self.assertEqual(
            NativeCommandValidation.model_fields["scoped_lookup_calls"].default, 0
        )
        with self.assertRaises(ValidationError):
            NativeProbeBinding(
                field="id", storage_kind="u32", reference_type="", value=True
            )

    def test_generated_unregistered_command_probe_is_not_execution_evidence(
        self,
    ) -> None:
        payload = {
            "schema_version": "iag.native_command_validation.v2",
            "command_name": "hire_leader",
            "country_id": 7,
            "class_name": "CHireLeaderCommand",
            "build_id": NATIVE_RUNTIME_BUILD_ID,
            "status": "native_invalid",
            "reason": "native_rules_rejected_candidate",
            "candidate_index": 0,
            "candidate_count": 1,
            "candidate_scan_truncated": False,
            "structure_checked": True,
            "run_game_update": False,
            "elapsed_us": 10,
            "create_us": 1,
            "populate_us": 1,
            "validate_us": 6,
            "destroy_us": 1,
            "bindings": [
                {
                    "field": "leader",
                    "storage_kind": "ref",
                    "reference_type": "CLeader",
                    "value": 42,
                }
            ],
            "constructed_from_generated_metadata": True,
            "native_is_valid": False,
            "factory_rva": 0x6D1FA0,
            "vtable_rva": 0x23949C0,
            "object_size": 0x28,
            "submitted": False,
            "execution_verified": False,
            "destroyed": True,
        }
        client = NativeRuntimeClient("ignored")
        response = (
            "IAG1\tprobe-1\tvalidate_recovered_command\tconfirmed\t"
            f"{NATIVE_RUNTIME_BUILD_ID}\t7\t{json.dumps(payload)}\t"
            "native_validation_only_no_submission"
        )
        with patch.object(client, "_exchange", return_value=response) as exchange:
            result = client.probe_hire_leader(
                request_id="probe-1", country_id=7, leader_id=42
            )
        exchange.assert_called_once_with(
            b"IAG1\tprobe-1\tvalidate_recovered_command\t7\thire_leader\t42\t0\n"
        )
        self.assertFalse(result.native_is_valid)
        self.assertFalse(result.submitted)
        self.assertFalse(result.execution_verified)
        self.assertEqual(result.scoped_lookup_calls, 0)
        future = NativeCommandValidation.model_validate_json(
            json.dumps({**payload, "scoped_lookup_calls": 2})
        )
        self.assertEqual(future.scoped_lookup_calls, 2)
        for count in (-1, 257, True):
            with self.assertRaises(ValueError):
                NativeCommandValidation.model_validate_json(
                    json.dumps({**payload, "scoped_lookup_calls": count})
                )

        with (
            patch.object(
                client,
                "_exchange",
                return_value=response.replace('"value": 42', '"value": 43'),
            ),
            self.assertRaisesRegex(NativeRuntimeError, "target mismatch"),
        ):
            client.probe_hire_leader(request_id="probe-1", country_id=7, leader_id=42)

        payload["submitted"] = True
        with (
            patch.object(
                client,
                "_exchange",
                return_value=response.replace(
                    '"submitted": false', '"submitted": true'
                ),
            ),
            self.assertRaisesRegex(NativeRuntimeError, "Invalid generated command"),
        ):
            client.probe_hire_leader(request_id="probe-1", country_id=7, leader_id=42)

        with patch.object(client, "_exchange") as exchange:
            for value in (True, -1, 0xFFFFFFFF, "7"):
                with self.assertRaises(NativeRuntimeError):
                    client.validate_recovered_command(
                        request_id="probe-1",
                        command_name="hire_leader",
                        country_id=value,
                    )
            with self.assertRaises(NativeRuntimeError):
                client.validate_recovered_command(
                    request_id="probe-1", command_name="hire_leader", candidate_index=16
                )
        exchange.assert_not_called()

    def test_generated_probe_auto_parameters_are_not_raw_protocol_targets(self) -> None:
        client = NativeRuntimeClient("ignored")
        with (
            patch.object(
                client, "_request", side_effect=NativeRuntimeError("fixture")
            ) as request,
            self.assertRaisesRegex(NativeRuntimeError, "fixture"),
        ):
            client.validate_recovered_command(
                request_id="probe-auto", command_name="finish_agenda_command"
            )
        request.assert_called_once_with(
            request_id="probe-auto",
            action="validate_recovered_command",
            country_id=0xFFFFFFFF,
            target_fields=("finish_agenda_command", "auto", "0"),
        )

    def test_parses_correlated_verified_response(self) -> None:
        response = NativeRuntimeClient._parse_response(
            f"IAG1\trequest-1\tstop_research\tconfirmed\t"
            f"{NATIVE_RUNTIME_BUILD_ID}\t7\ttech_shields_2\t"
            "native_postcondition_not_researching",
            request_id="request-1",
            action="stop_research",
            country_id=7,
            target_echo="tech_shields_2",
        )

        self.assertEqual(response.outcome, NativeRuntimeOutcome.CONFIRMED)
        self.assertEqual(response.country_id, 7)
        self.assertEqual(response.technology_id, "tech_shields_2")

    def test_rejects_wrong_build_or_correlation(self) -> None:
        base = "IAG1\trequest-1\tstop_research\tconfirmed\t{}\t7\ttech_shields_2\tok"
        with self.assertRaisesRegex(NativeRuntimeError, "build identity"):
            NativeRuntimeClient._parse_response(
                base.format("0" * 40),
                request_id="request-1",
                action="stop_research",
                country_id=7,
                target_echo="tech_shields_2",
            )
        with self.assertRaisesRegex(NativeRuntimeError, "correlation"):
            NativeRuntimeClient._parse_response(
                base.format(NATIVE_RUNTIME_BUILD_ID),
                request_id="different-request",
                action="stop_research",
                country_id=7,
                target_echo="tech_shields_2",
            )

    def test_parses_correlated_move_response(self) -> None:
        response = NativeRuntimeClient._parse_response(
            f"IAG1\tmove-1\tmove_fleet\tconfirmed\t"
            f"{NATIVE_RUNTIME_BUILD_ID}\t0\t888:47\t"
            "native_postcondition_player_movement_order_present",
            request_id="move-1",
            action="move_fleet",
            country_id=0,
            target_echo="888:47",
        )

        self.assertEqual(response.outcome, NativeRuntimeOutcome.CONFIRMED)
        self.assertEqual(response.target_echo, "888:47")
        self.assertIsNone(response.technology_id)

    def test_parses_correlated_attack_response(self) -> None:
        response = NativeRuntimeClient._parse_response(
            f"IAG1\tattack-1\tattack_fleet\tconfirmed\t"
            f"{NATIVE_RUNTIME_BUILD_ID}\t0\t888:220\t"
            "native_postcondition_attack_order_matches_target",
            request_id="attack-1",
            action="attack_fleet",
            country_id=0,
            target_echo="888:220",
        )

        self.assertEqual(response.outcome, NativeRuntimeOutcome.CONFIRMED)
        self.assertEqual(response.target_echo, "888:220")
        self.assertIsNone(response.technology_id)

    def test_regular_file_is_not_a_runtime_endpoint(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "runtime.sock"
            path.write_text("not a socket", encoding="utf-8")
            self.assertFalse(NativeRuntimeClient(path).available())

    def test_response_transport_accepts_utf8_event_keys(self) -> None:
        line = NativeRuntimeClient._decode_line(
            "IAG1\tr\tinspect_open_events\tconfirmed\tb\t1\t"
            '{"title_key":"测试事件"}\tok\n'.encode()
        )

        self.assertIn("测试事件", line)

    def test_uint64_parameter_enforces_full_width_bounds(self) -> None:
        parameter = NativeRuntimeParameter.model_validate(
            {
                "name": "pending_action_id",
                "type": "uint64",
                "required": True,
                "description": "Pending action id.",
                "minimum": 1,
                "maximum": 0xFFFFFFFFFFFFFFFF,
            }
        )

        self.assertEqual(parameter.encode(0xFFFFFFFFFFFFFFFF), str(0xFFFFFFFFFFFFFFFF))
        with self.assertRaises(NativeRuntimeError):
            parameter.encode(0x10000000000000000)

    def test_inspect_open_events_returns_typed_stable_candidates(self) -> None:
        payload = json.dumps(
            {
                "schema_version": "iag.open_event_state.v1",
                "country_id": 9,
                "content_mode": "stable_keys_no_rng",
                "truncated": False,
                "events": [
                    {
                        "open_event_id": 41,
                        "event_definition_id": 77,
                        "title_key": "ancrel.1000.name",
                        "description_state": "dynamic_unrendered",
                        "options_truncated": False,
                        "options": [
                            {
                                "option_index": 2,
                                "text_key": "ancrel.1000.a",
                            }
                        ],
                    }
                ],
            },
            ensure_ascii=False,
            separators=(",", ":"),
        )
        requests: list[bytes] = []

        def exchange(request: bytes) -> str:
            requests.append(request)
            return (
                "IAG1\tevent-state-1\tinspect_open_events\tconfirmed\t"
                f"{NATIVE_RUNTIME_BUILD_ID}\t9\t{payload}\t"
                "open_event_state_stable_keys"
            )

        client = NativeRuntimeClient("ignored")
        with patch.object(client, "_exchange", side_effect=exchange):
            state = client.inspect_open_events(
                request_id="event-state-1",
                country_id=9,
            )

        self.assertEqual(
            requests,
            [b"IAG1\tevent-state-1\tinspect_open_events\t9\n"],
        )
        self.assertEqual(state.events[0].open_event_id, 41)
        self.assertEqual(state.events[0].options[0].option_index, 2)

    def test_inspect_pending_diplomatic_actions_returns_typed_candidates(
        self,
    ) -> None:
        payload = json.dumps(
            {
                "schema_version": "iag.pending_diplomatic_action_state.v1",
                "country_id": 9,
                "truncated": False,
                "actions": [
                    {
                        "pending_action_id": 0xFEDCBA9876543210,
                        "action_tag": "declare_war",
                        "actor_country_id": 4,
                        "recipient_country_id": 9,
                        "can_accept": True,
                        "can_reject": True,
                    }
                ],
            },
            separators=(",", ":"),
        )
        requests: list[bytes] = []

        def exchange(request: bytes) -> str:
            requests.append(request)
            return (
                "IAG1\tdiplomacy-state-1\tinspect_pending_diplomatic_actions\t"
                f"confirmed\t{NATIVE_RUNTIME_BUILD_ID}\t9\t{payload}\t"
                "pending_diplomatic_action_state_current_candidates"
            )

        client = NativeRuntimeClient("ignored")
        with patch.object(client, "_exchange", side_effect=exchange):
            state = client.inspect_pending_diplomatic_actions(
                request_id="diplomacy-state-1",
                country_id=9,
            )

        self.assertEqual(
            requests,
            [b"IAG1\tdiplomacy-state-1\tinspect_pending_diplomatic_actions\t9\n"],
        )
        self.assertEqual(
            state.actions[0].pending_action_id,
            0xFEDCBA9876543210,
        )
        self.assertEqual(state.actions[0].action_tag, "declare_war")

    def test_runtime_manifest_drives_generic_argument_order(self) -> None:
        manifest = json.dumps(
            {
                "schema_version": "iag.native_tool_manifest.v1",
                "platform": "windows-x64",
                "game_version": "Stellaris 4.4.6",
                "build_id": WINDOWS_NATIVE_RUNTIME_BUILD_ID,
                "tools": [
                    {
                        "action_type": "move_fleet",
                        "action_version": 1,
                        "application_id": "fleet_operations",
                        "description": "Move one fleet.",
                        "risk_class": "state_change",
                        "verification_state": "live_verified",
                        "parameters": [
                            {
                                "name": "fleet_id",
                                "type": "uint32",
                                "required": True,
                                "description": "Fleet id.",
                                "minimum": 0,
                                "maximum": 0xFFFFFFFF,
                            },
                            {
                                "name": "destination_system_id",
                                "type": "uint32",
                                "required": True,
                                "description": "System id.",
                                "minimum": 0,
                                "maximum": 0xFFFFFFFF,
                            },
                        ],
                    }
                ],
            },
            separators=(",", ":"),
        )
        requests: list[bytes] = []

        def exchange(request: bytes) -> str:
            requests.append(request)
            if b"\tdescribe_tools\t" in request:
                return (
                    "IAG1\truntime-tool-manifest\tdescribe_tools\tconfirmed\t"
                    f"{WINDOWS_NATIVE_RUNTIME_BUILD_ID}\t0\t{manifest}\t"
                    "runtime_tool_manifest"
                )
            return (
                "IAG1\tmove-1\tmove_fleet\tconfirmed\t"
                f"{WINDOWS_NATIVE_RUNTIME_BUILD_ID}\t7\t888:47\t"
                "native_postcondition_move_order_type_present"
            )

        client = NativeRuntimeClient("ignored")
        with patch.object(client, "_exchange", side_effect=exchange):
            catalog = client.describe_tools()
            response = client.execute(
                request_id="move-1",
                action_type="move_fleet",
                action_version=1,
                country_id=7,
                target={"destination_system_id": 47, "fleet_id": 888},
            )

        self.assertEqual(catalog.tools[0].application_id, "fleet_operations")
        self.assertEqual(
            tuple(item.name for item in catalog.tools[0].parameters),
            ("fleet_id", "destination_system_id"),
        )
        self.assertEqual(response.outcome, NativeRuntimeOutcome.CONFIRMED)
        self.assertEqual(
            requests[1],
            b"IAG1\tmove-1\tmove_fleet\t7\t888\t47\n",
        )

    def test_targetless_runtime_action_has_no_placeholder_field(self) -> None:
        manifest = json.dumps(
            {
                "schema_version": "iag.native_tool_manifest.v1",
                "platform": "linux-x86_64",
                "game_version": "Stellaris 4.4.6",
                "build_id": NATIVE_RUNTIME_BUILD_ID,
                "tools": [
                    {
                        "action_type": "join_galactic_community",
                        "action_version": 1,
                        "application_id": "etc",
                        "description": "Join the Galactic Community.",
                        "risk_class": "state_change",
                        "verification_state": "paired_capture",
                        "parameters": [],
                    }
                ],
            },
            separators=(",", ":"),
        )
        requests: list[bytes] = []

        def exchange(request: bytes) -> str:
            requests.append(request)
            if b"\tdescribe_tools\t" in request:
                return (
                    "IAG1\truntime-tool-manifest\tdescribe_tools\tconfirmed\t"
                    f"{NATIVE_RUNTIME_BUILD_ID}\t0\t{manifest}\t"
                    "runtime_tool_manifest"
                )
            return (
                "IAG1\tjoin-1\tjoin_galactic_community\trejected\t"
                f"{NATIVE_RUNTIME_BUILD_ID}\t16777219\t-\t"
                "native_is_valid_false_before_submit"
            )

        client = NativeRuntimeClient("ignored")
        with patch.object(client, "_exchange", side_effect=exchange):
            client.execute(
                request_id="join-1",
                action_type="join_galactic_community",
                action_version=1,
                country_id=16777219,
                target={},
            )

        self.assertEqual(
            requests[1],
            b"IAG1\tjoin-1\tjoin_galactic_community\t16777219\n",
        )

    def test_optional_runtime_parameter_encodes_as_empty_field(self) -> None:
        manifest = json.dumps(
            {
                "schema_version": "iag.native_tool_manifest.v1",
                "platform": "linux-x86_64",
                "game_version": "Stellaris 4.4.6",
                "build_id": NATIVE_RUNTIME_BUILD_ID,
                "tools": [
                    {
                        "action_type": "example_action",
                        "action_version": 1,
                        "application_id": "etc",
                        "description": "Test optional parameter encoding.",
                        "risk_class": "state_change",
                        "verification_state": "live_verified",
                        "parameters": [
                            {
                                "name": "object_id",
                                "type": "uint32",
                                "required": True,
                                "description": "Object id.",
                                "minimum": 0,
                                "maximum": 0xFFFFFFFF,
                            },
                            {
                                "name": "label",
                                "type": "string",
                                "required": False,
                                "description": "Optional label.",
                                "maximum_length": 40,
                            },
                        ],
                    }
                ],
            },
            separators=(",", ":"),
        )
        requests: list[bytes] = []

        def exchange(request: bytes) -> str:
            requests.append(request)
            if b"\tdescribe_tools\t" in request:
                return (
                    "IAG1\truntime-tool-manifest\tdescribe_tools\tconfirmed\t"
                    f"{NATIVE_RUNTIME_BUILD_ID}\t0\t{manifest}\t"
                    "runtime_tool_manifest"
                )
            return (
                "IAG1\toptional-1\texample_action\tconfirmed\t"
                f"{NATIVE_RUNTIME_BUILD_ID}\t4\t9:\tok"
            )

        client = NativeRuntimeClient("ignored")

        with patch.object(client, "_exchange", side_effect=exchange):
            client.execute(
                request_id="optional-1",
                action_type="example_action",
                action_version=1,
                country_id=4,
                target={"object_id": 9, "label": None},
            )

        self.assertEqual(
            requests[1],
            b"IAG1\toptional-1\texample_action\t4\t9\t\n",
        )

    def test_manifest_accepts_bounded_capture_record_parameter(self) -> None:
        manifest = NativeRuntimeManifest.model_validate(
            {
                "schema_version": "iag.native_tool_manifest.v1",
                "platform": "linux-x86_64",
                "game_version": "Stellaris 4.4.6",
                "build_id": NATIVE_RUNTIME_BUILD_ID,
                "tools": (
                    {
                        "action_type": "create_ship_design",
                        "action_version": 1,
                        "application_id": "fleet_operations",
                        "description": "Capture-backed ship design.",
                        "risk_class": "state_change",
                        "verification_state": "paired_capture",
                        "parameters": (
                            {
                                "name": "verified_record_hex",
                                "type": "string",
                                "required": True,
                                "description": "Verified record body.",
                                "maximum_length": 60_000,
                            },
                        ),
                    },
                ),
            }
        )

        self.assertEqual(
            manifest.tools[0].parameters[0].maximum_length,
            60_000,
        )


if __name__ == "__main__":
    unittest.main()
