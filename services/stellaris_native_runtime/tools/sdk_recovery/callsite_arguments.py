"""Find verified direct constructor calls and basic-block-local literal args.

This deliberately does not perform cross-branch speculative value propagation.
Dynamic arguments remain unknown and retain their caller/callsite for Ghidra.
"""

from __future__ import annotations

import bisect
import re
import struct
from collections import defaultdict

from capstone.x86 import X86_OP_IMM, X86_OP_REG
from linux_elf import register

ARGUMENTS = ("rsi", "rdx", "rcx", "r8", "r9")


def recover_callsites(image, targets: set[int]) -> list[dict]:
    functions = {}
    for s in image.symbols:
        if (
            s["type"] == "STT_FUNC"
            and s["size"]
            and s["size"] > functions.get(s["rva"], {}).get("size", 0)
        ):
            functions[s["rva"]] = s
    starts = sorted(functions)
    grouped = defaultdict(set)
    for start, offset, length in image.segments:
        raw = image.data[offset : offset + length]
        for match in re.finditer(b"\xe8", raw):
            pos = match.start()
            if pos + 5 > len(raw):
                continue
            pc = start + pos
            target = pc + 5 + struct.unpack_from("<i", raw, pos + 1)[0]
            if target not in targets:
                continue
            n = bisect.bisect_right(starts, pc) - 1
            if n >= 0:
                symbol = functions[starts[n]]
                if pc + 5 <= symbol["rva"] + symbol["size"]:
                    grouped[symbol["rva"]].add(pc)
    result = []
    for start, wanted in sorted(grouped.items()):
        symbol = functions[start]
        if symbol["size"] > 65536:
            for pc in sorted(wanted):
                result.append(
                    {
                        "caller_rva": start,
                        "caller": image.name(symbol),
                        "call_rva": pc,
                        "instruction_verified": False,
                        "reason": "caller_exceeds_bounded_disassembly",
                        "register_literals": {},
                    }
                )
            continue
        instructions = image.instructions(symbol, 65536)
        block_starts = {start}
        for i in instructions:
            if i.mnemonic == "call":
                block_starts.add(i.address + i.size)
            if i.mnemonic.startswith("j"):
                block_starts.add(i.address + i.size)
                if i.operands and i.operands[0].type == X86_OP_IMM:
                    block_starts.add(i.operands[0].imm)
            if i.mnemonic == "ret":
                block_starts.add(i.address + i.size)
        known = {}
        for i in instructions:
            if i.address in block_starts:
                known.clear()
            ops = i.operands
            if i.mnemonic == "call":
                if (
                    i.address in wanted
                    and ops
                    and ops[0].type == X86_OP_IMM
                    and ops[0].imm in targets
                ):
                    result.append(
                        {
                            "caller_rva": start,
                            "caller": image.name(symbol),
                            "call_rva": i.address,
                            "constructor_rva": ops[0].imm,
                            "instruction_verified": True,
                            "register_literals": {
                                r: known[r] for r in ARGUMENTS if r in known
                            },
                        }
                    )
                known.clear()
                continue
            if not ops or ops[0].type != X86_OP_REG:
                continue
            dst = register(i.reg_name(ops[0].reg))
            if i.mnemonic in ("test", "cmp", "push"):
                continue
            value = None
            if len(ops) == 2:
                src = ops[1]
                if i.mnemonic in ("mov", "movabs"):
                    if src.type == X86_OP_IMM:
                        value = {"value": src.imm, "evidence_rva": i.address}
                    elif src.type == X86_OP_REG:
                        value = known.get(register(i.reg_name(src.reg)))
                elif (
                    i.mnemonic == "xor"
                    and src.type == X86_OP_REG
                    and ops[0].reg == src.reg
                ):
                    value = {"value": 0, "evidence_rva": i.address}
            if value is None:
                known.pop(dst, None)
            else:
                known[dst] = value
    return result


def apply_callsite_evidence(catalog: dict) -> None:
    by_constructor = defaultdict(list)
    for row in catalog.get("constructor_callsites", []):
        if row["instruction_verified"]:
            by_constructor[row["constructor_rva"]].append(row)
    for command in catalog["commands"]:
        for field in command.get("population_fields", []):
            evidence, quantities = [], {}
            for declaration in field.get("constructor_parameter_evidence", []):
                for call in by_constructor[declaration["constructor_rva"]]:
                    argument = ARGUMENTS[declaration["parameter_index"]]
                    literal = call["register_literals"].get(argument)
                    row = {
                        "caller": call["caller"],
                        "caller_rva": call["caller_rva"],
                        "call_rva": call["call_rva"],
                        "parameter_register": argument,
                        "literal": literal,
                        "dereferenced": declaration["dereferenced"],
                    }
                    evidence.append(row)
                    # A literal pointer is not its pointee; IDs/indices are
                    # never populated from UI constants by this generic rule.
                    if (
                        literal
                        and not declaration["dereferenced"]
                        and declaration["width"] == 4
                    ):
                        value = literal["value"] & 0xFFFFFFFF
                        if 0 < value <= 1_000_000:
                            quantities[value] = {
                                "value": value,
                                "evidence": "native_constructor_callsite_quantity_literal",
                                "caller_rva": call["caller_rva"],
                                "call_rva": call["call_rva"],
                                "assignment_rva": literal["evidence_rva"],
                            }
            field["callsite_parameter_evidence"] = evidence[:32]
            if (
                quantities
                and field.get("kind") == "i32"
                and field.get("name")
                in ("claims", "amount", "multiplier", "count", "days", "level")
                and not field.get("enum_type")
                and not field.get("scalar_candidates")
            ):
                field["scalar_candidates"] = [
                    quantities[k] for k in sorted(quantities)[:16]
                ]
