"""Read-only local ELF producer inventory and instruction-verified call evidence.

This tool neither connects to Stellaris nor invokes recovered native functions.
Direct-call evidence alone does not establish argument semantics or authority.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools/sdk_recovery"))
from callsite_arguments import recover_callsites
from linux_elf import ElfImage


def function_evidence(image, symbol: dict, *, limit: int = 65536) -> dict:
    """Retain full bytes plus direct/indirect calls; never infer missing edges."""
    size = symbol["size"]
    raw = image.read(symbol["rva"], min(size, limit))
    instructions = image.instructions(symbol, limit)
    complete = bool(
        size > 0 and size <= limit and sum(i.size for i in instructions) == size
    )
    calls, rows = [], []
    for instruction in instructions:
        target = None
        if instruction.mnemonic in ("call", "jmp") and instruction.operands:
            operand = instruction.operands[0]
            if operand.type == 2:
                target = operand.imm
                # Internal jumps are CFG edges, not function calls.
                if (
                    instruction.mnemonic == "call"
                    or not symbol["rva"] <= target < symbol["rva"] + size
                ):
                    calls.append(
                        {
                            "call_rva": instruction.address,
                            "target_rva": target,
                            "target": image.target_name(target),
                            "kind": "direct_call"
                            if instruction.mnemonic == "call"
                            else "tail_jump",
                        }
                    )
            else:
                calls.append(
                    {
                        "call_rva": instruction.address,
                        "target_rva": None,
                        "target": instruction.op_str,
                        "kind": "indirect_unresolved"
                        if instruction.mnemonic == "call"
                        else "indirect_jump_unresolved",
                    }
                )
        rip_references = []
        for operand in instruction.operands:
            if operand.type == 3 and instruction.reg_name(operand.mem.base) == "rip":
                address = instruction.address + instruction.size + operand.mem.disp
                rip_references.append(
                    {"rva": address, "symbol": image.target_name(address)}
                )
        rows.append(
            {
                "rva": instruction.address,
                "bytes": instruction.bytes.hex(),
                "mnemonic": instruction.mnemonic,
                "operands": instruction.op_str,
                "target_rva": target,
                "target": image.target_name(target) if target is not None else None,
                "rip_references": rip_references,
            }
        )
    return {
        "name": image.name(symbol),
        "raw": symbol["raw"],
        "rva": symbol["rva"],
        "size": size,
        "bytes": raw.hex(),
        "bytes_sha256": hashlib.sha256(raw).hexdigest(),
        "complete_linear_decode": complete,
        "linear_decode_is_not_reachability_proof": True,
        "instructions": rows,
        "calls": calls,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--linux-binary", type=Path, required=True)
    parser.add_argument("--sdk", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--inventory-pattern", action="append", default=[])
    parser.add_argument("--function-pattern", action="append", default=[])
    parser.add_argument(
        "--function-rva", type=lambda v: int(v, 0), action="append", default=[]
    )
    parser.add_argument("--xref-pattern", action="append", default=[])
    args = parser.parse_args()
    image = ElfImage(args.linux_binary)
    sdk = json.loads(args.sdk.read_text(encoding="utf-8"))
    if (
        sdk["build_id"] != image.build_id
        or sdk["sha256"] != hashlib.sha256(image.data).hexdigest()
    ):
        raise ValueError("SDK and exact ELF identity differ")
    args.output.mkdir(parents=True, exist_ok=False)
    inventory_patterns = [re.compile(p) for p in args.inventory_pattern]
    function_patterns = [re.compile(p) for p in args.function_pattern]
    xref_patterns = [re.compile(p) for p in args.xref_pattern]
    functions, selected, targets, inventory = {}, {}, set(), []
    for symbol in image.symbols:
        if symbol["type"] != "STT_FUNC" or not symbol["size"]:
            continue
        if symbol["size"] > functions.get(symbol["rva"], {}).get("size", 0):
            functions[symbol["rva"]] = symbol
        # Raw-name prefilter avoids demangling the entire symbol table.
        if (
            not any(p.search(symbol["raw"]) for p in inventory_patterns)
            and symbol["rva"] not in args.function_rva
        ):
            continue
        name = image.name(symbol)
        inventory.append({**symbol, "name": name})
        if symbol["rva"] in args.function_rva or any(
            p.search(name) for p in function_patterns
        ):
            selected[symbol["rva"]] = symbol
        if any(p.search(name) for p in xref_patterns):
            targets.add(symbol["rva"])
    xrefs = recover_callsites(image, targets) if targets else []
    for row in xrefs:
        if row["instruction_verified"]:
            selected[row["caller_rva"]] = functions[row["caller_rva"]]
    evidence = [function_evidence(image, s) for _, s in sorted(selected.items())]
    results = {
        "manifest.json": {
            "schema_version": "iag.native_producer_research.v1",
            "recorded_at": datetime.now(UTC).isoformat(),
            "build_id": image.build_id,
            "elf_sha256": sdk["sha256"],
            "sdk": str(args.sdk),
            "binary": str(args.linux_binary),
            "inventory_symbols": len(inventory),
            "selected_functions": len(evidence),
            "requested_function_rvas": sorted(set(args.function_rva)),
            "missing_requested_function_rvas": sorted(
                set(args.function_rva) - functions.keys()
            ),
            "selection": {
                "inventory_patterns": args.inventory_pattern,
                "function_patterns": args.function_pattern,
                "xref_patterns": args.xref_pattern,
            },
            "xref_targets": sorted(targets),
            "direct_xrefs": len(xrefs),
            "new_native_calls": 0,
            "production_promotions": 0,
            "limits": [
                "indirect callees unresolved",
                "inlined constructors can lack call edges",
                "linear decode is not complete CFG/dataflow or runtime reachability",
            ],
        },
        "symbol-inventory.json": inventory,
        "functions.json": evidence,
        "direct-xrefs.json": xrefs,
        "existing-constructor-callsites.json": sdk["constructor_callsites"],
    }
    for filename, data in results.items():
        with (args.output / filename).open("x", encoding="utf-8") as stream:
            json.dump(data, stream, indent=2)
    print(json.dumps(results["manifest.json"], indent=2))


if __name__ == "__main__":
    main()
