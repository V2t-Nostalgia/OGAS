# Technical Comparison: `Yidhar/stellaris-mcp`

> Publication: original/local evidence paths below are provenance labels, not Git downloads. Use the [indexed archive and access status](../research/EVIDENCE_ARCHIVE.md); public copies may be privacy-redacted and originals remain retained.


## Scope and pinned revision

This review compares the current OGAS execution stack with
[`Yidhar/stellaris-mcp`](https://github.com/Yidhar/stellaris-mcp) at commit
[`6cc8e82013f88d7ef51d906f3cdfa44054b7a250`](https://github.com/Yidhar/stellaris-mcp/tree/6cc8e82013f88d7ef51d906f3cdfa44054b7a250),
dated 2026-10-06. The external checkout was used read-only.

The principal conclusion is that the external project has one major
capability OGAS should adopt: a serializer-driven, cross-platform engine SDK
generator. It turns the symbolized Linux build into semantic anchors and then
rediscovers Windows command vtables, factories, allocation sizes, serialized
field offsets, database globals, and selected engine functions for each exact
Windows build.

That generator explains much of the project's implementation speed. It does
not replace OGAS's authority, idempotency, snapshot, semantic-contract, or
postcondition verification requirements.

## Architecture comparison

| Concern | `stellaris-mcp` | OGAS |
| --- | --- | --- |
| Public caller | Direct MCP tools | Applications call semantic actions through the Execution Broker |
| Native bridge | Windows DLL injected in `stellaris.exe` | Versioned Linux/Windows native runtime backends behind one Broker contract |
| Thread marshal | Named-pipe worker queues work; a DXGI `Present` hook drains all tasks | Runtime-specific scheduling with a single serialized side-effect lane |
| Command construction | Generated `CmdSpec` plus generic `CommandBuilder` | Typed, self-registered action implementations, many derived from capture evidence |
| Native validation | Calls command virtual `IsValid` and other engine predicates | Action-specific `Prepare`, native validation where known, and `Verify` |
| Candidate discovery | Reads live engine databases and frequently asks native predicates whether a candidate is legal | Save/world-state candidate generation plus native resolvers for implemented actions |
| Completion meaning | Usually returns success immediately after `PostCommand` returns | Normalized result distinguishes packet/save confirmation, provisional state, rejection, and failure |
| Freshness and authority | Mostly checks the current player and current in-memory objects inside each manager | Broker-bound application, authority context, source snapshot, candidate identity, permissions, and staleness checks |
| Retry safety | No request-id deduplication or persistent idempotency contract was found | Request correlation, one active side effect, conflict handling, and explicit idempotency semantics |
| Extension surface | Manager method, IPC `if/else`, and TypeScript MCP registration are edited manually | C++ actions self-register descriptors; the runtime manifest is overlaid with the semantic registry |
| Version gate | Exact Windows PE timestamp plus a command token/vtable check | Exact build profiles plus instruction/signature and runtime compatibility checks |

The external project's path is effectively:

```text
MCP tool
  -> hard-coded JSON-RPC method
  -> named-pipe IPC
  -> Present-hook main-thread queue
  -> domain manager
  -> generated CmdSpec + CommandBuilder
  -> command IsValid
  -> native PostCommand
```

The OGAS path is:

```text
Application
  -> semantic ActionSpec / typed target
  -> Execution Broker safety gates
  -> selected backend
  -> self-described native action
  -> version-bound object resolution / native command
  -> native submit
  -> runtime and save-backed verification
```

## Why its tool surface grew quickly

### 1. Serializer-driven SDK generation

The decisive component is
[`tools/sdk_dumper`](https://github.com/Yidhar/stellaris-mcp/tree/6cc8e82013f88d7ef51d906f3cdfa44054b7a250/tools/sdk_dumper).
Its documented pipeline uses `WriteMembers` and `WriteCommandMembers` as an
imperfect reflection system. Ordered serializer tokens identify fields and
provide cross-platform fingerprints. The pipeline then finds the corresponding
Windows functions and layouts and emits `stellaris_sdk.hpp`.

At the pinned revision, the generated header contains 366 `CmdSpec` records.
The dumper documentation reports 809/980 matched serializers, 3143/3442
resolved serialized fields, and 367 commands with factory/size information for
4.5.2. It also states that a complete run takes about 1.5 minutes and fails if
its hand-verified layout regression no longer reproduces.

This changes a new command from a wholly manual reverse-engineering task into
roughly:

1. select a generated command spec;
2. resolve semantic IDs or definition pointers;
3. write typed fields at generated offsets;
4. call the engine's `IsValid`;
5. submit through the common native `PostCommand` entry.

### 2. One generic command constructor

[`CommandBuilder`](https://github.com/Yidhar/stellaris-mcp/blob/6cc8e82013f88d7ef51d906f3cdfa44054b7a250/stellaris_bridge/src/command_builder.cpp)
centralizes engine allocation, factory calls, vtable/token checks, bounded field
writes, engine string ownership, virtual `IsValid`, destruction, and ownership
transfer to `PostCommand`. Commands without a factory can be allocated and
given the generated vtable and common command header.

Consequently, a typical action implementation is small. For example, fleet
movement resolves the owned fleet and target system, fills a generated
`CSendFleetToLocationCommand` layout, asks `IsValid`, and posts it.

### 3. The engine supplies legal candidates

The bridge reads the currently loaded databases and calls native predicates,
including command `IsValid`, to filter technologies, civics, construction
choices, fleet orders, and other candidates. This is especially useful for
mods because current in-memory definitions and current scripted rules are the
source of truth.

OGAS currently spends more time reconstructing candidate legality from saves
and then proving each reconstructed command by an active experiment. A safe
non-posting `Create -> populate -> IsValid -> destroy` path would eliminate a
large fraction of failed experiments and manual UI discovery.

### 4. Live memory avoids save-round-trip costs

Most read tools inspect the active game directly rather than waiting for and
parsing another save. This gives the MCP layer cheap, narrow state queries and
makes progressive disclosure practical. It does not provide OGAS's immutable
same-snapshot guarantee, but it is an important latency advantage for
interactive candidate discovery.

### 5. The public tool count uses a lighter acceptance definition

The README still advertises 29 tools, while the pinned `tools.ts` contains 104
named `server.tool` registrations. A simple name-based classification finds
about 41 query-like tools, 5 UI/session controls, and 58 mutation-like tools.
This is useful breadth, but it is not 104 independently save-verified command
pipelines.

Most mutation methods report success once the command is accepted for posting.
They often advise the caller to read state again later. No request-id
idempotency, source-save revision, authoritative confirmation, or durable
postcondition verifier was found. Therefore its "available" threshold is much
closer to "the exact build accepted this native call" than OGAS's
`live_verified` threshold.

The public history also starts with a 26,659-line initial import, and the SDK
migration commit adds about 55,930 lines, much of it generated. The commit
dates alone cannot establish how long the underlying reverse engineering took.

## Important limitations not to copy

1. **Posting is not completion.** A successful `PostCommand` call is returned
   as success without a correlated postcondition or later-save continuation.
2. **No replay contract.** A timed-out caller can resubmit the same mutation;
   no request-id deduplication layer was found.
3. **Transport and tool schema are duplicated.** A new MCP feature generally
   requires a manager method, another IPC dispatch branch, and another
   TypeScript registration. The native command SDK is generated, but the
   application-facing surface is not.
4. **Compatibility checking is comparatively shallow.** The primary build
   gate is the PE timestamp, supplemented by the selected command's token
   getter. OGAS's per-profile signature checks should remain.
5. **Generated addresses do not eliminate semantic offsets.** The managers
   still contain many manual object-layout constants, manually constructed
   helper objects, and some content-specific maps such as building upgrades.
6. **Authority is player-centric.** Actions generally obtain the current
   player country. That is simpler than OGAS's observer and arbitrary-country
   authority requirements for AI tournaments.
7. **Tests are not a production gate.** The release workflow builds C++ and
   TypeScript packages, but it does not run a C++ test suite, Python tests, or
   TypeScript tests. The MCP package itself defines build/start scripts only.
8. **The render hook is a practical marshal, not a proven simulation-thread
   contract.** Work is drained from DXGI `Present`; minimized, throttled, or
   headless behavior needs explicit verification before adopting that method.

## What OGAS was missing

The missing piece is not another packet capture or a larger MCP file. It is an
automated discovery layer below the existing native action registry:

```text
symbolized Linux build + exact Windows/Linux binary
  -> serializer/token index
  -> generated raw engine SDK and structural fingerprints
  -> reviewed semantic mapping
  -> typed OGAS native action descriptor
```

Two parts have immediate value:

- **Generated command layouts and version profiles.** This can replace much of
  the repeated per-command vtable/factory/field-offset work and make game
  version ports primarily a generator/regression task.
- **Native validation as a read-only research API.** Candidate enumeration can
  construct a command, call `IsValid`, capture the game's rejection reason,
  and destroy it without posting. This should substantially accelerate both
  semantic mapping and negative-case coverage.

OGAS already has the stronger upper boundary: self-registering action files,
manifest parameters and application ownership, an `etc` staging area, dynamic
Broker overlay, and explicit verification states. The external project's
generated SDK should sit underneath that boundary rather than replace it.

## Recommended adoption sequence

1. **Import no production action yet.** Build a research-only SDK generator
   against pinned 4.4.6 Linux/Windows artifacts and compare its output with the
   command layouts already proven by OGAS captures.
2. **Generate raw evidence, not public tools.** Emit versioned command token,
   vtable fingerprint, factory, size, serialized field offsets, field
   confidence, and source fingerprints. Keep ambiguous fields marked as such.
3. **Add a non-posting native validator.** Permit reviewed command specs to be
   populated and run through `IsValid` on the correct game thread, returning a
   typed result and reason without transferring ownership.
4. **Generate action scaffolds.** From a small reviewed semantic mapping file,
   generate a C++ action skeleton and manifest parameter descriptors. A human
   must still name semantic IDs, authority, risk, verifier, and owning
   application.
5. **Use an evidence ladder.** Track at least `layout_generated`,
   `native_is_valid`, `post_observed`, `state_verified`, `save_verified`, and
   `broker_enabled`. These are evidence dimensions, not synonyms for one
   another.
6. **Batch live validation.** Let Computer Use select legal candidates from the
   validator, submit bounded independent cases, and let one verifier correlate
   runtime evidence and multiple subsequent saves. Irreversible actions still
   require dedicated authorization and negative tests.
7. **Retain all Broker gates.** Application permission, authority, source
   snapshot, reservation, side-effect serialization, request-id idempotency,
   normalized results, and postcondition evidence must remain unchanged.

## Expected effect

This approach should greatly reduce time spent rediscovering native layouts,
finding legal test candidates, and porting actions between exact game builds.
It will not make semantic or destructive-action verification unnecessary.

The practical target is not to match an MCP tool count. It is to make the path
from a captured or symbolized command to an OGAS staged action mostly
automatic, while keeping promotion to `live_verified` evidence-based.
