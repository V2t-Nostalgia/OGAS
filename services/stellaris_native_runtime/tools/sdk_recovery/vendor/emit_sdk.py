"""Stage 3: turn win_layouts.json into the bridge SDK.

Outputs
  stellaris_bridge/include/sdk/stellaris_sdk.hpp   (generated, do not edit)
  tools/sdk_dumper/out/sdk.json                   (same data, for Python tooling/tests)

Commands are discovered from the exe itself (no hand-maintained table):
  command vtable = lea-referenced .rdata address whose slot 10 is `mov eax, TOKEN; ret`
                   and whose slot 2 is the shared CCommand base serializer
  factory        = smallest function that lea's the vtable and calls the engine allocator
  size           = the allocator argument in that factory
  class name     = Linux class matching the token name (camel-case) or the slot-20 serializer
"""
# SPDX-FileCopyrightText: 2026 Yidhar
# SPDX-License-Identifier: MIT
# OGAS changes: explicit, isolated input/output paths; see ../README.md.
import collections
import json
import os
import re
import runpy
import struct
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
OUT = Path(os.environ["IAG_SDK_WORK_DIR"])
HEADER = OUT / "upstream_reference.hpp"

wx = runpy.run_path(str(HERE / "win_extract.py"), run_name="sdk_emit")
Image, EXE = wx["Image"], wx["EXE"]
X86_OP_IMM = wx["X86_OP_IMM"]

CPP_KEYWORDS = set("""alignas alignof and asm auto bool break case catch char class const constexpr
continue default delete do double else enum explicit export extern false float for friend goto if
inline int long mutable namespace new noexcept not nullptr operator or private protected public
register return short signed sizeof static struct switch template this throw true try typedef
typeid typename union unsigned using virtual void volatile while xor""".split())


def ident(s):
    s = re.sub(r"[^0-9A-Za-z_]", "_", s)
    s = re.sub(r"_+", "_", s).strip("_") or "field"
    if s[0].isdigit():
        s = "_" + s
    return s + "_" if s in CPP_KEYWORDS else s


def camel(token_name):
    return "C" + "".join(p[:1].upper() + p[1:] for p in token_name.split("_") if p)


def copies_from_rcx(ins):
    """True for a function that dereferences its first argument before allocating: rcx saved into a
    register (or used directly) and read through ([R + d]), as a clone or copy constructor does."""
    held = {"rcx"}
    for i in ins[:40]:
        if i.mnemonic == "call":
            held.discard("rcx")  # clobbered by the call; a saved copy (rbx, rdi ...) survives it
            if not held:
                return False
            continue
        if i.mnemonic in ("ret", "jmp"):
            break
        m = re.match(r"^(r\w+), rcx$", i.op_str)
        if i.mnemonic == "mov" and m:
            held.add(m.group(1))
            continue
        for r in held:
            if re.search(r"\[" + r + r"(?: \+ [^\]]+)?\]", i.op_str) and not i.op_str.startswith("qword ptr [rsp"):
                return True
    return False


