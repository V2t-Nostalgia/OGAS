"""Offline proof of country-owned scalar IDs, never TPdxRef reclassification."""

from __future__ import annotations

import re
import struct
from collections import Counter

FORWARD = re.compile(
    rb"\x8b\x4f(?P<count>.)\x85\xc9\x7e\x1b\x48\x8b\x57(?P<data>.)"
    rb"\x31\xff\x0f\x1f\x00\x48\x8b\x04\xfa\x39\x70(?P<id>.)"
    rb"\x74\x10\x48\x83\xc7\x01\x48\x39\xf9\x75\xee"
    rb"\x48\x8b\x05(?P<null>.{4})\xc3",
    re.DOTALL,
)
REVERSE = re.compile(
    rb"\x8b\x8f(?P<count>.{4})\x48\x8b\x97(?P<data>.{4})\x0f\x1f\x00"
    rb"\x85\xc9\x7e\x13\x48\x8b\x44\xca\xf8\x48\x83\xc1\xff"
    rb"\x66\x39\xb0(?P<id>.{4})\x75\xea\xc3"
    rb"\x48\x8b\x05(?P<null>.{4})\xc3",
    re.DOTALL,
)
DEFINITION_JOIN = re.compile(
    rb"\x41\x56\x53\x50\x49\x89\xfe\x85\xf6\x78\x18"
    rb"\x48\x8b\x05(?P<database>.{4})\x39\x70(?P<definition_count>.)\x7e\x0c"
    rb"\x48\x8b\x40(?P<definition_data>.)\x89\xf1\x48\x8b\x1c\xc8\xeb\x07"
    rb"\x48\x8b\x1d(?P<definition_null>.{4})\x48\x8b\x03\x48\x89\xdf"
    rb"\xff\x50\x10\x84\xc0\x74\x2c\x49\x63\x8e(?P<count>.{4})"
    rb"\x48\x85\xc9\x74\x20\x49\x8b\x96(?P<data>.{4})"
    rb"\x48\xc1\xe1\x03\x31\xf6\x48\x8b\x04\x32"
    rb"\x48\x39\x58(?P<definition_member>.)\x74\x10"
    rb"\x48\x83\xc6\x08\x48\x39\xf1\x75\xed"
    rb"\x48\x8b\x05(?P<null>.{4})\x48\x83\xc4\x08\x5b\x41\x5e\xc3",
    re.DOTALL,
)
SCOPED_VALIDATOR = re.compile(
    rb"\x41\x56\x53\x50\x49\x89\xfe\x48\x8b\x0d(?P<database>.{4})"
    rb"\x48\x85\xc9\x74\x28\x41\x8b\x46(?P<country>.)\x89\xc2"
    rb"\x81\xe2\xff\xff\xff\x00\x3b\x51\x20\x73\x17"
    rb"\x48\x8b\x49\x18\x48\xc1\xe2\x04\x48\x8b\x5c\x11\x08"
    rb"\x48\x85\xdb\x74\x05\x39\x43(?P<country_id>.)\x74\x07"
    rb"\x48\x8b\x1d(?P<null>.{4})\x48\x8b\x03\x48\x89\xdf"
    rb"\xff\x50\x58\x84\xc0\x74\x1c\x41\x8b\x76(?P<id>.)"
    rb"\x48\x89\xdf\xe8(?P<lookup>.{4})\x48\x8b\x08\x48\x89\xc7"
    rb"\x48\x83\xc4\x08\x5b\x41\x5e\xff\x61\x40"
    rb"\x31\xc0\x48\x83\xc4\x08\x5b\x41\x5e\xc3",
    re.DOTALL,
)
PROJECT_PREFIX = (
    rb"\x41\x56\x53\x50\x49\x89\xfe\x48\x8b\x0d(?P<database>.{4})"
    rb"\x48\x85\xc9\x74\x28\x41\x8b\x46(?P<country>.)\x89\xc2"
    rb"\x81\xe2\xff\xff\xff\x00\x3b\x51\x20\x73\x17"
    rb"\x48\x8b\x49\x18\x48\xc1\xe2\x04\x48\x8b\x5c\x11\x08"
    rb"\x48\x85\xdb\x74\x05\x39\x43(?P<country_id>.)\x74\x07"
    rb"\x48\x8b\x1d(?P<null>.{4})\x48\x8b\x03\x48\x89\xdf"
    rb"\xff\x50\x58\x84\xc0\x74(?P<country_reject>.)\x41\x8b\x76(?P<id>.)"
    rb"\x48\x89\xdf\xe8(?P<lookup>.{4})\x49\x89\xc6\x48\x8b\x00"
    rb"\x4c\x89\xf7\xff\x50\x40\x84\xc0\x74(?P<project_reject>.)"
)
PROJECT_FAILURE = rb"(?P<failure>\x31\xc0\x48\x83\xc4\x08\x5b\x41\x5e\xc3)"
PROJECT_RESEARCH_VALIDATOR = re.compile(
    PROJECT_PREFIX + rb"\x48\x8d\xbb(?P<technology_offset>.{4})\x4c\x89\xf6"
    rb"\xe8(?P<research_status>.{4})\x84\xc0\x74\x0a"
    + PROJECT_FAILURE
    + rb"\x4c\x89\xf7\x48\x89\xde\xba\x01\x00\x00\x00\x31\xc9"
    rb"\x48\x83\xc4\x08\x5b\x41\x5e\xe9(?P<can_research>.{4})",
    re.DOTALL,
)
PROJECT_CANCEL_VALIDATOR = re.compile(
    PROJECT_PREFIX + rb"\x48\x81\xc3(?P<technology_offset>.{4})\x48\x89\xdf\x4c\x89\xf6"
    rb"\x48\x83\xc4\x08\x5b\x41\x5e\xe9(?P<research_status>.{4})" + PROJECT_FAILURE,
    re.DOTALL,
)


