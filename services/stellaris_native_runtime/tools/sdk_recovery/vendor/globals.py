"""Stage 2b: resolve named engine globals (TPdxRef<T>::_pDatabase, TPdxNullObject<T>::_pInstance,
TGameDatabase<X>::_pInstance, ...) on Windows by cross-referencing command methods.

Linux : every method of a command class -> set of global symbols it touches (by name).
Windows: the class-specific slots of the command's vtable -> set of rip-relative .data refs.
For each symbol, the address that co-occurs with it across the most classes (and rarely
without it) wins. No hard-coded addresses: the command vtables are rediscovered by emit_sdk.

Usage: python tools/sdk_dumper/globals.py   (after linux_index, win_extract, emit_sdk)
Output: out/globals.json
"""
# SPDX-FileCopyrightText: 2026 Yidhar
# SPDX-License-Identifier: MIT
# OGAS changes: direct ELF symbol associations replace the decompile dependency.
import collections
import json
import os
import re
import runpy
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
OUT = Path(os.environ["IAG_SDK_WORK_DIR"])
SRC = ROOT / "source" / "stellaris_4.5_source.cpp"

wx = runpy.run_path(str(HERE / "win_extract.py"), run_name="sdk_globals")
Image, EXE, X86_OP_MEM = wx["Image"], wx["EXE"], wx["X86_OP_MEM"]

METHOD = re.compile(r"^/\* ([\w:<>, ]+?)::(\w+)\(.*\) \*/")
END = re.compile(r"^// ============ .* End =+")
# Class singletons/databases (X::_pInstance, TPdxRef<T>::_pDatabase) and plain named globals
# such as g_CurrentGameState.
SYM = re.compile(r"\b((?:TPdxRef|TPdxNullObject|TGameDatabase|TGameDefines|CGameState|CGameApplication|CCountryDatabase|T\w+)(?:<[\w:, <>]+?>)?::_p(?:Database|Instance)\w*|g_[A-Z]\w+)\b")


def linux_symbols(classes):
    associations = json.loads((OUT / "linux_symbol_refs.json").read_text(encoding="utf-8"))
    return {name: set(associations.get(name, [])) for name in classes}


def linux_symbols_from_decompile(classes):
    per_class = collections.defaultdict(set)
    cur = None
    with open(SRC, encoding="utf-8", errors="ignore") as f:
        for line in f:
            if cur is None:
                m = METHOD.match(line)
                if m and m.group(1) in classes:
                    cur = m.group(1)
                continue
            if END.match(line):
                cur = None
                continue
            for s in SYM.findall(line):
                per_class[cur].add(s)
    return per_class


# Databases that a command reads in its ReadCommandMember (vtable slot 21) under a specific
# save token. When one command references several TGameDatabases, voting cannot tell them apart;
# the token branch can: `cmp r8d, <token>; je <branch>`, and the branch loads the database.
TOKEN_BRANCH_HINTS = {
    "TGameDatabase<CGovernmentCivicTypeDatabase>::_pInstance": ("CChangeGovernmentCommand", 0x38DB),
    "TGameDatabase<CGovernmentAuthorityTypeDatabase>::_pInstance": ("CChangeGovernmentCommand", 0x2D24),
}
READ_COMMAND_MEMBER_SLOT = 21


def token_branch_global(im, vtable, token, data0, data1):
    """The first .data global loaded in the ReadCommandMember branch taken for `token`."""
    fn = im.q(vtable + READ_COMMAND_MEMBER_SLOT * 8) - im.ib
    insns = im.disasm_fn(fn, 0x400)
    for n, ins in enumerate(insns):
        if ins.mnemonic == "cmp" and ins.op_str.endswith(hex(token)) and n + 1 < len(insns):
            jmp = insns[n + 1]
            if jmp.mnemonic != "je" or not jmp.op_str.startswith("0x"):
                return None
            for b in im.disasm_fn(int(jmp.op_str, 16) - im.ib, 0x80):
                for op in b.operands:
                    if op.type == X86_OP_MEM and b.reg_name(op.mem.base) == "rip":
                        t = b.address - im.ib + b.size + op.mem.disp
                        if data0 <= t < data1:
                            return t
                if b.mnemonic in ("ret", "jmp"):
                    break
    return None


