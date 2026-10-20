from __future__ import annotations

import os
import sys
import tempfile
import unittest
import json
import subprocess
import threading
from queue import Queue
from types import SimpleNamespace
from unittest.mock import patch
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent / "sdk_recovery"))

from capstone import Cs, CS_ARCH_X86, CS_MODE_64
from pydantic import ValidationError
from script_candidates.constraints import Evaluator, Fact, ObjectRef, Scope, Truth, World
from script_candidates.content import Content, ContentLayer, load_content
from script_candidates.feedback import Feedback
from script_candidates.native_guards import analyze, evaluate_guard, extract_guards
from script_candidates.native_predicates import pure_predicate, enum_table
from script_candidates.planner import Binding, Candidate, plan_command, scope_hints
from script_candidates.pipeline import native_bindings, run_validation
from script_candidates.snapshot import adapt_object
from script_candidates.syntax import CwtoolsParser, Node, ParseError


def scalar(key, value, op="="):
    return Node(key, op, value)


def block(key, *children):
    return Node(key, children=tuple(children))


def command():
    return {"class": "CTestCommand", "token_name": "test_command", "factory": 1, "vtable": 2,
            "size": 32, "is_valid": 3, "deleting_destructor": 4,
            "lifecycle_probe_safe": True,
            "fields": [{"name": "target", "kind": "ref", "ref": "CPlanet", "linux_off": 28,
                        "confidence": "direct_dataflow"}]}


def candidate():
    return Candidate(command_name="test", class_name="CTestCommand", build_id="b", sdk_sha256="sdk",
                     sdk_metadata_fingerprint="a" * 64,
                     save_sha256="save", content_fingerprint="content", bindings=(
                         Binding(field="target", offset=28, storage_kind="ref", reference_type="CPlanet",
                                 value=0x1000001, source="frozen_save_reference"),),
                     script_result="unknown", advisory_score=0)


class ConstraintTests(unittest.TestCase):
    def setUp(self):
        self.ref = ObjectRef("CPlanet", 1)
        self.world = World({self.ref: {"is_star": Fact(True, "fixture")}})
        self.scope = Scope(self.ref, self.ref)
        self.evaluator = Evaluator(self.world)

    def result(self, *nodes):
        return self.evaluator.evaluate(tuple(nodes), self.scope)

    def test_unknown_not_false(self):
        self.assertEqual(self.result(block("NOT", scalar("unimplemented", "yes"))).truth, Truth.UNKNOWN)

    def test_boolean_three_valued(self):
        self.assertEqual(self.result(block("OR", scalar("unimplemented", "yes"), scalar("always", "yes"))).truth, Truth.TRUE)
        self.assertEqual(self.result(block("AND", scalar("unimplemented", "yes"), scalar("always", "no"))).truth, Truth.FALSE)

    def test_multi_statement_not_is_not_guessed(self):
        self.assertEqual(self.result(block("NOT", scalar("always", "yes"), scalar("always", "no"))).truth, Truth.UNKNOWN)

    def test_tooltip_metadata_not_predicates(self):
        result = self.result(block("custom_tooltip", scalar("fail_text", "NOT_A_STAR"), scalar("is_star", "no")))
        self.assertEqual(result.truth, Truth.FALSE)
        self.assertEqual(result.failures, ("NOT_A_STAR",))

    def test_unknown_conditional_does_not_require_both_branches(self):
        result = self.result(block("if", block("limit", scalar("unknown", "yes")), scalar("always", "no")),
                             block("else", scalar("always", "yes")))
        self.assertEqual(result.truth, Truth.UNKNOWN)

    def test_conditional_skips_unreachable_failure(self):
        result = self.result(block("if", block("limit", scalar("always", "no")), scalar("always", "no")),
                             block("else", scalar("always", "yes")))
        self.assertEqual(result.truth, Truth.TRUE)

    def test_missing_collection_is_unknown_even_under_not(self):
        result = self.result(block("NOT", block("any_owned_fleet", scalar("always", "yes"))))
        self.assertEqual(result.truth, Truth.UNKNOWN)

    def test_quantifier_completeness(self):
        self.world.collections[self.ref, "owned_fleet"] = ((), False)
        self.assertEqual(self.result(block("any_owned_fleet", scalar("always", "yes"))).truth, Truth.UNKNOWN)
        self.world.collections[self.ref, "owned_fleet"] = ((), True)
        self.assertEqual(self.result(block("any_owned_fleet", scalar("always", "yes"))).truth, Truth.FALSE)

    def test_closed_sets_and_partial_sets(self):
        self.world.facts[self.ref]["ascension_perks"] = Fact(frozenset(), "fixture", complete=False)
        self.assertEqual(self.result(scalar("has_ascension_perk", "test")).truth, Truth.UNKNOWN)
        self.world.facts[self.ref]["ascension_perks"] = Fact(frozenset(), "fixture")
        self.assertEqual(self.result(scalar("has_ascension_perk", "test")).truth, Truth.FALSE)

    def test_external_definitions_not_engine_truth(self):
        self.world.facts[self.ref]["is_star"] = Fact(True, "external", trusted=False)
        self.assertEqual(self.result(scalar("is_star", "yes")).truth, Truth.UNKNOWN)
        self.assertEqual(Evaluator(self.world, advisory=True).evaluate((scalar("is_star", "yes"),), self.scope).truth, Truth.TRUE)

    def test_scripted_trigger_recursion_bounded(self):
        evaluator = Evaluator(self.world, {"cycle": block("cycle", scalar("cycle", "yes"))})
        self.assertEqual(evaluator.evaluate((scalar("cycle", "yes"),), self.scope).truth, Truth.UNKNOWN)

    def test_dynamic_flags_remain_unknown(self):
        self.assertEqual(self.result(scalar("has_fleet_flag", "in_progress@root")).truth, Truth.UNKNOWN)

    def test_numeric_comparator(self):
        self.world.facts[self.ref]["size"] = Fact(12, "fixture")
        self.assertEqual(self.result(scalar("size", "10", ">=")).truth, Truth.TRUE)

    def test_scope_root_survives_navigation(self):
        country = ObjectRef("CCountry", 8)
        self.world.links[self.ref, "owner"] = country
        self.world.facts[country] = {}
        self.assertEqual(self.result(block("owner", block("root", scalar("is_star", "yes")))).truth, Truth.TRUE)


