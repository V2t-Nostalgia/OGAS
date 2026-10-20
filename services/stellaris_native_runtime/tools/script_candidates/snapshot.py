"""Frozen-save fact adapter. All full reference IDs remain generation-bearing."""

from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path

from iag.stellaris.state.extract_game_state import load_gamestate
from iag.stellaris.state.state_index import WorldStateIndex

from .constraints import Fact, ObjectRef, World
from .content import Content
from .syntax import CwtoolsParser, Node, ParseError

# Save-schema adapters, shared by all Commands. No Command names occur here.
SAVE_FAMILIES = {
    "CCountry": "country", "CFleet": "fleet", "CPlanet": "planet",
    "CGalacticObject": "galactic_object", "CLeader": "leaders", "CShip": "ships",
    "CWar": "war", "CSpecies": "species_db", "CArmy": "army", "CStarbase": "starbase", "CPopGroup": "pop_groups",
    "CColony": "colony", "CBuilding": "buildings", "CDistrict": "districts", "CZone": "zones",
    "CFleetTemplate": "fleet_template", "CShipDesign": "ship_design", "CSector": "sectors",
    "CMegaStructure": "megastructures", "CCosmicStorm": "storms", "CResolution": "resolution",
    "CFederation": "federation", "CSpyNetwork": "spy_networks", "CEspionageOperation": "espionage_operations",
    "CEspionageAsset": "espionage_assets", "CAgreement": "agreements", "CSituation": "situations",
    "CFirstContact": "first_contacts", "CArchaeologicalSite": "archaeological_sites", "CAstralRift": "astral_rifts",
    "CCouncilPosition": "council_positions", "CPopFaction": "pop_factions", "CBypass": "bypasses",
    "CPatronRelation": "patron_relations", "CExhibit": "exhibits", "CVivariumCritter": "vivarium_critters",
    "CMission": "missions", "CContract": "contracts", "CWaystationNetwork": "waystation_networks",
    "CConstructionQueue": "@construction_queues", "CConstructionQueueItem": "@construction_items",
}


_ADAPTER_FILES = (Path(__file__), Path(__file__).with_name("syntax.py"), Path(__file__).with_name("constraints.py"))
_LOADED_ADAPTER_SHA256 = hashlib.sha256(b"".join(p.read_bytes() for p in _ADAPTER_FILES)).hexdigest()


def _adapter_fingerprint() -> str:
    # Bind facts to the implementation loaded by this process, not source files
    # which an editor may have changed halfway through a long offline run.
    return _LOADED_ADAPTER_SHA256


def world_cache(world: World, snapshot: dict, content: Content, parser_sha256: str) -> dict:
    return {"schema_version": "iag.offline_save_facts.v3", "snapshot": snapshot,
            "adapter_sha256": _adapter_fingerprint(), "parser_sha256": parser_sha256,
            "content_fingerprint": content.fingerprint,
            "facts": [{"type": ref.native_type, "id": ref.object_id,
                       "facts": {key: {"value": sorted(fact.value) if isinstance(fact.value, frozenset) else fact.value,
                                       "set": isinstance(fact.value, frozenset), "source": fact.source,
                                       "complete": fact.complete, "trusted": fact.trusted} for key, fact in facts.items()}}
                      for ref, facts in sorted(world.facts.items())],
            "links": [{"source_type": source.native_type, "source_id": source.object_id, "link": link,
                       "target_type": target.native_type, "target_id": target.object_id}
                      for (source, link), target in sorted(world.links.items())]}


def restore_world_cache(cache: dict, save_path: Path, content: Content, parser_sha256: str, *, native_collection_bindings=()) -> tuple[World, dict]:
    if (cache.get("schema_version") != "iag.offline_save_facts.v3" or cache.get("content_fingerprint") != content.fingerprint
            or cache.get("adapter_sha256") != _adapter_fingerprint() or cache.get("parser_sha256") != parser_sha256):
        raise ValueError("Fact cache schema/content identity mismatch")
    if hashlib.sha256(save_path.read_bytes()).hexdigest() != cache["snapshot"]["sha256"]:
        raise ValueError("Frozen save no longer matches fact cache")
    binding_sha = hashlib.sha256(json.dumps(native_collection_bindings, sort_keys=True).encode()).hexdigest()
    if cache["snapshot"].get("native_collection_bindings_sha256") != binding_sha:
        raise ValueError("Native save collection binding changed; fact cache cannot be reused")
    world = World()
    for row in cache["facts"]:
        ref = ObjectRef(row["type"], row["id"])
        world.facts[ref] = {key: Fact(frozenset(f["value"]) if f["set"] else f["value"], f["source"],
                                    f["complete"], f["trusted"]) for key, f in row["facts"].items()}
    for row in cache["links"]:
        world.links[ObjectRef(row["source_type"], row["source_id"]), row["link"]] = ObjectRef(row["target_type"], row["target_id"])
    return world, cache["snapshot"]


