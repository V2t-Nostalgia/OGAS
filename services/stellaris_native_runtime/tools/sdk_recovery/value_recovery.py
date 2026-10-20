"""Shared native value recovery, with normal-flow and ownership evidence.

No Command names, process access, lifecycle stubs or guessed defaults. Changes
are usable by the existing metadata emitter and NativeCommandBuilder.
"""

from __future__ import annotations

import hashlib
import re
from collections import Counter

from capstone.x86 import X86_OP_IMM, X86_OP_MEM, X86_OP_REG

from linux_elf import register


def refine_named_enum_fields(image, catalog, tokens):
    """Re-index unresolved token writers, composing proven nested offsets."""
    import bisect
    from linux_elf import extract_serializer
    from recovery_plans import recover_enum_values
    symbols = {s["rva"]: s for s in image.symbols if s["type"] == "STT_FUNC" and s["size"]}
    starts, cache, changed = sorted(symbols), {}, []
    for command in catalog["commands"]:
        fields = command.get("population_fields", command["fields"])
        for field in fields:
            if field.get("linux_off") is not None or field.get("writer") != "CWriter::WriteTokenValue(int, int)":
                continue
            pc = field.get("evidence_rva", 0)
            at = bisect.bisect_right(starts, pc) - 1
            if at < 0:
                continue
            symbol = symbols[starts[at]]
            if not symbol["rva"] <= pc < symbol["rva"] + symbol["size"] or "::Write" not in image.name(symbol):
                continue
            if symbol["rva"] not in cache:
                cache[symbol["rva"]] = extract_serializer(image, symbol, tokens)["fields"]
            recovered = cache[symbol["rva"]]
            rows = [f for f in recovered if f.get("evidence_rva") == pc and f.get("enum_type") and
                    f.get("confidence") == "direct_dataflow"]
            if len(rows) != 1:
                continue
            candidate = rows[0]
            if symbol["rva"] == command.get("serializer"):
                base = 0
            else:
                prefix = field.get("name", "").rpartition(".")[0]
                offsets = {f["linux_off"] - local["linux_off"] for f in fields
                    for local in recovered if f.get("linux_off") is not None and local.get("linux_off") is not None
                    and f.get("evidence_rva") == local.get("evidence_rva") and
                    f.get("name", "").rpartition(".")[0] == prefix}
                if len(offsets) != 1:
                    continue
                base = offsets.pop()
            field.update(kind=candidate["kind"], linux_off=base + candidate["linux_off"],
                confidence="direct_dataflow", enum_type=candidate["enum_type"],
                enum_serializer_rva=candidate["enum_serializer_rva"],
                scalar_candidates=recover_enum_values(image, candidate["enum_serializer_rva"]),
                value_recovery={"kind": "native_byvalue_enum_parameter_and_serializer", "serializer_rva": symbol["rva"],
                    "writer_rva": pc, "converter_rva": candidate["enum_serializer_rva"], "nested_base_offset": base})
            changed.append({"class": command["class"], "field": field["name"], "enum_type": field["enum_type"],
                            "offset": field["linux_off"], "kind": field["kind"]})
    return changed


def recover_save_collection_bindings(image, catalog, tokens):
    """Relate a native ref-database base to its sole persistent save payload.

    This selects a save collection; it never infers object memory offsets from
    spelling. Ambiguous manager serializers remain unresolved.
    """
    from linux_elf import extract_serializer
    from recovery_plans import factory_evidence
    serializers, constructors = {}, {}
    for sym in image.symbols:
        if sym["type"] != "STT_FUNC":
            continue
        if "CSerializer" in sym["raw"] and "WriteMembersE" in sym["raw"]:
            owner = image.name(sym).split("::CSerializer::", 1)
            if len(owner) == 2:
                serializers[owner[0]] = sym
        if re.search(r"C[12]E", sym["raw"]):
            constructors.setdefault(image.name(sym).split("::{", 1)[0], sym)
    types = {d["class"] for d in catalog.get("object_databases", [])}
    result = []
    for owner in sorted(serializers.keys() & constructors.keys()):
        ctor = constructors[owner]
        rec = factory_evidence(image, ctor, root_this=True)
        bases = []
        for call in rec["native_calls"]:
            match = re.fullmatch(r"TPdxRefDatabase<(C\w+), .+>::\{(?:base )?ctor\}\(unsigned int\)", call["callee"])
            if match and match[1] in types and call["offset"] == 0:
                bases.append((match[1], call))
        if len(bases) != 1:
            continue
        serializer = extract_serializer(image, serializers[owner], tokens)
        payloads = [f for f in serializer["fields"] if f.get("kind") == "persistent" and
                    f.get("name") and f.get("confidence") == "direct_dataflow"]
        if len(payloads) == 1:
            result.append({"native_type": bases[0][0], "collection_key": payloads[0]["name"],
                "manager_type": owner, "manager_ctor_rva": ctor["rva"],
                "base_ctor_rva": bases[0][1]["rva"], "base_call_rva": bases[0][1]["evidence_rva"],
                "serializer_rva": serializers[owner]["rva"], "field_rva": payloads[0]["evidence_rva"],
                "token": payloads[0]["token"], "evidence": "unique_typed_native_ref_database_base_and_persistent_save_payload"})
    return result