class NativeGuardTests(unittest.TestCase):
    @staticmethod
    def image(code):
        md = Cs(CS_ARCH_X86, CS_MODE_64)
        md.detail = True
        class Image:
            by_address = {3: {"size": len(code)}}
            @staticmethod
            def instructions(_):
                return list(md.disasm(code, 3))
        return Image()

    def test_necessary_reject_guard_recovered(self):
        # cmp payload,1; jne false; mov eax,1; ret; false:xor eax,eax;ret
        image = self.image(bytes.fromhex("83 7f 1c 01 75 06 b8 01 00 00 00 c3 31 c0 c3"))
        result = extract_guards(image, command(), "linux-x86_64")
        self.assertEqual(len(result["guards"]), 1)
        guard = result["guards"][0]
        self.assertEqual(guard["necessity"], "proven_rejection_guard")
        self.assertTrue(evaluate_guard(guard, {"target": 1}))
        self.assertFalse(evaluate_guard(guard, {"target": 2}))

    def test_conditional_guard_cannot_be_globally_required(self):
        # An unknown branch can skip the check and return true.
        code = bytes.fromhex("85 f6 75 0f 83 7f 1c 01 75 06 b8 01 00 00 00 c3 31 c0 c3 b8 01 00 00 00 c3")
        result = extract_guards(self.image(code), command(), "linux-x86_64")
        self.assertFalse(any(g["necessity"] == "proven_rejection_guard" for g in result["guards"]))

    def test_unmapped_field_not_invented(self):
        image = self.image(bytes.fromhex("83 7f 20 01 75 06 b8 01 00 00 00 c3 31 c0 c3"))
        self.assertFalse(extract_guards(image, command(), "linux-x86_64")["guards"])

    def test_partial_register_write_does_not_prove_full_return(self):
        image = self.image(bytes.fromhex("b0 00 c3"))
        _, returns, _ = analyze(image.instructions(None), {})
        self.assertEqual(returns, [None])

    def test_equality_uses_machine_width_not_python_sign(self):
        image = self.image(bytes.fromhex("83 7f 1c ff 74 06 b8 01 00 00 00 c3 31 c0 c3"))
        guard, = extract_guards(image, command(), "linux-x86_64")["guards"]
        self.assertFalse(evaluate_guard(guard, {"target": 0xFFFFFFFF}))

    def test_mutating_or_opaque_paths_do_not_become_initial_input_constraints(self):
        for prefix in ("e8 00 00 00 00", "c7 47 1c 01 00 00 00"):
            code = bytes.fromhex(prefix + " 83 7f 1c 01 75 06 b8 01 00 00 00 c3 31 c0 c3")
            result = extract_guards(self.image(code), command(), "linux-x86_64")
            self.assertFalse(result["guards"])

    def test_implicit_register_writes_cannot_prove_zero_returns(self):
        for tail in ("f7 e6", "93"):  # mul esi; xchg eax,ebx
            image = self.image(bytes.fromhex("b8 00 00 00 00 " + tail + " c3"))
            _, returns, _ = analyze(image.instructions(None), {})
            self.assertEqual(returns, [None])


