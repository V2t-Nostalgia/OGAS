# Stellaris 4.4.6 Mod/native-hook compatibility investigation

> Publication: original/local evidence paths below are provenance labels, not Git downloads. Use the [indexed archive and access status](../research/EVIDENCE_ARCHIVE.md); public copies may be privacy-redacted and originals remain retained.


Status: passive live evidence and static runtime audit complete; no production
Action Registry admission was changed.

## Conclusion

Most ordinary content additions do not require a new native Hook merely
because their definition key is new. When a Mod-defined object enters an
existing engine database and the game uses an existing command type, OGAS can
reuse the same native submit/validation path.

That does **not** mean current OGAS is automatically compatible with every Mod.
The remaining boundary is usually definition discovery and legal-candidate
generation against the effective, load-order-resolved game state. Special
script-driven mechanics may require a new state query or Semantic Action, and
only require a new Hook when they do not converge on an already supported
native command/dispatcher.

## Evidence identity

The third Observe session used:

```text
Stellaris 4.4.6 Linux ELF Build ID
c6969e60fd81d738948222a94c0b5a0841abbffc

Mod inventory fingerprint
67135c2310f78fa9c18e046630b630114294dfc80b4022c6e8ec8b6867a4a43b
```

Configured order:

1. Stronger Leaders (`ugc_3209755015`, v0.0.2)
2. 31 Tradition Slots + 32 AP Slots (`ugc_3359568450`)
3. Galactic Stock Market (`ugc_3813910097`, v1.0.0)

The executable identity and content inventory are intentionally separate. A
content Mod can change effective definitions without changing the ELF Build
ID. External file indexing shows what is available on disk; the save-declared
Mod set and captured game objects show what this session actually used.

## Catalog comparison

At the comparison checkpoint:

| Catalog | Vanilla run | Mod run |
| --- | ---: | ---: |
| command records | 2,145,493 | about 1.14 million |
| command RTTI types | 115 | 106 |
| payload types | 49 | 47-48 |
| dropped/malformed/writer-dropped | 0 | 0 |

There were 105 common command RTTI types. The Mod run uniquely observed
`CStartTerraformationCommand`; the vanilla run uniquely observed ten types,
including speed controls, slave-market actions and emergency-measure actions.
These unequal-run set differences are coverage observations, not Mod
attribution.

The old vanilla catalog schema did not record layout fingerprints. Therefore
layout equality cannot be calculated from these two catalogs. An empty shared
fingerprint set must be reported as `comparison unavailable`, not as a changed
layout. `analyze_mod_hook_compatibility.py` enforces that distinction.

Both environments observed the same established native families, including:

| Command | Mod post/execute | Vanilla post/execute |
| --- | ---: | ---: |
| `CAddBuildableToQueueCommand` | 11,629 / 11,605 | 15,263 / 15,245 |
| `CBuildMegaStructureCommand` | 1,741 / 1,726 | 1,552 / 1,531 |
| `CResearchTechnologyCommand` | 2,174 / 2,174 | 3,799 / 3,799 |
| `CSelectEventOptionCommand` | 997 / 997 | 1,044 / 1,044 |
| `CSetPolicyCommand` | 94 / 94 | 200 / 200 |

This is strong evidence that enabling this Mod set did not replace the common
native command pipeline. It is not proof that every individual Mod object is
accepted by every current OGAS action.

## Concrete cases

### Stronger Leaders event

**Captured evidence.** Event `lxleader.100` appeared in the state stream with
title `lxleader100.title`, description `lxleader100.desc`, options
`lxleader100.2` and `lxleader100.1`, followed by one execution and removal.
Those keys match the indexed Mod files. The supplied save also contains the
event identifier.

**Meaning.** A Mod-defined scripted event reused the existing event lifecycle
and option-selection architecture. The existing state probe can expose its
stable keys, and `CSelectEventOptionCommand` remained the active native family.

**Boundary.** This does not yet prove an OGAS-initiated selection on a legal
open instance. That needs a disposable-save test using the captured event
instance and option index, followed by authoritative state/save confirmation.

### Galactic Stock Market policies

**Captured evidence.** All eleven indexed `gsm_policy_*` identifiers occur in
the current save, each repeatedly, and the session captured 94 post/execute
`CSetPolicyCommand` pairs.

**Static runtime evidence.** `set_empire_policy` resolves a policy group from
the live engine database, obtains the option from that group, constructs the
native command and calls the game's validator. This is the right architecture
for Mod-defined policy keys when they are in the same registry.

**Boundary.** The command records do not retain the policy key, so no captured
command can yet be causally attributed to Galactic Stock Market. The action is
still `paired_capture` and Broker-rejected pending a legal disposable-save
submission/postcondition test.

