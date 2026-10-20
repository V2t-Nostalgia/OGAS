"""Recover the shared native coordinate value, never a per-Command layout.

Save-space units are distinct from renderer-space scaling. No native functions
are invoked. An exact typed serializer, conversion constants and factory vptr
are required before attaching a value region to any command.
"""

from __future__ import annotations

import math
import struct

from capstone.x86 import X86_OP_IMM, X86_OP_MEM, X86_OP_REG


def _constant(image, instruction):
    if len(instruction.operands) != 2:
        return None
    operand = instruction.operands[1]
    if operand.type != X86_OP_MEM or instruction.reg_name(operand.mem.base) != "rip":
        return None
    address = instruction.address + instruction.size + operand.mem.disp
    raw = image.read(address, 4)
    if len(raw) != 4:
        return None
    value = struct.unpack("<f", raw)[0]
    return {"rva": address, "value": value, "bytes": raw.hex(), "instruction_rva": instruction.address}


def recover_coordinate_value(image, tokens):
    from linux_elf import extract_serializer
    from value_recovery import normal_flow

    wanted = {
        "CCelestialCoordinate::WriteMembers(CWriter&)",
        "CCelestialCoordinate::SetDisplayHeight(float)",
        "CCelestialCoordinate::GetDisplayHeight const()",
        "CCelestialCoordinate::RandomizeDisplayHeightIfSet()",
        "CCelestialCoordinate::{ctor}(CGalacticObject const*, CFixedPoint const&, CFixedPoint const&)",
        "CGalacticObject::CalcFTLPointWith const(CGalacticObject const*)",
        "CGalacticObject::CalcFTLPointWith const(CCelestialCoordinate const&)",
    }
    symbols = {}
    vtables = []
    for symbol in image.symbols:
        raw = symbol["raw"]
        if "CCelestialCoordinate" not in raw and "CalcFTLPointWith" not in raw:
            continue
        name = image.name(symbol)
        if name in wanted and symbol["type"] == "STT_FUNC":
            symbols[name] = symbol
        if name == "vtable for CCelestialCoordinate":
            vtables.append(symbol)
    required = {n for n in wanted if not n.startswith("CGalacticObject::")}
    if not required <= symbols.keys() or len(vtables) != 1:
        return {"recovered": False, "reason": "typed_coordinate_symbols_or_vtable_missing"}
    writer = symbols["CCelestialCoordinate::WriteMembers(CWriter&)"]
    fields = extract_serializer(image, writer, tokens)["fields"]
    by_name = {f.get("name"): f for f in fields}
    roles = {"x", "y", "origin", "randomized", "visual_height"}
    if set(by_name) != roles:
        return {"recovered": False, "reason": "coordinate_serializer_fields_not_exact", "fields": fields}
    for name in ("x", "y", "visual_height"):
        field = by_name[name]
        if field.get("writer") != "CWriter::Write(int, CFixedPoint)" or field.get("width") != 8:
            return {"recovered": False, "reason": "coordinate_fixed_storage_not_proven"}
    if (by_name["origin"].get("ref") != "CGalacticObject" or
            by_name["randomized"].get("kind") != "bool" or
            not by_name["randomized"].get("conditional_bool")):
        return {"recovered": False, "reason": "coordinate_reference_or_flag_not_proven"}
    height = symbols["CCelestialCoordinate::SetDisplayHeight(float)"]
    body, cfg = normal_flow(image, height)
    constants = [(i, _constant(image, i)) for i in body]
    scales = [(i, c) for i, c in constants if i.mnemonic == "movss" and c and
              math.isfinite(c["value"]) and 1 < c["value"] <= 1e9 and c["value"].is_integer()]
    if len(scales) != 1 or not cfg["complete"]:
        return {"recovered": False, "reason": "coordinate_float_scale_not_unique"}
    scale_instruction, scale = scales[0]
    scale_register = scale_instruction.reg_name(scale_instruction.operands[0].reg)
    scale_index = body.index(scale_instruction)
    stores = [i for i in body if i.mnemonic == "mov" and len(i.operands) == 2 and
              i.operands[0].type == X86_OP_MEM and i.operands[0].size == 8 and
              i.operands[0].mem.disp == by_name["visual_height"]["linux_off"] and
              i.operands[1].type == X86_OP_REG and i.reg_name(i.operands[1].reg) == "rax"]
    if (len(stores) != 1 or scale_index + 1 >= len(body) or body[scale_index + 1].mnemonic != "mulss" or
            body[scale_index + 1].reg_name(body[scale_index + 1].operands[0].reg) != scale_register or
            body[body.index(stores[0]) - 1].mnemonic != "cvttss2si"):
        return {"recovered": False, "reason": "coordinate_height_conversion_flow_unproven"}
    inverse_symbol = symbols["CCelestialCoordinate::RandomizeDisplayHeightIfSet()"]
    inverse_body, inverse_cfg = normal_flow(image, inverse_symbol)
    inverse = [c for i in inverse_body if i.mnemonic == "movss" and (c := _constant(image, i)) and
               c["bytes"] == struct.pack("<f", 1 / scale["value"]).hex()]
    converted_offsets = {i.operands[1].mem.disp for i in inverse_body if i.mnemonic == "cvtsi2ss" and
                         len(i.operands) == 2 and i.operands[1].type == X86_OP_MEM and i.operands[1].size == 8}
    if (not inverse_cfg["complete"] or len(inverse) != 1 or
            not {by_name[n]["linux_off"] for n in ("x", "y")} <= converted_offsets):
        return {"recovered": False, "reason": "coordinate_XY_reciprocal_conversion_not_proven"}
    getter = symbols["CCelestialCoordinate::GetDisplayHeight const()"]
    get_body, get_cfg = normal_flow(image, getter)
    if (not get_cfg["complete"] or len(get_body) != 2 or get_body[0].mnemonic != "mov" or
            get_body[0].reg_name(get_body[0].operands[0].reg) != "rax" or get_body[0].operands[1].size != 8 or
            get_body[0].operands[1].type != X86_OP_MEM or
            get_body[0].operands[1].mem.disp != by_name["visual_height"]["linux_off"] or
            get_body[-1].mnemonic != "ret"):
        return {"recovered": False, "reason": "display_height_member_not_proven"}
    ctor = symbols["CCelestialCoordinate::{ctor}(CGalacticObject const*, CFixedPoint const&, CFixedPoint const&)"]
    ctor_body, ctor_cfg = normal_flow(image, ctor)
    # A no-call constructor copies X/Y, clears display height and both flag
    # bytes, and stores either system->id or the galaxy sentinel as origin.
    writes = [i for i in ctor_body if i.mnemonic.startswith("mov") and len(i.operands) == 2 and
              i.operands[0].type == X86_OP_MEM and i.reg_name(i.operands[0].mem.base) == "rdi"]
    clear = {(i.operands[0].mem.disp, i.operands[0].size) for i in writes if
             i.operands[1].type == X86_OP_IMM and i.operands[1].imm == 0}
    xy = {(i.operands[0].mem.disp, i.operands[0].size) for i in writes if i.operands[1].type == X86_OP_REG}
    flag = by_name["randomized"]["linux_off"]
    end = max(i.operands[0].mem.disp + i.operands[0].size for i in writes)
    size = (end + 7) // 8 * 8
    allowed_writes = {(0, 8), (by_name["x"]["linux_off"], 16),
                      (by_name["x"]["linux_off"], 8), (by_name["y"]["linux_off"], 8),
                      (by_name["visual_height"]["linux_off"], 8), (by_name["origin"]["linux_off"], 4), (flag - 1, 2)}
    if (not ctor_cfg["complete"] or any(i.mnemonic == "call" for i in ctor_body) or
            ctor_cfg["tails"] or any((i.operands[0].mem.disp, i.operands[0].size) not in allowed_writes for i in writes) or
            (by_name["visual_height"]["linux_off"], 8) not in clear or (flag - 1, 2) not in clear or
            any((by_name[n]["linux_off"], 8) not in xy for n in ("x", "y")) or
            any(i.operands[0].mem.index for i in writes) or size > 128):
        return {"recovered": False, "reason": "coordinate_nonowning_constructor_not_proven"}
    vtable = vtables[0]["rva"] + 16
    first = ctor_body[0]
    if (first.mnemonic != "lea" or first.operands[1].type != X86_OP_MEM or
            first.reg_name(first.operands[1].mem.base) != "rip" or
            first.address + first.size + first.operands[1].mem.disp != vtable):
        return {"recovered": False, "reason": "coordinate_constructor_vtable_mismatch"}
    table = image.read(vtable, min(vtables[0]["size"] - 16, 32 * 8))
    if writer["rva"] not in struct.unpack("<" + "Q" * (len(table) // 8), table):
        return {"recovered": False, "reason": "coordinate_vtable_writer_mismatch"}
    return {"recovered": True, "class": "CCelestialCoordinate", "size": size, "alignment": 8,
            "vtable_rva": vtable, "serializer_rva": writer["rva"], "fields": fields,
            "fixed_scale": int(scale["value"]), "scale_evidence": scale, "inverse_evidence": inverse[0],
            "height_setter_rva": height["rva"], "constructor_rva": ctor["rva"],
            "zero_height_and_no_randomize": True, "initialized_extent": end,
            "ftl_providers": [{"name": n, "rva": s["rva"], "abi": "SysV_sret_out_this_toward",
                               "existing_runtime_provider": True} for n, s in sorted(symbols.items()) if n.startswith("CGalacticObject::")],
            "limits": ["save_space_not_renderer_space", "no_owning_coordinate_members",
                       "local_2D_choice_uses_native_ctor_zero_height_no_randomize",
                       "cross_system_targets_require_native_CalcFTLPointWith_not_inferred_map_endpoints"]}


def bind_coordinate_regions(command, record, model):
    if not model.get("recovered"):
        return []
    fields = command.get("population_fields", command["fields"])
    local = {f["evidence_rva"]: f for f in model["fields"]}
    groups = {}
    for field in fields:
        nested = local.get(field.get("evidence_rva"))
        if nested and field.get("linux_off") is not None:
            prefix = field["name"].rpartition(".")[0]
            base = field["linux_off"] - nested["linux_off"]
            groups.setdefault((prefix, base), {})[nested["name"]] = field
    regions = []
    for (prefix, base), members in sorted(groups.items()):
        if set(members) != {f["name"] for f in model["fields"]} or base < 28 or base + model["size"] > command["size"]:
            continue
        writes = record.get("writes", [])
        vptr = [w for w in writes if w["offset"] == base and w["width"] == 8 and
                w.get("value") == ("rva", model["vtable_rva"])]
        # Serialized JSON stores tuples as lists; exact numeric identity remains.
        vptr += [w for w in writes if w["offset"] == base and w["width"] == 8 and
                 w.get("value") == ["rva", model["vtable_rva"]]]
        clear = {(w["offset"], w["width"]) for w in writes if w.get("value") in (("constant", 0), ["constant", 0])}
        height = members["visual_height"]["linux_off"]
        flag = members["randomized"]["linux_off"]
        if not vptr or (height, 8) not in clear or (flag - 1, 2) not in clear:
            continue
        roles = {role: field["name"] for role, field in members.items()}
        for role, field in members.items():
            field["native_coordinate_member"] = {"type": model["class"], "region_offset": base,
                "role": role, "fixed_scale": model["fixed_scale"], "serializer_rva": model["serializer_rva"],
                "constructor_rva": model["constructor_rva"], "factory_vptr_rva": vptr[-1]["evidence_rva"]}
        regions.append({"kind": "nonowning_native_coordinate", "type": model["class"],
            "offset": base, "size": model["size"], "alignment": model["alignment"],
            "layout_verified": True, "members": roles, "fixed_scale": model["fixed_scale"],
            "vtable_rva": model["vtable_rva"], "factory_vptr_rva": vptr[-1]["evidence_rva"],
            "initialized_extent": model["initialized_extent"],
            "padding_intervals": [[base + model["initialized_extent"], base + model["size"]]],
            "ctor_defaults": {"visual_height": 0, "randomized": False},
            "semantic_frame": "origin_selects_system_local_or_galaxy_transit"})
    if regions:
        command["native_value_regions"] = regions
    return regions