class PlannerTests(unittest.TestCase):
    def test_typed_frozen_bindings(self):
        with self.assertRaises(ValidationError):
            Binding(field="x", offset=28, storage_kind="ref", value={"raw_address": 1}, source="frozen_save_reference")
        with self.assertRaises(ValidationError):
            candidate().bindings[0].value = 1

    def test_all_unknown_rules_do_not_prevent_bounded_candidates(self):
        world = World({ObjectRef("CPlanet", i): {} for i in range(100)})
        result = plan_command(command(), 0, {"platform": "linux-x86_64", "build_id": "b", "sha256": "s"},
                              world, Content(), {"sha256": "save"}, {"rules": []}, {"guards": []}, candidate_limit=4)
        self.assertEqual(len(result["candidates"]), 4)
        self.assertTrue(result["domains"][0]["truncated"])
        self.assertEqual(result["native_is_valid_calls"], 0)

    def test_missing_parameters_not_filled_with_random_numbers(self):
        cmd = command()
        cmd["fields"][0]["kind"] = "u32"
        cmd["fields"][0].pop("ref")
        result = plan_command(cmd, 0, {"platform": "linux-x86_64", "build_id": "b", "sha256": "s"},
                              World(), Content(), {"sha256": "save"}, {"rules": []}, {"guards": []})
        self.assertFalse(result["candidates"])
        self.assertIn("candidate_domain_missing:target:u32", result["blockers"])

    def test_two_same_typed_fields_not_bound_by_english_names(self):
        cmd = command()
        cmd["fields"] *= 2
        rules = {"rules": [{"rule": "rule", "wrapper_rva": 10,
                 "evaluations": [{"this_scope": {"type": "Planet", "object": ("arg", 1, 0)}}]}]}
        self.assertEqual(scope_hints(cmd, rules), [])

    def test_candidate_identity_not_affected_by_advisory_rank(self):
        first = candidate()
        self.assertEqual(first.identity, first.model_copy(update={"advisory_score": 10}).identity)

    def test_save_ids_not_reduced_to_slot_indices(self):
        world = World()
        adapt_object(world, ObjectRef("CPlanet", 0x1000001), block("planet", scalar("owner", "33554434")), "fixture", Content())
        self.assertEqual(world.links[ObjectRef("CPlanet", 0x1000001), "owner"].object_id, 33554434)

    def test_repeated_technology_level_pairs_keep_semantics(self):
        world, ref = World(), ObjectRef("CCountry", 1)
        adapt_object(world, ref, block("country", block("tech_status", scalar("technology", "a"), scalar("level", "0"),
                    scalar("technology", "b"), scalar("level", "1"))), "fixture", Content())
        self.assertEqual(world.facts[ref]["technologies"].value, frozenset({"b"}))


class NativePredicateTests(unittest.TestCase):
    def image(self, code, name, table=b""):
        md = Cs(CS_ARCH_X86, CS_MODE_64)
        md.detail = True
        symbol = {"rva": 0x100, "size": len(code)}
        class Image:
            by_address = {0x100: symbol}
            @staticmethod
            def name(_):
                return name
            @staticmethod
            def instructions(_):
                return list(md.disasm(code, 0x100))
            @staticmethod
            def read(address, size):
                return table[:size] if address == 0x1000 else b""
        image = Image()
        image.md = md
        return image

    def test_pure_field_predicate_is_not_a_command_adapter(self):
        image = self.image(bytes.fromhex("40 38 b7 78 12 00 00 0f 94 c0 c3"), "CAnyObject::IsCategory const(EAnyCategory)")
        result = pure_predicate(image, 0x100)
        self.assertEqual((result["owner"], result["offset"], result["width"]), ("CAnyObject", 0x1278, 1))

    def test_nontrivial_predicate_not_summarized(self):
        image = self.image(bytes.fromhex("e8 00 00 00 00 40 38 b7 78 12 00 00 0f 94 c0 c3"), "CAnyObject::IsCategory const(EAnyCategory)")
        self.assertIsNone(pure_predicate(image, 0x100))

    def test_checked_native_enum_table_not_guessed_from_parameter_name(self):
        import struct
        code = bytes.fromhex("55 53 50 89 fd 40 80 fd 0f 73 10 48 0f be c5 48 8d 0d ea 0e 00 00 8b 1c 81 eb 05 bb e7 03 00 00 89 d8 48 83 c4 08 5b 5d c3")
        tokens = {n: "category_" + str(n) for n in range(15)}
        image = self.image(code, "GetCategoryTokenFromEnum(EAnyCategory)", struct.pack("<15I", *range(15)))
        result = enum_table(image, image.by_address[0x100], "EAnyCategory", tokens)
        self.assertEqual(result["tokens"]["3"], "category_3")
        self.assertIsNone(enum_table(image, image.by_address[0x100], "OtherEnum", tokens))
        self.assertIsNone(enum_table(image, image.by_address[0x100], "EAnyCategory", {}))


