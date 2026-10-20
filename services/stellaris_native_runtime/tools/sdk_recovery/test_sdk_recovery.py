from __future__ import annotations

import importlib.util
import struct
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from emit_ogas import emit_header, field_layout, flat_layout_complete

HAS_DISASSEMBLER = all(
    importlib.util.find_spec(module) is not None
    for module in ("capstone", "elftools", "itanium_demangler")
)


@unittest.skipUnless(HAS_DISASSEMBLER, "install tools/sdk_recovery/requirements.txt")
class ElfSerializerTests(unittest.TestCase):
    def test_template_reference_fields_and_tail_writer(self) -> None:
        from capstone import CS_ARCH_X86, CS_MODE_64, Cs
        from linux_elf import extract_serializer

        code = bytearray.fromhex("53 48 89 fb 48 8d 57 1c 48 89 f7 be 88 2c 00 00")
        code += b"\xe8" + struct.pack("<i", 0x2000 - (0x1000 + len(code) + 5))
        code += bytes.fromhex("48 8d 53 20 be 3c 40 00 00")
        code += b"\xe9" + struct.pack("<i", 0x2100 - (0x1000 + len(code) + 5))
        md = Cs(CS_ARCH_X86, CS_MODE_64)
        md.detail = True

        class FixtureImage:
            def name(self, _symbol):
                return "CHireLeaderCommand::WriteCommandMembers(CWriter&)"

            def instructions(self, _symbol):
                return list(md.disasm(bytes(code), 0x1000))

            def target_name(self, address):
                return {
                    0x2000: "void CWriter::Write<CCountry>(int, TPdxRef<CCountry> const&)",
                    0x2100: "void CWriter::Write<CLeader>(int, TPdxRef<CLeader> const&)",
                }.get(address, "")

        result = extract_serializer(
            FixtureImage(), {"rva": 0x1000}, {0x2C88: "country", 0x403C: "leader"}
        )
        self.assertEqual(
            [
                (f["name"], f["kind"], f["ref"], f["linux_off"])
                for f in result["fields"]
            ],
            [("country", "ref", "CCountry", 0x1C), ("leader", "ref", "CLeader", 0x20)],
        )

    def test_template_writer_keeps_reference_type(self) -> None:
        from linux_elf import writer_kind

        self.assertEqual(
            writer_kind("void CWriter::Write<CCountry>(int, TPdxRef<CCountry> const&)"),
            ("ref", "CCountry"),
        )


class GeneratedMetadataTests(unittest.TestCase):
    def test_container_count_is_not_a_scalar_payload(self) -> None:
        field = {
            "name": "fleet",
            "kind": "i32",
            "linux_off": 0x1C,
            "confidence": "direct_dataflow",
            "writer": "void CWriter::WriteUniformWithSpace<TPdxRef<CFleet>>(int, TPdxRef<CFleet> const*, int)",
        }
        self.assertEqual(field_layout(field, "linux-x86_64")[0], "container")
        self.assertFalse(
            flat_layout_complete({"fields": [field], "size": 0x20}, "linux-x86_64")
        )

    def test_flat_probe_eligibility_requires_full_tight_payload(self) -> None:
        country = {
            "name": "country",
            "kind": "ref",
            "ref": "CCountry",
            "linux_off": 0x1C,
            "confidence": "direct_dataflow",
        }
        leader = {**country, "name": "leader", "ref": "CLeader", "linux_off": 0x20}
        command = {"fields": [country, leader], "size": 0x28}
        self.assertTrue(flat_layout_complete(command, "linux-x86_64"))
        self.assertFalse(
            flat_layout_complete({**command, "size": 0x30}, "linux-x86_64")
        )
        self.assertFalse(
            flat_layout_complete(
                {**command, "serializer_subobjects": ["nested"]}, "linux-x86_64"
            )
        )
        self.assertFalse(
            flat_layout_complete(
                {**command, "fields": [country, {**leader, "linux_off": 0x24}]},
                "linux-x86_64",
            )
        )

    def test_indirect_key_never_becomes_inline_string_or_scalar(self) -> None:
        kind, _offset, width, writable = field_layout(
            {
                "kind": "string",
                "linux_indirect": True,
                "offset": 0x28,
                "confidence": "load",
            },
            "windows-x64",
        )
        self.assertEqual(kind, "definition_pointer")
        self.assertEqual(width, 0)
        self.assertFalse(writable)

    def test_positional_field_remains_non_writable(self) -> None:
        self.assertFalse(
            field_layout(
                {"kind": "ref", "offset": 0x24, "confidence": "positional"},
                "windows-x64",
            )[3]
        )

    def test_duplicate_and_out_of_bounds_fields_are_non_writable(self) -> None:
        command = {
            "token_name": "sample",
            "class": "CSampleCommand",
            "token": 123,
            "vtable": 0x1000,
            "factory": 0x2000,
            "size": 0x28,
            "is_valid": 0x3000,
            "deleting_destructor": 0x4000,
            "token_getter": 0x5000,
            "slots": {"is_valid": 8, "deleting_destructor": 0, "token": 10},
            "fields": [
                {
                    "name": "duplicate",
                    "kind": "ref",
                    "ref": "CCountry",
                    "offset": offset,
                    "confidence": "post",
                }
                for offset in (0x20, 0x24)
            ]
            + [{"name": "outside", "kind": "u32", "offset": 0x27, "confidence": "arg"}],
        }
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "sdk.hpp"
            emit_header(
                {
                    "commands": [command],
                    "platform": "windows-x64",
                    "build_id": "test",
                    "sha256": "test",
                },
                path,
            )
            result = path.read_text(encoding="utf-8")
        self.assertNotIn(", true}", result)
        self.assertIn("0x2000", result)
        self.assertNotIn("ActionRegistration", result)


if __name__ == "__main__":
    unittest.main()
