"""Evidence-scoped validator feedback; no learning unsupported general rules."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Callable

from .planner import Candidate


def parameter_key(command_name: str, bindings: list[dict]) -> str:
    normalized = sorted((b["field"], b.get("storage_kind"), b.get("reference_type"),
                         b.get("value"), b.get("text_value", ""), tuple(b.get("reference_ids", []))) for b in bindings)
    return hashlib.sha256(json.dumps([command_name, normalized], sort_keys=True).encode()).hexdigest()


class Feedback:
    """Two independent indexes: historical observations and exact fixture reuse.

    IsValid(false) excludes only that complete binding in that exact immutable
    state. Localized reason text can suggest investigations, never a predicate.
    Unknown/stale states and unpaired destructors cannot close the loop.
    """

    def __init__(self):
        self.rows: list[dict] = []
        self.reusable: dict[tuple[str, str, str], dict] = {}

    def load_report(self, path: Path, build_id: str) -> dict:
        report = json.loads(path.read_text(encoding="utf-8"))
        source_hash = hashlib.sha256(path.read_bytes()).hexdigest()
        if report.get("build_id") != build_id:
            return {"path": str(path), "sha256": source_hash, "status": "different_build_not_imported"}
        count = 0
        for command in report.get("commands", []):
            for attempt in command.get("attempts", []):
                if attempt.get("build_id") != build_id or attempt.get("submitted") is not False:
                    continue
                row = {"command_name": attempt["command_name"], "source_path": str(path),
                       "source_sha256": source_hash, "status": attempt.get("status"),
                       "native_is_valid": attempt.get("native_is_valid"),
                       "reason": attempt.get("native_reason"), "bindings": attempt.get("bindings", []),
                       "destroyed": attempt.get("destroyed"), "world_identity": attempt.get("world_identity"),
                       "game_date_before": attempt.get("game_date_before"),
                       "game_date_after": attempt.get("game_date_after"),
                       "reuse": "not_bound_to_an_immutable_save_and_content_fingerprint"}
                self.rows.append(row)
                count += 1
        return {"path": str(path), "sha256": source_hash, "status": "historical_native_observations_only", "attempts": count}

    def record(self, candidate: Candidate, result: dict) -> dict:
        """Consume a trusted game-thread validator callback or offline test double.

        The callback contract is intentionally not an arbitrary-target public RPC.
        It must use existing SDK/Builder, freshness and lifecycle checks. No
        transport, second queue or executor is implemented in this package.
        """
        required = {"build_id": candidate.build_id, "save_sha256": candidate.save_sha256,
                    "content_fingerprint": candidate.content_fingerprint, "submitted": False}
        if any(result.get(key) != value for key, value in required.items()):
            raise ValueError("Native feedback does not belong to the exact candidate fixture")
        if result.get("destroyed") is not True or type(result.get("native_is_valid")) is not bool:
            raise ValueError("Feedback missing native boolean or paired destruction")
        if result.get("source") != "native_game_thread_IsValid":
            raise ValueError("Synthetic/script validation cannot be recorded as native evidence")
        row = candidate.model_dump(mode="json") | {"native_feedback": result, "reuse": "exact_fixture_only"}
        key = candidate.build_id, candidate.save_sha256, candidate.identity
        old = self.reusable.get(key)
        if old and old["native_feedback"]["native_is_valid"] != result["native_is_valid"]:
            # A contradiction under allegedly identical full state is evidence
            # against the fixture's completeness, not permission to majority-vote.
            self.reusable.pop(key)
            raise ValueError("Contradictory native result: fixture dependencies are incomplete")
        self.reusable[key] = row
        self.rows.append(row)
        return row

    def validate(self, candidates: tuple[Candidate, ...], gate: Callable[[Candidate], dict], *, budget=16) -> list[dict]:
        if not 1 <= budget <= 64:
            raise ValueError("Validation budget outside bounds")
        results = []
        for candidate in candidates[:budget]:
            key = candidate.build_id, candidate.save_sha256, candidate.identity
            if key in self.reusable:
                results.append(self.reusable[key])
                continue
            # One callback, one native IsValid, then require lifecycle evidence.
            results.append(self.record(candidate, gate(candidate)))
        return results

    def summary(self) -> dict:
        return {"observations": len(self.rows), "historical_commands": len({r["command_name"] for r in self.rows}),
                "outcomes": dict(Counter(str(r.get("native_is_valid", r.get("native_feedback", {}).get("native_is_valid"))) for r in self.rows)),
                "fixture_reusable": len(self.reusable), "learned_unproven_rules": 0,
                "production_promotions": 0}
