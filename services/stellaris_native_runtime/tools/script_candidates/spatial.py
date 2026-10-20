"""Thin read-only reuse of save maps and native coordinate metadata."""

from __future__ import annotations

from collections import defaultdict
from decimal import Decimal, InvalidOperation, localcontext
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

from pydantic import BaseModel, ConfigDict, Field, model_validator


class LocalPoint(BaseModel):
    model_config = ConfigDict(strict=True, frozen=True, extra="forbid")
    origin: int = Field(ge=0, lt=0xFFFFFFFF)
    x: Decimal
    y: Decimal
    outer_radius: Decimal = Field(gt=0)
    source_id: int | None = Field(default=None, ge=0, lt=0xFFFFFFFF)
    source_kind: str

    @model_validator(mode="after")
    def finite(self):
        if not all(v.is_finite() for v in (self.x, self.y, self.outer_radius)):
            raise ValueError("Coordinates/radius must be finite")
        return self

    @property
    def normalized(self):
        return self.x / self.outer_radius, self.y / self.outer_radius

    @classmethod
    def from_normalized(cls, *, origin, x, y, outer_radius, source_kind="caller_local_point"):
        # Denormalize with this system's radius, never a global training scale.
        return cls(origin=origin, x=x * outer_radius, y=y * outer_radius,
                   outer_radius=outer_radius, source_kind=source_kind)


def fixed_raw(value: Decimal, scale: int) -> int:
    if type(scale) is not int or not 1 <= scale <= 1_000_000_000 or not value.is_finite():
        raise ValueError("Unproven fixed-point format or nonfinite value")
    if len(value.as_tuple().digits) > 64 or abs(value.as_tuple().exponent) > 64:
        raise ValueError("Coordinate decimal exceeds bounded exact conversion")
    with localcontext() as context:
        context.prec = 80
        raw = value * scale
    # Save/map values on the native lattice are exact. Do not silently invent a
    # float rounding policy or claim float renderer conversions are reversible.
    if raw != raw.to_integral_value() or not -(1 << 63) <= raw <= (1 << 63) - 1:
        raise ValueError("Coordinate is not exactly representable by native fixed-point")
    return int(raw)


class SpatialContext:
    def __init__(self, save_sha256: str, points, manifest):
        self.save_sha256 = save_sha256
        self.points = tuple(points)
        self.by_system = defaultdict(list)
        for point in self.points:
            self.by_system[point.origin].append(point)
        self.manifest = manifest

    def groups(self, command, world, *, limit):
        """Correlated value domains; never independently combine X/Y/origin."""
        from .constraints import ObjectRef
        from .planner import Binding

        fields = command.get("population_fields", command["fields"])
        by_name = {f["name"]: f for f in fields}
        context_refs = [f for f in fields if f.get("ref") == "CFleet" and
                        any("TPdxRef<CFleet>" in e.get("parameter_type", "") for e in f.get("constructor_parameter_evidence", []))]
        context = context_refs[0] if len(context_refs) == 1 else None
        systems = {ref.object_id for ref in world.objects("CGalacticObject")}
        result = []
        for region in command.get("native_value_regions", []):
            if not region.get("layout_verified") or region.get("kind") != "nonowning_native_coordinate":
                continue
            # Multiple coordinates sharing a fleet context require a joint
            # producer relation, not two independently chosen copies of fleet.
            if context and len(command["native_value_regions"]) != 1:
                continue
            members, scale = region["members"], region["fixed_scale"]
            values, seen, available, rejected = [], set(), 0, 0
            if context:
                owners = [(r, world.links.get((r, "solar_system"))) for r in world.objects("CFleet")]
            else:
                owners = [(None, ObjectRef("CGalacticObject", s)) for s in sorted(systems)]
            for ref, system in owners:
                if system is None or system.object_id not in systems:
                    continue
                for point in self.by_system.get(system.object_id, ()):
                    try:
                        x, y = fixed_raw(point.x, scale), fixed_raw(point.y, scale)
                    except (ValueError, InvalidOperation):
                        rejected += 1
                        continue
                    key = (ref.object_id if ref else None, point.origin, x, y)
                    if key in seen:
                        continue
                    seen.add(key)
                    available += 1
                    if len(values) >= limit:
                        continue
                    raw = {"x": x, "y": y, "origin": point.origin, **region["ctor_defaults"]}
                    bindings = [Binding(field=members[role], offset=by_name[members[role]]["linux_off"],
                        storage_kind="ref" if role == "origin" else "bool" if role == "randomized" else "i64",
                        reference_type="CGalacticObject" if role == "origin" else None, value=value,
                        source="native_value_ctor" if role in {"randomized", "visual_height"} else "frozen_save_coordinate")
                        for role, value in raw.items()]
                    if ref:
                        bindings.insert(0, Binding(field=context["name"], offset=context["linux_off"], storage_kind="ref",
                            reference_type="CFleet", value=ref.object_id, source="frozen_save_reference"))
                    # Reject galaxy-transit points above, keep same-system local
                    # targets here. Inter-system moves use the existing native
                    # CalcFTLPointWith provider, not inferred map lane endpoints.
                    values.append((0, tuple(bindings)))
            covered = set(members.values()) | ({context["name"]} if context else set())
            result.append({"fields": covered, "values": values, "available": available,
                           "rejected_not_on_native_lattice": rejected, "region": region})
        return result


