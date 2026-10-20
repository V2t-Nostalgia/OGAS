#!/usr/bin/env python3
"""Verify an exact Stellaris binary against a native-runtime evidence manifest."""

from __future__ import annotations

import argparse
import hashlib
import json
import mmap
import struct
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any


def _number(value: Any) -> int:
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        return int(value, 0)
    raise TypeError(f"expected integer or integer string, got {type(value).__name__}")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _slice(view: mmap.mmap, offset: int, size: int) -> bytes:
    if offset < 0 or size < 0 or offset + size > len(view):
        raise ValueError(f"binary range outside file: offset={offset:#x} size={size:#x}")
    return view[offset : offset + size]


@dataclass(frozen=True)
class Section:
    name: str
    address: int
    offset: int
    size: int
    raw_size: int


class BinaryImage:
    def __init__(self, view: mmap.mmap) -> None:
        self.view = view
        self.build_id: str | None = None
        self.pe_timestamp: int | None = None
        self.image_size = 0
        self.sections: dict[str, Section] = {}
        self.load_segments: list[tuple[int, int, int]] = []

    def rva_bytes(self, rva: int, size: int) -> bytes:
        for address, offset, file_size in self.load_segments:
            if address <= rva and rva + size <= address + file_size:
                return _slice(self.view, offset + rva - address, size)
        raise ValueError(f"RVA is not file-backed: {rva:#x}")


def _parse_pe(view: mmap.mmap) -> BinaryImage:
    if _slice(view, 0, 2) != b"MZ":
        raise ValueError("missing DOS signature")
    pe_offset = struct.unpack_from("<I", view, 0x3C)[0]
    if _slice(view, pe_offset, 4) != b"PE\0\0":
        raise ValueError("missing PE signature")
    machine, section_count, timestamp = struct.unpack_from(
        "<HHI", view, pe_offset + 4
    )
    if machine != 0x8664:
        raise ValueError(f"unsupported PE machine: {machine:#x}")
    optional_size = struct.unpack_from("<H", view, pe_offset + 20)[0]
    optional_offset = pe_offset + 24
    if struct.unpack_from("<H", view, optional_offset)[0] != 0x20B:
        raise ValueError("PE image is not PE32+")

    image = BinaryImage(view)
    image.pe_timestamp = timestamp
    image.image_size = struct.unpack_from("<I", view, optional_offset + 56)[0]
    section_offset = optional_offset + optional_size
    for index in range(section_count):
        current = section_offset + index * 40
        name = _slice(view, current, 8).split(b"\0", 1)[0].decode("ascii")
        virtual_size, address, raw_size, raw_offset = struct.unpack_from(
            "<IIII", view, current + 8
        )
        image.sections[name] = Section(
            name=name,
            address=address,
            offset=raw_offset,
            size=virtual_size,
            raw_size=raw_size,
        )
        image.load_segments.append((address, raw_offset, raw_size))
    return image


def _align4(value: int) -> int:
    return (value + 3) & ~3


def _parse_elf(view: mmap.mmap) -> BinaryImage:
    if _slice(view, 0, 4) != b"\x7fELF":
        raise ValueError("missing ELF signature")
    if view[4] != 2 or view[5] != 1:
        raise ValueError("ELF image is not little-endian ELF64")
    (
        _type,
        machine,
        _version,
        _entry,
        program_offset,
        section_offset,
        _flags,
        _header_size,
        program_entry_size,
        program_count,
        section_entry_size,
        section_count,
        string_section_index,
    ) = struct.unpack_from("<HHIQQQIHHHHHH", view, 16)
    if machine != 0x3E:
        raise ValueError(f"unsupported ELF machine: {machine:#x}")

    image = BinaryImage(view)
    max_load_end = 0
    for index in range(program_count):
        current = program_offset + index * program_entry_size
        (
            segment_type,
            _segment_flags,
            file_offset,
            virtual_address,
            _physical_address,
            file_size,
            memory_size,
            _alignment,
        ) = struct.unpack_from("<IIQQQQQQ", view, current)
        if segment_type == 1:
            image.load_segments.append((virtual_address, file_offset, file_size))
            max_load_end = max(max_load_end, virtual_address + memory_size)
        elif segment_type == 4:
            cursor = file_offset
            end = file_offset + file_size
            while cursor + 12 <= end:
                name_size, description_size, note_type = struct.unpack_from(
                    "<III", view, cursor
                )
                cursor += 12
                name = _slice(view, cursor, name_size)
                cursor += _align4(name_size)
                description = _slice(view, cursor, description_size)
                cursor += _align4(description_size)
                if note_type == 3 and name.rstrip(b"\0") == b"GNU":
                    image.build_id = description.hex()
    image.image_size = (max_load_end + 0xFFF) & ~0xFFF

    section_headers: list[tuple[int, int, int, int]] = []
    for index in range(section_count):
        current = section_offset + index * section_entry_size
        name_index, _kind, _flags, address, file_offset, size = struct.unpack_from(
            "<IIQQQQ", view, current
        )
        section_headers.append((name_index, address, file_offset, size))
    if string_section_index >= len(section_headers):
        raise ValueError("invalid ELF section-name table index")
    _, _, names_offset, names_size = section_headers[string_section_index]
    names = _slice(view, names_offset, names_size)
    for name_index, address, file_offset, size in section_headers:
        if name_index >= len(names):
            continue
        end = names.find(b"\0", name_index)
        if end < 0:
            continue
        name = names[name_index:end].decode("ascii", errors="replace")
        image.sections[name] = Section(name, address, file_offset, size, size)
    return image


