from __future__ import annotations

import importlib.util
import struct
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
HAS_DISASSEMBLER = all(
    importlib.util.find_spec(m) for m in ("capstone", "elftools", "itanium_demangler")
)


@unittest.skipUnless(HAS_DISASSEMBLER, "install sdk_recovery/requirements.txt")
class RecoveryEvidenceTests(unittest.TestCase):
    def image(
        self, code: bytes, name="CSample::WriteCommandMembers(CWriter&)", targets=None
    ):
        from capstone import CS_ARCH_X86, CS_MODE_64, Cs

        md = Cs(CS_ARCH_X86, CS_MODE_64)
        md.detail = True

        class Image:
            def __init__(self):
                self.by_address = {0x1000: {"rva": 0x1000, "size": len(code)}}
                self.symbols = []

            def read(self, rva, size):
                if 0x1000 <= rva and rva + size <= 0x1000 + len(code):
                    return code[rva - 0x1000 : rva - 0x1000 + size]
                return b""

            def instructions(self, symbol, limit=65536):
                return list(md.disasm(code[:limit], symbol["rva"]))

            def name(self, _):
                return name

            def target_name(self, rva):
                return (targets or {}).get(rva, "")

        result = Image()
        result.md = md
        return result

    def test_indirect_token_getter_is_not_a_zero_token(self):
        from recovery_plans import token_evidence

        code = (
            bytes.fromhex("48 8d 05")
            + struct.pack("<i", 0x2000 - 0x1007)
            + bytes.fromhex("8b 00 c3 90 90 90 90 90 90")
        )
        result = token_evidence(
            self.image(code, targets={0x2000: "CCommandHelper<CTest>::_Token"}), 0x1000
        )
        self.assertEqual(result["kind"], "module_global")
        self.assertEqual(result["global_rva"], 0x2000)
        self.assertIsNone(result["token"])
        self.assertEqual(
            token_evidence(self.image(b"\x90" * 16), 0x1000)["kind"], "unresolved"
        )

    def test_native_factory_initialization_and_unknown_call_are_distinct(self):
        from recovery_plans import factory_evidence

        code = bytes.fromhex("bf 28 00 00 00 e8") + struct.pack("<i", 0x2000 - 0x100A)
        code += bytes.fromhex("48 8d 0d") + struct.pack("<i", 0x3000 - 0x1011)
        code += bytes.fromhex("48 89 08 c7 40 20 ff ff ff ff c3")
        im = self.image(code, targets={0x2000: "operator new(unsigned long)"})
        r = factory_evidence(im, {"rva": 0x1000})
        self.assertEqual(r["allocations"], 1)
        self.assertEqual(r["writes"][0]["value"], ["rva", 0x3000])
        self.assertEqual(r["writes"][1]["offset"], 0x20)
        self.assertFalse(r["external_writes"])
        unknown = factory_evidence(self.image(code), {"rva": 0x1000})
        self.assertEqual(unknown["allocations"], 0)
        self.assertTrue(unknown["other_calls"])

    def test_native_counter_record_identity_is_evidence_not_a_candidate(self):
        from recovery_plans import native_counter_record_identity

        for owner, record in (("CMarket", "SMonthlyTradeData"), ("COwner", "SRecord")):
            code = bytes.fromhex("4889f28b47608d4801894f608946288b775c4883c748e9")
            code += struct.pack("<i", 0x2000 - (0x1000 + len(code) + 4))
            callee = (
                f"{record}& CPdxArray<{record}, int>::InsertAtEmplace<{record} const&>"
                f"(int, {record} const&)"
            )
            image = self.image(code, f"{owner}::AddRecord({record}&)", {0x2000: callee})
            found = native_counter_record_identity(
                image, {"rva": 0x1000, "size": len(code)}
            )
            self.assertEqual(found["owner_class"], owner)
            self.assertEqual(found["record_class"], record)
            self.assertEqual(found["counter_offset"], 0x60)
            self.assertEqual(found["record_identity_offset"], 0x28)
            self.assertEqual(found["array_offset"], 0x48)
            self.assertEqual(found["array_count_offset"], 0x5C)
            self.assertFalse(found["research_callable"])
            self.assertNotIn("scalar_candidates", found)

    def test_native_counter_record_requires_complete_and_typed_insert(self):
        from recovery_plans import native_counter_record_identity

        code = bytes.fromhex("4889f28b47608d4801894f608946288b775c4883c748e9")
        code += struct.pack("<i", 0x2000 - (0x1000 + len(code) + 4))
        target = "SRecord& CPdxArray<SRecord, int>::InsertAtEmplace<SRecord const&>(int, SRecord const&)"

        def recover(data=code, name="COwner::AddRecord(SRecord&)", callee=target):
            return native_counter_record_identity(
                self.image(data, name, {0x2000: callee}),
                {"rva": 0x1000, "size": len(data)},
            )

        self.assertIsNotNone(recover())
        self.assertIsNone(recover(code + b"\x90"))
        self.assertIsNone(recover(code[:-1]))
        self.assertIsNone(recover(name="COwner::AddRecord(SRecord const&)"))
        self.assertIsNone(recover(callee=target.replace("SRecord", "SOther")))
        self.assertIsNone(recover(callee=""))

    def test_native_counter_record_rejects_unproven_counter_and_record_stores(self):
        from recovery_plans import native_counter_record_identity

        code = bytes.fromhex("4889f28b47608d4801894f608946288b775c4883c748e9")
        code += struct.pack("<i", 0x2000 - (0x1000 + len(code) + 4))
        target = "SRecord& CPdxArray<SRecord, int>::InsertAtEmplace<SRecord const&>(int, SRecord const&)"
        # Argument forwarding, increment, counter destination, identity source,
        # alignment, count and array base each belong to the complete proof.
        for index, value in (
            (2, 0xFA),
            (8, 2),
            (11, 0x64),
            (13, 0x4E),
            (14, 0x29),
            (17, 0x60),
            (21, 0x40),
        ):
            bad = bytearray(code)
            bad[index] = value
            self.assertIsNone(
                native_counter_record_identity(
                    self.image(
                        bytes(bad), "COwner::AddRecord(SRecord&)", {0x2000: target}
                    ),
                    {"rva": 0x1000, "size": len(bad)},
                ),
                (index, value),
            )

    def test_generation_checked_accessor_recovers_type_and_id_offset(self):
        from recovery_plans import recover_databases

        code = bytes.fromhex("48 8b 05") + struct.pack("<i", 0x2000 - 0x1007)
        code += bytes.fromhex(
            "48 85 c0 74 26 8b 0f 89 ca 81 e2 ff ff ff 00 3b 50 20 73 17 48 8b 40 18 48 c1 e2 04 48 8b 44 10 08 48 85 c0 74 05 39 48 18 74 07 48 8b 05"
        )
        code += struct.pack("<i", 0x3000 - 0x1039) + b"\xc3"
        im = self.image(
            code,
            name="TPdxRef<CPlanet>::operator->()",
            targets={
                0x2000: "TPdxRef<CPlanet>::_pDatabase",
                0x3000: "TPdxNullObject<CPlanet>::_pInstance",
            },
        )
        im.symbols = [
            {"rva": 0x1000, "size": len(code), "type": "STT_FUNC", "raw": "TPdxRefptEv"}
        ]
        result = recover_databases(im)
        self.assertEqual(result[0]["id_offset"], 0x18)
        # Removing the generation comparison must not produce a resolver.
        bad = bytearray(code)
        bad[45:48] = b"\x90" * 3
        im2 = self.image(
            bytes(bad),
            name="TPdxRef<CPlanet>::operator->()",
            targets={
                0x2000: "TPdxRef<CPlanet>::_pDatabase",
                0x3000: "TPdxNullObject<CPlanet>::_pInstance",
            },
        )
        im2.symbols = im.symbols
        self.assertEqual(recover_databases(im2), [])

    def test_access_instance_requires_full_generation_guard_and_named_globals(self):
        from recovery_plans import recover_databases, recover_instance_accessors

        code = bytes.fromhex("48 8b 05") + struct.pack("<i", 0x2000 - 0x1007)
        code += bytes.fromhex(
            "48 85 c0 74 26 89 f1 81 e1 ff ff ff 00 3b 48 20 73 19 "
            "48 8b 40 18 89 c9 48 c1 e1 04 48 8b 44 08 08 48 85 c0 74 05 "
            "39 70 08 74 07 48 8b 05"
        )
        code += struct.pack("<i", 0x3000 - 0x1039) + b"\xc3"

        def image(data, cls="CPlanet"):
            im = self.image(
                data,
                name=f"{cls}::AccessInstance(CCountry&, unsigned int)",
                targets={
                    0x2000: "TPdxRef<CPlanet>::_pDatabase",
                    0x3000: "TPdxNullObject<CPlanet>::_pInstance",
                },
            )
            im.symbols = [
                {
                    "raw": "AccessInstance",
                    "type": "STT_FUNC",
                    "rva": 0x1000,
                    "size": len(data),
                }
            ]
            return im

        result = recover_instance_accessors(image(code))
        self.assertEqual(result[0x1000]["id_argument_register"], "rsi")
        self.assertEqual(result[0x1000]["id_offset"], 8)
        self.assertEqual(recover_databases(image(code))[0]["database_rva"], 0x2000)
        self.assertFalse(recover_instance_accessors(image(code, "COther")))
        for offset in (10, 24, 25, 45, 48):
            bad = bytearray(code)
            bad[offset] = 0x90
            self.assertFalse(recover_instance_accessors(image(bytes(bad))))

    def test_validator_field_type_follows_only_a_local_direct_checked_accessor(self):
        from recovery_plans import inline_database_witnesses

        accessor = {
            0x2000: {
                "class": "CPlanet",
                "id_offset": 8,
                "resolver_rva": 0x2000,
                "database_rva": 0x3000,
                "null_rva": 0x4000,
                "id_argument_register": "rsi",
            }
        }

        def recover(prefix, extra=b"", call=True):
            code = bytes.fromhex("41 56 49 89 fe") + prefix + extra
            code += (
                b"\xe8" + struct.pack("<i", 0x2000 - (0x1000 + len(code) + 5))
                if call
                else bytes.fromhex("ff d0")
            )
            code += bytes.fromhex("41 5e c3")
            return inline_database_witnesses(
                self.image(code), {"rva": 0x1000}, accessor
            )

        load = bytes.fromhex("41 8b 76 20 48 89 df")
        result = recover(load)
        self.assertEqual(result[0]["source_offset"], 0x20)
        self.assertEqual(result[0]["class"], "CPlanet")
        self.assertEqual(result[0]["accessor_rva"], 0x2000)
        self.assertFalse(recover(load, bytes.fromhex("31 f6")))
        self.assertFalse(recover(load, bytes.fromhex("85 c0 74 00")))
        self.assertFalse(recover(load, call=False))
        self.assertFalse(recover(bytes.fromhex("49 8b 76 20 48 89 df")))
        self.assertFalse(recover(bytes.fromhex("45 89 fe") + load))

    def test_scoped_lookup_evidence_does_not_become_a_global_reference(self):
        from recovery_plans import inline_database_witnesses

        code = bytes.fromhex("41 56 49 89 fe 41 8b 76 20 48 89 df e8")
        code += struct.pack("<i", 0x2000 - (0x1000 + len(code) + 4)) + bytes.fromhex(
            "41 5e c3"
        )
        for cls, kind in (
            ("CPointOfInterest", "country_member_value_not_TPdxRef"),
            (
                "CActiveEventChain",
                "loaded_definition_index_to_country_member_not_TPdxRef",
            ),
        ):
            scoped = {
                0x2000: {
                    "class": cls,
                    "id_argument_register": "rsi",
                    "lookup_rva": 0x2000,
                    "identity_kind": kind,
                }
            }
            notes = []
            global_refs = inline_database_witnesses(
                self.image(code),
                {"rva": 0x1000},
                scoped_accessors=scoped,
                scoped_findings=notes,
            )
            self.assertEqual(global_refs, [])
            self.assertEqual(notes[0]["source_offset"], 0x20)
            self.assertEqual(notes[0]["call_target_rva"], 0x2000)
            self.assertEqual(notes[0]["identity_kind"], kind)
            self.assertEqual(notes[0]["caller_country_binding"], "not_recovered")

    def test_conditional_true_serializer_still_recovers_boolean_storage(self):
        from linux_elf import extract_serializer

        code = bytes.fromhex(
            "53 48 89 fb 80 7b 24 00 74 10 be 23 01 00 00 ba 01 00 00 00"
        )
        code += b"\xe9" + struct.pack("<i", 0x2000 - (0x1000 + len(code) + 5)) + b"\xc3"
        r = extract_serializer(
            self.image(code, targets={0x2000: "CWriter::Write(int, bool)"}),
            {"rva": 0x1000},
            {0x123: "pinned"},
        )
        self.assertEqual(r["fields"][0]["linux_off"], 0x24)
        self.assertIsNotNone(r["fields"][0]["conditional_bool"])

    def wrapper_address_field(self, seed, arithmetic, *, indirect_offset=16):
        from linux_elf import extract_serializer

        code = bytes.fromhex("4889fb") + seed + arithmetic
        code += bytes.fromhex("4889f7be6b2c0000e8")
        code += struct.pack("<i", 0x2000 - (0x1000 + len(code) + 4))
        code += b"\xc3"
        image = self.image(
            code,
            name="CSample::CSerializer::WriteMembers(CWriter&)",
            targets={
                0x2000: "void CWriter::Write<CShipDesign>(int, TPdxRef<CShipDesign> const&)"
            },
        )
        return extract_serializer(
            image,
            {"rva": 0x1000},
            {0x2C6B: "design"},
            indirect_this_offset=indirect_offset,
        )["fields"][0]

    def test_wrapper_member_address_accepts_adjacent_constant_plus_proven_pointer(self):
        for offset in (0x200, 0x530, 0x534):
            field = self.wrapper_address_field(
                b"\xba" + struct.pack("<I", offset), bytes.fromhex("48035310")
            )
            self.assertEqual(
                (field["linux_off"], field["kind"], field["ref"], field["confidence"]),
                (offset, "ref", "CShipDesign", "direct_dataflow"),
            )

    def test_wrapper_member_address_rejects_unknown_width_index_scope_and_provenance(
        self,
    ):
        seed = bytes.fromhex("ba30050000")
        for initial, arithmetic, indirect in (
            (seed, bytes.fromhex("48035318"), 16),
            (seed, bytes.fromhex("035310"), 16),
            (seed, bytes.fromhex("4803544b10"), 16),
            (seed + b"\x90", bytes.fromhex("48035310"), 16),
            (bytes.fromhex("89ca"), bytes.fromhex("48035310"), 16),
            (bytes.fromhex("baffffffff"), bytes.fromhex("48035310"), 16),
            (seed, bytes.fromhex("48035310"), None),
        ):
            with self.subTest(
                initial=initial, arithmetic=arithmetic, indirect=indirect
            ):
                self.assertIsNone(
                    self.wrapper_address_field(
                        initial, arithmetic, indirect_offset=indirect
                    )["linux_off"]
                )

    def test_native_assignment_rebuild_is_a_population_dependency_not_permission(self):
        from emit_ogas import field_layout, population_layout_complete
        from recovery_plans import native_assignment_dependency

        body = bytearray.fromhex(
            "534889fb8b86300500008987300500008b86340500008987340500008b862c050000"
            "89872c050000488b86200500004889872005000048c7470800000000e8edbdffff4889d85bc3"
        )
        struct.pack_into("<i", body, len(body) - 9, 0x2000 - (0x1000 + len(body) - 5))
        name = "CShipDesignImplementation::operator=(CShipDesignImplementation const&)"
        im = self.image(
            bytes(body),
            name=name,
            targets={0x2000: "CBaseDesignImplementation::RecalcSpecialValues()"},
        )
        proof = native_assignment_dependency(im, im.by_address[0x1000])
        self.assertEqual(proof["rebuild_rva"], 0x2000)
        self.assertEqual(
            [m["offset"] for m in proof["copied_members"]], [0x530, 0x534, 0x52C, 0x520]
        )
        complete = {
            "fields": [
                {
                    "name": "country",
                    "kind": "ref",
                    "ref": "CCountry",
                    "linux_off": 28,
                    "confidence": "direct_dataflow",
                }
            ],
            "size": 32,
        }
        self.assertTrue(population_layout_complete(complete, "linux-x86_64"))
        field = complete["fields"][0]
        self.assertEqual(
            field_layout({**field, "native_assignment_required": True}, "linux-x86_64"),
            ("ref", 28, 4, False),
        )
        self.assertFalse(
            population_layout_complete(
                {**complete, "nested_recovery_gaps": [proof]}, "linux-x86_64"
            )
        )
        for bad in (
            bytes(body[:-1]),
            bytes(body) + b"\x90",
            bytes(body[:12]) + b"\x90" + bytes(body[13:]),
        ):
            im = self.image(
                bad,
                name=name,
                targets={0x2000: "CBaseDesignImplementation::RecalcSpecialValues()"},
            )
            self.assertIsNone(native_assignment_dependency(im, im.by_address[0x1000]))
        im = self.image(bytes(body), name=name, targets={0x2000: "CUnknown::Run()"})
        self.assertIsNone(native_assignment_dependency(im, im.by_address[0x1000]))

    def test_enum_table_is_a_domain_not_a_guessed_integer_range(self):
        from recovery_plans import recover_enum_values

        # movsxd rcx,[rdi]; mov eax,99; cmp rcx,2; ja ret;
        # lea rax,[rip+table]; mov eax,[rax+rcx*4]; ret; table[3]
        code = bytes.fromhex(
            "48 63 0f b8 63 00 00 00 48 83 f9 02 77 0a 48 8d 05 04 00 00 00 8b 04 88 c3"
        ) + struct.pack("<III", 31, 41, 59)
        im = self.image(code)
        im.instructions = lambda symbol, limit=65536: list(
            im.md.disasm(code[:25], symbol["rva"])
        )
        r = recover_enum_values(im, 0x1000)
        self.assertEqual(
            [(v["value"], v["token"]) for v in r], [(0, 31), (1, 41), (2, 59)]
        )

    def test_byte_enum_token_table_retains_guard_and_register_checks(self):
        from recovery_plans import recover_enum_values

        code = bytes.fromhex(
            "48 0f be 0f b8 63 00 00 00 48 83 f9 02 77 0a "
            "48 8d 05 04 00 00 00 8b 04 88 c3"
        ) + struct.pack("<III", 31, 41, 59)

        def recover(data):
            im = self.image(data)
            im.instructions = lambda symbol, limit=65536: list(
                im.md.disasm(data[:26], symbol["rva"])
            )
            return recover_enum_values(im, 0x1000)

        self.assertEqual([r["token"] for r in recover(code)], [31, 41, 59])
        # A different return register or guard edge is not the recognized ABI.
        self.assertFalse(recover(code.replace(b"\x8b\x04\x88", b"\x8b\x0c\x88")))
        self.assertFalse(recover(code.replace(b"\x77\x0a", b"\x77\x09")))
        self.assertFalse(recover(code[:-1]))
        overwritten_index = (
            code.replace(b"\x48\x0f\xbe\x0f", b"\x48\x0f\xbe\x07")
            .replace(b"\x48\x83\xf9\x02", b"\x48\x83\xf8\x02")
            .replace(b"\x8b\x04\x88", b"\x8b\x04\x80")
        )
        self.assertFalse(recover(overwritten_index))

    def test_relative_enum_switch_excludes_dynamic_leaves_and_default_holes(self):
        from recovery_plans import recover_enum_values

        # Four guarded indices. Leaves: inherited token, constant token,
        # runtime-dependent memory load, and the invalid/default branch.
        code = bytes.fromhex(
            "8b 0f 48 83 f9 03 77 23 b8 1f 00 00 00 "
            "48 8d 15 1d 00 00 00 48 63 0c 8a 48 01 d1 ff e1 "
            "c3 b8 29 00 00 00 c3 8b 05 00 00 00 00 c3 b8 63 00 00 00 c3"
        ) + struct.pack("<iiii", 29 - 49, 30 - 49, 36 - 49, 43 - 49)

        def recover(data):
            im = self.image(data)
            im.instructions = lambda symbol, limit=65536: list(
                im.md.disasm(data[:49], symbol["rva"])
            )
            return recover_enum_values(im, 0x1000)

        result = recover(code)
        self.assertEqual([(r["value"], r["token"]) for r in result], [(0, 31), (1, 41)])
        self.assertTrue(all(r["branch_target_rva"] >= 0x101D for r in result))
        self.assertTrue(all("constant_leaf" in r["evidence"] for r in result))
        self.assertFalse(recover(code[:-1]))
        bad_target = bytearray(code)
        struct.pack_into("<i", bad_target, 49, 0x4000)
        self.assertFalse(recover(bytes(bad_target)))
        # Invalid branch destinations and unproven jump-table register flow.
        self.assertFalse(recover(code.replace(b"\x77\x23", b"\x77\x00")))
        self.assertFalse(recover(code.replace(b"\x48\x01\xd1", b"\x48\x01\xc1")))
        self.assertFalse(recover(code.replace(b"\x48\x01\xd1", b"\x66\x01\xd1")))
        loop = bytearray(code)
        loop[30:36] = bytes.fromhex("e9 fb ff ff ff 90")
        self.assertEqual(
            [(r["value"], r["token"]) for r in recover(bytes(loop))], [(0, 31)]
        )

    def test_definition_lookup_requires_a_bounded_native_pointer_array(self):
        from recovery_plans import definition_lookup_evidence

        code = bytes.fromhex("48 8b 35") + struct.pack("<i", 0x3000 - 0x1007)
        code += bytes.fromhex("8b 4f 14 48 8b 5f 08 31 d2 48 8b 04 d3 39 ca 75 f8 c3")
        image = self.image(
            code, targets={0x3000: "TPdxNullObject<CDefinition>::_pInstance"}
        )
        r = definition_lookup_evidence(image, {"rva": 0x1000}, "CDefinition")
        self.assertEqual((r["data_offset"], r["count_offset"]), (8, 20))
        bad = code.replace(bytes.fromhex("39 ca 75 f8"), b"\x90" * 4)
        self.assertIsNone(
            definition_lookup_evidence(
                self.image(
                    bad, targets={0x3000: "TPdxNullObject<CDefinition>::_pInstance"}
                ),
                {"rva": 0x1000},
                "CDefinition",
            )
        )

    def test_quantity_candidate_requires_a_proven_false_guard_edge(self):
        from recovery_plans import positive_quantity_guards

        code = bytes.fromhex("83 7f 24 00 7e 03 b0 01 c3 31 c0 c3")
        result = positive_quantity_guards(self.image(code), {"rva": 0x1000})
        self.assertEqual(result[0x24]["value"], 1)
        unproven = code[:-3] + bytes.fromhex("b0 01 c3")
        self.assertFalse(
            positive_quantity_guards(self.image(unproven), {"rva": 0x1000})
        )

    def test_constructor_parameter_ast_rejects_unknown_abi_and_tracks_refs(self):
        from recovery_plans import constructor_parameter_evidence

        code = bytes.fromhex("89 77 1c 89 57 20 c3")
        symbol = {
            "rva": 0x1000,
            "raw": "_ZN18CHireLeaderCommandC1E7TPdxRefI8CCountryES0_I7CLeaderE",
        }
        rows = constructor_parameter_evidence(self.image(code), symbol)
        self.assertFalse(
            constructor_parameter_evidence(
                self.image(code), {**symbol, "raw": symbol["raw"].replace("C1E", "C2E")}
            )
        )
        self.assertEqual(
            [(r["offset"], r["parameter_type"]) for r in rows],
            [(0x1C, "TPdxRef<CCountry>"), (0x20, "TPdxRef<CLeader>")],
        )
        self.assertFalse(
            constructor_parameter_evidence(
                self.image(code), {**symbol, "raw": "_ZN18CHireLeaderCommandC1Eif"}
            )
        )
        self.assertFalse(
            constructor_parameter_evidence(
                self.image(code), {**symbol, "raw": "_ZN18CHireLeaderCommandC1E4Blob"}
            )
        )

    def test_callsite_literals_do_not_cross_branches_or_populate_ids(self):
        from callsite_arguments import apply_callsite_evidence, recover_callsites

        prefix = bytes.fromhex("b9 01 00 00 00")
        code = prefix + b"\xe8" + struct.pack("<i", 0x2000 - 0x100A) + b"\xc3"
        image = self.image(code)
        image.data, image.segments = code, [(0x1000, 0, len(code))]
        image.symbols = [{"type": "STT_FUNC", "rva": 0x1000, "size": len(code)}]
        rows = recover_callsites(image, {0x2000})
        self.assertEqual(rows[0]["register_literals"]["rcx"]["value"], 1)
        declaration = {
            "constructor_rva": 0x2000,
            "parameter_index": 2,
            "width": 4,
            "dereferenced": False,
        }
        fields = [
            {"name": n, "kind": "i32", "constructor_parameter_evidence": [declaration]}
            for n in ("claims", "id")
        ]
        catalog = {
            "constructor_callsites": rows,
            "commands": [{"population_fields": fields}],
        }
        apply_callsite_evidence(catalog)
        self.assertEqual(fields[0]["scalar_candidates"][0]["value"], 1)
        self.assertNotIn("scalar_candidates", fields[1])
        branch_prefix = prefix + bytes.fromhex("85 c0 74 00")
        code = (
            branch_prefix
            + b"\xe8"
            + struct.pack("<i", 0x2000 - (0x1000 + len(branch_prefix) + 5))
            + b"\xc3"
        )
        image = self.image(code)
        image.data, image.segments = code, [(0x1000, 0, len(code))]
        image.symbols = [{"type": "STT_FUNC", "rva": 0x1000, "size": len(code)}]
        rows = recover_callsites(image, {0x2000})
        self.assertNotIn("rcx", rows[0]["register_literals"])


