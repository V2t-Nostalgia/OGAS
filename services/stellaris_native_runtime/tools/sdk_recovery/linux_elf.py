"""Recover serializer fields and command metadata directly from a symbolized ELF.

This is bounded register data flow, not a decompiler. Unknown values remain
unresolved. In particular an object pointer serialized via its key is kept as
an indirect pointer, never relabeled as an inline CString.
"""

from __future__ import annotations

import hashlib
import json
import re
import struct
from collections import defaultdict
from pathlib import Path

import itanium_demangler
from capstone import CS_ARCH_X86, CS_MODE_64, Cs
from capstone.x86 import X86_OP_IMM, X86_OP_MEM, X86_OP_REG
from elftools.elf.elffile import ELFFile


def demangle(name: str) -> str:
    try:
        return str(itanium_demangler.parse(name) or name)
    except (ValueError, IndexError, KeyError, NotImplementedError):
        return name


def register(name: str | None) -> str:
    if name is None:
        return ""
    aliases = {
        "eax": "rax",
        "ax": "rax",
        "al": "rax",
        "edi": "rdi",
        "esi": "rsi",
        "edx": "rdx",
        "ecx": "rcx",
        "ebx": "rbx",
        "ebp": "rbp",
        "esp": "rsp",
        "dil": "rdi",
        "sil": "rsi",
        "dl": "rdx",
        "cl": "rcx",
        "bl": "rbx",
    }
    return aliases.get(name, re.sub(r"^(r\d+)[dwb]$", r"\1", name))


class ElfImage:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.data = path.read_bytes()
        with path.open("rb") as stream:
            elf = ELFFile(stream)
            self.build_id = next(
                (
                    note["n_desc"]
                    for section in elf.iter_sections()
                    if section["sh_type"] == "SHT_NOTE"
                    for note in section.iter_notes()
                    if note["n_type"] == "NT_GNU_BUILD_ID"
                ),
                "",
            )
            self.segments = [
                (int(s["p_vaddr"]), int(s["p_offset"]), int(s["p_filesz"]))
                for s in elf.iter_segments()
                if s["p_type"] == "PT_LOAD"
            ]
            self.debug_sections = [
                s.name for s in elf.iter_sections() if s.name.startswith(".debug_")
            ]
            table = elf.get_section_by_name(".symtab")
            if table is None:
                raise ValueError("Linux ELF has no .symtab")
            self.symbols = [
                {
                    "raw": s.name,
                    "rva": int(s["st_value"]),
                    "size": int(s["st_size"]),
                    "type": s["st_info"]["type"],
                }
                for s in table.iter_symbols()
                if s["st_value"]
            ]
            self.plt_names = {}
            plt = elf.get_section_by_name(".plt")
            relocations = elf.get_section_by_name(".rela.plt")
            if plt is not None and relocations is not None:
                dynamic_symbols = elf.get_section(relocations["sh_link"])
                for index, relocation in enumerate(relocations.iter_relocations()):
                    raw = dynamic_symbols.get_symbol(relocation["r_info_sym"]).name
                    self.plt_names[
                        int(plt["sh_addr"]) + (index + 1) * int(plt["sh_entsize"])
                    ] = demangle(raw)
        self.by_address = {s["rva"]: s for s in self.symbols}
        self.named: dict[str, str] = {}
        self.md = Cs(CS_ARCH_X86, CS_MODE_64)
        self.md.detail = True

    def name(self, symbol: dict) -> str:
        raw = symbol["raw"]
        if raw not in self.named:
            self.named[raw] = demangle(raw)
        return self.named[raw]

    def read(self, rva: int, size: int) -> bytes:
        for start, offset, length in self.segments:
            if start <= rva and rva + size <= start + length:
                return self.data[offset + rva - start : offset + rva - start + size]
        return b""

    def instructions(self, symbol: dict, limit: int = 65536):
        size = min(symbol["size"] or 256, limit)
        return list(self.md.disasm(self.read(symbol["rva"], size), symbol["rva"]))

    def target_name(self, rva: int) -> str:
        s = self.by_address.get(rva)
        return self.name(s) if s else self.plt_names.get(rva, "")