class FeedbackTests(unittest.TestCase):
    def result(self, value=False):
        return {"build_id": "b", "save_sha256": "save", "content_fingerprint": "content", "submitted": False,
                "destroyed": True, "native_is_valid": value, "source": "native_game_thread_IsValid"}

    def test_exact_rejection_is_cached_not_generalized(self):
        feedback, calls = Feedback(), []
        def gate(c):
            calls.append(c)
            return self.result()
        feedback.validate((candidate(),), gate)
        feedback.validate((candidate(),), gate)
        self.assertEqual(len(calls), 1)
        self.assertEqual(feedback.summary()["learned_unproven_rules"], 0)

    def test_stale_and_incomplete_results_not_used(self):
        for key, value in [("save_sha256", "other"), ("destroyed", False), ("source", "script"), ("submitted", True)]:
            with self.subTest(key=key), self.assertRaises(ValueError):
                Feedback().record(candidate(), self.result() | {key: value})

    def test_contradiction_invalidates_fixture_not_majority_vote(self):
        feedback = Feedback()
        feedback.record(candidate(), self.result())
        with self.assertRaisesRegex(ValueError, "Contradictory"):
            feedback.record(candidate(), self.result(True))
        self.assertEqual(feedback.summary()["fixture_reusable"], 0)


