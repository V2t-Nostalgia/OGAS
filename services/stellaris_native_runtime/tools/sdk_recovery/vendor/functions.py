"""Stage 2c: locate engine functions that the bridge calls directly, by structural fingerprint.

Some values are computed rather than stored (e.g. an agenda's cost scales with empire size), so
the bridge has to call the engine function. Each entry below describes the function the way the
Linux decompile shows it: an ordered list of instruction patterns that must appear within the
first `window` instructions of a 16-byte-aligned function. A fingerprint must match exactly one
function, otherwise the stage fails instead of guessing.

Usage: python tools/sdk_dumper/functions.py   -> out/functions.json
"""
# SPDX-FileCopyrightText: 2026 Yidhar
# SPDX-License-Identifier: MIT
# OGAS changes: explicit, isolated input/output paths; see ../README.md.
import json
import os
import re
import runpy
import struct
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = Path(os.environ["IAG_SDK_WORK_DIR"])

wx = runpy.run_path(str(HERE / "win_extract.py"), run_name="sdk_functions")
Image, EXE = wx["Image"], wx["EXE"]

FUNCTIONS = {
    "CCouncilAgenda_GetCost": {
        "linux": "CCouncilAgenda::GetCost(CCountry const*, CString*) const",
        # MSVC: rcx = this, rdx = CFixedPoint* result, r8 = country, r9 = CString* reason
        "signature": "int64_t* (*)(void* agenda, int64_t* out_cost, void* country, void* reason)",
        # empire size * 100000, then modifier scan for 0x13B (size base) and 0x13C (cost mult)
        "pattern": [(r"^imul ", "0x186a0"), (r"^cmp ", "0x13b"), (r"^cmp ", "0x13c")],
        "prefilter": [0x186A0, 0x13B, 0x13C],
        "window": 60,
    },
    "GetPlayerCountry": {
        "linux": "GetPlayerCountry()",
        # the country the local human plays (or observes): CGameState::GetLocalObserved on
        # g_CurrentGameState with g_AllowGetPlayer raised around the call
        "signature": "void* (*)()",
        "pattern": [(r"^movzx ebx, byte ptr \[rip \+ 0x", ""), (r"^mov byte ptr \[rip \+ 0x[0-9a-f]+\], 1$", ""),
                    (r"^mov rcx, qword ptr \[rip \+ 0x", ""), (r"^call 0x", ""),
                    (r"^mov byte ptr \[rip \+ 0x[0-9a-f]+\], bl$", "")],
        "prefilter_bytes": [b"\x0F\xB6\x1D"],  # movzx ebx, byte ptr [rip + x]
        "window": 12,
        "max_len": 14,
    },
    "CConsole_RunCommandNow": {
        "linux": "CConsole::RunCommandNow(CString const&)",
        # rcx = CConsole::_pInstance, rdx = CString const* (the whole command line)
        "signature": "void (*)(void* console, const void* command_cstring)",
        # appends the line to console_history.txt; the constructor also opens that file but
        # does not start with the history-size check `cmp dword ptr [rcx + 0x50], 1`
        "strings": ["console_history.txt"],
        "require": [r"cmp dword ptr \[rcx \+ 0x50\], 1"],
    },
    # --- perf hooks (bridge perf_tweaks): opinion and scripted game-rule memoization per tick
    "CGameState_HandleTurnTick": {
        "linux": "CGameState::HandleTurnTick(CPdxArray<CCommand*, int>&)",
        # rcx = game state, rdx = commands of this turn
        "signature": "void (*)(void* game_state, void* commands)",
        "strings": ["It is a new day: "],
    },
    "CCountry_CalcOurOpinionOfOtherNoScopeCopy": {
        "linux": "CCountry::CalcOurOpinionOfOtherNoScopeCopy(CCountry const*, CEventScope const&, CString*) const",
        "signature": "int (*)(const void* country, const void* other, const void* scope, void* reason)",
        # builds the opinion breakdown text with these keys; only this function references them
        "strings": ["IMPERIAL_AUTHORITY_ENVOY_OPINION", "IMPROVE_RELATIONS_VALUE"],
    },
    "CCountry_CalcOurOpinionOfOther": {
        "linux": "CCountry::CalcOurOpinionOfOther(CCountry const*, CString*) const",
        # rcx = this country, rdx = other country, r8 = CString* breakdown (nullptr when none)
        "signature": "int (*)(const void* country, const void* other, void* reason)",
        # the only caller of NoScopeCopy: builds the two country scopes and forwards
        "caller_of": "CCountry_CalcOurOpinionOfOtherNoScopeCopy",
    },
    "CScriptedRule_Evaluate": {
        "linux": "CScriptedRule::Evaluate(CEventScope&, CString*, CScriptedRule::EShowTooltip, bool) const",
        # rcx = rule, rdx = scope, r8 = CString* reason (nullptr when none), r9b = EShowTooltip
        "signature": "bool (*)(const void* rule, void* scope, void* reason, uint8_t show_tooltip, bool flag)",
        # script-profiler name "CGameRules::" + rule + ".Evaluate"; CWeightedRule::Evaluate and the
        # country-as-this variant build the same name but take no enum in r9b / no trigger at +8
        "strings": ["CGameRules::", ".Evaluate"],
        "require": [r"movzx esi, r9b", r"lea rcx, \[r14 \+ 8\]"],
    },
    "CSpeciesRightBase_IsPotential": {
        "linux": "CSpeciesRightBase::IsPotential(CCountry const*, CSpecies const*) const",
        # this = species right type + 0x40
        "signature": "bool (*)(void* right_base, void* country, void* species)",
        # script-profiler scope name "species_right." + key + ".potential"
        "strings": ["species_right.", ".potential"],
    },
    "CSpeciesRightBase_IsAllowed": {
        "linux": "CSpeciesRightBase::IsAllowed(CCountry const*, CSpecies const*, CString*) const",
        "signature": "bool (*)(void* right_base, void* country, void* species, void* reason_cstring)",
        "strings": ["species_right.", ".allow"],
    },
    # --- events: CEventWindow::Setup / GetToolTip are found by their GUI strings; the engine
    # functions they call are picked by position relative to an anchor instruction.
    "CEvent_GetTitle": {
        "linux": "CEvent::GetTitle(CEventScope const&) const",
        # MSVC: rcx = event, rdx = CString* out, r8 = scope; returns out
        "signature": "void* (*)(void* event, void* out_cstring, void* scope)",
        "call_near": {"strings": ["event_option_offset", "event_window_option_entry", "description_frame"],
                      "anchor": '"Title"', "pick": "last_call_before"},
    },
    "NEventWindowUtil_GetEventWindowDesc": {
        "linux": "NEventWindowUtil::GetEventWindowDesc(CEvent const&, CEventScope const&)",
        "signature": "void* (*)(void* out_cstring, void* event, void* scope)",
        "call_near": {"strings": ["event_option_offset", "event_window_option_entry", "description_frame"],
                      "anchor": '"description_frame"', "pick": "last_call_before"},
    },
    "CEventOption_GetDescForOptionAtIndex": {
        "linux": "CEventOption::GetDescForOptionAtIndex(CEventScope const&, bool, CPdxArray<CEventOption const*> const&, int, CEffect const*, bool)",
        # the effect tooltip of one event option (CEvent::GetEffectDescription is inlined)
        "signature": "void* (*)(void* out_cstring, void* scope, bool, void* options_array, int index, void* effect, bool)",
        "call_near": {"strings": ["event_option_button", "coop_event_option_selected_by_other"],
                      "anchor": r"lea r9, \[rax \+ 0x5e0\]", "pick": "first_call_after"},
    },
    "CEventWindow_PostEventOptionSelection": {
        "linux": "CEventWindow::PostEventOptionSelection(int)",
        # rcx = event window (as listed at [idler + 0x170]); forwards to
        # COpenPlayerEvent::PostEventOptionSelection, then logs the "selected_event_option" analytics event
        "signature": "void (*)(void* event_window, int option_index)",
        "strings": ["selected_event_option"],
        # several event views post option selections; this one looks the open player event up by id
        "require": [r"cmp dword ptr \[r\w+ \+ 0x180\], eax"],
    },
    "COutlinerPlanetStatusController_ShouldShowStatusFrame": {
        "linux": "COutlinerPlanetStatusController::ShouldShowStatusFrame(EOutlinerPlanetStatusFrame, CColony const&, TPdxRef<CCountry>, EPlanetBuildingOwnerType)",
        # rcx = controller (only frame 1 touches it: a growth-data map at +0x10), edx = frame,
        # r8 = colony, r9d = country id, [rsp+0x28] = owner type. Frames: 0 construction slot,
        # 1 clearable blocker, 2 capital upgrade, 5 unemployment, 6 excess civilians,
        # 7 overcrowding, 10 low stability.
        "signature": "bool (*)(void* controller, int frame, void* colony, uint32_t country, int owner_type)",
        # a 15-way jump table whose unemployment case tests colony flag bit 1 (+0x1088)
        "pattern": [(r"^cmp edx", "0xe"), (r"^jmp", "rdx"), (r"^mov eax, dword ptr \[rdi", "0x1088]")],
        "prefilter": [0x1088, 0xFD4],
        "window": 40,
    },
    "PdxLocalize_OneParam": {
        "linux": "PdxLocalize<char const(&)[N], CString const&>(key, param_name, value)",
        # rcx = CString* out, rdx = key view {const char*, int32 len, u8}, r8 = param name
        # (strlen'd at run time, so any name works), r9 = CString const& value
        "signature": "void* (*)(void* out_cstring, const void* key_view, const char* param, const void* value_cstring)",
        "call_near": {"strings": ["OUTLINER_PLANET_BLOCKADED", "OUTLINER_PLANET_OCCUPIED"],
                      "anchor": '"BLOCKADER"', "pick": "first_call_after"},
    },
    "CPersistentName_BuildString": {
        "linux": "CPersistentName::BuildString() const",
        # MSVC: rcx = CPersistentName (e.g. CFleet::name), rdx = CString* out; returns out.
        # Found through CFleet::GetLocalizedName (a CFleet vtable thunk): add rcx, <name - base>;
        # mov rbx, rdx; call BuildString.
        "signature": "void* (*)(const void* persistent_name, void* out_cstring)",
        "pattern": [(r"^add rcx", "0x3a0"), (r"^mov rbx", "rdx"), (r"^call", "")],
        "prefilter": [0x3A0],
        "window": 6,
        "follow_call": True,
    },
    "CArmy_CalcMilitaryPower": {
        "linux": "CArmy::CalcMilitaryPower() const",
        # MSVC: rcx = army, rdx = CFixedPoint* out (x100000); returns out
        "signature": "int64_t* (*)(const void* army, int64_t* out)",
        # CArmy::GetToolTip: power, then its formatting, then "ARMY_MILITARY_POWER_TIP"
        "call_near": {"strings": ["ARMY_MILITARY_POWER_TIP", "ARMY_NO_MORALE", "ARMY_NO_POP_LIMIT"],
                      "anchor": '"ARMY_MILITARY_POWER_TIP"', "pick": "last_call_before", "skip": 1},
    },
    "CArmyType_CalcMorale": {
        "linux": "CArmyType::CalcMorale(CModifier const*) const",
        # MSVC: rcx = army type, rdx = CFixedPoint* out, r8 = the army's CModifier; the army's
        # maximum morale (CArmy::CalcMaxMorale passes CArmy's modifier)
        "signature": "int64_t* (*)(const void* army_type, int64_t* out, const void* modifier)",
        # CArmy::GetToolTip: after the has_morale test, a formatting call, then CalcMorale
        "call_near": {"strings": ["ARMY_MILITARY_POWER_TIP", "ARMY_NO_MORALE", "ARMY_NO_POP_LIMIT"],
                      "anchor": r"cmp byte ptr \[rax \+ 0x355\], 0", "occurrence": 0,
                      "pick": "first_call_after", "skip": 1},
    },
    "CFleet_BuildOrdersString": {
        "linux": "CFleet::BuildOrdersString(bool, bool) const",
        # MSVC: rcx = fleet, rdx = CString* out, r8b, r9b (the outliner fleet entry passes 1, 0);
        # the fleet's current orders as the game describes them ("NO_ORDERS" when idle)
        "signature": "void* (*)(const void* fleet, void* out_cstring, bool, bool)",
        "strings": ["NO_ORDERS", "FLEETORDER_TOP_LEVEL_TEXT", "ORDERS_LEFT"],
    },
    "CCountry_CalcTotalCivicPoints": {
        "linux": "CCountry::CalcTotalCivicPoints() const",
        # rcx = country; GOVERNMENT_CIVIC_POINTS_BASE plus the country's civic points modifier (0x117)
        "signature": "int (*)(const void* country)",
        "pattern": [(r"^cmp dword ptr", "0x117"), (r"^movabs", "0x29f16b11c6d1e109"), (r"^add edx, dword ptr \[rip", "]")],
        "prefilter": [0x117],
        "window": 30,
    },
    "CCountry_CanChangeGovernment": {
        "linux": "CCountry::CanChangeGovernment(CString*) const",
        # rcx = country, rdx = CString* reason (reform cooldown, unity for the reform cost)
        "signature": "bool (*)(const void* country, void* reason_cstring)",
        # the first thing CChangeGovernmentCommand::IsValid (vtable slot 8) calls
        "vtable_call": {"command": "change_government", "slot": 8, "call_index": 0},
    },
    "CCountry_CalcGovernmentReformCost": {
        "linux": "CCountry::CalcGovernmentReformCost() const",
        # rcx = country, rdx = CFixedPoint* out: 0 under game rule 0xD0, else
        # empire_size * GOVERNMENT_CHANGE_EMPIRE_SIZE_MULT (unity)
        "signature": "int64_t* (*)(const void* country, int64_t* out)",
        "pattern": [(r"^mov edx", "0xd0"), (r"^call", ""), (r"^mov qword ptr \[rbx\], 0", "0"),
                    (r"^movsxd rax, dword ptr \[rdi", "]"), (r"^imul rax, qword ptr \[rip", "]")],
        "prefilter": [0xD0],
        "window": 24,
    },
    "SEthicGovernmentConfiguration_ctor_country": {
        "linux": "SEthicGovernmentConfiguration::SEthicGovernmentConfiguration(CCountry const*)",
        # rcx = this (0x98-byte struct), rdx = country; forwards (country, founder species)
        "signature": "void* (*)(void* config, const void* country)",
        "pattern": [(r"^mov r9, rdx", ""), (r"^mov edx, dword ptr \[rdx", "]"), (r"^cmp dword ptr \[r8 \+ 0x10\], edx", ""),
                    (r"^mov rdx, r9", ""), (r"^mov rcx, rbx", ""), (r"^call", "")],
        "prefilter_bytes": [b"\x4C\x8B\xCA"],  # mov r9, rdx
        "window": 26,
        "max_len": 30,
    },
    "SEthicGovernmentConfiguration_dtor": {
        "linux": "SEthicGovernmentConfiguration::~SEthicGovernmentConfiguration()",
        "signature": "void (*)(void* config)",
        # frees its CPdxArrays (ship categories +0x68, traits +0x50, civics +0x28, ethics +0x8)
        "pattern": [(r"^mov qword ptr \[rcx \+ 0x68\], rax", ""), (r"^mov rbx, rcx", ""),
                    (r"^mov dword ptr \[rcx \+ 0x7c\], edi", ""), (r"^mov rcx, qword ptr \[rcx \+ 0x70\]", ""),
                    # the civics array at +0x28 tells it from look-alike destructors
                    (r"^mov rcx, qword ptr \[rbx \+ 0x30\]", ""), (r"^mov qword ptr \[rbx \+ 0x28\], rax", "")],
        "prefilter_bytes": [b"\x48\x89\x41\x68\x48\x8B\xD9\x89\x79\x7C"],
        "window": 32,
    },
    "CGovernmentCivicType_IsPossible": {
        "linux": "CGovernmentCivicType::IsPossible(SEthicGovernmentConfiguration const&, EModdableCivicCondition, CCountry const*, CString*) const",
        # rcx = civic, rdx = config, r8w = condition flags (1 = can add, 2 = can remove),
        # r9 = country, [rsp+0x28] = CString* reason (the civic's requirements, with trigger icons)
        "signature": "bool (*)(const void* civic, const void* config, uint16_t flags, const void* country, void* reason)",
        "pattern": [(r"^movzx esi, r8w", ""), (r"^mov r15, rdx", ""), (r"^mov rbp, rcx", ""),
                    (r"^lea rcx, \[rbp \+ 0x210\]", "")],
        "prefilter": [0x210],
        "window": 40,
    },
    "CStrategicResource_GetMaximumForCountry": {
        "linux": "CStrategicResource::GetMaximumForCountry(CCountry const&) const",
        # MSVC: rcx = resource, rdx = CFixedPoint* out, r8 = country; the storage cap
        # (only meaningful when the resource's base maximum at +0x110 is >= 0)
        "signature": "int64_t* (*)(const void* resource, int64_t* out, const void* country)",
        "call_near": {"strings": ["RESOURCES_STORED_MAX", "RESOURCES_STORED"],
                      "anchor": '"RESOURCES_STORED_MAX"', "pick": "last_call_before"},
    },
    "CSpecialProjectInstance_IsSpeciesModification": {
        "linux": "CSpecialProjectInstance::IsSpeciesModification() const",
        # rcx = project: has species/colony pairs and the first pair's species is sapient
        "signature": "bool (*)(const void* project)",
        "pattern": [(r"^cmp dword ptr \[rcx \+ 0x", "], 0"), (r"^xor al, al", ""), (r"^ret", ""),
                    (r"^mov rax, qword ptr \[rcx \+ 0x", "]"), (r"^mov r8d, dword ptr \[rax \+ 8\]", ""),
                    (r"^movzx eax, byte ptr \[rax \+ 0x", "]"), (r"^and al, 1", ""), (r"^ret", "")],
        "reject": [r"^not al"],  # IsUplift is the same function with the flag inverted
        "prefilter_bytes": [b"\x44\x8B\x40\x08\x41\x8B\xC0\x25\xFF\xFF\xFF\x00"],
        "max_len": 4,
        "window": 30,
    },
    "CSpecialProjectInstance_IsUplift": {
        "linux": "CSpecialProjectInstance::IsUplift() const",
        # rcx = project: has species/colony pairs and the first pair's species is not sapient
        "signature": "bool (*)(const void* project)",
        "pattern": [(r"^cmp dword ptr \[rcx \+ 0x", "], 0"), (r"^xor al, al", ""), (r"^ret", ""),
                    (r"^mov rax, qword ptr \[rcx \+ 0x", "]"), (r"^mov r8d, dword ptr \[rax \+ 8\]", ""),
                    (r"^movzx eax, byte ptr \[rax \+ 0x", "]"), (r"^not al", ""), (r"^and al, 1", ""), (r"^ret", "")],
        "prefilter_bytes": [b"\x44\x8B\x40\x08\x41\x8B\xC0\x25\xFF\xFF\xFF\x00"],
        "max_len": 4,
        "window": 30,
    },
    "CCountry_GetIntelLevel": {
        "linux": "CCountry::GetIntelLevel(CGalacticObject const*) const",
        # rcx = country, rdx = system: EIntelLevel 0..4 (4 under the reveal cheat or for countries
        # that always have full intel; else the per-system byte, floored at 2 without fog of war)
        "signature": "uint8_t (*)(const void* country, const void* system)",
        "pattern": [(r"^shr rcx, 0x16", ""), (r"^test cl, 1", ""), (r"^and eax, 0xffffff", ""),
                    (r"^movzx r8d, byte ptr \[rcx \+ rax\]", ""), (r"^mov r8b, 4", ""), (r"^shr rcx, 0x15", "")],
        "prefilter_bytes": [b"\x48\xC1\xE9\x16\xF6\xC1\x01"],
        "window": 45,
    },
    "CCountry_HasAutoSurveyedSystem": {
        "linux": "CCountry::HasAutoSurveyedSystem(CGalacticObject const*) const",
        # rcx = country, rdx = system: true without the survey game rule or for the system owner
        "signature": "bool (*)(const void* country, const void* system)",
        # CCountry::CanSurveyDepositHolder: holder->GetSystem(), then HasAutoSurveyedSystem,
        # then _HasSurveyedDepositHolder ("already surveyed" if either)
        "call_near": {"strings": ["CAN_SURVEY_ALREADY_SURVEYED"], "anchor": r"^call qword ptr \[rax \+ 0x80\]",
                      "occurrence": 0, "pick": "first_call_after"},
    },
    "CCountry_HasSurveyedDepositHolder": {
        "linux": "CCountry::_HasSurveyedDepositHolder(CDepositHolder const*) const",
        # rcx = country, rdx = CDepositHolder (a planet's is at planet + 0x20)
        "signature": "bool (*)(const void* country, const void* deposit_holder)",
        "call_near": {"strings": ["CAN_SURVEY_ALREADY_SURVEYED"], "anchor": r"^call qword ptr \[rax \+ 0x80\]",
                      "occurrence": 0, "pick": "first_call_after", "skip": 1},
    },
    "CColony_CalcColonizationProgressPerc": {
        "linux": "CColony::CalcColonizationProgressPerc() const",
        # rcx = colony, rdx = CFixedPoint* out: colony pops / NDefines::NPop::COLONY_POPS_REQUIRED
        # (0..1 as a fixed point; the outliner shows it x100). Only meaningful while the colony is
        # under colonization (its colonizing_species is a real species).
        "signature": "int64_t* (*)(const void* colony, int64_t* out)",
        # CPlanetView::UpdatePlanetTopBar: after the COLONIZING_PLANET / SETTLING_PLANET title
        # (localize, change string, free) comes the progress call
        "call_near": {"strings": ["SETTLING_PLANET", "COLONIZING_PLANET"], "anchor": r'; "COLONIZING_PLANET"$',
                      "occurrence": 0, "pick": "first_call_after", "skip": 3},
    },
    "NHabitability_CalcHabitability": {
        "linux": "NHabitability::CalcHabitability(CSpecies const&, CColonyCarrier const&, CCountry const&, CPlanetClass const&, CPopGroup const*, CModifier const*)",
        # rcx = CFixedPoint* out (0..1 x100000), rdx = species, r8 = colony carrier (planet + 0x20),
        # r9 = country (whose modifiers apply), then planet class (carrier + 0x128), pop group, modifier
        "signature": "int64_t* (*)(int64_t* out, const void* species, const void* carrier, const void* country, const void* planet_class, const void* pop_group, const void* modifier)",
        # the (CPopGroup, CColonyCarrier, CModifier) overload: species of the pop group, the
        # carrier's planet class at +0x128, then its only call is the core
        "pattern": [(r"^mov rax, qword ptr \[rbx \+ 0x128\]", ""), (r"^mov r8, rbx", ""),
                    (r"^mov qword ptr \[rsp \+ 0x30\], 0", ""), (r"^call", "")],
        "prefilter_bytes": [b"\x48\x8B\x83\x28\x01\x00\x00"],
        "max_len": 40,
        "window": 30,
        "follow_call": True,
    },
    "CColony_CalcMaxBuildings": {
        "linux": "CColony::CalcMaxBuildings(CZone const&, EPlanetBuildingOwnerType, CCountry const&) const",
        # rcx = colony, rdx = zone, r8d = owner type (0 = the colony owner), r9 = country;
        # the zone's building slot count as the planet view shows it
        "signature": "int (*)(const void* colony, const void* zone, int owner_type, const void* country)",
        "pattern": [(r"^mov rbp, rcx", ""), (r"^mov r14, r9", ""), (r"^mov rcx, qword ptr \[rcx \+ 0xf78\]", ""),
                    (r"^mov ebx, r8d", ""), (r"^mov rdi, rdx", ""), (r"^call", ""), (r"^sub r11d, 1", "")],
        "prefilter": [0xF78],
        "window": 20,
    },
    "CFleetManagerView_Update": {
        "linux": "CFleetManagerView::Update()",
        # rcx = view; the fleet manager window's per-frame update (template grid, reinforce calc)
        "signature": "void (*)(void* view)",
        # the template grid entry shares FLEET_MANAGER_NEW_TEMPLATE but not NAVY_LIMIT_VALUE
        "strings": ["FLEET_MANAGER_NEW_TEMPLATE", "NAVY_LIMIT_VALUE"],
    },
    "CHasFlagTrigger_ActualEvaluate": {
        "linux": "CHasFlagTrigger::ActualEvaluate(CEventScope&) const",
        # rcx = trigger, rdx = scope. Shared by all 30 has_*_flag trigger vtables. Static flag id
        # (u16) and the dynamic base-name size are trigger members; the container comes from the
        # virtual GetFlags(trigger, scope)
        "signature": "bool (*)(const void* trigger, void* scope)",
        # MSVC splits it: the aligned .pdata chunk is only the first 14 bytes, so the prefilter sits there
        "pattern": [(r"^cmp qword ptr \[rcx \+ 0x[0-9a-f]+\], 0$", ""), (r"^call 0x", ""),
                    (r"^movzx ebx, word ptr \[rsp", ""), (r"^movzx ebx, word ptr \[rcx \+ 0x", ""),
                    (r"^call qword ptr \[rax \+ 0x[0-9a-f]+\]$", ""), (r"^movsxd rcx, dword ptr \[rax \+ 0x[0-9a-f]+\]$", ""),
                    (r"^mov rax, qword ptr \[rax \+ 0x[0-9a-f]+\]$", ""), (r"^cmp word ptr \[rax\], bx$", "")],
        "prefilter_bytes": [b"\x40\x53\x48\x83\xEC\x30\x48\x83\xB9"],  # push rbx; sub rsp,30h; cmp qword [rcx+disp32],
        "window": 40,
    },
    "CPdxIntegerFlags_UpdateFlags": {
        "linux": "CPdxIntegerFlags::UpdateFlags()",
        # rcx = flags container; daily expiry: for i = count-1..0, if days[i] > -1 and --days[i] == 0,
        # swap-remove i. Runs in the parallel DailyUpdate flag tasks
        "signature": "void (*)(void* flags)",
        "pattern": [(r"^mov esi, dword ptr \[rcx \+ 0x[0-9a-f]+\]$", ""), (r"^sub esi, 1$", ""),
                    (r"^mov rcx, qword ptr \[rbx \+ 0x[0-9a-f]+\]$", ""), (r"^mov eax, dword ptr \[rcx \+ rdi\]$", ""),
                    (r"^cmp eax, -1$", ""), (r"^jle", ""), (r"^sub eax, 1$", ""), (r"^mov dword ptr \[rcx \+ rdi\], eax$", "")],
        "prefilter_bytes": [b"\x83\xEE\x01\x0F\x88"],  # sub esi,1; js rel32
        "window": 20,
    },
    "CModifierNodeManager_Update": {
        "linux": "NModifierNode::CModifierNodeManager<CModifier, EModifierNodeCategory>::Update()",
        # rcx = manager. The modifier graph flush: returns if batched or busy; if anything was
        # invalidated, runs the parallel graph job over every dirty node with the RNG forbidden
        "signature": "void (*)(void* mgr)",
        "pattern": [(r"^cmp byte ptr \[rcx \+ 0x[0-9a-f]+\], 0$", ""), (r"^xchg byte ptr \[rcx \+ 0x[0-9a-f]+\], al$", ""),
                    (r"^xchg byte ptr \[rcx \+ 0x[0-9a-f]+\], al$", ""), (r"^lea r14, \[rcx \+ 0x[0-9a-f]+\]$", ""),
                    (r"^mov byte ptr \[rip \+ 0x[0-9a-f]+\], 1$", ""), (r"^call", ""), (r"^mov ebx, dword ptr \[rax \+ 0x", "]"),
                    (r"^or ebx, 2$", "")],
        "prefilter_bytes": [b"\x83\xCB\x02"],  # or ebx, 2 (the flag offsets move between patches)
        "window": 36,
    },
    "CRandomLog_Get": {
        "linux": "CRandomLog::Get() (the random-number log whose config the flush ORs with 2)",
        "signature": "void* (*)()",
        # the first direct call in CModifierNodeManager::Update
        "pattern": [(r"^cmp byte ptr \[rcx \+ 0x[0-9a-f]+\], 0$", ""), (r"^xchg byte ptr \[rcx \+ 0x[0-9a-f]+\], al$", ""),
                    (r"^xchg byte ptr \[rcx \+ 0x[0-9a-f]+\], al$", ""), (r"^lea r14, \[rcx \+ 0x[0-9a-f]+\]$", ""),
                    (r"^mov byte ptr \[rip \+ 0x[0-9a-f]+\], 1$", ""), (r"^call", ""), (r"^mov ebx, dword ptr \[rax \+ 0x", "]"),
                    (r"^or ebx, 2$", "")],
        "prefilter_bytes": [b"\x83\xCB\x02"],
        "window": 36,
        "follow_call": True,
    },
    "CModifierNodeManager_AddInvalid": {
        "linux": "(inlined) CModifierNodeBase::Invalidate -> per-thread invalid-id set insert",
        # rcx = manager, edx = node id, r8d = node category. The only writer of the manager's
        # "has invalid" byte; the 209 inlined Invalidate copies all end here
        "signature": "void (*)(void* mgr, uint32_t node_id, uint32_t category)",
        "pattern": [(r"^add rcx, 0x30$", ""), (r"^call", ""), (r"^xor eax, 0x811c9dc5$", ""),
                    (r"^mov byte ptr \[rdi \+ 0x[0-9a-f]+\], 1$", "")],
        "prefilter": [0x811C9DC5],
        "window": 40,
    },
    "CModifierNodeBase_Update": {
        "linux": "NModifierNode::CModifierNodeBase<CModifier, EModifierNodeCategory>::Update()",
        # rcx = node. On-demand rebuild: under the node mutex, if the dirty byte was set, clear the
        # modifier and run the node's calc (which updates dirty parents first)
        "signature": "void (*)(void* node)",
        "pattern": [(r"^cmp dword ptr \[rcx \+ 8\], -1$", ""), (r"^movzx eax, byte ptr \[rcx \+ 0x[0-9a-f]+\]$", ""),
                    (r"^lea rdi, \[rcx \+ 0x[0-9a-f]+\]$", ""), (r"^xchg byte ptr \[rbx \+ 0x[0-9a-f]+\], al$", ""),
                    (r"^call qword ptr \[rax \+ 0x80\]$", "")],
        "prefilter": [0x108, 0x110, 0x150],
        "window": 30,
    },
    "CPdxModifier_AddModifierInternal": {
        "linux": "CPdxModifier<...>::AddModifierInternal(CModifier const&, CPdxPooledModifierAllocator<CModifier>&, CFixedPoint, ModifierCategory, ModifierCategory, CPdxModifierName const*)",
        # rcx = dst modifier, rdx = src; the merge (read here only for the CModifier layout)
        "signature": "void (*)(void* dst, const void* src, void* alloc, int64_t mult, uint32_t incl, uint32_t excl, const void* const* name)",
        "pattern": [(r"^call qword ptr \[rax \+ 0x40\]$", ""), (r"^imul rcx, rax, 0xb0$", ""), (r"^cmp rbx, 0x186a0$", ""),
                    (r"^call", ""), (r"^call", "")],
        "prefilter": [0x186A0, 0xB0],
        "window": 60,
    },
    "CGameState_UpdateShipParallel": {
        "linux": "CGameState::MicroUpdate() -- the fleet parallel-for (CFleet::MicroUpdateParallel), split out on Windows",
        # the parallel-for over every fleet each micro tick; its partition (task count and chunk
        # size) is inlined here (anchors.py: UpdateShipParallel_GrainClamp)
        "signature": "void (*)(void* game_state)",
        "strings": ["UpdateShipParallel, created %d random values, last one is %d"],
    },
    "CEventTarget_GetScope": {
        "linux": "CEventTarget::GetScope(CEventScope const&, char const*) const",
        # rcx = target, rdx = CEventScope* out (hidden return, copy-constructed from the input),
        # r8 = input scope, r9 = location string for error logs. Every scope switch (owner, from,
        # prev, event_target:x, ...) resolves here
        "signature": "void* (*)(const void* target, void* out_scope, const void* in_scope, const char* location)",
        "strings": ["Undefined event target: %s, location: %s"],
        # the string is also used by 0x1ACBC40; the 0x748-byte frame tells them apart (the flag
        # tests sit too deep in the function for the matcher's scan window)
        "require": [r"sub rsp, 0x748"],
    },
    "CEventScope_Copy": {
        "linux": "CEventScope::Copy(CEventScope const&)",
        # rcx = dst, rdx = src; deep-copies the event target container (+ local_ variables) when the
        # source has one
        "signature": "void (*)(void* dst, const void* src)",
        "pattern": [(r"^cmp r8, 0x8000000$", ""), (r"^mov rbx, qword ptr \[r15 \+ 0x[0-9a-f]+\]$", ""),
                    (r"^mov ecx, 0x58$", "")],
        "prefilter_bytes": [b"\x49\x81\xF8\x00\x00\x00\x08"],  # cmp r8, 0x8000000
        "window": 60,
    },
    "GetDynamicFlag": {
        "linux": "GetDynamicFlag(CEventScope&, CEventTarget const&, CString const&, CString const&, bool)",
        # rcx = u16* out, rdx = scope, r8 = @-target, r9 = base name, [rsp+0x28] = location, [rsp+0x30] = log.
        # Resolves `name@target` (dynamic event targets and flags): a nested GetScope for the target,
        # a CString build of base + decimal id, then a hash lookup in the flag name table
        "signature": "uint16_t* (*)(uint16_t* out, void* scope, const void* target, const void* base, const void* where, bool log)",
        "strings": ["Could not get dynamic flag '%s' with target '%s' in scope: '%s' at %s"],
    },
    "CInGameIdler_SetPaused": {
        "linux": "CInGameIdler::SetPaused(SPauseGameSettings const&)",
        # rcx = idler, rdx = SPauseGameSettings: +0x10 std::string who (MSVC: 16-byte buffer,
        # +0x20 size, +0x28 capacity), +0x30 bool paused, +0x31 source (2 = bypasses the lock
        # a named pauser holds at idler + 0x595)
        "signature": "void (*)(void* idler, const void* settings)",
        "strings": ["Paused changed to %s by %s"],
    },
    "CInGameIdler_SetGameSpeed": {
        "linux": "CInGameIdler::SetGameSpeed(int)",
        # rcx = idler, edx = speed (clamped to 0..5); restarts the tick timer unless paused
        "signature": "void (*)(void* idler, int speed)",
        "pattern": [(r"^cmp byte ptr \[rcx \+ 0x", "], 0"), (r"^mov edi, edx", ""), (r"^mov rbx, rcx", ""),
                    (r"^mov edx, dword ptr \[rcx \+ 0x", "]"), (r"^inc edx", ""), (r"^call", ""),
                    (r"^mov dword ptr \[rbx \+ 0x", "], edi"), (r"^test edi, edi", "")],
        "prefilter_bytes": [b"\x8B\xFA\x48\x8B\xD9"],  # mov edi, edx; mov rbx, rcx
        "max_len": 20,
        "window": 12,
    },
    "CFleetManagerTemplateGridController_Update": {
        "linux": "CFleetManagerTemplateGridController::Update(CPdxArray<TPdxRef<CFleetTemplate>> const&, CContainerWindow*, CStandardGridBox*)",
        # rcx = view + 0x690 (Linux + 0x5c8); returns the selected row or < 0
        "signature": "int (*)(void* controller, const void* templates, void* window, void* grid)",
        # the first call after CFleetManagerView::Update stores its throttle flag (inlined
        # ShouldUpdateExpensiveThisFrame: `(int)(clock * 100) % 8`, `and eax, 0x80000007`)
        "call_near": {"strings": ["FLEET_MANAGER_NEW_TEMPLATE", "NAVY_LIMIT_VALUE"],
                      "anchor": r"^and eax, 0x80000007$", "pick": "first_call_after"},
    },
    "CFleet_CalcMilitaryPower": {
        "linux": "CFleet::CalcMilitaryPower(int) const",
        # rcx = fleet, rdx = CFixedPoint* out (returned in rax), r8d = power type, r9b = forwarded
        # to CShip::CalcMilitaryPower. Sums every ship from scratch; Linux inlines it into
        # CFleet::BuildFleetOffensivePowerString
        "signature": "int64_t* (*)(const void* fleet, int64_t* out, int type, bool flag)",
        "pattern": [(r"^movzx r14d, r9b", ""), (r"^cmp byte ptr \[rcx \+ 0x1280\], 0xa", ""),
                    (r"^movsxd rax, dword ptr \[rcx \+ 0x32c\]", ""), (r"^mov rbx, qword ptr \[rcx \+ 0x320\]", ""),
                    (r"^call", ""), (r"^cmp byte ptr \[rcx \+ 0x1280\], 4", "")],
        "prefilter_bytes": [b"\x80\xB9\x80\x12\x00\x00\x0A"],  # cmp byte ptr [rcx + 0x1280], 0xa
        "window": 70,
    },
    # --- fleet paths: DrawMovementDebugLines ("ETA %.1f days") inlines CFleetMovementManager::
    # CalcPath: it builds a CFleetPath on the stack, computes the path-find settings, calls
    # CFleetPath::Create, then CFleetPath::CalcEstimatedDays, and frees the node array
    "CPlanet_CanColonize": {
        "linux": "CPlanet::CanColonize(CCountry const*, CString*) const",
        # rcx = planet, rdx = country, r8 = CString* reason (nullptr when none); what
        # CFleetColonizePlanetCommand::IsValid asks (with a null reason) before CanQueue
        "signature": "bool (*)(const void* planet, const void* country, void* reason)",
        "strings": ["COLONIZABLE_UNSURVEYED", "COLONIZABLE_INSIDE_OTHER_BORDERS"],
    },
    "CGalacticObject_GetClaimsBy": {
        "linux": "CGalacticObject::GetClaimsBy(CCountry const*) const",
        # rcx = system, rdx = CClaim* out (vtable, owner +8, date +0xC, claims +0x10; returned in
        # rax), r8 = country; a default CClaim (claims 0) when the country has none there
        "signature": "void* (*)(const void* system, void* out_claim, const void* country)",
        # CRemoveSystemClaimCommand::IsValid compares the claims it removes with this first
        "vtable_call": {"command": "remove_system_claim_command", "slot": 8, "call_index": 0},
    },
    # --- ship designs: the designer's own edit path (CShipDesignerBase::SetComponentOnSlot: find
    # the stage's section for the slot, CShipDesignSection::SetComponentOnSlot, then
    # CShipGrowthStage::UpdateResources)
    "CShipDesignerBase_SetComponentOnSlot": {
        "linux": "CShipDesignerBase::SetComponentOnSlot(int, CComponentTemplate const*, CComponentSlot const*, int)",
        # UI only; anchors.py reads the design layout out of it
        "signature": "void (*)(void* designer, int stage, const void* component, const void* slot, int section_slot)",
        "strings": ["designer_add_utility", "designer_add_weapon"],
    },
    "CShipDesignSection_SetComponentOnSlot": {
        "linux": "CShipDesignSection::SetComponentOnSlot(CComponentTemplate const*, CComponentSlot const*)",
        # rcx = section, rdx = component template, r8 = the section template's slot; replaces the
        # component in that slot or inserts one (only if the template's own check passes)
        "signature": "void (*)(void* section, const void* component, const void* slot)",
        # the first call once the section index is found (`cmp r8d, -1`)
        "call_near": {"strings": ["designer_add_utility", "designer_add_weapon"], "anchor": r"^cmp r\w+d, -1$",
                      "pick": "first_call_after"},
    },
    "CShipGrowthStage_UpdateResources": {
        "linux": "CShipGrowthStage::UpdateResources()",
        # rcx = stage; recomputes the stage's cost / upkeep from its hull, sections and components
        "signature": "void (*)(void* stage)",
        "call_near": {"strings": ["designer_add_utility", "designer_add_weapon"], "anchor": r"^cmp r\w+d, -1$",
                      "pick": "first_call_after", "skip": 1},
    },
    "CShipDesign_CalcLongName": {
        "linux": "CShipDesign::CalcLongName()",
        # rcx = design; rebuilds the long name ("<NAME> <ship class>") from the name and hull
        "signature": "void (*)(void* design)",
        "strings": ["LONG_SHIPCLASS_NAME"],
    },
    "CShipGrowthStage_IsValidToSaveForCountry": {
        "linux": "CShipGrowthStage::IsValidToSaveForCountry(EDesignOwner, CCountry const&, CString*) const",
        # rcx = stage, edx = EDesignOwner (0 country), r8 = country, r9 = CString* reason; the ship
        # designer's save check (hull allowed, required components, valid sections and components)
        "signature": "bool (*)(const void* stage, uint32_t owner, const void* country, void* reason)",
        "strings": ["SHIPDESIGNER_SAVEFAIL_INVALID_SHIP_SIZE", "SHIPDESIGNER_SAVEFAIL_WRONG_REQUIRED_COMPONENTS"],
    },
    "NShipDesignUtil_CanBuildComponent": {
        "linux": "NShipDesignUtil::CanBuildComponent(CComponentTemplate const*, EDesignOwner, CShipGrowthStage const&, CComponentSlot const*, CString*)",
        # rcx = component, edx = EDesignOwner (0 country), r8 = stage, r9 = slot (nullptr for a required
        # component), [rsp+0x28] = CString* reason: the designer's check (allowed on this hull, valid
        # for the country, technology, with the missing techs in the reason)
        "signature": "bool (*)(const void* component, uint32_t owner, const void* stage, const void* slot, void* reason)",
        "strings": ["COMPONENT_CANT_BUILD_MISSING_TECH"],
    },
    "CShipDesignerBase_ComponentIsAllowedOnSlot": {
        "linux": "CShipDesignerBase::ComponentIsAllowedOnSlot(CComponentTemplate const*, CComponentSlot const*, CString*) const",
        # UI only: slot size / slot type against the component's, then CanBuildComponent; anchors.py
        # reads those fields and the "any" values out of it
        "signature": "bool (*)(const void* designer, const void* component, const void* slot, void* reason)",
        "pattern": [(r"^movzx eax, byte ptr \[r8 \+ 0x[0-9a-f]+\]$", ""), (r"^cmp al, byte ptr \[rdx \+ 0x[0-9a-f]+\]$", ""),
                    (r"^cmp al, 0xb$", ""), (r"^movzx eax, byte ptr \[r8 \+ 0x[0-9a-f]+\]$", ""),
                    (r"^cmp al, byte ptr \[rdx \+ 0x[0-9a-f]+\]$", ""), (r"^cmp al, 4$", "")],
        "prefilter_bytes": [b"\x3C\x0B", b"\x3C\x04", b"\x41\x0F\xB6\x80"],  # cmp al, 0xb; cmp al, 4; movzx eax, [r8+d32]
        "window": 24,
    },
    "CComponentTemplate_CanBeBuiltBy": {
        "linux": "CComponentTemplate::CanBeBuiltBy(CCountry const&, EDesignOwner) const",
        # rcx = component template, rdx = country, r8d = EDesignOwner (0 country); technology and
        # owner restrictions (what the designer lists as available)
        "signature": "bool (*)(const void* component, const void* country, uint32_t owner)",
        "pattern": [(r"^mov edi, r8d$", ""), (r"^mov rbx, rdx$", ""), (r"^mov r15, rcx$", ""),
                    (r"^test byte ptr \[rcx \+ 0x10\], 1$", ""), (r"^lea rcx, \[rdx \+ 0x18\]$", "")],
        "prefilter_bytes": [b"\xF6\x41\x10\x01"],  # test byte ptr [rcx + 0x10], 1
        "window": 20,
    },
    "CCreateOrUpdateShipDesignCommand_CtorCountry": {
        "linux": "CCreateOrUpdateShipDesignCommand::CCreateOrUpdateShipDesignCommand(CShipDesign const*, TPdxRef<CCountry>)",
        # rcx = command memory (create_or_update_ship_design::kSize), rdx = source design (copy-
        # constructed into +0x20), r8d = country; owner type 0 (country), no federation. The
        # federation / galactic community variants store 1 / 2 as the owner type
        "signature": "void* (*)(void* command, const void* design, uint32_t country)",
        "pattern": [(r"^lea rax, \[rip \+ 0x[0-9a-f]+\]$", ""), (r"^call 0x", ""),
                    (r"^mov dword ptr \[rdi \+ 0x228\], ebx$", ""), (r"^mov dword ptr \[rdi \+ 0x22c\], 0xffffffff$", ""),
                    (r"^mov dword ptr \[rdi \+ 0x230\], esi$", "")],
        "prefilter_bytes": [b"\xC7\x87\x2C\x02\x00\x00\xFF\xFF\xFF\xFF"],  # mov dword ptr [rdi+0x22c], -1
        "window": 30,
    },
    "DrawMovementDebugLines": {
        "linux": "DrawMovementDebugLines()",
        # not called by the bridge; anchors.py reads the CFleetPath / coordinate vtables out of it
        "signature": "void (*)()",
        "strings": ["ETA %.1f days"],
    },
    "CFleetPath_Create": {
        "linux": "CFleetPath::Create(CCelestialCoordinate const&, CCelestialCoordinate const&, CGalacticObject const*, CFleet const*, CSimpleBitMask<EPathFindSettings>)",
        # rcx = path (vt, CPdxArray<SNode> +8: data +0x10, size +0x1C; CGameDate +0x20), rdx = from,
        # r8 = to (CCelestialCoordinate, 0x28 bytes), r9 = avoid system (TPdxNullObject<CGalacticObject>),
        # [rsp+0x20] = fleet, [rsp+0x28] = settings
        "signature": "void (*)(void* path, const void* from, const void* to, const void* avoid, const void* fleet, uint32_t settings)",
        # settings = CalcMovementPathFindSettings: `neg ecx; and ecx, 1; or ecx, 2`, then Create
        "call_near": {"strings": ["ETA %.1f days"], "anchor": r"^or ecx, 2$", "pick": "first_call_after"},
    },
    "CFleet_PathFindSettingsFlag": {
        "linux": "CFleet::CalcMovementPathFindSettings() const (MSVC: the bool part; settings = flag ? 3 : 2)",
        # rcx = fleet; true when the fleet is passive, an AI fleet that must avoid danger, or flagged
        "signature": "bool (*)(const void* fleet)",
        "call_near": {"strings": ["ETA %.1f days"], "anchor": r"^or ecx, 2$", "pick": "last_call_before"},
    },
    "CFleetPath_CalcEstimatedDays": {
        "linux": "CFleetPath::CalcEstimatedDays(CFleet const*, CFixedPoint*) const",
        # rcx = path, rdx = CFixedPoint* out (returned in rax), r8 = fleet, r9 = CFixedPoint[size]
        # per-node days (nullptr when not wanted)
        "signature": "int64_t* (*)(const void* path, int64_t* out_days, const void* fleet, int64_t* per_node)",
        # after the red debug-line colour: two __chkstk probes for the alloca'd buffers, then the call
        "call_near": {"strings": ["ETA %.1f days"], "anchor": r"^mov dword ptr \[rbp \+ 0x[0-9a-f]+\], 0xff0000ff$",
                      "pick": "first_call_after", "skip": 2},
    },
    "CRT_operator_delete": {
        "linux": "operator delete(void*)",
        # frees engine allocations (kRvaEngineAlloc); here: the empty path's node array
        "signature": "void (*)(void* p)",
        "call_near": {"strings": ["ETA %.1f days"], "anchor": r"^cmp dword ptr \[rbp \+ 0x[0-9a-f]+\], 0$",
                      "pick": "first_call_after"},
    },
    # --- helpers the bridge used through hand-written addresses (all calls go through the SDK)
    "PostCommand": {
        "linux": "PostCommandToSession(CCommand*, bool)",
        # rcx = command (ownership passes to the engine), dl = force (skip IsValid)
        "signature": "void (*)(void* command, bool force)",
        "pattern": [(r"^mov qword ptr \[rsp \+ 8\], rbx$", ""), (r"^mov qword ptr \[rsp \+ 0x10\], rbp$", ""),
                    (r"^mov qword ptr \[rsp \+ 0x18\], rsi$", ""), (r"^push rdi$", ""), (r"^sub rsp, 0x30$", ""),
                    (r"^movzx ebp, dl$", ""), (r"^mov rdi, rcx$", "")],
        "prefilter_bytes": [b"\x48\x89\x5c\x24\x08\x48\x89\x6c\x24\x10\x48\x89\x74\x24\x18\x57\x48\x83\xec\x30\x0f\xb6\xea\x48"],
        "window": 8,
    },
    "PdxLocalize": {
        "linux": "PdxLocalize(std::string_view) -> CString (return slot)",
        # rcx = CString* out (constructed here), rdx = {const char*, size_t} key view
        "signature": "void* (*)(void* out_cstring, const void* key_view)",
        "pattern": [(r"^push rbx$", ""), (r"^sub rsp, 0x40$", ""), (r"^mov rbx, rcx$", ""),
                    (r"^movups xmm0, xmmword ptr \[rdx\]$", ""), (r"^movaps xmmword ptr \[rsp \+ 0x20\], xmm0$", ""),
                    (r"^xor r9d, r9d$", ""), (r"^xor r8d, r8d$", ""), (r"^lea rdx, \[rsp \+ 0x20\]$", ""),
                    (r"^lea rcx, \[rsp \+ 0x30\]$", ""), (r"^call 0x", ""), (r"^nop", ""),
                    (r"^movups xmm1, xmmword ptr \[rax\]$", "")],
        "prefilter_bytes": [b"\x0F\x10\x02\x0F\x29\x44\x24\x20\x45\x33\xC9\x45\x33\xC0"],
        "window": 14,
    },
    "CString_Assign": {
        "linux": "CString::assign(char const*, size_t) (std::basic_string assign)",
        # rcx = CString (MSVC string at +0x10: buffer/pointer, size +0x20, capacity +0x28), rdx = chars, r8 = length
        "signature": "void* (*)(void* cstring, const char* chars, size_t length)",
        "pattern": [(r"^mov rbp, qword ptr \[rcx \+ 0x28\]$", ""), (r"^mov rsi, r8$", ""), (r"^mov r15, rdx$", ""),
                    (r"^mov rbx, rcx$", ""), (r"^cmp r8, rbp$", ""), (r"^ja ", ""),
                    (r"^cmp qword ptr \[rcx \+ 0x28\], 0x10$", ""), (r"^lea rdi, \[rcx \+ 0x10\]$", "")],
        "prefilter_bytes": [b"\x48\x8B\x69\x28\x49\x8B\xF0\x4C\x8B\xFA"],
        "window": 16,
    },
    "CString_Free": {
        "linux": "CString::~CString() (frees the heap buffer, back to an empty inline string)",
        "signature": "void (*)(void* cstring)",
        "pattern": [(r"^push rbx$", ""), (r"^sub rsp, 0x20$", ""), (r"^cmp qword ptr \[rcx \+ 0x28\], 0x10$", ""),
                    (r"^mov rbx, rcx$", ""), (r"^jb ", ""), (r"^cmp dword ptr \[rcx\], 1$", ""), (r"^je ", ""),
                    (r"^mov rcx, qword ptr \[rcx \+ 0x10\]$", ""), (r"^call 0x", ""),
                    (r"^mov byte ptr \[rbx \+ 0x10\], 0$", ""), (r"^mov qword ptr \[rbx \+ 0x20\], 0$", ""),
                    (r"^mov qword ptr \[rbx \+ 0x28\], 0xf$", "")],
        "prefilter_bytes": [b"\x48\x83\x79\x28\x10\x48\x8B\xD9"],
        "window": 13,
        "identical_ok": True,  # the linker kept a byte-identical copy
    },
    "CTraitSet_SetTraits": {
        "linux": "CTraitSet::SetTraits(CPdxArray<CSpeciesTrait const*, int> const&)",
        # rcx = trait set (CSpecies::traits), rdx = CPdxArray {vtable, data +8, capacity +0x10, size +0x14}
        "signature": "void (*)(void* trait_set, const void* traits_array)",
        "pattern": [(r"^mov dword ptr \[rcx \+ 0x1c\], 0$", ""), (r"^mov rbx, rcx$", ""),
                    (r"^mov r9d, dword ptr \[rdx \+ 0x14\]$", ""), (r"^add rcx, 8$", ""),
                    (r"^mov r8, qword ptr \[rdx \+ 8\]$", ""), (r"^mov edx, dword ptr \[rcx \+ 0x14\]$", ""),
                    (r"^call 0x", ""), (r"^mov rcx, rbx$", ""), (r"^call 0x", ""), (r"^mov byte ptr \[rbx \+ 0x20\], 0$", "")],
        "prefilter_bytes": [b"\xC7\x41\x1C\x00\x00\x00\x00"],
        "window": 14,
    },
    "CSpecies_CopyCtor": {
        "linux": "CSpecies::CSpecies(CSpecies const&)",
        # rcx = destination (uninitialized, CSpecies size), rdx = source species
        "signature": "void* (*)(void* species, const void* source)",
        "vtable_ref": {"layout": "CSpecies::WriteMembers", "window": 14,
                       "pattern": [r"^mov rsi, rdx$", r"^mov dword ptr \[rcx \+ 0x10\], 0xffffffff$", r"^lea rax, \[rip"]},
    },
    "CSpecies_Dtor": {
        "linux": "CSpecies::~CSpecies()",
        # rcx = species; destroys members in place (what the scalar deleting destructor calls)
        "signature": "void (*)(void* species)",
        "vtable_ref": {"layout": "CSpecies::WriteMembers", "window": 40,
                       "pattern": [r"^mov esi, edx$", r"^test sil, 1$"], "anchor": r"^test sil, 1$", "pick": "last_call_before"},
    },
    "GetLocalizedLeaderName": {
        "linux": "SLeaderName::GetLocalizedName (the %LEADER_1% / %LEADER_2% formatter)",
        # rcx = CString* out, rdx = leader name object, r8d = mode
        "signature": "void (*)(void* out_cstring, const void* name, int mode)",
        "strings": ["%LEADER_1%", "%LEADER_2%"],
        # anchored to the prologue: the body scan runs on into the next function
        "require": [r"^(?:[^|]*\| ){0,10}mov r15d, r8d \| mov rsi, rdx \| mov rdi, rcx \| lea rbx, \[rdx \+ 0x18\]"],
    },
    # --- species modification (trait points as the species view computes them)
    "NSpeciesModification_HasFreeSpeciesTraitPoints": {
        "linux": "NSpeciesModification::HasFreeSpeciesTraitPoints(CCountry const*, CSpecies const*, int*, int*)",
        # rcx = country, rdx = species, r8 = int* free trait points, r9 = int* free trait picks
        # (either may be null); true when both are positive
        "signature": "bool (*)(const void* country, const void* species, int* points, int* picks)",
        # CTopBarSpeciesViewImp::UpdateSelectedSpecies, right before the trait points text box;
        # it forwards the species' class, extra points and trait array to CalcFreeTraitPoints
        "call_near": {"strings": ["selected_species_amount", "selected_species_trait_points"],
                      "anchor": '"selected_species_trait_points"', "pick": "last_call_before",
                      "require": [r"^(?:[^|]*\| ){0,20}lea rax, \[rdx \+ 0x[0-9a-f]+\] \| mov edx, dword ptr \[rdx \+ 0x[0-9a-f]+\]"]},
    },
    "NSpeciesModification_CalcFreeTraitPoints": {
        "linux": "NSpeciesModification::CalcFreeTraitPoints(CCountry const*, int, int, CSpeciesClass const*, CPdxArray<CTrait const*> const&, int*, int*)",
        "signature": "void (*)(const void* country, int extra_points, int extra_picks, const void* species_class, const void* traits, int* points, int* picks)",
        # HasFreeSpeciesTraitPoints' call after it loads the species' extra trait points
        "call_in": {"from": "NSpeciesModification_HasFreeSpeciesTraitPoints", "anchor": r"^mov edx, dword ptr \[rdx \+ 0x[0-9a-f]+\]$",
                    "occurrence": 0, "pick": "first_call_after"},
    },
    "CTrait_GetCost": {
        "linux": "CTrait::GetCost(CCountry const*) const",
        # rcx = trait, rdx = country (null: the base cost); trait points it costs for that country
        "signature": "int (*)(const void* trait, const void* country)",
        # CalcFreeTraitPoints' only direct call in its loop over the trait array
        "call_in": {"from": "NSpeciesModification_CalcFreeTraitPoints", "anchor": r"^movsxd r\w+, dword ptr \[r\w+ \+ 0x14\]$",
                    "pick": "first_call_after"},
    },
    "CCountry_CalcAllPops": {
        "linux": "CCountry::CalcAllPops() const",
        # rcx = country; pops on all its owned colonies
        "signature": "int (*)(const void* country)",
        # the observer outliner's country tooltip: the count, then "NUM_POPS"
        "call_near": {"strings": ["NUM_EMPIRE_COLONIES", "CLICK_TO_OBSERVE"], "anchor": '"NUM_POPS"',
                      "pick": "last_call_before"},
    },
    # --- event options as the event window builds them (any window type: standard, leader story)
    "CEventWindow_Setup": {
        "linux": "CEventWindow::Setup()",
        # rcx = event window; builds the window and its option buttons
        "signature": "void (*)(void* window)",
        "strings": [" has no valid options!", "event_option_offset"],
    },
    "CEventWindow_ForEachShownOption": {
        "linux": "(inlined into CEventWindow::Setup) the options shown: the matching exclusive one, else every potential one",
        # rcx = scope, dl = window flag, r8 = event options array, r9 = callback object
        "signature": "void (*)(const void* scope, bool flag, const void* options, void* callback)",
        # Setup's call right after it loads the window flag byte
        "call_in": {"from": "CEventWindow_Setup", "anchor": r"^movzx edx, byte ptr \[r\w+ \+ 0x[0-9a-f]+\]$",
                    "pick": "first_call_after"},
    },
    "CEventOption_FindMatchingPotentialExclusiveOptionIndex": {
        "linux": "CEventOption::FindMatchingPotentialExclusiveOptionIndex(CEventScope const&, bool, CPdxArray<...> const&)",
        # rcx = scope, dl = window flag, r8 = event options array; the one option to show, or -1
        "signature": "int (*)(const void* scope, bool flag, const void* options)",
        "call_in": {"from": "CEventWindow_ForEachShownOption", "anchor": r"^movzx r\w+, dl$", "pick": "first_call_after"},
    },
    "CEventOption_IsPotentialIgnoreExclusive": {
        "linux": "CEventOption::IsPotentialIgnoreExclusive(CEventScope const&, bool, bool) const",
        # rcx = option, rdx = scope, r8b = window flag, r9b = true (as the window passes it)
        "signature": "bool (*)(const void* option, const void* scope, bool flag, bool b)",
        "call_in": {"from": "CEventWindow_ForEachShownOption", "anchor": r"^mov r9b, 1$", "pick": "first_call_after"},
    },
    "CEventWindow_AddOptionButton": {
        "linux": "CEventWindow::Setup()::$_4 (creates one option button)",
        # rcx = callback object, edx = option index, r8 = option
        "signature": "void (*)(void* callback, int index, const void* option)",
        "call_in": {"from": "CEventWindow_ForEachShownOption", "anchor": r"^mov r9b, 1$", "pick": "first_call_after",
                    "skip": 1},
    },
    "CEventOption_GetName": {
        "linux": "CEventOption::GetName(CEventScope const&) const",
        # rcx = the option's name (option + sdk::rt::CEventOption_name), rdx = CString* out, r8 = scope;
        # the button text
        "signature": "void* (*)(const void* option_name, void* out_cstring, const void* scope)",
        # the button builder's call after it addresses the option's name
        "call_in": {"from": "CEventWindow_AddOptionButton", "anchor": r"^lea rcx, \[r\w+ \+ 0x[0-9a-f]{3,}\]$",
                    "pick": "first_call_after"},
    },
    "CEventOption_IsAllowedSkipPotential": {
        "linux": "CEventOption::IsAllowedSkipPotential(CEventScope const&) const",
        # rcx = option, rdx = scope; whether the button is enabled
        "signature": "bool (*)(const void* option, const void* scope)",
        # the last direct call before the button stores its option index
        "call_in": {"from": "CEventWindow_AddOptionButton", "anchor": r"^mov dword ptr \[r(?!sp)\w+ \+ 0x20\], r\w+d$",
                    "pick": "last_call_before"},
    },
    "CGameState_OnSavedGameStarted": {
        "linux": "CGameState::OnSavedGameStarted()",
        # rcx = game state. Runs once when a loaded save (single player, multiplayer host or joining client)
        # starts, from CInGameIdler::RestoreDeviceObjects; fires on_single_player_save_game_load when the
        # idler's multiplayer flag is off
        "signature": "void (*)(void* game_state)",
        "strings": ["on_single_player_save_game_load"],
    },
    "CGameState_OnNewGameStarted": {
        "linux": "CGameState::OnNewGameStarted()",
        # rcx = game state. Runs once when a new galaxy starts, from CInGameIdler::RestoreDeviceObjects:
        # fires on_game_start, then CCountry::OnNewGameStarted for every country
        "signature": "void (*)(void* game_state)",
        "strings": ["on_game_start"],
    },
    "CIsMultiplayerTrigger_ActualEvaluate": {
        "linux": "CIsMultiplayerTrigger::ActualEvaluate(CEventScope&) const",
        # rcx = scope. `is_multiplayer = yes/no`: CGameIdler::IsMultiplayer() of g_CurrentInGameIdler (null =
        # no) compared with the trigger's yes/no byte; the getter is inlined, so this is where the flag's
        # offset is visible (anchors.py reads it)
        "signature": "bool (*)(const void* scope)",
        "pattern": [(r"^mov rax, qword ptr \[rip", "]"), (r"^test rax, rax$", ""), (r"^je ", ""),
                    (r"^cmp byte ptr \[rax \+ 0x[0-9a-f]+\], 0$", ""), (r"^je ", ""),
                    (r"^movzx eax, byte ptr \[rcx \+ 0x[0-9a-f]+\]$", ""), (r"^mov edx, 1$", ""),
                    (r"^cmp edx, eax$", ""), (r"^sete al$", ""), (r"^ret", "")],
        "prefilter_bytes": [b"\x80\xB8\x80\x01\x00\x00\x00"],  # cmp byte ptr [rax + 0x180], 0
        "window": 14,
    },
    # --- shipyard: a ship buildable for a design, as the starbase's ship list builds it
    "CShipDesignImplementation_Ctor": {
        "linux": "CShipDesignImplementation::CShipDesignImplementation(TPdxRef<CShipDesign>, int)",
        # rcx = implementation (sdk::rt::CShipDesignImplementation_size bytes), edx = design id,
        # r8d = growth stage (0 for a new ship); computes the design's values (RecalcSpecialValues).
        # Destroy with the vtable's deleting destructor (sdk::vt::CShipDesignImplementation_Destroy), flag 0
        "signature": "void* (*)(void* impl, uint32_t design_id, int growth_stage)",
        "pattern": [(r"^mov edi, r8d$", ""), (r"^mov ebx, edx$", ""), (r"^mov rsi, rcx$", ""),
                    (r"^lea rax, \[rip", ""), (r"^mov qword ptr \[rcx\], rax$", ""),
                    (r"^mov qword ptr \[rcx \+ 8\], 0$", ""), (r"^add rcx, 0x10$", ""), (r"^call 0x", ""),
                    (r"^mov dword ptr \[rsi \+ 0x[0-9a-f]+\], edi$", ""), (r"^lea rax, \[rip", ""),
                    (r"^mov qword ptr \[rsi\], rax$", ""), (r"^mov dword ptr \[rsi \+ 0x[0-9a-f]+\], ebx$", ""),
                    (r"^mov dword ptr \[rsi \+ 0x[0-9a-f]+\], 0xffffffff$", ""), (r"^mov rcx, rsi$", ""), (r"^call 0x", "")],
        "prefilter_bytes": [b"\x41\x8B\xF8\x8B\xDA"],  # mov edi, r8d; mov ebx, edx
        "window": 24,
    },
    "NConstruction_CreateColonyShipBuildable": {
        "linux": "NConstruction::CreateBuildable(CRefObjectOrbitableRef<CFleetOrbitableEnumType>, CShipDesignImplementation const&, SColonizationData const&)",
        # rcx = CBuildableBase** out, rdx = orbitable ref, r8 = implementation, r9 = SColonizationData
        # {designation +8, species +0x10, automation +0x14} (sdk::ent::SColonizationData); one
        # CBuildableColonyShip, as the starbase view builds a colony ship after picking the species
        "signature": "void** (*)(void** out, const void* orbitable, const void* impl, const void* colonization)",
        "pattern": [(r"^mov rbx, r9$", ""), (r"^mov rbp, r8$", ""), (r"^mov rsi, rdx$", ""), (r"^mov rdi, rcx$", ""),
                    (r"^mov ecx, 0x[0-9a-f]+$", ""), (r"^call 0x", "")],
        "prefilter_bytes": [b"\x49\x8B\xD9\x49\x8B\xE8"],  # mov rbx, r9; mov rbp, r8
        "window": 14,
    },
    "CMegaStructureType_CalcCostTable": {
        "linux": "CEconomicUnit<CStandardEconomicUnit<CMegaStructureType, CCountry, CEconomicUnitScopeRef<CCountry, void>>>::CalcTable<0>(CResourceTable&, CFixedPoint, bool) const",
        # rcx = {u32 country, u32 -1, scope (megastructure + CMegaStructure_economic_scope), type}, rdx =
        # CResourceTable* cost, r8d = 100000 (CFixedPoint 1), r9b = 0: what the upgrade command charges
        "signature": "void (*)(const void* unit, void* cost, int64_t multiplier, bool flag)",
        "call_in": {"command": "upgrade_megastructure_command", "slot": 9, "anchor": r"^mov r8d, 0x186a0$",
                    "pick": "first_call_after"},
    },
    "CMegaStructureType_IsPotentiallyUpgradableFrom": {
        "linux": "CMegaStructureType::IsPotentiallyUpgradableFrom(CCountry const*, CMegaStructure const*) const",
        # rcx = target type, rdx = country, r8 = megastructure: whether the type is an upgrade the
        # megastructure's view offers at all (upgrade_from, owner, potential); no reason text
        "signature": "bool (*)(const void* type, const void* country, const void* megastructure)",
        # the megastructure's owner (CMegaStructure::owner) and type (::type) read from r8
        "pattern": [(r"^mov r14, r8$", ""), (r"^mov rbp, rdx$", ""), (r"^mov r15, rcx$", ""),
                    (r"^mov edx, dword ptr \[r8 \+ 0x1b8\]$", ""), (r"^mov rsi, qword ptr \[r8 \+ 0x178\]$", ""),
                    (r"^cmp rbx, rbp$", "")],
        "prefilter_bytes": [b"\x4D\x8B\xF0\x48\x8B\xEA\x4C\x8B\xF9"],  # mov r14, r8; mov rbp, rdx; mov r15, rcx
        "window": 30,
    },
    "CMegaStructureType_IsPotentialInBuildMenu": {
        "linux": "CMegaStructureType::IsPotentialInBuildMenu(CCountry const&, CFleet const&) const",
        # rcx = type, rdx = country, r8 = construction fleet: whether the construction ship's build
        # menu lists the type (potential, then build_menu_potential)
        "signature": "bool (*)(const void* type, const void* country, const void* fleet)",
        "strings": [".build_menu_potential"],
    },
    "CCountry_HasPotentiallyBuildableMegaStructureForPlanet": {
        "linux": "CCountry::HasPotentiallyBuildableMegaStructureForPlanet(CPlanet const&, CFleet const&) const",
        # rcx = country, rdx = planet, r8 = fleet. Walks the megastructure types: planet-placed
        # (build type 0), IsPotentialInBuildMenu, IsPotentiallyBuildable, then the type's
        # placement rules (CPlacementRules::IsPossible) for the planet
        "signature": "bool (*)(const void* country, const void* planet, const void* fleet)",
        "pattern": [(r"^mov rbp, qword ptr \[rip \+ 0x", ""), (r"^cmp dword ptr \[rbp \+ 0x5c\], ebx$", ""),
                    (r"^mov rdi, qword ptr \[rsi \+ rax\]$", ""), (r"^cmp dword ptr \[rdi \+ 0x[0-9a-f]+\], 0$", ""),
                    (r"^call 0x", ""), (r"^call 0x", ""), (r"^lea rcx, \[rdi \+ 0x[0-9a-f]+\]$", ""), (r"^call 0x", "")],
        "prefilter_bytes": [b"\x39\x5D\x5C"],  # cmp dword ptr [rbp + 0x5c], ebx (the type count)
        "window": 40,
    },
    "CMegaStructureType_IsPotentiallyBuildable": {
        "linux": "CMegaStructureType::IsPotentiallyBuildable(CCountry const&, CFleet const&) const",
        # rcx = type, rdx = country, r8 = fleet: the build menu's second filter (the menu lists a
        # type when IsPotentialInBuildMenu and this hold; upgrade stages fail it)
        "signature": "bool (*)(const void* type, const void* country, const void* fleet)",
        "call_in": {"from": "CCountry_HasPotentiallyBuildableMegaStructureForPlanet",
                    "anchor": r"^cmp dword ptr \[rdi \+ 0x[0-9a-f]+\], 0$", "pick": "first_call_after", "skip": 1},
    },
    "CPlacementRules_IsPossible": {
        "linux": "CPlacementRules::IsPossible(CPlanet const*, CCountry const*, CString*) const",
        # rcx = the type's placement rules (CMegaStructureType_placement_rules), rdx = planet,
        # r8 = country, r9 = CString* reason
        "signature": "bool (*)(const void* rules, const void* planet, const void* country, void* reason)",
        "call_in": {"from": "CCountry_HasPotentiallyBuildableMegaStructureForPlanet",
                    "anchor": r"^lea rcx, \[rdi \+ 0x[0-9a-f]+\]$", "pick": "first_call_after"},
    },
    "CGalacticObject_CalcFTLPointWith": {
        "linux": "CGalacticObject::CalcFTLPointWith(CCelestialCoordinate const&) const",
        # rcx = system, rdx = CCelestialCoordinate* out, r8 = a coordinate elsewhere (another
        # system's): the point on the system's edge toward it (FTL radius * 1.05), origin = system.
        # Where the AI places outside-gravity-well megastructures
        "signature": "void* (*)(const void* system, void* out_coordinate, const void* toward)",
        "pattern": [(r"^mov rdi, rdx$", ""), (r"^mov eax, 0xb504f333$", ""), (r"^mov rdx, qword ptr \[rcx \+ 0x[0-9a-f]+\]$", ""),
                    (r"^mov rsi, rcx$", ""), (r"^mov r10, r8$", "")],
        "prefilter_bytes": [b"\xB8\x33\xF3\x04\xB5"],  # mov eax, 0xb504f333
        "window": 12,
    },
    "CMegaStructureType_CanAfford": {
        "linux": "CMegaStructureType::CanAfford(CCountry const&, CString*) const",
        # rcx = type, rdx = country, r8 = CString* reason; costs the type in the country's economic
        # scope (CCountry_economic_scope) with CMegaStructureType_CalcCostTable's CalcTable
        "signature": "bool (*)(const void* type, const void* country, void* reason)",
        "pattern": [(r"^mov rsi, r8$", ""), (r"^mov rbx, rdx$", ""), (r"^mov r8, rcx$", ""),
                    (r"^lea rcx, \[rdx \+ 0x[0-9a-f]+\]$", ""), (r"^mov eax, dword ptr \[rdx \+ 0x20\]$", ""),
                    (r"^mov dword ptr \[rbp \+ 4\], 0xffffffff$", "")],
        "prefilter_bytes": [b"\x49\x8B\xF0\x48\x8B\xDA\x4C\x8B\xC1"],  # mov rsi, r8; mov rbx, rdx; mov r8, rcx
        "window": 60,
    },
    "CStarbase_GetShipsBuildQueueRef": {
        "linux": "CStarbase::GetShipsBuildQueueRef() const",
        # rcx = starbase, rdx = TPdxRef<CConstructionQueue>* out; the queue its shipyard builds into:
        # its ship's single queue (+0x104) when the carrier uses one, else its own shipyard queue
        # (sdk::ent::CStarbase::shipyard_build_queue; the main queue getter reads build_queue instead)
        "signature": "uint32_t* (*)(const void* starbase, uint32_t* out)",
        "pattern": [(r"^mov rdi, rdx$", ""), (r"^mov rsi, rcx$", ""), (r"^call qword ptr \[rax \+ 0x[0-9a-f]+\]$", ""),
                    (r"^mov eax, dword ptr \[rbx \+ 0x[0-9a-f]+\]$", ""), (r"^mov eax, dword ptr \[rsi \+ 0x884\]$", "")],
        "prefilter_bytes": [b"\x84\x08\x00\x00"],
        "window": 50,
    },
    "NConstruction_CreateShipBuildable": {
        "linux": "NConstruction::CreateBuildable(CRefObjectOrbitableRef<CFleetOrbitableEnumType>, CShipDesignImplementation const&)",
        # rcx = CBuildableBase** out (engine heap object, or null), rdx = orbitable ref {id +0, type
        # byte +4, has_extra +8, extra +0x10}, r8 = implementation; the ship, federation or galactic
        # community buildable by the design's owner type (three 0x560-byte allocations)
        "signature": "void** (*)(void** out, const void* orbitable, const void* impl)",
        "pattern": [(r"^mov rsi, r8$", ""), (r"^mov rbx, rdx$", ""), (r"^mov rdi, rcx$", ""),
                    (r"^mov rax, qword ptr \[r8\]$", ""), (r"^mov rcx, r8$", ""), (r"^call qword ptr \[rax \+ 0x[0-9a-f]+\]$", "")],
        "prefilter_bytes": [b"\xB9\x60\x05\x00\x00"],
        "window": 16,
    },
    # --- UI entry points (the bridge checks the object's vtable before calling)
    "CMessage_LeftClick": {
        "linux": "CMessage::LeftClick()",
        # rcx = notification (CMessage); opens what the notification points at (event, view, camera)
        "signature": "void (*)(void* message)",
        "pattern": [(r"^mov rdi, rcx$", ""), (r"^mov rax, qword ptr \[rcx\]$", ""), (r"^call qword ptr \[rax \+ 0x38\]$", ""),
                    (r"^test al, al$", ""), (r"^je ", ""), (r"^mov rax, qword ptr \[rdi \+ 0x18\]$", ""),
                    (r"^cmp byte ptr \[rax \+ 0x100\], 0$", "")],
        "prefilter_bytes": [b"\x80\xB8\x00\x01\x00\x00\x00"],
        "window": 20,
    },
    "CAlertIconsWindow_Click": {
        "linux": "CAlertManager::Click(CGuiObject*)",
        # rcx = alert icons window (CInGameIdler's alerticon_window), rdx = the clicked alert banner;
        # dispatches to the alert type's handler
        "signature": "void (*)(void* alert_window, void* banner)",
        "strings": ["alerticon_banner", "minor_artifacts"],
    },
    "CStartScreenWindow_Close": {
        "linux": "CStartScreenWindow::Close()",
        # rcx = start screen window: hides it, focuses the capital, fires on_press_begin
        "signature": "void (*)(void* window)",
        "strings": ["on_press_begin"],
    },
    "CRT_purecall": {
        "linux": "__cxa_pure_virtual (MSVC: _purecall)",
        "signature": "void (*)()  -- calls the registered purecall handler, then abort()",
        # the static CRT's _purecall: fill for every pure slot in abstract vtables
        "mnemonics": ["sub", "call", "test", "je", "call", "call"],
        "min_rdata_refs": 100,
    },
}


