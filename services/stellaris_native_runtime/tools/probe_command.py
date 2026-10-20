#!/usr/bin/env python3
"""Validate one SDK-constructed research candidate without submitting it."""

from __future__ import annotations

import argparse
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "src"))

from iag.stellaris.execution.native_runtime import NativeRuntimeClient


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command")
    parser.add_argument("--country", type=int, default=None)
    parser.add_argument("--leader", type=int, default=None)
    parser.add_argument("--candidate-index", type=int, default=0)
    parser.add_argument("--endpoint")
    parser.add_argument("--request-id", default=None)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.output is not None and args.output.exists():
        parser.error("output already exists; preserve the previous validation evidence")
    result = NativeRuntimeClient(args.endpoint).validate_recovered_command(
        request_id=args.request_id or f"sdk-probe-{uuid.uuid4().hex}",
        command_name=args.command,
        country_id=args.country,
        leader_id=args.leader,
        candidate_index=args.candidate_index,
    )
    serialized = result.model_dump_json(indent=2) + "\n"
    if args.output is not None:
        with args.output.open("x", encoding="utf-8") as stream:
            stream.write(serialized)
    print(serialized, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