def discover_commands(im, names, layouts, linux_cmd_classes, newline_fn=None):
    lea = im.lea_index()
    # the decompile's classes with this exe's token numbers (win_extract.py renumbers them by name)
    linux = json.loads((OUT / "linux_index_win.json").read_text(encoding="utf-8"))
    linux_cmd_fields = {v["class"]: v["fields"] for v in linux.values() if v.get("method") == "WriteCommandMembers"}
    known_tokens = {f["token"] for v in linux.values() for f in v["fields"]} | set(names)
    tok_vts = []
    for vt in lea:
        if not (im.rdata0 <= vt < im.rdata1):
            continue
        s10 = im.q(vt + 80) - im.ib
        if not (im.text0 <= s10 < im.text1):
            continue
        b = im.img[s10:s10 + 6]
        if b[0] == 0xB8 and b[5] == 0xC3:
            tok_vts.append((struct.unpack_from("<I", b, 1)[0], vt))
    # CCommand base serializer = most common slot 2 among *_command tokens
    base2 = collections.Counter(im.q(vt + 16) for t, vt in tok_vts
                                if names.get(t, "").endswith("command")).most_common(1)[0][0]
    cmds = [(t, vt) for t, vt in tok_vts if im.q(vt + 16) == base2]

    # engine allocator = majority `mov ecx, imm; call X` inside vtable-referencing functions
    alloc_votes = collections.Counter()
    per_vt_fns = {}
    for t, vt in cmds:
        fns = sorted({im.fn_of(r) for r in lea[vt]} - {None})
        per_vt_fns[vt] = fns
        for f in fns[:3]:
            ins = im.disasm_fn(f, 0x200)
            for n, i in enumerate(ins[:-1]):
                if i.mnemonic == "mov" and i.op_str.startswith("ecx, 0x"):
                    for j in ins[n + 1:n + 3]:
                        if j.mnemonic == "call" and j.operands[0].type == X86_OP_IMM:
                            alloc_votes[j.operands[0].imm - im.ib] += 1
                            break
    alloc_fn = alloc_votes.most_common(1)[0][0]

    by_serializer = collections.defaultdict(list)
    for key, lay in layouts.items():
        if lay["method"] == "WriteCommandMembers":
            by_serializer[lay["win_fn"]].append(key)

    out = []
    for t, vt in sorted(cmds, key=lambda x: x[1]):
        factory = size = None
        best = None
        for f in per_vt_fns[vt]:
            ins = im.disasm_fn(f, 0x200)
            if copies_from_rcx(ins):
                continue  # a clone / copy constructor reads its source from rcx; a factory takes none
            for n, i in enumerate(ins[:-1]):
                if i.mnemonic == "mov" and i.op_str.startswith("ecx, 0x") and \
                        any(j.mnemonic == "call" and j.operands[0].type == X86_OP_IMM and j.operands[0].imm - im.ib == alloc_fn
                            for j in ins[n + 1:n + 3]):
                    cand = (len(ins), f, i.operands[1].imm)
                    best = min(best, cand) if best else cand
                    break
        if best:
            _, factory, size = best
        else:
            # No factory (the UI builds it on the stack): vtable slot 12 is Clone, which
            # allocates exactly sizeof(command) through the engine allocator.
            clone = im.q(vt + 12 * 8) - im.ib
            ins = im.disasm_fn(clone, 0x200)
            for n, i in enumerate(ins[:-1]):
                if i.mnemonic == "mov" and i.op_str.startswith("ecx, 0x") and any(
                        j.mnemonic == "call" and j.operands[0].type == X86_OP_IMM and j.operands[0].imm - im.ib == alloc_fn
                        for j in ins[n + 1:n + 3]):
                    factory, size = 0, i.operands[1].imm
                    break
        s20 = im.q(vt + 20 * 8) - im.ib
        tname = names.get(t)
        cls, how = None, None
        if tname:
            for guess in (camel(tname), camel(tname) + "Command", camel(tname).removesuffix("Command")):
                if guess in linux_cmd_classes:
                    cls, how = guess, "token-name"
                    break
        if cls is None:
            keys = by_serializer.get(s20, [])
            classes = sorted({layouts[k]["class"] for k in keys})
            if len(classes) == 1:
                cls, how = classes[0], "serializer"
        lay = layouts.get(f"{cls}::WriteCommandMembers") if cls else None
        if lay is None and by_serializer.get(s20):
            lay = layouts[by_serializer[s20][0]]  # shared serializer => identical payload layout
        fields = [f for f in (lay["fields"] if lay else []) if f["win_off"] is not None]
        if lay and lay["win_fn"] != s20 and s20 not in by_serializer and linux_cmd_fields.get(cls):
            # the class's fingerprint matched a sibling with the same tokens; the command's own
            # serializer is slot 20 (commands have no this-adjust)
            fields, _ = wx["build_fields"](im, s20, linux_cmd_fields[cls], known_tokens, names, newline_fn)
            for f in fields:
                f["win_off"] = f["win_disp"]
            fields = [f for f in fields if f["win_off"] is not None]
        out.append({
            "token": t, "token_name": tname, "class": cls, "class_how": how,
            "vtable": vt, "factory": factory, "size": size, "serializer": s20,
            "fields": fields,
        })
    # Some tokens have two vtables: the command and a prototype object whose slot 12 clones
    # from `this` (not a factory) and whose slot 20 is _purecall. Keep the one with a real
    # serializer (a WriteCommandMembers layout, or at least not _purecall).
    stub = wx["purecall_rva"](im)
    by_tok = collections.defaultdict(list)
    for c in out:
        by_tok[c["token"]].append(c)
    kept = []
    for t, group in by_tok.items():
        if len(group) > 1:
            real = [c for c in group if c["serializer"] in by_serializer] or \
                   [c for c in group if c["serializer"] != stub]
            if len(real) == 1:
                group = real
        kept.extend(group)
    out = sorted(kept, key=lambda c: c["vtable"])
    return out, alloc_fn


