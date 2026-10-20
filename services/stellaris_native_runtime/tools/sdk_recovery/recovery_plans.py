"""Bounded, evidence-producing extensions to the direct ELF SDK index.

No process access. Unsupported instructions/calls invalidate tracked values;
this is deliberately not an attempt to replace Ghidra's type/dataflow analysis.
Factory writes are evidence of initialization, not semantic candidate values.
"""

from __future__ import annotations

import re
import struct
from collections import Counter, defaultdict

import itanium_demangler
from capstone.x86 import X86_OP_IMM, X86_OP_MEM, X86_OP_REG
from linux_elf import extract_serializer, register

VOLATILE = {"rax", "rcx", "rdx", "rsi", "rdi", "r8", "r9", "r10", "r11"}


def native_counter_record_identity(image, symbol: dict) -> dict | None:
    """Recognize a complete counter/store/array-insert mutator, never a getter."""
    name = re.fullmatch(r"([CS]\w+)::\w+\(([CS]\w+)&\)", image.name(symbol))
    if name is None or not 0 < symbol.get("size", 0) <= 128:
        return None
    ins = image.instructions(symbol, 128)
    if (
        len(ins) != 8
        or ins[-1].address + ins[-1].size != symbol["rva"] + symbol["size"]
        or [i.mnemonic for i in ins]
        != ["mov", "mov", "lea", "mov", "mov", "mov", "add", "jmp"]
        or any(len(i.operands) != 2 for i in ins[:-1])
    ):
        return None

    def reg(op, expected, width):
        return (
            op.type == X86_OP_REG
            and op.size == width
            and image.md.reg_name(op.reg) == expected
        )

    def member(op, base, width):
        return (
            op.type == X86_OP_MEM
            and op.size == width
            and image.md.reg_name(op.mem.base) == base
            and not op.mem.index
            and not op.mem.segment
            and 0 <= op.mem.disp <= 65535
            and op.mem.disp % width == 0
        )

    a = [i.operands for i in ins]
    if not (
        reg(a[0][0], "rdx", 8)
        and reg(a[0][1], "rsi", 8)
        and reg(a[1][0], "eax", 4)
        and member(a[1][1], "rdi", 4)
        and reg(a[2][0], "ecx", 4)
        and a[2][1].type == X86_OP_MEM
        and image.md.reg_name(a[2][1].mem.base) == "rax"
        and not a[2][1].mem.index
        and not a[2][1].mem.segment
        and a[2][1].mem.disp == 1
        and member(a[3][0], "rdi", 4)
        and a[3][0].mem.disp == a[1][1].mem.disp
        and reg(a[3][1], "ecx", 4)
        and member(a[4][0], "rsi", 4)
        and reg(a[4][1], "eax", 4)
        and reg(a[5][0], "esi", 4)
        and member(a[5][1], "rdi", 4)
        and reg(a[6][0], "rdi", 8)
        and a[6][1].type == X86_OP_IMM
        and 0 <= a[6][1].imm <= 65535
        and a[6][1].imm % 8 == 0
        and len(a[7]) == 1
        and a[7][0].type == X86_OP_IMM
    ):
        return None
    owner, record = name.groups()
    counter, identity = a[1][1].mem.disp, a[4][0].mem.disp
    count, array = a[5][1].mem.disp, a[6][1].imm
    expected = (
        f"{record}& CPdxArray<{record}, int>::InsertAtEmplace<{record} const&>"
        f"(int, {record} const&)"
    )
    if (
        image.target_name(a[7][0].imm) != expected
        or count != array + 20
        or array <= counter < array + 24
    ):
        return None
    return {
        "owner_class": owner,
        "record_class": record,
        "mutator_rva": symbol["rva"],
        "counter_offset": counter,
        "record_identity_offset": identity,
        "array_offset": array,
        "array_count_offset": count,
        "insert_rva": a[7][0].imm,
        "evidence": "complete_manager_counter_assign_then_record_array_insert",
        "research_callable": False,
        "side_effects": ["manager_counter_write", "record_id_write", "array_insert"],
    }


def native_assignment_dependency(image, symbol: dict) -> dict | None:
    """Recognize a complete member-copy/reset/rebuild assignment, not an adapter."""
    name = re.fullmatch(r"(C\w+)::operator=\(\1 const&\)", image.name(symbol))
    if name is None or not 0 < symbol.get("size", 0) <= 128:
        return None
    ins = image.instructions(symbol, 128)
    if (
        len(ins) != 15
        or ins[-1].address + ins[-1].size != symbol["rva"] + symbol["size"]
        or [i.mnemonic for i in ins]
        != ["push", "mov"] + ["mov"] * 9 + ["call", "mov", "pop", "ret"]
    ):
        return None

    def reg(op, expected, width=8):
        return (
            op.type == X86_OP_REG
            and op.size == width
            and image.md.reg_name(op.reg) == expected
        )

    if not (
        len(ins[0].operands) == 1
        and reg(ins[0].operands[0], "rbx")
        and len(ins[1].operands) == 2
        and reg(ins[1].operands[0], "rbx")
        and reg(ins[1].operands[1], "rdi")
        and len(ins[12].operands) == 2
        and reg(ins[12].operands[0], "rax")
        and reg(ins[12].operands[1], "rbx")
        and len(ins[13].operands) == 1
        and reg(ins[13].operands[0], "rbx")
        and not ins[14].operands
    ):
        return None
    members = []
    for n, width in ((2, 4), (4, 4), (6, 4), (8, 8)):
        load, store = ins[n].operands, ins[n + 1].operands
        if not (
            len(load) == len(store) == 2
            and reg(load[0], "eax" if width == 4 else "rax", width)
            and reg(store[1], "eax" if width == 4 else "rax", width)
        ):
            return None
        src, dst = load[1], store[0]
        if not (
            src.type == dst.type == X86_OP_MEM
            and src.size == dst.size == width
            and image.md.reg_name(src.mem.base) == "rsi"
            and image.md.reg_name(dst.mem.base) == "rdi"
            and not src.mem.index
            and not dst.mem.index
            and src.mem.disp == dst.mem.disp
            and 0 <= src.mem.disp <= 65535
        ):
            return None
        members.append({"offset": src.mem.disp, "width": width})
    reset, call = ins[10].operands, ins[11].operands
    if not (
        len(reset) == 2
        and reset[0].type == X86_OP_MEM
        and reset[0].size == 8
        and image.md.reg_name(reset[0].mem.base) == "rdi"
        and not reset[0].mem.index
        and 0 <= reset[0].mem.disp <= 65535
        and reset[1].type == X86_OP_IMM
        and reset[1].imm == 0
        and len(call) == 1
        and call[0].type == X86_OP_IMM
        and image.target_name(call[0].imm).endswith("::RecalcSpecialValues()")
    ):
        return None
    spans = [(m["offset"], m["offset"] + m["width"]) for m in members]
    spans.append((reset[0].mem.disp, reset[0].mem.disp + 8))
    if any(
        start < other_end and other_start < end
        for n, (start, end) in enumerate(spans)
        for other_start, other_end in spans[n + 1 :]
    ):
        return None
    return {
        "class": name[1],
        "assignment_rva": symbol["rva"],
        "rebuild_rva": call[0].imm,
        "copied_members": members,
        "reset_offset": reset[0].mem.disp,
        "evidence": "complete_copy_reset_then_native_rebuild_assignment",
    }