def main():
    sdk = json.loads((OUT / "sdk.json").read_text(encoding="utf-8"))
    im = Image(EXE)
    data0 = next(s.VirtualAddress for s in im.pe.sections if s.Name.startswith(b".data"))
    data1 = next(s.VirtualAddress + s.Misc_VirtualSize for s in im.pe.sections if s.Name.startswith(b".data"))

    cmds = [c for c in sdk["commands"] if c["class"]]
    slot_use = collections.Counter()
    slots = {}
    for c in cmds:
        fs = [im.q(c["vtable"] + i * 8) - im.ib for i in range(26)]
        slots[c["class"]] = fs
        slot_use.update(set(fs))
    win = {}
    db_shape = collections.Counter()   # address -> loads followed by TPdxRefDatabase access pattern
    gamedb_shape = collections.Counter()  # address -> loads followed by TGameDatabase access (+0x50 items, +0x5c count)
    loads = collections.Counter()
    for c in cmds:
        refs = set()
        for f in slots[c["class"]]:
            if not (im.text0 <= f < im.text1) or slot_use[f] > 3:  # skip shared base-class slots
                continue
            insns = im.disasm_fn(f, 0x3000)
            for n, ins in enumerate(insns):
                for op in ins.operands:
                    if op.type == X86_OP_MEM and ins.reg_name(op.mem.base) == "rip":
                        t = ins.address - im.ib + ins.size + op.mem.disp
                        if data0 <= t < data1:
                            refs.add(t)
                            if ins.mnemonic == "mov" and ins.operands[0].type != X86_OP_MEM:
                                r = ins.reg_name(ins.operands[0].reg)
                                loads[t] += 1
                                window = " | ".join(i.op_str for i in insns[n + 1:n + 18])
                                # capacity check [db+0x20] and slot array [db+0x18]
                                if f"[{r} + 0x20]" in window or f"[{r} + 0x18]" in window:
                                    db_shape[t] += 1
                                if f"[{r} + 0x5c]" in window and f"[{r} + 0x50]" in window:
                                    gamedb_shape[t] += 1
        win[c["class"]] = refs

    lin = linux_symbols(set(win))
    addr_freq = collections.Counter(a for s in win.values() for a in s)
    def is_db(a):
        return loads[a] > 0 and db_shape[a] / loads[a] >= 0.25

    pairs = []
    for sym in sorted({s for v in lin.values() for s in v}):
        with_s = [k for k in win if sym in lin.get(k, ())]
        if not with_s:
            continue
        want_db = sym.startswith("TPdxRef<") and sym.endswith("::_pDatabase")
        want_gamedb = sym.startswith("TGameDatabase<")
        votes = collections.Counter(a for k in with_s for a in win[k])
        for a, n in votes.items():
            # A TGameDatabase load is recognisable by its access pattern, so one referencing
            # class is enough evidence; everything else needs two co-occurrences.
            if want_gamedb and not gamedb_shape[a]:
                continue
            if n < 2 and not want_gamedb:
                continue
            if want_db and not is_db(a):
                continue
            recall = n / len(with_s)
            precision = n / addr_freq[a]
            pairs.append((0 if want_db else 1, recall * precision, sym, a, recall, precision, len(with_s)))
    # One address per symbol and one symbol per address, best evidence first. Databases are
    # placed first: their NullObject twins co-occur in exactly the same functions and would
    # otherwise tie with them.
    result, taken = {}, set()
    by_class = {c["class"]: c for c in cmds}
    for sym, (cls, token) in TOKEN_BRANCH_HINTS.items():
        if cls in by_class:
            a = token_branch_global(im, by_class[cls]["vtable"], token, data0, data1)
            if a is not None and a not in taken:
                result[sym] = {"rva": a, "score": 1.0, "recall": 1.0, "precision": 1.0, "classes": 1,
                               "db_shape": False, "source": f"{cls} token 0x{token:X} branch"}
                taken.add(a)
    cands = collections.defaultdict(list)
    for _, score, sym, a, recall, precision, ncls in sorted(pairs, key=lambda p: (p[0], -p[1])):
        if score >= 0.2 and len(cands[sym]) < 5:
            cands[sym].append(a)
        if score < 0.3 or sym in result or a in taken:
            continue
        result[sym] = {"rva": a, "score": round(score, 3), "recall": round(recall, 3),
                       "precision": round(precision, 3), "classes": ncls, "db_shape": is_db(a)}
        taken.add(a)
    for sym, r in result.items():
        r["candidates"] = cands[sym]  # static ties are settled live by live_verify.py
    (OUT / "globals.json").write_text(json.dumps(result, indent=1), encoding="utf-8")
    print(f"resolved {len(result)} globals from {len(win)} command classes")


if __name__ == "__main__":
    main()