def copy_parameter_bindings(image, symbol, sizes):
    """Recover by-reference native value copies into this+offset, not raw stores."""
    import itanium_demangler
    from recovery_plans import VOLATILE
    try:
        ast = itanium_demangler.parse(symbol["raw"])
        if not any(getattr(n, "kind", None) == "ctor" and n.value == "complete"
                   for n in ast.name.value):
            return []
        params = [str(t) for t in ast.arg_tys]
    except (AttributeError, ValueError, IndexError, TypeError, NotImplementedError):
        return []
    if len(params) > 5 or any(not (p.endswith(("&", "*")) or
            re.fullmatch(r"TPdxRef<\w+>|bool|int|unsigned int", p)) for p in params):
        return []
    regs = {"rdi": ("this", 0)} | {r: ("arg", n) for n, r in enumerate(
        ("rsi", "rdx", "rcx", "r8", "r9")[:len(params)])}
    rows = []
    for i in image.instructions(symbol, 16384):
        ops = i.operands
        if i.mnemonic in {"call", "jmp"}:
            name = image.target_name(ops[0].imm) if ops and ops[0].type == X86_OP_IMM else ""
            dst, src = regs.get("rdi"), regs.get("rsi")
            for typ, width in sizes.items():
                if (dst and dst[0] == "this" and src and src[0] == "arg" and
                        params[src[1]] == typ + " const&" and name in {
                            typ + "::{ctor}(" + typ + " const&)",
                            typ + "::{base ctor}(" + typ + " const&)",
                            typ + "::operator=(" + typ + " const&)"}):
                    rows.append({"offset": dst[1], "width": width,
                        "parameter_index": src[1], "parameter_type": params[src[1]],
                        "constructor_rva": symbol["rva"], "constructor_symbol": symbol["raw"],
                        "evidence_rva": i.address, "assignment_rva": ops[0].imm,
                        "dereferenced": True, "evidence": "typed_native_value_copy_from_constructor_parameter"})
            for r in VOLATILE:
                regs.pop(r, None)
            if i.mnemonic == "jmp":
                regs.clear()
            continue
        if i.mnemonic.startswith("j") or i.mnemonic.startswith("ret"):
            regs.clear()
            continue
        if not ops or ops[0].type != X86_OP_REG or i.mnemonic in {"cmp", "test", "push"}:
            continue
        dst = register(i.reg_name(ops[0].reg))
        value = None
        if i.mnemonic == "mov" and len(ops) == 2 and ops[1].type == X86_OP_REG:
            value = regs.get(register(i.reg_name(ops[1].reg)))
        elif i.mnemonic == "lea" and len(ops) == 2 and ops[1].type == X86_OP_MEM and not ops[1].mem.index:
            base = regs.get(register(i.reg_name(ops[1].mem.base)))
            if base and base[0] == "this":
                value = ("this", base[1] + ops[1].mem.disp)
        elif i.mnemonic == "add" and len(ops) == 2 and ops[1].type == X86_OP_IMM:
            base = regs.get(dst)
            if base and base[0] == "this":
                value = ("this", base[1] + ops[1].imm)
        regs.pop(dst, None)
        if value:
            regs[dst] = value
    return rows