class PopulationPlanTests(unittest.TestCase):
    def test_alignment_before_proven_embedded_vptr_is_not_an_unknown_payload(self):
        from emit_ogas import population_layout_complete

        command = {
            "size": 64,
            "fields": [],
            "population_fields": [
                {
                    "name": "resource",
                    "kind": "string",
                    "indirect": True,
                    "definition_type": "CResource",
                    "linux_off": 40,
                    "confidence": "direct_dataflow",
                },
                {
                    "name": "mode",
                    "kind": "i32",
                    "linux_off": 48,
                    "confidence": "direct_dataflow",
                },
                {
                    "name": "country",
                    "kind": "ref",
                    "linux_off": 52,
                    "confidence": "direct_dataflow",
                },
                {
                    "name": "quantity",
                    "kind": "i32",
                    "linux_off": 56,
                    "confidence": "direct_dataflow",
                },
            ],
            "factory_evidence": {
                "writes": [{"offset": 32, "width": 8, "value": ["rva", 1234]}]
            },
        }
        self.assertTrue(population_layout_complete(command, "linux-x86_64"))
        command["factory_evidence"]["writes"] = []
        self.assertFalse(population_layout_complete(command, "linux-x86_64"))
        command["factory_evidence"]["writes"] = [{"offset": 36, "width": 4}]
        self.assertFalse(population_layout_complete(command, "linux-x86_64"))
        command["factory_evidence"]["writes"] = [
            {"offset": 32, "width": 8},
            {"offset": 64, "width": 1},
        ]
        self.assertFalse(population_layout_complete(command, "linux-x86_64"))

    def test_native_value_alignment_dominates_smaller_initializer_store(self):
        from emit_ogas import population_layout_complete

        command = {
            "size": 88,
            "fields": [],
            "population_fields": [
                {
                    "name": "name",
                    "kind": "string",
                    "native_type": "CString",
                    "native_size": 48,
                    "assignment_rva": 1234,
                    "linux_off": 32,
                    "confidence": "direct_dataflow",
                },
                {
                    "name": "country",
                    "kind": "ref",
                    "linux_off": 80,
                    "confidence": "direct_dataflow",
                },
            ],
            "factory_evidence": {"writes": [{"offset": 32, "width": 4}]},
        }
        self.assertTrue(population_layout_complete(command, "linux-x86_64"))

    def test_native_factory_covered_hole_not_an_arbitrary_layout_relaxation(self):
        from emit_ogas import population_layout_complete

        f = {
            "name": "country",
            "kind": "ref",
            "linux_off": 0x28,
            "confidence": "direct_dataflow",
        }
        c = {
            "fields": [f],
            "size": 0x30,
            "factory_evidence": {"writes": [{"offset": 0x1C, "width": 12}]},
        }
        self.assertTrue(population_layout_complete(c, "linux-x86_64"))
        self.assertFalse(
            population_layout_complete({**c, "factory_evidence": {}}, "linux-x86_64")
        )
        self.assertFalse(
            population_layout_complete({**c, "fields": [f, f]}, "linux-x86_64")
        )

    def test_counter_identity_provenance_does_not_relax_population_audit(self):
        from audit_recovery import audit

        identity = {"record_class": "SRecord", "research_callable": False}
        command = {
            "class": "CTest",
            "token": 1,
            "factory": 1,
            "size": 0x20,
            "vtable": 1,
            "is_valid": 1,
            "deleting_destructor": 1,
            "token_getter": 1,
            "context_free_validator": True,
            "fields": [
                {
                    "name": "id",
                    "kind": "i32",
                    "linux_off": 0x1C,
                    "confidence": "direct_dataflow",
                    "width": 4,
                    "native_counter_record_identity": identity,
                }
            ],
        }
        sdk = {"build_id": "a", "platform": "linux-x86_64", "commands": [command]}
        result = audit(sdk, {"build_id": "a", "commands": []})["commands"][0]
        self.assertFalse(result["validation_static_eligible"])
        self.assertIn("parameter_semantics:id:i32", result["blockers"])
        self.assertEqual(
            result["fields"][0]["native_counter_record_identity"], identity
        )
        self.assertFalse(result["fields"][0]["enum_values"])

    def test_gap_audit_keeps_every_command_and_world_prerequisite(self):
        from audit_recovery import audit

        sdk = {
            "build_id": "a",
            "platform": "linux-x86_64",
            "object_databases": [{"class": "CResolution"}],
            "commands": [
                {
                    "class": "CTest",
                    "token": 1,
                    "factory": 1,
                    "size": 0x20,
                    "vtable": 1,
                    "is_valid": 1,
                    "deleting_destructor": 1,
                    "token_getter": 1,
                    "fields": [
                        {
                            "name": "resolution",
                            "kind": "ref",
                            "ref": "CResolution",
                            "linux_off": 0x1C,
                            "confidence": "direct_dataflow",
                            "validator_reference_evidence": [{"accessor_rva": 123}],
                        }
                    ],
                }
            ],
        }
        baseline = {
            "build_id": "a",
            "commands": [
                {
                    "status": "missing_parameters",
                    "reason": "no_live_candidate:CResolution",
                    "attempts": [{"class_name": "CTest"}],
                }
            ],
        }
        r = audit(sdk, baseline)
        self.assertEqual(len(r["commands"]), 1)
        self.assertTrue(r["commands"][0]["validation_static_eligible"])
        self.assertIn("CResolution", r["commands"][0]["scene_prerequisites"])
        self.assertEqual(
            r["commands"][0]["fields"][0]["validator_reference_evidence"],
            [{"accessor_rva": 123}],
        )
        self.assertEqual(r["new_native_calls"], 0)
        with self.assertRaises(ValueError):
            audit(sdk, {**baseline, "build_id": "b"})
        field = sdk["commands"][0]["fields"][0]
        for cls in ("CPointOfInterest", "CActiveEventChain"):
            field.update(kind="u32", scoped_reference_evidence=[{"class": cls}])
            unresolved = audit(sdk, baseline)["commands"][0]
            self.assertFalse(unresolved["validation_static_eligible"])
            self.assertIn(
                f"country_scoped_candidate_provider:{cls}", unresolved["blockers"]
            )
            self.assertIn(
                "country_scope_binding_unresolved:resolution", unresolved["blockers"]
            )
        note = {
            "class": "CActiveEventChain",
            "caller_country_binding": "generation_checked_command_country_reference",
            "evidence_rva": 100,
            "lookup_rva": 200,
            "call_target_rva": 200,
            "country_reference": {
                "class": "CActiveEventChain",
                "evidence": "complete_generation_checked_country_to_scoped_lookup",
                "country_generation_checked": True,
                "source_offset": field["linux_off"],
                "call_rva": 100,
                "lookup_rva": 200,
                "call_target_rva": 200,
            },
        }
        field["scoped_reference_evidence"] = [note]
        bound = audit(sdk, baseline)["commands"][0]
        self.assertNotIn(
            "country_scope_binding_unresolved:resolution", bound["blockers"]
        )
        self.assertIn(
            "country_scoped_candidate_provider:CActiveEventChain", bound["blockers"]
        )
        self.assertFalse(bound["validation_static_eligible"])
        note["country_reference"]["call_rva"] += 1
        self.assertIn(
            "country_scope_binding_unresolved:resolution",
            audit(sdk, baseline)["commands"][0]["blockers"],
        )


if __name__ == "__main__":
    unittest.main()