def recover_scoped_validator_binding(
    image, symbol: dict, accessors: dict
) -> dict | None:
    """Prove the complete caller's generation-checked country-to-ID binding.

    No native calls are made. In particular the indirect country predicate is
    retained as a guard, not interpreted as blanket actor permission.
    """
    if symbol.get("size") not in (117, 142, 161):
        return None
    code = image.read(symbol["rva"], symbol["size"])
    match = next(
        (
            m
            for p in (
                SCOPED_VALIDATOR,
                PROJECT_RESEARCH_VALIDATOR,
                PROJECT_CANCEL_VALIDATOR,
            )
            if (m := p.fullmatch(code)) is not None
        ),
        None,
    )
    if match is None:
        return None

    def scalar(key):
        return int.from_bytes(match[key], "little", signed=True)

    def rip_target(key):
        return symbol["rva"] + match.end(key) + scalar(key)

    if "failure" in match.groupdict():
        failure = symbol["rva"] + match.start("failure")
        if (
            any(
                rip_target(key) != failure
                for key in ("country_reject", "project_reject")
            )
            or not 0 <= scalar("technology_offset") <= 65535
            or image.target_name(rip_target("research_status"))
            != "CTechnologyStatus::IsResearching const(CSpecialProjectInstance const*)"
            or (
                "can_research" in match.groupdict()
                and image.target_name(rip_target("can_research"))
                != "CSpecialProjectInstance::CanResearch const(CCountry const&, bool, CString*)"
            )
        ):
            return None

    database, null, target = (rip_target(key) for key in ("database", "null", "lookup"))
    scoped = accessors.get(target)
    if (
        image.target_name(database) != "TPdxRef<CCountry>::_pDatabase"
        or image.target_name(null) != "TPdxNullObject<CCountry>::_pInstance"
        or scoped is None
        or scoped.get("scope_type") != "CCountry"
        or scoped.get("id_argument_register") != "rsi"
        or (
            "failure" in match.groupdict()
            and scoped.get("class") != "CSpecialProjectInstance"
        )
    ):
        return None
    country, identity, country_id = (
        scalar(key) for key in ("country", "id", "country_id")
    )
    if not (
        0x1C <= country < 0x10000
        and 0x1C <= identity < 0x10000
        and 0 <= country_id < 0x10000
    ):
        return None
    if abs(country - identity) < 4:
        return None
    return {
        "class": scoped["class"],
        "validator_rva": symbol["rva"],
        "country_source_offset": country,
        "country_database_rva": database,
        "country_null_rva": null,
        "country_object_id_offset": country_id,
        "country_reference_width": 4,
        "country_generation_checked": True,
        "country_predicate_virtual_slot": 0x58,
        "source_offset": identity,
        "call_rva": symbol["rva"] + match.start("lookup") - 1,
        "call_target_rva": target,
        "lookup_rva": scoped["lookup_rva"],
        "scope_argument_register": "rdi",
        "id_argument_register": "rsi",
        "evidence": "complete_generation_checked_country_to_scoped_lookup",
    }


