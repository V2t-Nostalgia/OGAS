from __future__ import annotations

import copy
import hashlib
import json
from decimal import Decimal
from pathlib import Path
import struct
import sys
import tempfile
import unittest

from capstone import Cs, CS_ARCH_X86, CS_MODE_64
from pydantic import ValidationError

TOOLS = Path(__file__).parent
sys.path.insert(0, str(TOOLS))
sys.path.insert(0, str(TOOLS / "sdk_recovery"))
sys.path.insert(0, str(TOOLS.parents[2] / "src"))

from sdk_recovery.coordinate_values import recover_coordinate_value, bind_coordinate_regions
from sdk_recovery.emit_ogas import population_layout_complete
from script_candidates.constraints import World, ObjectRef
from script_candidates.content import Content
from script_candidates.planner import plan_command, Candidate
from script_candidates.pipeline import native_bindings
from script_candidates.semantic_audit import audit_command
from script_candidates.spatial import LocalPoint, SpatialContext, fixed_raw, load_spatial_model


class SpatialSourceTests(unittest.TestCase):
    def test_neutral_manifest_keeps_relative_paths_and_exact_source_hashes(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "spatial-source"
            package = root / "stellaris_save_map"
            package.mkdir(parents=True)
            for name in ("save.py", "parser.py", "reconstruct.py", "map_model.py"):
                (package / name).write_text("# fixture\n", encoding="utf-8")
            (package / "__init__.py").write_text(
                "from types import SimpleNamespace as S\n"
                "class StellarisSave:\n"
                " def __init__(self, path): pass\n"
                " def build_full_map(self, *, include_dynamic):\n"
                "  assert include_dynamic\n"
                "  obj=S(origin=7,position=(1,-2),id=1,kind='planet')\n"
                "  system=S(system_id=7,outer_radius=500,objects=[obj],dynamic_overlay=[])\n"
                "  return S(systems={7:system},galaxy_overlay=[],unmapped_objects=[])\n"
                " def release_parsed_cache(self): pass\n", encoding="utf-8")
            (package / "export.py").write_text(
                "def export_json(galaxy, path): path.write_text('{}',encoding='utf-8')\n"
                "def export_jsonl(galaxy, path): path.write_text('{}\\n',encoding='utf-8')\n", encoding="utf-8")
            save = Path(temp) / "fixture.sav"
            save.write_bytes(b"frozen-spatial-fixture")
            output = Path(temp) / "new-evidence"
            context = load_spatial_model(root, save, hashlib.sha256(save.read_bytes()).hexdigest(), output)
            manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["schema_version"], "iag.spatial_model_reuse.v1")
            self.assertEqual(manifest["errors"], [])
            self.assertEqual(len(context.by_system[7]), 1)
            self.assertNotIn(str(root), json.dumps(manifest))
            for source in manifest["sources"]:
                self.assertTrue(source["path"].startswith("stellaris_save_map/"))
                self.assertFalse(Path(source["path"]).is_absolute())
                snapshot = output / "source-snapshot" / Path(source["path"]).name
                self.assertEqual(hashlib.sha256(snapshot.read_bytes()).hexdigest(), source["sha256"])


