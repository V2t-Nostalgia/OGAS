"""Conservative CFG abstract interpretation of native payload rejection guards.

No machine code is executed. Only guards whose bypass paths and rejecting arm
provably return zero are usable filters. Memory outside recovered payload fields
and calls without summaries remain UNKNOWN. This is deliberately not a full
reimplementation of IsValid or an unconstrained symbolic execution of the game.
"""

from __future__ import annotations

from collections import deque

from capstone.x86 import X86_OP_IMM, X86_OP_MEM, X86_OP_REG
from sdk_recovery.linux_elf import register
from sdk_recovery.emit_ogas import field_layout

VOLATILE = {"rax", "rcx", "rdx", "rsi", "rdi", "r8", "r9", "r10", "r11"}


def operand(ins, op, state, fields):
    if op.type == X86_OP_IMM:
        return ("constant", op.imm)
    if op.type == X86_OP_REG:
        return state.get(register(ins.reg_name(op.reg)))
    if op.type == X86_OP_MEM and not op.mem.index:
        base = state.get(register(ins.reg_name(op.mem.base)))
        if base and base[0] == "this":
            offset = base[1] + op.mem.disp
            if offset in fields and op.size == fields[offset]["width"] and "!payload_clobbered" not in state:
                return ("field", fields[offset]["name"])
    return None


def transfer(ins, incoming, fields):
    state = dict(incoming)
    ops, mnemonic = ins.operands, ins.mnemonic
    if mnemonic == "call":
        for reg in VOLATILE:
            state.pop(reg, None)
        # No mod/ref summary exists for opaque callees. Later payload loads
        # must not be equated with initial inputs, even for a const IsValid.
        state["!payload_clobbered"] = ("constant", 1)
        return state
    if mnemonic.startswith("j") or mnemonic in {"cmp", "test", "nop", "ret", "push"}:
        return state
    if not ops or ops[0].type != X86_OP_REG:
        if ops and ops[0].type == X86_OP_MEM:
            base = state.get(register(ins.reg_name(ops[0].mem.base)))
            if not base or base[0] != "stack":
                state["!payload_clobbered"] = ("constant", 1)
        for written in ins.regs_access()[1]:
            state.pop(register(ins.reg_name(written)), None)
        return state
    dest = register(ins.reg_name(ops[0].reg))
    val = None
    if mnemonic == "mov" and len(ops) == 2:
        val = operand(ins, ops[1], state, fields)
    elif mnemonic == "lea" and len(ops) == 2 and ops[1].type == X86_OP_MEM and not ops[1].mem.index:
        base = state.get(register(ins.reg_name(ops[1].mem.base)))
        if base and base[0] in {"this", "stack"}:
            val = (base[0], base[1] + ops[1].mem.disp)
    elif mnemonic in {"xor", "sub"} and len(ops) == 2 and ops[1].type == X86_OP_REG and ops[0].reg == ops[1].reg:
        val = ("constant", 0)
    elif mnemonic in {"add", "sub"} and len(ops) == 2 and ops[1].type == X86_OP_IMM:
        old = state.get(dest)
        if old and old[0] in {"constant", "this", "stack"}:
            val = (old[0], old[1] + ops[1].imm * (1 if mnemonic == "add" else -1))
    # Partial writes cannot establish the value of a full register.
    if ops[0].size < 4:
        val = None
    # Include implicit writes (mul/div/xchg/leave), not just operand zero.
    for written in ins.regs_access()[1]:
        state.pop(register(ins.reg_name(written)), None)
    if val is None:
        state.pop(dest, None)
    else:
        if val[0] == "constant" and ops[0].size == 4:
            val = ("constant", val[1] & 0xFFFFFFFF)
        state[dest] = val
    return state