def match_by_mnemonics(im, spec):
    """Functions referenced from .rdata at least min_rdata_refs times whose first
    instructions have exactly the given mnemonics."""
    counts = {}
    rd = im.img[im.rdata0:im.rdata1]
    for off in range(0, len(rd) - 8, 8):
        v = struct.unpack_from("<Q", rd, off)[0] - im.ib
        if im.text0 <= v < im.text1:
            counts[v] = counts.get(v, 0) + 1
    out = []
    want = spec["mnemonics"]
    for f, n in counts.items():
        if n < spec["min_rdata_refs"] or f % 16:
            continue
        ins = im.disasm_fn(f, 0x40)[:len(want)]
        if [i.mnemonic for i in ins] == want:
            out.append(f)
    return out


def match_by_strings(im, spec):
    """Functions that reference every given C string through a rip-relative operand."""
    import numpy as np
    t = np.frombuffer(im.img[im.text0:im.text1], dtype=np.uint8)
    n = len(t) - 4
    disp = (t[:n].astype(np.int64) | (t[1:n + 1].astype(np.int64) << 8) |
            (t[2:n + 2].astype(np.int64) << 16) | (t[3:n + 3].astype(np.int64) << 24))
    disp = np.where(disp >= 2 ** 31, disp - 2 ** 32, disp)
    # a disp32 at the end of the instruction (lea/mov reg, [rip+x]) points at insn_end + disp
    target = np.arange(n, dtype=np.int64) + im.text0 + 4 + disp
    sets = []
    for s in spec["strings"]:
        rvas = [m.start() for m in re.finditer(re.escape(s.encode() + b"\x00"), im.img)
                if im.rdata0 <= m.start() < im.rdata1]
        hits = np.nonzero(np.isin(target, rvas))[0]
        sets.append({im.fn_of(im.text0 + int(h)) for h in hits} - {None})
    found = set()
    for f in set.intersection(*sets):
        entry = aligned_entry(im, f)
        if entry is None:
            continue
        if spec.get("require"):
            text = " | ".join(f"{i.mnemonic} {i.op_str}" for i in im.disasm_fn(entry, 0x800))
            if not all(re.search(rx, text) for rx in spec["require"]):
                continue
        found.add(entry)
    return sorted(found)