class CoordinateImage:
    """Small exact-code regression corpus, not game process access."""
    def __init__(self):
        records = [
            ("CCelestialCoordinate::{ctor}(CGalacticObject const*, CFixedPoint const&, CFixedPoint const&)", 36193968,
             "488d0509aff9024889070f57c00f114708488b0248894708488b014889471048c74718000000004885f6740d8b460889472066c747240000c3b8ffffffff89472066c747240000c3"),
            ("CCelestialCoordinate::WriteMembers(CWriter&)", 36194192,
             "415653504989f64889fb488b57084889f7be20000000e8b5d10602488b53104c89f7be21000000e8a4d10602488d53204c89f7bead2c0000e8538c91ff807b250074124c89f7be2e320000ba01000000e89be00602488b53184885d274144c89f7bead3f00004883c4085b415ee95ed106024883c4085b415ec3"),
            ("CCelestialCoordinate::RandomizeDisplayHeightIfSet()", 36194560,
             "53807f2500740a4889fb48837f180074025bc3f3480f2a4308f30f10153f3c3702f30f59c2f3480f2a4b10f30f59cae84c8fbe000f28c8f30f100589a63702f30f59c1f30f58056da637020f57d20f2eca7305e818105afff3480f2cc0488943185bc3"),
            ("CCelestialCoordinate::SetDisplayHeight(float)", 36204256,
             "530f28c8f30f1005dc803702f30f59c1f30f5805c08037024889fb0f57d20f2eca7305e868ea59fff3480f2cc0488943185bc3"),
            ("CCelestialCoordinate::GetDisplayHeight const()", 36204320, "488b4718c3"),
        ]
        self.symbols = [{"raw": name, "name": name, "rva": address, "size": len(bytes.fromhex(raw)), "type": "STT_FUNC"}
                        for name, address, raw in records]
        self.memory = {address: bytes.fromhex(raw) for _, address, raw in records}
        self.symbols.append({"raw": "CCelestialCoordinate_vtable", "name": "vtable for CCelestialCoordinate",
                             "rva": 0x521F5B0, "size": 128, "type": "STT_OBJECT"})
        self.memory[0x521F5C0] = struct.pack("<" + "Q" * 14, 36194192, *([0] * 13))
        self.memory[0x45FEFC8] = struct.pack("<f", 100000)
        self.memory[0x45FEFB8] = struct.pack("<f", 0.5)
        self.memory[0x45F8560] = struct.pack("<f", 1 / 100000)
        self.names = {0x42F1960: "CWriter::Write(int, CFixedPoint)",
                      0x1B9D420: "void CWriter::Write<CGalacticObject>(int, TPdxRef<CGalacticObject> const&)",
                      0x42F2880: "CWriter::Write(int, bool)"}
        self.by_address = {s["rva"]: s for s in self.symbols}
        self.md = Cs(CS_ARCH_X86, CS_MODE_64)
        self.md.detail = True

    def name(self, symbol):
        return symbol["name"]

    def read(self, address, size):
        for start, raw in self.memory.items():
            if start <= address and address + size <= start + len(raw):
                return raw[address - start:address - start + size]
        return b""

    def instructions(self, symbol, limit=65536):
        return list(self.md.disasm(self.read(symbol["rva"], min(limit, symbol["size"])), symbol["rva"]))

    def target_name(self, address):
        return self.names.get(address, self.by_address.get(address, {}).get("name", ""))


TOKENS = {0x20: "x", 0x21: "y", 0x2CAD: "origin", 0x322E: "randomized", 0x3FAD: "visual_height"}


def coordinate_command(model):
    fields = [{"name": "source", "kind": "ref", "ref": "CFleet", "linux_off": 28, "confidence": "direct_dataflow",
               "constructor_parameter_evidence": [{"parameter_type": "TPdxRef<CFleet>"}]}]
    for field in model["fields"]:
        f = copy.deepcopy(field)
        f["name"] = "point." + f["name"]
        f["linux_off"] += 32
        if f["writer"] == "CWriter::Write(int, CFixedPoint)":
            f.update(storage_kind="i64", native_type="CFixedPoint")
        fields.append(f)
    fields += [{"name": "append", "kind": "bool", "linux_off": 72, "confidence": "direct_dataflow"},
               {"name": "front", "kind": "bool", "linux_off": 73, "confidence": "direct_dataflow"}]
    writes = [{"offset": off, "width": width, "value": value, "evidence_rva": 5000 + off} for off, width, value in
              [(32, 8, ["rva", model["vtable_rva"]]), (56, 8, ["constant", 0]),
               (64, 4, ["constant", 0xFFFFFFFF]), (68, 2, ["constant", 0]), (72, 2, ["constant", 0])]]
    return {"class": "CSyntheticUnregisteredCommand", "token_name": "arbitrary_test", "size": 80,
            "factory": 100, "is_valid": 200, "vtable": 300, "deleting_destructor": 400,
            "lifecycle_probe_safe": True, "fields": fields, "population_fields": fields,
            "factory_evidence": {"writes": writes}}


class CoordinateRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.image = CoordinateImage()
        self.model = recover_coordinate_value(self.image, TOKENS)

    def test_exact_native_scale_is_decimal_not_legacy_binary_fraction(self):
        self.assertTrue(self.model["recovered"], self.model)
        self.assertEqual(self.model["fixed_scale"], 100000)
        self.assertEqual(self.model["size"], 40)
        self.assertTrue(self.model["zero_height_and_no_randomize"])

    def test_inverse_conversion_disagreement_fails_closed(self):
        self.image.memory[0x45F8560] = struct.pack("<f", 1 / 32768)
        self.assertFalse(recover_coordinate_value(self.image, TOKENS)["recovered"])

    def test_missing_token_does_not_guess_coordinate_member(self):
        self.assertFalse(recover_coordinate_value(self.image, {})["recovered"])

    def test_incomplete_native_conversion_does_not_open_value_gate(self):
        self.image.by_address[36204256]["size"] -= 1
        self.assertFalse(recover_coordinate_value(self.image, TOKENS)["recovered"])

    def test_constructor_vtable_must_match_the_typed_serializer(self):
        raw = bytearray(self.image.memory[36193968])
        raw[3] ^= 8
        self.image.memory[36193968] = bytes(raw)
        self.assertFalse(recover_coordinate_value(self.image, TOKENS)["recovered"])

    def test_shared_region_repairs_tail_padding_not_payload(self):
        command = coordinate_command(self.model)
        self.assertFalse(population_layout_complete(command, "linux-x86_64"))
        regions = bind_coordinate_regions(command, command["factory_evidence"], self.model)
        self.assertEqual(regions[0]["padding_intervals"], [[70, 72]])
        self.assertTrue(population_layout_complete(command, "linux-x86_64"))
        self.assertEqual(len(command["population_fields"]), 8)

    def test_wrong_factory_vtable_is_not_the_same_coordinate_type(self):
        command = coordinate_command(self.model)
        command["factory_evidence"]["writes"][0]["value"][1] += 8
        self.assertFalse(bind_coordinate_regions(command, command["factory_evidence"], self.model))

    def test_randomize_state_must_be_native_initialized(self):
        command = coordinate_command(self.model)
        command["factory_evidence"]["writes"] = [w for w in command["factory_evidence"]["writes"] if w["offset"] != 68]
        self.assertFalse(bind_coordinate_regions(command, command["factory_evidence"], self.model))

    def test_forged_tail_padding_cannot_hide_other_missing_storage(self):
        command = coordinate_command(self.model)
        bind_coordinate_regions(command, command["factory_evidence"], self.model)
        command["native_value_regions"][0]["padding_intervals"] = [[56, 72]]
        self.assertFalse(population_layout_complete(command, "linux-x86_64"))


