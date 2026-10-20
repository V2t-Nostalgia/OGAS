"""Emit the same recovered engine layouts for OGAS research and production builders."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path


def catalog_fingerprint(catalog: dict) -> str:
    return hashlib.sha256(
        json.dumps(catalog, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def recovered_command_name(command: dict, index: int) -> str:
    return command.get("token_name") or f"token_{command.get('token') or 0:x}_{index}"


def field_layout(field: dict, platform: str) -> tuple[str, int, int, bool]:
    kind = field.get("storage_kind", field.get("kind", "other"))
    if field.get("indirect") or field.get("linux_indirect"):
        kind = "definition_pointer"
    offset = field.get("offset", field.get("linux_off"))
    widths = {
        "ref": 4,
        "u32": 4,
        "i32": 4,
        "u8": 1,
        "bool": 1,
        "u64": 8,
        "i64": 8,
        "game_date32": 4,
    }
    width = widths.get(kind, 0)
    if kind == "bool" and field.get("bit_mask", 0) > 255:
        kind, width = "unsupported_bitfield", 0
    if platform == "linux-x86_64":
        if kind == "definition_pointer" and field.get("definition_type"):
            width = 8
        elif (
            kind == "string"
            and field.get("native_type") == "CString"
            and field.get("assignment_rva")
            or kind in ("reference_array", "native_text_value")
            and field.get("assignment_rva")
        ):
            width = field["native_size"]
    direct = field.get("confidence", "") in {
        "direct_dataflow",
        "arg",
        "lea",
        "pre",
        "post",
        "load",
    }
    if platform == "linux-x86_64":
        direct = field.get("confidence") == "direct_dataflow"
    # Uniform/container writers also contain an 'int' count argument. That is
    # not a scalar field, even when register flow recovers its address.
    writer = field.get("writer", "")
    if kind != "reference_array" and any(
        part in writer for part in ("Uniform", "Array", "Vector", "Label")
    ):
        kind, width = "container", 0
    return (
        kind,
        offset or 0,
        width,
        (
            direct
            and offset is not None
            and width != 0
            and not field.get("native_assignment_required", False)
        ),
    )


def flat_layout_complete(command: dict, platform: str) -> bool:
    """Only tightly covered POD/ref payloads are eligible for automatic probing."""
    fields = command["fields"]
    if not fields or command.get("serializer_subobjects"):
        return False
    if len({f.get("name") for f in fields}) != len(fields):
        return False
    cursor = 0x1C if platform == "linux-x86_64" else 0x20
    for field in sorted(fields, key=lambda f: field_layout(f, platform)[1]):
        _, offset, width, writable = field_layout(field, platform)
        if not writable or not field.get("name") or offset != cursor:
            return False
        cursor += width
    return (cursor + 7) // 8 * 8 == command.get("size")


def population_layout_complete(command: dict, platform: str) -> bool:
    """Require recovered writes or ABI padding for every unrepresented byte.

    Unlike the initial POD-only gate, this accepts proven native subobjects and
    alignment holes, not arbitrary unaccounted payloads.
    """
    if platform != "linux-x86_64":
        return flat_layout_complete(command, platform)
    fields = command.get("population_fields", command["fields"])
    if not fields:
        return bool(command.get("empty_payload_proven") and command.get("size") == 32
                    and not command.get("serializer_subobjects"))
    if (
        command.get("nested_recovery_gaps")
        or command.get("serializer_subobjects")
    ):
        return False
    if len({f.get("name") for f in fields}) != len(fields):
        return False
    spans = []
    for field in fields:
        _, off, width, writable = field_layout(field, platform)
        if (
            not field.get("name")
            or not writable
            or off < 0x1C
            or off + width > (command.get("size") or 0)
        ):
            return False
        if any(off < end and start < off + width for start, end in spans):
            return False
        spans.append((off, off + width))
    writes = (command.get("factory_evidence") or {}).get("writes", [])
    # A nested native vptr can itself follow ABI padding. Merge its proven
    # initializer span before checking gaps, instead of treating the entire
    # padding + initialized vptr as one unexplained hole before the next field.
    proof = [(start, end, min(end - start, 8)) for start, end in spans]
    for write in writes:
        start, end = write["offset"], write["offset"] + write["width"]
        if start < 0 or end > command["size"]:
            return False
        if end > 0x1C:
            proof.append((max(0x1C, start), end, min(write["width"], 8)))
    # A proven inline value's tail padding belongs to that value, not the
    # alignment of the next serialized byte field. It is never a writable field.
    for region in command.get("native_value_regions", []):
        if not region.get("layout_verified") or region.get("kind") != "nonowning_native_coordinate":
            continue
        start, size = region["offset"], region["size"]
        members = {f["name"]: f for f in fields}
        if (region.get("alignment") != 8 or not 28 <= start < start + size <= command["size"] or
                set(region.get("members", {})) != {"x", "y", "origin", "randomized", "visual_height"} or
                any(name not in members or not start <= field_layout(members[name], platform)[1] < start + size
                    for name in region["members"].values()) or
                not any(w["offset"] == start and w["width"] == 8 and w.get("value") in
                        (["rva", region["vtable_rva"]], ("rva", region["vtable_rva"])) for w in writes)):
            return False
        end = start + region["initialized_extent"]
        if (size % 8 or not 0 <= start + size - end < 8 or
                region.get("padding_intervals") != [[end, start + size]]):
            return False
        if end < start + size:
            proof.append((end, start + size, 1))
    cursor = 0x1C
    for start, end, alignment in sorted(proof, key=lambda s: (s[0], -s[2], -s[1])) + [
        (command["size"], command["size"], 8)
    ]:
        if start > cursor and (
            alignment not in (1, 2, 4, 8)
            or start != (cursor + alignment - 1) // alignment * alignment
        ):
            return False
        cursor = max(cursor, end)
    return True


def emit_header(catalog: dict, path: Path) -> None:
    from scoped_id_recovery import scoped_id_bindings

    lines = [
        "// GENERATED by tools/sdk_recovery/recover_sdk.py. DO NOT EDIT.",
        "// Structure evidence only: no Action registration or live_verified claim.",
        "#pragma once",
        "#include <array>",
        '#include "iag_native_runtime/sdk_metadata.h"',
        "namespace iag::native_runtime::generated {",
    ]
    commands = catalog["commands"]
    for index, command in enumerate(commands):
        fields = command.get("population_fields", command["fields"])
        counts = Counter(f.get("name") for f in fields)
        for n, f in enumerate(fields):
            values = [str(v["value"]) for v in f.get("scalar_candidates", [])]
            lines.append(
                f"inline constexpr std::array<std::int64_t, {len(values)}> kValues{index}_{n} = {{{{"
                + ", ".join(values)
                + "}};"
            )
        lines.append(
            f"inline constexpr std::array<RecoveredField, {len(fields)}> kFields{index} = {{{{"
        )
        for n, f in enumerate(fields):
            kind, offset, width, writable = field_layout(f, catalog["platform"])
            writable = writable and counts[f.get("name")] == 1 and offset >= 0x1C
            writable = writable and offset + width <= (command.get("size") or 0)
            values = (
                json.dumps(f.get("name") or ""),
                json.dumps(kind),
                json.dumps(f.get("ref") or ""),
                hex(offset),
                str(width),
                str(writable).lower(),
                json.dumps(
                    f.get("definition_type")
                    or f.get("native_type")
                    or f.get("enum_type")
                    or ""
                ),
                hex(f.get("assignment_rva") or 0),
                hex(f.get("bit_mask") or 0),
                f"kValues{index}_{n}",
            )
            lines.append("  {" + ", ".join(values) + "},")
        lines.append("}};")
    lines.append(
        f"inline constexpr std::array<RecoveredCommand, {len(commands)}> kCommands = {{{{"
    )
    for index, c in enumerate(commands):
        slots = c["slots"]
        values = [
            json.dumps(recovered_command_name(c, index)),
            json.dumps(c.get("class") or ""),
        ]
        values += [
            hex(c.get(k) or 0)
            for k in (
                "token",
                "vtable",
                "factory",
                "size",
                "is_valid",
                "deleting_destructor",
                "token_getter",
            )
        ]
        values += [
            str(slots.get(k) if slots.get(k) is not None else 65)
            for k in ("is_valid", "deleting_destructor", "token")
        ]
        values.append(f"kFields{index}")
        values.append(str(flat_layout_complete(c, catalog["platform"])).lower())
        values.append(str(population_layout_complete(c, catalog["platform"])).lower())
        values.append(hex(c.get("token_evidence", {}).get("global_rva", 0)))
        values.append(str(c.get("lifecycle_probe_safe", False)).lower())
        values.append(str(c.get("context_free_validator", False)).lower())
        lines.append("  {" + ", ".join(values) + "},")
    lines.append("}};")
    scoped = scoped_id_bindings(catalog)
    lines.append(
        f"inline constexpr std::array<RecoveredScopedIdBinding, {len(scoped)}> kScopedIdBindings = {{{{"
    )
    for binding in scoped:
        values = [
            json.dumps(binding["command_class"]),
            hex(binding["field_offset"]),
            hex(binding["country_field_offset"]),
            json.dumps(binding["class"]),
            "ScopedIdKind::" + binding["kind"],
        ]
        values += [
            hex(binding[k])
            for k in (
                "lookup_rva",
                "null_rva",
                "data_offset",
                "count_offset",
                "member_offset",
            )
        ]
        values.append(str(binding["reverse"]).lower())
        values += [
            hex(binding[k])
            for k in (
                "definition_database_rva",
                "definition_null_rva",
                "definition_data_offset",
                "definition_count_offset",
            )
        ]
        lines.append("  {" + ", ".join(values) + "},")
    lines.append("}};")
    databases = catalog.get("object_databases", [])
    lines.append(
        f"inline constexpr std::array<RecoveredObjectDatabase, {len(databases)}> kObjectDatabases = {{{{"
    )
    for db in databases:
        lines.append(
            "  {"
            + json.dumps(db["class"])
            + ", "
            + ", ".join(hex(db[k]) for k in ("database_rva", "null_rva", "id_offset"))
            + "},"
        )
    lines.append("}};")
    definitions = catalog.get("definition_databases", [])
    lines.append(
        f"inline constexpr std::array<RecoveredDefinitionDatabase, {len(definitions)}> kDefinitionDatabases = {{{{"
    )
    for db in definitions:
        lines.append(
            "  {"
            + json.dumps(db["class"])
            + ", "
            + ", ".join(
                hex(db[k])
                for k in (
                    "database_rva",
                    "null_rva",
                    "data_offset",
                    "count_offset",
                    "key_offset",
                )
            )
            + "},"
        )
    lines.append("}};")
    native_values = catalog.get("native_text_values", [])
    lines.append(
        f"inline constexpr std::array<RecoveredNativeTextValue, {len(native_values)}> kNativeTextValues = {{{{"
    )
    for value in native_values:
        lines.append(
            "  {"
            + json.dumps(value["class"])
            + ", "
            + ", ".join(
                hex(value[k])
                for k in (
                    "size",
                    "construct_text_rva",
                    "move_assign_rva",
                    "destroy_rva",
                )
            )
            + "},"
        )
    lines.append("}};")
    for key in ("functions", "globals"):
        symbols = catalog.get(key, {})
        lines.append(
            f"inline constexpr std::array<RecoveredSymbol, {len(symbols)}> k{key.title()} = {{{{"
        )
        for name, symbol in sorted(symbols.items()):
            lines.append("  {" + json.dumps(name) + ", " + hex(symbol["rva"]) + "},")
        lines.append("}};")
    lines.extend(
        [
            "inline constexpr RecoveredSdk kRecoveredSdk{",
            "  " + json.dumps(catalog["platform"]) + ",",
            "  " + json.dumps(catalog["build_id"]) + ",",
            "  " + json.dumps(catalog["sha256"]) + ",",
            "  kCommands, kFunctions, kGlobals, kObjectDatabases, kDefinitionDatabases, kNativeTextValues, kScopedIdBindings, "
            + json.dumps(catalog_fingerprint(catalog))
            + "};",
            "}  // namespace iag::native_runtime::generated",
            "",
        ]
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")
