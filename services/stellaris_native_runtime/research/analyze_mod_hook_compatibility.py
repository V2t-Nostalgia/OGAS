#!/usr/bin/env python3
"""Build a conservative Mod/native-hook compatibility evidence report."""

from __future__ import annotations

import argparse
import json
import zipfile
from pathlib import Path
from typing import Any


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _fingerprints(value: dict[str, Any]) -> set[str]:
    return {
        str(signature["fingerprint"])
        for signature in value.get("layout_signatures", [])
        if signature.get("fingerprint")
    }


def _has_layout_evidence(value: dict[str, Any]) -> bool:
    """Return whether this catalog schema recorded layout signatures at all."""

    return isinstance(value.get("layout_signatures"), list)


def _phase_counts(value: dict[str, Any]) -> dict[str, int]:
    return {str(key): int(count) for key, count in value.get("phases", {}).items()}


def _definition_samples(inventory: dict[str, Any]) -> dict[str, list[str]]:
    result: dict[str, set[str]] = {}
    for mod in inventory.get("mods", []):
        samples = mod.get("external_definitions", {}).get("samples", {})
        for kind, values in samples.items():
            result.setdefault(str(kind), set()).update(map(str, values))
    return {kind: sorted(values) for kind, values in sorted(result.items())}


def _scan_save(path: Path | None, samples: dict[str, list[str]]) -> dict[str, Any]:
    if path is None:
        return {"available": False, "reason": "no save supplied"}
    with zipfile.ZipFile(path) as archive:
        gamestate = archive.read("gamestate")
    mentions: dict[str, dict[str, int]] = {}
    for kind, values in samples.items():
        found = {
            value: gamestate.count(value.encode("utf-8"))
            for value in values
            if value.encode("utf-8") in gamestate
        }
        if found:
            mentions[kind] = found
    return {
        "available": True,
        "provenance": "literal identifiers in supplied save gamestate",
        "mentions": mentions,
        "warning": "A save mention proves persistence, not which command created it.",
    }


def analyze(
    baseline: dict[str, Any],
    modded: dict[str, Any],
    inventory: dict[str, Any],
    *,
    save_path: Path | None = None,
) -> dict[str, Any]:
    baseline_commands = baseline.get("command_types", {})
    modded_commands = modded.get("command_types", {})
    baseline_payloads = baseline.get("payload_types", {})
    modded_payloads = modded.get("payload_types", {})
    common_commands = sorted(set(baseline_commands) & set(modded_commands))
    mod_only_commands = sorted(set(modded_commands) - set(baseline_commands))
    baseline_only_commands = sorted(set(baseline_commands) - set(modded_commands))

    command_layouts: list[dict[str, Any]] = []
    for command in common_commands:
        baseline_has_layout = _has_layout_evidence(baseline_commands[command])
        modded_has_layout = _has_layout_evidence(modded_commands[command])
        comparable = baseline_has_layout and modded_has_layout
        shared = (
            sorted(
                _fingerprints(baseline_commands[command])
                & _fingerprints(modded_commands[command])
            )
            if comparable
            else None
        )
        command_layouts.append(
            {
                "command": command,
                "layout_comparison_available": comparable,
                "shared_layout_fingerprints": shared,
                "baseline_phases": _phase_counts(baseline_commands[command]),
                "modded_phases": _phase_counts(modded_commands[command]),
            }
        )

    common_payloads = sorted(set(baseline_payloads) & set(modded_payloads))
    payload_layout_reuse: dict[str, dict[str, Any]] = {}
    for payload in common_payloads:
        comparable = _has_layout_evidence(
            baseline_payloads[payload]
        ) and _has_layout_evidence(modded_payloads[payload])
        payload_layout_reuse[payload] = {
            "layout_comparison_available": comparable,
            "shared_layout_fingerprints": (
                sorted(
                    _fingerprints(baseline_payloads[payload])
                    & _fingerprints(modded_payloads[payload])
                )
                if comparable
                else None
            ),
        }
    samples = _definition_samples(inventory)
    event_evidence = {
        event: modded.get("event_definitions", {}).get(event)
        for event in samples.get("event", [])
        if event in modded.get("event_definitions", {})
    }

    return {
        "schema": "iag.stellaris.mod_native_hook_compatibility.v1",
        "executable_identity": {
            "elf_build_id": inventory.get("elf_build_id"),
            "game_version": inventory.get("game_version"),
            "inventory_fingerprint_sha256": inventory.get(
                "inventory_fingerprint_sha256"
            ),
        },
        "attribution_policy": inventory.get("attribution_policy", {}),
        "mods": [
            {
                "load_index": value.get("load_index"),
                "name": value.get("name"),
                "remote_file_id": value.get("remote_file_id"),
                "content_fingerprint": value.get("fingerprints", {}).get(
                    "semantic_content_fingerprint_sha256"
                ),
                "external_definition_counts": value.get(
                    "external_definitions", {}
                ).get("counts", {}),
                "engine_loaded_definitions": value.get(
                    "external_definitions", {}
                ).get("engine_loaded", False),
            }
            for value in inventory.get("mods", [])
        ],
        "command_catalog_comparison": {
            "baseline_count": len(baseline_commands),
            "modded_count": len(modded_commands),
            "common_count": len(common_commands),
            "modded_only": mod_only_commands,
            "baseline_only": baseline_only_commands,
            "common_layouts": command_layouts,
            "layout_comparison_available": bool(command_layouts)
            and all(
                value["layout_comparison_available"] for value in command_layouts
            ),
            "warning": (
                "Set differences are coverage observations from unequal runs; they do "
                "not attribute a command to a Mod. A missing layout-signature field "
                "means the older catalog cannot support a layout comparison; it is "
                "not evidence that the layout changed."
            ),
        },
        "payload_catalog_comparison": {
            "baseline_count": len(baseline_payloads),
            "modded_count": len(modded_payloads),
            "common_count": len(common_payloads),
            "layout_comparison_available": bool(payload_layout_reuse)
            and all(
                value["layout_comparison_available"]
                for value in payload_layout_reuse.values()
            ),
            "layouts": payload_layout_reuse,
        },
        "external_definition_samples": samples,
        "captured_mod_event_evidence": event_evidence,
        "save_evidence": _scan_save(save_path, samples),
        "evidence_boundaries": {
            "native_structure_reuse": (
                "shared RTTI, plus layout fingerprints only when both catalog schemas "
                "recorded them"
            ),
            "content_presence": "external file index and optional save mentions",
            "live_action_compatibility": (
                "not established without a legal-candidate query and disposable-save "
                "submission/postcondition test"
            ),
            "per_mod_causality": "unknown without controlled single-Mod runs",
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline-catalog", required=True, type=Path)
    parser.add_argument("--modded-catalog", required=True, type=Path)
    parser.add_argument("--mod-inventory", required=True, type=Path)
    parser.add_argument("--save", type=Path)
    parser.add_argument("--output", type=Path)
    arguments = parser.parse_args()
    report = analyze(
        load_json(arguments.baseline_catalog),
        load_json(arguments.modded_catalog),
        load_json(arguments.mod_inventory),
        save_path=arguments.save,
    )
    encoded = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if arguments.output:
        arguments.output.write_text(encoded, encoding="utf-8")
    else:
        print(encoded, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