class SpatialCandidateTests(unittest.TestCase):
    def setUp(self):
        model = recover_coordinate_value(CoordinateImage(), TOKENS)
        self.command = coordinate_command(model)
        bind_coordinate_regions(self.command, self.command["factory_evidence"], model)
        self.sdk = {"platform": "linux-x86_64", "build_id": "fixture", "sha256": "elf", "commands": [self.command],
                    "object_databases": [{"class": "CFleet"}, {"class": "CGalacticObject"}]}
        self.world = World()
        for typ, ids in {"CGalacticObject": (45, 46), "CFleet": (0x03000001, 0x05000002)}.items():
            for object_id in ids:
                self.world.facts[ObjectRef(typ, object_id)] = {}
        for fleet, system in zip(self.world.objects("CFleet"), (45, 46)):
            self.world.links[fleet, "solar_system"] = ObjectRef("CGalacticObject", system)
        points = [LocalPoint(origin=45, x=Decimal("12.125"), y=Decimal("-3.5"), outer_radius=Decimal(800), source_kind="planet"),
                  LocalPoint(origin=46, x=Decimal("90"), y=Decimal("7"), outer_radius=Decimal(400), source_kind="planet")]
        self.spatial = SpatialContext("save", points, {})

    def plan(self, spatial=True):
        return plan_command(self.command, 0, self.sdk, self.world, Content(),
                            {"sha256": "save"}, {"rules": []}, {}, spatial=self.spatial if spatial else None)

    def test_coordinates_and_fleet_origin_are_one_correlated_domain(self):
        report = self.plan()
        self.assertTrue(report["candidates"], report)
        for row in report["candidates"]:
            values = {b["field"]: b["value"] for b in row["bindings"]}
            system = self.world.links[ObjectRef("CFleet", values["source"]), "solar_system"].object_id
            self.assertEqual(values["point.origin"], system)
            self.assertEqual((values["point.x"], values["point.y"]),
                             (1212500, -350000) if system == 45 else (9000000, 700000))
            self.assertIs(values["point.randomized"], False)
            self.assertEqual(values["point.visual_height"], 0)

    def test_no_map_means_caller_coordinates_not_a_new_abi_gap(self):
        report = self.plan(spatial=False)
        audit = audit_command(self.command, report, self.sdk,
            {"sha256": "save", "objects": {"CFleet": {"parsed": 2}, "CGalacticObject": {"parsed": 2}}},
            {"functions": [], "calls": [], "producer_callsites": [], "native_parameter_sources": {}})
        self.assertFalse(audit["technical_gaps"])
        self.assertEqual(audit["primary_status"], "waiting_caller_parameters")
        self.assertTrue(any(r["requirement"] == "typed_local_coordinate_or_frozen_spatial_model_required"
                            for r in audit["caller_requirements"]))

    def test_same_world_does_not_allow_a_different_save_map(self):
        self.spatial.save_sha256 = "other"
        with self.assertRaises(ValueError):
            self.plan()

    def test_constraint_codec_preserves_correlated_i64_coordinates(self):
        row = self.plan()["candidates"][0]
        candidate = Candidate.model_validate_json(__import__("json").dumps(row))
        bindings = native_bindings(candidate)
        self.assertEqual({b.field: b.value for b in bindings},
                         {b.field: int(b.value) for b in candidate.bindings})
        self.assertTrue(any(b.storage_kind == "i64" and b.value < 0 for b in bindings))

    def test_transit_fleet_not_mistaken_for_an_intrasystem_fleet(self):
        self.world.links.clear()
        self.assertFalse(self.plan()["candidates"])

    def test_exact_decimal_fixed_point_and_int64_bounds(self):
        self.assertEqual(fixed_raw(Decimal("-0.00001"), 100000), -1)
        self.assertEqual(fixed_raw(Decimal("12.125"), 100000), 1212500)
        for value in (Decimal("1.000001"), Decimal("NaN"), Decimal("1e30")):
            with self.assertRaises(ValueError):
                fixed_raw(value, 100000)

    def test_decimal_context_does_not_silently_round_an_off_lattice_input(self):
        with self.assertRaises(ValueError):
            fixed_raw(Decimal("1.0000000000000000000000000000001"), 100000)

    def test_each_system_uses_its_own_radius_and_preserves_outliers(self):
        small = LocalPoint.from_normalized(origin=1, x=Decimal("1.1"), y=Decimal(0), outer_radius=Decimal(400))
        large = LocalPoint.from_normalized(origin=2, x=Decimal("1.1"), y=Decimal(0), outer_radius=Decimal(800))
        self.assertEqual(small.x, 440)
        self.assertEqual(large.x, 880)
        self.assertEqual(large.normalized[0], Decimal("1.1"))

    def test_galaxy_sentinel_is_not_a_local_origin(self):
        with self.assertRaises(ValidationError):
            LocalPoint(origin=0xFFFFFFFF, x=Decimal(1), y=Decimal(2), outer_radius=Decimal(500), source_kind="fleet")


if __name__ == "__main__":
    unittest.main()
