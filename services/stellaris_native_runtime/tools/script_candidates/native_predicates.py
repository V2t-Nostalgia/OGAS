"""Recover small native field predicates and serializer-backed enum semantics.

No Command-specific names, offsets or enum values. A recognized three-op native
predicate, a serializer field at the SAME offset, a checked enum/token table and
a literal callsite must all agree. Unique-type Command associations remain
advisory until interprocedural argument flow is proven.
"""

from __future__ import annotations

import re
import struct

from capstone.x86 import X86_OP_IMM, X86_OP_MEM, X86_OP_REG
from linux_elf import extract_serializer, register as _register
from callsite_arguments import recover_callsites
from .native_guards import analyze


def register(name):
    return {"bpl": "rbp", "spl": "rsp"}.get(name, _register(name))


def pure_predicate(image, rva):
    symbol = image.by_address.get(rva)
    if not symbol or symbol["size"] > 64:
        return None
    name = image.name(symbol)
    match = re.fullmatch(r"(C\w+)::Is\w+ const\((E\w+)\)", name)
    if not match:
        return None
    instructions = [i for i in image.instructions(symbol) if i.mnemonic != "nop"]
    if len(instructions) != 3 or [i.mnemonic for i in instructions] not in (["cmp", "sete", "ret"], ["cmp", "setne", "ret"]):
        return None
    left, right = instructions[0].operands
    if (left.type != X86_OP_MEM or image.md.reg_name(left.mem.base) != "rdi" or left.mem.index
            or right.type != X86_OP_REG or register(image.md.reg_name(right.reg)) != "rsi"
            or instructions[1].op_str != "al"):
        return None
    return {"owner": match[1], "enum_type": match[2], "offset": left.mem.disp, "width": left.size,
            "operator": "==" if instructions[1].mnemonic == "sete" else "!=", "rva": rva, "name": name}


def enum_table(image, symbol, enum_type, tokens):
    if symbol["size"] > 512 or not image.name(symbol).endswith("TokenFromEnum(" + enum_type + ")"):
        return None
    instructions = image.instructions(symbol)
    # A by-value token converter's first argument may be saved in a register.
    origins = {"rdi"}
    for index, ins in enumerate(instructions):
        ops = ins.operands
        copied = None
        if ins.mnemonic == "mov" and len(ops) == 2 and ops[0].type == ops[1].type == X86_OP_REG:
            if register(ins.reg_name(ops[1].reg)) in origins:
                copied = register(ins.reg_name(ops[0].reg))
        if ins.mnemonic == "call":
            return None
        for written in ins.regs_access()[1]:
            origins.discard(register(ins.reg_name(written)))
        if copied:
            origins.add(copied)
        if ins.mnemonic != "cmp" or len(ops) != 2 or ops[0].type != X86_OP_REG or ops[1].type != X86_OP_IMM:
            continue
        if register(ins.reg_name(ops[0].reg)) not in origins or not 1 <= ops[1].imm <= 64 or index + 4 >= len(instructions):
            continue
        branch, extend, lea, load = instructions[index + 1:index + 5]
        if (branch.mnemonic != "jae" or branch.operands[0].type != X86_OP_IMM
                or branch.operands[0].imm <= load.address or extend.mnemonic not in {"movsx", "movzx", "movsxd"}
                or extend.operands[1].type != X86_OP_REG or extend.operands[1].reg != ops[0].reg
                or lea.mnemonic != "lea" or lea.operands[1].type != X86_OP_MEM
                or ins.reg_name(lea.operands[1].mem.base) != "rip" or lea.operands[1].mem.index
                or load.mnemonic != "mov" or load.operands[1].type != X86_OP_MEM
                or load.operands[1].size != 4 or load.operands[1].mem.scale != 4
                or load.operands[1].mem.disp != 0
                or load.operands[1].mem.index != extend.operands[0].reg
                or load.operands[1].mem.base != lea.operands[0].reg):
            continue
        address = lea.address + lea.size + lea.operands[1].mem.disp
        data = image.read(address, ops[1].imm * 4)
        if len(data) != ops[1].imm * 4:
            continue
        values = struct.unpack("<" + "I" * ops[1].imm, data)
        if any(token not in tokens for token in values):
            continue
        # Verify the loaded table value is returned without modification on
        # the in-range arm; out-of-range diagnostics are not interpreted.
        returned_register = register(load.reg_name(load.operands[0].reg))
        cursor = index + 5
        if instructions[cursor].mnemonic != "jmp":
            continue
        target = instructions[cursor].operands[0].imm
        tail = next((n for n, i in enumerate(instructions) if i.address == target), None)
        if tail is None or instructions[tail].mnemonic != "mov" or instructions[tail].op_str != "eax, " + returned_register.replace("r", "e", 1):
            continue
        if any(i.mnemonic not in {"add", "pop", "ret", "nop"} or
               (i.mnemonic == "add" and i.op_str.split(",")[0] != "rsp") or
               (i.mnemonic == "pop" and register(i.op_str) == "rax") for i in instructions[tail+1:]):
            continue
        return {"converter_rva": symbol["rva"], "table_rva": address,
                "tokens": {str(n): tokens[token] for n, token in enumerate(values)}}
    return None