class PipelineTests(unittest.TestCase):
    def client(self, results, revision=6):
        catalog = SimpleNamespace(probe_revision=revision, build_id="b", instance_id=2, sdk_fingerprint="a" * 64)
        class Client:
            calls = []
            def describe_recovered_commands(self, **_):
                return catalog
            def validate_constraint_candidate(self, **args):
                self.calls.append(args)
                item = results.pop(0)
                if isinstance(item, Exception):
                    raise item
                data = {"native_is_valid": item, "status": "native_valid" if item else "native_invalid"}
                return SimpleNamespace(status=data["status"], reason="native_result", native_is_valid=item,
                                       fixture_paused=True, model_dump=lambda **_: data)
        return Client()

    def test_rejection_selects_next_candidate_then_stops_on_true(self):
        first = candidate()
        second = first.model_copy(update={"bindings": (first.bindings[0].model_copy(update={"value": 2}),)})
        report = {"build_id": "b", "commands": [{"candidates": [first.model_dump(mode="json"), second.model_dump(mode="json"), first.model_dump(mode="json")]}]}
        client = self.client([False, True])
        with tempfile.TemporaryDirectory() as temp:
            result = run_validation(report, client, {"instance_id": 2, "world_identity": 100, "game_date": 12}, Path(temp) / "new", interval=0)
        self.assertEqual(result["requests_completed"], 2)
        self.assertEqual(result["commands_native_true"], 1)
        self.assertFalse(result["submitted"])

    def test_timeout_never_replays_pending_or_continues(self):
        report = {"build_id": "b", "commands": [{"candidates": [candidate().model_dump(mode="json")] * 2}]}
        client = self.client([TimeoutError("uncertain")])
        with tempfile.TemporaryDirectory() as temp:
            result = run_validation(report, client, {"instance_id": 2, "world_identity": 100, "game_date": 12}, Path(temp) / "new", interval=0)
        self.assertEqual(len(client.calls), 1)
        self.assertEqual(result["requests_completed"], 0)
        self.assertIn("uncertain_request_completion", result["aborted"])

    def test_old_runtime_is_rejected_without_native_probes(self):
        client = self.client([], revision=5)
        with tempfile.TemporaryDirectory() as temp, self.assertRaises(ValueError):
            run_validation({"build_id": "b", "commands": []}, client, {"instance_id": 2}, Path(temp) / "new")
        self.assertEqual(client.calls, [])

    def test_signed_values_use_existing_unsigned_report_contract(self):
        value = candidate().model_copy(update={"bindings": (Binding(field="value", offset=28,
            storage_kind="i32", value=-1, source="sdk_enum"),)})
        self.assertEqual(native_bindings(value)[0].value, 0xFFFFFFFF)

    def test_old_runtime_skips_i64_without_marking_an_uncertain_native_request(self):
        value = candidate().model_copy(update={"bindings": (Binding(field="point.x", offset=32,
            storage_kind="i64", value=-1, source="frozen_save_coordinate"),)})
        report = {"build_id": "b", "commands": [{"candidates": [value.model_dump(mode="json")]}]}
        client = self.client([], revision=6)
        with tempfile.TemporaryDirectory() as temp:
            result = run_validation(report, client, {"instance_id": 2, "world_identity": 100, "game_date": 12}, Path(temp) / "new")
        self.assertEqual(client.calls, [])
        self.assertEqual(result["blocked"], {"native_gate_i64_requires_revision_7": 1})
        self.assertIsNone(result["aborted"])

    def test_i64_values_keep_signed_precision_through_binding_and_json(self):
        from iag.stellaris.execution.native_runtime import NativeProbeBinding
        for number in (-(1 << 63), -(1 << 32) - 1, -1, 0, 1 << 32, (1 << 53) + 1, (1 << 63) - 1):
            with self.subTest(number=number):
                value = candidate().model_copy(update={"bindings": (Binding(field="point.x", offset=32,
                    storage_kind="i64", value=number, source="frozen_save_coordinate"),)})
                binding, = native_bindings(value)
                self.assertEqual(binding.value, number)
                self.assertEqual(NativeProbeBinding.model_validate_json(binding.model_dump_json()), binding)

    def test_probe_binding_i64_is_strict_and_does_not_widen_other_kinds(self):
        from iag.stellaris.execution.native_runtime import NativeProbeBinding
        base = dict(field="point.x", reference_type="", storage_kind="i64")
        for bad in (-(1 << 63) - 1, 1 << 63, True, False, 1.0, "1", None):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                NativeProbeBinding(**base, value=bad)
        for kind in ("ref", "i32", "u32", "bool", "definition_pointer", "game_date32"):
            for bad in (-1, 1 << 32):
                with self.subTest(kind=kind, bad=bad), self.assertRaises(ValueError):
                    NativeProbeBinding(**(base | {"storage_kind": kind}), value=bad)

    def test_unsupported_definition_keys_skip_before_any_native_request(self):
        value = candidate().model_copy(update={"bindings": (Binding(field="value", offset=28,
            storage_kind="definition_pointer", reference_type="CType", value="not a wire token", source="external_definition"),)})
        with self.assertRaises(ValueError):
            native_bindings(value)


