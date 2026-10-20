"""Stage 2: resolve Windows layouts for every serializer indexed from the Linux build.

Inputs : out/linux_index.json (stage 1), the installed stellaris.exe (static, game not needed).
Output : out/win_layouts.json

Method (all anchors survive patches; nothing here is a hard-coded address except the
exe path):
  * token names   : every `lea r8,"name"; mov edx,TOKEN; call RegisterToken` in .text
  * WriteToken fn : most frequent call target right after `mov edx, <known token>`
  * fn matching   : commands -> vtable slot 20 of the registered command (by class name);
                    everything else -> token-set fingerprint vs. the Linux serializer
  * field disp    : register-alias tracking of `this` around each token event
  * this adjust   : WriteMembers is a virtual of a (secondary) CPersistent base; the
                    constructor stores that vtable at [obj+X], so object offset = X + disp
  * sub-objects   : calls to other matched serializers with rcx = this+disp
"""
# SPDX-FileCopyrightText: 2026 Yidhar
# SPDX-License-Identifier: MIT
# OGAS changes: explicit, isolated input/output paths; see ../README.md.
import bisect
import collections
import json
import os
import re
import struct
import sys
from pathlib import Path

import pefile
from capstone import CS_ARCH_X86, CS_MODE_64, Cs
from capstone.x86 import X86_OP_IMM, X86_OP_MEM, X86_OP_REG

ROOT = Path(__file__).resolve().parents[2]
EXE = Path(os.environ["IAG_SDK_WINDOWS_EXE"])
OUT_DIR = Path(os.environ["IAG_SDK_WORK_DIR"])
LINUX = OUT_DIR / "linux_index.json"
LINUX_TOKENS = OUT_DIR / "linux_tokens.json"

NEWLINE_TOKEN = 0x10  # `mov edx,0x10; call` terminates a key=value pair
VOLATILE = {"rax", "rcx", "rdx", "r8", "r9", "r10", "r11"}


class Image:
    def __init__(self, path):
        self.pe = pefile.PE(str(path), fast_load=True)
        self.ib = self.pe.OPTIONAL_HEADER.ImageBase
        self.img = bytes(self.pe.get_memory_mapped_image())
        self.timestamp = self.pe.FILE_HEADER.TimeDateStamp
        secs = {s.Name.rstrip(b"\0").decode(): s for s in self.pe.sections}
        t, r = secs[".text"], secs[".rdata"]
        self.text0, self.text1 = t.VirtualAddress, t.VirtualAddress + t.Misc_VirtualSize
        self.rdata0, self.rdata1 = r.VirtualAddress, r.VirtualAddress + r.Misc_VirtualSize
        p = secs[".pdata"]
        raw = self.img[p.VirtualAddress:p.VirtualAddress + p.Misc_VirtualSize]
        entries = {struct.unpack_from("<III", raw, i) for i in range(0, len(raw) - 11, 12)}
        rf = sorted({(a, b) for a, b, _ in entries} - {(0, 0)})
        self.fstarts = [a for a, _ in rf]
        self.fend = dict(rf)
        self.unwind = {a: u for a, _, u in entries}
        self.md = Cs(CS_ARCH_X86, CS_MODE_64)
        self.md.detail = True
        self._lea = None

    def fn_of(self, rva):
        i = bisect.bisect_right(self.fstarts, rva) - 1
        return self.fstarts[i] if i >= 0 else None

    def primary(self, f):
        """The function a .pdata fragment belongs to: MSVC splits a function into chained entries
        (UNW_FLAG_CHAININFO), whose unwind info ends with the parent's RUNTIME_FUNCTION."""
        for _ in range(8):
            ui = self.unwind.get(f)
            if not ui or ui + 4 > len(self.img):
                return f
            flags, count = self.img[ui] >> 3, self.img[ui + 2]
            if not flags & 0x4:
                return f
            parent = struct.unpack_from("<I", self.img, ui + 4 + ((count + 1) & ~1) * 2)[0]
            if not parent or parent == f:
                return f
            f = parent
        return f

    def q(self, rva):
        return struct.unpack_from("<Q", self.img, rva)[0]

    def disasm_fn(self, start, limit=0x4000):
        """Linear sweep that follows forward branches: MSVC splits hot/cold parts of a
        function into several .pdata entries, so the .pdata end is not the real end."""
        out, reach = [], start
        for ins in self.md.disasm(self.img[start:start + limit], self.ib + start):
            rva = ins.address - self.ib
            if rva > start and ins.bytes[0] == 0xCC and rva >= reach:
                break
            out.append(ins)
            if ins.group(7) or ins.mnemonic.startswith("j"):  # jumps
                op = ins.operands[0] if ins.operands else None
                if op is not None and op.type == X86_OP_IMM:
                    t = op.imm - self.ib
                    if start < t < start + limit:
                        reach = max(reach, t)
            if ins.mnemonic in ("ret", "jmp") and rva >= reach:
                break
        return out

    def rip_target(self, ins):
        for op in ins.operands:
            if op.type == X86_OP_MEM and ins.reg_name(op.mem.base) == "rip":
                return ins.address - self.ib + ins.size + op.mem.disp
        return None

    def lea_index(self):
        """rip-relative lea target -> [instruction rva] (vtable starts are always lea'd by ctors)."""
        if self._lea is None:
            idx = collections.defaultdict(list)
            text = self.img[self.text0:self.text1]
            for m in re.finditer(rb"[\x48\x4C]\x8D[\x05\x0D\x15\x1D\x25\x2D\x35\x3D]", text):
                i = m.start()
                disp = struct.unpack_from("<i", text, i + 3)[0]
                idx[self.text0 + i + 7 + disp].append(self.text0 + i)
            self._lea = idx
        return self._lea

    def cstr(self, rva, n=128):
        return self.img[rva:rva + n].split(b"\0")[0].decode("latin1")


