"""Regression check for the SDK dumper against layouts verified by hand (engine factories,
IsValid/Execute disassembly and the RE cheatsheet). Run after every game patch:

    python tools/sdk_dumper/validate.py

Exit code 1 if any known field moved in a way the dumper did not reproduce.
Offsets are Windows object offsets (from the start of the object / command).
"""
# SPDX-FileCopyrightText: 2026 Yidhar
# SPDX-License-Identifier: MIT
import json
import os
import sys
from pathlib import Path

OUT = Path(os.environ["IAG_SDK_WORK_DIR"]) / "win_layouts.json"
LINUX_TOKENS = Path(__file__).resolve().parent / "linux_tokens.json"

# serializer key -> {token: expected Windows offset}. Tokens are numbered as in the decompile
# (linux_tokens.json); main() renumbers them to the installed exe by name, like win_extract.py.
GROUND_TRUTH = {
    # commands (engine factories + serializers, 4.5.1)
    "CResearchTechnologyCommand::WriteCommandMembers": {0x2c88: 0x20, 0x2d0d: 0x28},
    "CCancelResearchTechnologyCommand::WriteCommandMembers": {0x2c88: 0x20, 0x2d0d: 0x28},
    "CHireLeaderCommand::WriteCommandMembers": {0x2c88: 0x20, 0x4033: 0x24},
    "CFireLeaderCommand::WriteCommandMembers": {0x2c88: 0x20, 0x4033: 0x24},
    "CAssignLeaderCommand::WriteCommandMembers": {0x4033: 0x20, 0x3fd3: 0x24, 0x3e24: 0x34},
    "CSetSituationApproachCommand::WriteCommandMembers": {0x2df4: 0x20, 0xdc: 0x38},
    "CActivateRelicCommand::WriteCommandMembers": {0x2c88: 0x50, 0x3ce4: 0x30, 0x4048: 0x54},
    "CAddEdictCommand::WriteCommandMembers": {0x2c88: 0x50, 0x1b: 0x30},
    "CReinforceFleetCommand::WriteCommandMembers": {0x2c88: 0x20, 0x3b38: 0x24},
    "CFleetUpgradeDesignCommand::WriteCommandMembers": {0x2c88: 0x20, 0x2c56: 0x24, 0x3df1: 0x28, 0x4091: 0x2c, 0x35e3: 0x2d},
    "CCountryActivateTraditionCommand::WriteCommandMembers": {0x2c88: 0x20, 0x41: 0x28},
    "CFinishAgendaCommand::WriteCommandMembers": {0x2c88: 0x20},
    "CEnactDecisionCommand::WriteCommandMembers": {0x2b7e: 0x20, 0x45e7: 0x28, 0x2c88: 0x30},
    "CCountryDeleteSpeciesModTemplate::WriteCommandMembers": {0x2c88: 0x20, 0x2b52: 0x24},
    "CMarketBuyResourceCommand::WriteCommandMembers": {0x33cb: 0x20, 0x2d5c: 0x38},
    "CAddBuildableToQueueCommand::WriteCommandMembers": {0x2c88: 0x28, 0x4091: 0x2c},
    "CSetFavoriteJobCommand::WriteCommandMembers": {0x2c88: 0x20, 0x3931: 0x24, 0x2cdc: 0x28},
    "CStartTerraformationCommand::WriteCommandMembers": {0x2a19: 0x20, 0x3051: 0x24, 0x2eab: 0x28},
    # entities (docs/REVERSE_ENGINEERING_CHEATSHEET.md, verified live)
    "CPlanet::WriteMembers": {0x2c99: 0xd0},
    "CColonyCarrier::WriteMembers": {0x3931: 0xc0, 0x3dfb: 0xc4},
}
# sub-object placement: (parent serializer, child class) -> Windows offset in parent
SUBOBJECTS = {
    ("CPlanet::WriteMembers", "CColonyCarrier"): 0x20,   # => CPlanet+0xE0 colony, +0xE4 build queue
}


def main():
    data = json.loads(OUT.read_text(encoding="utf-8"))
    layouts = data["layouts"]
    ref = {int(k, 16): v for k, v in json.loads(LINUX_TOKENS.read_text(encoding="utf-8"))["tokens"].items()}
    by_name = {v: int(k) for k, v in data["token_names"].items()}
    ok = bad = 0
    for key, linux_fields in GROUND_TRUTH.items():
        fields = {by_name.get(ref.get(t), t): off for t, off in linux_fields.items()}
        lay = layouts.get(key)
        if lay is None:
            print(f"MISSING  {key}")
            bad += len(fields)
            continue
        got = {f["token"]: f["win_off"] for f in lay["fields"]}
        for tok, exp in fields.items():
            if got.get(tok) == exp:
                ok += 1
            else:
                bad += 1
                g = got.get(tok)
                print(f"MISMATCH {key} token 0x{tok:x}: expected 0x{exp:x}, got {hex(g) if g is not None else None}")
    for (key, child), exp in SUBOBJECTS.items():
        subs = {s["class"]: s["win_off"] for s in layouts.get(key, {}).get("subobjects", [])}
        if subs.get(child) == exp:
            ok += 1
        else:
            bad += 1
            print(f"MISMATCH {key} sub-object {child}: expected 0x{exp:x}, got {subs.get(child)}")
    print(f"validate: {ok} ok, {bad} wrong")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
