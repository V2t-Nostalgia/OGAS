"""Evidence-based parameter provenance and construction capability audit.

Candidate availability, caller input and native ABI are independent dimensions.
No Command-specific allow/deny list, fabricated parameter or production action.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from enum import Enum
import hashlib
import re
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict

from sdk_recovery.emit_ogas import field_layout, population_layout_complete, recovered_command_name


class ParameterSource(str, Enum):
    CALLER = "caller_input"
    OBJECT = "game_object_reference"
    DEFINITION = "game_definition_choice"
    INTERNAL = "engine_generated_context"
    ENUM = "native_enum_choice"
    SCALAR = "native_scalar_candidate_domain"
    SPATIAL = "game_spatial_model"
    BINDING = "parameter_binding_not_yet_recovered"


class ParameterContract(BaseModel):
    model_config = ConfigDict(strict=True, frozen=True, extra="forbid")
    field: str
    storage_kind: str
    native_type: str | None
    source: ParameterSource
    setter: str | None
    writable: bool
    supplied_candidates: int
    requirement: str | None
    evidence: tuple[dict, ...]


BUILDERS = {"ref": "SetObjectId", "i32": "SetSigned", "i64": "SetSigned",
            "u32": "SetUnsigned", "u64": "SetUnsigned", "u8": "SetUnsigned",
            "bool": "SetUnsigned", "game_date32": "SetUnsigned", "string": "SetText",
            "native_text_value": "SetText", "reference_array": "SetReferenceList",
            "definition_pointer": "SetDefinitionKey"}

# Native subsystem anchors, never substring checks on Command names. Network
# session calls alone do not mean lobby: normal gameplay uses the same session.
DEFERRED_SUBSYSTEMS = {
    "CLobbyCoopGroupsManager": "lobby_cooperative_membership",
    "CLargeFileHandler": "file_transfer",
    "CChatBuffer": "chat_transport",
    "CChatMessage": "chat_transport",
    "CChatChannel": "chat_transport",
    "CChatSyncAllCommand": "chat_transport",
    "CGuiPresenceManager": "multiplayer_gui_presence",
    "CHotJoinSetup": "hotjoin_synchronization",
    "CFrontEndIdler": "game_setup",
    "NGameSetupSync": "game_setup_synchronization",
    "COosChecks": "lockstep_synchronization",
    "CGameCamera": "camera_presence",
}

DEFERRED_METHODS = {
    "CIngameLobby::PlayerArrived": "multiplayer_lobby",
    "CIngameLobby::SetReadyAfterHotjoin": "hotjoin_synchronization",
    "CIngameLobby::PostSaveGameLoadSyncDone": "hotjoin_synchronization",
    "CGameState::OnStartResync": "lockstep_synchronization",
    "CGameState::HandleTurnTick": "lockstep_tick",
    "CRandom::SynchronisedSeed": "lockstep_synchronization",
    "AccessCheatManager": "diagnostic_cheat_control",
    "CHuman::SetSelectedCountry": "player_controller_assignment",
}


def _reference_types(command):
    return {f.get("ref") for f in command.get("population_fields", command["fields"]) if f.get("ref")}


def command_phase(command, native_calls, callers):
    matches, strong = [], False
    for call in native_calls:
        owner = call["name"].split("::", 1)[0]
        if owner in DEFERRED_SUBSYSTEMS:
            matches.append({"phase": DEFERRED_SUBSYSTEMS[owner], "evidence": call})
        method = call["name"].split("(", 1)[0].removesuffix(" const")
        if method in DEFERRED_METHODS:
            matches.append({"phase": DEFERRED_METHODS[method], "evidence": call})
            strong = strong or method == "CHuman::SetSelectedCountry"
    for call in callers:
        owner = call.get("caller", "").split("::", 1)[0]
        if owner in {"CGameSetup", "NOosChecksums"}:
            matches.append({"phase": "game_setup_or_sync_producer", "evidence": call})
    for typ in _reference_types(command):
        if typ in DEFERRED_SUBSYSTEMS:
            matches.append({"phase": DEFERRED_SUBSYSTEMS[typ], "evidence": {
                "source": "typed_serializer_reference", "native_type": typ}})
    core = _reference_types(command) & {"CCountry", "CFleet", "CPlanet", "CColony", "CArmy", "CLeader", "CShip", "CStarbase"}
    # A manager used inside an empire action is not by itself a non-core action.
    deferred = bool(matches) and (not core or strong)
    diagnostic = [c for c in callers if "ImGui::" in c.get("caller", "")]
    return {"deferred": deferred, "phase": matches[0]["phase"] if deferred else "runtime_or_unclassified",
            "evidence": matches, "diagnostic_producer_evidence": diagnostic,
            "reason": ("native_controller_assignment_mutator" if strong else "native_subsystem_and_absence_of_empire_object_scope") if deferred else
                      "not_excluded_by_English_command_name"}


def field_contract(field, domain, command, sdk, snapshot, callers):
    kind, off, width, writable = field_layout(field, sdk["platform"])
    native_type = field.get("ref") or field.get("definition_type") or field.get("native_type") or field.get("enum_type")
    evidence = [{"source": "native_serializer", "rva": field.get("evidence_rva"),
                 "writer": field.get("writer"), "offset": off, "width": width}]
    for key in ("value_recovery", "native_record_source", "native_counter_record_identity", "native_coordinate_member"):
        if field.get(key):
            evidence.append({"source": key, **field[key]})
    evidence += [{"source": "constructor_parameter", **e} for e in field.get("constructor_parameter_evidence", [])]
    evidence += [{"source": "producer_callsite", **e} for e in field.get("callsite_parameter_evidence", [])]
    evidence += [{"source":"native_member_consumer_argument", **e} for e in field.get("native_consumer_evidence", [])]
    available = domain.get("available", 0)
    requirement, source = None, ParameterSource.BINDING
    if kind in {"ref", "reference_array"}:
        source = ParameterSource.OBJECT
        obj = snapshot.get("objects", {}).get(field.get("ref"))
        if obj:
            evidence.append({"source": "frozen_save_index", "native_type": field.get("ref"), **obj})
        if obj and obj.get("parsed", 0):
            requirement = None if kind == "ref" else "caller_selects_nonempty_ordered_reference_list"
        elif obj and obj.get("absence_proven"):
            requirement = "required_object_absent_in_frozen_fixture"
        else:
            requirement = "save_candidate_provider_not_proven_empty"
    elif kind == "definition_pointer":
        source = ParameterSource.DEFINITION
        pools = [d for d in sdk.get("definition_databases", []) if d["class"] == field.get("definition_type")]
        if len({(d.get("database_rva"), d.get("data_offset")) for d in pools}) > 1:
            requirement = "definition_pool_selection_requires_native_producer_binding"
            evidence += [{"source": "native_definition_database_pool", **d} for d in pools]
        if not available:
            requirement = "effective_definition_database_or_content_mapping_required"
    elif field.get("writer") == "CWriter::WriteLabel(int)":
        source = ParameterSource.INTERNAL
        requirement = "serializer_group_layout_requires_native_member_binding"
    elif field.get("native_counter_record_identity"):
        source = ParameterSource.INTERNAL
        requirement = "engine_record_identity_and_correlated_fields_required"
    elif field.get("scoped_reference_evidence"):
        source = ParameterSource.INTERNAL
        bound = [b for b in sdk.get("scoped_id_bindings", []) if b["command_class"] == command["class"] and b["field_offset"] == off]
        if len(bound) == 1 and kind == "u32":
            requirement = "existing_native_country_scoped_provider_query_required" if not available else None
            evidence.append({"source": "existing_sdk_probe_ScopedBindingFor_EnumerateScoped", **bound[0]})
        else:
            requirement = "country_scoped_record_binding_required" if not available else None
        evidence += [{"source": "native_scoped_lookup", **e} for e in field["scoped_reference_evidence"]]
    elif field.get("native_parameter_source", {}).get("kind") == "session_human_slot":
        source = ParameterSource.INTERNAL
        requirement = "session_actor_slot_binding_required"
        evidence.append({"source":"native_typed_consumer_dataflow", **field["native_parameter_source"]})
    elif field.get("native_coordinate_member"):
        role = field["native_coordinate_member"]["role"]
        if role in {"x", "y"} and not available:
            source = ParameterSource.CALLER
            requirement = "typed_local_coordinate_or_frozen_spatial_model_required"
        else:
            source = ParameterSource.SPATIAL
            requirement = None
    elif kind == "native_text_value" and (field.get("native_copy_parameter_evidence") or
            field.get("name") in command.get("observed_text_input_fields", [])):
        # A native text-valued by-reference input, copied into this field by the
        # real constructor. This is caller data, not a required existing object.
        source = ParameterSource.CALLER
        requirement = "caller_text_required"
    elif kind == "string" and any("RenameDialog::DoRename(" in c.get("caller", "") for c in callers):
        source = ParameterSource.CALLER
        requirement = "caller_text_required"
        evidence += [{"source": "native_edit_dialog_producer", **c} for c in callers if "RenameDialog::DoRename(" in c.get("caller", "")]
    elif kind == "bool" or field.get("enum_type"):
        source = ParameterSource.ENUM
        if not available:
            requirement = "native_enum_domain_required"
    elif field.get("scalar_candidates"):
        source = ParameterSource.SCALAR
        evidence.append({"source":"recovered_scalar_domain_not_an_enum_or_complete_legality_rule",
                         "candidates":field["scalar_candidates"]})
        if not available:
            requirement = "native_scalar_domain_binding_required"
    elif kind == "game_date32":
        source = ParameterSource.INTERNAL
        requirement = "existing_native_game_date_query_required"
        evidence.append({"source": "existing_sdk_probe_game_date32_population",
                         "profile_field": "claim_war_commands.current_game_date_offset",
                         "representation": "native_uint32_not_reencoded_from_calendar_text"})
    elif field.get("value_recovery", {}).get("units"):
        requirement = ("fixed_point_parameter_origin_or_domain_required" if field["value_recovery"].get("fixed_scale")
                       else "fixed_point_native_unit_conversion_and_parameter_origin_required")
    else:
        requirement = "producer_argument_or_native_consumer_binding_required"
    return ParameterContract(field=field.get("name") or "<unresolved_token>", storage_kind=kind,
        native_type=native_type, source=source, setter=BUILDERS.get(kind), writable=writable,
        supplied_candidates=available, requirement=requirement, evidence=tuple(evidence))


def native_neighborhood(image, command, catalog):
    from sdk_recovery.value_recovery import normal_flow
    from capstone.x86 import X86_OP_IMM
    functions, calls, unresolved, literals, parameter_sources, consumers = [], [], [], [], {}, defaultdict(list)
    from sdk_recovery.array_recovery import argument_locations
    # The registered vtable, not a class-name substring, selects execution.
    table = image.read(command["vtable"], 26 * 8)
    import struct
    addresses = {command["is_valid"], command["factory"], command["deleting_destructor"]}
    for offset in range(0, len(table) - 7, 8):
        address = struct.unpack_from("<Q", table, offset)[0]
        name = image.target_name(address)
        if name.startswith(command["class"] + "::Execute") or name.startswith(command.get("serializer_owner", "\0") + "::Execute"):
            addresses.add(address)
    for address in sorted(addresses):
        symbol = image.by_address.get(address)
        if not symbol:
            unresolved.append({"rva": address, "reason": "function_symbol_missing"})
            continue
        body, cfg = normal_flow(image, symbol)
        locations, location_complete = argument_locations(body) if address == command["is_valid"] or "::Execute" in image.name(symbol) else ({},False)
        if not location_complete or not cfg["complete"]:
            locations = {}
        functions.append({"rva": address, "name": image.name(symbol), "size": symbol["size"], "cfg": cfg})
        pcs = {i.address for i in body}
        for i in body:
            # Search anchors only. A readable string's existence does not prove
            # that a field has a particular meaning or memory representation.
            if i.mnemonic == "lea" and len(i.operands) == 2 and i.operands[1].type == 3:
                mem = i.operands[1].mem
                if i.reg_name(mem.base) == "rip" and not mem.index:
                    rva = i.address + i.size + mem.disp
                    raw = image.read(rva, 256).split(b"\0", 1)[0]
                    if re.fullmatch(rb"[A-Za-z][A-Za-z0-9_.]{3,127}", raw):
                        literals.append({"value": raw.decode("ascii"), "string_rva": rva, "reference_rva": i.address})
            if i.mnemonic not in {"call", "jmp"} or not i.operands:
                continue
            if i.operands[0].type == X86_OP_IMM:
                target = i.operands[0].imm
                if target not in pcs:
                    name = image.target_name(target)
                    calls.append({"call_rva": i.address, "target_rva": target, "name": name, "caller_rva": address})
                    for reg in ("rdi","rsi","rdx","rcx","r8","r9"):
                        origins = locations.get(i.address,{}).get(reg,frozenset({None}))
                        if len(origins)!=1:
                            continue
                        origin = next(iter(origins))
                        if not origin or origin[0] not in {"this","member"}:
                            continue
                        matching = [f for f in command.get("population_fields",command["fields"]) if
                                    f.get("linux_off")==origin[1] and f.get("name")]
                        if len(matching)==1:
                            consumers[matching[0]["name"]].append({"call_rva":i.address,"callee_rva":target,
                                "callee":name,"argument_register":reg,"origin":list(origin),
                                "meaning":"member_location_flow_not_immutable_input_constraint"})
                    if name in {"CGameState::GetHuman const(int)", "CGameState::AccessHuman(int)"}:
                        origins = locations.get(i.address, {}).get("rsi",frozenset({None}))
                        origin = next(iter(origins)) if len(origins)==1 else None
                        if origin and origin[0] == "member" and origin[2]==4:
                            matching = [f for f in command.get("population_fields",command["fields"])
                                        if f.get("linux_off") == origin[1] and field_layout(f,catalog["platform"])[0] in {"i32","u32"}]
                            if len(matching) == 1:
                                parameter_sources[matching[0]["name"]] = {"kind":"session_human_slot",
                                    "field_offset":field_layout(matching[0],catalog["platform"])[1], "call_rva":i.address,"callee_rva":target,
                                    "callee":name,"abi_argument":"rsi","evidence":"command_field_to_native_human_lookup"}
            else:
                unresolved.append({"call_rva": i.address, "caller_rva": address, "reason": "indirect_native_call", "operand": i.op_str})
    constructors = {e["constructor_rva"] for f in command.get("population_fields", command["fields"])
                    for e in f.get("constructor_parameter_evidence", [])}
    callers = [c for c in catalog.get("constructor_callsites", []) if c.get("instruction_verified") and c.get("constructor_rva") in constructors]
    producer_neighborhood = []
    for address in sorted({c["caller_rva"] for c in callers}):
        symbol = image.by_address.get(address)
        if not symbol:
            continue
        body, cfg = normal_flow(image, symbol)
        direct = [{"call_rva": i.address, "target_rva": i.operands[0].imm,
                   "name": image.target_name(i.operands[0].imm)} for i in body
                  if i.mnemonic == "call" and i.operands and i.operands[0].type == X86_OP_IMM]
        producer_neighborhood.append({"rva": address, "name": image.name(symbol), "cfg_complete": cfg["complete"], "calls": direct})
    return {"functions": functions, "calls": calls, "indirect_edges": unresolved,
            "producer_callsites": callers, "producer_neighborhood": producer_neighborhood,
            "native_literal_search_anchors": literals, "native_parameter_sources": parameter_sources,
            "field_consumers":dict(consumers)}


def search_game_sources(game_root: Path, rows, *, max_hits=8):
    """Batch exact-token reference search, explicitly not semantic inference."""
    queries = defaultdict(set)
    for row in rows:
        command = row["command_name"]
        neighborhood = row["native_neighborhood"]
        tokens = {e["value"] for e in neighborhood.get("native_literal_search_anchors", [])}
        tokens.add(command.removesuffix("_command"))
        for p in row["parameter_contracts"]:
            typ = p.get("native_type") or ""
            if typ.startswith("C") and len(typ) > 3:
                tokens.add(re.sub(r"(?<!^)(?=[A-Z][a-z])", "_", typ[1:]).lower().removesuffix("_type"))
        for token in tokens:
            if len(token) >= 4:
                queries[token.lower()].add(command)
    hits, files, errors = defaultdict(list), [], []
    paths = sorted(set((game_root / "interface").glob("*.gui")) |
                   set((game_root / "common").glob("**/*.txt")) |
                   set((game_root / "localisation" / "english").glob("*.yml")))
    # One bounded pass over game files, not one full-directory search per field.
    # Execution is deliberately sequential; no game-thread work or background
    # resident service. The parser remains CWTools, this is a reference locator.
    token_pattern = re.compile(r"[A-Za-z][A-Za-z0-9_.]*")
    for path in paths:
        raw = path.read_bytes()
        if len(raw) > 16 * 1024 * 1024:
            errors.append({"path": str(path), "reason": "reference_file_size_budget"})
            continue
        try:
            text = raw.decode("utf-8-sig")
        except UnicodeError as error:
            errors.append({"path": str(path), "reason": str(error)})
            continue
        identity = {"path": str(path), "sha256": hashlib.sha256(raw).hexdigest()}
        used = False
        for number, line in enumerate(text.splitlines(), 1):
            keys = {t.lower() for t in token_pattern.findall(line)} & queries.keys()
            for key in keys:
                for command in queries[key]:
                    if len(hits[command]) < max_hits:
                        hits[command].append(identity | {"line": number, "query": key, "excerpt": line.strip()[:240]})
                        used = True
        if used:
            files.append(identity)
    return {"files_searched": len(paths), "matching_files": files, "errors": errors,
            "commands": dict(hits), "meaning": "search_references_not_field_binding_or_ABI_proof"}


def audit_command(command, candidate_row, sdk, snapshot, neighborhood):
    domains = {d["field"]: d for d in candidate_row["domains"]}
    callers = neighborhood["producer_callsites"]
    contracts = [field_contract(f | ({"native_parameter_source": neighborhood["native_parameter_sources"][f["name"]]}
                    if f.get("name") in neighborhood.get("native_parameter_sources", {}) else {}) |
                    {"native_consumer_evidence":neighborhood.get("field_consumers",{}).get(f.get("name"),[])},
                    domains.get(f.get("name"), {}), command, sdk, snapshot, callers)
                 for f in command.get("population_fields", command["fields"])]
    phase = command_phase(command, neighborhood["calls"], callers)
    technical, state, caller, internal, semantic = [], [], [], [], []
    region = command.get("native_object_region_layout",{})
    unbound_fields = {r["field"] for r in region.get("unbound_members",[])} if region.get("complete") else set()
    semantic_member_gaps = [{"field":f,"requirement":"native_array_serializer_projection_binding_required"} for f in sorted(unbound_fields)]
    if not population_layout_complete(command, sdk["platform"]) and not unbound_fields:
        technical.append({"kind": "population_layout", "gaps": command.get("nested_recovery_gaps", []),
                          "serializer_subobjects": command.get("serializer_subobjects", [])})
    if not command.get("lifecycle_probe_safe"):
        technical.append({"kind": "lifecycle_effects", "factory_rva": command.get("factory"),
                          "destructor_rva": command.get("deleting_destructor"),
                          "normal_flow_recovery": command.get("lifecycle_recovery")})
    object_types = {d["class"] for d in sdk.get("object_databases", [])}
    definition_types = {d["class"] for d in sdk.get("definition_databases", [])}
    for contract in contracts:
        if (not contract.writable or contract.setter is None) and contract.field not in unbound_fields:
            array_evidence = [a for a in command.get("array_recovery_attempts",[]) if a["field"]==contract.field]
            technical.append({"kind": "field_layout_or_native_value_assignment", "field": contract.field,
                              "storage_kind": contract.storage_kind, "native_type": contract.native_type,
                              "native_array_recovery":array_evidence})
        if contract.source == ParameterSource.OBJECT and contract.native_type not in object_types:
            internal.append({"kind": "native_object_resolver_missing", "field": contract.field, "type": contract.native_type})
        if contract.source == ParameterSource.DEFINITION and contract.native_type not in definition_types:
            internal.append({"kind": "effective_definition_resolver_not_in_generated_catalog", "field": contract.field, "type": contract.native_type})
        if contract.requirement:
            requirement = {"field": contract.field, "requirement": contract.requirement, "native_type": contract.native_type}
            if contract.source == ParameterSource.CALLER or contract.requirement == "caller_selects_nonempty_ordered_reference_list":
                caller.append(requirement)
            elif contract.source == ParameterSource.OBJECT:
                state.append(requirement)
            elif contract.source == ParameterSource.INTERNAL:
                requirement["capability_recovered"] = contract.requirement.startswith("existing_native_")
                internal.append(requirement)
            elif contract.supplied_candidates == 0 or contract.source == ParameterSource.BINDING or contract.source == ParameterSource.DEFINITION:
                semantic.append(requirement)
    semantic += semantic_member_gaps
    constructible = not technical and not unbound_fields
    if phase["deferred"]:
        primary = "deferred_noncore"
    elif technical:
        primary = "abi_or_lifecycle_gap"
    elif any(not r.get("capability_recovered") for r in internal):
        primary = "engine_parameter_binding_gap"
    elif semantic:
        primary = "semantic_parameter_binding_gap"
    elif any(s["requirement"] != "required_object_absent_in_frozen_fixture" for s in state):
        primary = "state_discovery_gap"
    elif state:
        primary = "waiting_game_state"
    elif internal:
        primary = "waiting_engine_state_query"
    elif caller:
        primary = "waiting_caller_parameters"
    else:
        primary = "typed_constructible"
    # Preserve detailed attempts even when a command has several independent
    # requirements. A readable label is not a substitute for a recovery trace.
    attempts = [
        {"path": "exact_ELF_factory_vtable_serializer_destructor", "status": "recovered" if constructible else "incomplete", "functions": neighborhood["functions"]},
        {"path": "native_constructor_parameter_and_UI_AI_callsites", "verified_callsites": len(callers), "evidence": callers},
        {"path": "SDK_typed_object_and_definition_databases", "object_types": sorted(_reference_types(command)), "native_resolver_count": sum(c.native_type in object_types for c in contracts)},
        {"path": "frozen_save_numeric_and_nested_container_index", "snapshot_sha256": snapshot["sha256"], "requirements": state},
        {"path": "script_rules_and_native_necessary_guards", "rule_paths": candidate_row["native_rule_paths"], "guards": candidate_row["native_constraints"]},
    ]
    return {"command_name": candidate_row["command_name"], "class_name": command["class"],
        "primary_status": primary, "can_construct_with_typed_inputs": constructible,
        "has_complete_fixture_candidates": bool(candidate_row["candidates"]), "runtime_phase": phase,
        "parameter_contracts": [c.model_dump(mode="json") for c in contracts],
        "technical_gaps": technical, "caller_requirements": caller, "state_requirements": state,
        "engine_binding_requirements": internal, "semantic_binding_requirements": semantic,
        "attempted_recovery_paths": attempts, "native_neighborhood": neighborhood,
        "historical_validation_evidence": command.get("historical_validation_observations", []),
        "native_array_recovery_attempts":command.get("array_recovery_attempts",[]),
        "native_object_region_layout":region,
        "native_calls_this_audit": 0, "production_promotions": 0}


def audit_summary(rows):
    return {"catalog_commands": len(rows), "exclusive_primary_status": dict(Counter(r["primary_status"] for r in rows)),
        "independent_dimensions_not_additive": {
            "typed_constructible_with_inputs": sum(r["can_construct_with_typed_inputs"] for r in rows),
            "waiting_caller_parameters": sum(bool(r["caller_requirements"]) for r in rows),
            "waiting_game_state": sum(any(s["requirement"] == "required_object_absent_in_frozen_fixture" for s in r["state_requirements"]) for r in rows),
            "state_discovery_gaps": sum(any(s["requirement"] != "required_object_absent_in_frozen_fixture" for s in r["state_requirements"]) for r in rows),
            "abi_or_lifecycle_gaps": sum(bool(r["technical_gaps"]) for r in rows),
            "engine_parameter_binding_gaps": sum(any(not x.get("capability_recovered") for x in r["engine_binding_requirements"]) for r in rows),
            "existing_engine_provider_queries": sum(any(x.get("capability_recovered") for x in r["engine_binding_requirements"]) for r in rows),
            "semantic_parameter_binding_gaps": sum(bool(r["semantic_binding_requirements"]) for r in rows),
            "deferred_noncore": sum(r["runtime_phase"]["deferred"] for r in rows)},
        "native_is_valid_calls": 0, "production_promotions": 0}
