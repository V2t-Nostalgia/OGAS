from __future__ import annotations

import struct
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from scoped_id_recovery import (
    recover_country_scoped_accessors,
    recover_scoped_validator_binding,
)


class CountryScopedRecoveryTests(unittest.TestCase):
    FORWARD = bytes.fromhex(
        "8b 4f 6c 85 c9 7e 1b 48 8b 57 60 31 ff 0f 1f 00 48 8b 04 fa "
        "39 70 18 74 10 48 83 c7 01 48 39 f9 75 ee 48 8b 05 37 56 31 03 c3"
    )
    REVERSE = bytes.fromhex(
        "8b 8f 9c 00 00 00 48 8b 97 90 00 00 00 0f 1f 00 85 c9 7e 13 "
        "48 8b 44 ca f8 48 83 c1 ff 66 39 b0 f0 03 00 00 75 ea c3 "
        "48 8b 05 8a 63 31 03 c3"
    )
    DEFINITION_JOIN = bytes.fromhex(
        "41 56 53 50 49 89 fe 85 f6 78 18 48 8b 05 66 95 31 03 "
        "39 70 5c 7e 0c 48 8b 40 50 89 f1 48 8b 1c c8 eb 07 "
        "48 8b 1d 3e 7c 31 03 48 8b 03 48 89 df ff 50 10 84 c0 74 2c "
        "49 63 8e 6c 24 00 00 48 85 c9 74 20 49 8b 96 60 24 00 00 "
        "48 c1 e1 03 31 f6 48 8b 04 32 48 39 58 18 74 10 "
        "48 83 c6 08 48 39 f1 75 ed 48 8b 05 e6 7d 31 03 "
        "48 83 c4 08 5b 41 5e c3"
    )

    def image(self, body, cls="CSpecialProjectInstance"):
        code = bytearray(body)
        struct.pack_into("<i", code, len(code) - 5, 0x3000 - (0x1200 + len(code) - 1))
        blobs = {
            0x1000: b"\xe9" + struct.pack("<i", 0x1100 - 0x1005),
            0x1100: bytes.fromhex("48 81 c7 48 24 00 00 e9")
            + struct.pack("<i", 0x1200 - 0x110C),
            0x1200: bytes(code),
        }

        class Image:
            def __init__(self):
                self.blobs = blobs
                self.symbols = [
                    {
                        "rva": rva,
                        "size": len(raw),
                        "type": "STT_FUNC",
                        "raw": "AccessInstance" if rva == 0x1000 else "helper",
                    }
                    for rva, raw in blobs.items()
                ]
                self.by_address = {s["rva"]: s for s in self.symbols}

            def read(self, rva, size):
                return self.blobs.get(rva, b"")[:size]

            def name(self, symbol):
                return f"{cls}::AccessInstance(CCountry&, unsigned int)"

            def target_name(self, rva):
                return f"TPdxNullObject<{cls}>::_pInstance" if rva == 0x3000 else ""

        return Image()

    def join_image(self):
        image = self.image(self.FORWARD, "CActiveEventChain")
        body = bytearray(self.DEFINITION_JOIN)
        for displacement, instruction_end, target in (
            (14, 18, 0x3100),
            (38, 42, 0x3200),
            (102, 106, 0x3300),
        ):
            struct.pack_into(
                "<i", body, displacement, target - (0x1000 + instruction_end)
            )
        image.blobs[0x1000] = bytes(body)
        image.by_address[0x1000]["size"] = len(body)
        image.target_name = lambda rva: {
            0x3100: "TGameDatabase<CEventChainDatabase>::_pInstance",
            0x3200: "TPdxNullObject<CEventChain>::_pInstance",
            0x3300: "TPdxNullObject<CActiveEventChain>::_pInstance",
        }.get(rva, "")
        return image

    def test_forward_member_id_is_scoped_not_a_generation_handle(self):
        result = recover_country_scoped_accessors(self.image(self.FORWARD))[0x1000]
        self.assertEqual(
            (result["data_offset"], result["count_offset"]), (0x24A8, 0x24B4)
        )
        self.assertEqual(
            (result["identity_offset"], result["identity_width"]), (0x18, 4)
        )
        self.assertFalse(result["generation_checked"])
        self.assertEqual(
            result["candidate_provider"], "requires_proven_command_binding"
        )
        self.assertEqual(result["caller_country_binding"], "not_recovered")
        self.assertEqual(result["equivalent_country_entrypoints"], [0x1000, 0x1100])
        self.assertNotIn(0x1200, result["equivalent_country_entrypoints"])

    def test_reverse_lookup_retains_16_bit_identity_and_country_offset(self):
        result = recover_country_scoped_accessors(
            self.image(self.REVERSE, "CPointOfInterest")
        )[0x1000]
        self.assertEqual(
            (result["data_offset"], result["count_offset"]), (0x24D8, 0x24E4)
        )
        self.assertEqual(
            (result["identity_offset"], result["identity_width"]), (0x3F0, 2)
        )
        self.assertEqual(result["search_direction"], "reverse")

    def equivalent_getter_image(self):
        image = self.image(self.FORWARD)
        body = bytearray(image.blobs[0x1200])
        struct.pack_into("<i", body, len(body) - 5, 0x3000 - (0x1400 + len(body) - 1))
        image.blobs[0x1400] = bytes(body)
        image.blobs[0x1300] = bytes.fromhex("4881c748240000e9") + struct.pack(
            "<i", 0x1400 - 0x130C
        )
        for address in (0x1300, 0x1400):
            symbol = {
                "rva": address,
                "size": len(image.blobs[address]),
                "type": "STT_FUNC",
                "raw": "unclassified_helper",
            }
            image.symbols.append(symbol)
            image.by_address[address] = symbol
        return image

    def test_distinct_const_getter_body_requires_complete_equivalence(self):
        image = self.equivalent_getter_image()
        result = recover_country_scoped_accessors(image)[0x1000]
        self.assertIn(0x1300, result["equivalent_country_entrypoints"])
        self.assertNotIn(0x1400, result["equivalent_country_entrypoints"])
        self.assertEqual(
            result["equivalent_entrypoint_evidence"][0]["member_lookup_rva"], 0x1400
        )
        for address, offset in (
            (0x1300, 3),
            (0x1400, 2),
            (0x1400, 6),
            (0x1400, 21),
            (0x1400, 37),
        ):
            image = self.equivalent_getter_image()
            body = bytearray(image.blobs[address])
            body[offset] ^= 1
            image.blobs[address] = bytes(body)
            with self.subTest(address=address, offset=offset):
                result = recover_country_scoped_accessors(image)[0x1000]
                self.assertNotIn(0x1300, result["equivalent_country_entrypoints"])

    def test_changed_bounds_branch_null_type_or_body_remains_unknown(self):
        for template, offset in ((self.FORWARD, 6), (self.REVERSE, 19)):
            bad = bytearray(template)
            bad[offset] = 0
            self.assertFalse(recover_country_scoped_accessors(self.image(bytes(bad))))
        image = self.image(self.FORWARD)
        image.target_name = lambda _: "TPdxNullObject<COther>::_pInstance"
        self.assertFalse(recover_country_scoped_accessors(image))
        self.assertFalse(
            recover_country_scoped_accessors(self.image(self.FORWARD + b"\x90"))
        )

    def test_thunk_cycles_unknown_targets_and_negative_adjustment_are_rejected(self):
        for destination in (0x1000, 0x9000):
            image = self.image(self.FORWARD)
            image.blobs[0x1000] = b"\xe9" + struct.pack("<i", destination - 0x1005)
            self.assertFalse(recover_country_scoped_accessors(image))
        image = self.image(self.FORWARD)
        bad = bytearray(image.blobs[0x1100])
        struct.pack_into("<i", bad, 3, -8)
        image.blobs[0x1100] = bytes(bad)
        self.assertFalse(recover_country_scoped_accessors(image))

    def test_loaded_definition_index_is_not_an_instance_id(self):
        result = recover_country_scoped_accessors(self.join_image())[0x1000]
        self.assertEqual(
            result["identity_kind"],
            "loaded_definition_index_to_country_member_not_TPdxRef",
        )
        self.assertEqual(
            (result["data_offset"], result["count_offset"]), (0x2460, 0x246C)
        )
        self.assertEqual(
            (result["definition_data_offset"], result["definition_count_offset"]),
            (0x50, 0x5C),
        )
        self.assertEqual(result["definition_pointer_member_offset"], 0x18)
        self.assertEqual(
            result["definition_index_bounds"], "signed_nonnegative_and_less_than_count"
        )
        self.assertEqual(result["definition_validation_virtual_slot"], 0x10)
        self.assertEqual(result["native_member_count_guard"], "nonzero_not_nonnegative")
        self.assertEqual(result["equivalent_country_entrypoints"], [0x1000])
        self.assertNotIn("identity_offset", result)
        self.assertFalse(result["generation_checked"])
        self.assertEqual(
            result["candidate_provider"], "requires_proven_command_binding"
        )

    def test_definition_join_requires_agreeing_database_and_both_null_types(self):
        for target in (0x3100, 0x3200, 0x3300):
            image = self.join_image()
            original = image.target_name
            image.target_name = lambda rva, target=target, original=original: (
                "wrong_global" if rva == target else original(rva)
            )
            self.assertFalse(recover_country_scoped_accessors(image))

    def test_definition_join_rejects_changed_control_flow_width_stride_and_slot(self):
        # Every non-offset instruction byte must remain the complete witnessed body.
        offsets = set(range(14, 18)) | {20, 26} | set(range(38, 42))
        offsets |= set(range(58, 62)) | set(range(70, 74)) | {87} | set(range(102, 106))
        for position in set(range(len(self.DEFINITION_JOIN))) - offsets:
            image = self.join_image()
            bad = bytearray(image.blobs[0x1000])
            bad[position] ^= 1
            image.blobs[0x1000] = bytes(bad)
            with self.subTest(position=position):
                self.assertFalse(recover_country_scoped_accessors(image))

    def test_definition_join_rejects_invalid_member_offsets_and_trailing_code(self):
        for position, width in ((20, 1), (26, 1), (58, 4), (70, 4), (87, 1)):
            image = self.join_image()
            bad = bytearray(image.blobs[0x1000])
            bad[position : position + width] = b"\xff" * width
            image.blobs[0x1000] = bytes(bad)
            with self.subTest(position=position):
                self.assertFalse(recover_country_scoped_accessors(image))
        image = self.join_image()
        image.blobs[0x1000] += b"\x90"
        image.by_address[0x1000]["size"] += 1
        self.assertFalse(recover_country_scoped_accessors(image))

    def test_definition_join_extracts_offsets_instead_of_fixing_one_layout(self):
        image = self.join_image()
        body = bytearray(image.blobs[0x1000])
        body[20], body[26], body[87] = 0x6C, 0x60, 0x28
        struct.pack_into("<i", body, 58, 0x266C)
        struct.pack_into("<i", body, 70, 0x2660)
        image.blobs[0x1000] = bytes(body)
        result = recover_country_scoped_accessors(image)[0x1000]
        self.assertEqual(
            (result["data_offset"], result["count_offset"]), (0x2660, 0x266C)
        )
        self.assertEqual(
            (result["definition_data_offset"], result["definition_count_offset"]),
            (0x60, 0x6C),
        )
        self.assertEqual(result["definition_pointer_member_offset"], 0x28)


