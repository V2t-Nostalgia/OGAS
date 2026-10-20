#!/usr/bin/env python3
"""Recover an OGAS engine SDK from the current Linux ELF and Windows PE.

Only engine metadata is generated. This tool never registers semantic actions,
enables a Broker capability, attaches to a process or submits a command.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import runpy
import subprocess
import sys
import time
from pathlib import Path

from emit_ogas import emit_header
from linux_elf import recover_linux

HERE = Path(__file__).resolve().parent
VENDOR = HERE / "vendor"


def write_json(path: Path, value: object) -> None:
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def run_stage(name: str, environment: dict[str, str], work: Path) -> int:
    start = time.monotonic()
    result = subprocess.run(
        [sys.executable, str(VENDOR / name)],
        env=environment,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    (work / (name + ".log")).write_text(result.stdout + result.stderr, encoding="utf-8")
    print(
        f"{name}: exit={result.returncode}, {time.monotonic() - start:.1f}s", flush=True
    )
    if result.returncode:
        print((result.stdout + result.stderr)[-4000:], flush=True)
    return result.returncode


def normalize_windows(work: Path, binary: Path) -> dict:
    sdk = json.loads((work / "sdk.json").read_text(encoding="utf-8"))
    wx = runpy.run_path(str(VENDOR / "win_extract.py"), run_name="sdk_metadata")
    image = wx["Image"](binary)
    commands = []
    for source in sdk["commands"]:
        command = dict(source)
        vt = command["vtable"]
        command.update(
            is_valid=image.q(vt + 8 * 8) - image.ib,
            deleting_destructor=image.q(vt) - image.ib,
            token_getter=image.q(vt + 10 * 8) - image.ib,
            slots={"is_valid": 8, "deleting_destructor": 0, "token": 10},
            evidence_level="layout_generated",
            execution_verified=False,
        )
        for field in command["fields"]:
            field["offset"] = field["win_off"]
            field["confidence"] = field.get("evidence") or "unresolved"
            field["storage_kind"] = (
                "definition_pointer" if field.get("linux_indirect") else field["kind"]
            )
        commands.append(command)
    return {
        "schema_version": "iag.recovered_sdk.v1",
        "platform": "windows-x64",
        "build_id": "sha256:" + hashlib.sha256(binary.read_bytes()).hexdigest(),
        "sha256": hashlib.sha256(binary.read_bytes()).hexdigest(),
        "pe_timestamp": image.timestamp,
        "commands": commands,
        "entities": sdk["entities"],
        "helpers": sdk["helpers"],
        "functions": json.loads((work / "functions.json").read_text(encoding="utf-8")),
        "globals": json.loads((work / "globals.json").read_text(encoding="utf-8")),
    }


def compare_reference(catalog: dict, reference: Path) -> dict:
    """Compare fresh discovery with a pinned upstream header, by semantic token name."""
    import re

    text = reference.read_text(encoding="utf-8")
    errors, checked = [], 0
    samples = (
        "hire_leader",
        "research_technology_command",
        "cancel_research_technology_command",
        "fleet_fly_to_coordinates",
        "market_buy_resource_command",
        "add_buildable_to_queue_command",
    )
    by_name = {c["token_name"]: c for c in catalog["commands"]}
    for name in samples:
        match = re.search(
            r"namespace " + re.escape(name) + r" \{[^\n]*\n(.*?)\n\}", text, re.DOTALL
        )
        command = by_name.get(name)
        if not match or command is None:
            errors.append(f"missing sample {name}")
            continue
        block = match.group(1)
        for const, key in (
            ("kToken", "token"),
            ("kVtableRva", "vtable"),
            ("kFactoryRva", "factory"),
            ("kSize", "size"),
        ):
            value = re.search(r"\b" + const + r" = (0x[0-9A-Fa-f]+);", block)
            if value and command[key] == int(value.group(1), 16):
                checked += 1
            else:
                errors.append(f"{name}.{key} differs from upstream")
        offsets = {f["name"]: f["offset"] for f in command["fields"]}
        for field, raw in re.findall(
            r"std::ptrdiff_t (\w+) = (0x[0-9A-Fa-f]+);", block
        ):
            if offsets.get(field) == int(raw, 16):
                checked += 1
            else:
                errors.append(
                    f"{name}.{field} differs: got {offsets.get(field)}, expected {raw}"
                )
    return {
        "checks": checked,
        "errors": errors,
        "samples": list(samples),
        "ok": not errors,
    }


def compare_ogas_evidence(linux: dict, windows: dict) -> dict:
    """Independent regression anchors from OGAS typed actions and live documents.

    These include the new sample's static constraints. They are assertions,
    never discovery inputs; a mismatch is not repaired from expected values.
    """
    expected = {
        "CCancelResearchTechnologyCommand": (
            0x28,
            {"country": 0x1C, "technology": 0x20},
        ),
        "CFleetFlyToCoordinatesCommand": (
            0x50,
            {"fleet": 0x1C, "target": 0x20, "queue": 0x48, "queue_to_front": 0x49},
        ),
        "CMarketBuyResourceCommand": (0x40, {"multiplier": 0x38, "trade_data": 0x20}),
        "CHireLeaderCommand": (0x28, {"country": 0x1C, "leader": 0x20}),
    }
    checks, errors = 0, []
    lmap = {c["class"]: c for c in linux["commands"]}
    wmap = {c["class"]: c for c in windows["commands"] if c["class"]}
    for name, (size, fields) in expected.items():
        command = lmap.get(name)
        if command is None:
            errors.append(f"missing Linux sample {name}")
            continue
        if command["size"] == size:
            checks += 1
        else:
            errors.append(f"{name}: Linux size {command['size']} != {size}")
        recovered_fields = {f["name"]: f["linux_off"] for f in command["fields"]}
        for field, offset in fields.items():
            if recovered_fields.get(field) == offset:
                checks += 1
            else:
                errors.append(
                    f"{name}.{field}: Linux offset {recovered_fields.get(field)} != {offset}"
                )
        if name in wmap and command["token"] == wmap[name]["token"]:
            checks += 1
        else:
            errors.append(f"{name}: platform token mismatch")
    return {"checks": checks, "errors": errors, "ok": not errors}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--linux-binary", required=True, type=Path)
    parser.add_argument("--windows-binary", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--reference-header", type=Path)
    args = parser.parse_args()
    for source in (args.linux_binary, args.windows_binary, args.reference_header):
        if source is not None and not source.is_file():
            parser.error(f"input does not exist: {source}")
    work = args.output.resolve()
    work.mkdir(parents=True, exist_ok=True)
    # Never replace an earlier run's evidence or accidentally mix two builds.
    if any(work.iterdir()):
        parser.error("output directory must be empty; choose a new run directory")
    environment = dict(
        os.environ,
        IAG_SDK_WINDOWS_EXE=str(args.windows_binary.resolve()),
        IAG_SDK_WORK_DIR=str(work),
    )
    os.environ.update(
        {k: v for k, v in environment.items() if k.startswith("IAG_SDK_")}
    )
    started = time.monotonic()
    wx = runpy.run_path(str(VENDOR / "win_extract.py"), run_name="sdk_token_index")
    names, register_token = wx["token_names"](wx["Image"](args.windows_binary), set())
    if len(names) < 100:
        raise RuntimeError("current PE token registry was not recovered")
    print(
        f"Current token registry: {len(names)}, RegisterToken={register_token:#x}",
        flush=True,
    )
    linux = recover_linux(args.linux_binary, work, names)
    for stage in (
        "win_extract.py",
        "validate.py",
        "emit_sdk.py",
        "globals.py",
        "functions.py",
    ):
        code = run_stage(stage, environment, work)
        if code:
            return code
    windows = normalize_windows(work, args.windows_binary)
    write_json(work / "windows_sdk.json", windows)
    report = {
        "schema_version": "iag.sdk_recovery_report.v1",
        "elapsed_seconds": round(time.monotonic() - started, 3),
        "linux_build_id": linux["build_id"],
        "windows_build_id": windows["build_id"],
        "linux_commands": len(linux["commands"]),
        "windows_commands": len(windows["commands"]),
        "production_actions_added": 0,
        "evidence_level": "layout_generated",
        "execution_verified": False,
        "ogas_comparison": compare_ogas_evidence(linux, windows),
        "windows_functions": len(windows["functions"]),
        "windows_globals": len(windows["globals"]),
        "linux_factories": sum(bool(c["factory"]) for c in linux["commands"]),
        "windows_factories": sum(bool(c["factory"]) for c in windows["commands"]),
        "linux_dwarf_sections": linux.get("dwarf_sections", []),
        "linux_recovery_capabilities": linux.get("recovery_summary", {}),
    }
    if args.reference_header:
        report["reference_comparison"] = compare_reference(
            windows, args.reference_header
        )
    write_json(work / "recovery_report.json", report)
    print(json.dumps(report, indent=2), flush=True)
    if (
        report.get("reference_comparison", {}).get("errors")
        or report["ogas_comparison"]["errors"]
    ):
        return 1
    emit_header(linux, work / "stellaris_linux_sdk.hpp")
    emit_header(windows, work / "stellaris_windows_sdk.hpp")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
