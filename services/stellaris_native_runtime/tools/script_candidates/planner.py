"""Typed, bounded candidate search combining script/native/producer evidence."""

from __future__ import annotations

import hashlib
import heapq
import json
from collections import Counter
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from sdk_recovery.emit_ogas import catalog_fingerprint, field_layout, population_layout_complete, recovered_command_name

from .constraints import Evaluator, ObjectRef, Scope, Truth, World
from .content import Content
from .native_guards import evaluate_guard


class Binding(BaseModel):
    model_config = ConfigDict(strict=True, frozen=True, extra="forbid")
    field: str
    offset: int = Field(ge=28)
    storage_kind: Literal["ref", "i32", "u32", "u8", "bool", "i64", "u64", "definition_pointer"]
    reference_type: str | None = None
    value: int | bool | str
    source: Literal["frozen_save_reference", "sdk_enum", "producer_literal", "external_definition",
                    "frozen_save_coordinate", "native_value_ctor"]

    @model_validator(mode="after")
    def check_typed_value(self):
        if self.storage_kind in {"ref", "definition_pointer"} and not self.reference_type:
            raise ValueError("A native reference/definition type is required")
        if self.storage_kind == "definition_pointer":
            if type(self.value) is not str or not self.value or len(self.value) > 128:
                raise ValueError("A bounded definition key is required, not a pointer")
        elif self.storage_kind == "bool":
            if type(self.value) is not bool:
                raise ValueError("A strict boolean is required")
        else:
            if type(self.value) is not int:
                raise ValueError("A strict integer is required")
            bits = {"ref": 32, "i32": 32, "u32": 32, "u8": 8, "i64": 64, "u64": 64}[self.storage_kind]
            signed = self.storage_kind.startswith("i")
            low, high = (-(1 << (bits - 1)), (1 << (bits - 1)) - 1) if signed else (0, (1 << bits) - 1)
            if not low <= self.value <= high or (self.storage_kind == "ref" and self.value == 0xFFFFFFFF):
                raise ValueError("Value outside recovered storage range")
        return self


class Candidate(BaseModel):
    model_config = ConfigDict(strict=True, frozen=True, extra="forbid")
    command_name: str
    class_name: str
    build_id: str
    sdk_sha256: str
    sdk_metadata_fingerprint: str = ""
    save_sha256: str
    content_fingerprint: str
    bindings: tuple[Binding, ...] = Field(min_length=1, max_length=32)
    script_result: Literal["true", "false", "unknown"]
    advisory_score: int
    native_validation: Literal["not_called"] = "not_called"
    submitted: Literal[False] = False

    @model_validator(mode="after")
    def unique_fields(self):
        if len({binding.field for binding in self.bindings}) != len(self.bindings):
            raise ValueError("Duplicate candidate fields")
        return self

    @property
    def identity(self) -> str:
        context = [self.command_name, self.build_id, self.sdk_sha256, self.sdk_metadata_fingerprint, self.save_sha256, self.content_fingerprint,
                   [(b.field, b.storage_kind, b.reference_type, b.value) for b in self.bindings]]
        return hashlib.sha256(json.dumps(context, sort_keys=True).encode()).hexdigest()


DEFINITION_FAMILIES = {
    "CBuilding": "buildings", "CBuildingType": "buildings", "CDistrictType": "districts",
    "CZoneType": "zones", "CTechnology": "technology", "CShipSize": "ship_sizes",
    "CTradition": "traditions", "CAscensionPerk": "ascension_perks", "CResource": "strategic_resources",
    "CPolicyGroup": "policies", "CWarGoalType": "war_goals", "CResolutionType": "resolutions",
    "CEdict": "edicts", "CSituationApproach": "situation_approaches",
    "CGovernmentAuthorityType": "governments/authorities", "CJobType": "pop_jobs",
    "CGovernmentCouncilorType": "governments/councilors", "CGfxCulture": "graphical_culture",
    "CCosmicStormType": "storm_types", "COverclockType": "megastructure_overclock_types",
}