def _definition_join(image, body: dict, code: bytes, cls: str, adjustment: int):
    match = DEFINITION_JOIN.fullmatch(code)
    if match is None:
        return None

    def scalar(key):
        return int.from_bytes(match[key], "little", signed=True)

    def rip_global(key):
        return body["rva"] + match.end(key) + scalar(key)

    definition_null = rip_global("definition_null")
    definition = re.fullmatch(
        r"TPdxNullObject<(\w+)>::_pInstance", image.target_name(definition_null)
    )
    database, null = rip_global("database"), rip_global("null")
    if definition is None or (
        image.target_name(database)
        != f"TGameDatabase<{definition.group(1)}Database>::_pInstance"
        or image.target_name(null) != f"TPdxNullObject<{cls}>::_pInstance"
    ):
        return None
    offsets = {
        key: scalar(key)
        for key in (
            "data",
            "count",
            "definition_data",
            "definition_count",
            "definition_member",
        )
    }
    if any(not 0 <= value < 0x10000 for value in offsets.values()) or any(
        adjustment + offsets[key] > 0x10000 for key in ("data", "count")
    ):
        return None
    return {
        "data_offset": adjustment + offsets["data"],
        "count_offset": adjustment + offsets["count"],
        "entry_stride": 8,
        "id_argument_register": "rsi",
        "search_direction": "forward",
        "null_rva": null,
        "identity_kind": "loaded_definition_index_to_country_member_not_TPdxRef",
        "definition_class": definition.group(1),
        "definition_database_rva": database,
        "definition_null_rva": definition_null,
        "definition_data_offset": offsets["definition_data"],
        "definition_count_offset": offsets["definition_count"],
        "definition_entry_stride": 8,
        "definition_index_width": 4,
        "definition_index_bounds": "signed_nonnegative_and_less_than_count",
        "definition_validation_virtual_slot": 0x10,
        "definition_pointer_member_offset": offsets["definition_member"],
        "native_member_count_guard": "nonzero_not_nonnegative",
        "evidence": "complete_loaded_definition_to_country_member_join",
    }


def _tail_target(image, root: dict):
    current, adjustment, seen, chain = root, 0, set(), []
    for _ in range(4):
        if current["rva"] in seen or current["size"] > 4096:
            return None
        seen.add(current["rva"])
        code = image.read(current["rva"], current["size"])
        if len(code) != current["size"]:
            return None
        delta = 0
        if len(code) == 5 and code[0] == 0xE9:
            jump = 0
        elif len(code) == 12 and code[:3] == b"\x48\x81\xc7" and code[7] == 0xE9:
            jump = 7
            delta = struct.unpack_from("<i", code, 3)[0]
            if not 0 < delta <= 0x10000:
                return None
        else:
            return current, adjustment, chain
        adjustment += delta
        if adjustment > 0x10000:
            return None
        target = current["rva"] + jump + 5 + struct.unpack_from("<i", code, jump + 1)[0]
        chain.append(
            {"rva": current["rva"], "target_rva": target, "country_adjustment": delta}
        )
        current = image.by_address.get(target)
        if current is None or current.get("type") != "STT_FUNC":
            return None
    return None