def purecall_rva(im):
    """The CRT's _purecall: the pure-virtual filler of abstract vtables (>= 100 .rdata slots),
    `sub rsp; call; test; je; call [handler]; call abort` (same fingerprint as functions.py)."""
    counts = collections.Counter()
    rd = im.img[im.rdata0:im.rdata1]
    for off in range(0, len(rd) - 8, 8):
        v = struct.unpack_from("<Q", rd, off)[0] - im.ib
        if im.text0 <= v < im.text1:
            counts[v] += 1
    want = ["sub", "call", "test", "je", "call", "call"]
    hits = [f for f, n in counts.items() if n >= 100 and f % 16 == 0 and
            [i.mnemonic for i in im.disasm_fn(f, 0x40)[:len(want)]] == want]
    return hits[0] if len(hits) == 1 else None


def find_calls_to(im, target):
    """rva of every `call rel32` to target."""
    out = []
    text = im.img[im.text0:im.text1]
    for m in re.finditer(rb"\xE8", text):
        i = m.start()
        if i + 5 > len(text):
            break
        if im.text0 + i + 5 + struct.unpack_from("<i", text, i + 1)[0] == target:
            out.append(im.text0 + i)
    return out


def token_names(im, known_tokens):
    """Locate RegisterToken via the `mov edx,0xb` / "id" registration, then read every call site."""
    # candidate register fn: call right after `lea r8,"id"; mov edx,0xb`
    reg_fn = None
    for m in re.finditer(rb"\xBA\x0B\x00\x00\x00", im.img[im.text0:im.text1]):
        at = im.text0 + m.start()
        seq = list(im.md.disasm(im.img[at - 7:at + 0x20], im.ib + at - 7))
        if not seq or seq[0].mnemonic != "lea" or im.cstr(im.rip_target(seq[0]) or 0) != "id":
            continue
        for ins in seq:
            if ins.mnemonic == "call" and ins.operands[0].type == X86_OP_IMM:
                reg_fn = ins.operands[0].imm - im.ib
                break
        if reg_fn:
            break
    names = {}
    if not reg_fn:
        return names, None
    # Registration code is huge straight-line init functions: sweep each one from its
    # real start (decoding backwards from a call site desynchronises on x86).
    sites = find_calls_to(im, reg_fn)
    fns = sorted({im.fn_of(c) for c in sites} - {None})
    site_set = set(sites)
    for f in fns:
        end = max(c for c in sites if im.fn_of(c) == f) + 5
        tok = name = None
        for ins in im.md.disasm(im.img[f:end], im.ib + f):
            if ins.mnemonic == "mov" and ins.op_str.startswith("edx, ") and ins.operands[1].type == X86_OP_IMM:
                tok = ins.operands[1].imm
            elif ins.mnemonic == "lea" and ins.op_str.startswith("r8, "):
                t = im.rip_target(ins)
                name = im.cstr(t) if t and im.rdata0 <= t < im.rdata1 else None
            elif ins.mnemonic == "call" and ins.address - im.ib in site_set:
                if tok is not None and name:
                    names.setdefault(tok, name)
                tok = name = None
    return names, reg_fn


def serializer_candidates(im, tokens):
    """fn start -> token multiset, for every function that loads a known token into edx."""
    text = im.img[im.text0:im.text1]
    fn_toks = collections.defaultdict(list)
    for m in re.finditer(rb"\xBA", text):
        i = m.start()
        if i + 5 > len(text):
            break
        v = struct.unpack_from("<I", text, i + 1)[0]
        if v in tokens and v > 0x10:
            f = im.fn_of(im.text0 + i)
            if f is not None:
                f = im.primary(f)  # a chained fragment counts for its function
            if f is not None:
                fn_toks[f].append(v)
    return fn_toks


