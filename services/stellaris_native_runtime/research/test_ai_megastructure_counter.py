from __future__ import annotations

import unittest

from services.stellaris_native_runtime.research.analyze_ai_megastructure_counter import (
    summarize,
)
from services.stellaris_native_runtime.research.analyze_mod_hook_compatibility import (
    analyze,
)


def snapshot(timestamp: int, find: int, calc: int, duplicates: int):
    return {
        "schema": "iag.stellaris.ai_megastructure_counter.v1",
        "kind": "snapshot",
        "monotonic_ns": timestamp,
        "realtime_ns": timestamp + 100,
        "mode": "full",
        "key_table_overflow": 0,
        "identity_table_overflow": 0,
        "signature_table_overflow": 0,
        "counters": {
            "find_best_position": {
                "total": find,
                "path": find,
                "thread_cpu_ns": find * 100,
                "max_thread_cpu_ns": 150,
            },
            "calc_ai_weight": {
                "total": calc,
                "path": calc,
                "thread_cpu_ns": calc * 10,
                "max_thread_cpu_ns": 20,
            },
            "trigger_evaluate": {"total": calc * 2, "path": calc * 2},
            "owned_fleet_actual_evaluate": {"total": calc, "path": calc},
            "owned_fleet_calculate_count": {"total": calc, "path": calc},
        },
        "identities": [
            {
                "identity_kind": "country_object",
                "identity": "0x1234",
                "duplicate_calc_calls": duplicates,
                "duplicate_trigger_calls": duplicates * 2,
                "duplicate_owned_calls": duplicates,
            }
        ],
        "repeated_signatures": [],
    }


class CounterAnalysisTest(unittest.TestCase):
    def test_exact_counts_stay_distinct_from_repetition(self):
        report = summarize(
            [snapshot(1_000_000_000, 2, 10, 2), snapshot(2_000_000_000, 5, 25, 5)]
        )
        self.assertEqual(report["exact_entry_counts"]["calc_ai_weight"]["total"], 25)
        self.assertEqual(
            report["same_civilian_update_repetition"]["calc_duplicate_calls"], 5
        )
        self.assertEqual(
            report["intervals"][0]["counters"]["calc_ai_weight"]["total"], 15
        )
        self.assertIn("upper bound", report["same_civilian_update_repetition"]["cacheability_warning"])

    def test_overflow_marks_duplicate_count_as_lower_bound(self):
        value = snapshot(1_000_000_000, 2, 10, 2)
        value["key_table_overflow"] = 1
        report = summarize([value])
        self.assertEqual(
            report["same_civilian_update_repetition"]["classification"],
            "lower_bound",
        )


class ModCompatibilityAnalysisTest(unittest.TestCase):
    def test_compares_layouts_without_claiming_mod_causality(self):
        baseline = {
            "command_types": {
                "CSetPolicyCommand": {
                    "phases": {"session_post": 2},
                    "layout_signatures": [{"fingerprint": "same"}],
                }
            },
            "payload_types": {},
        }
        modded = {
            "command_types": {
                "CSetPolicyCommand": {
                    "phases": {"session_post": 3},
                    "layout_signatures": [{"fingerprint": "same"}],
                },
                "CModOnlyObservedCommand": {
                    "phases": {"session_post": 1},
                    "layout_signatures": [],
                },
            },
            "payload_types": {},
            "event_definitions": {
                "mod_event.1": {"content_observed": True},
            },
        }
        inventory = {
            "elf_build_id": "build",
            "mods": [
                {
                    "load_index": 0,
                    "name": "Test Mod",
                    "remote_file_id": "1",
                    "fingerprints": {},
                    "external_definitions": {
                        "engine_loaded": False,
                        "counts": {"event": 1},
                        "samples": {"event": ["mod_event.1"]},
                    },
                }
            ],
        }
        report = analyze(baseline, modded, inventory)
        comparison = report["command_catalog_comparison"]
        self.assertEqual(comparison["modded_only"], ["CModOnlyObservedCommand"])
        self.assertEqual(
            comparison["common_layouts"][0]["shared_layout_fingerprints"],
            ["same"],
        )
        self.assertTrue(comparison["layout_comparison_available"])
        self.assertIn("do not attribute", comparison["warning"])
        self.assertTrue(
            report["captured_mod_event_evidence"]["mod_event.1"]["content_observed"]
        )

    def test_missing_old_layout_schema_is_unavailable_not_changed(self):
        baseline = {
            "command_types": {"CSetPolicyCommand": {"phases": {"session_post": 2}}},
            "payload_types": {"CPayload": {}},
        }
        modded = {
            "command_types": {
                "CSetPolicyCommand": {
                    "phases": {"session_post": 3},
                    "layout_signatures": [{"fingerprint": "new-schema"}],
                }
            },
            "payload_types": {
                "CPayload": {
                    "layout_signatures": [{"fingerprint": "new-schema"}]
                }
            },
        }
        report = analyze(baseline, modded, {"mods": []})
        command = report["command_catalog_comparison"]
        self.assertFalse(command["layout_comparison_available"])
        self.assertIsNone(
            command["common_layouts"][0]["shared_layout_fingerprints"]
        )
        payload = report["payload_catalog_comparison"]
        self.assertFalse(payload["layout_comparison_available"])
        self.assertIsNone(
            payload["layouts"]["CPayload"]["shared_layout_fingerprints"]
        )


if __name__ == "__main__":
    unittest.main()
