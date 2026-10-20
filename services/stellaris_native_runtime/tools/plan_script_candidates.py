#!/usr/bin/env python3
"""Offline Command constraints/candidates for the entire generated SDK.

Never connects to a runtime, opens process memory, submits a command, or replaces
generated SDK layouts. Outputs are new, immutable research artifacts.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from collections import defaultdict

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent / "sdk_recovery"))

from sdk_recovery.linux_elf import ElfImage
from sdk_recovery.emit_ogas import catalog_fingerprint
from script_candidates.content import ContentLayer, load_content
from script_candidates.feedback import Feedback
from script_candidates.native_guards import extract_guards
from script_candidates.native_rules import Discovery
from script_candidates.native_predicates import discover_predicates
from script_candidates.planner import DEFINITION_FAMILIES, discover_definition_families, plan_command, summarize
from script_candidates.snapshot import load_snapshot, restore_world_cache, world_cache
from script_candidates.syntax import CwtoolsParser
from script_candidates.semantic_audit import audit_command, audit_summary, native_neighborhood, search_game_sources


def write_new(path, value):
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, ensure_ascii=True)
        stream.write("\n")


def archive_sources(output: Path, bridge: Path) -> list[dict]:
    root = Path(__file__).resolve().parents[3]
    package = Path(__file__).resolve().parent / "script_candidates"
    sources = [p for p in package.rglob("*") if p.is_file() and
               p.suffix in {".py", ".cs", ".csproj", ".json", ".txt"} and
               not {"obj", "bin", "__pycache__"} & set(p.parts)]
    sources += [Path(__file__).resolve(), Path(__file__).with_name("validate_constraint_candidates.py")]
    sources += [Path(__file__).with_name("test_script_candidates.py")]
    sources += [Path(__file__).with_name("test_semantic_audit.py")]
    sources += [Path(__file__).with_name("test_coordinate_reuse.py")]
    sources += [Path(__file__).parent / "sdk_recovery" / name for name in
                ("linux_elf.py", "emit_ogas.py", "callsite_arguments.py", "value_recovery.py", "recovery_plans.py", "array_recovery.py", "coordinate_values.py")]
    for relative in ("src/iag/stellaris/execution/native_runtime.py", "services/stellaris_native_runtime/sdk_probe.cpp",
                     "services/stellaris_native_runtime/include/iag_native_runtime/sdk_probe.h",
                     "services/stellaris_native_runtime/tests/command_producers_test.cpp",
                     "services/stellaris_native_runtime/tests/command_builder_test.cpp",
                     "services/stellaris_native_runtime/command_builder.cpp",
                     "services/stellaris_native_runtime/command_producers.cpp",
                     "services/stellaris_native_runtime/game_api.cpp",
                     "services/stellaris_native_runtime/runtime.cpp", "services/stellaris_native_runtime/runtime_windows.cpp"):
        sources.append(root / relative)
    manifest = []
    for path in sorted(sources):
        relative = path.relative_to(root)
        destination = output / "source-snapshot" / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        with destination.open("xb") as stream:
            stream.write(path.read_bytes())
        manifest.append({"path": relative.as_posix(), "sha256": hashlib.sha256(destination.read_bytes()).hexdigest()})
    parser_output = output / "parser-binary"
    parser_output.mkdir()
    for path in sorted(bridge.parent.iterdir()):
        if path.is_file() and path.suffix in {".dll", ".json"}:
            shutil.copyfile(path, parser_output / path.name)
    write_new(output / "source-manifest.json", manifest)
    return manifest


def recovery_worklist(rows: list[dict]) -> list[dict]:
    """Group shared missing capabilities, not 351 one-off manual adapters."""
    groups = defaultdict(lambda: {"commands": set(), "evidence_rvas": set()})
    for row in rows:
        if row.get("semantic_audit"):
            audit = row["semantic_audit"]
            for parameter in audit["parameter_contracts"]:
                if not parameter["requirement"]:
                    continue
                prefix = "caller_contract:" if parameter["source"] == "caller_input" else "parameter_source:"
                key = prefix + parameter["requirement"] + ":" + (parameter["native_type"] or parameter["storage_kind"])
                groups[key]["commands"].add(row["command_name"])
                for evidence in parameter["evidence"]:
                    for kind, value in evidence.items():
                        if (kind == "rva" or kind.endswith("_rva")) and type(value) is int and value:
                            groups[key]["evidence_rvas"].add(value)
            for gap in audit["technical_gaps"]:
                key = "native_capability:" + gap["kind"] + ":" + (gap.get("native_type") or gap.get("storage_kind") or "")
                groups[key]["commands"].add(row["command_name"])
                for function in audit["native_neighborhood"]["functions"]:
                    groups[key]["evidence_rvas"].add(function["rva"])
            continue
        for domain in row["domains"]:
            if domain["available"]:
                continue
            key = "candidate_domain:" + (domain["reference_type"] or domain["kind"])
            groups[key]["commands"].add(row["command_name"])
        for rule in row["native_rule_paths"]["rules"]:
            if not any(h["rule"] == rule["rule"] for h in row["scope_hints"]):
                key = "native_rule_argument_binding:" + rule["rule"]
                groups[key]["commands"].add(row["command_name"])
                groups[key]["evidence_rvas"].add(rule["wrapper_rva"])
        for reason in row["blockers"]:
            if not reason.startswith("candidate_domain_missing:"):
                groups[reason]["commands"].add(row["command_name"])
    return [{"capability": key, "affected_commands": sorted(value["commands"]),
            "evidence_rvas": sorted(value["evidence_rvas"]),
            "status": "caller_input_not_recovery_failure" if key.startswith("caller_contract:") else "shared_requirement_with_per_command_evidence"}
            for key, value in sorted(groups.items(), key=lambda item: (-len(item[1]["commands"]), item[0]))]


def main():
    args = argparse.ArgumentParser(description=__doc__)
    args.add_argument("--sdk", type=Path, required=True)
    args.add_argument("--elf", type=Path, required=True)
    args.add_argument("--tokens", type=Path, help="Exact-version recovered token registry, for serializer-backed native enum predicates")
    args.add_argument("--parser-bridge", type=Path, required=True)
    args.add_argument("--game-root", type=Path, required=True)
    args.add_argument("--content-layers", type=Path, help="Optional JSON array of {root, replace_paths}, in confirmed load order, after base game")
    args.add_argument("--save", type=Path, required=True, help="An immutable, already archived save; never the current autosave")
    args.add_argument("--output", type=Path, required=True)
    args.add_argument("--objects-per-type", type=int, default=512)
    args.add_argument("--candidates", type=int, default=16)
    args.add_argument("--fact-cache", type=Path, help="Reuse an immutable fact cache only after exact save/content hash verification")
    args.add_argument("--feedback-report", type=Path, action="append", default=[])
    args.add_argument("--recover-values", action="store_true", help="Refine native value/layout/lifecycle evidence from the exact ELF; emit a new SDK, never replace a production header")
    args.add_argument("--lifecycle-evidence", type=Path, action="append", default=[], help="Existing exact-build paired Factory/Destroy reports; never transfer legality or object candidates")
    args.add_argument("--audit-baseline", type=Path, help="Immutable previous offline report; record all classification and recovery transitions")
    args.add_argument("--search-game-sources", action="store_true", help="Batch reference search in original scripts, English localization and GUI files; never an ABI proof")
    args.add_argument("--spatial-model-root", type=Path, help="Explicit existing save-map source directory; reuse its API for this exact frozen save")
    values = args.parse_args()
    started = time.monotonic()
    sdk = json.loads(values.sdk.read_text(encoding="utf-8"))
    parser_sha256 = hashlib.sha256(values.parser_bridge.read_bytes()).hexdigest()
    values.output.mkdir(parents=True, exist_ok=False)
    source_manifest = archive_sources(values.output, values.parser_bridge)
    image = ElfImage(values.elf)
    if values.recover_values:
        from sdk_recovery.value_recovery import refine_catalog
        from sdk_recovery.callsite_arguments import apply_callsite_evidence
        from sdk_recovery.emit_ogas import emit_header
        reports = [(str(p), json.loads(p.read_text(encoding="utf-8"))) for p in values.lifecycle_evidence]
        token_names = {int(k, 0): v for k, v in json.loads(values.tokens.read_text(encoding="utf-8"))["tokens"].items()} if values.tokens else {}
        improvements = refine_catalog(image, sdk, lifecycle_reports=reports, tokens=token_names)
        if values.tokens:
            from sdk_recovery.value_recovery import recover_save_collection_bindings
            sdk["save_collection_bindings"] = recover_save_collection_bindings(image, sdk, token_names)
        apply_callsite_evidence(sdk)
        write_new(values.output / "native_value_recovery.json", improvements)
        write_new(values.output / "recovered_linux_sdk.json", sdk)
        emit_header(sdk, values.output / "recovered_linux_sdk.hpp")
    sdk_fingerprint = catalog_fingerprint(sdk)
    spatial = None
    layers = [ContentLayer(values.game_root)]
    if values.content_layers:
        for layer in json.loads(values.content_layers.read_text(encoding="utf-8")):
            layers.append(ContentLayer(Path(layer["root"]), tuple(layer.get("replace_paths", []))))
    with CwtoolsParser(values.parser_bridge) as parser:
        print("Parsing external game rules, triggers and definitions with CWTools", flush=True)
        definition_families = discover_definition_families(sdk, values.game_root)
        families = tuple(sorted({"game_rules", "scripted_triggers", "planet_classes"} | set(definition_families.values())))
        content = load_content(parser, tuple(layers), families)
        content.definition_families = definition_families
        write_new(values.output / "content.json", {"files": content.files, "errors": content.errors,
                  "ambiguous_definitions": sorted(content.ambiguous), "fingerprint": content.fingerprint,
                  "definition_families": content.definition_families,
                  "engine_loaded": False, "layers": [{"root": str(l.root), "replace_paths": l.replace_paths} for l in layers]})
        print("Reading frozen save (no process or runtime connection)", flush=True)
        if values.fact_cache:
            world, snapshot = restore_world_cache(json.loads(values.fact_cache.read_text(encoding="utf-8")), values.save, content, parser_sha256,
                native_collection_bindings=sdk.get("save_collection_bindings", ()))
        else:
            world, snapshot = load_snapshot(parser, values.save, content, per_type=values.objects_per_type,
                native_collection_bindings=sdk.get("save_collection_bindings", ()))
        write_new(values.output / "snapshot.json", snapshot)
        write_new(values.output / "save_facts.json", world_cache(world, snapshot, content, parser_sha256))
    if values.spatial_model_root:
        from script_candidates.spatial import load_spatial_model
        print("Reusing the save spatial model for the same frozen save", flush=True)
        spatial = load_spatial_model(values.spatial_model_root, values.save, snapshot["sha256"], values.output / "spatial-model")
    inputs = values.output / "inputs"
    inputs.mkdir()
    for name, path in (("linux_sdk.json", values.sdk), ("linux_tokens.json", values.tokens), ("fixture.sav", values.save)):
        if path:
            shutil.copyfile(path, inputs / name)
    for n, path in enumerate(values.lifecycle_evidence):
        shutil.copyfile(path, inputs / (f"lifecycle-evidence-{n:02d}.json"))
    if values.audit_baseline:
        shutil.copyfile(values.audit_baseline, inputs / "audit-baseline.json")
    if hashlib.sha256((inputs / "fixture.sav").read_bytes()).hexdigest() != snapshot["sha256"]:
        raise ValueError("Archived fixture differs from analyzed save")
    print("Indexing exact ELF and existing SDK for all Commands", flush=True)
    discovery = Discovery(image, sdk, set(content.family("game_rules")))
    write_new(values.output / "rule_wrappers.json", list(discovery.wrappers.values()))
    rows, analyses = [], []
    for command in sdk["commands"]:
        analyses.append((discovery.command(command), extract_guards(image, command, sdk["platform"])))
    predicates, predicate_hints = [], [[] for _ in analyses]
    if values.tokens:
        token_registry = json.loads(values.tokens.read_text(encoding="utf-8"))
        tokens = {int(key, 0): name for key, name in token_registry["tokens"].items()}
        predicates, predicate_hints = discover_predicates(image, discovery, [a[0] for a in analyses], sdk, tokens)
    write_new(values.output / "native_predicates.json", predicates)
    with (values.output / "progress.jsonl").open("x", encoding="utf-8") as journal:
        for index, command in enumerate(sdk["commands"]):
            paths, native = analyses[index]
            paths["predicate_hints"] = predicate_hints[index]
            row = plan_command(command, index, sdk, world, content, snapshot, paths, native, candidate_limit=values.candidates, sdk_fingerprint=sdk_fingerprint, spatial=spatial)
            audit = audit_command(command, row, sdk, snapshot, native_neighborhood(image, command, sdk))
            # Preserve old candidate-search reasons without presenting caller
            # input or snapshot absence as an ABI failure.
            row["candidate_generation_diagnostics"] = row["blockers"]
            row["blockers"] = sorted({gap["kind"] + (":" + gap["field"] if gap.get("field") else "") for gap in audit["technical_gaps"]})
            row["status"] = audit["primary_status"]
            row["semantic_audit"] = audit
            rows.append(row)
            journal.write(json.dumps({"index": index, "command": row["command_name"], "candidates": len(row["candidates"]), "blockers": row["blockers"]}) + "\n")
            journal.flush()
            if index % 50 == 0:
                print(f"Analyzed {index + 1}/{len(sdk['commands'])}", flush=True)
    if values.search_game_sources:
        print("Searching original script/localization/UI reference anchors", flush=True)
        references = search_game_sources(values.game_root, [r["semantic_audit"] for r in rows])
        write_new(values.output / "game_source_references.json", references)
        for row in rows:
            row["semantic_audit"]["game_source_references"] = references["commands"].get(row["command_name"], [])
    feedback = Feedback()
    imported = [feedback.load_report(path, sdk["build_id"]) for path in values.feedback_report]
    write_new(values.output / "feedback.json", {"sources": imported, "summary": feedback.summary(), "observations": feedback.rows})
    write_new(values.output / "native_functions.json", list(discovery.cache.values()))
    result = {"schema_version": "iag.offline_script_native_candidates.v1", "created_at": datetime.now(UTC).isoformat(),
              "elapsed_seconds": time.monotonic() - started, "build_id": sdk["build_id"],
              "elf_sha256": sdk["sha256"], "sdk_file_sha256": hashlib.sha256(values.sdk.read_bytes()).hexdigest(),
              "parser_bridge_sha256": hashlib.sha256(values.parser_bridge.read_bytes()).hexdigest(),
              "token_registry_sha256": hashlib.sha256(values.tokens.read_bytes()).hexdigest() if values.tokens else None,
              "tool_sources": source_manifest,
              "tool_sources_changed_during_run": any(hashlib.sha256((Path(__file__).resolve().parents[3] / row["path"]).read_bytes()).hexdigest() != row["sha256"] for row in source_manifest),
              "snapshot": snapshot, "content_fingerprint": content.fingerprint, "parser": "CWTools 0.6.0-alpha",
              "summary": summarize(rows), "feedback": feedback.summary(), "commands": rows,
              "limitations": ["Script rules are necessary but not complete", "External content is not an engine-loaded definition database",
                "Reachable native rules and unique-type associations are advisory until argument and path necessity are proven",
                "No native validator or game process was called in this offline run", "Constraint-plan native gate requires a future revision-6 runtime validation window"]}
    write_new(values.output / "report.json", result)
    semantic_result = {"schema_version": "iag.command_semantic_audit.v1",
        "build_id": sdk["build_id"], "elf_sha256": sdk["sha256"], "sdk_fingerprint": sdk_fingerprint,
        "summary": audit_summary([r["semantic_audit"] for r in rows]),
        "commands": [r["semantic_audit"] for r in rows]}
    if values.audit_baseline:
        baseline = json.loads(values.audit_baseline.read_text(encoding="utf-8"))
        if baseline.get("build_id") != sdk["build_id"] or baseline.get("elf_sha256") != sdk["sha256"]:
            raise ValueError("Audit baseline must match exact ELF identity")
        old = {r["class_name"]: r for r in baseline["commands"]}
        transitions = [{"command": r["command_name"], "previous_candidates": len(old[r["class_name"]]["candidates"]),
            "current_candidates": len(r["candidates"]), "previous_search_diagnostics": old[r["class_name"]]["blockers"],
            "current_primary_status": r["status"], "typed_constructible": r["semantic_audit"]["can_construct_with_typed_inputs"]}
            for r in rows if r["class_name"] in old]
        semantic_result["baseline_comparison"] = {"source": str(values.audit_baseline), "all_transitions": transitions,
            "previously_without_candidates": sum(t["previous_candidates"] == 0 for t in transitions),
            "previously_without_candidates_by_current_status": dict(__import__("collections").Counter(t["current_primary_status"] for t in transitions if t["previous_candidates"] == 0))}
    write_new(values.output / "semantic_audit.json", semantic_result)
    write_new(values.output / "recovery_worklist.json", {"build_id": sdk["build_id"], "elf_sha256": sdk["sha256"], "groups": recovery_worklist(rows)})
    print(json.dumps({key: value for key, value in result["summary"].items() if key != "blockers"}, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