class NativeConstraintClientTests(unittest.TestCase):
    def setUp(self):
        from iag.stellaris.execution.native_runtime import NativeRecoveredCommandCatalog, NativeRuntimeClient, NATIVE_RUNTIME_BUILD_ID
        self.build = NATIVE_RUNTIME_BUILD_ID
        self.client = NativeRuntimeClient("not-connected")
        self.catalog = NativeRecoveredCommandCatalog(schema_version="iag.recovered_command_catalog.v1",
            build_id=self.build, process_id=1, instance_id=2, probe_revision=6, commands=("test",), sdk_fingerprint="a" * 64)
        self.bindings = native_bindings(candidate())
        self.args = dict(request_id="offline-test", command_name="test", catalog=self.catalog,
                         expected_world=100, expected_date=12, candidate_identity="b" * 64, bindings=self.bindings)

    def payload(self):
        return {"schema_version": "iag.native_command_validation.v2", "command_name": "test", "class_name": "CTestCommand",
            "build_id": self.build, "status": "native_valid", "reason": "native_is_valid_true", "country_id": None,
            "world_identity": 100, "candidate_index": 0, "candidate_count": 1, "candidate_scan_truncated": False,
            "candidate_source": "constraint_plan", "candidate_identity": "b" * 64, "structure_checked": True,
            "constructed_from_generated_metadata": True, "native_is_valid": True, "parameters_populated": True,
            "factory_rva": 1, "vtable_rva": 2, "object_size": 32, "submitted": False, "execution_verified": False,
            "destroyed": True, "run_game_update": False, "fixture_paused": True, "game_date_before": 12, "game_date_after": 12,
            "elapsed_us": 1, "create_us": 1, "populate_us": 1, "validate_us": 1, "destroy_us": 1,
            "bindings": [b.model_dump(mode="json") for b in self.bindings]}

    def test_reuses_existing_validation_request_not_an_action(self):
        from iag.stellaris.execution.native_runtime import NativeRuntimeOutcome
        response = SimpleNamespace(outcome=NativeRuntimeOutcome.CONFIRMED, build_id=self.build, target_echo=json.dumps(self.payload()))
        with patch.object(self.client, "_request", return_value=response) as request:
            result = self.client.validate_constraint_candidate(**self.args)
        self.assertEqual(request.call_args.kwargs["action"], "validate_recovered_command")
        self.assertEqual(request.call_args.kwargs["target_fields"][3], "constraint_plan")
        self.assertTrue(result.native_is_valid)

    def test_mismatched_populated_values_not_accepted(self):
        from iag.stellaris.execution.native_runtime import NativeRuntimeError, NativeRuntimeOutcome
        payload = self.payload()
        payload["bindings"][0]["value"] = 9
        response = SimpleNamespace(outcome=NativeRuntimeOutcome.CONFIRMED, build_id=self.build, target_echo=json.dumps(payload))
        with patch.object(self.client, "_request", return_value=response), self.assertRaises(NativeRuntimeError):
            self.client.validate_constraint_candidate(**self.args)

    def test_i64_decimal_wire_and_json_echo_are_lossless(self):
        from iag.stellaris.execution.native_runtime import NativeProbeBinding, NativeRuntimeOutcome
        catalog = self.catalog.model_copy(update={"probe_revision": 7})
        for number in (-(1 << 63), -(1 << 32) - 1, -1, 0, 1 << 32, (1 << 53) + 1, (1 << 63) - 1):
            with self.subTest(number=number):
                binding = NativeProbeBinding(field="point.x", storage_kind="i64", reference_type="", value=number)
                payload = self.payload() | {"bindings": [binding.model_dump(mode="json")]}
                response = SimpleNamespace(outcome=NativeRuntimeOutcome.CONFIRMED, build_id=self.build, target_echo=json.dumps(payload))
                with patch.object(self.client, "_request", return_value=response) as request:
                    result = self.client.validate_constraint_candidate(**(self.args | {"catalog": catalog, "bindings": (binding,)}))
                self.assertEqual(request.call_args.kwargs["target_fields"][8], f"point.x~i64~{number}")
                self.assertEqual(result.bindings, (binding,))

    def test_i64_truncated_or_unsigned_echo_is_not_accepted(self):
        from iag.stellaris.execution.native_runtime import NativeProbeBinding, NativeRuntimeError, NativeRuntimeOutcome
        binding = NativeProbeBinding(field="point.x", storage_kind="i64", reference_type="", value=-4294967297)
        for bad in (binding.value & 0xFFFFFFFF, binding.value & 0xFFFFFFFFFFFFFFFF, float(binding.value), str(binding.value)):
            payload = self.payload() | {"bindings": [binding.model_dump(mode="json") | {"value": bad}]}
            response = SimpleNamespace(outcome=NativeRuntimeOutcome.CONFIRMED, build_id=self.build, target_echo=json.dumps(payload))
            with self.subTest(bad=bad), patch.object(self.client, "_request", return_value=response), self.assertRaises(NativeRuntimeError):
                self.client.validate_constraint_candidate(**(self.args | {"catalog": self.catalog.model_copy(update={"probe_revision": 7}), "bindings": (binding,)}))

    def test_i64_on_old_runtime_sends_nothing(self):
        from iag.stellaris.execution.native_runtime import NativeProbeBinding, NativeRuntimeError
        binding = NativeProbeBinding(field="point.x", storage_kind="i64", reference_type="", value=-1)
        with patch.object(self.client, "_request") as request, self.assertRaisesRegex(NativeRuntimeError, "revision 7"):
            self.client.validate_constraint_candidate(**(self.args | {"bindings": (binding,)}))
        request.assert_not_called()

    @unittest.skipUnless(os.environ.get("IAG_CONSTRAINT_PREFLIGHT_REPORT"), "Set IAG_CONSTRAINT_PREFLIGHT_REPORT for full catalog communication preflight")
    def test_full_catalog_wire_and_json_preflight_without_native_calls(self):
        from iag.stellaris.execution.native_runtime import NativeProbeBinding
        report = json.loads(Path(os.environ["IAG_CONSTRAINT_PREFLIGHT_REPORT"]).read_text(encoding="utf-8"))
        self.assertEqual(report["build_id"], self.build)
        commands = tuple(row["command_name"] for row in report["commands"])
        validated, coordinate_commands = 0, set()
        for row in report["commands"]:
            for raw in row["candidates"]:
                value = Candidate.model_validate_json(json.dumps(raw))
                expected = native_bindings(value)
                def exchange(request):
                    fields = request.decode("ascii").removesuffix("\n").split("\t")
                    self.assertEqual(len(fields), 14)
                    self.assertEqual(fields[7], "constraint_plan")
                    echoed = []
                    for entry in fields[12].split("|"):
                        name, kind, text = entry.split("~")
                        number = 0 if kind == "definition_pointer" else int(text, 10)
                        if kind == "i32":
                            number &= 0xFFFFFFFF
                        ref_type = next(b.reference_type for b in expected if b.field == name)
                        echoed.append(NativeProbeBinding(field=name, storage_kind=kind, reference_type=ref_type,
                            value=number, text_value=text if kind == "definition_pointer" else "").model_dump(mode="json"))
                    # Codec-only echo: no claim of construction, native rules or execution.
                    payload = self.payload() | {"command_name": fields[4], "candidate_identity": fields[10],
                        "status": "not_tested", "reason": "offline_communication_only", "structure_checked": False,
                        "constructed_from_generated_metadata": False, "destroyed": False, "native_is_valid": None,
                        "parameters_populated": False, "bindings": echoed}
                    return "\t".join((fields[0], fields[1], fields[2], "confirmed", self.build, fields[3], json.dumps(payload), "offline_mock"))
                catalog = self.catalog.model_copy(update={"probe_revision": 7, "commands": commands,
                    "sdk_fingerprint": value.sdk_metadata_fingerprint})
                with patch.object(self.client, "_exchange", side_effect=exchange):
                    result = self.client.validate_constraint_candidate(**(self.args | {"command_name": value.command_name,
                        "catalog": catalog, "candidate_identity": value.identity, "bindings": expected}))
                self.assertEqual(result.bindings, expected, value.command_name)
                self.assertIsNone(result.native_is_valid)
                self.assertFalse(result.constructed_from_generated_metadata or result.submitted)
                validated += 1
                if any(b.storage_kind == "i64" for b in expected):
                    coordinate_commands.add(value.command_name)
        self.assertEqual(validated, sum(len(row["candidates"]) for row in report["commands"]))
        self.assertTrue({"fleet_fly_to_coordinates", "fleet_send_to_location", "build_megastructure_command",
                         "add_ship_to_coordinates"} <= coordinate_commands)

    def test_old_runtime_and_duplicate_fields_send_nothing(self):
        from iag.stellaris.execution.native_runtime import NativeRuntimeError
        for changed in [{"catalog": self.catalog.model_copy(update={"probe_revision": 5})}, {"bindings": self.bindings * 2}]:
            with patch.object(self.client, "_request") as request, self.assertRaises(NativeRuntimeError):
                self.client.validate_constraint_candidate(**(self.args | changed))
            request.assert_not_called()