class CountryScopeBindingTests(unittest.TestCase):
    BODY = bytes.fromhex(
        "415653504989fe488b0daabf51024885c97428418b461c89c281e2ffffff003b51207317"
        "488b491848c1e204488b5c11084885db74053943207407488b1d066c5102488b034889df"
        "ff505884c0741c418b76204889dfe825f21fff488b084889c74883c4085b415eff614031c0"
        "4883c4085b415ec3"
    )

    def fixture(self):
        body = bytearray(self.BODY)
        for offset, end, target in (
            (10, 14, 0x3000),
            (62, 66, 0x3100),
            (87, 91, 0x2000),
        ):
            struct.pack_into("<i", body, offset, target - (0x1000 + end))

        class Image:
            def __init__(self):
                self.code = bytes(body)

            def read(self, address, size):
                return self.code[address - 0x1000 : address - 0x1000 + size]

            def target_name(self, address):
                return {
                    0x3000: "TPdxRef<CCountry>::_pDatabase",
                    0x3100: "TPdxNullObject<CCountry>::_pInstance",
                }.get(address, "")

            def instructions(self, symbol, limit):
                from capstone import CS_ARCH_X86, CS_MODE_64, Cs

                decoder = Cs(CS_ARCH_X86, CS_MODE_64)
                decoder.detail = True
                return list(decoder.disasm(self.code, symbol["rva"]))[:limit]

        symbol = {"rva": 0x1000, "size": len(body)}
        scoped = {
            0x2000: {
                "class": "CSpecialProjectInstance",
                "scope_type": "CCountry",
                "id_argument_register": "rsi",
                "lookup_rva": 0x2000,
                "identity_kind": "country_member_value_not_TPdxRef",
            }
        }
        return Image(), symbol, scoped

    def test_complete_binding_retains_country_reference_and_scoped_id_distinction(self):
        image, symbol, scoped = self.fixture()
        proof = recover_scoped_validator_binding(image, symbol, scoped)
        self.assertEqual(proof["country_source_offset"], 0x1C)
        self.assertEqual(proof["source_offset"], 0x20)
        self.assertEqual(proof["country_object_id_offset"], 0x20)
        self.assertEqual(proof["call_rva"], 0x1056)
        self.assertEqual(proof["country_predicate_virtual_slot"], 0x58)
        self.assertTrue(proof["country_generation_checked"])
        self.assertNotIn("actor_permission", proof)

    def test_each_changed_guard_register_generation_check_or_call_shape_is_rejected(
        self,
    ):
        variable = (
            set(range(10, 14)) | {22, 56, 82} | set(range(62, 66)) | set(range(87, 91))
        )
        for position in set(range(len(self.BODY))) - variable:
            image, symbol, scoped = self.fixture()
            code = bytearray(image.code)
            code[position] ^= 1
            image.code = bytes(code)
            with self.subTest(position=position):
                self.assertIsNone(
                    recover_scoped_validator_binding(image, symbol, scoped)
                )

    def test_unknown_globals_or_scoped_resolver_do_not_prove_country_binding(self):
        for destination in (0x3000, 0x3100):
            image, symbol, scoped = self.fixture()
            original = image.target_name
            image.target_name = (
                lambda address, original=original, destination=destination: (
                    "unknown_global" if address == destination else original(address)
                )
            )
            self.assertIsNone(recover_scoped_validator_binding(image, symbol, scoped))
        image, symbol, scoped = self.fixture()
        self.assertIsNone(recover_scoped_validator_binding(image, symbol, {}))
        scoped[0x2000]["scope_type"] = "CColony"
        self.assertIsNone(recover_scoped_validator_binding(image, symbol, scoped))

    def test_invalid_or_overlapping_offsets_and_partial_bodies_are_rejected(self):
        for country, identity, country_id in (
            (28, 28, 32),
            (28, 30, 32),
            (27, 32, 32),
            (255, 32, 32),
            (28, 255, 32),
            (28, 32, 255),
        ):
            image, symbol, scoped = self.fixture()
            code = bytearray(image.code)
            code[22], code[82], code[56] = country, identity, country_id
            image.code = bytes(code)
            self.assertIsNone(recover_scoped_validator_binding(image, symbol, scoped))
        image, symbol, scoped = self.fixture()
        image.code = image.code[:-1]
        self.assertIsNone(recover_scoped_validator_binding(image, symbol, scoped))
        symbol["size"] -= 1
        self.assertIsNone(recover_scoped_validator_binding(image, symbol, scoped))

    def test_existing_field_flow_attaches_binding_without_global_ref_reclassification(
        self,
    ):
        from recovery_plans import inline_database_witnesses

        image, symbol, scoped = self.fixture()
        notes = []
        references = inline_database_witnesses(
            image, symbol, scoped_accessors=scoped, scoped_findings=notes
        )
        self.assertEqual({r["class"] for r in references}, {"CCountry"})
        self.assertEqual(len(notes), 1)
        self.assertEqual(notes[0]["class"], "CSpecialProjectInstance")
        self.assertEqual(notes[0]["source_offset"], 0x20)
        self.assertEqual(notes[0]["country_reference"]["country_source_offset"], 0x1C)
        self.assertEqual(
            notes[0]["caller_country_binding"],
            "generation_checked_command_country_reference",
        )

    def binding_catalog(self):
        from recovery_plans import inline_database_witnesses

        image, symbol, scoped = self.fixture()
        recipe = scoped[0x2000]
        recipe.update(
            equivalent_country_entrypoints=[0x2000],
            entry_stride=8,
            identity_width=4,
            identity_offset=0x18,
            search_direction="forward",
            data_offset=0x2448,
            count_offset=0x2454,
            null_rva=0x3200,
        )
        notes = []
        inline_database_witnesses(
            image, symbol, scoped_accessors=scoped, scoped_findings=notes
        )
        fields = [
            {
                "name": "requester",
                "kind": "ref",
                "ref": "CCountry",
                "linux_off": 0x1C,
                "confidence": "direct_dataflow",
            },
            {
                "name": "id",
                "kind": "u32",
                "linux_off": 0x20,
                "confidence": "direct_dataflow",
                "scoped_reference_evidence": notes,
            },
        ]
        return {
            "platform": "linux-x86_64",
            "build_id": "fixture",
            "sha256": "fixture",
            "object_databases": [
                {
                    "class": "CCountry",
                    "database_rva": 0x3000,
                    "null_rva": 0x3100,
                    "id_offset": 0x20,
                }
            ],
            "country_scoped_accessors": [recipe],
            "commands": [
                {
                    "class": "CScopedFixture",
                    "token_name": "fixture",
                    "token": 1,
                    "vtable": 1,
                    "factory": 1,
                    "size": 0x28,
                    "is_valid": 0x1000,
                    "deleting_destructor": 1,
                    "token_getter": 1,
                    "slots": {"is_valid": 9, "deleting_destructor": 1, "token": 11},
                    "fields": fields,
                }
            ],
        }

    def test_bound_provider_metadata_is_emitted_and_audited_without_type_conversion(
        self,
    ):
        from audit_recovery import audit
        from emit_ogas import emit_header
        from scoped_id_recovery import scoped_id_bindings

        catalog = self.binding_catalog()
        bindings = scoped_id_bindings(catalog)
        self.assertEqual(len(bindings), 1)
        self.assertEqual(bindings[0]["kind"], "member_u32")
        self.assertEqual(catalog["commands"][0]["fields"][1]["kind"], "u32")
        result = audit(catalog, {"build_id": "fixture", "commands": []})
        self.assertTrue(result["commands"][0]["validation_static_eligible"])
        self.assertEqual(result["new_native_calls"], 0)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "sdk.hpp"
            emit_header(catalog, path)
            header = path.read_text()
            self.assertIn("std::array<RecoveredScopedIdBinding, 1>", header)
            self.assertIn("ScopedIdKind::member_u32", header)

    def test_unbound_cross_platform_partial_or_duplicate_providers_remain_blocked(self):
        from scoped_id_recovery import scoped_id_bindings

        catalog = self.binding_catalog()
        field = catalog["commands"][0]["fields"][1]
        original = field["scoped_reference_evidence"][0]["country_reference"][
            "call_rva"
        ]
        field["scoped_reference_evidence"][0]["country_reference"]["call_rva"] += 1
        self.assertFalse(scoped_id_bindings(catalog))
        field["scoped_reference_evidence"][0]["country_reference"]["call_rva"] = (
            original
        )
        catalog["platform"] = "windows-x64"
        self.assertFalse(scoped_id_bindings(catalog))
        catalog["platform"] = "linux-x86_64"
        catalog["country_scoped_accessors"][0]["count_offset"] = -1
        self.assertFalse(scoped_id_bindings(catalog))
        catalog["country_scoped_accessors"][0]["count_offset"] = 0x2454
        catalog["commands"][0]["fields"].append(dict(field))
        self.assertFalse(scoped_id_bindings(catalog))


