from __future__ import annotations

import copy
import importlib.util
import json
import struct
import sys
import tempfile
import unittest
from pathlib import Path

TOOLS = Path(__file__).parent
sys.path.insert(0, str(TOOLS))
sys.path.insert(0, str(TOOLS / "sdk_recovery"))
sys.path.insert(0, str(TOOLS.parents[2] / "src"))

from script_candidates.semantic_audit import audit_command, audit_summary, command_phase, field_contract, ParameterSource
from script_candidates.syntax import Node


def field(name="object", kind="ref", **extra):
    return {"name": name, "kind": kind, "ref": "CFleet" if kind == "ref" else None,
            "linux_off": 28, "confidence": "direct_dataflow", "evidence_rva": 4096,
            "writer": "CWriter::Write", **extra}


def sample(fields=None):
    fields = [field()] if fields is None else fields
    return {"class": "CExample", "fields": fields, "population_fields": fields,
            "size": 32, "factory": 100, "is_valid": 200, "vtable": 300,
            "deleting_destructor": 400, "lifecycle_probe_safe": True,
            "factory_evidence": {"writes": []}}


def catalog(command):
    return {"platform": "linux-x86_64", "build_id": "exact", "commands": [command],
            "object_databases": [{"class": "CFleet"}], "definition_databases": []}


def candidate_row():
    return {"command_name": "arbitrary", "domains": [{"field": "object", "available": 0}],
            "candidates": [], "native_rule_paths": {}, "native_constraints": {}}