def analyze(instructions, fields, *, start=None, initial=None, blocked=None, budget=10000):
    if not instructions:
        return {}, [], False
    positions = {ins.address: index for index, ins in enumerate(instructions)}
    first = instructions[0].address if start is None else start
    states = {first: {"rdi": ("this", 0), "rsp": ("stack", 0)} if initial is None else initial}
    queue, returns, complete = deque([first]), {}, True
    steps = 0
    while queue:
        address = queue.popleft()
        if address == blocked:
            continue
        steps += 1
        if steps > budget or address not in positions:
            complete = False
            break
        index = positions[address]
        ins, state = instructions[index], states[address]
        next_state = transfer(ins, state, fields)
        if ins.mnemonic == "ret":
            returns[address] = state.get("rax")
            continue
        if ins.mnemonic in {"ud2", "int3"}:
            complete = False
            continue
        following = instructions[index + 1].address if index + 1 < len(instructions) else None
        successors = []
        if ins.mnemonic.startswith("j"):
            if not ins.operands or ins.operands[0].type != X86_OP_IMM:
                complete = False
                continue
            successors.append(ins.operands[0].imm)
            if ins.mnemonic != "jmp" and following:
                successors.append(following)
        elif following:
            successors.append(following)
        else:
            complete = False
        for target in successors:
            if target == blocked:
                continue
            if target not in positions:
                complete = False
                continue
            if target not in states:
                states[target] = dict(next_state)
                queue.append(target)
            else:
                merged = {key: value for key, value in states[target].items() if next_state.get(key) == value}
                if "!payload_clobbered" in states[target] or "!payload_clobbered" in next_state:
                    merged["!payload_clobbered"] = ("constant", 1)
                if merged != states[target]:
                    states[target] = merged
                    queue.append(target)
    # Read final merged states, not values observed before the fixed point.
    return states, [states[r].get("rax") for r in returns], complete


def extract_guards(image, command, platform):
    fields = {}
    for field in command.get("population_fields", command.get("fields", [])):
        kind, offset, width, writable = field_layout(field, platform)
        if writable and kind in {"ref", "i32", "u32", "u8", "bool", "i64", "u64"}:
            fields[offset] = {"name": field["name"], "width": width, "kind": kind}
    symbol = image.by_address.get(command.get("is_valid", 0))
    if not symbol or symbol["size"] > 16384:
        return {"guards": [], "unknown_reason": "validator_missing_or_budget"}
    instructions = image.instructions(symbol)
    states, _, complete = analyze(instructions, fields)
    output = []
    comparisons = {"je": "!=", "jz": "!=", "jne": "==", "jnz": "=="}
    for index, ins in enumerate(instructions[:-1]):
        if ins.address not in states or ins.mnemonic not in {"cmp", "test"} or len(ins.operands) != 2:
            continue
        branch = instructions[index + 1]
        if branch.mnemonic not in comparisons or branch.operands[0].type != X86_OP_IMM:
            continue
        left = operand(ins, ins.operands[0], states[ins.address], fields)
        right = operand(ins, ins.operands[1], states[ins.address], fields)
        if ins.mnemonic == "test":
            if left != right:
                continue
            right = ("constant", 0)
        if not left or not right or "field" not in {left[0], right[0]}:
            continue
        target = branch.operands[0].imm
        _, rejected, reject_complete = analyze(instructions, fields, start=target, initial=states[ins.address])
        _, bypass, bypass_complete = analyze(instructions, fields, blocked=ins.address)
        necessary = complete and reject_complete and bypass_complete and bool(rejected) and all(r == ("constant", 0) for r in rejected + bypass)
        output.append({"comparison_rva": ins.address, "branch_rva": branch.address, "reject_rva": target,
                       "left": left, "right": right, "required_operator": comparisons[branch.mnemonic],
                       "bit_width": ins.operands[0].size * 8,
                       "necessity": "proven_rejection_guard" if necessary else "UNKNOWN",
                       "proof": "all_reject_and_bypass_returns_zero" if necessary else "control_flow_not_fully_proven"})
    return {"guards": output, "cfg_complete": complete, "unknown_reason": None if complete else "unresolved_cfg_or_budget"}


def evaluate_guard(guard: dict, values: dict[str, int | bool | str]) -> bool | None:
    if guard["necessity"] != "proven_rejection_guard":
        return None
    def resolve(expression):
        return expression[1] if expression[0] == "constant" else values.get(expression[1])
    left, right = resolve(guard["left"]), resolve(guard["right"])
    if type(left) not in {int, bool} or type(right) not in {int, bool} or guard.get("bit_width") not in {8, 16, 32, 64}:
        return None
    mask = (1 << guard["bit_width"]) - 1
    left, right = int(left) & mask, int(right) & mask
    return left == right if guard["required_operator"] == "==" else left != right
