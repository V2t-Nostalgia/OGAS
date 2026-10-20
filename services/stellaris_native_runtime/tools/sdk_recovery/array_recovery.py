"""Recover reference-array writer arguments by bounded address-origin CFG flow.

This tracks memory LOCATIONS, not stable values, rule predicates or purity.
Calls kill volatile registers; an opaque/ambiguous argument prevents recovery.
"""

from __future__ import annotations

from collections import deque
import re

from capstone.x86 import X86_OP_IMM, X86_OP_MEM, X86_OP_REG
from linux_elf import register

UNKNOWN = frozenset({None})
VOLATILE = {"rax","rcx","rdx","rsi","rdi","r8","r9","r10","r11"}


def argument_locations(instructions, *, budget=4096):
    positions = {i.address:n for n,i in enumerate(instructions)}
    if not instructions:
        return {}, False
    initial = instructions[0].address
    states, pending, steps = {initial:{"rdi":frozenset({("this",0)})}}, deque([initial]), 0
    complete = True
    while pending:
        pc = pending.popleft(); steps += 1
        if steps > budget:
            return states, False
        i = instructions[positions[pc]]; incoming = states[pc]; state = dict(incoming); ops = i.operands
        def value(op, address=False):
            if op.type == X86_OP_IMM:
                return frozenset({("constant",op.imm)})
            if op.type == X86_OP_REG:
                return incoming.get(register(i.reg_name(op.reg)), UNKNOWN)
            if op.type == X86_OP_MEM and not op.mem.index:
                roots = incoming.get(register(i.reg_name(op.mem.base)), UNKNOWN)
                return frozenset(("this",r[1]+op.mem.disp) if address else
                    ("member",r[1]+op.mem.disp,op.size) if r and r[0]=="this" else None for r in roots) if all(r and r[0]=="this" for r in roots) else UNKNOWN
            return UNKNOWN
        assigned = None
        if len(ops)==2 and ops[0].type==X86_OP_REG:
            if i.mnemonic in {"mov","movzx","movsx","movsxd"}:
                assigned = value(ops[1])
            elif i.mnemonic == "lea":
                assigned = value(ops[1],True)
            elif i.mnemonic in {"add","sub"} and ops[1].type==X86_OP_IMM:
                src = incoming.get(register(i.reg_name(ops[0].reg)), UNKNOWN)
                assigned = frozenset(("this",v[1]+ops[1].imm*(1 if i.mnemonic=="add" else -1))
                    if v and v[0]=="this" else None for v in src)
            elif i.mnemonic=="xor" and ops[0].type==ops[1].type==X86_OP_REG and ops[0].reg==ops[1].reg:
                assigned = frozenset({("constant",0)})
            if assigned is not None:
                if ops[0].size < 8 and any(v and v[0]=="this" for v in assigned):
                    assigned = UNKNOWN
                if (ops[1].type==X86_OP_REG and any(v and v[0]=="member" and v[2]>ops[1].size for v in assigned)):
                    assigned = UNKNOWN
        if i.mnemonic == "call":
            for r in VOLATILE:
                state.pop(r,None)
        else:
            for reg in i.regs_access()[1]:
                state.pop(register(i.reg_name(reg)),None)
            if assigned is not None and ops[0].size>=4:
                state[register(i.reg_name(ops[0].reg))] = assigned
        if i.mnemonic.startswith("ret") or i.mnemonic in {"ud2","int3"}:
            continue
        following = instructions[positions[pc]+1].address if positions[pc]+1<len(instructions) else None
        successors = []
        if i.mnemonic.startswith("j"):
            if not ops or ops[0].type!=X86_OP_IMM:
                complete=False; continue
            if ops[0].imm in positions:
                successors.append(ops[0].imm)
            elif i.mnemonic!="jmp":
                complete=False
            if i.mnemonic!="jmp" and following:
                successors.append(following)
        elif following:
            successors.append(following)
        for target in successors:
            if target not in states:
                states[target]=state.copy(); pending.append(target)
                continue
            previous = states[target]
            merged = {r:previous.get(r,UNKNOWN)|state.get(r,UNKNOWN) for r in previous.keys()|state.keys()}
            merged = {r:v if len(v)<=8 else UNKNOWN for r,v in merged.items()}
            if merged != previous:
                states[target]=merged; pending.append(target)
    return states,complete