class SemanticAuditTests(unittest.TestCase):
    def audit(self, c, snapshot=None, row=None, calls=()):
        return audit_command(c, row or candidate_row(), catalog(c), snapshot or
            {"sha256": "frozen", "objects": {}}, {"functions": [], "calls": list(calls),
                "producer_callsites": [], "indirect_edges": []})

    def test_empty_fixture_and_resolver_gap_are_not_abi_gap(self):
        c = sample()
        result = self.audit(c, {"sha256": "frozen", "objects": {"CFleet": {"parsed": 0, "absence_proven": True}}})
        self.assertEqual(result["primary_status"], "waiting_game_state")
        self.assertTrue(result["can_construct_with_typed_inputs"])
        self.assertFalse(result["technical_gaps"])

    def test_unparsed_save_does_not_prove_missing_scene(self):
        result = self.audit(sample())
        self.assertEqual(result["primary_status"], "state_discovery_gap")
        self.assertEqual(result["state_requirements"][0]["requirement"], "save_candidate_provider_not_proven_empty")

    def test_caller_text_has_a_typed_slot_not_a_missing_object_domain(self):
        f = field("label", "native_text_value", native_type="CPersistentName", native_size=88,
                  assignment_rva=900, native_copy_parameter_evidence=[{"constructor_rva": 1000}])
        c = sample([f]); c["size"] = 120
        # Value starts aligned after the base; factory proof covers the gap.
        f["linux_off"] = 32
        c["factory_evidence"] = {"writes": [{"offset": 28, "width": 4}]}
        result = self.audit(c)
        self.assertEqual(result["primary_status"], "waiting_caller_parameters")
        self.assertEqual(result["caller_requirements"][0]["requirement"], "caller_text_required")
        self.assertFalse(result["technical_gaps"])

    def test_a_name_token_alone_does_not_prove_free_text(self):
        f = field("name", "string", native_type="CString", native_size=48, assignment_rva=900)
        p = field_contract(f, {}, sample([f]), catalog(sample()), {"objects": {}}, [])
        self.assertEqual(p.source, ParameterSource.BINDING)
        self.assertEqual(p.requirement, "producer_argument_or_native_consumer_binding_required")

    def test_paired_native_text_population_is_reusable_as_input_ability_not_value(self):
        f = field("arbitrary", "native_text_value", native_type="CPersistentName", native_size=88, assignment_rva=900)
        c = sample([f]); c["observed_text_input_fields"] = ["arbitrary"]
        p = field_contract(f, {}, c, catalog(c), {}, [])
        self.assertEqual(p.source, ParameterSource.CALLER)
        self.assertEqual(p.supplied_candidates, 0)

    def test_record_counter_is_engine_context_not_guessed_caller_integer(self):
        f = field("id", "i32", native_counter_record_identity={"counter_offset": 80})
        p = field_contract(f, {}, sample([f]), catalog(sample()), {"objects": {}}, [])
        self.assertEqual(p.source, ParameterSource.INTERNAL)
        self.assertIn("correlated", p.requirement)

    def test_positive_quantity_candidate_is_not_misreported_as_native_enum(self):
        f=field("quantity","i32",scalar_candidates=[{"value":1,"evidence":"native_guard"}])
        p=field_contract(f,{"available":1},sample([f]),catalog(sample()),{},[])
        self.assertEqual(p.source,ParameterSource.SCALAR)
        self.assertNotEqual(p.source,ParameterSource.ENUM)

    def test_existing_scoped_provider_is_a_query_requirement_not_missing_recovery(self):
        f = field("handle", "u32", scoped_reference_evidence=[{"class":"CRecord"}])
        c = sample([f]); s = catalog(c)
        s["scoped_id_bindings"] = [{"command_class":"CExample","field_offset":28,"country_field_offset":32}]
        p = field_contract(f, {}, c, s, {}, [])
        self.assertEqual(p.requirement,"existing_native_country_scoped_provider_query_required")

    def test_one_native_type_with_multiple_definition_pools_requires_origin_binding(self):
        f = field("object","string",indirect=True,definition_type="CSharedType")
        c = sample([f]); s = catalog(c)
        s["definition_databases"] = [{"class":"CSharedType","database_rva":100,"data_offset":8},
                                     {"class":"CSharedType","database_rva":200,"data_offset":8}]
        p = field_contract(f,{"available":2},c,s,{},[])
        self.assertEqual(p.requirement,"definition_pool_selection_requires_native_producer_binding")

    def test_native_lobby_manager_evidence_not_command_name(self):
        calls = [{"name": "CLobbyCoopGroupsManager::ContainsGroup const(int)", "call_rva": 10}]
        self.assertTrue(command_phase(sample([]), calls, [])["deferred"])
        c = sample(); c["class"] = "CCreateLobbyCoopGroupCommand"
        self.assertFalse(command_phase(c, [], [])["deferred"])

    def test_chat_notification_does_not_prove_lobby_operation(self):
        self.assertFalse(command_phase(sample([]),[{"name":"CIngameLobby::OnChatMessage(CChatMessage*)"}],[])["deferred"])

    def test_pause_is_not_deferred_as_generic_session_management(self):
        self.assertFalse(command_phase(sample([]),[{"name":"CInGameIdler::SetPaused(SPauseGameSettings const&)"}],[])["deferred"])

    def test_session_or_debug_caller_does_not_exclude_empire_action(self):
        self.assertFalse(command_phase(sample(), [{"name": "CSession::PostCommand()"}], [{"caller": "CCosmicStormsImGui::Draw()"}])["deferred"])

    def test_summary_primary_partition_and_overlapping_axes_are_explicit(self):
        rows = [self.audit(sample())]
        result = audit_summary(rows)
        self.assertEqual(sum(result["exclusive_primary_status"].values()), 1)
        self.assertEqual(result["independent_dimensions_not_additive"]["typed_constructible_with_inputs"], 1)

    def test_fixed_point_storage_does_not_guess_units(self):
        f = field("x", "other", storage_kind="i64", native_type="CFixedPoint",
                  value_recovery={"units": "requires_native_conversion"})
        p = field_contract(f, {}, sample([f]), catalog(sample()), {}, [])
        self.assertIn("unit_conversion", p.requirement)
        self.assertNotEqual(p.source, ParameterSource.CALLER)

    def test_reference_list_not_an_unimplemented_value_type(self):
        f = field("objects", "reference_array", ref="CFleet", native_size=24, assignment_rva=900)
        p = field_contract(f, {}, sample([f]), catalog(sample()), {"objects": {"CFleet": {"parsed": 3}}}, [])
        self.assertTrue(p.writable)
        self.assertEqual(p.setter, "SetReferenceList")
        self.assertEqual(p.requirement, "caller_selects_nonempty_ordered_reference_list")

    def test_known_native_region_with_unbound_label_is_not_missing_abi(self):
        f=field("projection","i32",linux_off=None,confidence="unresolved",writer="CWriter::WriteUniformWithSpace")
        c=sample([f]);c["native_object_region_layout"]={"complete":True,"unbound_members":[{"field":"projection","offset":32,"width":24}]}
        result=self.audit(c)
        self.assertFalse(result["technical_gaps"])
        self.assertFalse(result["can_construct_with_typed_inputs"])
        self.assertEqual(result["primary_status"],"semantic_parameter_binding_gap")
        self.assertIn("native_array_serializer_projection_binding_required",[g["requirement"] for g in result["semantic_binding_requirements"]])