@unittest.skipUnless(os.environ.get("IAG_CONSTRAINT_CODEC_TEST_EXE"), "Set IAG_CONSTRAINT_CODEC_TEST_EXE for the C++ mock wire fixture")
class NativeConstraintWireTests(unittest.TestCase):
    def test_real_python_wire_cpp_parser_builder_json_roundtrip(self):
        from iag.stellaris.execution.native_runtime import NativeProbeBinding, NativeRecoveredCommandCatalog, NativeRuntimeClient, NATIVE_RUNTIME_BUILD_ID
        process = subprocess.Popen([os.environ["IAG_CONSTRAINT_CODEC_TEST_EXE"], "--i64-wire", NATIVE_RUNTIME_BUILD_ID],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        def stop():
            process.stdin.close()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
            process.stdout.close()
            process.stderr.close()
        self.addCleanup(stop)
        lines = Queue()
        def read_lines():
            for line in process.stdout:
                lines.put(line)
            lines.put(None)
        reader = threading.Thread(target=read_lines, daemon=True)
        reader.start()
        hello = json.loads(lines.get(timeout=10))
        catalog = NativeRecoveredCommandCatalog.model_validate_json(json.dumps(hello["catalog"]))
        self.assertEqual(catalog.probe_revision, 7)
        client = NativeRuntimeClient("offline-cpp-fixture-only")
        sent = []
        def exchange(request):
            sent.append(request)
            process.stdin.write(request)
            process.stdin.flush()
            response = lines.get(timeout=10)
            self.assertIsNotNone(response, "C++ mock fixture stopped before responding")
            return client._decode_line(response)
        for index, number in enumerate((-(1 << 63), -(1 << 32) - 1, -1, 0, 1 << 32, (1 << 53) + 1, (1 << 63) - 1)):
            opposite = (1 << 63) - 1 if number == -(1 << 63) else -number
            bindings = (
                NativeProbeBinding(field="country", storage_kind="ref", reference_type="CCountry", value=hello["country_id"]),
                NativeProbeBinding(field="queue", storage_kind="ref", reference_type="CConstructionQueue", value=hello["queue_id"]),
                NativeProbeBinding(field="point.x", storage_kind="i64", reference_type="", value=number),
                NativeProbeBinding(field="point.y", storage_kind="i64", reference_type="", value=opposite),
            )
            with self.subTest(number=number), patch.object(client, "_exchange", side_effect=exchange):
                result = client.validate_constraint_candidate(request_id=f"i64-wire-{index}", command_name="coordinate_fixture",
                    catalog=catalog, expected_world=hello["world_identity"], expected_date=hello["game_date"],
                    candidate_identity="b" * 64, bindings=bindings)
                self.assertEqual(result.bindings, bindings)
                self.assertTrue(result.destroyed and result.parameters_populated and result.native_is_valid)
                self.assertFalse(result.submitted or result.execution_verified)
                self.assertIn(f"point.x~i64~{number}|point.y~i64~{opposite}".encode("ascii"), sent[-1])
        process.stdin.close()
        self.assertEqual(process.wait(timeout=5), 0, process.stderr.read().decode("utf-8"))
        reader.join(timeout=5)


BRIDGE = os.environ.get("IAG_CWTOOLS_BRIDGE")


@unittest.skipUnless(BRIDGE, "Optional CWTools integration: set IAG_CWTOOLS_BRIDGE")
class CommunityParserTests(unittest.TestCase):
    def setUp(self):
        self.parser = CwtoolsParser(Path(BRIDGE))
        self.addCleanup(self.parser.close)

    def test_duplicates_comparators_quotes_and_anonymous_values(self):
        root, = self.parser.parse('a={ x>=2 x=1 v={ a b "#literal" } "x>"=3 }')
        self.assertEqual([n.operator for n in root.all("x")], [">=", "="])
        self.assertEqual(root.one("v").children[-1].value, "#literal")
        self.assertIsNotNone(root.one("x>"))

    def test_parse_failure_not_empty_success(self):
        with self.assertRaises(ParseError):
            self.parser.parse("a={")

    def test_optional_operator_whitespace_keeps_unknown_semantics(self):
        node, = self.parser.parse('owner? = { always=yes }')
        self.assertEqual((node.key, node.operator), ("owner", "?="))
        # Optional-scope semantics are not assumed by the partial evaluator.
        self.assertEqual(Evaluator(World()).evaluate((node,), Scope(None)).truth, Truth.UNKNOWN)

    def test_generic_rule_to_candidate_ranking_not_special_command_logic(self):
        rule, = self.parser.parse('can_use_target={ custom_tooltip={ fail_text=ONLY_STARS is_star=yes } }')
        content = Content(entries={("game_rules", "can_use_target"): rule})
        refs = [ObjectRef("CPlanet", 1), ObjectRef("CPlanet", 2)]
        world = World({refs[0]: {"is_star": Fact(False, "fixture")}, refs[1]: {"is_star": Fact(True, "fixture")}})
        native = {"rules": [{"rule": "can_use_target", "wrapper_rva": 10,
            "evaluations": [{"this_scope": {"type": "Planet", "object": ("arg", 1, 0)},
                             "root_scope": {"object": ("arg", 1, 0)}}]}]}
        result = plan_command(command(), 0, {"platform": "linux-x86_64", "build_id": "b", "sha256": "s"},
                              world, content, {"sha256": "save"}, native, {"guards": []})
        self.assertEqual(result["candidates"][0]["bindings"][0]["value"], 2)
        self.assertEqual(len(result["candidates"]), 2)  # advisory rule cannot delete uncertain paths

    def test_content_file_overlay_replace_path_and_duplicate_keys(self):
        with tempfile.TemporaryDirectory() as temp:
            roots = [Path(temp) / str(i) for i in range(2)]
            for root in roots:
                (root / "common/game_rules").mkdir(parents=True)
            (roots[0] / "common/game_rules/a.txt").write_text("old={always=yes}", encoding="utf-8")
            (roots[1] / "common/game_rules/b.txt").write_text("new={always=no}", encoding="utf-8")
            content = load_content(self.parser, (ContentLayer(roots[0]), ContentLayer(roots[1], ("common/game_rules",))), ("game_rules",))
            self.assertEqual(set(content.family("game_rules")), {"new"})
            self.assertFalse(content.engine_loaded)


if __name__ == "__main__":
    unittest.main()