def load_spatial_model(root: Path, save: Path, expected_sha256: str, output: Path) -> SpatialContext:
    """Import the explicit existing package; never search a latest-save output."""
    root = root.resolve()
    package = root / "stellaris_save_map"
    source_names = ("__init__.py", "save.py", "parser.py", "reconstruct.py", "map_model.py", "export.py")
    sources = [{"path": "stellaris_save_map/" + n, "sha256": hashlib.sha256((package / n).read_bytes()).hexdigest()}
               for n in source_names]
    if hashlib.sha256(save.read_bytes()).hexdigest() != expected_sha256:
        raise ValueError("Spatial map input differs from the frozen candidate fixture")
    output.mkdir(parents=True, exist_ok=False)
    package_name = "_iag_save_map_" + hashlib.sha256(str(package).encode()).hexdigest()[:16]
    spec = importlib.util.spec_from_file_location(package_name, package / "__init__.py",
                                                 submodule_search_locations=[str(package)])
    if spec is None or spec.loader is None:
        raise ValueError("Cannot load the explicitly selected save-map package")
    old_bytecode = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        module = importlib.util.module_from_spec(spec)
        sys.modules[package_name] = module
        spec.loader.exec_module(module)
        reader = module.StellarisSave(save)
        galaxy = reader.build_full_map(include_dynamic=True)
        from importlib import import_module
        exporter = import_module(package_name + ".export")
        exporter.export_json(galaxy, output / "map.json")
        exporter.export_jsonl(galaxy, output / "systems.jsonl")
        reader.release_parsed_cache()
    finally:
        sys.dont_write_bytecode = old_bytecode
        for name in list(sys.modules):
            if name == package_name or name.startswith(package_name + "."):
                del sys.modules[name]
    points, errors = [], []
    for system in galaxy.systems.values():
        if system.outer_radius is None:
            errors.append({"system": system.system_id, "reason": "missing_outer_radius"})
            continue
        for obj in system.objects + system.dynamic_overlay:
            if obj.origin != system.system_id:
                errors.append({"system": system.system_id, "reason": "object_origin_mismatch", "object": obj.id})
                continue
            try:
                points.append(LocalPoint(origin=obj.origin, x=Decimal(str(obj.position[0])), y=Decimal(str(obj.position[1])),
                    outer_radius=Decimal(str(system.outer_radius)), source_id=obj.id, source_kind=obj.kind))
            except ValueError as error:
                errors.append({"system": system.system_id, "reason": str(error), "object": obj.id})
    if hashlib.sha256(save.read_bytes()).hexdigest() != expected_sha256 or any(
            hashlib.sha256((root / s["path"]).read_bytes()).hexdigest() != s["sha256"] for s in sources):
        raise ValueError("Spatial source or frozen save changed during reconstruction")
    source_dir = output / "source-snapshot"
    source_dir.mkdir()
    for source in sources:
        with (source_dir / Path(source["path"]).name).open("xb") as stream:
            stream.write((root / source["path"]).read_bytes())
    manifest = {"schema_version": "iag.spatial_model_reuse.v1", "save_sha256": expected_sha256,
        "sources": sources, "systems": len(galaxy.systems), "local_points": len(points),
        "galaxy_transit_excluded": len(galaxy.galaxy_overlay), "unmapped_excluded": len(galaxy.unmapped_objects),
        "errors": errors, "normalization": "local_xy / per_system_outer_radius_without_clipping",
        "inferred_hyperlane_endpoints_used_as_commands": False, "native_calls": 0}
    with (output / "manifest.json").open("x", encoding="utf-8") as stream:
        json.dump(manifest, stream, indent=2)
    return SpatialContext(expected_sha256, points, manifest)