def mem_ops(ins):
    for op in ins.operands:
        if op.type == X86_OP_MEM:
            yield op


_FAMILY = {}
for _r64, _subs in {
    "rax": "eax ax al", "rbx": "ebx bx bl", "rcx": "ecx cx cl", "rdx": "edx dx dl",
    "rsi": "esi si sil", "rdi": "edi di dil", "rbp": "ebp bp bpl", "rsp": "esp sp spl",
    **{f"r{n}": f"r{n}d r{n}w r{n}b" for n in range(8, 16)},
}.items():
    _FAMILY[_r64] = _r64
    for _s in _subs.split():
        _FAMILY[_s] = _r64


def fam(name):
    return _FAMILY.get(name, name)


def regs_rw(ins):
    try:
        r, w = ins.regs_access()
    except Exception:
        return set(), set()
    return {fam(ins.reg_name(x)) for x in r}, {fam(ins.reg_name(x)) for x in w}


_helper_tokens = {}


def writer_helper_token(im, fn, known_tokens):
    """The key a writer helper writes itself: `mov edx, TOKEN` then a call in its first instructions."""
    if fn not in _helper_tokens:
        _helper_tokens[fn] = None
        if im.text0 <= fn < im.text1:
            ins = im.disasm_fn(fn, 0x100)[:16]
            for a, b in zip(ins, ins[1:]):
                if a.mnemonic == "mov" and a.op_str.startswith("edx, 0x") and b.mnemonic == "call":
                    tok = int(a.op_str.split(", ")[1], 16)
                    _helper_tokens[fn] = tok if tok in known_tokens else None
                    break
    return _helper_tokens[fn]


