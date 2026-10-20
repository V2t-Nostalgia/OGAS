"""Research coordinator over the EXISTING runtime queue/Builder/IsValid lane.

Importing this module never connects or injects. Only an explicit caller can
supply a runtime client and a current paused-session context. It has no Post or
Execute capability. Feedback is observational, not production action admission.
"""

from __future__ import annotations

import json
import re
import time
import uuid
from collections import Counter
from pathlib import Path

from iag.stellaris.execution.native_runtime import NativeProbeBinding

from .planner import Candidate


def native_bindings(candidate: Candidate) -> tuple[NativeProbeBinding, ...]:
    output = []
    for binding in candidate.bindings:
        if not re.fullmatch(r"[A-Za-z0-9_.:-]{1,96}", binding.field):
            raise ValueError("Field name is outside the bounded research codec")
        kind = binding.storage_kind
        if kind not in {"ref", "i32", "i64", "u32", "bool", "definition_pointer"}:
            raise ValueError("Native constraint gate does not support this field kind")
        if kind == "definition_pointer":
            if not isinstance(binding.value, str):
                raise ValueError("Definition needs a semantic key")
            if not re.fullmatch(r"[A-Za-z0-9_.:-]{1,128}", binding.value):
                raise ValueError("Definition key is outside the bounded research codec")
            value, text = 0, binding.value
        else:
            if type(binding.value) not in {bool, int}:
                raise ValueError("Scalar/reference needs a typed integer")
            value, text = int(binding.value), ""
            if kind == "i32" and -(1 << 31) <= value < 0:
                value &= 0xFFFFFFFF
        output.append(NativeProbeBinding(field=binding.field, storage_kind=kind,
                       reference_type=binding.reference_type or "" if kind == "ref" else "",
                       value=value, text_value=text))
    return tuple(output)


def run_validation(report: dict, client, context: dict, output: Path, *, budget=1024,
                   interval=0.1, health_every=16) -> dict:
    """Stop on exceptions, stale context or uncertain completion. Never replay.

    The caller must explicitly authorize a live research window. This function
    doesn't load/inject/restart/pause anything. A changed GameDate is a blocker,
    not a reason to refresh IDs and continue silently against another state.
    """
    if not 1 <= budget <= 4096 or not 0 <= interval <= 5 or not 1 <= health_every <= 64:
        raise ValueError("Invalid bounded validation policy")
    output.mkdir(parents=True, exist_ok=False)
    catalog = client.describe_recovered_commands(request_id="constraint-catalog-" + uuid.uuid4().hex)
    if catalog.probe_revision < 6 or catalog.build_id != report["build_id"] or catalog.instance_id != context["instance_id"]:
        raise ValueError("Exact runtime revision/build/instance mismatch; no native probes sent")
    if not context.get("world_identity") or type(context.get("game_date")) is not int:
        raise ValueError("Missing current session world/date")
    run_id = "constraint-" + uuid.uuid4().hex
    rows, calls, blocked, abort = [], 0, Counter(), None
    seen = set()
    with (output / "progress.jsonl").open("x", encoding="utf-8") as journal:
        def log(row):
            journal.write(json.dumps(row, ensure_ascii=True) + "\n")
            journal.flush()
        for command in report["commands"]:
            for raw in command["candidates"]:
                candidate = Candidate.model_validate_json(json.dumps(raw))
                if candidate.identity in seen:
                    continue
                seen.add(candidate.identity)
                if candidate.sdk_metadata_fingerprint != catalog.sdk_fingerprint:
                    blocked["sdk_metadata_mismatch"] += 1
                    break
                try:
                    bindings = native_bindings(candidate)
                except ValueError:
                    blocked["native_gate_field_kind_or_range"] += 1
                    break
                if catalog.probe_revision < 7 and any(b.storage_kind == "i64" for b in bindings):
                    blocked["native_gate_i64_requires_revision_7"] += 1
                    break
                if calls >= budget:
                    abort = "native_call_budget_reached"
                    break
                if calls and calls % health_every == 0:
                    current = client.describe_recovered_commands(request_id=run_id + "-health-" + str(calls))
                    if current != catalog:
                        abort = "runtime_identity_changed"
                        break
                request_id = run_id + "-" + str(calls)
                log({"event": "started", "request_id": request_id, "candidate": candidate.model_dump(mode="json"),
                     "candidate_identity": candidate.identity, "context": context})
                try:
                    result = client.validate_constraint_candidate(request_id=request_id,
                        command_name=candidate.command_name, catalog=catalog,
                        expected_world=context["world_identity"], expected_date=context["game_date"],
                        candidate_identity=candidate.identity, bindings=bindings)
                except Exception as error:
                    # A timeout might have completed natively. Retain pending,
                    # stop the batch and never blindly resubmit it.
                    abort = "uncertain_request_completion:" + type(error).__name__
                    log({"event": "uncertain", "request_id": request_id, "error": str(error)})
                    break
                calls += 1
                evidence = {"candidate_identity": candidate.identity, "candidate": candidate.model_dump(mode="json"),
                            "result": result.model_dump(mode="json"), "context": context,
                            "fixture_equivalence": "world_date_and_ids_only_not_full_save_equivalence",
                            "execution_verified": False}
                rows.append(evidence)
                log({"event": "completed", "request_id": request_id, **evidence})
                if result.status == "call_exception":
                    abort = "native_exception_stop_no_replay"
                    break
                if result.reason.startswith("constraint_plan_stale") or "fixture_changed" in result.reason or result.fixture_paused is not True:
                    abort = "fixture_not_stable_and_paused"
                    break
                if result.native_is_valid is True:
                    # A proven candidate is enough for this coverage pass.
                    # No need to consume more native calls on the same Command.
                    break
                if result.status not in {"native_valid", "native_invalid"}:
                    blocked[result.reason] += 1
                    break
                time.sleep(interval)
            if abort:
                break
    summary = {"schema_version": "iag.constraint_validation_batch.v1", "run_id": run_id,
               "build_id": catalog.build_id, "instance_id": catalog.instance_id,
               "requests_completed": calls, "native_calls": sum(r["result"]["native_is_valid"] is not None for r in rows),
               "commands_native_validated": len({r["candidate"]["command_name"] for r in rows if r["result"]["native_is_valid"] is not None}),
               "commands_native_true": len({r["candidate"]["command_name"] for r in rows if r["result"]["native_is_valid"] is True}),
               "outcomes": dict(Counter(r["result"]["status"] for r in rows)), "blocked": dict(blocked),
               "aborted": abort, "observations": rows, "submitted": False, "production_promotions": 0,
               "cross_state_feedback_reuse": False}
    with (output / "report.json").open("x", encoding="utf-8") as stream:
        json.dump(summary, stream, indent=2)
        stream.write("\n")
    return summary