@unittest.skipUnless(importlib.util.find_spec("capstone"), "SDK disassembler optional")
class NativeValueRecoveryTests(unittest.TestCase):
    def image(self, code, targets=None, raw=""):
        from capstone import Cs, CS_ARCH_X86, CS_MODE_64
        md = Cs(CS_ARCH_X86, CS_MODE_64); md.detail = True
        class Image:
            def instructions(self, symbol, limit=65536):
                return list(md.disasm(code[:limit], symbol["rva"]))
            def target_name(self, address):
                return (targets or {}).get(address, "")
            def name(self, symbol):
                return symbol.get("raw", "")
        return Image(), {"rva": 4096, "size": len(code), "raw": raw}

    def enum_field(self, method=False):
        from linux_elf import extract_serializer
        code = bytes.fromhex("534889fb0fb67b20")
        code += b"\xe8" + struct.pack("<i",8192-(4096+len(code)+5))
        code += bytes.fromhex("89c2be10000000")
        code += b"\xe8" + struct.pack("<i",12288-(4096+len(code)+5)) + bytes.fromhex("5bc3")
        image, symbol = self.image(code, {8192:"CMethod::Convert(ESample)" if method else "Convert(ESample)",
            12288:"CWriter::WriteTokenValue(int, int)"})
        image.by_address = {8192:{"raw":"_ZN7CMethod7ConvertE7ESample" if method else "_Z7Convert7ESample"}}
        image.name = lambda s:"CSample::WriteMembers(CWriter&)"
        return extract_serializer(image,symbol,{16:"choice"})["fields"][0]

    def test_named_byvalue_enum_recovers_real_byte_storage(self):
        f = self.enum_field()
        self.assertEqual((f["kind"],f["linux_off"],f["enum_type"]),("u8",32,"ESample"))

    def test_member_function_hidden_this_not_mistaken_for_enum_argument(self):
        self.assertIsNone(self.enum_field(method=True)["linux_off"])

    def test_normal_cfg_excludes_post_return_exception_cleanup(self):
        from value_recovery import normal_flow
        image, symbol = self.image(b"\xc3\xe8\0\0\0\0")
        body, evidence = normal_flow(image, symbol)
        self.assertEqual(len(body), 1)
        self.assertTrue(evidence["complete"])
        self.assertEqual(evidence["unreachable_instructions"], 1)

    def test_actual_branch_to_cleanup_is_not_ignored(self):
        from value_recovery import normal_flow
        image, symbol = self.image(bytes.fromhex("7401c3c3"))
        _, evidence = normal_flow(image, symbol)
        self.assertEqual(sorted(evidence["return_rvas"]), [4098, 4099])

    def test_invalid_boundary_and_indirect_tail_fail_closed(self):
        from value_recovery import normal_flow
        for code in (bytes.fromhex("ebffc3"), bytes.fromhex("ffe0")):
            image, symbol = self.image(code)
            self.assertFalse(normal_flow(image, symbol)[1]["complete"])

    def human_origin(self, load):
        from script_candidates.semantic_audit import native_neighborhood
        code = load + b"\xe8" + struct.pack("<i",8192-(4096+len(load)+5)) + b"\xc3"
        image, symbol = self.image(code, {8192:"CGameState::AccessHuman(int)"}, "CExample::IsValid const(CString*)")
        image.by_address = {4096:symbol}
        image.read = lambda *_: b""
        c = sample([field("human","i32")]); c["is_valid"] = 4096
        s = catalog(c)
        before = copy.deepcopy(s)
        result = native_neighborhood(image,c,s)
        self.assertEqual(s,before)
        return result

    def test_native_human_slot_requires_actual_argument_flow_and_preserves_sdk(self):
        result = self.human_origin(bytes.fromhex("8b771c"))
        self.assertEqual(result["native_parameter_sources"]["human"]["kind"],"session_human_slot")

    def test_human_field_name_without_argument_flow_does_not_infer_session_slot(self):
        self.assertFalse(self.human_origin(bytes.fromhex("31f6"))["native_parameter_sources"])

    def test_inline_string_requires_all_stores_and_no_conflict(self):
        from value_recovery import _inline_string
        f = field("anything", "string", linux_off=32)
        r = {"writes": [{"offset": 32+d, "width": w, "value": v, "evidence_rva": 10+d}
             for d,w,v in [(0,4,["constant",0]),(8,8,["constant",0]),(16,8,["object",64]),
                            (24,8,["constant",0]),(32,1,["constant",0])]]}
        self.assertIsNotNone(_inline_string(f, r, 80, 900))
        r["writes"].append({"offset":48,"width":8,"value":["constant",0],"evidence_rva":999})
        self.assertIsNone(_inline_string(f, r, 80, 900))

    def test_native_text_copy_tracks_actual_constructor_argument(self):
        from value_recovery import copy_parameter_bindings
        # this += 40; source = arg #2; tail-call native copy constructor.
        code = bytes.fromhex("4883c7284889ce") + b"\xe9" + struct.pack("<i", 8192-(4096+12))
        raw = "_ZN22CChangeArmyNameCommandC1E7TPdxRefI8CCountryES0_I5CArmyERK15CPersistentName"
        image, symbol = self.image(code, {8192:"CPersistentName::{base ctor}(CPersistentName const&)"}, raw)
        rows = copy_parameter_bindings(image, symbol, {"CPersistentName":88})
        self.assertEqual(rows[0]["offset"], 40)
        self.assertEqual(rows[0]["parameter_index"], 2)

    def test_unrelated_copy_function_cannot_bind_text(self):
        from value_recovery import copy_parameter_bindings
        code = bytes.fromhex("4883c7284889ce") + b"\xe9" + struct.pack("<i", 8192-(4096+12))
        image, symbol = self.image(code, {8192:"CUnrelated::Copy()"},
            "_ZN22CChangeArmyNameCommandC1E7TPdxRefI8CCountryES0_I5CArmyERK15CPersistentName")
        self.assertFalse(copy_parameter_bindings(image, symbol, {"CPersistentName":88}))

    def test_historical_true_without_destroy_or_build_cannot_change_lifecycle(self):
        from value_recovery import paired_lifecycle_evidence
        report = {"build_id":"exact", "commands":[{"attempts":[{"native_is_valid":True}]}]}
        self.assertFalse(paired_lifecycle_evidence({"build_id":"exact"}, [("old",report)]))

    def test_paired_lifecycle_does_not_import_world_legality(self):
        from value_recovery import paired_lifecycle_evidence
        a = {"build_id":"exact","structure_checked":True,"constructed_from_generated_metadata":True,
             "destroyed":True,"submitted":False,"status":"native_invalid", "class_name":"CAny",
             "factory_rva":1,"vtable_rva":2,"object_size":40,"world_identity":999}
        report = {"build_id":"exact", "commands":[{"attempts":[a]}]}
        values = paired_lifecycle_evidence({"build_id":"exact"},[("old",report)])
        self.assertFalse(values[("CAny",1,2,40)][0]["legality_reused"])

    def test_paired_factory_destroy_is_usable_even_when_population_was_not_tested(self):
        from value_recovery import paired_lifecycle_evidence
        a = {"build_id":"exact","structure_checked":True,"constructed_from_generated_metadata":True,
             "destroyed":True,"submitted":False,"status":"not_tested", "class_name":"CAny",
             "factory_rva":1,"vtable_rva":2,"object_size":40,"native_is_valid":None}
        report = {"build_id":"exact", "commands":[{"attempts":[a]}]}
        values = paired_lifecycle_evidence({"build_id":"exact"},[("old",report)])
        self.assertIn(("CAny",1,2,40),values)
        self.assertIsNone(values[("CAny",1,2,40)][0]["historical_native_is_valid"])

    def array_state(self, prefix):
        from array_recovery import argument_locations
        pc=4096+len(prefix)
        code=prefix+b"\xe8"+struct.pack("<i",0x9000-(pc+5))+b"\xc3"
        image,symbol=self.image(code)
        states,complete=argument_locations(image.instructions(symbol))
        self.assertTrue(complete)
        return states[pc]

    def test_native_array_data_and_count_reach_the_actual_writer(self):
        from array_recovery import proven_pair
        state=self.array_state(bytes.fromhex("4889fb488b53308b4b3c"))
        self.assertTrue(proven_pair(state,40))
        self.assertFalse(proven_pair(state,32))

    def test_array_empty_branch_can_join_only_proven_data_count_locations(self):
        from array_recovery import proven_pair
        state=self.array_state(bytes.fromhex("4889fb85f67409488b53308b4b3ceb0431d231c9"))
        self.assertTrue(proven_pair(state,40))

    def test_array_opaque_call_kills_volatile_argument_origins(self):
        from array_recovery import proven_pair
        state=self.array_state(bytes.fromhex("4889fb488b53308b4b3c")+b"\xe8\0\0\0\0")
        self.assertFalse(proven_pair(state,40))

    def test_pointer_or_this_truncation_is_not_a_valid_array_origin(self):
        from array_recovery import proven_pair
        for prefix in ("4889fb488b53308b4b3c89d2", "89fb488b53308b4b3c"):
            self.assertFalse(proven_pair(self.array_state(bytes.fromhex(prefix)),40))

    def test_empty_factory_defaults_do_not_identify_a_serializer_field(self):
        from array_recovery import proven_pair
        self.assertFalse(proven_pair(self.array_state(bytes.fromhex("31d231c9")),40))


