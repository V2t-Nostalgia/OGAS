"""Decode captured CDiploActionProposeCommand nested action objects.

The command probe records object bytes only for layouts established against the
exact Stellaris build. This module deliberately decodes stable scalar fields;
pointer-rich engine containers remain diagnostic data and never become public
semantic targets.
"""

from __future__ import annotations

import argparse
import gzip
import json
import pathlib
import struct
from collections.abc import Iterable, Iterator, Mapping
from typing import Any


ACTION_LAYOUTS: dict[str, tuple[str, int]] = {
    "COpenBordersAction": ("open_borders", 0x50),
    "CCloseBordersAction": ("close_borders", 0x50),
    "CMakeRivalAction": ("establish_rivalry", 0x50),
    "CDeclareWarAction": ("declare_war", 0x90),
    "COfferPeaceAction": ("offer_peace", 0x68),
    "CCreateEmbassyAction": ("establish_embassy", 0x50),
    "CFormCommercialPactAction": ("form_commercial_pact", 0x50),
    "CFormDefensivePactAction": ("form_defensive_pact", 0x50),
    "CFormResearchAgreementAction": ("form_research_agreement", 0x50),
    "CFormMigrationPactAction": ("form_migration_pact", 0x50),
    "CInviteToFederationAction": ("invite_to_federation", 0xB8),
    "COfferTradeDealAction": ("offer_trade_deal", 0x2A0),
    "CDemandSubjugationAction": ("demand_subjugation", 0x1E0),
    "CBreakMigrationPactAction": ("break_migration_pact", 0x50),
    "CBreakCommercialPactAction": ("break_commercial_pact", 0x50),
    "CInsultAction": ("insult_country", 0x50),
}

PEACE_OFFER_KINDS = {
    0: "status_quo",
    1: "surrender",
    2: "force_demands",
    4: "unspecified",
}


def _u8(payload: bytes, offset: int) -> int:
    return payload[offset]


def _u32(payload: bytes, offset: int) -> int:
    return struct.unpack_from("<I", payload, offset)[0]


def _i32(payload: bytes, offset: int) -> int:
    return struct.unpack_from("<i", payload, offset)[0]


def _u64(payload: bytes, offset: int) -> int:
    return struct.unpack_from("<Q", payload, offset)[0]


def _i64(payload: bytes, offset: int) -> int:
    return struct.unpack_from("<q", payload, offset)[0]


def decode_pdx_ref(raw: int) -> dict[str, int | bool]:
    """Split a generation-bearing four-byte TPdxRef without resolving it."""

    return {
        "raw": raw,
        "object_index": raw & 0x00FFFFFF,
        "generation": raw >> 24,
        "is_null": raw == 0xFFFFFFFF,
    }


def _decode_known_tail(
    native_type: str,
    payload: bytes,
    decoded: dict[str, Any],
) -> None:
    if native_type == "CDeclareWarAction" and len(payload) >= 0x90:
        decoded["war_goal"] = {
            "type_pointer": _u64(payload, 0x58),
            "war": decode_pdx_ref(_u32(payload, 0x60)),
            "country_a": decode_pdx_ref(_u32(payload, 0x64)),
            "country_b": decode_pdx_ref(_u32(payload, 0x68)),
            "flag_a": bool(_u8(payload, 0x6C)),
            "flag_b": bool(_u8(payload, 0x6D)),
        }
        decoded["attacker_ally_count"] = _i32(payload, 0x84)
        decoded["subject_country"] = decode_pdx_ref(_u32(payload, 0x88))
    elif native_type == "COfferPeaceAction" and len(payload) >= 0x68:
        status = _i32(payload, 0x64)
        decoded["peace_offer"] = {
            "actor_country": decode_pdx_ref(_u32(payload, 0x58)),
            "recipient_country": decode_pdx_ref(_u32(payload, 0x5C)),
            "war": decode_pdx_ref(_u32(payload, 0x60)),
            "status": status,
            "kind": PEACE_OFFER_KINDS.get(status, "unknown"),
        }
    elif native_type == "CInviteToFederationAction" and len(payload) >= 0xB8:
        decoded["auto_accept"] = bool(_u8(payload, 0x50))
        decoded["federation_type_pointer"] = _u64(payload, 0xB0)
    elif native_type == "COfferTradeDealAction" and len(payload) >= 0x2A0:
        decoded["trade_deal"] = {
            "persistent_id": _i32(payload, 0x60),
            "flag": bool(_u8(payload, 0x288)),
            "status_a": _i32(payload, 0x28C),
            "status_b": _i32(payload, 0x290),
            "referenced_deal": decode_pdx_ref(_u32(payload, 0x298)),
        }
    elif native_type == "CDemandSubjugationAction" and len(payload) >= 0x1E0:
        decoded["initial_loyalty"] = {
            "present": bool(_u8(payload, 0x1D0)),
            "fixed_point_raw": _i64(payload, 0x1D8),
        }


def decode_record(record: Mapping[str, Any]) -> dict[str, Any] | None:
    """Return one typed diplomatic action, or ``None`` for another record."""

    if record.get("command_type") != "CDiploActionProposeCommand":
        return None
    native_type = record.get("nested_type")
    if not isinstance(native_type, str) or native_type not in ACTION_LAYOUTS:
        return None
    semantic_action, object_size = ACTION_LAYOUTS[native_type]
    encoded = record.get("known_nested_hex")
    if not isinstance(encoded, str):
        raise ValueError("recognized diplomatic action has no nested payload")
    try:
        payload = bytes.fromhex(encoded)
    except ValueError as exc:
        raise ValueError("known_nested_hex is not valid hexadecimal") from exc
    if len(payload) < 0x50:
        raise ValueError("recognized diplomatic action payload is shorter than base")

    captured_size = int(record.get("known_nested_size", len(payload)))
    reported_object_size = int(record.get("known_nested_object_size", 0))
    complete = (
        bool(record.get("known_nested_complete"))
        and reported_object_size == object_size
        and captured_size >= object_size
        and len(payload) >= object_size
    )
    decoded: dict[str, Any] = {
        "semantic_action": semantic_action,
        "native_type": native_type,
        "expected_object_size": object_size,
        "captured_size": min(captured_size, len(payload)),
        "complete": complete,
        "actor_country": decode_pdx_ref(_u32(payload, 0x20)),
        "recipient_country": decode_pdx_ref(_u32(payload, 0x24)),
        "action_instance_id": _u64(payload, 0x30),
    }
    _decode_known_tail(native_type, payload, decoded)
    return decoded


def _open_text(path: pathlib.Path):
    if path.suffix == ".gz":
        return gzip.open(path, "rt", encoding="utf-8")
    return path.open("r", encoding="utf-8")


def iter_records(paths: Iterable[pathlib.Path]) -> Iterator[dict[str, Any]]:
    for path in paths:
        with _open_text(path) as stream:
            for line_number, line in enumerate(stream, 1):
                if not line.strip():
                    continue
                try:
                    value = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise ValueError(f"{path}:{line_number}: invalid JSON") from exc
                if isinstance(value, dict):
                    yield value


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Decode the 16 mapped nested Stellaris diplomatic actions."
    )
    parser.add_argument("paths", nargs="+", type=pathlib.Path)
    args = parser.parse_args()
    for record in iter_records(args.paths):
        decoded = decode_record(record)
        if decoded is not None:
            print(json.dumps(decoded, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