def extract_fields(im, fn, known_tokens, newline_fn):
    """Token events and `this`-relative references of one Windows serializer."""
    insns = im.disasm_fn(fn, 0x20000)
    alias = {"rcx"}          # registers currently holding `this`
    derived = {}             # reg -> disp it was loaded from ([this+disp]) for indirect fields
    events, refs, calls = [], [], []
    last_edx_imm = None
    # Big serializers spill `this` to its home slot, call __chkstk, and reload it
    # through rbp later: track entry-relative stack addresses to follow it.
    sp = {"rsp": 0}          # reg -> value relative to rsp at entry
    this_slots = set()
    last_eax = None

    def stack_addr(op, ins_):
        b = ins_.reg_name(op.mem.base) if op.mem.base else None
        if b in sp and op.mem.index == 0:
            return sp[b] + op.mem.disp
        return None

    for n, ins in enumerate(insns):
        mnem = ins.mnemonic
        ops = ins.operands
        # --- stack pointer bookkeeping -------------------------------------
        if mnem == "push":
            sp["rsp"] -= 8
        elif mnem == "pop":
            sp["rsp"] += 8
        elif mnem in ("sub", "add") and len(ops) == 2 and ops[0].type == X86_OP_REG and ins.reg_name(ops[0].reg) == "rsp":
            amt = ops[1].imm if ops[1].type == X86_OP_IMM else (last_eax if ops[1].type == X86_OP_REG and ins.reg_name(ops[1].reg) == "rax" else None)
            if amt is not None:
                sp["rsp"] += -amt if mnem == "sub" else amt
        if mnem == "mov" and len(ops) == 2 and ops[0].type == X86_OP_REG and ins.reg_name(ops[0].reg) == "eax" and ops[1].type == X86_OP_IMM:
            last_eax = ops[1].imm
        if len(ops) == 2 and ops[0].type == X86_OP_REG:
            d = ins.reg_name(ops[0].reg)
            if d != "rsp":
                if mnem == "mov" and ops[1].type == X86_OP_REG and ins.reg_name(ops[1].reg) in sp:
                    sp[d] = sp[ins.reg_name(ops[1].reg)]
                elif mnem == "lea" and ops[1].type == X86_OP_MEM and stack_addr(ops[1], ins) is not None:
                    sp[d] = stack_addr(ops[1], ins)
                elif d in sp and not (mnem == "mov" and ops[1].type == X86_OP_MEM and stack_addr(ops[1], ins) in this_slots):
                    sp.pop(d, None)
        # spill / reload of `this`
        if mnem == "mov" and len(ops) == 2:
            if ops[0].type == X86_OP_MEM and ops[1].type == X86_OP_REG and ins.reg_name(ops[1].reg) in alias:
                a = stack_addr(ops[0], ins)
                if a is not None:
                    this_slots.add(a)
            elif ops[0].type == X86_OP_REG and ops[1].type == X86_OP_MEM:
                a = stack_addr(ops[1], ins)
                if a is not None and a in this_slots:
                    alias.add(ins.reg_name(ops[0].reg))
                    derived.pop(ins.reg_name(ops[0].reg), None)
                    continue
        # memory references relative to this (or to a pointer loaded from this)
        dst_reg = fam(ins.reg_name(ops[0].reg)) if ops and ops[0].type == X86_OP_REG and mnem not in ("cmp", "test") else None
        for op in mem_ops(ins):
            base = ins.reg_name(op.mem.base) if op.mem.base else None
            common = {"i": n, "mnem": mnem, "dst": dst_reg, "cmp": mnem in ("cmp", "test")}
            if base in alias and op.mem.index == 0:
                refs.append({**common, "disp": op.mem.disp, "size": op.size, "lea": mnem == "lea", "ind": None})
            elif base in derived and op.mem.index == 0:
                refs.append({**common, "disp": derived[base], "size": 8, "lea": False, "ind": op.mem.disp})
        # track mov edx, imm
        if mnem == "mov" and len(ops) == 2 and ops[0].type == X86_OP_REG and ins.reg_name(ops[0].reg) == "edx" and ops[1].type == X86_OP_IMM:
            last_edx_imm = (ops[1].imm, n)
        # the last field is often written by a tail jump into the writer after the epilogue
        # (`mov edx, TOKEN; mov rcx, rdi; mov rbx, [rsp+x]; add rsp, y; pop rdi; jmp Write`)
        tail = (mnem == "jmp" and ops and ops[0].type == X86_OP_IMM and last_edx_imm
                and n - last_edx_imm[1] <= 6
                and all(b.mnemonic in ("mov", "add", "pop") for b in insns[last_edx_imm[1] + 1:n])
                # an epilogue, not `mov edx, TOKEN; jmp shared_write` inside the function
                and any(b.mnemonic == "pop" or b.op_str.startswith("rsp, ") for b in insns[last_edx_imm[1] + 1:n]))
        # a writer helper that emits its own key (`WriteUniform<T>(writer, array)` inlined with the
        # token: `mov edx, TOKEN; call WriteToken` at its start), also reached by a tail jump
        helper_tok = None
        if mnem in ("call", "jmp") and ops and ops[0].type == X86_OP_IMM and not last_edx_imm:
            helper_tok = writer_helper_token(im, ops[0].imm - im.ib, known_tokens)
            if mnem == "jmp" and not any(b.mnemonic == "pop" or b.op_str.startswith("rsp, ")
                                         for b in insns[max(0, n - 6):n]):
                helper_tok = None
        if mnem == "call" or tail or helper_tok:
            tgt = ops[0].imm - im.ib if ops and ops[0].type == X86_OP_IMM else None
            if last_edx_imm and n - last_edx_imm[1] <= (6 if tail else 3):
                tok = last_edx_imm[0]
                # the "newline" helper is really a generic WriteToken(char/token): small values
                # are punctuation (0x10 newline, 0x3 '=' ...), real field tokens are keys
                if tok == NEWLINE_TOKEN or (tgt == newline_fn and tok < 0x20):
                    events.append({"i": n, "kind": "nl"})
                elif tok in known_tokens:
                    events.append({"i": n, "kind": "tok", "token": tok, "call": tgt})
            else:
                # possible sub-object serializer call: rcx = this+disp
                rcx_disp = None
                for back in insns[max(0, n - 4):n][::-1]:
                    if back.op_str.startswith("rcx, "):
                        if back.mnemonic == "mov" and back.op_str.split(", ")[1] in alias:
                            rcx_disp = 0
                        elif back.mnemonic == "lea":
                            mo = next(mem_ops(back), None)
                            if mo is not None and back.reg_name(mo.mem.base) in alias:
                                rcx_disp = mo.mem.disp
                        break
                if tgt is not None and rcx_disp is not None:
                    calls.append({"i": n, "target": tgt, "disp": rcx_disp})
                elif helper_tok is not None:
                    events.append({"i": n, "kind": "tok", "token": helper_tok, "call": tgt})
            last_edx_imm = None
            nxt_ins = insns[n + 1] if n + 1 < len(insns) else None
            if nxt_ins is not None and nxt_ins.mnemonic == "sub" and nxt_ins.op_str == "rsp, rax":
                continue  # __chkstk stack probe: preserves argument registers
            for r in VOLATILE:
                alias.discard(r)
                derived.pop(r, None)
            continue
        # register dataflow for `this` aliases
        if mnem in ("mov", "lea") and len(ops) == 2 and ops[0].type == X86_OP_REG:
            dst = ins.reg_name(ops[0].reg)
            if ops[1].type == X86_OP_REG and ins.reg_name(ops[1].reg) in alias and mnem == "mov":
                alias.add(dst)
                derived.pop(dst, None)
                continue
            src_mem = ops[1] if ops[1].type == X86_OP_MEM else None
            alias.discard(dst)
            derived.pop(dst, None)
            if mnem == "mov" and src_mem is not None and src_mem.size == 8 and src_mem.mem.index == 0 \
                    and ins.reg_name(src_mem.mem.base) in alias | {dst}:
                if ins.reg_name(src_mem.mem.base) in alias or dst in alias:
                    derived[dst] = src_mem.mem.disp
        elif ops and ops[0].type == X86_OP_REG and mnem not in ("cmp", "test", "push"):
            dst = ins.reg_name(ops[0].reg)
            if dst in alias and mnem not in ("mov",):
                alias.discard(dst)
    return events, refs, calls, insns