def writer_kind(name: str) -> tuple[str, str | None]:
    match = re.search(r"CWriter::Write<(.+?)>\(", name)
    if match:
        return "ref", match.group(1)
    if "CString" in name:
        return "string", None
    if "CPersistent" in name:
        return "persistent", None
    for typename, kind in (
        ("unsigned long long", "u64"),
        ("long long", "i64"),
        ("unsigned long", "u64"),
        ("long", "i64"),
        ("unsigned int", "u32"),
        ("int", "i32"),
        ("bool", "bool"),
        ("float", "f32"),
        ("unsigned char", "u8"),
    ):
        if re.search(r", " + typename + r"(?: const)?(?:&)?\)", name):
            return kind, None
    return "other", None


def extract_serializer(
    image: ElfImage,
    symbol: dict,
    tokens: dict[int, str],
    *,
    indirect_this_offset: int | None = None,
) -> dict:
    name = image.name(symbol)
    cls, method = name.split("::Write", 1)
    method = "Write" + method.split("(", 1)[0]
    regs: dict[str, tuple] = {
        "rdi": ("address", 0),
        "rsi": ("writer",),
        "rsp": ("stack", 0),
    }
    if indirect_this_offset is not None:
        regs["rdi"] = ("wrapper_address", 0)
    fields, subobjects, pointer_uses = [], [], []
    stack = {}
    pending_bool = None
    bool_guard = None
    instructions = image.instructions(symbol)
    for instruction_index, ins in enumerate(instructions):
        ops = ins.operands
        if bool_guard and ins.address >= bool_guard["end"]:
            bool_guard = None
        if (
            ins.mnemonic == "cmp"
            and len(ops) == 2
            and ops[0].type == X86_OP_MEM
            and ops[0].size == 1
            and ops[1].type == X86_OP_IMM
            and ops[1].imm == 0
        ):
            base = regs.get(register(ins.reg_name(ops[0].mem.base)))
            pending_bool = (
                (base[1] + ops[0].mem.disp, ins.address)
                if base and base[0] == "address" and not ops[0].mem.index
                else None
            )
        elif (
            ins.mnemonic == "je"
            and pending_bool
            and ops[0].type == X86_OP_IMM
            and ins.address < ops[0].imm <= ins.address + 512
        ):
            bool_guard = {
                "offset": pending_bool[0],
                "evidence_rva": pending_bool[1],
                "end": ops[0].imm,
            }
            pending_bool = None
        elif ins.mnemonic not in ("nop", "cmp"):
            pending_bool = None
        if ins.mnemonic in ("call", "jmp") and ops and ops[0].type == X86_OP_IMM:
            callee = image.target_name(ops[0].imm)
            tok, value = regs.get("rsi"), regs.get("rdx")
            receiver = regs.get("rdi")
            enum_result = None
            if "EnumToToken<" in callee and receiver and receiver[0] == "address":
                enum_type = callee.split("EnumToToken<", 1)[1].split(">(", 1)[0]
                enum_result = ("enum", receiver[1], enum_type, ops[0].imm)
            elif receiver and receiver[0] == "value" and receiver[2] in (1, 4):
                # A named converter can take a native enum by value instead of
                # EnumToToken<T>(T const&). Recover the encoded parameter type,
                # actual load width and this-field offset, not its English name.
                target_symbol = image.by_address.get(ops[0].imm)
                try:
                    ast = itanium_demangler.parse(target_symbol["raw"]) if target_symbol else None
                    arguments = [str(p) for p in ast.arg_tys] if ast else []
                except (AttributeError, ValueError, IndexError, KeyError, NotImplementedError):
                    arguments = []
                if (len(arguments) == 1 and re.fullmatch(r"E\w+", arguments[0]) and
                        "::" not in callee.split("(", 1)[0]):
                    enum_result = ("enum_value", receiver[1], arguments[0], ops[0].imm, receiver[2])
            if (
                receiver
                and receiver[0] == "value"
                and receiver[2] == 8
                and "::" in callee
            ):
                owner = callee.split("::", 1)[0].split()[-1]
                if re.fullmatch(r"C\w+", owner):
                    pointer_uses.append(
                        {
                            "offset": receiver[1],
                            "class": owner,
                            "evidence_rva": ins.address,
                        }
                    )
            if (
                ("CWriter::" in callee or "NParserUtil::" in callee)
                and tok
                and tok[0] == "imm"
            ):
                kind, ref = writer_kind(callee)
                off = (
                    value[1]
                    if value
                    and value[0] in ("address", "value", "indirect", "enum", "enum_value", "bit")
                    else None
                )
                wrapper = None
                if kind == "persistent" and value and value[0] == "stack":
                    vptr = stack.get(value[1])
                    wrapped = stack.get(value[1] + 16)
                    if (
                        vptr
                        and vptr[0] == "rva"
                        and wrapped
                        and wrapped[0] == "address"
                    ):
                        wrapper = {
                            "vtable_rva": vptr[1],
                            "type": image.target_name(vptr[1] - 16),
                            "target_offset": wrapped[1],
                        }
                        off = wrapped[1]
                if value and value[0] == "enum":
                    kind = "i32"
                elif value and value[0] == "enum_value":
                    kind = "u8" if value[4] == 1 else "i32"
                if kind == "bool" and value == ("imm", 1) and bool_guard:
                    off = bool_guard["offset"]
                fields.append(
                    {
                        "token": tok[1],
                        "name": tokens.get(tok[1]),
                        "writer": callee,
                        "kind": kind,
                        "ref": ref,
                        "linux_off": off,
                        "off_source": "arg" if off is not None else None,
                        "indirect": bool(
                            value
                            and value[0] in ("value", "indirect")
                            and kind == "string"
                        ),
                        "width": (
                            value[2]
                            if value and value[0] == "value"
                            else 4
                            if kind == "ref"
                            else None
                        ),
                        "evidence_rva": ins.address,
                        "confidence": "direct_dataflow"
                        if off is not None
                        else "unresolved",
                        "arg": "ELF register data flow",
                        "enum_type": value[2] if value and value[0] in {"enum", "enum_value"} else None,
                        "enum_serializer_rva": value[3]
                        if value and value[0] in {"enum", "enum_value"}
                        else None,
                        "wrapper": wrapper,
                        "pointer_key_offset": value[2]
                        if value and value[0] == "indirect"
                        else None,
                        "bit_mask": value[3] if value and value[0] == "bit" else 0,
                        "conditional_bool": dict(bool_guard)
                        if kind == "bool" and value == ("imm", 1) and bool_guard
                        else None,
                    }
                )
            elif (
                "::WriteMembers(" in callee and regs.get("rdi", (None,))[0] == "address"
            ):
                subobjects.append(
                    {
                        "class": callee.split("::WriteMembers", 1)[0],
                        "method": "WriteMembers",
                        "linux_off": regs["rdi"][1],
                    }
                )
            for reg in ("rax", "rcx", "rdx", "rsi", "rdi", "r8", "r9", "r10", "r11"):
                regs.pop(reg, None)
            if enum_result:
                regs["rax"] = enum_result
            continue
        if ins.mnemonic == "push":
            regs["rsp"] = ("stack", regs.get("rsp", ("stack", 0))[1] - 8)
            continue
        if len(ops) == 2 and ops[0].type == X86_OP_MEM and ins.mnemonic == "mov":
            base = regs.get(register(ins.reg_name(ops[0].mem.base)))
            if base and base[0] == "stack" and not ops[0].mem.index:
                source = ops[1]
                val = (
                    regs.get(register(ins.reg_name(source.reg)))
                    if source.type == X86_OP_REG
                    else None
                )
                stack[base[1] + ops[0].mem.disp] = val
            continue
        if not ops or ops[0].type != X86_OP_REG:
            continue
        dest = register(ins.reg_name(ops[0].reg))
        if ins.mnemonic == "pop":
            regs.pop(dest, None)
            regs["rsp"] = ("stack", regs.get("rsp", ("stack", 0))[1] + 8)
            continue
        if len(ops) < 2:
            continue
        source = ops[1]
        if ins.mnemonic in ("mov", "movzx", "movsxd"):
            if source.type == X86_OP_REG:
                regs[dest] = regs.get(register(ins.reg_name(source.reg)), ("unknown",))
            elif source.type == X86_OP_IMM:
                regs[dest] = ("imm", source.imm)
            elif source.type == X86_OP_MEM:
                base = regs.get(register(ins.reg_name(source.mem.base)))
                if (
                    base
                    and base[0] in ("address", "wrapper_address")
                    and not source.mem.index
                ):
                    if (
                        base[0] == "wrapper_address"
                        and base[1] + source.mem.disp == indirect_this_offset
                        and source.size == 8
                    ):
                        regs[dest] = ("address", 0)
                    elif base[0] == "wrapper_address":
                        regs.pop(dest, None)
                    else:
                        regs[dest] = ("value", base[1] + source.mem.disp, source.size)
                elif base and base[0] == "stack" and not source.mem.index:
                    regs[dest] = stack.get(base[1] + source.mem.disp, ("unknown",))
                else:
                    regs.pop(dest, None)
        elif ins.mnemonic == "lea" and source.type == X86_OP_MEM:
            base = regs.get(register(ins.reg_name(source.mem.base)))
            if (
                base
                and base[0] in ("address", "wrapper_address")
                and not source.mem.index
            ):
                regs[dest] = (base[0], base[1] + source.mem.disp)
            elif base and base[0] == "stack" and not source.mem.index:
                regs[dest] = ("stack", base[1] + source.mem.disp)
            elif ins.reg_name(source.mem.base) == "rip":
                regs[dest] = ("rva", ins.address + ins.size + source.mem.disp)
            else:
                regs.pop(dest, None)
        elif ins.mnemonic == "add" and source.type == X86_OP_MEM:
            base = regs.get(register(ins.reg_name(source.mem.base)))
            value = regs.get(dest)
            previous = (
                instructions[instruction_index - 1] if instruction_index else None
            )
            previous_ops = previous.operands if previous else []
            if (
                indirect_this_offset is not None
                and base
                and base[0] == "wrapper_address"
                and not source.mem.index
                and base[1] + source.mem.disp == indirect_this_offset
                and source.size == ops[0].size == 8
                and value
                and value[0] == "imm"
                and 0 <= value[1] <= 65535
                and previous
                and previous.mnemonic == "mov"
                and len(previous_ops) == 2
                and previous_ops[0].type == X86_OP_REG
                and previous_ops[0].size in (4, 8)
                and register(previous.reg_name(previous_ops[0].reg)) == dest
                and previous_ops[1].type == X86_OP_IMM
            ):
                regs[dest] = ("address", value[1])
            else:
                regs.pop(dest, None)
        elif ins.mnemonic in ("add", "sub") and source.type == X86_OP_IMM:
            value = regs.get(dest)
            delta = source.imm if ins.mnemonic == "add" else -source.imm
            if value and value[0] in ("address", "wrapper_address", "stack", "rva"):
                regs[dest] = (value[0], value[1] + delta)
            elif value and value[0] == "value":
                regs[dest] = ("indirect", value[1], source.imm)
        elif ins.mnemonic == "shr" and source.type == X86_OP_IMM:
            value = regs.get(dest)
            if value and value[0] == "value" and 0 <= source.imm < value[2] * 8:
                regs[dest] = ("bit", value[1], value[2], 1 << source.imm)
            else:
                regs.pop(dest, None)
        elif ins.mnemonic == "and" and source.type == X86_OP_IMM:
            value = regs.get(dest)
            if (
                value
                and value[0] == "value"
                and source.imm > 0
                and source.imm & (source.imm - 1) == 0
            ):
                regs[dest] = ("bit", value[1], value[2], source.imm)
            elif value and value[0] == "bit" and source.imm == 1:
                pass
            else:
                regs.pop(dest, None)
        elif (
            ins.mnemonic == "xor"
            and source.type == X86_OP_REG
            and ops[0].reg == source.reg
        ):
            regs[dest] = ("imm", 0)
        elif ins.mnemonic not in ("cmp", "test"):
            regs.pop(dest, None)
    return {
        "class": cls,
        "method": method,
        "fields": fields,
        "subobjects": subobjects,
        "serializer_rva": symbol["rva"],
        "pointer_uses": pointer_uses,
    }


