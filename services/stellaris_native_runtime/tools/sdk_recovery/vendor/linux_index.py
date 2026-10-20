"""Stage 1: index serializer functions in the Linux (symbolized) Ghidra decompile.

Streams source/stellaris_4.5_source.cpp once and extracts, for every
    Class::WriteMembers(CWriter&) / Class::WriteCommandMembers(CWriter&)
the ordered list of serialized fields:
    token (same numeric value on Windows), linux offset, value kind, ref type.
Nested sub-object serializers (Base::WriteMembers((Base*)(this+off), w)) are kept too.

Linux offsets are GCC layout and must NOT be used on Windows; they are only kept
for reference. Windows offsets come from stage 2 (win_extract.py).

Usage: python tools/sdk_dumper/linux_index.py [source.cpp] [out.json]
"""
# SPDX-FileCopyrightText: 2026 Yidhar
# SPDX-License-Identifier: MIT
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "source" / "stellaris_4.5_source.cpp"
OUT = Path(sys.argv[2]) if len(sys.argv) > 2 else ROOT / "tools" / "sdk_dumper" / "out" / "linux_index.json"

FUNC_COMMENT = re.compile(r"^/\* ([\w:<>, ]+?)::(WriteMembers|WriteCommandMembers)\(CWriter&\)(?: const)? \*/")
FUNC_END = re.compile(r"^// ============ .* End =+")

# CWriter::Write<CCountry>(param_1,0x2c88,(TPdxRef *)(this + 0x1c));
CALL = re.compile(
    r"(?P<fn>[\w:]+(?:<(?P<targ>[^()]*?)>)?)\s*\(\s*param_1\s*,\s*(?P<tok>0x[0-9a-f]+|\d+)\s*,(?P<args>.*?)\)\s*;")
SUBOBJ = re.compile(r"(?P<cls>[\w:<>]+)::(?P<m>WriteMembers|WriteCommandMembers|SaveOnDeath_WriteMembers)\s*\(\s*\([\w:<> ]+\*\)\s*\(this \+ (?P<off>0x[0-9a-f]+|\d+)\)\s*,\s*param_1\s*\)")
LOCAL_ALIAS = re.compile(r"(?P<var>local_\w+|p\w+Var\d+)\s*=\s*(?:\([\w:<> ]+\*\)\s*)?\(?this \+ (?P<off>0x[0-9a-f]+|\d+)\)?\s*;")
THIS_OFF = re.compile(r"this \+ (0x[0-9a-f]+|\d+)|this\[(0x[0-9a-f]+|\d+)\]")
CAST_KIND = re.compile(r"^\s*\*?\s*\((?P<ty>[\w:<> ]+?)\s*\*\)")


def classify(fn, targ, args):
    """Best-effort value kind from the Ghidra call shape."""
    a = args.strip()
    if targ and fn.startswith("CWriter::Write<"):
        return "ref", targ
    if targ and "WriteUniformWithSpace" in fn:
        return "ref_array", targ
    m = CAST_KIND.match(a)
    ty = m.group("ty").strip() if m else None
    deref = a.startswith("*")
    if ty in ("CString",):
        return "string", None
    if ty in ("CPersistent",):
        return "persistent", None
    if ty and deref:
        return {"uint": "u32", "int": "i32", "char": "bool", "byte": "u8", "bool": "bool",
                "undefined8": "u64", "ulong": "u64", "long": "i64", "float": "f32",
                "double": "f64", "ushort": "u16", "short": "i16", "undefined4": "u32"}.get(ty, ty), None
    if ty:
        return "ptr:" + ty, None
    return "other", None


