"""Bounded exact-ELF rule/call/guard discovery for the complete SDK catalog.

Reachability and type uniqueness are NOT proof that a rule is a necessary
precondition. Such associations are retained as ranking hints, not filters.
Unknown indirect edges and budgets are explicit in every affected report.
"""

from __future__ import annotations

import hashlib
import re
import struct
from collections import deque

from capstone.x86 import X86_OP_IMM, X86_OP_MEM, X86_OP_REG
from sdk_recovery.linux_elf import register

ARGS = ("rdi", "rsi", "rdx", "rcx", "r8", "r9")
VOLATILE = ("rax", "rcx", "rdx", "rsi", "rdi", "r8", "r9", "r10", "r11")


def snake(name: str) -> str:
    return re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1_\2", name)).lower()


def _plus(value, offset):
    if value and value[0] in {"stack", "arg", "address"}:
        return value[0], value[1], value[2] + offset
    return None


class Discovery:
    def __init__(self, image, sdk: dict, rule_keys: set[str]):
        if image.build_id != sdk["build_id"] or hashlib.sha256(image.data).hexdigest() != sdk["sha256"]:
            raise ValueError("SDK and ELF exact identity mismatch")
        self.image, self.sdk, self.rule_keys = image, sdk, rule_keys
        self.cache: dict[int, dict] = {}
        self.wrappers: dict[int, dict] = {}
        self.ctor_cache = {}
        for symbol in image.symbols:
            if symbol["type"] == "STT_FUNC" and "CGameRules" in symbol["raw"] and symbol["rva"] not in self.wrappers:
                name = image.name(symbol)
                method = name.split("::", 1)[-1].split("(", 1)[0].removesuffix(" const")
                key = snake(method)
                if key in rule_keys:
                    details = self.function(symbol["rva"])
                    if details["rule_evaluations"]:
                        self.wrappers[symbol["rva"]] = {
                            "rule": key, "wrapper_rva": symbol["rva"], "function": name,
                            "name_binding": "exact_symbol_snake_case_and_script_key",
                            "registration_token_verified": False,
                            "evaluations": details["rule_evaluations"],
                            "scope_setters": details["scope_setters"],
                        }

    def constructor_vptr(self, rva):
        if rva in self.ctor_cache:
            return self.ctor_cache[rva]
        symbol = self.image.by_address.get(rva)
        result = None
        if symbol and symbol["size"] <= 2048:
            regs = {}
            for ins in self.image.instructions(symbol):
                ops = ins.operands
                if ins.mnemonic == "lea" and len(ops) == 2 and ops[0].type == X86_OP_REG and ops[1].type == X86_OP_MEM and ins.reg_name(ops[1].mem.base) == "rip":
                    regs[register(ins.reg_name(ops[0].reg))] = ins.address + ins.size + ops[1].mem.disp
                elif ins.mnemonic == "mov" and len(ops) == 2 and ops[0].type == X86_OP_MEM and ins.reg_name(ops[0].mem.base) == "rdi" and ops[0].mem.disp == 0 and not ops[0].mem.index and ops[1].type == X86_OP_REG:
                    pointer = regs.get(register(ins.reg_name(ops[1].reg)))
                    if pointer and self.image.read(pointer, 8):
                        result = pointer
                elif ops and ops[0].type == X86_OP_REG:
                    regs.pop(register(ins.reg_name(ops[0].reg)), None)
        self.ctor_cache[rva] = result
        return result

    def function(self, rva: int) -> dict:
        if rva in self.cache:
            return self.cache[rva]
        symbol = self.image.by_address.get(rva)
        output = {"rva": rva, "name": self.image.target_name(rva), "calls": [],
                  "scope_setters": [], "rule_evaluations": [], "comparisons": [],
                  "unknown_indirect_calls": [], "truncated": False}
        self.cache[rva] = output
        if not symbol or symbol["type"] != "STT_FUNC" or symbol["size"] > 16384:
            output["truncated"] = True
            return output
        instructions = self.image.instructions(symbol)
        output["sha256"] = hashlib.sha256(self.image.read(rva, symbol["size"])).hexdigest()
        # This limited value pass resolves local stack-object vtables and
        # wrapper scope construction only. Crossing a join invalidates values.
        targets = {i.operands[0].imm for i in instructions if i.mnemonic.startswith("j") and i.operands and i.operands[0].type == X86_OP_IMM}
        regs = {r: ("arg", n, 0) for n, r in enumerate(ARGS)}
        regs["rsp"] = ("stack", 0, 0)
        memory = {}
        scope_setters = {}

        def value(ins, op, address=False):
            if op.type == X86_OP_IMM:
                return "address", op.imm, 0
            if op.type == X86_OP_REG:
                return regs.get(register(ins.reg_name(op.reg)))
            if op.type != X86_OP_MEM or op.mem.index:
                return None
            if ins.reg_name(op.mem.base) == "rip":
                location = ("address", ins.address + ins.size + op.mem.disp, 0)
            else:
                location = _plus(regs.get(register(ins.reg_name(op.mem.base))), op.mem.disp)
            if address:
                return location
            if location in memory:
                return memory[location]
            return None

        for ins in instructions:
            ops = ins.operands
            if ins.address in targets:
                # Do not accidentally use a value from a different CFG arm.
                regs = {"rsp": regs.get("rsp")}
                memory.clear()
                scope_setters.clear()
            if ins.mnemonic in {"push", "pop"}:
                regs["rsp"] = _plus(regs.get("rsp"), -8 if ins.mnemonic == "push" else 8)
                if ins.mnemonic == "pop" and ops[0].type == X86_OP_REG:
                    regs.pop(register(ins.reg_name(ops[0].reg)), None)
                continue
            if ins.mnemonic in {"call", "jmp"} and ops:
                target = ops[0].imm if ops[0].type == X86_OP_IMM else None
                kind = "direct" if target else "unknown_indirect"
                if target is None and ops[0].type == X86_OP_MEM:
                    base = regs.get(register(ins.reg_name(ops[0].mem.base)))
                    receiver = regs.get("rdi")
                    if base and base[0] == "vtable" and receiver == base[2] and not ops[0].mem.index:
                        raw = self.image.read(base[1] + ops[0].mem.disp, 8)
                        target = struct.unpack("<Q", raw)[0] if len(raw) == 8 else None
                        kind = "local_constructed_object_virtual" if target else kind
                if target:
                    name = self.image.target_name(target)
                    call = {"site_rva": ins.address, "target_rva": target, "name": name, "kind": kind}
                    output["calls"].append(call)
                    if "CScopeObjectReference::Set" in name:
                        typ = name.split("::Set", 1)[1].split("(", 1)[0]
                        entry = {"type": typ, "object": regs.get("rsi"), "scope": regs.get("rdi"), "site_rva": ins.address}
                        output["scope_setters"].append(entry)
                        scope_setters[regs.get("rdi")] = entry
                    if "CScriptedRule::Evaluate" in name:
                        receiver, scope = regs.get("rdi"), regs.get("rsi")
                        output["rule_evaluations"].append({
                            "site_rva": ins.address, "rule_receiver": receiver,
                            "this_scope": scope_setters.get(scope),
                            "root_scope": scope_setters.get(memory.get(_plus(scope, 0x30))),
                            "from_scope": scope_setters.get(memory.get(_plus(scope, 0x38))),
                        })
                    local = regs.get("rdi")
                    vptr = self.constructor_vptr(target) if "::{" in name and "ctor}" in name else None
                    if vptr and local and local[0] == "stack":
                        memory[local] = ("vtable", vptr, local)
                elif ins.mnemonic == "call":
                    output["unknown_indirect_calls"].append(ins.address)
                if ins.mnemonic == "call":
                    for reg in VOLATILE:
                        regs.pop(reg, None)
                continue
            if ins.mnemonic in {"cmp", "test"} and len(ops) == 2:
                output["comparisons"].append({"site_rva": ins.address, "instruction": ins.mnemonic + " " + ins.op_str,
                                              "left": value(ins, ops[0]), "right": value(ins, ops[1]),
                                              "status": "UNKNOWN_until_dataflow_and_path_binding"})
                continue
            if ins.mnemonic == "mov" and len(ops) == 2:
                source = value(ins, ops[1])
                if ops[0].type == X86_OP_REG:
                    regs[register(ins.reg_name(ops[0].reg))] = source
                elif ops[0].type == X86_OP_MEM:
                    location = value(ins, ops[0], True)
                    if location:
                        memory[location] = source
                continue
            if ins.mnemonic == "lea" and len(ops) == 2 and ops[0].type == X86_OP_REG:
                regs[register(ins.reg_name(ops[0].reg))] = value(ins, ops[1], True)
                continue
            if ins.mnemonic in {"add", "sub"} and len(ops) == 2 and ops[0].type == X86_OP_REG and ops[1].type == X86_OP_IMM:
                reg = register(ins.reg_name(ops[0].reg))
                regs[reg] = _plus(regs.get(reg), ops[1].imm * (1 if ins.mnemonic == "add" else -1))
                continue
            if ops and ops[0].type == X86_OP_REG and ins.mnemonic not in {"nop", "ret"}:
                regs.pop(register(ins.reg_name(ops[0].reg)), None)
        return output

    @staticmethod
    def _follow(name):
        if not name or "dtor}" in name or "ctor}" in name:
            return False
        if name.startswith(("CGameRules::", "NFleetOrderUtil::")):
            return True
        # Decision/query neighborhoods only, never execute or script effects.
        return bool(re.search(r"::(?:Is|Can|Check|CalcCan|GetController|GetOwner|GetCountry|GetPlanet)", name))

    def command(self, command: dict, max_depth=5, max_functions=160) -> dict:
        queue = deque([(command.get("is_valid", 0), ())])
        seen, rules, functions, unknown, paths = set(), {}, [], [], []
        while queue and len(seen) < max_functions:
            rva, path = queue.popleft()
            if not rva or rva in seen:
                continue
            seen.add(rva)
            evidence = self.function(rva)
            functions.append(rva)
            new_path = path + (rva,)
            if rva in self.wrappers:
                rules[rva] = self.wrappers[rva] | {"path": new_path, "necessity": "UNKNOWN"}
                continue
            unknown.extend(evidence["unknown_indirect_calls"])
            if len(new_path) <= max_depth:
                for edge in evidence["calls"]:
                    if self._follow(edge["name"]):
                        queue.append((edge["target_rva"], new_path))
                    if edge["kind"] == "local_constructed_object_virtual":
                        paths.append(edge | {"caller_rva": rva})
        return {"rules": sorted(rules.values(), key=lambda r: r["rule"]),
                "functions": functions, "unresolved_indirect_sites": sorted(set(unknown)),
                "resolved_local_virtual_edges": paths, "budget_exhausted": bool(queue),
                "hardcoded_comparisons": sum(len(self.function(r)["comparisons"]) for r in functions)}
