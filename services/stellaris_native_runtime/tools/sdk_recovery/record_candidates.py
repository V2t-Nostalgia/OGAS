"""Offline record-source recovery and bounded read-only correlated hints.

No game calls or writes. A record is kept intact; membership is not legality.
"""

from __future__ import annotations

import re
import struct
from collections import Counter
from collections.abc import Callable

from scoped_id_candidates import ReadBudget

COUNTRY_RECORD = re.compile(
    rb"\x41\x57\x41\x56\x41\x54\x53\x50\x48\x63\x4f(?P<count>.)"
    rb"\x48\x85\xc9\x0f\x84\x8f\x00\x00\x00\x49\x89\xd6\x49\x89\xf7"
    rb"\x48\x8b\x5f(?P<data>.)\x48\x8b\x05(?P<database>.{4})"
    rb"\x48\xc1\xe1\x04\x4c\x8d\x24\x49\xeb\x0a\x48\x83\xc3\x30"
    rb"\x49\x83\xc4\xd0\x74\x6a\x48\x85\xc0\x74\x41"
    rb"\x8b\x4b(?P<country>.)\x89\xca\x81\xe2\xff\xff\xff\x00"
    rb"\x3b\x50\x20\x73\x31\x48\x8b\x70\x18\x48\xc1\xe2\x04"
    rb"\x48\x8b\x54\x16\x08\x48\x85\xd2\x74\x1f"
    rb"\x39\x4a(?P<country_id>.)\x75\x1a\x66\x2e\x0f\x1f\x84\x00\x00\x00\x00\x00"
    rb"\x4c\x39\xfa\x75\xbb\xeb\x15\x66\x0f\x1f\x84\x00\x00\x00\x00\x00"
    rb"\x48\x8b\x15(?P<null>.{4})\x4c\x39\xfa\x75\xa4\x41\x8b\x76\x14"
    rb"\x4c\x89\xf7\x48\x89\xda\xe8(?P<insert>.{4})"
    rb"\x48\x8b\x05(?P<database_again>.{4})\xeb\x8c\x48\x83\xc4\x08"
    rb"\x5b\x41\x5c\x41\x5e\x41\x5f\xc3",
    re.DOTALL,
)


def recover_country_record_source(image, symbol: dict, identity: dict) -> dict | None:
    """Require the full generation-checked filter/copy loop, not its name alone."""
    name = re.fullmatch(
        r"([CS]\w+)::\w+ const\(CCountry const\*, CPdxArray<([CS]\w+), int>&\)",
        image.name(symbol),
    )
    if name is None or symbol.get("size") != 176 or symbol.get("type") != "STT_FUNC":
        return None
    match = COUNTRY_RECORD.fullmatch(image.read(symbol["rva"], symbol["size"]))
    if match is None:
        return None

    def relative(key):
        return (
            symbol["rva"]
            + match.end(key)
            + int.from_bytes(match[key], "little", signed=True)
        )

    count, data, country, country_id = (
        int.from_bytes(match[key], "little", signed=True)
        for key in ("count", "data", "country", "country_id")
    )
    database, null, insert = relative("database"), relative("null"), relative("insert")
    owner, record = name.groups()
    expected_insert = (
        f"{record}& CPdxArray<{record}, int>::InsertAtEmplace<{record} const&>"
        f"(int, {record} const&)"
    )
    if (
        identity.get("evidence")
        != "complete_manager_counter_assign_then_record_array_insert"
        or identity.get("research_callable") is not False
        or identity.get("owner_class") != owner
        or identity.get("record_class") != record
        or identity.get("array_offset", -100) + 8 != data
        or identity.get("array_count_offset") != count
        or count < 0
        or data < 0
        or count % 4
        or data % 8
        or identity.get("insert_rva") != insert
        or relative("database_again") != database
        or image.target_name(database) != "TPdxRef<CCountry>::_pDatabase"
        or image.target_name(null) != "TPdxNullObject<CCountry>::_pInstance"
        or image.target_name(insert) != expected_insert
        or not 0 <= country <= 44
        or country % 4 != 0
        or country_id < 0
        or country_id % 4 != 0
        or type(identity.get("record_identity_offset")) is not int
        or not 0 <= identity["record_identity_offset"] <= 44
        or identity["record_identity_offset"] % 4
        or not all(0 < address < 0x10000000 for address in (database, null, insert))
    ):
        return None
    return {
        "owner_class": owner,
        "record_class": record,
        "filter_copy_rva": symbol["rva"],
        "data_offset": data,
        "count_offset": count,
        "entry_stride": 48,
        "country_field_offset": country,
        "country_id_offset": country_id,
        "country_database_rva": database,
        "country_null_rva": null,
        "identity_field_offset": identity["record_identity_offset"],
        "evidence": "complete_generation_checked_country_record_filter_copy",
        "native_output_allocation": True,
        "native_function_called": False,
        "runtime_candidate_provider_implemented": False,
    }