class NestedSnapshotTests(unittest.TestCase):
    def parser(self, nodes):
        class Parser:
            def parse(self, *_): return nodes
        return Parser()

    def test_unique_manager_container_preserves_generation(self):
        from script_candidates.snapshot import nested_database
        block = Node("83886080",children=(Node("type",value="x"),))
        objects, evidence = nested_database(self.parser((Node("collection",children=(block,)),)), "", "manager")
        self.assertIn(83886080,objects)
        self.assertEqual(evidence["collection_path"], ["manager","collection"])

    def test_ambiguous_child_tables_are_not_guessed(self):
        from script_candidates.snapshot import nested_database
        nodes = (Node("a",children=(Node("0",children=()),)), Node("b",children=(Node("1",children=()),)))
        objects, evidence = nested_database(self.parser(nodes), "", "manager")
        self.assertFalse(objects)
        self.assertFalse(evidence["absence_proven"])

    def test_numeric_counter_map_is_not_mistaken_for_empty_object_database(self):
        from script_candidates.snapshot import nested_database
        objects, evidence = nested_database(self.parser((Node("0",value="12"),)), "", "manager")
        self.assertFalse(objects)
        self.assertFalse(evidence["absence_proven"])

    def test_explicit_empty_collection_not_unmapped_schema(self):
        from script_candidates.snapshot import nested_database
        objects, evidence = nested_database(self.parser((Node("table",children=()),)), "", "manager")
        self.assertFalse(objects)
        self.assertTrue(evidence["absence_proven"])

    def test_duplicate_generation_identity_rejected(self):
        from script_candidates.snapshot import nested_database
        objects, evidence = nested_database(self.parser((Node("5",children=()),Node("5",children=()))), "", "db")
        self.assertFalse(objects)
        self.assertEqual(evidence["schema_resolution"], "duplicate_object_identity")

    def test_native_typed_manager_evidence_disambiguates_child_tables(self):
        from script_candidates.snapshot import nested_database
        nodes = (Node("objects",children=(Node("83886080",children=()),)),
                 Node("counters",children=(Node("0",children=()),)))
        result, evidence = nested_database(self.parser(nodes), "", "manager", native_binding={"collection_key":"objects"})
        self.assertEqual(list(result),[83886080])
        self.assertIsNotNone(evidence["native_collection_binding"])


class DefinitionFamilyDiscoveryTests(unittest.TestCase):
    def test_existing_sdk_evidence_refuses_overwrite_before_loading_binary(self):
        from linux_elf import recover_linux
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            p = root / "linux_sdk.json"
            p.write_text("original-evidence",encoding="utf-8")
            with self.assertRaises(FileExistsError):
                recover_linux(root/"does-not-exist",root,{})
            self.assertEqual(p.read_text(encoding="utf-8"),"original-evidence")

    def test_inline_scripts_are_not_ambiguous_definition_databases(self):
        from script_candidates.planner import discover_definition_families
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            for directory in ("colony_types","inline_scripts/colony_types","megastructures","inline_scripts/megastructures"):
                path = root / "common" / directory
                path.mkdir(parents=True)
                (path / "sample.txt").write_text("definition={}",encoding="utf-8")
            s = {"commands":[{"fields":[{"definition_type":"CColonyType"},{"definition_type":"CMegaStructureType"}]}]}
            result = discover_definition_families(s,root)
            self.assertEqual(result["CColonyType"],"colony_types")
            self.assertEqual(result["CMegaStructureType"],"megastructures")


if __name__ == "__main__":
    unittest.main()