def discover_definition_families(sdk: dict, game_root) -> dict[str, str]:
    """Batch content-key hints from native type names and unique directory names.

    The mapping is external evidence only. Every proposed key must still resolve
    in the exact native definition DB before Populate; ambiguous matches are left
    unbound. This does not infer prerequisites from folder names.
    """
    import re
    def forms(name):
        name = re.sub(r"[^a-z]", "", name.lower())
        result = {name}
        if name.endswith("ies"):
            result.add(name[:-3] + "y")
        if name.endswith("es"):
            result.add(name[:-2])
        if name.endswith("s"):
            result.add(name[:-1])
        return result
    common = game_root / "common"
    directories = [p for p in common.glob("**/*") if p.is_dir() and any(p.glob("*.txt")) and
                   not {"inline_scripts", "scripted_effects", "scripted_triggers"} & set(p.relative_to(common).parts)]
    result = {typ: family for typ, family in DEFINITION_FAMILIES.items() if (common / family).is_dir()}
    types = {f["definition_type"] for c in sdk["commands"] for f in c.get("population_fields", c["fields"]) if f.get("definition_type")}
    for typ in types - result.keys():
        raw = typ.removeprefix("C")
        # Match the complete native type before its weaker Type-less spelling.
        # An inline-script directory is not a definition database with the same
        # basename (e.g. colony_types and megastructures).
        for names in (forms(raw), forms(raw.removesuffix("Type"))):
            matches = [p.relative_to(common).as_posix() for p in directories if forms(p.name) & names]
            if len(matches) == 1:
                result[typ] = matches[0]
                break
    return result


def scope_hints(command: dict, discovery: dict) -> list[dict]:
    """Expose only unambiguous typed associations; not a dataflow proof.

    A wrapper taking a Planet cannot be bound to one of two Planet fields by
    English names. Controller links require an actual native getter in the
    discovered neighborhood, and remain advisory until argument flow is proven.
    """
    fields = command.get("population_fields", command.get("fields", []))
    result = []
    for rule in discovery.get("rules", []):
        for evaluation in rule["evaluations"]:
            scope = evaluation.get("this_scope")
            if not scope or not scope.get("object"):
                continue
            typ = "C" + scope["type"]
            matches = [f for f in fields if f.get("ref") == typ]
            path = ()
            if len(matches) != 1:
                # No name-based fallback. Native controller relationships can
                # be added by the same dataflow recovery used for other refs.
                continue
            same_root = bool(evaluation.get("root_scope") and evaluation["root_scope"].get("object") == scope["object"])
            result.append({"rule": rule["rule"], "field": matches[0]["name"], "path": path,
                           "root_is_this": same_root, "native_type": typ,
                           "necessity": "UNKNOWN", "binding": "unique_native_type_advisory",
                           "wrapper_rva": rule["wrapper_rva"]})
    return result


def _unary_score(field, ref, hints, evaluator, content, predicates=()):
    score, outcomes, unknown = 0, [], set()
    rules = content.family("game_rules")
    for predicate in predicates:
        if predicate["command_field"] != field:
            continue
        fact = evaluator.world.facts.get(ref, {}).get(predicate["save_field"])
        if fact is None or not fact.complete:
            unknown.add("native_predicate_fact:" + predicate["save_field"])
            continue
        matched = fact.value == predicate["expected"]
        if predicate["operator"] == "!=":
            matched = not matched
        score += 2 if matched else -2
    for hint in hints:
        if hint["field"] != field or hint["rule"] not in rules:
            continue
        scope = Scope(ref, ref if hint["root_is_this"] else None)
        children = rules[hint["rule"]].children or ()
        # Independent top-level conjuncts can contribute evidence even when
        # another conjunct is UNKNOWN. Keep conditional chains as one unit.
        groups = (children,) if any(n.key in {"if", "else_if", "else"} for n in children) else tuple((n,) for n in children)
        for group in groups:
            result = evaluator.evaluate(group, scope)
            score += {Truth.TRUE: 2, Truth.UNKNOWN: 0, Truth.FALSE: -2}[result.truth]
            outcomes.append(result.truth)
            unknown.update(result.unknown)
    return score, outcomes, unknown