def discover_country_records(
    read: Callable[[int, int], bytes],
    module_base: int,
    owner_pointer: int,
    country_id: int,
    source: dict,
    fields: list[dict],
    definition: dict,
    *,
    scan_limit: int = 256,
    candidate_limit: int = 16,
) -> dict:
    """Retain copied field tuples only as hints, with generation/definition joins.

    The caller supplies an already identified owner pointer. This function does
    not acquire it by invoking a getter, nor parse a native CString from an
    untrusted pointer. Definition array indices are diagnostics, not semantic IDs.
    """
    if (
        type(module_base) is not int
        or not 0 <= module_base < 2**64
        or type(owner_pointer) is not int
        or not 0 < owner_pointer < 2**64
        or type(country_id) is not int
        or not 0 <= country_id < 0xFFFFFFFF
        or type(scan_limit) is not int
        or not 1 <= scan_limit <= 512
        or type(candidate_limit) is not int
        or not 1 <= candidate_limit <= 16
    ):
        raise ValueError("unsafe_record_discovery_bounds")
    if (
        source.get("evidence")
        != "complete_generation_checked_country_record_filter_copy"
        or source.get("entry_stride") != 48
        or source.get("runtime_candidate_provider_implemented") is not False
        or not isinstance(source.get("record_class"), str)
        or not re.fullmatch(r"[CS]\w+", source["record_class"])
        or not isinstance(definition.get("class"), str)
        or not re.fullmatch(r"[CS]\w+", definition["class"])
    ):
        raise ValueError("unsupported_record_source")
    for key in (
        "data_offset",
        "count_offset",
        "country_id_offset",
        "country_field_offset",
        "identity_field_offset",
    ):
        if type(source.get(key)) is not int or not 0 <= source[key] <= 65535:
            raise ValueError("invalid_record_offset")
    for key in ("country_field_offset", "identity_field_offset"):
        if source[key] % 4 or source[key] + 4 > 48:
            raise ValueError("invalid_record_member")
    for key in ("country_database_rva", "country_null_rva"):
        if type(source.get(key)) is not int or not 0 < source[key] < 0x10000000:
            raise ValueError("invalid_record_global")
    for key in ("database_rva", "null_rva"):
        if type(definition.get(key)) is not int or not 0 < definition[key] < 0x10000000:
            raise ValueError("invalid_record_definition")
    for key in ("data_offset", "count_offset"):
        if type(definition.get(key)) is not int or not 0 <= definition[key] <= 65535:
            raise ValueError("invalid_record_definition")
    if not fields or len(fields) > 16:
        raise ValueError("unsupported_record_fields")
    spans, names, resource_field, country_field, identity_field = (
        [],
        set(),
        None,
        None,
        None,
    )
    for field in fields:
        name, kind, off, width = (
            field.get(k) for k in ("name", "kind", "offset", "width")
        )
        if (
            not isinstance(name, str)
            or not name
            or name in names
            or type(off) is not int
            or type(width) is not int
            or kind not in ("i32", "u32", "ref", "definition_pointer")
            or width != (8 if kind == "definition_pointer" else 4)
            or off < 0
            or off + width > 48
            or off % width
        ):
            raise ValueError("unsupported_record_fields")
        names.add(name)
        spans.append((off, off + width))
        if kind == "definition_pointer":
            if resource_field is not None or field.get("type") != definition.get(
                "class"
            ):
                raise ValueError("ambiguous_record_definition")
            resource_field = field
        if kind == "ref":
            if (
                country_field is not None
                or field.get("type") != "CCountry"
                or off != source["country_field_offset"]
            ):
                raise ValueError("unsupported_record_reference")
            country_field = field
        if off == source["identity_field_offset"] and kind == "i32":
            identity_field = field
    if (
        resource_field is None
        or country_field is None
        or identity_field is None
        or any(
            a < d and c < b for n, (a, b) in enumerate(spans) for c, d in spans[n + 1 :]
        )
    ):
        raise ValueError("incomplete_or_overlapping_record_fields")

    budget, observed = ReadBudget(read), {}

    def observe(address, size):
        data = budget(address, size)
        old = observed.setdefault((address, size), data)
        if data != old:
            raise OSError("memory_changed_during_record_discovery")
        return data

    def integer(address, size=8, signed=False):
        return int.from_bytes(observe(address, size), "little", signed=signed)

    database = integer(module_base + source["country_database_rva"])
    null_country = integer(module_base + source["country_null_rva"])
    if not database:
        raise ValueError("missing_country_database")
    slots = integer(database + 0x20, 4)
    if slots > 1000000 or (country_id & 0xFFFFFF) >= slots:
        raise ValueError("country_generation_or_slot_mismatch")
    entries = integer(database + 0x18)
    if not entries:
        raise ValueError("missing_country_slots")
    country = integer(entries + (country_id & 0xFFFFFF) * 16 + 8)
    if (
        not country
        or country == null_country
        or integer(country + source["country_id_offset"], 4) != country_id
    ):
        raise ValueError("country_generation_or_slot_mismatch")

    definition_db = integer(module_base + definition["database_rva"])
    null_definition = integer(module_base + definition["null_rva"])
    if not definition_db:
        raise ValueError("missing_definition_database")
    definition_count = integer(definition_db + definition["count_offset"], 4, True)
    if not 0 <= definition_count <= 1000000:
        raise ValueError("invalid_definition_count")
    definition_data = integer(definition_db + definition["data_offset"])
    if definition_count and not definition_data:
        raise ValueError("missing_definition_data")
    definitions = {}
    definition_scan = min(definition_count, 4096)
    if definition_scan:
        for n, (pointer,) in enumerate(
            struct.iter_unpack("<Q", observe(definition_data, definition_scan * 8))
        ):
            if pointer and pointer != null_definition:
                definitions.setdefault(pointer, n)
    count = integer(owner_pointer + source["count_offset"], 4, True)
    if not 0 <= count <= 1000000:
        raise ValueError("invalid_record_count")
    data = integer(owner_pointer + source["data_offset"])
    if count and not data:
        raise ValueError("missing_record_data")
    scan = min(count, scan_limit)
    raw = observe(data, scan * 48) if scan else b""
    candidates, rejected, identities = [], Counter(), Counter()
    for index in range(scan):
        record = raw[index * 48 : (index + 1) * 48]
        values = {
            f["name"]: int.from_bytes(
                record[f["offset"] : f["offset"] + f["width"]],
                "little",
                signed=f["kind"] == "i32",
            )
            for f in fields
        }
        if values[country_field["name"]] != country_id:
            rejected["other_or_stale_country"] += 1
            continue
        if values[identity_field["name"]] < 0:
            rejected["negative_unassigned_record_identity"] += 1
            continue
        identities[values[identity_field["name"]]] += 1
        resource = values[resource_field["name"]]
        if resource not in definitions:
            rejected["definition_not_in_bounded_loaded_database"] += 1
            continue
        candidates.append(
            {
                "source_array_index": index,
                "values": values,
                "definition_array_index": definitions[resource],
            }
        )
    unambiguous = [
        c for c in candidates if identities[c["values"][identity_field["name"]]] == 1
    ]
    rejected["duplicate_record_identity"] += len(candidates) - len(unambiguous)
    stable = all(
        budget(address, size) == value for (address, size), value in observed.items()
    )
    hints = unambiguous[:candidate_limit] if stable else []
    return {
        "record_class": source["record_class"],
        "country_id": country_id,
        "source_count": count,
        "scanned_entries": scan,
        "array_truncated": scan < count,
        "definition_count": definition_count,
        "definition_scan_truncated": definition_scan < definition_count,
        "hints": hints,
        "hints_truncated": len(unambiguous) > candidate_limit,
        "rejected_in_scan": dict(rejected),
        "selected_bytes_unchanged": stable,
        "identity_uniqueness_scope": "bounded_scan_only",
        "duplicate_identities_in_scan": sorted(
            key for key, count in identities.items() if count > 1
        ),
        "consistency": "double_read_not_frozen_world",
        "evidence_level": "correlated_record_hint_not_native_validation",
        "requires_game_thread_native_resolution": True,
        "runtime_candidate_provider_implemented": False,
        "definition_key_resolved": False,
        "native_is_valid": None,
        "native_function_called": False,
        "submitted": False,
        "read_calls": budget.calls,
        "read_bytes": budget.bytes,
    }