def entry_of(im, rva):
    """The function containing rva. Leaf functions have no .pdata entry, so a hit past the end
    of the preceding function belongs to the last 16-byte-aligned start after int3 padding."""
    f = im.fn_of(rva)
    if f is None:
        return None
    end = im.fend.get(f, 0)
    if rva < end:
        return f
    g = (end + 15) & ~15
    best = None
    while g <= rva:
        if g == ((end + 15) & ~15) or im.img[g - 1] == 0xCC:
            best = g
        g += 16
    return best


def aligned_entry(im, f, reach=0x400):
    """MSVC splits functions into chunks; a string reference can land in a chunk that directly
    follows its 16-byte-aligned entry. Walk back to the nearest known aligned function start
    whose straight-line instructions reach `f`."""
    if f % 16 == 0:
        return f
    starts = im.fstarts if not callable(im.fstarts) else im.fstarts()
    for g in sorted((g for g in starts if f - reach < g < f and g % 16 == 0), reverse=True):
        addrs = [(i.address - im.ib if i.address > im.ib else i.address) for i in im.disasm_fn(g, f - g + 16)]
        if f in addrs:
            return g
    return None


def match_call_near(im, spec):
    """The direct call target nearest to an anchor inside the one function that references the
    given strings. The anchor is a regex over 'mnemonic op_str' plus a '; "string"' annotation
    for rip-relative loads of C strings."""
    cn = spec["call_near"]
    fns = match_by_strings(im, {"strings": cn["strings"]})
    # several functions may share the strings; they count if they all lead to one target
    targets = {t for f in fns for t in call_near_in(im, f, cn)}
    if cn.get("require"):
        # regexes over the target's opening instructions ("mnemonic op_str" joined by " | ")
        def head(t):
            return " | ".join(f"{i.mnemonic} {i.op_str}" for i in im.disasm_fn(t, 0x200)[:40])
        targets = {t for t in targets if all(re.search(rx, head(t)) for rx in cn["require"])}
    return sorted(targets)