def factory_evidence(image, symbol: dict, *, root_this=False) -> dict:
    """Recover direct stores and embedded native ctor calls after engine new."""
    regs, writes, calls, other_calls, external_writes = (
        ({"rdi": ("object", 0)} if root_this else {}),
        [],
        [],
        [],
        [],
    )
    allocations = 0
    allocation_size = None
    branch = False
    for ins in image.instructions(symbol, 16384):
        ops = ins.operands
        if ins.mnemonic.startswith("j") and ins.mnemonic != "jmp":
            branch = True
        if ins.mnemonic in ("call", "jmp"):
            target = (
                image.target_name(ops[0].imm)
                if ops and ops[0].type == X86_OP_IMM
                else ""
            )
            args = [regs.get(r) for r in ("rdi", "rsi", "rdx")]
            for r in VOLATILE:
                regs.pop(r, None)
            if target.startswith("operator new("):
                allocations += 1
                if allocations == 1:
                    regs["rax"] = ("object", 0)
                    if args[0] and args[0][0] == "constant":
                        allocation_size = args[0][1]
            elif args[0] and args[0][0] == "object":
                calls.append(
                    {
                        "offset": args[0][1],
                        "callee": target,
                        "rva": ops[0].imm if ops[0].type == X86_OP_IMM else 0,
                        "evidence_rva": ins.address,
                        "arguments": [list(a) if a else None for a in args],
                    }
                )
            else:
                other_calls.append({"callee": target, "evidence_rva": ins.address})
            continue
        if not ops:
            continue
        if (
            ins.mnemonic in ("mov", "movabs", "movups", "movaps", "movdqu")
            and len(ops) == 2
            and ops[0].type == X86_OP_MEM
        ):
            dst, src = ops
            base = regs.get(register(ins.reg_name(dst.mem.base)))
            if base and base[0] == "object" and not dst.mem.index:
                val = (
                    ("constant", src.imm)
                    if src.type == X86_OP_IMM
                    else regs.get(register(ins.reg_name(src.reg)))
                    if src.type == X86_OP_REG
                    else None
                )
                writes.append(
                    {
                        "offset": base[1] + dst.mem.disp,
                        "width": dst.size,
                        "value": list(val) if val else None,
                        "evidence_rva": ins.address,
                    }
                )
            elif ins.reg_name(dst.mem.base) not in ("rsp", "rbp"):
                external_writes.append(ins.address)
            continue
        if ops[0].type != X86_OP_REG:
            continue
        dst = register(ins.reg_name(ops[0].reg))
        if ins.mnemonic == "pop":
            regs.pop(dst, None)
            continue
        if len(ops) < 2:
            continue
        src = ops[1]
        val = None
        if ins.mnemonic in ("mov", "movabs"):
            if src.type == X86_OP_REG:
                val = regs.get(register(ins.reg_name(src.reg)))
            elif src.type == X86_OP_IMM:
                val = ("constant", src.imm)
            elif src.type == X86_OP_MEM and ins.reg_name(src.mem.base) == "rip":
                val = ("global", ins.address + ins.size + src.mem.disp)
        elif ins.mnemonic == "lea" and src.type == X86_OP_MEM:
            base = regs.get(register(ins.reg_name(src.mem.base)))
            if ins.reg_name(src.mem.base) == "rip":
                val = ("rva", ins.address + ins.size + src.mem.disp)
            elif base and base[0] == "object" and not src.mem.index:
                val = ("object", base[1] + src.mem.disp)
        elif (
            ins.mnemonic in ("xor", "xorps", "pxor")
            and src.type == X86_OP_REG
            and src.reg == ops[0].reg
        ):
            val = ("constant", 0)
        elif ins.mnemonic == "add" and src.type == X86_OP_IMM:
            old = regs.get(dst)
            if old and old[0] in ("object", "rva"):
                val = (old[0], old[1] + src.imm)
        elif ins.mnemonic in ("cmp", "test", "push"):
            continue
        if val is None:
            regs.pop(dst, None)
        else:
            regs[dst] = val
    return {
        "rva": symbol["rva"],
        "allocations": allocations,
        "allocation_size": allocation_size,
        "straight_line": not branch,
        "writes": writes,
        "native_calls": calls,
        "other_calls": other_calls,
        "external_writes": external_writes,
    }


def recover_definitions(image, catalog, native_functions) -> list[dict]:
    """Recover definition arrays from native DB constructors and key serializers.

    Array ABI comes from the concrete CPdxArray vptr initialization, not an
    assumption that every definition database has the same base offset.
    """
    keys, nulls, databases = defaultdict(set), {}, {}
    for command in catalog["commands"]:
        for f in command.get("population_fields", []):
            if f.get("definition_type") and f.get("pointer_key_offset") is not None:
                keys[f["definition_type"]].add(f["pointer_key_offset"])
                nulls[f["definition_type"]] = f["definition_null_rva"]
    for name, symbol in catalog["globals"].items():
        match = re.fullmatch(r"(?:TGameDatabase<)?(\w+Database)>?::_pInstance", name)
        if match:
            databases[match[1]] = symbol["rva"]
    constructors = {}
    for s in image.symbols:
        if s["type"] == "STT_FUNC" and re.search(r"C[12]E", s["raw"]):
            name = image.name(s)
            for db in databases:
                if name.startswith(db + "::{"):
                    constructors[db] = s
    memo = {}

    def array_initializations(symbol, depth=0, seen=frozenset()):
        if depth > 4 or symbol["rva"] in seen:
            return []
        if symbol["rva"] in memo:
            return memo[symbol["rva"]]
        rec = factory_evidence(image, symbol, root_this=True)
        results = []
        derived_stores = [
            w["evidence_rva"]
            for w in rec["writes"]
            if w["offset"] == 0
            and w["value"]
            and w["value"][0] == "rva"
            and image.target_name(w["value"][1] - 16).endswith("Database")
        ]
        derived_boundary = max(derived_stores) if derived_stores else None
        for w in rec["writes"]:
            if not w["value"] or w["value"][0] != "rva":
                continue
            name = image.target_name(w["value"][1] - 16)
            m = re.fullmatch(r"vtable for CPdxArray<(\w+)(?: const)?\*, int>", name)
            if m and (derived_boundary is None or w["evidence_rva"] < derived_boundary):
                results.append((m[1], w["offset"], w["evidence_rva"]))
        for call in rec["native_calls"]:
            if "::{" not in call["callee"] or "ctor}" not in call["callee"]:
                continue
            target = image.by_address.get(call["rva"])
            if target:
                for cls, off, witness in array_initializations(
                    target, depth + 1, seen | {symbol["rva"]}
                ):
                    results.append((cls, call["offset"] + off, witness))
        memo[symbol["rva"]] = results
        return results

    results = []
    for db_name, ctor in constructors.items():
        for cls, array_offset, witness in array_initializations(ctor):
            if cls not in keys or len(keys[cls]) != 1:
                continue
            row = {
                "class": cls,
                "database_rva": databases[db_name],
                "null_rva": nulls[cls],
                "data_offset": array_offset + 8,
                "count_offset": array_offset + 20,
                "key_offset": next(iter(keys[cls])),
                "constructor_rva": ctor["rva"],
                "array_init_rva": witness,
                "evidence": "native_array_vptr_and_key_serializer",
            }
            if row not in results:
                results.append(row)
    for symbol in image.symbols:
        if symbol["type"] != "STT_FUNC" or "Database" not in symbol["raw"]:
            continue
        name = image.name(symbol)
        for cls, offsets in keys.items():
            db_name = cls + "Database"
            if (
                len(offsets) != 1
                or db_name not in databases
                or not name.startswith(db_name + "::")
                or not name.endswith(" const(CString const&)")
            ):
                continue
            lookup = definition_lookup_evidence(image, symbol, cls)
            if lookup:
                results.append(
                    {
                        **lookup,
                        "class": cls,
                        "database_rva": databases[db_name],
                        "null_rva": nulls[cls],
                        "key_offset": next(iter(offsets)),
                        "evidence": "native_key_lookup_bounded_pointer_array",
                    }
                )
    grouped = defaultdict(list)
    for row in results:
        grouped[(row["class"], row["database_rva"])].append(row)
    return [
        rows[0]
        for _identity, rows in sorted(grouped.items())
        if len(
            {
                (
                    r["database_rva"],
                    r["data_offset"],
                    r["count_offset"],
                    r["key_offset"],
                )
                for r in rows
            }
        )
        == 1
    ]


def definition_lookup_evidence(image, symbol, cls: str) -> dict | None:
    """Typed, const key lookups can prove a DB layout without a ctor symbol."""
    regs, arrays, counts, bounded, null_seen, returns_object = (
        {"rdi": ("db",)},
        set(),
        set(),
        set(),
        False,
        False,
    )
    instructions = image.instructions(symbol, 8192)
    for n, ins in enumerate(instructions):
        ops = ins.operands
        if ins.mnemonic == "ret":
            value = regs.get("rax")
            returns_object = returns_object or bool(value and value[0] == "object")
        if ins.mnemonic == "call":
            for r in VOLATILE:
                regs.pop(r, None)
            continue
        if len(ops) != 2:
            if ins.mnemonic == "pop" and ops and ops[0].type == X86_OP_REG:
                regs.pop(register(ins.reg_name(ops[0].reg)), None)
            continue
        a, b = ops
        if (
            ins.mnemonic == "cmp"
            and a.type == b.type == X86_OP_REG
            and n + 1 < len(instructions)
            and instructions[n + 1].mnemonic in ("je", "jne", "jb", "jae", "jl", "jge")
        ):
            for op in (a, b):
                value = regs.get(register(ins.reg_name(op.reg)))
                if value and value[0] == "count":
                    bounded.add(value[1])
            continue
        if a.type != X86_OP_REG:
            continue
        dst = register(ins.reg_name(a.reg))
        value = None
        if ins.mnemonic in ("mov", "movsxd"):
            if b.type == X86_OP_REG:
                value = regs.get(register(ins.reg_name(b.reg)))
            elif b.type == X86_OP_MEM:
                base = regs.get(register(ins.reg_name(b.mem.base)))
                if base == ("db",) and not b.mem.index:
                    if b.size == 4:
                        value = ("count", b.mem.disp)
                        counts.add(b.mem.disp)
                    elif b.size == 8:
                        value = ("array", b.mem.disp)
                elif (
                    base
                    and base[0] == "array"
                    and b.mem.index
                    and b.mem.scale == 8
                    and b.mem.disp == 0
                ):
                    value = ("object", base[1])
                    arrays.add(base[1])
                elif ins.reg_name(b.mem.base) == "rip":
                    glob = ins.address + ins.size + b.mem.disp
                    if image.target_name(glob) == f"TPdxNullObject<{cls}>::_pInstance":
                        null_seen = True
                        value = ("object", cls)
        elif ins.mnemonic in ("test", "cmp", "push") or ins.mnemonic.startswith("j"):
            continue
        if value is None:
            regs.pop(dst, None)
        else:
            regs[dst] = value
    if (
        len(arrays) == 1
        and len(counts) == 1
        and counts <= bounded
        and null_seen
        and returns_object
    ):
        return {
            "data_offset": next(iter(arrays)),
            "count_offset": next(iter(counts)),
            "lookup_rva": symbol["rva"],
        }
    return None