def normal_flow(image, symbol, *, budget=4096):
    """Instruction-boundary checked CFG; exception landing pads are not entries."""
    ins = image.instructions(symbol, 65536)
    if not ins or not 0 < symbol.get("size", 0) <= 65536:
        return [], {"complete": False, "reason": "function_size_or_decode_budget"}
    by_pc = {i.address: i for i in ins}
    seen, todo, tails, returns = set(), [symbol["rva"]], [], []
    complete = True
    while todo and len(seen) < budget:
        pc = todo.pop()
        if pc in seen:
            continue
        i = by_pc.get(pc)
        if i is None:
            complete = False
            continue
        seen.add(pc)
        if i.mnemonic.startswith("ret"):
            returns.append(pc)
        elif i.mnemonic.startswith("j"):
            if not i.operands or i.operands[0].type != X86_OP_IMM:
                complete = False
                continue
            target = i.operands[0].imm
            if target not in by_pc:
                if i.mnemonic == "jmp" and image.target_name(target):
                    tails.append({"pc": pc, "target": target, "name": image.target_name(target)})
                else:
                    complete = False
            else:
                todo.append(target)
            if i.mnemonic != "jmp":
                todo.append(pc + i.size)
        elif i.mnemonic in {"ud2", "int3", "hlt"}:
            complete = False
        else:
            todo.append(pc + i.size)
    complete = complete and not todo
    return [i for i in ins if i.address in seen], {
        "complete": complete, "entry_rva": symbol["rva"], "return_rvas": returns,
        "tails": tails, "unreachable_instructions": len(ins) - len(seen),
        "unreachable_rvas": [i.address for i in ins if i.address not in seen],
    }


class NormalImage:
    def __init__(self, image):
        self.image = image

    def __getattr__(self, key):
        return getattr(self.image, key)

    def instructions(self, symbol, limit=65536):
        return normal_flow(self.image, symbol)[0]


def _inline_string(field, record, size, assignment):
    """Recognize the established CString SBO initializer, not a string token."""
    off = field.get("linux_off")
    if (field.get("kind") != "string" or field.get("indirect") or
            field.get("confidence") != "direct_dataflow" or off is None or
            off < 28 or off + 48 > size or not assignment):
        return None
    writes = record.get("writes", [])
    # CString's existing 48-byte ABI: length/control, allocator, data, length,
    # inline capacity/data. All five stores must be present at the same base.
    required = [(0, 4, ["constant", 0]), (8, 8, ["constant", 0]),
                (16, 8, ["object", off + 32]), (24, 8, ["constant", 0]),
                (32, 1, ["constant", 0])]
    proof = []
    for delta, width, value in required:
        matching = [w for w in writes if w["offset"] == off + delta and
                    w["width"] == width and list(w.get("value") or ()) == value]
        if not matching:
            return None
        # A conflicting later write would invalidate the empty SBO state.
        last = [w for w in writes if w["offset"] == off + delta][-1]
        if last not in matching:
            return None
        proof.append(last["evidence_rva"])
    return {"kind": "native_inline_CString_SBO_initializer", "store_rvas": proof,
            "assignment_rva": assignment, "size": 48, "source": "existing_CString_ABI_and_factory_stores"}


def paired_lifecycle_evidence(catalog, reports):
    """Reuse exact-binary, matched native factory/destruction observations.

    Legality, candidates and world identity are deliberately not transferred.
    A same class name or IsValid=true alone is insufficient.
    """
    observations = {}
    for path, report in reports:
        if report.get("build_id") != catalog["build_id"] or report.get("aborted"):
            continue
        canonical_hash = hashlib.sha256(__import__("json").dumps(report, sort_keys=True).encode()).hexdigest()
        for row in report.get("commands", []):
            for a in row.get("attempts", []):
                if (a.get("build_id") != catalog["build_id"] or not a.get("structure_checked") or
                        not a.get("constructed_from_generated_metadata") or a.get("destroyed") is not True or
                        a.get("submitted") is not False or a.get("status") not in {
                            "native_valid", "native_invalid", "constructed_only", "not_tested", "missing_parameters"}):
                    continue
                key = (a.get("class_name"), a.get("factory_rva"), a.get("vtable_rva"), a.get("object_size"))
                observations.setdefault(key, []).append({"source": str(path),
                    "source_canonical_json_sha256": canonical_hash,
                    "status": a["status"], "constructed": True, "destroyed": True,
                    "world_identity": a.get("world_identity"), "game_date": a.get("game_date_before"),
                    "parameters_populated": a.get("parameters_populated") is True,
                    "historical_native_is_valid": a.get("native_is_valid"),
                    "legality_reused": False, "bindings_reused": False,
                    "typed_text_inputs_observed": [b["field"] for b in a.get("bindings", [])
                        if a.get("parameters_populated") and b.get("storage_kind") == "native_text_value" and
                        type(b.get("text_value")) is str and b["text_value"]]})
    return observations