def proven_pair(state, offset):
    pointer,count = state.get("rdx",UNKNOWN),state.get("rcx",UNKNOWN)
    data,number = ("member",offset+8,8),("member",offset+20,4)
    return (data in pointer and number in count and pointer <= {data,("constant",0)} and
            count <= {number,("constant",0)})


def recover_reference_arrays(image, command, record, native_functions):
    from value_recovery import normal_flow
    symbol = image.by_address.get(command.get("serializer"))
    if not symbol:
        return []
    body,cfg = normal_flow(image,symbol)
    states,complete = argument_locations(body)
    if not complete or not cfg["complete"]:
        return []
    changes,attempts = [],[]
    command["array_recovery_attempts"] = attempts
    factory_arrays = []
    for w in record.get("writes",[]):
        if w.get("value") and w["value"][0]=="rva":
            name = image.target_name(w["value"][1]-16)
            if name.startswith("vtable for CPdxArray<") and 28<=w["offset"]:
                factory_arrays.append({"offset":w["offset"],"type":name.removeprefix("vtable for "),
                                       "initializer_rva":w["evidence_rva"]})
    for field in command.get("population_fields",command["fields"]):
        if field.get("kind")=="reference_array":
            continue
        if "WriteUniformWithSpace<" in field.get("writer",""):
            element = field["writer"].split("WriteUniformWithSpace<",1)[1].split(">(int,",1)[0]
            sources = [a for a in factory_arrays if field.get("evidence_rva") in states and proven_pair(states[field["evidence_rva"]],a["offset"])]
            attempt = {"field":field["name"],"writer_rva":field.get("evidence_rva"),
                "serialized_element_type":element,"factory_arrays":factory_arrays,
                "data_count_bound_arrays":sources,"status":"native_container_population_requires_owned_element_recipe"}
            if len(sources)==1:
                attempt["status"]="native_array_region_bound_but_element_recipe_required"
            elif factory_arrays:
                attempt["status"]="possible_native_projection_requires_temporary_dataflow_proof"
            for array in sources or (factory_arrays if len(factory_arrays)==1 else []):
                typename = array["type"].removeprefix("CPdxArray<").removesuffix(", int>")
                if "*" in typename or "TPdxRef<" in typename:
                    continue
                serializer = next((s for s in image.symbols if s["type"]=="STT_FUNC" and
                    "WriteMembers" in s["raw"] and image.name(s)==typename+"::WriteMembers(CWriter&)"),None)
                if serializer:
                    from linux_elf import extract_serializer
                    ast = extract_serializer(image,serializer,{})
                    attempt["native_element_serializer"] = {"type":typename,"rva":serializer["rva"],
                        "fields":[{"offset":f.get("linux_off"),"kind":f["kind"],"reference_type":f.get("ref"),
                                   "writer":f["writer"],"writer_rva":f["evidence_rva"],"token":f["token"]} for f in ast["fields"]]}
            attempts.append(attempt)
        match = re.search(r"WriteUniformWithSpace<TPdxRef<(\w+)>>\(int, TPdxRef<\1> const\*, int\)",field.get("writer",""))
        if not match or field.get("evidence_rva") not in states:
            continue
        typ = match[1]; array = f"CPdxArray<TPdxRef<{typ}>, int>"
        slots = [w for w in record.get("writes",[]) if w.get("value") and w["value"][0]=="rva" and
                 image.target_name(w["value"][1]-16)=="vtable for "+array and
                 28<=w["offset"] and w["offset"]+24<=command["size"] and
                 proven_pair(states[field["evidence_rva"]],w["offset"])]
        insert = native_functions.get(f"TPdxRef<{typ}>& {array}::InsertAtEmplace<>(int)")
        if len(slots)!=1 or not insert:
            continue
        field.update(kind="reference_array",ref=typ,linux_off=slots[0]["offset"],native_size=24,
            confidence="direct_dataflow",assignment_rva=insert["rva"],
            value_recovery={"kind":"native_array_vptr_data_count_to_typed_serializer_arguments",
                "array_init_rva":slots[0]["evidence_rva"],"writer_rva":field["evidence_rva"],
                "assignment_rva":insert["rva"],"null_empty_branch_allowed":True})
        changes.append({"class":command["class"],"field":field["name"],"reference_type":typ,"offset":slots[0]["offset"]})
        attempts[-1]["status"]="reference_array_recovered"
    return changes