def discover_predicates(image, discovery, analyses, sdk, tokens):
    predicates = {}
    for function in discovery.cache.values():
        for call in function["calls"]:
            rva = call["target_rva"]
            if rva not in predicates:
                predicates[rva] = pure_predicate(image, rva)
    predicates = {r: p for r, p in predicates.items() if p}
    if not predicates:
        return [], [[] for _ in analyses]
    owners = {p["owner"] for p in predicates.values()}
    serializers = {}
    for symbol in image.symbols:
        if symbol["type"] == "STT_FUNC" and "WriteMembers" in symbol["raw"] and any(owner in symbol["raw"] for owner in owners):
            name = image.name(symbol)
            owner = name.split("::", 1)[0]
            if owner in owners and name == owner + "::WriteMembers(CWriter&)":
                serializers[owner] = symbol
    confirmed = {}
    for rva, predicate in predicates.items():
        serializer = serializers.get(predicate["owner"])
        if not serializer:
            continue
        rows = extract_serializer(image, serializer, tokens)["fields"]
        instructions = image.instructions(serializer)
        states, _, _ = analyze(instructions, {})
        for field in rows:
            writer_index = next((n for n, i in enumerate(instructions) if i.address == field["evidence_rva"]), None)
            if writer_index is None or writer_index < 5:
                continue
            load, convert, writer, token_load, result_move = instructions[writer_index-5:writer_index]
            if (load.mnemonic not in {"movzx", "movsx", "mov"} or len(load.operands) != 2
                    or load.operands[0].type != X86_OP_REG or register(load.reg_name(load.operands[0].reg)) != "rdi"
                    or load.operands[1].type != X86_OP_MEM or load.operands[1].mem.index
                    or load.operands[1].mem.disp != predicate["offset"] or load.operands[1].size != predicate["width"]
                    or states.get(load.address, {}).get(register(load.reg_name(load.operands[1].mem.base))) != ("this", 0)
                    or convert.mnemonic != "call" or convert.operands[0].type != X86_OP_IMM
                    or writer.mnemonic != "mov" or writer.op_str.split(",")[0] != "rdi"
                    or token_load.mnemonic != "mov" or token_load.op_str.split(",")[0] != "esi"
                    or token_load.operands[1].type != X86_OP_IMM or token_load.operands[1].imm != field["token"]
                    or result_move.mnemonic != "mov" or result_move.op_str != "edx, eax"):
                continue
            converter = image.by_address.get(convert.operands[0].imm)
            table = enum_table(image, converter, predicate["enum_type"], tokens) if converter else None
            if table:
                confirmed[rva] = predicate | table | {"save_field": field["name"], "serializer_rva": serializer["rva"], "writer_rva": field["evidence_rva"]}
    callsites = recover_callsites(image, set(confirmed)) if confirmed else []
    hints = []
    for command, analysis in zip(sdk["commands"], analyses):
        found = []
        fields = command.get("population_fields", command["fields"])
        for call in callsites:
            if not call["instruction_verified"] or call["caller_rva"] not in analysis["functions"] or "rsi" not in call["register_literals"]:
                continue
            predicate = confirmed[call["constructor_rva"]]
            matches = [f for f in fields if f.get("ref") == predicate["owner"]]
            literal = str(call["register_literals"]["rsi"]["value"])
            if len(matches) == 1 and literal in predicate["tokens"]:
                found.append(predicate | {"command_field": matches[0]["name"], "expected": predicate["tokens"][literal],
                    "call_rva": call["call_rva"], "literal_evidence": call["register_literals"]["rsi"],
                    "binding": "unique_native_type_advisory", "necessity": "UNKNOWN"})
        hints.append(found)
    return list(confirmed.values()), hints