def recover_country_scoped_accessors(image) -> dict[int, dict]:
    """Recognize complete member searches/definition joins through pure thunks.

    These IDs are country-member values, not generation-bearing global handles.
    Evidence deliberately does not claim caller-country binding or enable a
    candidate provider. Unrecognized bodies stay unsupported.
    """
    results = {}
    for root in image.symbols:
        if root["type"] != "STT_FUNC" or "AccessInstance" not in root["raw"]:
            continue
        name = re.fullmatch(
            r"(\w+)::AccessInstance\(CCountry&, unsigned int\)", image.name(root)
        )
        resolved = _tail_target(image, root) if name else None
        if resolved is None:
            continue
        body, adjustment, chain = resolved
        code = image.read(body["rva"], body["size"])
        forward, reverse = FORWARD.fullmatch(code), REVERSE.fullmatch(code)
        match = forward or reverse
        cls = name.group(1)
        join = _definition_join(image, body, code, cls, adjustment)
        if join is not None:
            fields = join
        elif match is not None:

            def scalar(key, pattern=match):
                return int.from_bytes(pattern[key], "little", signed=True)

            count, data, identity = scalar("count"), scalar("data"), scalar("id")
            if not (
                0 <= data < 0x10000 and 0 <= count < 0x10000 and 0 <= identity < 0x10000
            ):
                continue
            if max(adjustment + data, adjustment + count) > 0x10000:
                continue
            null = body["rva"] + len(code) - 1 + scalar("null")
            if image.target_name(null) != f"TPdxNullObject<{cls}>::_pInstance":
                continue
            fields = {
                "data_offset": adjustment + data,
                "count_offset": adjustment + count,
                "entry_stride": 8,
                "identity_offset": identity,
                "identity_width": 4 if forward else 2,
                "id_argument_register": "rsi",
                "search_direction": "forward" if forward else "reverse",
                "null_rva": null,
                "identity_kind": "country_member_value_not_TPdxRef",
                "evidence": "complete_country_member_array_search",
            }
        else:
            continue
        aliases, before = [], 0
        for edge in chain:
            if before == 0:
                aliases.append(edge["rva"])
            before += edge["country_adjustment"]
        if not chain or before == 0:
            aliases.append(body["rva"])
        results[root["rva"]] = {
            "class": cls,
            "lookup_rva": root["rva"],
            "member_lookup_rva": body["rva"],
            "scope_type": "CCountry",
            "country_adjustment": adjustment,
            **fields,
            "thunk_chain": chain,
            "equivalent_country_entrypoints": aliases,
            "generation_checked": False,
            "caller_country_binding": "not_recovered",
            "candidate_provider": "requires_proven_command_binding",
        }
    # A const getter can have a distinct body/address while retaining exactly
    # the known search, scope adjustment and null object. Names alone do not
    # make it an equivalent country entrypoint.
    for root in image.symbols:
        if root["type"] != "STT_FUNC" or root["size"] not in (5, 12):
            continue
        resolved = _tail_target(image, root)
        if resolved is None:
            continue
        body, adjustment, chain = resolved
        if not chain:
            continue
        code = image.read(body["rva"], body["size"])
        for recipe in results.values():
            if (
                recipe["identity_kind"] != "country_member_value_not_TPdxRef"
                or adjustment != recipe["country_adjustment"]
                or root["rva"] in recipe["equivalent_country_entrypoints"]
            ):
                continue
            known = image.by_address[recipe["member_lookup_rva"]]
            known_code = image.read(known["rva"], known["size"])
            if (
                len(code) != len(known_code)
                or len(code) != body["size"]
                or len(known_code) != known["size"]
                or len(code) < 5
                or code[:-5] + code[-1:] != known_code[:-5] + known_code[-1:]
                or body["rva"]
                + len(code)
                - 1
                + struct.unpack_from("<i", code, len(code) - 5)[0]
                != recipe["null_rva"]
            ):
                continue
            recipe["equivalent_country_entrypoints"].append(root["rva"])
            recipe.setdefault("equivalent_entrypoint_evidence", []).append(
                {
                    "rva": root["rva"],
                    "member_lookup_rva": body["rva"],
                    "country_adjustment": adjustment,
                    "thunk_chain": chain,
                    "evidence": "complete_member_search_equivalent_except_relocated_same_null",
                }
            )
    return results


