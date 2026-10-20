from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from record_candidates import discover_country_records, recover_country_record_source


class SourceRecoveryTests(unittest.TestCase):
    def fixture(self):
        code = bytes.fromhex(
            "415741564154535048634f5c4885c90f848f0000004989d64989f7488b5f50488b05"
            "a2469e0348c1e1044c8d2449eb0a4883c3304983c4d0746a4885c074418b4b1c"
            "89ca81e2ffffff003b50207331488b701848c1e204488b5416084885d2741f394a20"
            "751a662e0f1f8400000000004c39fa75bbeb15660f1f840000000000488b15d1f29d03"
            "4c39fa75a4418b76144c89f74889dae865420000488b0526469e03eb8c4883c408"
            "5b415c415e415fc3"
        )
        targets = {
            0x5732588: "TPdxRef<CCountry>::_pDatabase",
            0x572D218: "TPdxNullObject<CCountry>::_pInstance",
            0x1D521C0: "SMonthlyTradeData& CPdxArray<SMonthlyTradeData, int>::InsertAtEmplace<SMonthlyTradeData const&>(int, SMonthlyTradeData const&)",
        }

        class Image:
            def read(self, address, size):
                return code if address == 0x1D4DEC0 and size == len(code) else b""

            def name(self, _symbol):
                return "CMarket::GetMonthlyTrades const(CCountry const*, CPdxArray<SMonthlyTradeData, int>&)"

            def target_name(self, address):
                return targets.get(address, "")

        identity = {
            "owner_class": "CMarket",
            "record_class": "SMonthlyTradeData",
            "array_offset": 0x48,
            "array_count_offset": 0x5C,
            "record_identity_offset": 0x28,
            "insert_rva": 0x1D521C0,
            "research_callable": False,
            "evidence": "complete_manager_counter_assign_then_record_array_insert",
        }
        symbol = {"rva": 0x1D4DEC0, "size": len(code), "type": "STT_FUNC"}
        return Image(), code, targets, identity, symbol

    def test_complete_native_filter_recovers_generation_checked_record_source(self):
        image, _, _, identity, symbol = self.fixture()
        result = recover_country_record_source(image, symbol, identity)
        self.assertIsNotNone(result)
        self.assertEqual(result["data_offset"], 0x50)
        self.assertEqual(result["count_offset"], 0x5C)
        self.assertEqual(result["country_field_offset"], 0x1C)
        self.assertEqual(result["country_id_offset"], 0x20)
        self.assertEqual(result["identity_field_offset"], 0x28)
        self.assertEqual(result["entry_stride"], 48)
        self.assertTrue(result["native_output_allocation"])
        self.assertFalse(result["native_function_called"])
        self.assertFalse(result["runtime_candidate_provider_implemented"])

    def test_filter_requires_all_branch_generation_and_insert_evidence(self):
        image, code, targets, identity, symbol = self.fixture()
        for old, new in (
            (b"\x39\x4a\x20", b"\x90\x90\x90"),
            (b"\x75\x1a", b"\x75\x19"),
            (b"\x8b\x4b\x1c", b"\x8b\x4b\xfc"),
            (b"\x48\x8b\x5f\x50", b"\x48\x8b\x5f\xd0"),
        ):
            changed = code.replace(old, new)
            self.assertNotEqual(changed, code)
            image.read = lambda _address, _size, raw=changed: raw
            self.assertIsNone(recover_country_record_source(image, symbol, identity))
        image.read = lambda _address, _size: code
        for address in tuple(targets):
            previous = targets[address]
            targets[address] = "unknown"
            self.assertIsNone(recover_country_record_source(image, symbol, identity))
            targets[address] = previous
        self.assertIsNone(
            recover_country_record_source(image, {**symbol, "size": 175}, identity)
        )
        self.assertIsNone(
            recover_country_record_source(
                image, {**symbol, "type": "STT_OBJECT"}, identity
            )
        )

    def test_filter_does_not_guess_source_from_name_or_counter_alone(self):
        image, _, _, identity, symbol = self.fixture()
        for update in (
            {"record_class": "SOther"},
            {"array_offset": 0x40},
            {"record_identity_offset": None},
            {"research_callable": True},
            {"record_identity_offset": -4},
            {"record_identity_offset": True},
        ):
            self.assertIsNone(
                recover_country_record_source(image, symbol, {**identity, **update})
            )