ARG_REGS = {"rdx", "r8", "r9"}


def enum_switch(insns, i, nxt_i, R):
    """The value loaded into R at insns[i] is switched on (test/cmp/sub R first) to pick token
    constants (`mov reg, imm` with an imm in token range) before the next key is written."""
    between = insns[i + 1:nxt_i]
    first = None
    for b in between:
        rd, wr = regs_rw(b)
        if b.mnemonic == "call" or (R in wr and R not in rd):
            return False  # the loaded value is gone (a call or another load) before any switch on it
        if R in rd:
            first = b
            break
    # switched on as a value (`test ecx, ecx` / `cmp ecx, 5` / `sub ecx, 1`), not used as a pointer
    if (first is None or first.mnemonic not in ("test", "cmp", "sub") or first.operands[0].type != X86_OP_REG
            or fam(first.reg_name(first.operands[0].reg)) != R):
        return False
    return sum(1 for b in between if b.mnemonic == "mov" and len(b.operands) == 2
               and b.operands[1].type == X86_OP_IMM and b.operands[1].imm >= 0x100) >= 2


def assign_offsets(events, refs, insns, kinds, indirect=None):
    """Pair each token event with the this-reference that carries its value.

    MSVC shapes seen in serializers:
      post load  : WriteToken(tok); mov edx,[this+d]; WriteValue
      pre load   : mov edi,[this+d]; [cmp; je]; WriteToken(tok); mov edx,edi; WriteValue
      direct kv  : mov r8,[this+d]; mov edx,tok; call WriteKV
      wrapper    : lea rax,[this+d]; mov [rsp+x],rax; WriteToken(tok); call wrapper->Write
      sentinel   : cmp [this+d],-1; je skip; WriteToken(tok); ...
      enum token : mov ecx,[this+d]; test ecx,ecx; je; sub ecx,1; ... mov ebx,TOKEN_k; WriteToken(tok);
                   mov edx,ebx (EnumToToken switched into a register before the key is written)
    """
    toks = [e for e in events if e["kind"] == "tok"]
    all_calls = sorted(e["i"] for e in events)
    owner = {}
    for r in refs:
        i = r["i"]
        nxt = next((e for e in toks if e["i"] > i), None)
        prv = next((e for e in reversed(toks) if e["i"] < i), None)
        nl_between_prev = prv is not None and any(e["kind"] == "nl" and prv["i"] < e["i"] < i for e in events)
        belongs_next = False
        as_arg = False
        if nxt is not None:
            if r["cmp"]:
                belongs_next = True
            elif r["dst"] and enum_switch(insns, i, nxt["i"], r["dst"]):
                belongs_next = True
            elif r["dst"]:
                R = r["dst"]
                # value register consumed by the next token's writer (arg) or right after it
                clobbered = False
                for ins in insns[i + 1:nxt["i"]]:
                    rd, wr = regs_rw(ins)
                    if R in wr:
                        clobbered = True
                        break
                if not clobbered and R in ARG_REGS:
                    belongs_next = True
                    # direct kv: `lea/mov r8|r9, [this+d]; mov edx, TOKEN; call` hands the value
                    # straight to the writer, which beats any load that follows the call
                    # (register moves such as saving `this` may sit in between: `lea r8, [rcx+d];
                    # mov rbx, rcx; mov edx, TOKEN; mov rcx, rdi; call`)
                    between = insns[i + 1:nxt["i"]]
                    as_arg = (R in ("r8", "r9") and 1 <= len(between) <= 3
                              and any(b.op_str == f"edx, {hex(nxt['token'])}" for b in between)
                              and all(b.mnemonic == "mov" and not b.op_str.startswith(R + ",")
                                      and (b.op_str.startswith("edx, ")
                                           or (len(b.operands) == 2 and b.operands[1].type == X86_OP_REG))
                                      for b in between))
                elif not clobbered:
                    for ins in insns[nxt["i"] + 1:nxt["i"] + 8]:
                        rd, wr = regs_rw(ins)
                        if R in rd:
                            belongs_next = True
                            break
                        if R in wr:
                            break
                if not belongs_next and r["lea"]:
                    # lea into a register that is spilled to the stack => wrapper object
                    for ins in insns[i + 1:i + 3]:
                        if ins.mnemonic == "mov" and ins.op_str.startswith("qword ptr [rsp") and ins.op_str.endswith(R):
                            belongs_next = True
                            break
        if as_arg:
            owner[i] = ("arg", nxt["i"])            # the writer's own argument register
        elif belongs_next:
            owner[i] = ("pre", nxt["i"])            # proven by data flow / sentinel
        elif prv is not None and not nl_between_prev:
            owner[i] = ("post", prv["i"])
        elif nxt is not None:
            owner[i] = ("pre_default", nxt["i"])    # only positional evidence
    out = []
    indirect = indirect or [False] * len(kinds)
    for ev, kind, ind in zip(toks, kinds, indirect):
        mine = [r for r in refs if owner.get(r["i"], (None, None))[1] == ev["i"]]
        post = [r for r in mine if owner[r["i"]][0] == "post"]
        arg = [r for r in mine if owner[r["i"]][0] == "arg"]
        pre = [r for r in mine if owner[r["i"]][0] == "pre"]
        pre_default = [r for r in mine if owner[r["i"]][0] == "pre_default"]
        pick = where = None
        if kind == "string" and ind:
            # Linux writes the key of an object the field points to: the Windows reference is a
            # load through [this+d] (derived), not a lea of an embedded string
            # (the key is read right after the token is written; derived refs before it are the
            # previous field's tail, e.g. CDeposit writes type then swap_type the same way)
            through = [r for r in post if r["ind"] is not None and not r["cmp"]]
            if through:
                pick, where = through[0], "load"
        if kind == "string" and pick is None:
            leas = [r for r in mine if r["lea"] and r["ind"] is None]
            loads = [r for r in mine if not r["cmp"]]
            if leas:
                pick, where = leas[0], "lea"
            elif loads:
                pick, where = loads[0], "load"
        if pick is None:
            post_ld = [r for r in post if not r["cmp"]]
            pre_ld = [r for r in pre if not r["cmp"]]
            sentinel = [r for r in pre if r["cmp"]]
            for cand, w in ((arg, "arg"), (post_ld, "post"), (pre_ld, "pre"), (sentinel, "sentinel"),
                            (pre_default, "positional"), (post, "post")):
                if cand:
                    pick, where = (cand[0] if w == "post" else cand[-1]), w
                    break
        out.append({"token": ev["token"], "ref": pick, "where": where, "writer_call": ev["call"]})
    return out