def token_evidence(image, rva: int) -> dict:
    data = image.read(rva, 16)
    if len(data) >= 6 and data[0] == 0xB8 and data[5] == 0xC3:
        return {"kind": "immediate", "token": struct.unpack_from("<I", data, 1)[0]}
    # Template command token storage is initialized by the game's registrator.
    # Its file image can be zero: do not invent a compile-time token value.
    if data[:3] == b"\x48\x8d\x05" and data[7:10] == b"\x8b\x00\xc3":
        glob = rva + 7 + struct.unpack_from("<i", data, 3)[0]
        return {
            "kind": "module_global",
            "global_rva": glob,
            "symbol": image.target_name(glob),
            "token": None,
        }
    return {"kind": "unresolved", "token": None}


def positive_quantity_guards(image, symbol) -> dict[int, dict]:
    """Recover >0 guards whose taken edge demonstrably returns false.

    The caller restricts this to named quantity fields, never IDs or indices.
    Satisfying this guard does not establish the remaining game conditions.
    """
    instructions = image.instructions(symbol, 16384)
    by_address = {i.address: n for n, i in enumerate(instructions)}

    def returns_false(address):
        start = by_address.get(address)
        if start is None:
            return False
        zero = False
        for i in instructions[start : start + 12]:
            if i.mnemonic == "ret":
                return zero
            if i.mnemonic == "call" or i.mnemonic.startswith("j"):
                return False
            ops = i.operands
            if (
                ops
                and ops[0].type == X86_OP_REG
                and register(i.reg_name(ops[0].reg)) == "rax"
            ):
                zero = (
                    i.mnemonic == "xor"
                    and len(ops) == 2
                    and ops[1].type == X86_OP_REG
                    and ops[0].reg == ops[1].reg
                ) or (
                    i.mnemonic == "mov"
                    and len(ops) == 2
                    and ops[1].type == X86_OP_IMM
                    and ops[1].imm == 0
                )
        return False

    regs, result = {"rdi": ("this", 0)}, {}
    for n, i in enumerate(instructions):
        ops = i.operands
        if i.mnemonic == "call":
            for r in VOLATILE:
                regs.pop(r, None)
            continue
        if len(ops) != 2:
            if i.mnemonic == "pop" and ops and ops[0].type == X86_OP_REG:
                regs.pop(register(i.reg_name(ops[0].reg)), None)
            continue
        a, b = ops
        field = None
        if i.mnemonic == "cmp" and b.type == X86_OP_IMM and b.imm == 0:
            if a.type == X86_OP_MEM and a.size == 4 and not a.mem.index:
                base = regs.get(register(i.reg_name(a.mem.base)))
                if base and base[0] == "this":
                    field = base[1] + a.mem.disp
            elif a.type == X86_OP_REG:
                value = regs.get(register(i.reg_name(a.reg)))
                if value and value[0] == "field":
                    field = value[1]
        elif i.mnemonic == "test" and a.type == b.type == X86_OP_REG and a.reg == b.reg:
            value = regs.get(register(i.reg_name(a.reg)))
            if value and value[0] == "field":
                field = value[1]
        if field is not None and n + 1 < len(instructions):
            jump = instructions[n + 1]
            if (
                jump.mnemonic == "jle"
                and jump.operands[0].type == X86_OP_IMM
                and returns_false(jump.operands[0].imm)
            ):
                result[field] = {
                    "value": 1,
                    "evidence": "smallest_positive_quantity_passing_native_guard",
                    "guard_rva": i.address,
                }
        if i.mnemonic in ("cmp", "test") or a.type != X86_OP_REG:
            continue
        dst, value = register(i.reg_name(a.reg)), None
        if i.mnemonic == "mov":
            if b.type == X86_OP_REG:
                value = regs.get(register(i.reg_name(b.reg)))
            elif b.type == X86_OP_MEM and b.size == 4 and not b.mem.index:
                base = regs.get(register(i.reg_name(b.mem.base)))
                if base and base[0] == "this":
                    value = ("field", base[1] + b.mem.disp)
        if value is None:
            regs.pop(dst, None)
        else:
            regs[dst] = value
    return result


def constructor_parameter_evidence(image, symbol, enum_types=frozenset()) -> list[dict]:
    """Trace identity stores from ABI-safe constructor parameters into fields.

    Parse the mangled parameter AST, not comma-separated C++ text. Aggregates
    with unknown register classification and floating-point arguments are
    deliberately excluded from this integer-register model.
    """
    try:
        node = itanium_demangler.parse(symbol["raw"])
        if node.name.kind != "qual_name" or not any(
            getattr(c, "kind", None) == "ctor" and c.value == "complete"
            for c in node.name.value
        ):
            # Base-object ctors can have a hidden VTT argument with virtual
            # inheritance. Their register classification is not assumed here.
            return []
        parameters = [str(t) for t in node.arg_tys]
    except (AttributeError, ValueError, IndexError, KeyError, NotImplementedError):
        return []
    if parameters == ["void"]:
        parameters = []
    if len(parameters) > 5:
        return []
    for p in parameters:
        if p in ("float", "double", "long double") or not (
            p.endswith(("&", "*"))
            or p in enum_types
            or re.fullmatch(
                r"(?:bool|(?:unsigned )?(?:char|short|int|long|long long)|TPdxRef<\w+>)",
                p,
            )
        ):
            return []
    regs = {"rdi": ("this", 0)}
    regs.update(
        {
            r: ("arg", n)
            for n, r in enumerate(("rsi", "rdx", "rcx", "r8", "r9")[: len(parameters)])
        }
    )
    results = []
    for i in image.instructions(symbol, 16384):
        ops = i.operands
        if i.mnemonic == "call":
            for reg in VOLATILE:
                regs.pop(reg, None)
            continue
        if i.mnemonic == "pop" and ops and ops[0].type == X86_OP_REG:
            regs.pop(register(i.reg_name(ops[0].reg)), None)
        if len(ops) != 2:
            continue
        a, b = ops
        if i.mnemonic == "mov" and a.type == X86_OP_MEM and b.type == X86_OP_REG:
            base = regs.get(register(i.reg_name(a.mem.base)))
            value = regs.get(register(i.reg_name(b.reg)))
            if (
                base
                and base[0] == "this"
                and value
                and value[0] in ("arg", "ref_value")
                and not a.mem.index
            ):
                results.append(
                    {
                        "offset": base[1] + a.mem.disp,
                        "width": a.size,
                        "parameter_type": parameters[value[1]],
                        "parameter_index": value[1],
                        "constructor_rva": symbol["rva"],
                        "constructor_symbol": symbol["raw"],
                        "evidence_rva": i.address,
                        "dereferenced": value[0] == "ref_value",
                    }
                )
            continue
        if a.type != X86_OP_REG or i.mnemonic in ("cmp", "test"):
            continue
        dst, value = register(i.reg_name(a.reg)), None
        if i.mnemonic in ("mov", "movzx", "movsxd"):
            if b.type == X86_OP_REG:
                value = regs.get(register(i.reg_name(b.reg)))
            elif (
                b.type == X86_OP_MEM
                and not b.mem.index
                and b.mem.disp == 0
                and b.size in (1, 4, 8)
            ):
                base = regs.get(register(i.reg_name(b.mem.base)))
                if base and base[0] == "arg" and parameters[base[1]].endswith("&"):
                    value = ("ref_value", base[1])
        elif i.mnemonic == "lea" and b.type == X86_OP_MEM and not b.mem.index:
            base = regs.get(register(i.reg_name(b.mem.base)))
            if base and base[0] == "this":
                value = ("this", base[1] + b.mem.disp)
        if value is None:
            regs.pop(dst, None)
        else:
            regs[dst] = value
    return results