def parse_body(body):
    text = " ".join(l.strip() for l in body)
    aliases = {}
    for m in LOCAL_ALIAS.finditer(text):
        aliases[m.group("var")] = int(m.group("off"), 0)
    fields, subs = [], []
    for m in SUBOBJ.finditer(text):
        subs.append({"class": m.group("cls"), "method": m.group("m"), "linux_off": int(m.group("off"), 0)})
    seg_start = 0
    for m in CALL.finditer(text):
        fn, targ, tok, args = m.group("fn"), m.group("targ"), int(m.group("tok"), 0), m.group("args")
        if not fn.startswith(("CWriter::", "NParserUtil::")):
            continue
        offs = [int(a or b, 0) for a, b in THIS_OFF.findall(args)]
        source = "arg"
        if not offs:
            # Value built from context: `if (this[0x74]) Write(tok, true)`,
            # `local_28 = this + 0x898; Write(tok, (CPersistent*)&local_38)`, ...
            ctx = [int(a or b, 0) for a, b in THIS_OFF.findall(text[seg_start:m.start()])]
            if ctx:
                offs, source = [ctx[-1]], "context"
        seg_start = m.end()
        kind, ref = classify(fn, targ, args)
        if kind == "other" and args.strip() in ("true", "false"):
            kind = "bool_cond"
        fields.append({
            "token": tok,
            "writer": re.sub(r"<.*>", "<T>", fn),
            "kind": kind,
            "ref": ref,
            "linux_off": offs[0] if offs else None,
            "off_source": source if offs else None,
            "indirect": bool(re.search(r"\*\(long \*\)\s*\(this \+", args)),
            "arg": args.strip()[:120],
        })
    return fields, subs


EXECUTE_COMMENT = re.compile(r"^/\* ([\w:<>, ]+?)::Execute\(\) \*/")
# any function header, for the anchors below
ANY_FUNC = re.compile(r"^/\* ([\w:<>, ~]+?::~?\w+)\(.*\) \*/")
DB_PATH = re.compile(r'"(common/[\w/]+)"')
REF_DB_CTOR = re.compile(r"TPdxRefDatabase<(\w+), ?8u>::TPdxRefDatabase\b")
GAME_STATE_DB_CTOR = "CGameStateDatabase::CGameStateDatabase"


def main():
    classes = {}
    command_classes = set()
    cur, body = None, []
    # for anchors.py: which function loads each "common/<folder>" database, and the order in
    # which CGameStateDatabase constructs its TPdxRefDatabase<X> members (Windows inlines those
    # constructors, so the order of the _pDatabase stores is all that is left to name them)
    fn_name, db_paths, ref_order = None, {}, []
    with open(SRC, encoding="utf-8", errors="ignore") as f:
        for line in f:
            if line.startswith("/* "):
                m = ANY_FUNC.match(line)
                if m:
                    fn_name = m.group(1)
            elif fn_name:
                if '"common/' in line:
                    for p in DB_PATH.findall(line):
                        db_paths.setdefault(p, set()).add(fn_name)
                if fn_name == GAME_STATE_DB_CTOR and "TPdxRefDatabase<" in line:
                    ref_order += REF_DB_CTOR.findall(line)
            if cur is None:
                m = FUNC_COMMENT.match(line)
                if m:
                    cur, body = (m.group(1), m.group(2)), []
                    continue
                m = EXECUTE_COMMENT.match(line)
                if m:
                    command_classes.add(m.group(1))
                continue
            if FUNC_END.match(line):
                fields, subs = parse_body(body)
                # Ghidra emits trivial thunks with an empty body; keep the richest variant.
                key = f"{cur[0]}::{cur[1]}"
                prev = classes.get(key)
                if prev is None or len(fields) + len(subs) > len(prev["fields"]) + len(prev["subobjects"]):
                    classes[key] = {"class": cur[0], "method": cur[1], "fields": fields, "subobjects": subs}
                cur = None
                continue
            body.append(line)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(classes, indent=1), encoding="utf-8")
    (OUT.parent / "linux_classes.json").write_text(
        json.dumps({"execute_classes": sorted(command_classes)}, indent=1), encoding="utf-8")
    (OUT.parent / "linux_anchors.json").write_text(json.dumps({
        "db_paths": {p: sorted(fns) for p, fns in sorted(db_paths.items())},
        "game_state_ref_order": ref_order}, indent=1), encoding="utf-8")
    n_f = sum(len(c["fields"]) for c in classes.values())
    print(f"indexed {len(classes)} serializer functions, {n_f} fields -> {OUT}")


if __name__ == "__main__":
    main()