def command_slot(im, token_name, slot):
    """A command's virtual function: its vtable (out/sdk.json, from emit_sdk) at `slot`."""
    sdk = json.loads((OUT / "sdk.json").read_text(encoding="utf-8"))
    vts = {c["vtable"] for c in sdk["commands"] if c["token_name"] == token_name}
    if len(vts) != 1:
        return None
    return im.q(vts.pop() + slot * 8) - im.ib


def call_near_in(im, fn, cn):
    lines = []
    for i in im.disasm_fn(fn, 0x4000):
        text = f"{i.mnemonic} {i.op_str}"
        m = re.search(r"rip \+ (0x[0-9a-f]+)\]", i.op_str)
        if m:
            addr = (i.address - im.ib if i.address > im.ib else i.address) + i.size + int(m.group(1), 16)
            if im.rdata0 <= addr < im.rdata1:
                text += f' ; "{im.cstr(addr, 80)}"'
        lines.append((i, text))
    idx = [k for k, (_, t) in enumerate(lines) if re.search(cn["anchor"], t)]
    # The linear sweep can run past the function into its neighbours; "occurrence" picks the
    # n-th hit (the function's own one comes first), otherwise the anchor must be unique.
    if "occurrence" in cn:
        if len(idx) <= cn["occurrence"]:
            return []
        k = idx[cn["occurrence"]]
    elif len(idx) != 1:
        return []
    else:
        k = idx[0]
    order = range(k + 1, len(lines)) if cn["pick"] == "first_call_after" else range(k - 1, -1, -1)
    skip = cn.get("skip", 0)
    for j in order:
        i, _ = lines[j]
        if i.mnemonic == "call" and i.op_str.startswith("0x"):
            if skip:
                skip -= 1
                continue
            t = int(i.op_str, 16)
            return [t - im.ib if t > im.ib else t]
    return []


