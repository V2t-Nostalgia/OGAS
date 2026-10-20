# Nested Native Value Recovery: Stellaris 4.5.2

> Publication: original/local evidence paths below are provenance labels, not Git downloads. Use the [indexed archive and access status](../research/EVIDENCE_ARCHIVE.md); public copies may be privacy-redacted and originals remain retained.


This is offline recovery evidence for Linux Build ID
`121ecb516cbc5f1d39917fbcc36620534384e2c2`. Nothing here establishes native
legality, execution, Windows accessors or production eligibility. The overnight
Runtime/config and installed run-18 consumer headers remain unchanged.

## Address Recovery

`CShipDesignImplementation::CSerializer::WriteMembers` at RVA `0x2af61a0`
uses an 84-byte body. Two references are addressed with this instruction shape:

```asm
mov edx, 0x530
add rdx, qword ptr [wrapper + 0x10]
```

This computes a field address in the referenced object, not a pointer stored at
offset `0x530`. The extractor previously understood the equivalent LEA form,
but not this constant-plus-wrapper-pointer form. It now requires an adjacent
constant MOV, full-width pointer addition, the proven wrapper-member offset,
no index register and a bounded nonnegative constant. Unknown provenance,
32-bit addition, changed wrapper offsets and intervening instructions remain
unsupported. No expression is evaluated against a running process.

The relative object offsets are `design +0x530`, `upgrade +0x534` and
`growth_stage +0x52c`. Typed constructor evidence independently places the
same members. Fourteen previously unresolved serialized reference records gain
offsets across five Commands: add/remove/retrofit fleet-template design,
designable-starbase downgrade and country expansion. These represent twelve
distinct command-relative byte offsets: two country-expansion serializer paths
currently resolve to the same offsets; their semantic relationship remains
unresolved. Do not count duplicate names or aliases as new objects.

## Native Assignment Requirement

Known offsets do not imply that independent raw field writes are valid.
The 72-byte native assignment at RVA `0x2afa440` copies three 32-bit members and
a pointer at `+0x520`, clears a member at `+8`, then invokes
`CBaseDesignImplementation::RecalcSpecialValues` at `0x2af6270` before returning.
The typed constructor at `0x2afa3b0` also invokes that rebuild. The pointed-to
member's type/ownership is not inferred from its width.

The generator recognizes the complete copy/reset/rebuild assignment using
structured operands, agreeing source/destination offsets, nonoverlapping
members, the named rebuild and the complete function boundary. It records
`native_assignment_dependencies` and adds a
`native_derived_state_assignment_required` nested gap for matching wrappers.

All 21 affected serialized field records, covering 18 distinct byte offsets,
carry `native_assignment_required`. They retain recovered type/offset facts
but emit `writable=false`. The existing shared Builder therefore refuses raw
reference/scalar writes even when their offsets are known. Population probing
also remains blocked. No new native assignment adapter is implemented here.

The five Commands remain unvalidated. Growth-stage candidate semantics and
country-expansion alias/overlap constraints are independent remaining gaps.
Design, upgrade and growth stage must not be independently combined from
unrelated candidate pools. A future adapter must establish coupled candidates,
optional-reference/sentinel semantics, native initialization/assignment/destruction
and rebuild requirements before using the existing game-thread validation queue.
Do not guess the fourth pointer or memcpy a composite object.

## Evidence And Tests

Immutable evidence: `.runtime-evidence/sdk-incremental-20261019-01/`
`offline-31-20261019T2236Z/`. It includes complete function bytes/disassembly,
fresh Linux metadata/header, dependency and offset-delta records, final-source
checks, tests and hashes. The comparison uses class, stable field index and
writer evidence RVA; collapsing fields by name would miscount duplicate tokens.

Fresh Linux recovery took 71.991 seconds locally. The four Windows matcher
inputs are unchanged, allowing 18 checks against the retained Windows catalog;
Windows discovery was not rerun. All 500 maintained tests, including 56 SDK
tests, pass. Windows and Linux standalone fake-object Builder fixtures pass,
including refusal of read-only reference and scalar writes. Linux compilation
ran briefly at `nice -n 19`, using 11.16 CPU seconds and about 196 MiB peak RSS;
that is compiler cost, not an online observer-overhead measurement.

Static-ready coverage stays **193 / 351**, with **158** static blockers and no
regression among the previously validated classes. Real coverage stays
**154 native-validated / 87 ever true**. No native command was called, submitted,
captured or promoted by this offline work; no binary was deployed into Stellaris.