def _verify(manifest: dict[str, Any], binary: Path) -> dict[str, Any]:
    errors: list[str] = []
    expected_size = _number(manifest["binary"]["size"])
    actual_size = binary.stat().st_size
    if actual_size != expected_size:
        errors.append(f"binary size: expected {expected_size}, got {actual_size}")
    expected_sha = manifest["binary"]["sha256"].lower()
    actual_sha = _sha256(binary)
    if actual_sha != expected_sha:
        errors.append(f"binary sha256: expected {expected_sha}, got {actual_sha}")

    with binary.open("rb") as stream, mmap.mmap(
        stream.fileno(), 0, access=mmap.ACCESS_READ
    ) as view:
        platform = manifest["platform"]
        if platform == "windows-x64":
            image = _parse_pe(view)
        elif platform == "linux-x86_64":
            image = _parse_elf(view)
        else:
            raise ValueError(f"unsupported manifest platform: {platform}")
        expected_image_size = _number(manifest["binary"]["image_size"])
        if image.image_size != expected_image_size:
            errors.append(
                f"image size: expected {expected_image_size:#x}, got {image.image_size:#x}"
            )
        if platform == "windows-x64":
            expected_timestamp = _number(manifest["binary"]["pe_timestamp"])
            if image.pe_timestamp != expected_timestamp:
                errors.append(
                    "PE timestamp: expected "
                    f"{expected_timestamp:#x}, got {image.pe_timestamp:#x}"
                )
        else:
            expected_build_id = manifest["binary"]["elf_build_id"].lower()
            if image.build_id != expected_build_id:
                errors.append(
                    f"ELF Build ID: expected {expected_build_id}, got {image.build_id}"
                )

        text = image.sections.get(".text")
        if text is None:
            errors.append(".text section is missing")
        else:
            expected_text = manifest["text"]
            for label, actual, key in (
                (".text RVA", text.address, "rva"),
                (".text virtual size", text.size, "virtual_size"),
                (".text raw size", text.raw_size, "raw_size"),
            ):
                expected = _number(expected_text[key])
                if actual != expected:
                    errors.append(f"{label}: expected {expected:#x}, got {actual:#x}")
            text_hash = hashlib.sha256(
                _slice(view, text.offset, text.raw_size)
            ).hexdigest()
            if text_hash != expected_text["sha256"].lower():
                errors.append(
                    f".text sha256: expected {expected_text['sha256']}, got {text_hash}"
                )

        anchors_checked = 0
        for anchor in manifest["anchors"]:
            expected = bytes.fromhex(anchor["prefix_hex"])
            rva = _number(anchor["rva"])
            actual = image.rva_bytes(rva, len(expected))
            anchors_checked += 1
            if actual != expected:
                errors.append(
                    f"anchor {anchor['name']} at {rva:#x}: "
                    f"expected {expected.hex()}, got {actual.hex()}"
                )

    return {
        "ok": not errors,
        "profile_id": manifest["profile_id"],
        "platform": manifest["platform"],
        "binary": str(binary),
        "sha256": actual_sha,
        "anchors_checked": anchors_checked,
        "errors": errors,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--binary", required=True, type=Path)
    arguments = parser.parse_args()
    manifest = json.loads(arguments.manifest.read_text(encoding="utf-8"))
    result = _verify(manifest, arguments.binary)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
