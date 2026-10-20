from __future__ import annotations

import contextlib
import hashlib
import importlib.util
import io
import json
import struct
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

HAS_DISASSEMBLER = all(
    importlib.util.find_spec(module) is not None
    for module in ("capstone", "elftools", "itanium_demangler")
)


@unittest.skipUnless(HAS_DISASSEMBLER, "install tools/sdk_recovery/requirements.txt")
class ProducerEvidenceTests(unittest.TestCase):
    def image(self, raw: bytes):
        from capstone import CS_ARCH_X86, CS_MODE_64, Cs

        decoder = Cs(CS_ARCH_X86, CS_MODE_64)
        decoder.detail = True

        class FixtureImage:
            data = raw
            build_id = "fixture-only"

            def __init__(self):
                self.symbols = [
                    {
                        "rva": 0x1000,
                        "size": len(raw),
                        "raw": "fixture",
                        "type": "STT_FUNC",
                    }
                ]

            def read(self, rva, size):
                return raw[rva - 0x1000 : rva - 0x1000 + size]

            def instructions(self, symbol, limit=65536):
                return list(decoder.disasm(raw[:limit], symbol["rva"]))

            def name(self, _symbol):
                return "Fixture::Producer()"

            def target_name(self, rva):
                return {0x2000: "Fixture::Callee()", 0x3000: "Fixture::Database"}.get(
                    rva, ""
                )

        return FixtureImage()

    def evidence(self, raw, **kwargs):
        from services.stellaris_native_runtime.research.discover_command_producers import (
            function_evidence,
        )

        image = self.image(raw)
        return function_evidence(image, image.symbols[0], **kwargs)

    def test_records_verified_direct_call_and_preserves_bytes(self):
        raw = b"\xe8" + struct.pack("<i", 0x2000 - 0x1005) + b"\xc3"
        value = self.evidence(raw)
        self.assertTrue(value["complete_linear_decode"])
        self.assertTrue(value["linear_decode_is_not_reachability_proof"])
        self.assertEqual(value["bytes"], raw.hex())
        self.assertEqual(value["bytes_sha256"], hashlib.sha256(raw).hexdigest())
        self.assertEqual(
            value["calls"],
            [
                {
                    "call_rva": 0x1000,
                    "target_rva": 0x2000,
                    "target": "Fixture::Callee()",
                    "kind": "direct_call",
                }
            ],
        )

    def test_internal_jump_is_not_a_call_but_external_jump_is_retained(self):
        raw = b"\xeb\x00\xe9" + struct.pack("<i", 0x2000 - 0x1007)
        value = self.evidence(raw)
        self.assertEqual(len(value["calls"]), 1)
        self.assertEqual(value["calls"][0]["kind"], "tail_jump")
        self.assertEqual(value["instructions"][0]["target_rva"], 0x1002)

    def test_indirect_calls_and_jumps_remain_unresolved(self):
        value = self.evidence(bytes.fromhex("ff5048 ff6008 c3"))
        self.assertEqual(
            [c["kind"] for c in value["calls"]],
            ["indirect_unresolved", "indirect_jump_unresolved"],
        )
        self.assertTrue(all(c["target_rva"] is None for c in value["calls"]))

    def test_rip_reference_is_not_a_callee(self):
        value = self.evidence(
            b"\x48\x8b\x05" + struct.pack("<i", 0x3000 - 0x1007) + b"\xc3"
        )
        self.assertEqual(value["calls"], [])
        self.assertEqual(
            value["instructions"][0]["rip_references"],
            [{"rva": 0x3000, "symbol": "Fixture::Database"}],
        )

    def test_truncation_or_undecodable_suffix_is_not_complete(self):
        self.assertFalse(self.evidence(b"\x90\xc3", limit=1)["complete_linear_decode"])
        self.assertFalse(self.evidence(b"\x90\x0f")["complete_linear_decode"])

    def test_manifest_reports_unmatched_rvas_and_never_overwrites_output(self):
        from services.stellaris_native_runtime.research import (
            discover_command_producers as tool,
        )

        image = self.image(b"\xc3")
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            sdk = root / "sdk.json"
            sdk.write_text(
                json.dumps(
                    {
                        "build_id": image.build_id,
                        "sha256": hashlib.sha256(image.data).hexdigest(),
                        "constructor_callsites": [],
                    }
                ),
                encoding="utf-8",
            )
            output = root / "new-evidence"
            args = [
                "tool",
                "--linux-binary",
                str(root / "unused.elf"),
                "--sdk",
                str(sdk),
                "--output",
                str(output),
                "--function-rva",
                "0x1000",
                "--function-rva",
                "0x9999",
            ]
            with (
                patch.object(tool.sys, "argv", args),
                patch.object(tool, "ElfImage", return_value=image),
            ):
                with contextlib.redirect_stdout(io.StringIO()):
                    tool.main()
                manifest = json.loads(
                    (output / "manifest.json").read_text(encoding="utf-8")
                )
                self.assertEqual(manifest["missing_requested_function_rvas"], [0x9999])
                self.assertEqual(manifest["selected_functions"], 1)
                self.assertEqual(manifest["new_native_calls"], 0)
                previous = (output / "manifest.json").read_bytes()
                with self.assertRaises(FileExistsError):
                    tool.main()
                self.assertEqual((output / "manifest.json").read_bytes(), previous)

    def test_mismatched_binary_is_rejected_before_creating_output(self):
        from services.stellaris_native_runtime.research import (
            discover_command_producers as tool,
        )

        image = self.image(b"\xc3")
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            sdk = root / "sdk.json"
            sdk.write_text(
                json.dumps({"build_id": "other-build", "sha256": "wrong"}),
                encoding="utf-8",
            )
            output = root / "must-not-exist"
            args = [
                "tool",
                "--linux-binary",
                "unused",
                "--sdk",
                str(sdk),
                "--output",
                str(output),
            ]
            with (
                patch.object(tool.sys, "argv", args),
                patch.object(tool, "ElfImage", return_value=image),
                self.assertRaisesRegex(ValueError, "exact ELF identity differ"),
            ):
                tool.main()
            self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
