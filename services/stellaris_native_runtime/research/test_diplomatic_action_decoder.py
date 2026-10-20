import importlib.util
import struct
import sys
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).with_name("diplomatic_action_decoder.py")
SPEC = importlib.util.spec_from_file_location("iag_diplomatic_decoder", MODULE_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"Cannot import {MODULE_PATH}")
decoder = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = decoder
SPEC.loader.exec_module(decoder)
ACTION_LAYOUTS = decoder.ACTION_LAYOUTS
decode_record = decoder.decode_record


def make_record(native_type: str, payload: bytearray, *, complete: bool = True):
    return {
        "command_type": "CDiploActionProposeCommand",
        "nested_type": native_type,
        "known_nested_hex": payload.hex(),
        "known_nested_size": len(payload),
        "known_nested_object_size": len(payload) if complete else 0,
        "known_nested_complete": complete,
    }


class DiplomaticActionDecoderTests(unittest.TestCase):
    def test_all_sixteen_observed_actions_are_registered(self):
        self.assertEqual(
            {
                "open_borders",
                "close_borders",
                "establish_rivalry",
                "declare_war",
                "offer_peace",
                "establish_embassy",
                "form_commercial_pact",
                "form_defensive_pact",
                "form_research_agreement",
                "form_migration_pact",
                "invite_to_federation",
                "offer_trade_deal",
                "demand_subjugation",
                "break_migration_pact",
                "break_commercial_pact",
                "insult_country",
            },
            {semantic_action for semantic_action, _size in ACTION_LAYOUTS.values()},
        )

    def test_common_country_refs_decode_from_incomplete_old_capture(self):
        payload = bytearray(0x50)
        struct.pack_into("<I", payload, 0x20, 0x0300002A)
        struct.pack_into("<I", payload, 0x24, 0x07000011)
        struct.pack_into("<Q", payload, 0x30, 991)
        decoded = decode_record(
            make_record("COpenBordersAction", payload, complete=False)
        )
        self.assertIsNotNone(decoded)
        assert decoded is not None
        self.assertEqual("open_borders", decoded["semantic_action"])
        self.assertFalse(decoded["complete"])
        self.assertEqual(42, decoded["actor_country"]["object_index"])
        self.assertEqual(3, decoded["actor_country"]["generation"])
        self.assertEqual(17, decoded["recipient_country"]["object_index"])
        self.assertEqual(991, decoded["action_instance_id"])

    def test_offer_peace_tail_is_typed(self):
        payload = bytearray(0x68)
        struct.pack_into("<I", payload, 0x20, 1)
        struct.pack_into("<I", payload, 0x24, 2)
        struct.pack_into("<I", payload, 0x58, 1)
        struct.pack_into("<I", payload, 0x5C, 2)
        struct.pack_into("<I", payload, 0x60, 0x02000009)
        struct.pack_into("<i", payload, 0x64, 0)
        decoded = decode_record(make_record("COfferPeaceAction", payload))
        assert decoded is not None
        self.assertTrue(decoded["complete"])
        self.assertEqual("status_quo", decoded["peace_offer"]["kind"])
        self.assertEqual(9, decoded["peace_offer"]["war"]["object_index"])

    def test_declare_war_tail_is_typed(self):
        payload = bytearray(0x90)
        struct.pack_into("<I", payload, 0x20, 4)
        struct.pack_into("<I", payload, 0x24, 8)
        struct.pack_into("<Q", payload, 0x58, 0x12345678)
        struct.pack_into("<I", payload, 0x60, 0xFFFFFFFF)
        struct.pack_into("<I", payload, 0x64, 4)
        struct.pack_into("<I", payload, 0x68, 8)
        struct.pack_into("<i", payload, 0x84, 3)
        struct.pack_into("<I", payload, 0x88, 0xFFFFFFFF)
        decoded = decode_record(make_record("CDeclareWarAction", payload))
        assert decoded is not None
        self.assertEqual(3, decoded["attacker_ally_count"])
        self.assertTrue(decoded["war_goal"]["war"]["is_null"])
        self.assertTrue(decoded["subject_country"]["is_null"])

    def test_invite_to_federation_tail_is_typed(self):
        payload = bytearray(0xB8)
        struct.pack_into("<I", payload, 0x20, 4)
        struct.pack_into("<I", payload, 0x24, 8)
        struct.pack_into("<B", payload, 0x50, 1)
        struct.pack_into("<Q", payload, 0xB0, 0xABCDEF00)
        decoded = decode_record(
            make_record("CInviteToFederationAction", payload)
        )
        assert decoded is not None
        self.assertTrue(decoded["auto_accept"])
        self.assertEqual(0xABCDEF00, decoded["federation_type_pointer"])

    def test_offer_trade_deal_tail_is_typed(self):
        payload = bytearray(0x2A0)
        struct.pack_into("<I", payload, 0x20, 4)
        struct.pack_into("<I", payload, 0x24, 8)
        struct.pack_into("<i", payload, 0x60, 73)
        struct.pack_into("<B", payload, 0x288, 1)
        struct.pack_into("<i", payload, 0x28C, 2)
        struct.pack_into("<i", payload, 0x290, 5)
        struct.pack_into("<I", payload, 0x298, 0x0300002A)
        decoded = decode_record(make_record("COfferTradeDealAction", payload))
        assert decoded is not None
        self.assertEqual(73, decoded["trade_deal"]["persistent_id"])
        self.assertTrue(decoded["trade_deal"]["flag"])
        self.assertEqual(2, decoded["trade_deal"]["status_a"])
        self.assertEqual(5, decoded["trade_deal"]["status_b"])
        self.assertEqual(
            42,
            decoded["trade_deal"]["referenced_deal"]["object_index"],
        )

    def test_demand_subjugation_tail_is_typed(self):
        payload = bytearray(0x1E0)
        struct.pack_into("<I", payload, 0x20, 4)
        struct.pack_into("<I", payload, 0x24, 8)
        struct.pack_into("<B", payload, 0x1D0, 1)
        struct.pack_into("<q", payload, 0x1D8, -250000)
        decoded = decode_record(
            make_record("CDemandSubjugationAction", payload)
        )
        assert decoded is not None
        self.assertTrue(decoded["initial_loyalty"]["present"])
        self.assertEqual(-250000, decoded["initial_loyalty"]["fixed_point_raw"])

    def test_unrelated_command_is_ignored(self):
        self.assertIsNone(decode_record({"command_type": "CSetPolicyCommand"}))

    def test_short_recognized_payload_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "shorter than base"):
            decode_record(
                {
                    "command_type": "CDiploActionProposeCommand",
                    "nested_type": "CInsultAction",
                    "known_nested_hex": "00" * 20,
                }
            )


if __name__ == "__main__":
    unittest.main()