def constructor_writes(image, record: dict, depth=0, seen=frozenset()) -> list[dict]:
    """Expand named this-pointer constructors, retaining each store's witness."""
    if depth >= 4 or record["rva"] in seen:
        return []
    results = []
    for call in record["native_calls"]:
        if not re.search(r"::\{(?:base )?ctor\}", call["callee"]):
            continue
        symbol = image.by_address.get(call["rva"])
        if symbol is None or symbol["size"] > 32768:
            continue
        rec = factory_evidence(image, symbol, root_this=True)
        for write in rec["writes"] + constructor_writes(
            image, rec, depth + 1, seen | {record["rva"]}
        ):
            results.append(
                {
                    **write,
                    "offset": call["offset"] + write["offset"],
                    "initializer_rva": call["rva"],
                }
            )
    return results


def recover_instance_accessors(image) -> dict[int, dict]:
    """Recover the complete generation-checking AccessInstance(country, ID) ABI."""
    result = {}
    for symbol in image.symbols:
        if symbol["type"] != "STT_FUNC" or "AccessInstance" not in symbol["raw"]:
            continue
        match = re.fullmatch(
            r"(\w+)::AccessInstance\(CCountry&, unsigned int\)", image.name(symbol)
        )
        if not match or symbol["size"] != 58:
            continue
        code = image.read(symbol["rva"], symbol["size"])
        if len(code) != 58 or not (
            code[:3] == b"\x48\x8b\x05"
            and code[7:25]
            == bytes.fromhex("48 85 c0 74 26 89 f1 81 e1 ff ff ff 00 3b 48 20 73 19")
            and code[25:45]
            == bytes.fromhex(
                "48 8b 40 18 89 c9 48 c1 e1 04 48 8b 44 08 08 48 85 c0 74 05"
            )
            and code[45:47] == b"\x39\x70"
            and code[48:53] == b"\x74\x07\x48\x8b\x05"
            and code[57] == 0xC3
        ):
            continue
        cls = match.group(1)
        db = symbol["rva"] + 7 + struct.unpack_from("<i", code, 3)[0]
        null = symbol["rva"] + 57 + struct.unpack_from("<i", code, 53)[0]
        if (
            image.target_name(db) != f"TPdxRef<{cls}>::_pDatabase"
            or image.target_name(null) != f"TPdxNullObject<{cls}>::_pInstance"
        ):
            continue
        result[symbol["rva"]] = {
            "class": cls,
            "database_rva": db,
            "null_rva": null,
            "id_offset": code[47],
            "resolver_rva": symbol["rva"],
            "id_argument_register": "rsi",
            "evidence": "complete_generation_checked_access_instance",
            "witnesses": [symbol["rva"]],
        }
    return result


def recover_databases(image) -> list[dict]:
    """Require the complete known TPdxRef resolver instruction shape.

    Reading the full ID from object+offset and then using this resolver retains
    generation validation. Never use the slot index alone as an object ID.
    """
    result = {}
    for symbol in image.symbols:
        raw = symbol["raw"]
        if symbol["type"] != "STT_FUNC" or "TPdxRef" not in raw or "ptEv" not in raw:
            continue
        name = image.name(symbol)
        match = re.fullmatch(r"TPdxRef<([\w]+)>::operator->(?: const)?\(\)", name)
        if not match:
            continue
        code = image.read(symbol["rva"], symbol["size"])
        # Clang emits this same generation-checking accessor for many databases.
        if len(code) != 58 or not (
            code[:3] == b"\x48\x8b\x05"
            and code[7:25]
            == bytes.fromhex("48 85 c0 74 26 8b 0f 89 ca 81 e2 ff ff ff 00 3b 50 20")
            and code[25:45]
            == bytes.fromhex(
                "73 17 48 8b 40 18 48 c1 e2 04 48 8b 44 10 08 48 85 c0 74 05"
            )
            and code[45:47] == b"\x39\x48"
            and code[48:53] == b"\x74\x07\x48\x8b\x05"
            and code[57] == 0xC3
        ):
            continue
        db = symbol["rva"] + 7 + struct.unpack_from("<i", code, 3)[0]
        null = symbol["rva"] + 57 + struct.unpack_from("<i", code, 53)[0]
        cls = match.group(1)
        if (
            image.target_name(db) != f"TPdxRef<{cls}>::_pDatabase"
            or image.target_name(null) != f"TPdxNullObject<{cls}>::_pInstance"
        ):
            continue
        entry = {
            "class": cls,
            "database_rva": db,
            "null_rva": null,
            "id_offset": code[47],
            "resolver_rva": symbol["rva"],
            "evidence": "complete_generation_checked_accessor",
            "witnesses": [symbol["rva"]],
        }
        if cls in result:
            previous = result[cls]
            if any(
                previous[k] != entry[k]
                for k in ("database_rva", "null_rva", "id_offset")
            ):
                raise ValueError(
                    f"Conflicting native reference accessor evidence for {cls}"
                )
            previous["witnesses"].append(symbol["rva"])
        else:
            result[cls] = entry
    for entry in recover_instance_accessors(image).values():
        cls = entry["class"]
        if cls in result:
            previous = result[cls]
            if any(
                previous[k] != entry[k]
                for k in ("database_rva", "null_rva", "id_offset")
            ):
                raise ValueError(
                    f"AccessInstance disagrees with native accessor: {cls}"
                )
            previous["witnesses"].extend(entry["witnesses"])
        else:
            result[cls] = entry
    # Inlined accessors retain the same bounds/index/generation logic, even
    # when no out-of-line operator-> symbol survived. Require two independent
    # functions to agree, and reject ambiguous offsets rather than voting.
    witnesses = defaultdict(list)
    for symbol in image.symbols:
        if symbol["type"] != "STT_FUNC" or not 40 <= symbol["size"] <= 32768:
            continue
        raw = image.read(symbol["rva"], symbol["size"])
        if b"\xff\xff\xff\x00" not in raw:
            continue
        for evidence in inline_database_witnesses(image, symbol):
            witnesses[evidence["class"]].append(evidence)
    for cls, rows in witnesses.items():
        identities = {(r["database_rva"], r["null_rva"], r["id_offset"]) for r in rows}
        if len(identities) != 1:
            continue
        if cls in result:
            old = result[cls]
            if (
                old["database_rva"],
                old["null_rva"],
                old["id_offset"],
            ) not in identities:
                raise ValueError(
                    f"Inlined accessor disagrees with native accessor: {cls}"
                )
        elif len({r["resolver_rva"] for r in rows}) >= 2:
            row = rows[0]
            result[cls] = {
                **row,
                "resolver_rva": 0,
                "evidence": "independent_inlined_generation_checks",
                "witnesses": sorted({r["resolver_rva"] for r in rows}),
            }
    return sorted(result.values(), key=lambda x: x["class"])


