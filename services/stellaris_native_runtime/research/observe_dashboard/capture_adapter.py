from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .common import game_date_ordinal, load_json, parse_timestamp, read_last_jsonl, utc_now


NATIVE_CONTENT_FAMILIES = {
    "building": (("CAddBuildableToQueueCommand", "CBuildableBuilding"),),
    "district": (("CAddBuildableToQueueCommand", "CBuildableDistrict"),),
    "zone": (("CAddBuildableToQueueCommand", "CBuildableZone"),),
    "ship": (
        ("CAddBuildableToQueueCommand", "CShipDesign"),
        ("CCreateOrUpdateShipDesignCommand", None),
    ),
    "technology": (("CResearchTechnologyCommand", None),),
    "event": (("CSelectEventOptionCommand", None),),
    "situation": (("CSetSituationApproachCommand", None),),
}


class CaptureStatusReader:
    """Read compact state emitted by ``long_run_capture.py``.

    The dashboard never tails the multi-million-record evidence streams.  It
    consumes their atomic catalogs and indexes, then reports how fresh that
    compact view is.
    """

    def __init__(self, capture_root: Path | None, baseline_catalog: Path | None = None):
        self.capture_root = capture_root
        self.baseline_catalog = baseline_catalog

    def snapshot(self) -> dict[str, Any]:
        if self.capture_root is None:
            return self._unavailable("capture root was not configured")
        health = load_json(self.capture_root / "health.json", {})
        catalog = load_json(self.capture_root / "catalog.json", {})
        coverage = load_json(self.capture_root / "coverage.json", {})
        session = load_json(self.capture_root / "session.json", {})
        if not any((health, catalog, coverage, session)):
            return self._unavailable(
                f"no compact capture state exists at {self.capture_root}"
            )
        latest_save = read_last_jsonl(self.capture_root / "save_index.jsonl")
        updated = parse_timestamp(health.get("updated_at"))
        now = datetime.now(UTC).timestamp()
        age = now - updated if updated is not None else None
        totals = catalog.get("totals", {}) if isinstance(catalog, dict) else {}
        stream_backlog = self._stream_backlog(session, health)
        baseline = load_json(self.baseline_catalog, {}) if self.baseline_catalog else {}
        command_diff = self._catalog_diff(baseline, catalog)
        coverage_counts = coverage.get("counts", {}) if isinstance(coverage, dict) else {}
        game_date = latest_save.get("game_date") if latest_save else None
        return {
            "available": True,
            "observed_at": utc_now(),
            "root": str(self.capture_root),
            "updated_at": health.get("updated_at"),
            "age_seconds": age,
            "live": bool(age is not None and age <= 30.0),
            "stale_reason": None
            if age is not None and age <= 30.0
            else "capture health has not updated in the last 30 seconds",
            "game_date": game_date,
            "game_date_ordinal": game_date_ordinal(game_date),
            "latest_save": latest_save,
            "game": health.get("game", {}),
            "totals": {
                "command_records": int(totals.get("command_records", 0) or 0),
                "payload_records": int(totals.get("payload_records", 0) or 0),
                "state_records": int(totals.get("state_records", 0) or 0),
                "malformed": int(totals.get("malformed", 0) or 0),
                "dropped": int(totals.get("dropped", 0) or 0),
                "writer_dropped": int(totals.get("writer_dropped", 0) or 0),
                "command_types": len(catalog.get("command_types", {})),
                "nested_types": int(coverage_counts.get("nested_types", 0) or 0),
            },
            "backlog": stream_backlog,
            "coverage": {
                "ready_for_early_review": coverage.get("ready_for_early_review"),
                "missing_state_targets": coverage.get("missing_state_targets", []),
                "counts": coverage_counts,
            },
            "command_diff": command_diff,
            "native_content_family_evidence": self._native_family_evidence(catalog),
            "source_semantics": {
                "new_type_attribution": "correlation_only",
                "causal_mod_attribution": "unknown",
                "note": (
                    "A type observed with a mod set is not attributed to one mod "
                    "without a controlled comparison."
                ),
            },
        }

    @staticmethod
    def _native_family_evidence(catalog: dict[str, Any]) -> dict[str, Any]:
        commands = catalog.get("command_types", {})
        result: dict[str, Any] = {}
        for category, rules in NATIVE_CONTENT_FAMILIES.items():
            matches: list[dict[str, Any]] = []
            for command_name, nested_name in rules:
                record = commands.get(command_name)
                if not isinstance(record, dict):
                    continue
                nested = record.get("nested_types", [])
                if nested_name is not None and nested_name not in nested:
                    continue
                phases = record.get("phases", {})
                matches.append(
                    {
                        "command_type": command_name,
                        "nested_type": nested_name,
                        "sampled_records": sum(
                            int(value or 0) for value in phases.values()
                        ),
                    }
                )
            result[category] = {
                "observed": bool(matches),
                "matches": matches,
                "interpretation": (
                    "native family observed with the complete environment; no "
                    "individual Mod content item is attributed"
                ),
            }
        return result

    @staticmethod
    def _unavailable(reason: str) -> dict[str, Any]:
        return {
            "available": False,
            "observed_at": utc_now(),
            "live": False,
            "reason": reason,
            "totals": {},
            "backlog": {"ready_segments": 0, "unread_bytes": 0},
        }

    @staticmethod
    def _catalog_diff(
        baseline: dict[str, Any], current: dict[str, Any]
    ) -> dict[str, Any]:
        baseline_commands = baseline.get("command_types", {})
        current_commands = current.get("command_types", {})
        baseline_payloads = baseline.get("payload_types", {})
        current_payloads = current.get("payload_types", {})
        baseline_nested = {
            nested
            for record in baseline_commands.values()
            if isinstance(record, dict)
            for nested in record.get("nested_types", [])
            if isinstance(nested, str)
        }
        current_nested = {
            nested
            for record in current_commands.values()
            if isinstance(record, dict)
            for nested in record.get("nested_types", [])
            if isinstance(nested, str)
        }
        changed_command_layouts = CaptureStatusReader._layout_diff(
            baseline_commands, current_commands
        )
        changed_payload_layouts = CaptureStatusReader._layout_diff(
            baseline_payloads, current_payloads
        )
        return {
            "baseline_configured": bool(baseline),
            "new_command_types": sorted(set(current_commands) - set(baseline_commands)),
            "missing_baseline_command_types": sorted(
                set(baseline_commands) - set(current_commands)
            ),
            "new_nested_types": sorted(current_nested - baseline_nested),
            "new_payload_types": sorted(set(current_payloads) - set(baseline_payloads)),
            "changed_command_layouts": changed_command_layouts,
            "changed_payload_layouts": changed_payload_layouts,
        }

    @staticmethod
    def _layout_diff(
        baseline: dict[str, Any], current: dict[str, Any]
    ) -> list[dict[str, Any]]:
        changes: list[dict[str, Any]] = []
        for name in sorted(set(baseline) & set(current)):
            before = {
                value.get("fingerprint")
                for value in baseline[name].get("layout_signatures", [])
                if isinstance(value, dict) and value.get("fingerprint")
            }
            after = {
                value.get("fingerprint")
                for value in current[name].get("layout_signatures", [])
                if isinstance(value, dict) and value.get("fingerprint")
            }
            if before and after and before != after:
                changes.append(
                    {
                        "type": name,
                        "baseline_fingerprints": sorted(before),
                        "current_fingerprints": sorted(after),
                        "interpretation": "structural_change_candidate",
                    }
                )
        return changes

    def _stream_backlog(
        self, session: dict[str, Any], health: dict[str, Any]
    ) -> dict[str, Any]:
        streams = health.get("streams", {}) if isinstance(health, dict) else {}
        ready_segments = 0
        ready_bytes = 0
        unread_bytes = 0
        per_stream: dict[str, Any] = {}
        for name in ("commands", "payloads", "states"):
            raw_path = session.get(name)
            state = streams.get(name, {}) if isinstance(streams, dict) else {}
            path = Path(raw_path) if isinstance(raw_path, str) else None
            active_unread = 0
            ready_count = 0
            ready_size = 0
            if path is not None:
                try:
                    active_unread = max(0, path.stat().st_size - int(state.get("offset", 0)))
                except (FileNotFoundError, OSError, TypeError, ValueError):
                    active_unread = 0
                try:
                    ready = list(path.parent.glob(f"{path.name}.*.ready"))
                except OSError:
                    ready = []
                ready_count = len(ready)
                for item in ready:
                    try:
                        ready_size += item.stat().st_size
                    except OSError:
                        continue
            ready_segments += ready_count
            ready_bytes += ready_size
            unread_bytes += active_unread
            per_stream[name] = {
                "active_unread_bytes": active_unread,
                "ready_segments": ready_count,
                "ready_bytes": ready_size,
                "probe_pid": state.get("probe_pid"),
                "max_sequence": state.get("max_sequence"),
            }
        return {
            "ready_segments": ready_segments,
            "ready_bytes": ready_bytes,
            "unread_bytes": unread_bytes,
            "probe_pipe_queue_depth": None,
            "probe_pipe_queue_depth_reason": (
                "the passive probes expose loss counters, not instantaneous pipe occupancy"
            ),
            "streams": per_stream,
        }