### Galactic Stock Market buildings

The Mod defines sixteen sampled `gsm_branch_*` buildings, but their definitions
declare `owner_type=subject_holding`, `can_build=no` and `can_demolish=no`. No
`gsm_branch_*` identifier was found in the inspected save.

These are not evidence for ordinary player `build_building` compatibility.
They appear script-managed and may be controlled by a market event or special
mechanic. A new building ID alone is not a reason to add a C++ Hook; first
identify the actual UI/script action and resulting command or event path.

### Technology and ship components

This Mod set provides no concrete indexed Mod technology or ship-component
case. The common research and ship-design command families were observed, but
there is no defensible per-Mod active example. Compatibility here remains a
static expectation requiring a suitable Mod and disposable-save validation.

## Runtime audit

### Reusable native boundary

`GameApi::ResolveStaticDefinition()` walks a configured live engine definition
database and compares semantic keys. It is not restricted to a compiled list
of vanilla IDs. Native governance actions already use it for policy groups,
traditions, ascension perks and council positions. This is the preferred Mod
compatibility path: resolve the current engine object, construct the existing
command, use the game's validator, and submit through the common session path.

### Current construction debt

The generated `build_building`, district, zone and research implementations
remain capture-backed adapters. For example, `build_building` requires private
fields such as `context_822c`, `build_queue_id`, `colony_id` and `zone_id`,
patches an ASCII `building_id` into a captured serialized body, and relies on
the captured command family.

This preserves known behavior but is not yet a general semantic resolver. It
does not ask the live engine for the current building definition, current
effective prerequisites, target queue semantics or a legal candidate. A Mod ID
that fits the capture field is not sufficient evidence that submitting it is
valid.

### Candidate-generation debt

`game_knowledge.py` currently scans the configured vanilla game root. It does
not evaluate active Mod load order, replacement semantics or the final merged
definition set. No integrated Mod Analyzer was found in this repository.

This is the main blocker for rule-changing Mods: the native Hook may still be
correct while OGAS proposes a candidate made illegal by an override. The
long-term source of truth should be a read-only live-engine candidate/query
surface, with an external load-order-aware parser used for explanation and
fallback rather than authority.

## Compatibility matrix

| Mod change | Existing Hook | Additional work |
| --- | --- | --- |
| New ordinary building/district/resource using an existing native command | normally reusable | live definition lookup plus legal target/candidate query |
| New technology in the normal research database | normally reusable | enumerate current alternatives and resolve live definition |
| New ship component used by the normal designer | common dispatcher likely reusable | current component/section legality and design validation |
| Modified prerequisites, costs or upgrade chains | Hook usually unchanged | query effective merged rules; never trust vanilla-only knowledge |
| New scripted event on the normal event path | event state and option command reusable | bind current event instance, scope and valid option |
| Script-only building or market UI mechanism | unknown | identify real semantic operation before adding an action |
| Entirely new diplomatic/order object | common submit may remain reusable | new typed Semantic Action and constructor/layout; special Hook only if no common choke point exists |

## Minimal automatic adaptation path

1. Fingerprint the executable and ordered content set separately.
2. Read legal candidates from the current live game state or engine definition
   database, retaining generation-bearing object identity where required.
3. Resolve a stable semantic key to the live native definition object.
4. Reuse the existing typed command constructor and common submit path.
5. Let the game's native validator reject stale or illegal candidates.
6. Require authoritative packet/state/save evidence before promoting a new
   Mod-backed case from research to `live_verified`.
7. Add a new Semantic Action only when the player intent differs; add a new
   Hook only when static and runtime evidence shows no supported common entry.

Load order affects which definition wins, legal prerequisites, localization
and content fingerprints. Game updates affect code offsets, ABI and signatures.
The former should invalidate candidate/definition caches; the latter must fail
the exact-build runtime profile before any Hook is installed.

## Confidence labels

| Finding | Confidence |
| --- | --- |
| third Observe loaded the declared Mod set and retained zero capture loss | `live_verified` |
| Mod event keys and lifecycle were observed in the live state stream | `live_verified` |
| common RTTI command families remained active | `captured_evidence` |
| live definition lookup can resolve Mod objects in the same engine registry | `static_deduction` pending per-type test |
| GSM policy actions work through OGAS today | `unverified` |
| GSM branch buildings are ordinary build candidates | contradicted by indexed definitions |
| every content Mod needs a separate Hook | false |
| every content Mod works without candidate/parser changes | false |

No production Broker capability or verification state was changed by this
investigation.