def refine_catalog(image, catalog, *, lifecycle_reports=(), tokens=None):
    """Enrich a new catalog in place; never touch an existing output artifact."""
    from recovery_plans import factory_evidence, constructor_writes
    from emit_ogas import population_layout_complete, field_layout

    if (catalog["build_id"] != image.build_id or
            catalog["sha256"] != hashlib.sha256(image.data).hexdigest() or
            catalog["platform"] != "linux-x86_64"):
        raise ValueError("Native value evidence requires the exact Linux ELF")
    enum_changes = refine_named_enum_fields(image, catalog, tokens or {})
    from coordinate_values import recover_coordinate_value, bind_coordinate_regions
    coordinate = recover_coordinate_value(image, tokens or {})
    catalog["native_coordinate_value"] = coordinate
    names = {image.name(s): s for s in image.symbols if s["type"] == "STT_FUNC" and
             ("CString" in s["raw"] or "CPersistentName" in s["raw"] or "InsertAtEmplace" in s["raw"])}
    assignment = names.get("CString::operator=(char const*)", {}).get("rva", 0)
    normal_image = NormalImage(image)
    recipes = {r["class"]: r for r in catalog.get("native_text_values", [])}
    # These native operations are already consumed by Builder::SetText. We only
    # accept their default constructors at a recovered embedded field location.
    local_ctors = {r["class"] + "::{ctor}()": r for r in recipes.values()}
    local_ctors |= {r["class"] + "::{base ctor}()": r for r in recipes.values()}
    owners = {c["class"] for c in catalog["commands"]}
    bindings = {}
    sizes = {typ: r["size"] for typ, r in recipes.items()} | {"CString": 48}
    for sym in image.symbols:
        if sym["type"] == "STT_FUNC" and "C1E" in sym["raw"] and image.name(sym).split("::{", 1)[0] in owners:
            for b in copy_parameter_bindings(image, sym, sizes):
                bindings.setdefault(image.name(sym).split("::{", 1)[0], []).append(b)
    changes, array_changes, coordinate_changes = [], [], []
    observed = paired_lifecycle_evidence(catalog, lifecycle_reports)
    for command in catalog["commands"]:
        fields = command.get("population_fields", command["fields"])
        old_layout = population_layout_complete(command, catalog["platform"])
        symbol = image.by_address.get(command.get("factory"))
        if not symbol:
            continue
        reachable, cfg = normal_flow(image, symbol)
        rec = factory_evidence(normal_image, symbol)
        rec["writes"] = constructor_writes(normal_image, rec) + rec["writes"]
        from array_recovery import recover_reference_arrays
        array_changes += recover_reference_arrays(image, command, rec, names)
        # Separate known native object regions from semantic serializer-member
        # binding. Unnamed regions are never emitted as writable SDK fields.
        unbound = []
        for attempt in command.get("array_recovery_attempts",[]):
            expected = re.fullmatch(r"TPdxRef<(\w+)>",attempt["serialized_element_type"])
            matching = [a for a in attempt["factory_arrays"] if expected and
                        a["type"]==f"CPdxArray<TPdxRef<{expected[1]}>, int>"]
            if len(matching)==1 and attempt["status"]!="reference_array_recovered":
                a = matching[0]
                insert = names.get(f"TPdxRef<{expected[1]}>& {a['type']}::InsertAtEmplace<>(int)")
                if insert:
                    unbound.append({"field":attempt["field"],"offset":a["offset"],"width":24,
                        "reference_type":expected[1],"native_type":a["type"],"assignment_rva":insert["rva"],
                        "initializer_rva":a["initializer_rva"],"binding_proven":False})
        if unbound:
            shadow = dict(command)
            shadow["population_fields"] = [f for f in fields if field_layout(f,catalog["platform"])[3]] + [
                {"name":f"@unbound_native_region_{a['offset']}","kind":"reference_array","linux_off":a["offset"],
                 "confidence":"direct_dataflow","native_size":24,"assignment_rva":a["assignment_rva"]} for a in unbound]
            command["native_object_region_layout"] = {"complete":population_layout_complete(shadow,catalog["platform"]),
                "unbound_members":unbound,"emitted_as_writable_fields":False,
                "meaning":"native_object_regions_known_but_serializer_projection_binding_pending"}
        command["factory_normal_flow"] = cfg | {"native_calls": rec["native_calls"],
            "other_calls": rec["other_calls"], "external_writes": rec["external_writes"]}
        changed_fields = []
        for f in fields:
            copied = [b for b in bindings.get(command["class"], []) if b["offset"] == f.get("linux_off")]
            if copied:
                f["native_copy_parameter_evidence"] = copied
                known = f.setdefault("constructor_parameter_evidence", [])
                known += [b for b in copied if b not in known]
            inline = _inline_string(f, rec, command["size"], assignment)
            if inline and f.get("native_type") != "CString":
                f.update(native_type="CString", assignment_rva=assignment, native_size=48,
                         value_recovery=inline)
                changed_fields.append({"field": f["name"], "capability": "inline_CString"})
            # CWriter's typed by-value CFixedPoint argument has a recovered
            # eight-byte load. Units are NOT inferred; candidates require a
            # separate typed producer/conversion binding.
            if (f.get("writer") == "CWriter::Write(int, CFixedPoint)" and
                    f.get("kind") == "other" and f.get("width") == 8 and
                    f.get("confidence") == "direct_dataflow"):
                f.update(storage_kind="i64", native_type="CFixedPoint",
                         value_recovery={"kind": "native_typed_64bit_fixed_point_storage",
                             "serializer_rva": f["evidence_rva"], "units": "requires_native_conversion"})
                if coordinate.get("recovered"):
                    f["value_recovery"].update(fixed_scale=coordinate["fixed_scale"],
                        units="native_CFixedPoint_scale_proven_semantic_domain_still_required",
                        conversion_rva=coordinate["height_setter_rva"])
                changed_fields.append({"field": f["name"], "capability": "fixed_point_storage"})
        regions = bind_coordinate_regions(command, rec, coordinate)
        if regions:
            coordinate_changes.append({"class": command["class"], "regions": regions})
        # Empty payload is a fact about the exact serializer, not the absence of
        # scanner output. Only a complete RET body plus base-sized allocation.
        ser = image.by_address.get(command.get("serializer"))
        if not fields and ser and command["size"] == 32 and not command.get("serializer_subobjects"):
            body, scfg = normal_flow(image, ser)
            if scfg["complete"] and body and all(i.mnemonic in {"ret", "nop"} for i in body):
                command["empty_payload_proven"] = {"serializer_rva": ser["rva"],
                    "evidence": "complete_ret_only_serializer_and_base_sized_factory"}
        # Do not relabel an arbitrary complex factory as safe merely because a
        # default value constructor is present. Match each call to an existing
        # native value recipe, recovered field extent and registered destructor.
        calls_covered, ownership = True, []
        for call in rec["native_calls"]:
            recipe = local_ctors.get(call["callee"])
            if call["callee"] in {"CString::{ctor}(char const*)", "CString::{base ctor}(char const*)"}:
                args = call.get("arguments", [])
                src = args[1] if len(args) > 1 else None
                if src and src[0] == "rva" and image.read(src[1], 1) == b"\0":
                    recipe = {"class": "CString", "size": 48, "destroy_rva": None,
                              "move_assign_rva": assignment}
            if recipe is None:
                callee = image.by_address.get(call["rva"])
                typename = call["callee"].split("::{", 1)[0]
                primitive = [f for f in fields if f.get("native_type") == typename and
                             f.get("linux_off") == call["offset"] and
                             field_layout(f, catalog["platform"])[2] in (1, 4, 8)]
                if callee and len(primitive) == 1:
                    width = field_layout(primitive[0], catalog["platform"])[2]
                    pinit = factory_evidence(normal_image, callee, root_this=True)
                    _, pcfg = normal_flow(image, callee)
                    spans = pinit["writes"]
                    if (pcfg["complete"] and pinit["straight_line"] and spans and
                            not pinit["allocations"] and not pinit["native_calls"] and
                            not pinit["other_calls"] and not pinit["external_writes"] and
                            all(0 <= w["offset"] < w["offset"] + w["width"] <= width for w in spans)):
                        recipe = {"class": typename, "size": width, "destroy_rva": None,
                                  "move_assign_rva": None, "primitive_ctor_evidence": spans}
            matches = [f for f in fields if recipe and f.get("native_type") == recipe["class"] and
                       f.get("linux_off") == call["offset"] and
                       (f.get("native_size") or field_layout(f, catalog["platform"])[2]) == recipe["size"]]
            member_extent_proven = bool(recipe and 28 <= call["offset"] and
                                       call["offset"] + recipe["size"] <= command["size"])
            if not recipe or not member_extent_proven:
                calls_covered = False
            else:
                ownership.append({"offset": call["offset"], "type": recipe["class"],
                    "ctor_rva": call["rva"], "field": matches[0]["name"] if len(matches) == 1 else None,
                    "assignment_field_bound": len(matches) == 1,
                    "value_destructor_rva": recipe["destroy_rva"],
                    "native_assignment_rva": recipe["move_assign_rva"]})
        roots = [w for w in rec["writes"] if w["offset"] == 0 and w.get("value") and
                 w["value"][0] == "rva"]
        dtor = image.by_address.get(command.get("deleting_destructor"))
        dbody, dcfg = normal_flow(image, dtor) if dtor else ([], {"complete": False})
        dnames = [image.target_name(i.operands[0].imm) for i in dbody
                  if i.mnemonic in {"call", "jmp"} and i.operands and i.operands[0].type == X86_OP_IMM
                  and i.operands[0].imm not in {j.address for j in dbody}]
        # An embedded native value's generated destructor can inline its own
        # array destruction. Keep that case as a separate ownership proof rather
        # than pretending an indirect call is an unknown game callback.
        allowed_dtor = {"operator delete(void*)", "operator delete(void*, unsigned long)",
                        "CPdxCommonStringAllocator::deallocate(char*, unsigned long)"}
        dtor_covered = dcfg["complete"] and "operator delete(void*)" in dnames and all(n in allowed_dtor for n in dnames)
        indirect_dtor = any(i.mnemonic in {"call", "jmp"} and i.operands and
                            i.operands[0].type != X86_OP_IMM for i in dbody)
        # PName array virtual destruction is not yet an effect proof. Retain the
        # full factory improvement, but don't open the live lifecycle gate.
        safe = (cfg["complete"] and bool(cfg["return_rvas"]) and rec["allocations"] == 1 and
                rec.get("allocation_size") == command["size"] and not rec["other_calls"] and
                not rec["external_writes"] and calls_covered and roots and
                roots[-1]["value"][1] == command["vtable"] and dtor_covered and not indirect_dtor)
        life = {"normal_factory_effects_covered": bool(cfg["complete"] and calls_covered and
                    not rec["other_calls"] and not rec["external_writes"]),
                "embedded_values": ownership, "destructor_cfg": dcfg,
                "destructor_direct_calls": dnames, "destructor_indirect_calls": indirect_dtor,
                "destructor_effects_covered": bool(dtor_covered and not indirect_dtor),
                "evidence": "normal_CFG_existing_native_value_recipes_registered_destructor",
                "remaining": [] if safe else ["native_destructor_or_factory_effects_require_further_proof"]}
        command["lifecycle_recovery"] = life
        previous_safe = command.get("lifecycle_probe_safe") is True
        paired = observed.get((command["class"], command.get("factory"), command.get("vtable"), command.get("size")), [])
        command["historical_validation_observations"] = paired
        command["observed_text_input_fields"] = sorted({f for e in paired for f in e["typed_text_inputs_observed"]})
        # Only local native value constructors or pure factory stores qualify.
        # A historical success cannot bless an unknown game-side initializer.
        if (paired and life["normal_factory_effects_covered"] and cfg["complete"] and
                rec["allocations"] == 1 and rec.get("allocation_size") == command["size"] and
                roots and roots[-1]["value"][1] == command["vtable"]):
            life["paired_same_binary_lifecycle"] = paired
            safe = True
            life["remaining"] = []
        if safe and not previous_safe:
            command["lifecycle_probe_safe"] = True
        # Retain the original full factory record, including EH evidence. The
        # normal record is additional evidence, not a replacement of history.
        new_layout = population_layout_complete(command, catalog["platform"])
        if changed_fields or (safe and not previous_safe) or command.get("empty_payload_proven"):
            changes.append({"class": command["class"], "fields": changed_fields,
                "layout_before": old_layout, "layout_after": new_layout,
                "lifecycle_before": previous_safe, "lifecycle_after": command.get("lifecycle_probe_safe", False)})
    result = {"changes": changes, "enum_field_changes": enum_changes, "reference_array_changes": array_changes,
              "coordinate_value": coordinate, "coordinate_region_changes": coordinate_changes,
              "counts": dict(Counter(f["capability"] for c in changes for f in c["fields"])),
              "lifecycle_newly_proven": sum(not c["lifecycle_before"] and c["lifecycle_after"] for c in changes)}
    catalog["shared_value_recovery"] = result
    return result