def match_vtable_call(im, spec):
    """The call_index-th direct call in the given vtable slot of a command (vtables from sdk.json)."""
    vc = spec["vtable_call"]
    sdk = json.loads((OUT / "sdk.json").read_text(encoding="utf-8"))
    cmd = next((c for c in sdk["commands"] if c["token_name"] == vc["command"]), None)
    if not cmd:
        return []
    fn = im.q(cmd["vtable"] + vc["slot"] * 8) - im.ib
    calls = [int(i.op_str, 16) for i in im.disasm_fn(fn, 0x400) if i.mnemonic == "call" and i.op_str.startswith("0x")]
    if len(calls) <= vc["call_index"]:
        return []
    t = calls[vc["call_index"]]
    return [t - im.ib if t > im.ib else t]


def match_vtable_ref(im, spec):
    """Functions that store one of a class's vtables (`lea reg, [rip + vtable]`; vtables of the
    class's serializer from win_layouts.json) and whose first `window` instructions contain the
    pattern in order. With "pick" (an anchor regex and first_call_after / last_call_before), the
    answer is that call's target instead of the function."""
    vr = spec["vtable_ref"]
    layouts = json.loads((OUT / "win_layouts.json").read_text(encoding="utf-8"))["layouts"]
    vts = [a for a, _ in layouts.get(vr["layout"], {}).get("vtables", [])]
    lea = im.lea_index()
    cands = sorted({im.fn_of(r) for v in vts for r in lea.get(v, [])} - {None})
    out = []
    for f in cands:
        ins = im.disasm_fn(f, 0x800)[:vr.get("window", 60)]
        ops = [f"{i.mnemonic} {i.op_str}" for i in ins]
        k = 0
        for o in ops:
            if k < len(vr["pattern"]) and re.search(vr["pattern"][k], o):
                k += 1
        if k < len(vr["pattern"]):
            continue
        if "anchor" not in vr:
            out.append(f)
            continue
        hit = next((n for n, o in enumerate(ops) if re.search(vr["anchor"], o)), None)
        if hit is None:
            continue
        order = range(hit + 1, len(ins)) if vr.get("pick") == "first_call_after" else range(hit - 1, -1, -1)
        for n in order:
            if ins[n].mnemonic == "call" and ins[n].op_str.startswith("0x"):
                out.append(int(ins[n].op_str, 16) - im.ib)
                break
    return sorted(set(out))


