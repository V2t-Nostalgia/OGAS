#!/usr/bin/env python3
"""Review generated candidates offline, or explicitly validate in a future window.

Default mode is offline. --native is an explicit opt-in to an already-loaded
revision-6 runtime (revision 7 for i64). There is no loader, injection or
game-state control path.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "src"))

from iag.stellaris.execution.native_runtime import NativeRuntimeClient
from script_candidates.pipeline import native_bindings, run_validation
from script_candidates.planner import Candidate


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--native", action="store_true")
    parser.add_argument("--context", type=Path, help="Fresh {instance_id,world_identity,game_date}, from the same paused runtime session")
    parser.add_argument("--endpoint", help="Existing local Unix socket or Windows named pipe")
    parser.add_argument("--budget", type=int, default=1024)
    values = parser.parse_args()
    report = json.loads(values.report.read_text(encoding="utf-8"))
    if values.native:
        if not values.context:
            parser.error("--native requires a fresh --context; never infer it from an old save")
        client = NativeRuntimeClient(values.endpoint)
        if not client.available():
            parser.error("No loaded runtime endpoint; this tool never injects")
        result = run_validation(report, client, json.loads(values.context.read_text(encoding="utf-8")), values.output, budget=values.budget)
    else:
        rows = []
        for command in report["commands"]:
            accepted, blocked = [], []
            for row in command["candidates"]:
                candidate = Candidate.model_validate_json(json.dumps(row))
                try:
                    bindings = native_bindings(candidate)
                    accepted.append({"candidate_identity": candidate.identity, "command_name": candidate.command_name,
                                     "bindings": [b.model_dump(mode="json") for b in bindings],
                                     "required_probe_revision": 7 if any(b.storage_kind == "i64" for b in bindings) else 6,
                                     "sdk_metadata_fingerprint": candidate.sdk_metadata_fingerprint})
                except ValueError as error:
                    blocked.append(str(error))
            rows.append({"command_name": command["command_name"], "plans": accepted, "blockers": sorted(set(blocked))})
        result = {"schema_version": "iag.constraint_validation_preflight.v1", "build_id": report["build_id"],
                  "catalog_commands": len(rows), "commands_with_plans": sum(bool(r["plans"]) for r in rows),
                  "plans": sum(len(r["plans"]) for r in rows), "native_calls": 0, "connected": False,
                  "required_probe_revision": max((p["required_probe_revision"] for r in rows for p in r["plans"]), default=6),
                  "submitted": False, "production_promotions": 0, "commands": rows}
        values.output.mkdir(parents=True, exist_ok=False)
        with (values.output / "preflight.json").open("x", encoding="utf-8") as stream:
            json.dump(result, stream, indent=2)
            stream.write("\n")
    print(json.dumps({k: v for k, v in result.items() if k not in {"commands", "observations"}}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