def command_serializers(im, names, linux_cmd_classes, purecall):
    """{Linux command class: its Windows WriteCommandMembers} from the image alone: a command's vtable
    has `mov eax, TOKEN; ret` in slot 10 (GetToken) and the CCommand base's slot 2, its token's name
    is the class name in snake case (research_technology_command -> CResearchTechnologyCommand), and
    slot 20 is the serializer. A prototype's slot 20 is _purecall and is skipped; a class whose
    vtables disagree is left to the token matching."""
    tok_vts = []
    for vt in im.lea_index():
        if not (im.rdata0 <= vt < im.rdata1):
            continue
        s10 = im.q(vt + 10 * 8) - im.ib
        if not (im.text0 <= s10 < im.text1):
            continue
        b = im.img[s10:s10 + 6]
        if b[0] == 0xB8 and b[5] == 0xC3:
            tok_vts.append((struct.unpack_from("<I", b, 1)[0], vt))
    base2 = collections.Counter(im.q(vt + 2 * 8) for t, vt in tok_vts
                                if names.get(t, "").endswith("command")).most_common(1)
    if not base2:
        return {}
    found = collections.defaultdict(set)
    for t, vt in tok_vts:
        if im.q(vt + 2 * 8) != base2[0][0] or not names.get(t):
            continue
        camel = "C" + "".join(p[:1].upper() + p[1:] for p in names[t].split("_") if p)
        for guess in (camel, camel + "Command", camel.removesuffix("Command")):
            if guess in linux_cmd_classes:
                s20 = im.q(vt + 20 * 8) - im.ib
                if s20 != purecall and im.text0 <= s20 < im.text1:
                    found[guess].add(s20)
                break
    return {cls: fns.pop() for cls, fns in found.items() if len(fns) == 1}