def main():
    im = Image(EXE)
    text = im.img[im.text0:im.text1]
    result, failures = {}, []
    for name, spec in FUNCTIONS.items():
        if "caller_of" in spec:
            # the unique function that calls an already located one (a thin wrapper around it)
            target = result.get(spec["caller_of"], {}).get("rva")
            callers = set()
            if target is not None:
                for m in re.finditer(rb"\xe8", text):
                    i = m.start()
                    if im.text0 + i + 5 + struct.unpack_from("<i", text, i + 1)[0] == target:
                        e = aligned_entry(im, im.fn_of(im.text0 + i))
                        if e is not None:
                            callers.add(e)
            matches = sorted(callers)
            if len(matches) == 1:
                result[name] = {"rva": matches[0], "linux": spec["linux"], "signature": spec["signature"]}
                print(f"{name}: 0x{matches[0]:X}")
            else:
                failures.append(name)
                print(f"{name}: {len(matches)} callers {[hex(m) for m in matches]} -- fingerprint needs updating")
            continue
        if "call_in" in spec:
            # the call next to an anchor inside a function located earlier in this table, or inside
            # a command's vtable slot ({"command": token name, "slot": 8 IsValid / 9 Execute})
            ci = spec["call_in"]
            src = result.get(ci["from"], {}).get("rva") if "from" in ci else command_slot(im, ci["command"], ci["slot"])
            matches = call_near_in(im, src, ci) if src is not None else []
            if len(matches) == 1:
                result[name] = {"rva": matches[0], "linux": spec["linux"], "signature": spec["signature"]}
                print(f"{name}: 0x{matches[0]:X}")
            else:
                failures.append(name)
                print(f"{name}: {len(matches)} matches {[hex(m) for m in matches]} -- fingerprint needs updating")
            continue
        if "vtable_ref" in spec:
            matches = match_vtable_ref(im, spec)
            if len(matches) == 1:
                result[name] = {"rva": matches[0], "linux": spec["linux"], "signature": spec["signature"]}
                print(f"{name}: 0x{matches[0]:X}")
            else:
                failures.append(name)
                print(f"{name}: {len(matches)} matches {[hex(m) for m in matches]} -- fingerprint needs updating")
            continue
        if "mnemonics" in spec or "strings" in spec or "call_near" in spec or "vtable_call" in spec:
            matches = (match_by_mnemonics(im, spec) if "mnemonics" in spec else
                       match_by_strings(im, spec) if "strings" in spec else
                       match_vtable_call(im, spec) if "vtable_call" in spec else match_call_near(im, spec))
            if len(matches) == 1:
                result[name] = {"rva": matches[0], "linux": spec["linux"], "signature": spec["signature"]}
                print(f"{name}: 0x{matches[0]:X}")
            else:
                failures.append(name)
                print(f"{name}: {len(matches)} matches {[hex(m) for m in matches]} -- fingerprint needs updating")
            continue
        # functions containing every prefilter constant as an immediate
        sets = []
        needles = [struct.pack("<I", imm) for imm in spec.get("prefilter", [])] + spec.get("prefilter_bytes", [])
        for needle in needles:
            fns = {entry_of(im, im.text0 + m.start()) for m in re.finditer(re.escape(needle), text)}
            sets.append(fns - {None})
        cands = set.intersection(*sets)
        matches = []
        for f in sorted(cands):
            if f % 16:
                continue  # MSVC function entries are 16-byte aligned; others are split fragments
            if "max_len" in spec:
                body = im.disasm_fn(f, 0x800)
                ret = next((n for n, i in enumerate(body) if i.mnemonic in ("ret", "jmp")), len(body))
                if ret > spec["max_len"]:
                    continue
            ins = [f"{i.mnemonic} {i.op_str}" for i in im.disasm_fn(f, 0x800)[:spec["window"]]]
            if any(re.match(rx, s) for rx in spec.get("reject", []) for s in ins):
                continue  # a sibling with the same shape plus this instruction
            k = 0
            for s in ins:
                rx, needle = spec["pattern"][k]
                if re.match(rx, s) and s.endswith(needle):
                    k += 1
                    if k == len(spec["pattern"]):
                        matches.append(f)
                        break
        if spec.get("identical_ok") and len(matches) > 1:
            # the linker kept byte-identical copies (same instructions, same call targets): any one is it
            def body(f):
                out = []
                for i in im.disasm_fn(f, 0x200):
                    op = i.op_str
                    if i.mnemonic.startswith("j") and op.startswith("0x") and 0 <= int(op, 16) - im.ib - f < 0x200:
                        op = f"+{int(op, 16) - im.ib - f:#x}"  # branch inside the function
                    out.append(f"{i.mnemonic} {op}")
                return tuple(out)
            bodies = {body(f) for f in matches}
            if len(bodies) == 1:
                matches = [min(matches)]
        if spec.get("follow_call"):
            # the fingerprint matched a thin wrapper; the function wanted is what it calls
            targets = set()
            for f in matches:
                for i in im.disasm_fn(f, 0x200):  # the first direct call, however far in
                    if i.mnemonic == "call" and i.op_str.startswith("0x"):
                        t = int(i.op_str, 16)
                        targets.add(t - im.ib if t > im.ib else t)
                        break
            matches = sorted(targets)
        if len(matches) == 1:
            result[name] = {"rva": matches[0], "linux": spec["linux"], "signature": spec["signature"]}
            print(f"{name}: 0x{matches[0]:X}")
        else:
            failures.append(name)
            print(f"{name}: {len(matches)} matches {[hex(m) for m in matches]} -- fingerprint needs updating")
    (OUT / "functions.json").write_text(json.dumps(result, indent=1), encoding="utf-8")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
