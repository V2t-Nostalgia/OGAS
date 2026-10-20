"""Bounded external-memory hints for recovered country-scoped IDs.

No native function calls, injection, memory writes or legality claims. The
reader is supplied by an existing read-only process audit or an offline fixture.
"""

from __future__ import annotations

import struct
from collections.abc import Callable


class ReadBudget:
    def __init__(self, read: Callable[[int, int], bytes]):
        self.read = read
        self.bytes = 0
        self.calls = 0

    def __call__(self, address: int, size: int) -> bytes:
        if (
            type(address) is not int
            or type(size) is not int
            or not 0 < address < 2**64
            or not 0 < size <= 65536
            or address + size > 2**64
        ):
            raise ValueError("invalid_read_bounds")
        if self.bytes + size > 262144 or self.calls >= 4096:
            raise ValueError("read_budget_exhausted")
        self.calls += 1
        self.bytes += size
        data = self.read(address, size)
        if len(data) != size:
            raise OSError("short_memory_read")
        return data


def discover_scoped_ids(
    read: Callable[[int, int], bytes],
    module_base: int,
    country_pointer: int,
    recipe: dict,
    *,
    scan_limit: int = 256,
    candidate_limit: int = 16,
) -> dict:
    """Read possible ID values, preserving the native search order and width.

    Even identical before/after observations are not a frozen-world guarantee.
    In particular native definition validity and caller authority are unknown.
    """
    if (
        type(scan_limit) is not int
        or type(candidate_limit) is not int
        or not 1 <= scan_limit <= 1024
        or not 1 <= candidate_limit <= 16
    ):
        raise ValueError("unsafe_discovery_bounds")
    if (
        type(module_base) is not int
        or type(country_pointer) is not int
        or not 0 <= module_base < 2**64
        or not 0 < country_pointer < 2**64
    ):
        raise ValueError("invalid_scope_pointer")
    if (
        recipe.get("scope_type") != "CCountry"
        or recipe.get("entry_stride") != 8
        or recipe.get("search_direction") not in ("forward", "reverse")
    ):
        raise ValueError("unsupported_scoped_recipe")
    member_id = recipe.get("identity_kind") == "country_member_value_not_TPdxRef"
    definition_join = (
        recipe.get("identity_kind")
        == "loaded_definition_index_to_country_member_not_TPdxRef"
    )
    if not member_id and not definition_join:
        raise ValueError("unsupported_identity_kind")
    if member_id and recipe.get("identity_width") not in (2, 4):
        raise ValueError("unsupported_identity_width")
    if definition_join and recipe.get("definition_entry_stride") != 8:
        raise ValueError("unsupported_definition_stride")
    for key in (
        "data_offset",
        "count_offset",
        "identity_offset" if member_id else "definition_pointer_member_offset",
    ):
        if type(recipe.get(key)) is not int or not 0 <= recipe[key] < 65536:
            raise ValueError("unsupported_member_offset")
    for key in (
        ("null_rva", "definition_database_rva", "definition_null_rva")
        if definition_join
        else ("null_rva",)
    ):
        if type(recipe.get(key)) is not int or not 0 < recipe[key] < 0x10000000:
            raise ValueError("unsupported_global_rva")

    budget = ReadBudget(read)
    observations: dict[tuple[int, int], bytes] = {}

    def observe(address, size):
        key = address, size
        value = budget(address, size)
        if key in observations and observations[key] != value:
            raise OSError("memory_changed_during_discovery")
        observations[key] = value
        return value

    def integer(address, width=8, signed=False):
        return int.from_bytes(observe(address, width), "little", signed=signed)

    def pointers(owner, data_offset, count_offset, limit, reverse=False):
        count = integer(owner + count_offset, 4, True)
        if not 0 <= count <= 1000000:
            raise ValueError("invalid_array_count")
        pointer = integer(owner + data_offset)
        if count and not pointer:
            raise ValueError("missing_array_data")
        start = max(0, count - limit) if reverse else 0
        size = min(count, limit)
        raw = observe(pointer + start * 8, size * 8) if size else b""
        values = [
            (start + index, value[0])
            for index, value in enumerate(struct.iter_unpack("<Q", raw))
        ]
        return count, list(reversed(values)) if reverse else values

    null = integer(module_base + recipe["null_rva"])
    count, objects = pointers(
        country_pointer,
        recipe["data_offset"],
        recipe["count_offset"],
        scan_limit,
        recipe["search_direction"] == "reverse",
    )
    definitions, definition_count, definition_truncated = {}, None, False
    if objects and definition_join:
        for key in ("definition_data_offset", "definition_count_offset"):
            if type(recipe.get(key)) is not int or not 0 <= recipe[key] < 65536:
                raise ValueError("unsupported_definition_offset")
        database = integer(module_base + recipe["definition_database_rva"])
        definition_null = integer(module_base + recipe["definition_null_rva"])
        if not database:
            raise ValueError("missing_definition_database")
        definition_count, entries = pointers(
            database,
            recipe["definition_data_offset"],
            recipe["definition_count_offset"],
            4096,
        )
        definition_truncated = definition_count > len(entries)
        for index, pointer in entries:
            if pointer not in (0, definition_null):
                definitions.setdefault(pointer, index)

    hints, seen, duplicates = [], set(), 0
    for index, pointer in objects:
        if pointer in (0, null):
            continue
        if member_id:
            identity = integer(
                pointer + recipe["identity_offset"], recipe["identity_width"]
            )
        else:
            definition = integer(pointer + recipe["definition_pointer_member_offset"])
            if definition not in definitions:
                continue
            identity = definitions[definition]
        if identity in seen:
            duplicates += 1
            continue
        seen.add(identity)
        if len(hints) < candidate_limit:
            hints.append(
                {
                    "value": identity,
                    "object_pointer": pointer,
                    "source_array_index": index,
                }
            )

    stable = all(
        budget(address, size) == value
        for (address, size), value in observations.items()
    )
    return {
        "class": recipe["class"],
        "evidence_level": "read_only_candidate_hint_not_native_validation",
        "identity_kind": recipe["identity_kind"],
        "source_count": count,
        "scanned_entries": len(objects),
        "array_truncated": count > len(objects),
        "definition_count": definition_count,
        "definition_scan_truncated": definition_truncated,
        "hints": hints,
        "duplicate_ids_in_scan": duplicates,
        "hints_truncated": len(seen) > len(hints),
        "selected_bytes_unchanged": stable,
        "consistency": "double_read_not_frozen_world",
        "native_lookup_called": False,
        "native_is_valid": None,
        "requires_game_thread_native_resolution": True,
        "runtime_candidate_provider_implemented": False,
        "submitted": False,
        "read_calls": budget.calls,
        "read_bytes": budget.bytes,
    }