def inline_database_witnesses(
    image, symbol, accessors=None, *, scoped_accessors=None, scoped_findings=None
) -> list[dict]:
    from scoped_id_recovery import recover_scoped_validator_binding

    scoped_binding = (
        recover_scoped_validator_binding(image, symbol, scoped_accessors)
        if scoped_accessors
        else None
    )
    regs, bounds, findings, nulls, dbs, origins = (
        {"rdi": ("this", 0)},
        set(),
        [],
        {},
        {},
        {},
    )
    instructions = image.instructions(symbol, 32768)
    block_starts = {symbol["rva"]}
    for instruction in instructions:
        if instruction.mnemonic.startswith("j"):
            block_starts.add(instruction.address + instruction.size)
            if instruction.operands and instruction.operands[0].type == X86_OP_IMM:
                block_starts.add(instruction.operands[0].imm)
        elif instruction.mnemonic in ("call", "ret"):
            block_starts.add(instruction.address + instruction.size)
    block_start = symbol["rva"]
    for n, ins in enumerate(instructions):
        if ins.address in block_starts:
            block_start = ins.address
        ops = ins.operands
        if ins.mnemonic == "pop" and ops and ops[0].type == X86_OP_REG:
            regs.pop(register(ins.reg_name(ops[0].reg)), None)
        if ins.mnemonic == "call":
            accessor = (
                (accessors or {}).get(ops[0].imm)
                if ops and ops[0].type == X86_OP_IMM
                else None
            )
            if accessor:
                value = regs.get(accessor["id_argument_register"])
                if (
                    value
                    and value[0] == "id"
                    and value[1] >= block_start
                    and origins.get(value[1]) is not None
                ):
                    cls = accessor["class"]
                    dbs[cls], nulls[cls] = (
                        accessor["database_rva"],
                        accessor["null_rva"],
                    )
                    findings.append(
                        {
                            "class": cls,
                            "id_offset": accessor["id_offset"],
                            "evidence_rva": ins.address,
                            "source_offset": origins[value[1]],
                            "accessor_rva": accessor["resolver_rva"],
                            "evidence": "direct_call_to_complete_generation_checked_accessor",
                        }
                    )
            scoped = (
                (scoped_accessors or {}).get(ops[0].imm)
                if ops and ops[0].type == X86_OP_IMM
                else None
            )
            if scoped and scoped_findings is not None:
                value = regs.get(scoped["id_argument_register"])
                if (
                    value
                    and value[0] == "id"
                    and value[1] >= block_start
                    and origins.get(value[1]) is not None
                ):
                    binding = (
                        scoped_binding
                        if scoped_binding
                        and scoped_binding["call_rva"] == ins.address
                        and scoped_binding["source_offset"] == origins[value[1]]
                        else None
                    )
                    scoped_findings.append(
                        {
                            "class": scoped["class"],
                            "source_offset": origins[value[1]],
                            "evidence_rva": ins.address,
                            "lookup_rva": scoped["lookup_rva"],
                            "call_target_rva": ops[0].imm,
                            "identity_kind": scoped["identity_kind"],
                            "caller_country_binding": (
                                "generation_checked_command_country_reference"
                                if binding
                                else "not_recovered"
                            ),
                            **({"country_reference": binding} if binding else {}),
                        }
                    )
            for reg in VOLATILE:
                regs.pop(reg, None)
            bounds.clear()
            continue
        if len(ops) != 2:
            continue
        a, b = ops
        if ins.mnemonic == "cmp" and a.type == X86_OP_MEM and b.type == X86_OP_REG:
            obj = regs.get(register(ins.reg_name(a.mem.base)))
            val = regs.get(register(ins.reg_name(b.reg)))
            if (
                obj
                and obj[0] == "object"
                and val == ("id", obj[2])
                and a.size == 4
                and not a.mem.index
                and 0 <= a.mem.disp <= 0x1000
                and (obj[1], obj[2]) in bounds
                and n + 1 < len(instructions)
                and instructions[n + 1].mnemonic in ("je", "jne")
            ):
                findings.append(
                    {
                        "class": obj[1],
                        "id_offset": a.mem.disp,
                        "evidence_rva": ins.address,
                        "source_offset": origins.get(obj[2]),
                    }
                )
        if ins.mnemonic == "cmp":
            for lhs, rhs in ((a, b), (b, a)):
                if (
                    lhs.type == X86_OP_REG
                    and rhs.type == X86_OP_MEM
                    and rhs.mem.disp == 0x20
                    and not rhs.mem.index
                ):
                    index = regs.get(register(ins.reg_name(lhs.reg)))
                    db = regs.get(register(ins.reg_name(rhs.mem.base)))
                    if index and index[0] == "index" and db and db[0] == "db":
                        bounds.add((db[1], index[1]))
            continue
        if a.type != X86_OP_REG:
            continue
        dst = register(ins.reg_name(a.reg))
        value = None
        if ins.mnemonic in ("mov", "movsxd", "movzx"):
            if b.type == X86_OP_REG:
                value = regs.get(register(ins.reg_name(b.reg)))
                if value and value[0] == "this" and a.size != 8:
                    value = None
            elif b.type == X86_OP_MEM:
                if ins.reg_name(b.mem.base) == "rip":
                    address = ins.address + ins.size + b.mem.disp
                    name = image.target_name(address)
                    m = re.fullmatch(r"TPdxRef<(\w+)>::_pDatabase", name)
                    n = re.fullmatch(r"TPdxNullObject<(\w+)>::_pInstance", name)
                    if m:
                        value = ("db", m[1])
                        dbs[m[1]] = address
                    elif n:
                        nulls[n[1]] = address
                else:
                    base = regs.get(register(ins.reg_name(b.mem.base)))
                    idx = (
                        regs.get(register(ins.reg_name(b.mem.index)))
                        if b.mem.index
                        else None
                    )
                    if base and base[0] == "db" and b.mem.disp == 0x18 and not idx:
                        value = ("entries", base[1])
                    elif (
                        base
                        and base[0] == "entries"
                        and idx
                        and idx[0] == "slot"
                        and b.mem.scale == 1
                        and b.mem.disp == 8
                    ):
                        value = ("object", base[1], idx[1])
                    elif b.size == 4:
                        value = ("id", ins.address)
                        if base and base[0] == "this" and not b.mem.index:
                            origins[ins.address] = base[1] + b.mem.disp
        elif ins.mnemonic == "lea" and b.type == X86_OP_MEM:
            base = regs.get(register(ins.reg_name(b.mem.base)))
            if base and base[0] == "this" and not b.mem.index:
                value = ("this", base[1] + b.mem.disp)
        elif ins.mnemonic == "add" and b.type == X86_OP_IMM:
            base = regs.get(dst)
            if base and base[0] == "this":
                value = ("this", base[1] + b.imm)
        elif ins.mnemonic == "and" and b.type == X86_OP_IMM and b.imm == 0xFFFFFF:
            old = regs.get(dst)
            if old and old[0] == "id":
                value = ("index", old[1])
        elif ins.mnemonic == "shl" and b.type == X86_OP_IMM and b.imm == 4:
            old = regs.get(dst)
            if old and old[0] == "index":
                value = ("slot", old[1])
        elif ins.mnemonic in ("test", "push") or ins.mnemonic.startswith("j"):
            continue
        if value is None:
            regs.pop(dst, None)
        else:
            regs[dst] = value
    return [
        {
            **f,
            "database_rva": dbs[f["class"]],
            "null_rva": nulls[f["class"]],
            "resolver_rva": symbol["rva"],
        }
        for f in findings
        if f["class"] in nulls
    ]