def anon_values(node: Node | None) -> frozenset[str]:
    return frozenset(n.value for n in node.children or () if n.key is None and n.value is not None) if node else frozenset()


def adapt_object(world: World, ref: ObjectRef, node: Node, source: str, content: Content) -> None:
    facts: dict[str, Fact] = {}
    world.facts[ref] = facts
    # Only unambiguous scalar keys become facts. Repeated fields stay ordered
    # in the AST and cannot silently overwrite one another.
    for child in node.children or ():
        if child.key and child.children is None and len(node.all(child.key)) == 1:
            facts[child.key] = Fact(child.value, source)
    for key, native_type in {"owner": "CCountry", "controller": "CCountry"}.items():
        value = node.scalar(key)
        if value and value.isdecimal() and int(value) != 0xFFFFFFFF:
            world.links[ref, key] = ObjectRef(native_type, int(value))
    coordinate = node.one("coordinate")
    if ref.native_type == "CFleet":
        movement = node.one("movement_manager")
        coordinate = movement.one("coordinate") if movement else None
    origin = coordinate.scalar("origin") if coordinate else None
    if origin and origin.isdecimal() and int(origin) != 0xFFFFFFFF:
        world.links[ref, "solar_system"] = ObjectRef("CGalacticObject", int(origin))
    for field in ("ascension_perks", "traditions"):
        value = node.one(field)
        if value:
            facts[field] = Fact(anon_values(value), source, complete=all(n.key is None and n.value is not None for n in value.children or ()))
    tech = node.one("tech_status")
    if tech:
        technologies, current, complete = set(), None, True
        for member in tech.children or ():
            if member.key == "technology":
                if current is not None:
                    complete = False
                current = member.value
            elif member.key == "level" and current is not None:
                if member.value and member.value.isdecimal():
                    if int(member.value) > 0:
                        technologies.add(current)
                else:
                    complete = False
                current = None
        facts["technologies"] = Fact(frozenset(technologies), source, complete=complete and current is None)
    government = node.one("government")
    if government and government.one("civics"):
        facts["civics"] = Fact(anon_values(government.one("civics")), source)
    if ref.native_type == "CPlanet":
        cls = node.scalar("planet_class")
        definition = content.entries.get(("planet_classes", cls))
        if definition and ("planet_classes", cls) not in content.ambiguous:
            star = definition.scalar("star")
            # The positive declaration is explicit. A missing key is not used
            # to infer a native default; unverified content can rank, not prune.
            if star in {"yes", "no"}:
                facts["is_star"] = Fact(star == "yes", content.sources["planet_classes", cls], trusted=content.engine_loaded)