def plan_command(command: dict, index: int, sdk: dict, world: World, content: Content,
                 snapshot: dict, discovery: dict, native: dict, *, candidate_limit=16,
                 search_limit=256, domain_limit=32, sdk_fingerprint: str | None = None, spatial=None) -> dict:
    if not 1 <= candidate_limit <= 64 or not 1 <= search_limit <= 4096 or not 1 <= domain_limit <= 256:
        raise ValueError("Candidate search budget outside bounds")
    name = recovered_command_name(command, index)
    fingerprint = sdk_fingerprint or catalog_fingerprint(sdk)
    fields = command.get("population_fields", command.get("fields", []))
    hints = scope_hints(command, discovery)
    evaluator = Evaluator(world, content.family("scripted_triggers"), advisory=True)
    domains, blockers, domain_report, unknown = [], [], [], set()
    structural = all(command.get(k) for k in ("factory", "vtable", "size", "is_valid", "deleting_destructor"))
    layout = population_layout_complete(command, sdk["platform"])
    if not structural:
        blockers.append("factory_vtable_size_validator_or_lifecycle_missing")
    if not layout:
        blockers.append("population_layout_incomplete")
    if command.get("lifecycle_probe_safe") is not True:
        blockers.append("lifecycle_not_proven_safe")
    if not fields or len(fields) > 32:
        blockers.append("payload_field_count_outside_native_gate")
    if spatial and spatial.save_sha256 != snapshot["sha256"]:
        raise ValueError("Coordinate model and candidate snapshot differ")
    spatial_groups = spatial.groups(command, world, limit=domain_limit) if spatial else []
    grouped = {name for group in spatial_groups for name in group["fields"]}
    if sum(len(group["fields"]) for group in spatial_groups) != len(grouped):
        raise ValueError("Overlapping native coordinate parameter groups")
    for group in spatial_groups:
        domains.append(group["values"])
        if not group["values"]:
            blockers.append("correlated_local_coordinate_domain_missing")
    for field in fields:
        kind, offset, width, writable = field_layout(field, sdk["platform"])
        fname, values = field.get("name"), []
        if not fname or not writable:
            blockers.append("unwritable_field:" + str(fname))
            continue
        if fname in grouped:
            group = next(g for g in spatial_groups if fname in g["fields"])
            domain_report.append({"field": fname, "kind": kind,
                "reference_type": field.get("ref"), "available": group["available"],
                "used": len(group["values"]), "truncated": group["available"] > len(group["values"]),
                "ranked_by_evidence": False, "correlated_group": sorted(group["fields"]),
                "source": "same_frozen_save_system_local_model"})
            continue
        if kind == "ref":
            for ref in world.objects(field["ref"]):
                score, _, gaps = _unary_score(fname, ref, hints, evaluator, content, discovery.get("predicate_hints", ()))
                unknown.update(gaps)
                values.append((score, Binding(field=fname, offset=offset, storage_kind=kind,
                                              reference_type=field["ref"], value=ref.object_id,
                                              source="frozen_save_reference")))
        elif kind == "definition_pointer":
            family = content.definition_families.get(field.get("definition_type")) or DEFINITION_FAMILIES.get(field.get("definition_type"))
            for key in sorted(content.family(family)) if family else ():
                if len(key) > 128:
                    unknown.add("definition_key_exceeds_native_gate:" + fname)
                    continue
                values.append((0, Binding(field=fname, offset=offset, storage_kind=kind,
                                          reference_type=field.get("definition_type"), value=key,
                                          source="external_definition")))
        elif kind in {"i32", "u32", "u8", "bool", "i64", "u64"}:
            literals = []
            for evidence in field.get("callsite_parameter_evidence", []):
                literal = evidence.get("literal")
                if isinstance(literal, dict) and type(literal.get("value")) is int:
                    literals.append((literal["value"], "producer_literal", 1))
            for evidence in field.get("scalar_candidates", []):
                literals.append((evidence["value"], "sdk_enum", 0))
            # Boolean values have an intrinsic two-element domain. No other
            # unbound scalar, duration, ID or string gets a guessed default.
            if kind == "bool":
                literals += [(False, "sdk_enum", 0), (True, "sdk_enum", 0)]
            seen = set()
            for value, source, score in literals:
                if kind == "bool":
                    if value not in (0, 1):
                        continue
                    value = bool(value)
                low = -(1 << (width * 8 - 1)) if kind.startswith("i") else 0
                high = (1 << (width * 8 - (1 if kind.startswith("i") else 0))) - 1
                if value in seen or not low <= value <= high:
                    continue
                seen.add(value)
                values.append((score, Binding(field=fname, offset=offset, storage_kind=kind,
                                              value=value, source=source)))
        values.sort(key=lambda pair: (-pair[0], str(pair[1].value)))
        domain_report.append({"field": fname, "kind": kind, "reference_type": field.get("ref") or field.get("definition_type"),
                              "available": len(values), "used": min(len(values), domain_limit),
                              "truncated": len(values) > domain_limit,
                              "ranked_by_evidence": len({score for score, _ in values}) > 1})
        if not values:
            blockers.append("candidate_domain_missing:" + fname + ":" + kind)
        domains.append([(score, (binding,)) for score, binding in values[:domain_limit]])
    candidates, examined, pruned, frontier = [], 0, 0, []
    # Best-first traversal of domain ranks, not a materialized Cartesian product.
    # Uncertain script associations rank candidates, never delete them.
    if not blockers and domains:
        initial = tuple(0 for _ in domains)
        def priority(indices):
            return -sum(domains[i][position][0] for i, position in enumerate(indices))
        heapq.heappush(frontier, (priority(initial), initial))
        seen = {initial}
        while frontier and examined < search_limit and len(candidates) < candidate_limit:
            negative_score, positions = heapq.heappop(frontier)
            examined += 1
            bindings = tuple(binding for i, position in enumerate(positions) for binding in domains[i][position][1])
            values = {b.field: b.value for b in bindings}
            if any(evaluate_guard(g, values) is False for g in native.get("guards", [])):
                pruned += 1
            else:
                # Overall legality remains UNKNOWN: hardcoded checks, scope
                # binding and effective Mod content are not fully established.
                candidates.append(Candidate(command_name=name, class_name=command["class"],
                    build_id=sdk["build_id"], sdk_sha256=sdk["sha256"], sdk_metadata_fingerprint=fingerprint, save_sha256=snapshot["sha256"],
                    content_fingerprint=content.fingerprint, bindings=bindings,
                    script_result="unknown", advisory_score=-negative_score).model_dump(mode="json"))
            for i, position in enumerate(positions):
                if position + 1 >= len(domains[i]):
                    continue
                neighbor = positions[:i] + (position + 1,) + positions[i + 1:]
                if neighbor not in seen:
                    seen.add(neighbor)
                    heapq.heappush(frontier, (priority(neighbor), neighbor))
    return {"index": index, "command_name": name, "class_name": command["class"],
            "structure_recovered": bool(structural), "layout_recovered": layout,
            "native_rule_paths": discovery, "scope_hints": hints, "native_constraints": native,
            "producer_fields": sum(bool(f.get("callsite_parameter_evidence")) for f in fields),
            "domains": domain_report, "blockers": sorted(set(blockers)), "unknown_triggers": sorted(unknown),
            "candidates": candidates, "examined": examined, "proven_native_pruned": pruned,
            "search_truncated": bool(frontier), "native_is_valid_calls": 0,
            "spatial_groups": [{"fields": sorted(g["fields"]), "available": g["available"],
                "used": len(g["values"]), "rejected_not_on_native_lattice": g["rejected_not_on_native_lattice"],
                "frame": "same_system_local", "height_policy": "native_constructor_zero_no_randomize"}
                for g in spatial_groups],
            "status": "awaiting_native_validation" if candidates else "blocked_or_no_candidate",
            "eligibility": "research_only_no_production_promotion"}


def summarize(rows):
    return {"catalog_commands": len(rows), "structural": sum(r["structure_recovered"] for r in rows),
            "layouts": sum(r["layout_recovered"] for r in rows),
            "with_native_rule_paths": sum(bool(r["native_rule_paths"]["rules"]) for r in rows),
            "with_typed_rule_scope_hints": sum(bool(r["scope_hints"]) for r in rows),
            "with_producer_evidence": sum(r["producer_fields"] > 0 for r in rows),
            "with_native_payload_guards": sum(bool(r["native_constraints"]["guards"]) for r in rows),
            "with_native_predicate_hints": sum(bool(r["native_rule_paths"].get("predicate_hints")) for r in rows),
            "with_proven_native_guards": sum(any(g["necessity"] == "proven_rejection_guard" for g in r["native_constraints"]["guards"]) for r in rows),
            "with_candidates": sum(bool(r["candidates"]) for r in rows),
            "candidate_count": sum(len(r["candidates"]) for r in rows),
            "native_pruned": sum(r["proven_native_pruned"] for r in rows),
            "blockers": dict(Counter(b for r in rows for b in r["blockers"])),
            "native_is_valid_calls": 0, "submitted": False, "production_promotions": 0}