def enrich_linux(image, catalog: dict, serializers: dict, factories: dict) -> None:
    """Attach proof records; flatten only native, embedded serializer identities."""
    vtables = {s["rva"] + 16: s for s in image.symbols if s["raw"].startswith("_ZTV")}
    instance_accessors = recover_instance_accessors(image)
    catalog["instance_accessors"] = list(instance_accessors.values())
    from scoped_id_recovery import recover_country_scoped_accessors

    scoped_recipes = recover_country_scoped_accessors(image)
    catalog["country_scoped_accessors"] = list(scoped_recipes.values())
    scoped_accessors = {
        entry: recipe
        for recipe in scoped_recipes.values()
        for entry in recipe["equivalent_country_entrypoints"]
    }
    assignments = [
        dependency
        for symbol in image.symbols
        if symbol["type"] == "STT_FUNC"
        and "aSERK" in symbol["raw"]
        and (dependency := native_assignment_dependency(image, symbol)) is not None
    ]
    catalog["native_assignment_dependencies"] = assignments
    record_identities = []
    record_identity_fields = {}
    for symbol in image.symbols:
        if (
            symbol["type"] != "STT_FUNC"
            or "Add" not in symbol["raw"]
            or not 0 < symbol.get("size", 0) <= 128
        ):
            continue
        identity = native_counter_record_identity(image, symbol)
        if identity is None:
            continue
        serializer = serializers.get(identity["record_class"] + "::WriteMembers", {})
        fields = [
            f
            for f in serializer.get("fields", [])
            if f.get("linux_off") == identity["record_identity_offset"]
            and f.get("kind") in ("i32", "u32")
            and f.get("width") == 4
            and not f.get("indirect")
            and f.get("evidence_rva")
        ]
        if len(fields) != 1:
            continue
        identity["serializer_field_rva"] = fields[0]["evidence_rva"]
        identity["serializer_token"] = fields[0]["token"]
        if identity not in record_identities:
            record_identities.append(identity)
            record_identity_fields.setdefault(fields[0]["evidence_rva"], []).append(
                identity
            )
    catalog["native_counter_record_identities"] = record_identities
    from record_candidates import recover_country_record_source

    record_sources = []
    for symbol in image.symbols:
        if symbol["type"] != "STT_FUNC" or symbol.get("size") != 176:
            continue
        for identity in record_identities:
            if identity["record_class"] not in symbol["raw"]:
                continue
            source = recover_country_record_source(image, symbol, identity)
            if source is not None and source not in record_sources:
                record_sources.append(source)
    catalog["native_country_record_sources"] = record_sources
    factory_records = {cls: factory_evidence(image, s) for cls, s in factories.items()}
    for rec in factory_records.values():
        rec["writes"] = constructor_writes(image, rec) + rec["writes"]
    null_types = {}
    for symbol in image.symbols:
        if symbol["type"] == "STT_OBJECT" and "TPdxNullObject" in symbol["raw"]:
            match = re.fullmatch(
                r"TPdxNullObject<(\w+)>::_pInstance", image.name(symbol)
            )
            if match:
                null_types[match[1]] = symbol["rva"]
    native_functions = {
        image.name(s): s
        for s in image.symbols
        if s["type"] == "STT_FUNC"
        and any(
            p in s["raw"]
            for p in ("EnumToToken", "InsertAtEmplace", "CStringaS", "CPersistentName")
        )
    }
    native_text_values = []
    for cls in ("CPersistentName",):
        ctor = native_functions.get(cls + "::{ctor}(char const*, bool)")
        assign = native_functions.get(cls + "::operator=(" + cls + "&&)")
        destroy = native_functions.get(cls + "::{base dtor}()")
        default_ctor = native_functions.get(cls + "::{ctor}()")
        if not all((ctor, assign, destroy, default_ctor)):
            continue
        init = factory_evidence(image, default_ctor, root_this=True)
        writes = init["writes"] + constructor_writes(image, init)
        extent = max((w["offset"] + w["width"] for w in writes), default=0)
        size = (extent + 7) // 8 * 8
        if not 8 <= size <= 4096 or init["external_writes"]:
            continue
        native_text_values.append(
            {
                "class": cls,
                "size": size,
                "construct_text_rva": ctor["rva"],
                "move_assign_rva": assign["rva"],
                "destroy_rva": destroy["rva"],
                "extent_evidence": writes,
                "evidence": "native_default_ctor_extent_text_ctor_move_assignment_and_destructor",
            }
        )
    catalog["native_text_values"] = native_text_values
    enum_types = {
        name.split("EnumToToken<", 1)[1].split(">(", 1)[0]
        for name in native_functions
        if "EnumToToken<" in name
    }
    constructor_fields = defaultdict(list)
    command_types = {c["class"] for c in catalog["commands"]} | set(factories)
    for symbol in image.symbols:
        if symbol["type"] != "STT_FUNC" or not re.search(r"C[12]E", symbol["raw"]):
            continue
        owner = image.name(symbol).split("::{", 1)[0]
        if owner in command_types:
            constructor_fields[owner].extend(
                constructor_parameter_evidence(image, symbol, enum_types)
            )
    by_factory_vtable = {}
    for cls, rec in factory_records.items():
        roots = [
            w
            for w in rec["writes"]
            if w["offset"] == 0 and w["value"] and w["value"][0] == "rva"
        ]
        if roots:
            by_factory_vtable[roots[-1]["value"][1]] = (cls, rec)
    for command in catalog["commands"]:
        # CRTP queue bases have their own abstract/base vtable. Only adopt the
        # concrete registered vtable when its serializer is exactly the base's.
        if not command.get("factory"):
            matches = []
            for vt, (cls, rec) in by_factory_vtable.items():
                table = vtables.get(vt)
                if table is None:
                    continue
                slots = image.read(vt, min(table["size"] - 16, 26 * 8))
                if (
                    command["serializer"]
                    and struct.pack("<Q", command["serializer"]) in slots
                ):
                    matches.append((vt, cls, rec))
            if len(matches) == 1:
                vt, cls, rec = matches[0]
                command["serializer_owner"] = command["class"]
                command.update({"class": cls, "vtable": vt, "factory": rec["rva"]})
                for key, slot in command["slots"].items():
                    if slot is not None:
                        address = struct.unpack("<Q", image.read(vt + slot * 8, 8))[0]
                        command[
                            {
                                "is_valid": "is_valid",
                                "deleting_destructor": "deleting_destructor",
                                "token": "token_getter",
                            }[key]
                        ] = address
        token = token_evidence(image, command.get("token_getter") or 0)
        command["token_evidence"] = token
        if token["kind"] == "immediate":
            command["token"] = token["token"]
        rec = factory_records.get(command["class"])
        command["factory_evidence"] = rec
        if rec is None:
            continue
        if (
            rec["allocations"] == 1
            and rec.get("allocation_size")
            and command["size"] != rec["allocation_size"]
        ):
            command["previous_size_evidence"] = command["size"]
            command["size"] = rec["allocation_size"]
        roots = [
            w
            for w in rec["writes"]
            if w["offset"] == 0 and w["value"] and w["value"][0] == "rva"
        ]
        command["lifecycle_probe_safe"] = (
            rec["allocations"] == 1
            and rec["straight_line"]
            and not rec["native_calls"]
            and not rec["other_calls"]
            and not rec.get("external_writes")
            and bool(roots)
            and roots[-1]["value"][1] == command["vtable"]
        )
        validator = image.by_address.get(command.get("is_valid"))
        scoped_findings = []
        validator_refs = (
            inline_database_witnesses(
                image,
                validator,
                instance_accessors,
                scoped_accessors=scoped_accessors,
                scoped_findings=scoped_findings,
            )
            if validator
            else []
        )
        quantity_guards = (
            positive_quantity_guards(image, validator) if validator else {}
        )
        validator_code = image.read(command.get("is_valid") or 0, 6)
        command["context_free_validator"] = validator_code[:3] in (
            b"\xb0\x01\xc3",
            b"\x31\xc0\xc3",
        ) or validator_code in (b"\xb8\x01\0\0\0\xc3", b"\xb8\0\0\0\0\xc3")
        # CPersistent fields have a vptr installed by the factory. Resolve that
        # vtable's actual WriteMembers function, not a guessed field-name type.
        expanded, unresolved = [], []

        def expand(
            fields,
            base=0,
            prefix="",
            depth=0,
            expanded=expanded,
            unresolved=unresolved,
            rec=rec,
            command=command,
        ):
            for field in fields:
                f = dict(field)
                off = f.get("linux_off")
                f["name"] = prefix + (f.get("name") or "")
                if off is None:
                    expanded.append(f)
                    continue
                f["linux_off"] = base + off
                if f.get("kind") != "persistent" or f.get("indirect") or depth >= 4:
                    expanded.append(f)
                    continue
                wrapper = f.get("wrapper")
                stores = [
                    w
                    for w in rec["writes"]
                    if w["offset"] == base + off
                    and w["value"]
                    and w["value"][0] == "rva"
                ]
                vt = (
                    wrapper["vtable_rva"]
                    if wrapper
                    else stores[-1]["value"][1]
                    if stores
                    else None
                )
                table = vtables.get(vt)
                if table is None:
                    unresolved.append(
                        {
                            "field": f["name"],
                            "reason": "persistent_identity_not_in_factory",
                        }
                    )
                    expanded.append(f)
                    continue
                type_name = image.target_name(vt - 16).removeprefix("vtable for ")
                text_type = next(
                    (t for t in native_text_values if t["class"] == type_name), None
                )
                if (
                    not wrapper
                    and text_type
                    and base + off + text_type["size"] <= command["size"]
                ):
                    f.update(
                        kind="native_text_value",
                        native_type=type_name,
                        native_size=text_type["size"],
                        assignment_rva=text_type["move_assign_rva"],
                    )
                    expanded.append(f)
                    continue
                raw = image.read(vt, min(table["size"] - (vt - table["rva"]), 32 * 8))
                writers = []
                for addr in struct.unpack("<" + "Q" * (len(raw) // 8), raw):
                    writer_name = image.target_name(addr)
                    if (
                        "::WriteMembers(CWriter&)" in writer_name
                        and not writer_name.startswith("non-virtual thunk")
                    ):
                        nested = serializers.get(writer_name.split("(", 1)[0])
                        if wrapper:
                            symbol = image.by_address.get(addr)
                            if symbol:
                                names = {
                                    v["token"]: v["name"]
                                    for ser in serializers.values()
                                    for v in ser["fields"]
                                    if v.get("name")
                                }
                                nested = extract_serializer(
                                    image, symbol, names, indirect_this_offset=16
                                )
                        if nested:
                            writers.append(nested)
                if (
                    wrapper
                    and wrapper["type"] == "vtable for CGameDate::CSerializerCommands"
                ):
                    # This wrapper overrides Write(), not WriteMembers(). Its
                    # exact body loads the referenced CGameDate's uint32 word.
                    write = struct.unpack("<Q", image.read(vt + 2 * 8, 8))[0]
                    code = image.read(write, 17)
                    if code[:13] == bytes.fromhex(
                        "48 89 f0 48 8b 4f 10 8b 31 48 89 c7 e9"
                    ):
                        target = write + 17 + struct.unpack_from("<i", code, 13)[0]
                        if image.target_name(target) == "CWriter::Write(int)":
                            f.update(
                                kind="game_date32",
                                native_type="CGameDate",
                                width=4,
                                scalar_evidence_rva=write,
                            )
                            expanded.append(f)
                            continue
                if len(writers) != 1 or not writers[0]["fields"]:
                    expanded.append(f)
                    unresolved.append(
                        {
                            "field": f["name"],
                            "reason": "nested_serializer_not_uniquely_resolved",
                        }
                    )
                    continue
                offset_to_top = struct.unpack("<q", image.read(vt - 16, 8))[0]
                if offset_to_top != 0:
                    expanded.append(f)
                    unresolved.append(
                        {
                            "field": f["name"],
                            "reason": "secondary_base_adjustment_required",
                        }
                    )
                    continue
                dependency = next(
                    (
                        d
                        for d in assignments
                        if type_name == d["class"] + "::CSerializer"
                    ),
                    None,
                )
                if wrapper and dependency:
                    unresolved.append(
                        {
                            "field": f["name"],
                            "reason": "native_derived_state_assignment_required",
                            **dependency,
                        }
                    )
                before = len(expanded)
                expand(writers[0]["fields"], base + off, f["name"] + ".", depth + 1)
                if wrapper and dependency:
                    for nested_field in expanded[before:]:
                        nested_field.update(
                            native_assignment_required=True,
                            native_assignment_rva=dependency["assignment_rva"],
                            native_rebuild_rva=dependency["rebuild_rva"],
                        )

        expand(command["fields"])
        command["population_fields"] = expanded
        command["nested_recovery_gaps"] = unresolved
        for f in expanded:
            identities = record_identity_fields.get(f.get("evidence_rva"), [])
            if len(identities) == 1 and f.get("kind") in ("i32", "u32"):
                # Identity provenance is not a scalar candidate or a safe native
                # accessor. Correlated live record fields still need a provider.
                f["native_counter_record_identity"] = identities[0]
                sources = [
                    source
                    for source in record_sources
                    if source["owner_class"] == identities[0]["owner_class"]
                    and source["record_class"] == identities[0]["record_class"]
                ]
                if len(sources) == 1:
                    f["native_record_source"] = sources[0]
            owner = command.get("serializer_owner", command["class"])
            source_fields = constructor_fields[command["class"]]
            if owner != command["class"]:
                source_fields = source_fields + constructor_fields[owner]
            declarations = [
                d
                for d in source_fields
                if d["offset"] == f.get("linux_off") and d["width"] in (4, 8)
            ]
            f["constructor_parameter_evidence"] = declarations
            types = {d["parameter_type"] for d in declarations}
            if len(types) == 1:
                declared = (
                    next(iter(types)).removesuffix(" const&").removesuffix(" const*")
                )
                ref = re.fullmatch(r"TPdxRef<(\w+)>", declared)
                if (
                    f.get("kind") in ("u32", "i32")
                    and ref
                    and all(d["width"] == 4 for d in declarations)
                ):
                    f.update(
                        kind="ref",
                        ref=ref[1],
                        semantic_evidence="native_constructor_typed_reference",
                    )
                elif f.get("kind") == "i32" and re.fullmatch(r"E\w+", declared):
                    f["enum_type"] = declared
                    enum = native_functions.get(
                        f"int EnumToToken<{declared}>({declared} const&)"
                    )
                    if enum:
                        f["enum_serializer_rva"] = enum["rva"]
                elif (
                    f.get("indirect")
                    and declared in null_types
                    and all(d["width"] == 8 for d in declarations)
                ):
                    f.update(
                        definition_type=declared,
                        definition_null_rva=null_types[declared],
                    )
            if (
                f.get("kind") == "i32"
                and not f.get("enum_type")
                and f.get("name")
                in ("claims", "amount", "multiplier", "count", "days", "level")
                and f.get("linux_off") in quantity_guards
            ):
                f["scalar_candidates"] = [quantity_guards[f["linux_off"]]]
            if (
                f.get("kind") in ("u32", "i32")
                and f.get("linux_off") is not None
                and not f.get("enum_type")
            ):
                matches = {
                    r["class"]
                    for r in validator_refs
                    if r.get("source_offset") == f["linux_off"]
                }
                if len(matches) == 1:
                    f.update(
                        kind="ref",
                        ref=matches.pop(),
                        semantic_evidence="native_validator_generation_checked_reference",
                        validator_reference_evidence=[
                            r
                            for r in validator_refs
                            if r.get("source_offset") == f["linux_off"]
                        ],
                    )
                scoped = [
                    r for r in scoped_findings if r["source_offset"] == f["linux_off"]
                ]
                if scoped and f["kind"] in ("u32", "i32"):
                    # Keep the scalar representation; scoped candidate
                    # eligibility is checked separately from TPdxRef recovery.
                    f["scoped_reference_evidence"] = scoped
            if (
                f.get("kind") == "i32"
                and f.get("name") in ("multiplier", "claims")
                and not f.get("enum_type")
            ):
                defaults = [
                    w
                    for w in rec["writes"]
                    if w["offset"] == f["linux_off"]
                    and w["width"] >= 4
                    and w["value"]
                    and w["value"][0] == "constant"
                ]
                if defaults and 0 < (defaults[-1]["value"][1] & 0xFFFFFFFF) <= 100:
                    f["scalar_candidates"] = [
                        {
                            "value": defaults[-1]["value"][1] & 0xFFFFFFFF,
                            "factory_store_rva": defaults[-1]["evidence_rva"],
                            "evidence": "native_positive_quantity_default",
                        }
                    ]
            if f.get("indirect") and f.get("linux_off") is not None:
                stores = [
                    w
                    for w in rec["writes"]
                    if w["offset"] == f["linux_off"]
                    and w["value"]
                    and w["value"][0] == "global"
                ]
                if stores:
                    name = image.target_name(stores[-1]["value"][1])
                    match = re.fullmatch(r"TPdxNullObject<([\w]+)>::_pInstance", name)
                    if match:
                        f["definition_type"] = match.group(1)
                        f["definition_null_rva"] = stores[-1]["value"][1]
                if not f.get("definition_type"):
                    owner = command.get("serializer_owner", command["class"])
                    uses = serializers.get(owner + "::WriteCommandMembers", {}).get(
                        "pointer_uses", []
                    )
                    types = {
                        u["class"]
                        for u in uses
                        if u["offset"] == f["linux_off"] and u["class"] in null_types
                    }
                    if len(types) == 1:
                        f["definition_type"] = types.pop()
                        f["definition_null_rva"] = null_types[f["definition_type"]]
            if f.get("enum_serializer_rva"):
                f["scalar_candidates"] = recover_enum_values(
                    image, f["enum_serializer_rva"]
                )
            if f.get("kind") == "string" and not f.get("indirect"):
                stores = [
                    w
                    for w in rec["writes"]
                    if w["offset"] == f["linux_off"]
                    and w["value"]
                    and w["value"][0] == "rva"
                ]
                native_ctor = any(
                    c["offset"] == f["linux_off"]
                    and c["callee"].startswith("CString::{")
                    for c in rec["native_calls"]
                )
                vptr = stores[-1]["value"][1] if stores else 0
                if native_ctor or image.target_name(vptr - 16) == "vtable for CString":
                    assign = native_functions.get("CString::operator=(char const*)")
                    if assign:
                        f.update(
                            native_type="CString",
                            assignment_rva=assign["rva"],
                            native_size=48,
                        )
            if any(x in f.get("writer", "") for x in ("Uniform", "Array", "Vector")):
                match = re.search(r"TPdxRef<(\w+)>", f["writer"])
                if match:
                    cls = match[1]
                    array_name = f"CPdxArray<TPdxRef<{cls}>, int>"
                    stores = [
                        w
                        for w in rec["writes"]
                        if w["value"]
                        and w["value"][0] == "rva"
                        and image.target_name(w["value"][1] - 16)
                        == "vtable for " + array_name
                    ]
                    # A serializer field's pointer/count may point into the
                    # array, but only one nearby native array is acceptable.
                    stores = [
                        w
                        for w in stores
                        if f.get("linux_off") is not None
                        and w["offset"] <= f["linux_off"] <= w["offset"] + 16
                    ]
                    insert = native_functions.get(
                        f"TPdxRef<{cls}>& {array_name}::InsertAtEmplace<>(int)"
                    )
                    if len(stores) == 1 and insert:
                        f.update(
                            kind="reference_array",
                            ref=cls,
                            linux_off=stores[0]["offset"],
                            native_size=24,
                            assignment_rva=insert["rva"],
                        )
    catalog["object_databases"] = recover_databases(image)
    from scoped_id_recovery import scoped_id_bindings

    catalog["scoped_id_bindings"] = scoped_id_bindings(catalog)
    catalog["definition_databases"] = recover_definitions(
        image, catalog, native_functions
    )
    catalog["recovery_summary"] = {
        "native_reference_databases": len(catalog["object_databases"]),
        "native_assignment_dependencies": len(assignments),
        "native_counter_record_identities": len(record_identities),
        "native_country_record_sources": len(record_sources),
        "scoped_candidate_bindings": len(catalog["scoped_id_bindings"]),
        "native_definition_databases": len(catalog["definition_databases"]),
        "native_definition_types": len(
            {d["class"] for d in catalog["definition_databases"]}
        ),
        "native_text_value_types": len(native_text_values),
        "native_country_scoped_accessors": len(scoped_recipes),
        "country_scoped_id_fields": sum(
            bool(f.get("scoped_reference_evidence"))
            for c in catalog["commands"]
            for f in c.get("population_fields", [])
        ),
        "country_scoped_bound_fields": sum(
            bool(f.get("scoped_reference_evidence"))
            and all(r.get("country_reference") for r in f["scoped_reference_evidence"])
            for c in catalog["commands"]
            for f in c.get("population_fields", [])
        ),
        "concrete_factory_aliases": sum(
            "serializer_owner" in c for c in catalog["commands"]
        ),
        "token_sources": dict(
            Counter(c["token_evidence"]["kind"] for c in catalog["commands"])
        ),
        "nested_fields_recovered": sum(
            "." in f["name"]
            for c in catalog["commands"]
            for f in c.get("population_fields", [])
        ),
    }


def _enum_switch_values(image, symbol: dict, ins: list) -> list[dict]:
    """Recognize a bounded relative switch, retaining only constant-token leaves."""
    if len(ins) < 9 or [i.mnemonic for i in ins[:8]] != [
        "mov",
        "cmp",
        "ja",
        "mov",
        "lea",
        "movsxd",
        "add",
        "jmp",
    ]:
        return []
    first, compare, guard, initial, table, entry, add, jump = [
        i.operands for i in ins[:8]
    ]
    if not (
        len(first) == 2
        and first[0].type == X86_OP_REG
        and first[0].size == 4
        and first[1].type == X86_OP_MEM
        and first[1].size == 4
        and image.md.reg_name(first[1].mem.base) == "rdi"
        and not first[1].mem.index
        and first[1].mem.disp == 0
        and len(compare) == 2
        and compare[0].type == X86_OP_REG
        and compare[1].type == X86_OP_IMM
        and 0 <= compare[1].imm < 32
        and len(guard) == 1
        and guard[0].type == X86_OP_IMM
        and len(initial) == 2
        and initial[0].type == X86_OP_REG
        and image.md.reg_name(initial[0].reg) == "eax"
        and initial[1].type == X86_OP_IMM
        and len(table) == 2
        and table[0].type == X86_OP_REG
        and table[0].size == 8
        and table[1].type == X86_OP_MEM
        and image.md.reg_name(table[1].mem.base) == "rip"
        and not table[1].mem.index
        and len(entry) == 2
        and entry[0].type == X86_OP_REG
        and entry[0].size == 8
        and entry[1].type == X86_OP_MEM
        and entry[1].size == 4
        and entry[1].mem.scale == 4
        and entry[1].mem.disp == 0
        and len(add) == 2
        and all(o.type == X86_OP_REG and o.size == 8 for o in add)
        and len(jump) == 1
        and jump[0].type == X86_OP_REG
        and jump[0].size == 8
    ):
        return []

    def reg(operand):
        return register(image.md.reg_name(operand.reg))

    index, base = reg(first[0]), reg(table[0])
    if not (
        index != base
        and reg(compare[0]) == reg(entry[0]) == reg(add[0]) == reg(jump[0]) == index
        and reg(add[1]) == base
        and register(image.md.reg_name(entry[1].mem.base)) == base
        and register(image.md.reg_name(entry[1].mem.index)) == index
        and index != "rax"
        and base != "rax"
    ):
        return []
    instructions = {i.address: i for i in ins}
    if guard[0].imm not in instructions or guard[0].imm <= ins[7].address:
        return []
    table_rva = ins[4].address + ins[4].size + table[1].mem.disp
    count = compare[1].imm + 1
    data = image.read(table_rva, count * 4)
    if len(data) != count * 4:
        return []
    targets = [table_rva + v for v in struct.unpack("<" + "i" * count, data)]
    if any(t not in instructions or t <= ins[7].address for t in targets):
        return []

    def constant_leaf(address: int) -> int | None:
        token = initial[1].imm
        visited = set()
        while address in instructions and len(visited) < 8:
            if address in visited:
                return None
            visited.add(address)
            instruction = instructions[address]
            ops = instruction.operands
            if instruction.mnemonic == "ret" and not ops:
                return token if 0 < token <= 0xFFFFFFFF else None
            if (
                instruction.mnemonic == "mov"
                and len(ops) == 2
                and ops[0].type == X86_OP_REG
                and image.md.reg_name(ops[0].reg) == "eax"
                and ops[1].type == X86_OP_IMM
            ):
                token = ops[1].imm
            elif (
                instruction.mnemonic == "jmp"
                and len(ops) == 1
                and ops[0].type == X86_OP_IMM
            ):
                address = ops[0].imm
                continue
            else:
                # Global/object reads and conditional leaves are not constants.
                return None
            address += instruction.size
        return None

    return [
        {
            "value": value,
            "token": token,
            "serializer_rva": symbol["rva"],
            "table_rva": table_rva,
            "branch_target_rva": target,
            "evidence": "bounded_relative_enum_switch_constant_leaf",
        }
        for value, target in enumerate(targets)
        if target != guard[0].imm and (token := constant_leaf(target)) is not None
    ]


def recover_enum_values(image, rva: int) -> list[dict]:
    """Recognize bounded native token tables/switches, never guessed ranges."""
    symbol = image.by_address.get(rva)
    if symbol is None:
        return []
    ins = image.instructions(symbol, 1024)
    if values := _enum_switch_values(image, symbol, ins):
        return values
    # Exact shape: signed enum load, unsigned range check, token lookup.
    if (
        len(ins) != 7
        or ins[0].mnemonic not in ("movsxd", "movsx")
        or ins[2].mnemonic != "cmp"
        or ins[3].mnemonic != "ja"
        or ins[4].mnemonic != "lea"
        or ins[5].mnemonic != "mov"
        or ins[6].mnemonic != "ret"
    ):
        return []
    a, cmp, lea, load = (
        ins[0].operands,
        ins[2].operands,
        ins[4].operands,
        ins[5].operands,
    )
    if (
        len(a) != 2
        or a[0].type != X86_OP_REG
        or register(image.md.reg_name(a[0].reg)) == "rax"
        or a[1].type != X86_OP_MEM
        or a[1].mem.disp != 0
        or image.md.reg_name(a[1].mem.base) != "rdi"
        or a[1].mem.index
        or ins[1].mnemonic != "mov"
        or len(ins[1].operands) != 2
        or ins[1].operands[0].type != X86_OP_REG
        or image.md.reg_name(ins[1].operands[0].reg) != "eax"
        or ins[1].operands[1].type != X86_OP_IMM
        or cmp[0].type != X86_OP_REG
        or cmp[1].type != X86_OP_IMM
        or not 0 <= cmp[1].imm < 32
        or ins[3].operands[0].type != X86_OP_IMM
        or ins[3].operands[0].imm != ins[6].address
    ):
        return []
    if (
        lea[0].type != X86_OP_REG
        or lea[1].type != X86_OP_MEM
        or image.md.reg_name(lea[1].mem.base) != "rip"
        or lea[1].mem.index
        or load[0].type != X86_OP_REG
        or image.md.reg_name(load[0].reg) != "eax"
        or load[1].type != X86_OP_MEM
        or load[1].size != 4
        or load[1].mem.scale != 4
        or load[1].mem.disp != 0
    ):
        return []
    if (
        register(image.md.reg_name(cmp[0].reg)) != register(image.md.reg_name(a[0].reg))
        or load[1].mem.index != a[0].reg
        or load[1].mem.base != lea[0].reg
    ):
        return []
    table = ins[4].address + ins[4].size + lea[1].mem.disp
    data = image.read(table, (cmp[1].imm + 1) * 4)
    if len(data) != (cmp[1].imm + 1) * 4:
        return []
    return [
        {"value": i, "token": token, "serializer_rva": rva, "table_rva": table}
        for i, token in enumerate(struct.unpack("<" + "I" * (len(data) // 4), data))
    ]