class SpecialProjectBindingTests(unittest.TestCase):
    RESEARCH = bytes.fromhex(
        "415653504989fe488b0d2ade48034885c97428418b461c89c281e2ffffff003b51207317"
        "488b491848c1e204488b5c11084885db74053943207407488b1d868a4803488b034889df"
        "ff505884c0742f418b76204889dfe825b2d0ff4989c6488b004c89f7ff504084c07413"
        "488dbbe01500004c89f6e8c6bbe0ff84c0740a31c04883c4085b415ec34c89f74889de"
        "ba0100000031c94883c4085b415ee9ef76cfff"
    )
    CANCEL = bytes.fromhex(
        "415653504989fe488b0dbadb48034885c97428418b461c89c281e2ffffff003b51207317"
        "488b491848c1e204488b5c11084885db74053943207407488b1d16884803488b034889df"
        "ff505884c07435418b76204889dfe8b5afd0ff4989c6488b004c89f7ff504084c07419"
        "4881c3e01500004889df4c89f64883c4085b415ee94cb9e0ff31c04883c4085b415ec3"
    )

    def project_fixture(self, research):
        from scoped_id_recovery import (
            PROJECT_CANCEL_VALIDATOR,
            PROJECT_RESEARCH_VALIDATOR,
        )

        image, symbol, scoped = CountryScopeBindingTests().fixture()
        pattern = PROJECT_RESEARCH_VALIDATOR if research else PROJECT_CANCEL_VALIDATOR
        body = bytearray(self.RESEARCH if research else self.CANCEL)
        match = pattern.fullmatch(body)
        self.assertIsNotNone(match)
        for key, target in {
            "database": 0x3000,
            "null": 0x3100,
            "lookup": 0x2000,
            "research_status": 0x4000,
            **({"can_research": 0x4100} if research else {}),
        }.items():
            struct.pack_into(
                "<i", body, match.start(key), target - (0x1000 + match.end(key))
            )
        image.code = bytes(body)
        symbol["size"] = len(body)
        prior = image.target_name
        image.target_name = lambda address: {
            0x4000: "CTechnologyStatus::IsResearching const(CSpecialProjectInstance const*)",
            0x4100: "CSpecialProjectInstance::CanResearch const(CCountry const&, bool, CString*)",
        }.get(address, prior(address))
        return image, symbol, scoped, match

    def test_both_project_predicates_prove_country_binding_and_keep_scalar_type(self):
        from recovery_plans import inline_database_witnesses

        for research in (False, True):
            image, symbol, scoped, _ = self.project_fixture(research)
            proof = recover_scoped_validator_binding(image, symbol, scoped)
            self.assertEqual(
                (proof["country_source_offset"], proof["source_offset"]), (28, 32)
            )
            notes = []
            inline_database_witnesses(
                image, symbol, scoped_accessors=scoped, scoped_findings=notes
            )
            self.assertEqual(len(notes), 1)
            self.assertEqual(notes[0]["country_reference"]["lookup_rva"], 0x2000)
            from scoped_id_recovery import scoped_id_bindings

            catalog = CountryScopeBindingTests().binding_catalog()
            command = catalog["commands"][0]
            command["class"] = (
                "CResearchSpecialProjectCommand"
                if research
                else "CCancelResearchSpecialProjectCommand"
            )
            field = command["fields"][1]
            field.update(name="special_project", scoped_reference_evidence=notes)
            self.assertEqual(scoped_id_bindings(catalog)[0]["lookup_rva"], 0x2000)
            self.assertEqual(field["kind"], "u32")

    def test_project_branch_slots_scope_and_predicate_targets_fail_closed(self):
        variable = (
            "database",
            "null",
            "lookup",
            "country",
            "id",
            "country_id",
            "technology_offset",
            "research_status",
            "can_research",
        )
        for research in (False, True):
            image, symbol, scoped, match = self.project_fixture(research)
            mutable = {
                p
                for key in variable
                if key in match.groupdict()
                for p in range(match.start(key), match.end(key))
            }
            for position in set(range(symbol["size"])) - mutable:
                image, symbol, scoped, _ = self.project_fixture(research)
                body = bytearray(image.code)
                body[position] ^= 1
                image.code = bytes(body)
                with self.subTest(research=research, position=position):
                    self.assertIsNone(
                        recover_scoped_validator_binding(image, symbol, scoped)
                    )
            image, symbol, scoped, _ = self.project_fixture(research)
            prior = image.target_name
            image.target_name = lambda address, prior=prior: (
                "unknown" if address == 0x4000 else prior(address)
            )
            self.assertIsNone(recover_scoped_validator_binding(image, symbol, scoped))
            image, symbol, scoped, _ = self.project_fixture(research)
            scoped[0x2000]["class"] = "CUnknown"
            self.assertIsNone(recover_scoped_validator_binding(image, symbol, scoped))


if __name__ == "__main__":
    unittest.main()