class Memory:
    def __init__(self):
        self.data = bytearray(0x50000)
        self.calls = []

    def put(self, address, value, width=8, signed=False):
        self.data[address : address + width] = value.to_bytes(
            width, "little", signed=signed
        )

    def read(self, address, size):
        self.calls.append((address, size))
        if address < 0 or address + size > len(self.data):
            raise OSError("unmapped_fixture_memory")
        return bytes(self.data[address : address + size])


class CorrelatedRecordTests(unittest.TestCase):
    def fixture(self):
        memory = Memory()
        source = {
            "record_class": "SMonthlyTradeData",
            "data_offset": 0x50,
            "count_offset": 0x5C,
            "country_field_offset": 0x1C,
            "country_id_offset": 0x20,
            "identity_field_offset": 0x28,
            "entry_stride": 48,
            "country_database_rva": 0x100,
            "country_null_rva": 0x108,
            "evidence": "complete_generation_checked_country_record_filter_copy",
            "runtime_candidate_provider_implemented": False,
        }
        definition = {
            "class": "CStrategicResource",
            "database_rva": 0x120,
            "null_rva": 0x128,
            "data_offset": 8,
            "count_offset": 20,
        }
        fields = [
            {
                "name": "resource",
                "kind": "definition_pointer",
                "offset": 0x10,
                "width": 8,
                "type": "CStrategicResource",
            },
            {"name": "trade_type", "kind": "i32", "offset": 0x18, "width": 4},
            {
                "name": "country",
                "kind": "ref",
                "offset": 0x1C,
                "width": 4,
                "type": "CCountry",
            },
            {"name": "amount", "kind": "i32", "offset": 0x20, "width": 4},
            {"name": "price", "kind": "i32", "offset": 0x24, "width": 4},
            {"name": "id", "kind": "i32", "offset": 0x28, "width": 4},
        ]
        country_id = 0x03000002
        memory.put(0x100, 0x2000)
        memory.put(0x108, 0x19000)
        memory.put(0x2018, 0x3000)
        memory.put(0x2020, 8, 4)
        memory.put(0x3028, 0x4000)
        memory.put(0x4020, country_id, 4)
        memory.put(0x120, 0x5000)
        memory.put(0x128, 0x19100)
        memory.put(0x5008, 0x6000)
        memory.put(0x5014, 2, 4)
        memory.put(0x6000, 0x8000)
        memory.put(0x6008, 0x9000)
        memory.put(0x1050, 0xA000)
        memory.put(0x105C, 3, 4)
        for index, row in enumerate(
            (
                (0x8000, 0, country_id, 15, 0, 7),
                (0x9000, 1, country_id, 80, 100, 8),
                (0x8000, 0, 0x01000002, 999, 3, 9),
            )
        ):
            for field, value in zip(fields, row):
                memory.put(
                    0xA000 + index * 48 + field["offset"],
                    value,
                    field["width"],
                    field["kind"] == "i32",
                )
        return memory, source, fields, definition, country_id

    def discover(self, fixture, **options):
        memory, source, fields, definition, country = fixture
        return discover_country_records(
            memory.read, 0, 0x1000, country, source, fields, definition, **options
        )

    def test_coupled_fields_stay_together_and_are_only_hints(self):
        result = self.discover(self.fixture())
        values = [h["values"] for h in result["hints"]]
        self.assertEqual(
            [(v["resource"], v["amount"], v["price"], v["id"]) for v in values],
            [(0x8000, 15, 0, 7), (0x9000, 80, 100, 8)],
        )
        self.assertEqual(result["rejected_in_scan"]["other_or_stale_country"], 1)
        self.assertTrue(result["selected_bytes_unchanged"])
        self.assertIsNone(result["native_is_valid"])
        for key in (
            "runtime_candidate_provider_implemented",
            "native_function_called",
            "submitted",
            "definition_key_resolved",
        ):
            self.assertFalse(result[key])
        self.assertIn("not_native_validation", result["evidence_level"])
        self.assertIn("not_frozen_world", result["consistency"])

    def test_country_full_generation_is_checked_before_record_scan(self):
        fixture = self.fixture()
        fixture[0].put(0x4020, 0x01000002, 4)
        with self.assertRaisesRegex(ValueError, "generation"):
            self.discover(fixture)
        self.assertNotIn((0xA000, 144), fixture[0].calls)

    def test_unknown_definition_pointer_is_not_dereferenced(self):
        fixture = self.fixture()
        fixture[0].put(0xA010, 0xDEADBEEF)
        result = self.discover(fixture)
        self.assertEqual([h["values"]["id"] for h in result["hints"]], [8])
        self.assertFalse(
            any(address == 0xDEADBEEF for address, _size in fixture[0].calls)
        )

    def test_duplicate_identity_with_unknown_definition_rejects_both_rows(self):
        fixture = self.fixture()
        fixture[0].put(0xA000 + 48 + 0x28, 7, 4)
        fixture[0].put(0xA000 + 48 + 0x10, 0xDEADBEEF)
        result = self.discover(fixture)
        self.assertEqual(result["hints"], [])
        self.assertEqual(result["duplicate_identities_in_scan"], [7])

    def test_record_limits_keep_bounded_uniqueness_and_truncation_explicit(self):
        result = self.discover(self.fixture(), candidate_limit=1)
        self.assertTrue(result["hints_truncated"])
        self.assertEqual(len(result["hints"]), 1)
        result = self.discover(self.fixture(), scan_limit=1)
        self.assertTrue(result["array_truncated"])
        self.assertEqual(result["identity_uniqueness_scope"], "bounded_scan_only")

    def test_negative_unassigned_id_is_not_an_existing_order(self):
        fixture = self.fixture()
        fixture[0].put(0xA028, -1, 4, True)
        result = self.discover(fixture)
        self.assertEqual([h["values"]["id"] for h in result["hints"]], [8])
        self.assertEqual(
            result["rejected_in_scan"]["negative_unassigned_record_identity"], 1
        )

    def test_raw_signed_quantity_is_not_silently_made_legal(self):
        fixture = self.fixture()
        fixture[0].put(0xA020, -9, 4, True)
        result = self.discover(fixture)
        self.assertEqual(result["hints"][0]["values"]["amount"], -9)
        self.assertIsNone(result["native_is_valid"])

    def test_memory_change_discards_hints_instead_of_claiming_coherence(self):
        fixture = self.fixture()
        memory, source, fields, definition, country = fixture
        reads = 0

        def changed(address, size):
            nonlocal reads
            if address == 0xA000:
                reads += 1
                if reads > 1:
                    memory.put(0xA020, 999, 4)
            return memory.read(address, size)

        result = discover_country_records(
            changed, 0, 0x1000, country, source, fields, definition
        )
        self.assertFalse(result["selected_bytes_unchanged"])
        self.assertEqual(result["hints"], [])

    def test_bad_counts_empty_data_and_short_reads_fail_closed(self):
        for count in (-1, 1000001):
            fixture = self.fixture()
            fixture[0].put(0x105C, count, 4, True)
            with self.assertRaisesRegex(ValueError, "record_count"):
                self.discover(fixture)
        fixture = self.fixture()
        fixture[0].put(0x1050, 0)
        with self.assertRaisesRegex(ValueError, "record_data"):
            self.discover(fixture)
        fixture[0].put(0x105C, 0, 4)
        self.assertEqual(self.discover(fixture)["hints"], [])
        _memory, source, fields, definition, country = fixture
        with self.assertRaises(OSError):
            discover_country_records(
                lambda *_: b"", 0, 0x1000, country, source, fields, definition
            )

    def test_recipe_field_types_and_unsafe_limits_are_rejected_before_reads(self):
        for key, value in (
            ("count_offset", True),
            ("entry_stride", 32),
            ("identity_field_offset", 48),
            ("country_database_rva", 0),
        ):
            fixture = self.fixture()
            fixture[1][key] = value
            with self.assertRaises(ValueError):
                self.discover(fixture)
            self.assertEqual(fixture[0].calls, [])
        for options in (
            {"scan_limit": 513},
            {"candidate_limit": 17},
            {"scan_limit": True},
        ):
            fixture = self.fixture()
            with self.assertRaises(ValueError):
                self.discover(fixture, **options)
            self.assertEqual(fixture[0].calls, [])
        for update in (
            {"kind": "string"},
            {"width": True},
            {"offset": -1},
            {"offset": 0x1C},
        ):
            fixture = self.fixture()
            fixture[2][0].update(update)
            with self.assertRaises(ValueError):
                self.discover(fixture)
            self.assertEqual(fixture[0].calls, [])


if __name__ == "__main__":
    unittest.main()