def scoped_id_bindings(catalog: dict) -> list[dict]:
    """Emit only complete, command-bound Linux recipes for the shared probe."""
    if catalog.get("platform") != "linux-x86_64":
        return []
    recipes = {
        r["lookup_rva"]: r
        for r in catalog.get("country_scoped_accessors", [])
        if type(r.get("lookup_rva")) is int
    }
    countries = [
        d for d in catalog.get("object_databases", []) if d["class"] == "CCountry"
    ]
    if len(countries) != 1:
        return []
    country_db = countries[0]
    if any(
        type(country_db.get(k)) is not int
        for k in ("database_rva", "null_rva", "id_offset")
    ):
        return []
    results = []
    for command in catalog["commands"]:
        fields = command.get("population_fields", command["fields"])
        for field in fields:
            notes = field.get("scoped_reference_evidence", [])
            if (
                len(notes) != 1
                or field.get("kind") != "u32"
                or field.get("confidence") != "direct_dataflow"
            ):
                continue
            note = notes[0]
            proof = note.get("country_reference", {})
            recipe = recipes.get(note.get("lookup_rva"))
            if recipe is None or not (
                note.get("caller_country_binding")
                == "generation_checked_command_country_reference"
                and proof.get("evidence")
                == "complete_generation_checked_country_to_scoped_lookup"
                and proof.get("country_generation_checked") is True
                and proof.get("country_reference_width") == 4
                and proof.get("validator_rva") == command.get("is_valid")
                and proof.get("source_offset") == field.get("linux_off")
                and proof.get("class") == note.get("class") == recipe.get("class")
                and proof.get("lookup_rva") == recipe["lookup_rva"]
                and proof.get("call_rva") == note.get("evidence_rva")
                and proof.get("call_target_rva") == note.get("call_target_rva")
                and proof.get("call_target_rva")
                in recipe.get("equivalent_country_entrypoints", [])
                and proof.get("country_database_rva") == country_db["database_rva"]
                and proof.get("country_null_rva") == country_db["null_rva"]
                and proof.get("country_object_id_offset") == country_db["id_offset"]
            ):
                continue
            country_fields = [
                f
                for f in fields
                if f.get("kind") == "ref"
                and f.get("ref") == "CCountry"
                and f.get("linux_off") == proof.get("country_source_offset")
            ]
            if (
                len(country_fields) != 1
                or recipe.get("entry_stride") != 8
                or recipe.get("scope_type") != "CCountry"
                or recipe.get("search_direction") not in ("forward", "reverse")
                or type(command.get("size")) is not int
                or any(
                    type(v) is not int or not 0x1C <= v <= command["size"] - 4
                    for v in (
                        field.get("linux_off"),
                        proof.get("country_source_offset"),
                    )
                )
                or field["linux_off"] == proof["country_source_offset"]
            ):
                continue
            identity = recipe.get("identity_kind")
            if identity == "country_member_value_not_TPdxRef" and recipe.get(
                "identity_width"
            ) in (2, 4):
                kind = "member_u16" if recipe["identity_width"] == 2 else "member_u32"
                member_offset = recipe.get("identity_offset")
            elif (
                identity == "loaded_definition_index_to_country_member_not_TPdxRef"
                and recipe.get("definition_entry_stride") == 8
            ):
                kind, member_offset = (
                    "definition_index",
                    recipe.get("definition_pointer_member_offset"),
                )
            else:
                continue
            offsets = [
                recipe.get("data_offset"),
                recipe.get("count_offset"),
                member_offset,
            ]
            rvas = [proof.get("call_target_rva"), recipe.get("null_rva")]
            if kind == "definition_index":
                offsets += [
                    recipe.get("definition_data_offset"),
                    recipe.get("definition_count_offset"),
                ]
                rvas += [
                    recipe.get("definition_database_rva"),
                    recipe.get("definition_null_rva"),
                ]
            if any(type(v) is not int or not 0 <= v <= 65535 for v in offsets) or any(
                type(v) is not int or not 0 < v < 0x10000000 for v in rvas
            ):
                continue
            results.append(
                {
                    "command_class": command["class"],
                    "field_offset": field["linux_off"],
                    "country_field_offset": proof["country_source_offset"],
                    "class": recipe["class"],
                    "kind": kind,
                    "lookup_rva": proof["call_target_rva"],
                    "null_rva": recipe["null_rva"],
                    "data_offset": recipe["data_offset"],
                    "count_offset": recipe["count_offset"],
                    "member_offset": member_offset,
                    "reverse": recipe["search_direction"] == "reverse",
                    **{
                        key: recipe.get(key, 0)
                        for key in (
                            "definition_database_rva",
                            "definition_null_rva",
                            "definition_data_offset",
                            "definition_count_offset",
                        )
                    },
                }
            )
    counts = Counter((r["command_class"], r["field_offset"]) for r in results)
    return [r for r in results if counts[r["command_class"], r["field_offset"]] == 1]