def nested_database(parser: CwtoolsParser, section: str, family: str, *, native_binding=None) -> tuple[dict[int, Node], dict]:
    """Recover a uniquely nested numeric object collection, not English aliases.

    Some save databases serialize a manager and then its numeric table. An
    empty direct parse does not prove absence. Ambiguous/too-large containers
    remain a snapshot-provider gap rather than a missing game scenario.
    """
    root = Node(None, children=parser.parse(section, "save/database/" + family))
    candidates = []
    def visit(node, path, depth):
        if depth > 3 or node.children is None:
            return
        numeric = [n for n in node.children if n.key and n.key.isdecimal()]
        if numeric:
            # A numeric histogram/counter map is not an object database. Native
            # empty slots are allowed, arbitrary scalar entries are not.
            if all(n.children is not None or n.value == "none" for n in numeric):
                candidates.append((path, numeric))
            return
        blocks = [n for n in node.children if n.key and n.children is not None]
        if not blocks and not node.children:
            candidates.append((path, []))
        for child in blocks:
            visit(child, path + (child.key,), depth + 1)
    visit(root, (family,), 0)
    if native_binding:
        candidates = [(p, n) for p, n in candidates if len(p) > 1 and p[1] == native_binding["collection_key"]]
    if len(candidates) != 1:
        return {}, {"schema_resolution": "ambiguous_or_unmapped_collection", "section_present": True,
                    "candidate_paths": [list(path) for path, _ in candidates], "absence_proven": False}
    path, rows = candidates[0]
    ids = [int(n.key) for n in rows]
    if len(set(ids)) != len(ids):
        return {}, {"schema_resolution": "duplicate_object_identity", "section_present": True,
                    "collection_path": list(path), "absence_proven": False}
    objects = {int(n.key): n for n in rows if n.children is not None and 0 <= int(n.key) < 0xFFFFFFFF}
    return objects, {"schema_resolution": "unique_structured_numeric_collection", "section_present": True,
                     "collection_path": list(path), "absence_proven": not objects,
                     "native_collection_binding": native_binding}


def load_snapshot(parser: CwtoolsParser, path: Path, content: Content, *, per_type: int = 512, native_collection_bindings=()) -> tuple[World, dict]:
    if not 1 <= per_type <= 10000:
        raise ValueError("Snapshot object budget outside bounds")
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    with zipfile.ZipFile(path) as save:
        meta = Node(None, children=parser.parse(save.read("meta").decode("utf-8-sig"), "save/meta"))
    index = WorldStateIndex(load_gamestate(path))
    world, counts, errors = World(), {}, []
    for native_type, family in SAVE_FAMILIES.items():
        schema = {"schema_resolution": "existing_numeric_index", "section_present": True, "absence_proven": False}
        try:
            adapters = {"planet": index.planets, "starbase": index.starbases,
                        "@construction_queues": index.construction_queues, "@construction_items": index.construction_items}
            blocks = adapters[family]() if family in adapters else index.optional_numeric_map(family)
        except ValueError:
            blocks = {}
        if not blocks and family not in adapters:
            section = index.optional_section(family)
            if section:
                try:
                    bindings = [b for b in native_collection_bindings if b["native_type"] == native_type]
                    binding = bindings[0] if len(bindings) == 1 else None
                    blocks, schema = nested_database(parser, section, family, native_binding=binding)
                except ParseError as error:
                    schema = {"schema_resolution": "container_parse_failed", "section_present": True, "absence_proven": False}
                    errors.append({"type": native_type, "error": str(error)})
            else:
                schema = {"schema_resolution": "section_absent_requires_native_schema_evidence", "section_present": False, "absence_proven": False}
        live = sorted((identity, block) for identity, block in blocks.items() if block is not None)
        counts[native_type] = {"available": len(live), "parsed": 0, "truncated": len(live) > per_type, **schema}
        for identity, block in live[:per_type]:
            if identity < 0 or identity >= 0xFFFFFFFF:
                continue
            try:
                ast = block if isinstance(block, Node) else Node(None, children=parser.parse(block, f"save/{family}/{identity}"))
            except ParseError as error:
                errors.append({"type": native_type, "id": identity, "error": str(error)})
                continue
            adapt_object(world, ObjectRef(native_type, identity), ast, f"save:{before}:{family}:{identity}", content)
            counts[native_type]["parsed"] += 1
    after = hashlib.sha256(path.read_bytes()).hexdigest()
    if before != after:
        raise ValueError("Snapshot changed during offline inspection; results discarded")
    return world, {"save_path": str(path.resolve()), "sha256": before, "date": meta.scalar("date"),
                   "native_collection_bindings_sha256": hashlib.sha256(json.dumps(native_collection_bindings, sort_keys=True).encode()).hexdigest(),
                   "version": meta.scalar("version"), "mod_metadata_present": bool(meta.all("mod") or meta.all("mods")),
                   "saved_mods": [n.value for mods in meta.all("mods") for n in mods.children or () if n.key is None and n.value is not None],
                   "saved_mod_order_source": "save_metadata_not_current_active_playset",
                   "objects": counts, "errors": errors, "runtime_state": False,
                   "content_alignment": "unverified_external_files_not_engine_database"}