def this_adjust(im, fn):
    """Offset at which the ctor stores the vtable that contains fn (the CPersistent sub-object)."""
    lea = im.lea_index()
    # the lea targets sorted once: the vtable holding a slot is the nearest one at or below it
    # (a scan of every target per slot took hours where a function sits in many vtables)
    if getattr(im, "_lea_sorted", None) is None:
        im._lea_sorted = sorted(lea)
    keys = im._lea_sorted
    pat = struct.pack("<Q", im.ib + fn)
    results = collections.Counter()
    vts = []
    pos = im.img.find(pat, im.rdata0)
    while pos != -1 and pos < im.rdata1:
        k = bisect.bisect_right(keys, pos) - 1
        if k >= 0 and keys[k] >= pos - 0x800:
            vt = keys[k]
            vts.append((vt, (pos - vt) // 8))
            for r in lea[vt]:
                for ins in im.md.disasm(im.img[r:r + 0x40], im.ib + r):
                    if ins.mnemonic == "mov" and ins.operands and ins.operands[0].type == X86_OP_MEM \
                            and ins.operands[1].type == X86_OP_REG and ins.reg_name(ins.operands[1].reg) == "rax":
                        results[ins.operands[0].mem.disp] += 1
                        break
        pos = im.img.find(pat, pos + 1)
    if not results:
        return None, vts
    top, n = results.most_common(1)[0]
    if n * 3 >= sum(results.values()) * 2:  # one dominant store offset: a real class layout
        return top, vts
    # Stored at many different offsets: a value type embedded in many parents (STradeData
    # lives at +0x20 of market commands, +0x08 of SMonthlyTradeData, ...). Its own ctor
    # stores the vtable at +0, so offsets are relative to the struct itself.
    if 0 in results:
        return 0, vts
    return None, vts


def build_fields(im, fn, linux_fields, known_tokens, names, newline_fn):
    """Fields of one serializer: Windows token events paired with the Linux fields (same tokens, in
    order). win_disp is relative to the serializer's `this`; the caller adds the this-adjust."""
    events, refs, calls, insns = extract_fields(im, fn, known_tokens, newline_fn)
    cls = {"fields": linux_fields}
    # kind per Windows token event, taken from the Linux field with the same token (in order)
    lk = collections.defaultdict(list)
    for lf in cls["fields"]:
        lk[lf["token"]].append((lf["kind"], lf.get("indirect", False)))
    kinds_ind = [lk[e["token"]].pop(0) if lk.get(e["token"]) else (None, False)
                 for e in events if e["kind"] == "tok"]
    pairs = assign_offsets(events, refs, insns, [k for k, _ in kinds_ind], [i for _, i in kinds_ind])
    # align Linux fields to Windows events by token, in order
    pool = collections.defaultdict(list)
    for p in pairs:
        pool[p["token"]].append(p)
    fields = []
    for lf in cls["fields"]:
        p = pool[lf["token"]].pop(0) if pool.get(lf["token"]) else None
        r = p["ref"] if p else None
        disp = r["disp"] if r else None
        fields.append({
            "token": lf["token"],
            "name": names.get(lf["token"]),
            "kind": lf["kind"],
            "ref": lf["ref"],
            "linux_off": lf["linux_off"],
            "linux_indirect": lf.get("indirect", False),
            "win_disp": disp,
            "indirect_off": r["ind"] if r else None,
            "size": r["size"] if r else None,
            "found": p is not None,
            "evidence": p["where"] if p else None,
        })
    return fields, calls


def remap_linux_tokens(linux, names):
    """Rewrite the decompile's token numbers to this exe's, by name (linux_tokens.json holds the
    decompile build's names). A patch that registers new tokens shifts the numbers of every token
    after them (4.5.2 added 10 and moved 4141), while names stay. Tokens without a name in either
    table keep their number. Returns (tokens renumbered, tokens named in both)."""
    ref = {int(k, 16): v for k, v in json.loads(LINUX_TOKENS.read_text(encoding="utf-8"))["tokens"].items()}
    by_name = {v: k for k, v in names.items()}
    remap = {t: by_name[n] for t, n in ref.items() if n in by_name}
    for v in linux.values():
        for f in v["fields"]:
            f["token"] = remap.get(f["token"], f["token"])
    return sum(1 for t, w in remap.items() if t != w), len(remap)


def main():
    linux = json.loads(LINUX.read_text(encoding="utf-8"))
    im = Image(EXE)

    names, reg_fn = token_names(im, set())
    print(f"token names: {len(names)} (RegisterToken=0x{reg_fn or 0:X})")
    moved, both = remap_linux_tokens(linux, names)
    print(f"decompile tokens renumbered to this exe by name: {moved} of {both}")
    # the decompile's classes with this exe's token numbers, for the later stages
    (OUT_DIR / "linux_index_win.json").write_text(json.dumps(linux, indent=1), encoding="utf-8")
    known = {f["token"] for v in linux.values() for f in v["fields"]}

    cands = serializer_candidates(im, known)
    # token-registration init functions mention every token; never serializers
    for f in {im.fn_of(c) for c in find_calls_to(im, reg_fn)} if reg_fn else ():
        cands.pop(f, None)
    slot20_stub = purecall_rva(im)
    cmd_fn = command_serializers(im, names, {v["class"] for v in linux.values() if v["method"] == "WriteCommandMembers"},
                                 slot20_stub)
    # WriteToken / newline helpers: most common call targets after mov edx,imm
    # OGAS: vote within already identified command writers. A wider ELF index
    # otherwise admits unrelated calls in the first 400 token-bearing functions.
    tgt_counter, nl_counter = collections.Counter(), collections.Counter()
    for f in sorted(set(cmd_fn.values())):
        ins = im.disasm_fn(f, 0x800)
        for n, i in enumerate(ins[:-3]):
            if i.mnemonic == "mov" and i.op_str.startswith("edx, 0x"):
                for j in ins[n + 1:n + 4]:
                    if j.mnemonic == "call" and j.operands[0].type == X86_OP_IMM:
                        (nl_counter if i.op_str == "edx, 0x10" else tgt_counter)[j.operands[0].imm - im.ib] += 1
                        break
    write_token_fn = tgt_counter.most_common(1)[0][0]
    newline_fn = nl_counter.most_common(1)[0][0]
    print(f"WriteToken=0x{write_token_fn:X} newline=0x{newline_fn:X} candidates={len(cands)}")

    # ---- function matching -------------------------------------------------
    print(f"command serializers by token name: {len(cmd_fn)}")
    by_token = collections.defaultdict(set)
    for f, toks in cands.items():
        for t in set(toks):
            by_token[t].add(f)
    tok_freq = collections.Counter(t for toks in cands.values() for t in set(toks))

    matched = {}
    for key, cls in linux.items():
        L = {f["token"] for f in cls["fields"]}
        if not L:
            continue
        name = cls["class"]
        if cls["method"] == "WriteCommandMembers" and name in cmd_fn:
            matched[key] = {"fn": cmd_fn[name], "how": "cmd-vtable", "score": 1.0}
            continue
        rare = min(L, key=lambda t: tok_freq.get(t, 1 << 30))
        scored = []
        for f in by_token.get(rare, ()):
            W = set(cands[f])
            recall = len(L & W) / len(L)
            precision = len(L & W) / len(W)
            scored.append((recall * (0.5 + 0.5 * precision), recall, f))
        if not scored:
            continue
        scored.sort(reverse=True)
        best = scored[0]
        ambiguous = len(scored) > 1 and scored[1][0] >= best[0] - 1e-9 and len(L) <= 2
        if best[1] >= 0.6:
            matched[key] = {"fn": best[2], "how": "fingerprint", "score": round(best[0], 3),
                            "ambiguous": ambiguous}

    # ---- per-function extraction ------------------------------------------
    fn_to_key = collections.defaultdict(list)
    for k, m in matched.items():
        fn_to_key[m["fn"]].append(k)
    layouts = {}
    for key, m in matched.items():
        cls = linux[key]
        # every engine-registered token delimits a key, even ones Linux writes via helpers
        fields, calls = build_fields(im, m["fn"], cls["fields"], known | set(names), names, newline_fn)
        adj, vts = this_adjust(im, m["fn"])
        if cls["method"] == "WriteCommandMembers":
            adj = 0  # commands: WriteCommandMembers lives in the primary vtable at [obj+0]
        for f in fields:
            f["win_off"] = (adj + f["win_disp"]) if (f["win_disp"] is not None and adj is not None) else None
        subs = []
        for c in calls:
            for sk in fn_to_key.get(c["target"], []):
                subs.append({"serializer": sk, "win_disp": c["disp"]})
        layouts[key] = {
            "class": cls["class"], "method": cls["method"],
            "win_fn": m["fn"], "match": m["how"], "score": m["score"], "ambiguous": m.get("ambiguous", False),
            "this_adjust": adj, "vtables": [[vt, slot] for vt, slot in vts],
            "fields": fields, "subobjects_raw": subs, "linux_subobjects": cls["subobjects"],
        }

    # sub-object placement: object offset of child = parent_adjust + disp - child_adjust
    for key, lay in layouts.items():
        placed = []
        for s in lay["subobjects_raw"]:
            child = layouts.get(s["serializer"])
            if child and lay["this_adjust"] is not None and child["this_adjust"] is not None:
                placed.append({"class": child["class"], "serializer": s["serializer"],
                               "win_off": lay["this_adjust"] + s["win_disp"] - child["this_adjust"]})
        lay["subobjects"] = placed
        del lay["subobjects_raw"]

    out = {
        "exe": str(EXE), "timestamp": im.timestamp,
        "helpers": {"write_token": write_token_fn, "newline": newline_fn, "register_token": reg_fn},
        "token_names": {str(k): v for k, v in sorted(names.items())},
        "layouts": layouts,
    }
    (OUT_DIR / "win_layouts.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
    nf = sum(len(l["fields"]) for l in layouts.values())
    nfound = sum(1 for l in layouts.values() for f in l["fields"] if f["win_off"] is not None)
    print(f"matched {len(layouts)}/{len(linux)} serializers; fields with Windows offset {nfound}/{nf}")


if __name__ == "__main__":
    main()
