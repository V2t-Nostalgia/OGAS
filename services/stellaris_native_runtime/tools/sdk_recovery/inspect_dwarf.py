#!/usr/bin/env python3
"""Check actual DWARF coverage before assuming .debug_info describes game types."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from elftools.elf.elffile import ELFFile


def inspect(binary: Path, wanted: set[str], max_dies: int = 2_000_000) -> dict:
    result = {
        "compilation_units": 0,
        "dies": 0,
        "truncated": False,
        "matched_types": [],
    }
    with binary.open("rb") as stream:
        elf = ELFFile(stream)
        result["has_debug_info"] = elf.has_dwarf_info(strict=True)
        if not result["has_debug_info"]:
            return result
        dwarf = elf.get_dwarf_info()
        for cu in dwarf.iter_CUs():
            result["compilation_units"] += 1
            for die in cu.iter_DIEs():
                result["dies"] += 1
                if result["dies"] > max_dies:
                    result["truncated"] = True
                    return result
                name = die.attributes.get("DW_AT_name")
                if name is None or not isinstance(name.value, bytes):
                    continue
                text = name.value.decode("utf-8", "replace")
                if text not in wanted or die.tag not in (
                    "DW_TAG_class_type",
                    "DW_TAG_structure_type",
                    "DW_TAG_union_type",
                ):
                    continue
                size = die.attributes.get("DW_AT_byte_size")
                members = []
                for child in die.iter_children():
                    if child.tag != "DW_TAG_member":
                        continue
                    m_name = child.attributes.get("DW_AT_name")
                    off = child.attributes.get("DW_AT_data_member_location")
                    members.append(
                        {
                            "name": m_name.value.decode("utf-8", "replace")
                            if m_name and isinstance(m_name.value, bytes)
                            else None,
                            "offset": off.value
                            if off and isinstance(off.value, int)
                            else None,
                        }
                    )
                result["matched_types"].append(
                    {
                        "name": text,
                        "die_offset": die.offset,
                        "byte_size": size.value if size else None,
                        "members": members,
                    }
                )
    return result


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--binary", type=Path, required=True)
    p.add_argument("--sdk", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args()
    sdk = json.loads(args.sdk.read_text(encoding="utf-8"))
    with args.binary.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    if digest != sdk["sha256"]:
        p.error("ELF fingerprint does not match the supplied SDK")
    wanted = {c["class"] for c in sdk["commands"]} | {
        d["class"] for d in sdk.get("object_databases", [])
    }
    wanted |= {
        f["native_type"]
        for c in sdk["commands"]
        for f in c.get("population_fields", [])
        if f.get("native_type")
    }
    wanted |= {
        "CCommand",
        "CGameState",
        "CGameIdler",
        "CWriter",
        "CReader",
        "CPersistentName",
        "CShipDesignImplementation",
    }
    result = inspect(args.binary, wanted)
    result.update(
        build_id=sdk["build_id"],
        binary_sha256=digest,
        wanted_types=len(wanted),
        metadata_applied=False,
    )
    with args.output.open("x", encoding="utf-8") as out:
        json.dump(result, out, indent=2)
        out.write("\n")
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