def flatten_entity(key, layouts, depth=0, base=0, seen=None, rejected=None):
    """Own fields + sub-object fields (recursively) with absolute offsets. `rejected` maps a class
    to field names located code contradicts (anchors.py); those are left out."""
    seen = seen or set()
    rejected = rejected or {}
    if key in seen or depth > 5:
        return []
    seen = seen | {key}
    lay = layouts[key]
    rows = []
    drop = set(rejected.get(lay["class"], []))
    for f in lay["fields"]:
        if f["win_off"] is not None and f["name"] not in drop:
            rows.append({**f, "abs": base + f["win_off"], "via": []})
    for s in lay.get("subobjects", []):
        for r in flatten_entity(s["serializer"], layouts, depth + 1, base + s["win_off"], seen, rejected):
            rows.append({**r, "via": [s["class"]] + r["via"]})
    return rows


def type_comment(f):
    k = f["kind"]
    if k == "string" and f.get("linux_indirect"):
        k = "ptr (object pointer; serialized as its key string)"
    if f.get("ref"):
        k += f"<{f['ref']}>"
    if f.get("indirect_off") is not None:
        k += f" (ptr; value at +0x{f['indirect_off']:X})"
    return k


def main():
    data = json.loads((OUT / "win_layouts.json").read_text(encoding="utf-8"))
    layouts = data["layouts"]
    names = {int(k): v for k, v in data["token_names"].items()}
    linux_cmd_classes = set(json.loads((OUT / "linux_classes.json").read_text())["execute_classes"])
    im = Image(EXE)

    apath0 = OUT / "anchors.json"
    rejected = (json.loads(apath0.read_text(encoding="utf-8")) if apath0.exists() else {}).get("rejected_fields", {})

    commands, alloc_fn = discover_commands(im, names, layouts, linux_cmd_classes, data["helpers"]["newline"])

    entities = {}
    for key, lay in sorted(layouts.items()):
        if lay["method"] != "WriteMembers" or lay["this_adjust"] is None:
            continue
        rows = flatten_entity(key, layouts, rejected=rejected)
        if rows:
            entities[lay["class"]] = {"serializer_rva": lay["win_fn"], "score": lay["score"],
                                      "subobjects": lay.get("subobjects", []), "fields": rows}

    sdk = {"exe_timestamp": data["timestamp"], "helpers": {**data["helpers"], "engine_alloc": alloc_fn},
           "commands": commands, "entities": entities}
    (OUT / "sdk.json").write_text(json.dumps(sdk, indent=1), encoding="utf-8")

    # ---------------------------------------------------------------- header
    L = []
    w = L.append
    w("// GENERATED by tools/sdk_dumper (linux_index -> win_extract -> emit_sdk). DO NOT EDIT.")
    w("// Offsets are Windows object offsets derived from the engine's own save/command")
    w("// serializers; field names are the engine's save-file tokens.")
    w("#pragma once")
    w("#include <cstddef>")
    w("#include <cstdint>")
    w("")
    w("namespace sdk {")
    w(f"inline constexpr uint32_t kExeTimestamp = 0x{data['timestamp']:08X};  // PE TimeDateStamp this SDK was dumped from")
    w(f"inline constexpr uintptr_t kRvaEngineAlloc = 0x{alloc_fn:X};")
    w(f"inline constexpr uintptr_t kRvaWriteToken = 0x{data['helpers']['write_token']:X};")
    w("")
    w("// Everything CommandBuilder needs to create a command through the engine's own factory.")
    w("struct CmdSpec {")
    w("    const char* name;")
    w("    uint32_t token;        // returned by vtable slot 10 (`mov eax, token; ret`)")
    w("    uintptr_t vtable_rva;")
    w("    uintptr_t factory_rva; // allocates kSize bytes and writes engine defaults")
    w("    std::size_t size;")
    w("};")
    w("")
    gpath = OUT / "globals_verified.json" if (OUT / "globals_verified.json").exists() else OUT / "globals.json"
    globs = json.loads(gpath.read_text(encoding="utf-8")) if gpath.exists() else {}
    apath = OUT / "anchors.json"
    anchors = json.loads(apath.read_text(encoding="utf-8")) if apath.exists() else {}
    claimed = {a: sym for sym, a in anchors.get("globals", {}).items()}
    for sym in [s for s, g in globs.items() if claimed.get(g["rva"], s) != s]:
        # anchors.py follows the code that creates the object; a command vote that put another
        # name on the same address is the weaker evidence
        print(f"glob 0x{globs[sym]['rva']:X}: {claimed[globs[sym]['rva']]} (anchor) replaces {sym} (vote)")
        del globs[sym]
    for sym, a in anchors.get("globals", {}).items():
        # derived from located code (anchors.py), not voted from commands
        globs.setdefault(sym, {"rva": a, "score": "anchor", "live": "anchor"})
    if globs:
        w("// ============================== globals ===============================")
        w("// RVAs of pointer-sized engine globals, resolved by name from the Linux build.")
        w("// live=ok: the database's objects were type-checked in a running game.")
        w("namespace glob {")
        for sym, g in sorted(globs.items()):
            live = g.get("live", "static")
            w(f"    inline constexpr uintptr_t {ident(sym)} = 0x{g['rva']:X};  // {sym}  score={g['score']} live={live}")
        w("}  // namespace glob")
        w("// TPdxRefDatabase<T>*: arr at +0x18 (16-byte slots, object at +8), capacity at +0x20; invalid id 0xFFFFFFFF")
        w("namespace db {")
        for sym, g in sorted(globs.items()):
            m = re.match(r"TPdxRef<(\w+)>::_pDatabase$", sym)
            if m and not str(g.get("live", "")).startswith("failed"):
                w(f"    inline constexpr uintptr_t {m.group(1)} = 0x{g['rva']:X};")
        w("}  // namespace db")
        w("")
    if anchors.get("fields"):
        w("// ============================ runtime fields ============================")
        w("// Offsets of runtime (not serialized) members, read from located engine code by anchors.py.")
        w("namespace rt {")
        for name, off in sorted(anchors["fields"].items()):
            w(f"    inline constexpr std::ptrdiff_t {ident(name)} = 0x{off:X};")
        w("}  // namespace rt")
        w("")
    if anchors.get("vtables") or anchors.get("slots"):
        w("// ============================== vtables ===============================")
        w("// Engine class vtables and virtual slot indices derived by tools/sdk_dumper/anchors.py.")
        w("namespace vt {")
        for cls, a in sorted(anchors.get("vtables", {}).items()):
            w(f"    inline constexpr uintptr_t {ident(cls)} = 0x{a:X};")
        for name, k in sorted(anchors.get("slots", {}).items()):
            w(f"    inline constexpr int {ident(name)} = {k};")
        w("}  // namespace vt")
        w("")
    fpath = OUT / "functions.json"
    funcs = json.loads(fpath.read_text(encoding="utf-8")) if fpath.exists() else {}
    if funcs:
        w("// ============================== functions =============================")
        w("// Engine functions located by structural fingerprint (tools/sdk_dumper/functions.py).")
        w("namespace fn {")
        for name, f in sorted(funcs.items()):
            w(f"    // {f['linux']}  --  {f['signature']}")
            w(f"    inline constexpr uintptr_t {ident(name)} = 0x{f['rva']:X};")
        w("}  // namespace fn")
        w("")
    w("// ============================== entities ==============================")
    w("namespace ent {")
    ent_ns = collections.Counter()
    for cls, e in sorted(entities.items()):
        if any(f["abs"] < 0 for f in e["fields"]):
            # embedded struct without its own vtable: the ctor store we found belongs to the
            # enclosing object, so absolute offsets are not trustworthy
            w(f"// {cls}: layout unresolved (this-adjust not found; serializer 0x{e['serializer_rva']:X})")
            continue
        ns = ident(cls)
        ent_ns[ns] += 1
        if ent_ns[ns] > 1:
            ns = f"{ns}_{ent_ns[ns]}"
        w(f"namespace {ns} {{  // {cls} serializer 0x{e['serializer_rva']:X}, match {e['score']}")
        used = collections.Counter()
        for f in sorted(e["fields"], key=lambda r: (r["abs"], len(r["via"]))):
            base = ident(f["name"] or f"tok_{f['token']:x}")
            if f["via"] and used[base]:
                base = ident("_".join(v.lstrip("C") for v in f["via"]) + "_" + base)
            used[base] += 1
            nm = base if used[base] == 1 else f"{base}_{used[base]}"
            via = f" via {'/'.join(f['via'])}" if f["via"] else ""
            flag = "" if f.get("evidence") in ("arg", "post", "pre", "lea", "load") else f"  [check: {f.get('evidence')}]"
            w(f"    inline constexpr std::ptrdiff_t {nm} = 0x{f['abs']:X};  // tok 0x{f['token']:x} {type_comment(f)}{via}{flag}")
        w("}")
    w("}  // namespace ent")
    w("")
    w("// ============================== commands ==============================")
    w("// kToken/kVtableRva/kFactoryRva/kSize come from the exe; build commands with the factory,")
    w("// then only write payload fields.")
    w("namespace cmd {")
    seen_ns = collections.Counter()
    for c in commands:
        ns = ident(c["token_name"] or f"token_{c['token']:x}")
        seen_ns[ns] += 1
        if seen_ns[ns] > 1:
            ns = f"{ns}_{seen_ns[ns]}"
        w(f"namespace {ns} {{  // {c['class'] or '?'}" + (f" ({c['class_how']})" if c["class"] else ""))
        w(f"    inline constexpr uint32_t kToken = 0x{c['token']:X};")
        w(f"    inline constexpr uintptr_t kVtableRva = 0x{c['vtable']:X};")
        if c["factory"] is not None:
            if c["factory"] == 0:
                w("    // no engine factory: CommandBuilder allocates kSize (from Clone) and writes the header")
            w(f"    inline constexpr uintptr_t kFactoryRva = 0x{c['factory']:X};")
            w(f"    inline constexpr std::size_t kSize = 0x{c['size']:X};")
            w(f"    inline constexpr CmdSpec kSpec{{\"{ns}\", kToken, kVtableRva, kFactoryRva, kSize}};")
        used = collections.Counter()
        for f in c["fields"]:
            nm = ident(f["name"] or f"tok_{f['token']:x}")
            used[nm] += 1
            if used[nm] > 1:
                nm = f"{nm}_{used[nm]}"
            bad = c["size"] is not None and f["win_off"] >= c["size"]
            w(f"    inline constexpr std::ptrdiff_t {nm} = 0x{f['win_off']:X};  // tok 0x{f['token']:x} {type_comment(f)}"
              + ("  [check: beyond kSize]" if bad else ""))
        w("}")
    w("}  // namespace cmd")
    w("}  // namespace sdk")
    HEADER.parent.mkdir(parents=True, exist_ok=True)
    HEADER.write_text("\n".join(L) + "\n", encoding="utf-8")

    named = sum(1 for c in commands if c["class"])
    print(f"commands: {len(commands)} ({named} with C++ class), engine_alloc=0x{alloc_fn:X}")
    print(f"entities: {len(entities)}; header -> {HEADER}")


if __name__ == "__main__":
    main()
