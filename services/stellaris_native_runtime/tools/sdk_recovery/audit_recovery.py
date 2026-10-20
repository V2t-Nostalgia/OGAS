#!/usr/bin/env python3
"""Join an immutable live batch with fresh offline SDK evidence, for every row.

Static eligibility is not a native validation result. Produces all blockers,
not just the first failing field, plus non-mutating test-scene prerequisites.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path

from emit_ogas import field_layout, population_layout_complete

SCENARIOS = {
    "CResolution": "An existing Galactic Community resolution/proposal; enumerate all live handles. Do not propose one automatically.",
    "CWar": "An existing war involving the selected actor; a peaceful save cannot manufacture this read-only.",
    "CFirstContact": "An active first contact for a live country.",
    "CArchaeologicalSite": "An existing archaeology site; excavation legality additionally depends on ownership and assignment.",
    "CAstralRift": "An existing astral rift and an appropriate scientific fleet.",
    "CSituation": "An active situation with a current approach; resolve script keys from that situation.",
    "CSpyNetwork": "An existing spy network owned by the selected country.",
    "CEspionageOperation": "An existing operation with the required phase/event.",
    "CConstructionQueueItem": "An already queued item; generation-checked queue and actor relationship must agree.",
    "CFleetTemplate": "An existing fleet template owned by the actor, not an assumed numeric template ID.",
    "CColony": "A live colony (not merely a colonizable CPlanet); enumerate its building/zone/queue relations.",
    "CCouncilPosition": "An unlocked native council position and an eligible leader.",
    "CMission": "An existing mission/situation-log entry.",
    "CCosmicStorm": "An existing cosmic storm and the appropriate ability/state.",
    "CPatronRelation": "An existing patron relation for the actor.",
    "CExhibit": "An existing exhibit and the required collection/exhibition state.",
}


def audit(sdk: dict, baseline: dict) -> dict:
    from scoped_id_recovery import scoped_id_bindings

    if sdk["build_id"] != baseline["build_id"]:
        raise ValueError("Cannot join evidence from different exact builds.")
    previous = {
        a["class_name"]: row for row in baseline["commands"] for a in row["attempts"]
    }
    object_types = {d["class"] for d in sdk.get("object_databases", [])}
    definition_types = {d["class"] for d in sdk.get("definition_databases", [])}
    scoped = {(r["command_class"], r["field_offset"]) for r in scoped_id_bindings(sdk)}
    # These existing exact-build profile resolvers predate generated databases.
    definition_types |= {
        "CPolicyGroup",
        "CTradition",
        "CAscensionPerk",
        "CGovernmentCouncilorType",
        "CResolutionType",
        "CWarGoalType",
        "CEspionageOperationType",
    }
    rows = []
    for index, command in enumerate(sdk["commands"]):
        old = previous.get(
            command["class"], previous.get(command.get("serializer_owner"))
        )
        blockers, operations, scenarios = [], [], set()
        token = command.get("token_evidence", {})
        structural = all(
            command.get(k)
            for k in (
                "factory",
                "size",
                "vtable",
                "is_valid",
                "deleting_destructor",
                "token_getter",
            )
        )
        structural = bool(
            structural
            and (command.get("token") or token.get("kind") == "module_global")
        )
        if not structural:
            blockers.append("factory_lifecycle_or_token_unresolved")
        layout = population_layout_complete(command, sdk["platform"])
        if not layout:
            blockers.append("population_layout_incomplete")
        has_reference = False
        for field in command.get("population_fields", command["fields"]):
            kind, offset, width, writable = field_layout(field, sdk["platform"])
            name = field.get("name") or "<unresolved_token>"
            operation = {
                "field": name,
                "kind": kind,
                "offset": offset,
                "width": width,
                "writable": writable,
                "writer_rva": field.get("evidence_rva"),
                "reference_type": field.get("ref"),
                "definition_type": field.get("definition_type"),
                "enum_type": field.get("enum_type"),
                "enum_values": field.get("scalar_candidates", []),
                "wrapper": field.get("wrapper"),
                "constructor_parameter_evidence": field.get(
                    "constructor_parameter_evidence", []
                ),
                "semantic_evidence": field.get("semantic_evidence"),
                "native_counter_record_identity": field.get(
                    "native_counter_record_identity"
                ),
                "native_record_source": field.get("native_record_source"),
                "validator_reference_evidence": field.get(
                    "validator_reference_evidence", []
                ),
                "scoped_reference_evidence": field.get("scoped_reference_evidence", []),
                "callsite_parameter_evidence": field.get(
                    "callsite_parameter_evidence", []
                ),
            }
            operations.append(operation)
            if not writable:
                blockers.append(f"field_layout:{name}:{kind}")
            if kind in ("ref", "reference_array"):
                has_reference = True
                cls = field["ref"]
                if cls not in object_types:
                    blockers.append(f"object_resolver:{cls}")
                if cls in SCENARIOS:
                    scenarios.add(cls)
            elif kind == "definition_pointer":
                cls = field.get("definition_type")
                if cls not in definition_types:
                    blockers.append(f"definition_resolver:{cls or 'unknown'}")
            elif field.get("scoped_reference_evidence"):
                if (command["class"], field.get("linux_off")) not in scoped:
                    for cls in {r["class"] for r in field["scoped_reference_evidence"]}:
                        blockers.append(f"country_scoped_candidate_provider:{cls}")
                if not all(
                    r.get("caller_country_binding")
                    == "generation_checked_command_country_reference"
                    and (binding := r.get("country_reference", {})).get("evidence")
                    == "complete_generation_checked_country_to_scoped_lookup"
                    and binding.get("country_generation_checked") is True
                    and binding.get("class") == r.get("class")
                    and binding.get("source_offset") == field.get("linux_off")
                    and binding.get("call_rva") == r.get("evidence_rva")
                    and binding.get("lookup_rva") == r.get("lookup_rva")
                    and binding.get("call_target_rva") == r.get("call_target_rva")
                    for r in field["scoped_reference_evidence"]
                ):
                    blockers.append(f"country_scope_binding_unresolved:{name}")
            elif (
                kind == "i32"
                and field.get("scalar_candidates")
                or kind in ("bool", "game_date32")
                or kind == "string"
                and field.get("native_type") == "CString"
                and name in ("name", "male", "female")
                or kind == "native_text_value"
                and name in ("name", "male", "female")
            ):
                pass
            else:
                blockers.append(f"parameter_semantics:{name}:{kind}")
        if not has_reference and not command.get("context_free_validator"):
            blockers.append("no_game_object_scope")
        rows.append(
            {
                "index": index,
                "command_name": command.get("token_name") or command["class"],
                "class_name": command["class"],
                "serializer_owner": command.get("serializer_owner"),
                "previous_status": old["status"] if old else "not_in_baseline",
                "previous_reason": old["reason"] if old else None,
                "structure_recovered": structural,
                "lifecycle_only_static_eligible": command.get(
                    "lifecycle_probe_safe", False
                ),
                "population_layout_recovered": layout,
                "validation_static_eligible": not blockers,
                "blockers": sorted(set(blockers)),
                "fields": operations,
                "scene_prerequisites": {s: SCENARIOS[s] for s in sorted(scenarios)},
                "native_calls_requiring_review": (
                    command.get("factory_evidence") or {}
                ).get("native_calls", []),
                "nested_gaps": command.get("nested_recovery_gaps", []),
                "token_evidence": token,
            }
        )
    return {
        "schema_version": "iag.sdk_recovery_gap_audit.v1",
        "build_id": sdk["build_id"],
        "evidence_level": "static_recovery_only",
        "new_native_calls": 0,
        "submitted": False,
        "execution_verified": False,
        "summary": {
            "catalog_commands": len(rows),
            "structure_recovered": sum(r["structure_recovered"] for r in rows),
            "lifecycle_only_static_eligible": sum(
                r["lifecycle_only_static_eligible"] for r in rows
            ),
            "population_layout_recovered": sum(
                r["population_layout_recovered"] for r in rows
            ),
            "validation_static_eligible": sum(
                r["validation_static_eligible"] for r in rows
            ),
            "previously_skipped_now_static_eligible": sum(
                r["validation_static_eligible"]
                and r["previous_status"] not in ("native_valid", "native_invalid")
                for r in rows
            ),
            "existing_world_only_gaps_still_static_eligible": sum(
                r["validation_static_eligible"]
                and r["previous_status"] == "missing_parameters"
                for r in rows
            ),
            "new_static_eligible_excluding_world_only_gaps": sum(
                r["validation_static_eligible"]
                and r["previous_status"]
                not in ("native_valid", "native_invalid", "missing_parameters")
                for r in rows
            ),
            "previously_completed_regressions": [
                r["command_name"]
                for r in rows
                if r["previous_status"] in ("native_valid", "native_invalid")
                and r["blockers"]
            ],
            "factory_dtor_static_eligible": sum(
                r["lifecycle_only_static_eligible"] or r["validation_static_eligible"]
                for r in rows
            ),
            "remaining_static_blocked": sum(bool(r["blockers"]) for r in rows),
            "blocker_counts_nonexclusive": dict(
                Counter(b for r in rows for b in r["blockers"])
            ),
            **sdk.get("recovery_summary", {}),
        },
        "commands": rows,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sdk", type=Path, required=True)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = audit(
        json.loads(args.sdk.read_text(encoding="utf-8")),
        json.loads(args.baseline.read_text(encoding="utf-8")),
    )
    result["sources"] = {
        str(p): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in (args.sdk, args.baseline)
    }
    args.output.mkdir(parents=True, exist_ok=False)
    with (args.output / "audit.json").open("x", encoding="utf-8") as stream:
        json.dump(result, stream, indent=2, ensure_ascii=True)
        stream.write("\n")
    lines = [
        "# Offline Recovery Gap Audit",
        "",
        "Static eligibility is not a live native call or a live_verified promotion.",
        "",
        "```json",
        json.dumps(result["summary"], indent=2),
        "```",
        "",
        "| Command | Previous | Structure | Layout | Static IsValid-ready | Remaining blockers |",
        "|---|---|---|---|---|---|",
    ]
    lines += [
        f"| {r['command_name']} | {r['previous_status']} | {r['structure_recovered']} | {r['population_layout_recovered']} | {r['validation_static_eligible']} | {'; '.join(r['blockers'])} |"
        for r in result["commands"]
    ]
    with (args.output / "audit.md").open("x", encoding="utf-8") as stream:
        stream.write("\n".join(lines) + "\n")
    print(
        json.dumps(
            {
                k: v
                for k, v in result["summary"].items()
                if k != "blocker_counts_nonexclusive"
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
