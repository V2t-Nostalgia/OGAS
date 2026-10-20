from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

spec = importlib.util.spec_from_file_location(
    "prepare_window_tool", Path(__file__).with_name("prepare_validation_window.py")
)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class PreparationTests(unittest.TestCase):
    def inputs(self, root):
        sdk = {
            "platform": "linux-x86_64",
            "build_id": "fixture",
            "sha256": "binary-fixture",
            "commands": [],
            "functions": {},
            "globals": {},
        }
        baseline = {"build_id": "fixture", "commands": []}
        a, b = root / "sdk.json", root / "baseline.json"
        a.write_text(json.dumps(sdk), encoding="utf8")
        b.write_text(json.dumps(baseline), encoding="utf8")
        return a, b

    def test_generates_independent_header_audit_and_bound_plan(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            a, b = self.inputs(root)
            original = a.read_bytes(), b.read_bytes()
            plan = module.prepare(a, b, root / "new")
            self.assertEqual(len(plan["sdk_fingerprint"]), 64)
            self.assertIn(
                plan["sdk_fingerprint"],
                (root / "new/recovered_sdk.hpp").read_text(encoding="utf8"),
            )
            self.assertFalse(plan["execution_verified"])
            self.assertEqual(plan["new_native_calls"], 0)
            self.assertEqual((a.read_bytes(), b.read_bytes()), original)
            with self.assertRaises(FileExistsError):
                module.prepare(a, b, root / "new")

    def test_exact_build_mismatch_rejects_before_output(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            a, b = self.inputs(root)
            b.write_text(
                json.dumps({"build_id": "different", "commands": []}), encoding="utf8"
            )
            with self.assertRaises(ValueError):
                module.prepare(a, b, root / "new")
            self.assertFalse((root / "new").exists())

    def test_true_and_static_blockers_are_not_added_to_backfill(self):
        rows = [
            {
                "command_name": "true",
                "validation_static_eligible": True,
                "previous_status": "native_valid",
                "blockers": [],
            },
            {
                "command_name": "negative",
                "validation_static_eligible": True,
                "previous_status": "native_invalid",
                "blockers": [],
            },
            {
                "command_name": "new",
                "validation_static_eligible": True,
                "previous_status": "not_tested",
                "blockers": [],
            },
            {
                "command_name": "blocked",
                "validation_static_eligible": False,
                "previous_status": "not_tested",
                "blockers": ["layout"],
            },
        ]
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            a, b = self.inputs(root)
            with patch.object(
                module, "audit", return_value={"commands": rows, "summary": {}}
            ):
                plan = module.prepare(a, b, root / "new")
        self.assertEqual(plan["legacy_selected_commands"], ["negative", "new"])
        self.assertEqual(
            plan["static_blocked"],
            [{"command_name": "blocked", "blockers": ["layout"]}],
        )

    def test_metadata_fingerprint_is_order_independent_and_content_bound(self):
        self.assertEqual(
            module.catalog_fingerprint({"a": 1, "b": 2}),
            module.catalog_fingerprint({"b": 2, "a": 1}),
        )
        self.assertNotEqual(
            module.catalog_fingerprint({"a": 1}), module.catalog_fingerprint({"a": 2})
        )

    def test_dynamic_template_command_names_match_emitted_consumer(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            a, b = self.inputs(root)
            sdk = json.loads(a.read_text(encoding="utf8"))
            sdk["commands"] = [
                {
                    "class": "CTemplateCommand<CThing>",
                    "fields": [],
                    "slots": {},
                    "token": 0,
                }
            ]
            a.write_text(json.dumps(sdk), encoding="utf8")
            row = {
                "class_name": "CTemplateCommand<CThing>",
                "command_name": "CTemplateCommand<CThing>",
                "validation_static_eligible": True,
                "previous_status": "not_tested",
                "blockers": [],
            }
            with patch.object(
                module, "audit", return_value={"commands": [row], "summary": {}}
            ):
                plan = module.prepare(a, b, root / "new")
            self.assertEqual(plan["legacy_selected_commands"], ["token_0_0"])
            self.assertIn(
                '"token_0_0", "CTemplateCommand<CThing>"',
                (root / "new/recovered_sdk.hpp").read_text(encoding="utf8"),
            )


if __name__ == "__main__":
    unittest.main()