def recover_linux(binary: Path, work: Path, tokens: dict[int, str]) -> dict:
    outputs = ("linux_index.json", "linux_classes.json", "linux_tokens.json", "linux_symbol_refs.json",
               "linux_sdk.json", "linux_constructor_callsites.json")
    if any((work / name).exists() for name in outputs):
        raise FileExistsError("Linux recovery requires new output files; existing evidence is never overwritten")
    from callsite_arguments import apply_callsite_evidence, recover_callsites
    from recovery_plans import enrich_linux

    image = ElfImage(binary)
    serializers = {}
    command_classes = set()
    globals_by_address: dict[int, str] = {}
    for s in image.symbols:
        raw = s["raw"]
        if "WriteMembersE" in raw or "WriteCommandMembersE" in raw:
            name = image.name(s)
            if "::Write" in name and "(CWriter&)" in name and s["type"] == "STT_FUNC":
                entry = extract_serializer(image, s, tokens)
                key = f"{entry['class']}::{entry['method']}"
                if len(entry["fields"]) >= len(
                    serializers.get(key, {}).get("fields", [])
                ):
                    serializers[key] = entry
                if entry["method"] == "WriteCommandMembers":
                    command_classes.add(entry["class"])
        if s["type"] == "STT_OBJECT" and any(
            x in raw
            for x in (
                "_pDatabase",
                "_pInstance",
                "TPdxNullObject",
                "g_CurrentGameState",
            )
        ):
            globals_by_address[s["rva"]] = image.name(s)

    factories = {}
    for symbol in image.symbols:
        if "CommandRegistrator6CreateEv" in symbol["raw"]:
            match = re.search(
                r"CCommandHelper<(.+)>::CommandRegistrator::Create\(\)",
                image.name(symbol),
            )
            if match:
                factories[match.group(1)] = symbol
    commands = []
    refs: dict[str, set[str]] = defaultdict(set)
    for s in image.symbols:
        if not s["raw"].startswith("_ZTV"):
            continue
        cls = image.name(s).removeprefix("vtable for ")
        if cls not in command_classes:
            continue
        slots_raw = image.read(s["rva"] + 16, min(s["size"] - 16, 26 * 8))
        if len(slots_raw) < 16:
            continue
        slots = list(struct.unpack("<" + "Q" * (len(slots_raw) // 8), slots_raw))
        slot_names = [image.target_name(address) for address in slots]

        def slot_containing(text: str, names=slot_names) -> int | None:
            return next((n for n, value in enumerate(names) if text in value), None)

        token_slot = slot_containing("::GetToken")
        valid_slot = slot_containing("::IsValid")
        clone_slot = slot_containing("::Clone")
        token = None
        if token_slot is not None:
            b = image.read(slots[token_slot], 6)
            if len(b) == 6 and b[0] == 0xB8 and b[5] == 0xC3:
                token = struct.unpack_from("<I", b, 1)[0]
        size = None
        allocation_source = factories.get(cls)
        if allocation_source is None and clone_slot is not None:
            allocation_source = image.by_address.get(slots[clone_slot])
        if allocation_source is not None:
            clone = image.instructions(allocation_source, 512)
            for n, ins in enumerate(clone):
                if (
                    ins.mnemonic == "mov"
                    and ins.op_str.startswith("edi, ")
                    and ins.operands[1].type == X86_OP_IMM
                    and any(
                        i.mnemonic == "call"
                        and i.operands[0].type == X86_OP_IMM
                        and "operator new(" in image.target_name(i.operands[0].imm)
                        for i in clone[n + 1 : n + 4]
                    )
                ):
                    size = ins.operands[1].imm
                    break
        for address in set(slots):
            symbol = image.by_address.get(address)
            if not symbol or not image.name(symbol).startswith(cls + "::"):
                continue
            for ins in image.instructions(symbol, 16384):
                for op in ins.operands:
                    if op.type == X86_OP_MEM and ins.reg_name(op.mem.base) == "rip":
                        target = ins.address + ins.size + op.mem.disp
                        if target in globals_by_address:
                            refs[cls].add(globals_by_address[target])
        commands.append(
            {
                "class": cls,
                "token": token,
                "token_name": tokens.get(token),
                "vtable": s["rva"] + 16,
                "size": size,
                "factory": factories[cls]["rva"] if cls in factories else None,
                "serializer": serializers.get(cls + "::WriteCommandMembers", {}).get(
                    "serializer_rva"
                ),
                "is_valid": slots[valid_slot] if valid_slot is not None else None,
                "deleting_destructor": slots[1],
                "token_getter": slots[token_slot] if token_slot is not None else None,
                "slots": {
                    "is_valid": valid_slot,
                    "deleting_destructor": 1,
                    "token": token_slot,
                },
                "fields": serializers.get(cls + "::WriteCommandMembers", {}).get(
                    "fields", []
                ),
                "serializer_subobjects": serializers.get(
                    cls + "::WriteCommandMembers", {}
                ).get("subobjects", []),
            }
        )
    functions = {}
    for s in image.symbols:
        if s["type"] == "STT_FUNC" and any(
            x in s["raw"]
            for x in (
                "PostCommandToSession",
                "CGameIdler4Idle",
                "CCountry19AccessTechnology",
                "CCountry22AccessTechnologyModule",
            )
        ):
            functions[image.name(s)] = {"rva": s["rva"], "evidence": "elf_symbol"}
    result = {
        "schema_version": "iag.recovered_sdk.v1",
        "platform": "linux-x86_64",
        "build_id": image.build_id,
        "sha256": hashlib.sha256(image.data).hexdigest(),
        "dwarf_sections": image.debug_sections,
        "token_name_source": "current_matching_windows_token_registry",
        "commands": sorted(commands, key=lambda c: c["class"]),
        "functions": functions,
        "globals": {
            name: {"rva": address, "evidence": "elf_symbol"}
            for address, name in sorted(globals_by_address.items())
        },
    }
    enrich_linux(image, result, serializers, factories)
    targets = {
        d["constructor_rva"]
        for c in result["commands"]
        for f in c.get("population_fields", [])
        for d in f.get("constructor_parameter_evidence", [])
    }
    result["constructor_callsites"] = recover_callsites(image, targets)
    apply_callsite_evidence(result)
    from value_recovery import refine_catalog
    refine_catalog(image, result, tokens=tokens)
    # Native owning-value copies introduce constructor parameter bindings which
    # share the already indexed constructor callsites, not a second producer API.
    apply_callsite_evidence(result)
    result["recovery_summary"]["verified_constructor_callsites"] = sum(
        r["instruction_verified"] for r in result["constructor_callsites"]
    )
    for command in result["commands"]:
        command["token_name"] = tokens.get(command["token"])
    work.mkdir(parents=True, exist_ok=True)
    for filename, data in (
        ("linux_index.json", serializers),
        ("linux_classes.json", {"execute_classes": sorted(command_classes)}),
        ("linux_tokens.json", {"tokens": {hex(k): v for k, v in tokens.items()}}),
        ("linux_symbol_refs.json", {k: sorted(v) for k, v in refs.items()}),
        ("linux_sdk.json", result),
        ("linux_constructor_callsites.json", result["constructor_callsites"]),
    ):
        (work / filename).write_text(
            json.dumps(data, indent=1, sort_keys=True) + "\n", encoding="utf-8"
        )
    print(
        f"Linux: {len(serializers)} serializers, {len(commands)} commands, {len(globals_by_address)} globals",
        flush=True,
    )
    return result
