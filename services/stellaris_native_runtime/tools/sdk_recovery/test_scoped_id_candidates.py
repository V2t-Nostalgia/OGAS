from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from scoped_id_candidates import ReadBudget, discover_scoped_ids


class Memory:
    def __init__(self):
        self.data = bytearray(0x20000)
        self.reads = 0

    def put(self, address, value, width=8, signed=False):
        self.data[address : address + width] = value.to_bytes(
            width, "little", signed=signed
        )

    def read(self, address, size):
        self.reads += 1
        return bytes(self.data[address : address + size])


class ScopedCandidateTests(unittest.TestCase):
    def fixture(self, width=4, reverse=False):
        memory = Memory()
        recipe = {
            "class": "CTestScoped",
            "scope_type": "CCountry",
            "entry_stride": 8,
            "data_offset": 0x60,
            "count_offset": 0x6C,
            "null_rva": 0x100,
            "identity_kind": "country_member_value_not_TPdxRef",
            "identity_offset": 0x18,
            "identity_width": width,
            "search_direction": "reverse" if reverse else "forward",
        }
        memory.put(0x100, 0x19000)
        memory.put(0x1060, 0x2000)
        memory.put(0x106C, 3, 4)
        for i, (pointer, identity) in enumerate(
            ((0x3000, 11), (0x4000, 22), (0x5000, 11))
        ):
            memory.put(0x2000 + 8 * i, pointer)
            memory.put(pointer + 0x18, identity, width)
        return memory, recipe

    def test_forward_lookup_retains_first_duplicate_and_is_only_a_hint(self):
        memory, recipe = self.fixture()
        result = discover_scoped_ids(memory.read, 0, 0x1000, recipe)
        self.assertEqual([h["value"] for h in result["hints"]], [11, 22])
        self.assertEqual(result["hints"][0]["object_pointer"], 0x3000)
        self.assertEqual(result["duplicate_ids_in_scan"], 1)
        self.assertTrue(result["selected_bytes_unchanged"])
        self.assertFalse(result["native_lookup_called"])
        self.assertIsNone(result["native_is_valid"])
        self.assertFalse(result["submitted"])
        self.assertTrue(result["requires_game_thread_native_resolution"])
        self.assertIn("not_native_validation", result["evidence_level"])

    def test_reverse_16_bit_ids_and_truncation_follow_native_order(self):
        memory, recipe = self.fixture(2, True)
        memory.put(0x501A, 0xFFFF, 2)
        result = discover_scoped_ids(memory.read, 0, 0x1000, recipe, scan_limit=2)
        self.assertEqual([h["source_array_index"] for h in result["hints"]], [2, 1])
        self.assertEqual(result["hints"][0]["value"], 11)
        self.assertTrue(result["array_truncated"])

    def test_null_sentinels_and_empty_lists_do_not_dereference_objects(self):
        memory, recipe = self.fixture()
        memory.put(0x2000, 0)
        memory.put(0x2008, 0x19000)
        self.assertEqual(
            len(discover_scoped_ids(memory.read, 0, 0x1000, recipe)["hints"]), 1
        )
        memory.put(0x106C, 0, 4)
        memory.put(0x1060, 0)
        self.assertEqual(
            discover_scoped_ids(memory.read, 0, 0x1000, recipe)["hints"], []
        )

    def test_signed_count_short_reads_and_budgets_fail_closed(self):
        memory, recipe = self.fixture()
        for count in (-1, 1000001):
            memory.put(0x106C, count, 4, True)
            with self.assertRaisesRegex(ValueError, "invalid_array_count"):
                discover_scoped_ids(memory.read, 0, 0x1000, recipe)
        with self.assertRaises(OSError):
            discover_scoped_ids(lambda *_: b"", 0, 0x1000, recipe)
        budget = ReadBudget(memory.read)
        budget.bytes = 262144
        with self.assertRaisesRegex(ValueError, "budget"):
            budget(1, 1)

    def test_candidate_limit_does_not_erase_truncation_or_duplicate_evidence(self):
        memory, recipe = self.fixture()
        result = discover_scoped_ids(memory.read, 0, 0x1000, recipe, candidate_limit=1)
        self.assertEqual([h["value"] for h in result["hints"]], [11])
        self.assertTrue(result["hints_truncated"])
        self.assertEqual(result["duplicate_ids_in_scan"], 1)

    def test_budget_checks_address_overflow_and_short_reads(self):
        memory, _ = self.fixture()
        for address, size in (
            (0, 1),
            (-1, 1),
            (2**64 - 1, 2),
            (1, 65537),
            (1.5, 8),
            (True, 8),
        ):
            with self.assertRaises(ValueError):
                ReadBudget(memory.read)(address, size)
        with self.assertRaises(OSError):
            ReadBudget(lambda *_: b"x")(1, 8)
        budget = ReadBudget(memory.read)
        budget.calls = 4096
        with self.assertRaisesRegex(ValueError, "budget"):
            budget(1, 1)

    def test_changed_memory_does_not_claim_coherence(self):
        memory, recipe = self.fixture()
        seen = 0

        def read(address, size):
            nonlocal seen
            if address == 0x3018:
                seen += 1
                if seen > 1:
                    return (99).to_bytes(size, "little")
            return memory.read(address, size)

        result = discover_scoped_ids(read, 0, 0x1000, recipe)
        self.assertFalse(result["selected_bytes_unchanged"])
        self.assertIsNone(result["native_is_valid"])

    def test_definition_join_uses_loaded_indices_not_instance_ids(self):
        memory, recipe = self.fixture()
        recipe.update(
            identity_kind="loaded_definition_index_to_country_member_not_TPdxRef",
            definition_database_rva=0x110,
            definition_null_rva=0x120,
            definition_data_offset=0x50,
            definition_count_offset=0x5C,
            definition_entry_stride=8,
            definition_pointer_member_offset=0x18,
        )
        memory.put(0x110, 0x6000)
        memory.put(0x120, 0x19100)
        memory.put(0x6050, 0x7000)
        memory.put(0x605C, 3, 4)
        for index, definition in enumerate((0x19100, 0x8000, 0x9000)):
            memory.put(0x7000 + index * 8, definition)
        memory.put(0x3018, 0x9000)
        memory.put(0x4018, 0x8000)
        memory.put(0x5018, 0x19100)
        result = discover_scoped_ids(memory.read, 0, 0x1000, recipe)
        self.assertEqual([h["value"] for h in result["hints"]], [2, 1])
        self.assertEqual(result["definition_count"], 3)
        self.assertIsNone(result["native_is_valid"])

    def test_unproven_layouts_and_unsafe_bounds_are_not_followed(self):
        memory, recipe = self.fixture()
        for update in (
            {"identity_width": 8},
            {"entry_stride": 16},
            {"count_offset": -1},
            {"null_rva": 0},
            {"scope_type": "CCountryManager"},
            {"count_offset": True},
        ):
            with self.assertRaises(ValueError):
                discover_scoped_ids(memory.read, 0, 0x1000, {**recipe, **update})
        with self.assertRaises(ValueError):
            discover_scoped_ids(memory.read, 0, 0x1000, recipe, scan_limit=16384)
        with self.assertRaises(ValueError):
            discover_scoped_ids(memory.read, 0, 0, recipe)
        with self.assertRaises(ValueError):
            discover_scoped_ids(memory.read, 0, 0x1000, recipe, scan_limit=1.5)


if __name__ == "__main__":
    unittest.main()
