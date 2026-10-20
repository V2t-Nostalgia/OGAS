#!/usr/bin/env python3
"""Offline acceptance inputs from an existing SDK and immutable live report.

Reuses the maintained recovery audit/emitter. No process, socket, loader,
execution, or game-control API. Old consumers and evidence are not replaced.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "sdk_recovery"))
from audit_recovery import audit
from emit_ogas import catalog_fingerprint, emit_header, recovered_command_name


def prepare(sdk_path: Path, baseline_path: Path, output: Path) -> dict:
    sdk = json.loads(sdk_path.read_text(encoding="utf8"))
    baseline = json.loads(baseline_path.read_text(encoding="utf8"))
    recovered = audit(sdk, baseline)
    if sdk["platform"] != "linux-x86_64":
        raise ValueError("The reviewed native domain ABI is currently Linux-only.")
    output.mkdir(parents=True, exist_ok=False)
    header = output / "recovered_sdk.hpp"
    emit_header(sdk, header)
    # Positive-only commands are regression evidence, not a list to endlessly
    # retest. Native providers have a separate explicit regression/producer lane.
    names_by_class = {
        c["class"]: recovered_command_name(c, i) for i, c in enumerate(sdk["commands"])
    }
    native_commands = [
        names_by_class[c["class"]]
        for c in sdk["commands"]
        if c["class"]
        in {
            "CResearchTechnologyCommand",
            "CCancelResearchTechnologyCommand",
            "CAddBuildableToQueueCommand",
        }
    ]
    selected = [
        names_by_class.get(r.get("class_name"), r["command_name"])
        for r in recovered["commands"]
        if r["validation_static_eligible"]
        and r["previous_status"] != "native_valid"
        and names_by_class.get(r.get("class_name"), r["command_name"])
        not in native_commands
    ]
    plan = {
        "schema_version": "iag.producer_validation_preparation.v1",
        "prepared_at": datetime.now(UTC).isoformat(),
        "build_id": sdk["build_id"],
        "binary_sha256": sdk["sha256"],
        "sdk_fingerprint": catalog_fingerprint(sdk),
        "sources": {
            str(p.resolve()): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in (sdk_path, baseline_path)
        },
        "generated_header": "recovered_sdk.hpp",
        "generated_header_sha256": hashlib.sha256(header.read_bytes()).hexdigest(),
        "native_domain_commands": native_commands,
        "legacy_selected_commands": selected,
        "command_classes": {name: cls for cls, name in names_by_class.items()},
        "static_blocked": [
            {"command_name": r["command_name"], "blockers": r["blockers"]}
            for r in recovered["commands"]
            if r["blockers"]
        ],
        "audit_summary": recovered["summary"],
        "planned_only": True,
        "new_native_calls": 0,
        "submitted": False,
        "execution_verified": False,
        "promotions": 0,
    }
    for filename, value in (("audit.json", recovered), ("plan.json", plan)):
        with (output / filename).open("x", encoding="utf8") as stream:
            json.dump(value, stream, ensure_ascii=True, indent=2)
            stream.write("\n")
    return plan


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sdk", type=Path, required=True)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    plan = prepare(args.sdk, args.baseline, args.output)
    print(
        json.dumps(
            {
                "legacy_selected": len(plan["legacy_selected_commands"]),
                "native_domain": plan["native_domain_commands"],
                "static_blocked": len(plan["static_blocked"]),
                "new_native_calls": 0,
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
