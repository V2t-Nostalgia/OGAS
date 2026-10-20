# Monthly Trade Identity And Candidate Constraints (4.5.2)

> Publication: original/local evidence paths below are provenance labels, not Git downloads. Use the [indexed archive and access status](../research/EVIDENCE_ARCHIVE.md); public copies may be privacy-redacted and originals remain retained.


This is **offline exact-build evidence**, not native legality, capture pairing
or execution verification. The live observer, configuration, Runtime and installed
consumer headers were not changed. No native call was made for this investigation.

Linux ELF Build ID: `121ecb516cbc5f1d39917fbcc36620534384e2c2`.
Complete bytes and annotated disassemblies are retained in
`.runtime-evidence/sdk-incremental-20261019-01/offline-32-20261019T2307Z/`.
Addresses below are ELF-relative RVAs, not runtime absolute addresses.

## Exact Native Evidence

| Function | RVA | Finding |
| --- | --- | --- |
| `SMonthlyTradeData::WriteMembers` | `0x1a6ce70` | Serializes embedded trade data, amount, price and ID separately. |
| `CMarket::AddMonthlyTrade` | `0x1d4df70` | Assigns the old manager counter to the record ID, increments the counter and inserts a copy. This is a **mutator**, not a candidate accessor. |
| `CMarket::GetMonthlyTrades` | `0x1d4dec0` | Iterates existing records, generation-checks their country reference and copies matching-country records to an output array. |
| `CMarket::RemoveMonthlyTrade` | `0x1d4df90` | Searches by the whole record, including country, resource, type, amount, price and ID; a valid ID alone does not establish equality. |
| `CMarket::UpdateMonthlyTrade` | `0x1d4e1e0` | Searches by ID, verifies the country relationship and writes resource, type, amount and price. |
| `CMonthlyTradeView::Reset` | `0x2f99500` | Resets the GUI ID to `-1`; GUI existing-trade checks use the ID's sign. This is not permission to use arbitrary IDs in existing-trade requests. |
| `CMonthlyTradeView::InitPrice` | `0x2f99770` | Sets price to zero after a native resource validity guard. |
| `CMonthlyTradeView::GetCurrentTradeData` | `0x2f99430` | Assembles the resource, type, observed country, amount, price and ID into one record. |
| `CMonthlyTradeView::AddTrade` | `0x2f96fe0` | Chooses Add versus Update from the GUI ID sign, constructs and validates the corresponding command, then submits a separate heap copy. Not called in this research. |
| `CMonthlyTradeView::CancelTrade` | `0x2f96e60` | Builds Remove from the GUI's existing trade data. Not called in this research. |
| `CAddMonthlyTradeCommand` constructor | `0x4328730` | Copies the coupled record payload into command offsets `0x30..0x4b`; embedded identities come from native construction. |
| `CAddMonthlyTradeCommand::IsValid` | `0x43287f0` | Includes resource/country/economy checks and a positive-amount condition; resource-dependent quantity rules remain. |
| `CRemoveMonthlyTradeCommand::IsValid` | `0x4329230` | Complete three-byte function returns true without checking the record. |
| `CUpdateMonthlyTradeCommand::IsValid` | `0x4329350` | Gets existing trades for the command country and tests ID membership; it is not a comprehensive amount/price/resource validator. |
| `CMarket::CanPerformMonthlyTrade` | `0x1d4d810` | Evaluates amount and per-unit price limits for buy/sell branches before their native resource checks. Separate from command IsValid. |

## Coupled Layout

The serialized `SMonthlyTradeData` record is 48 bytes in the observed array.
The Command embeds it at `0x20`; the native constructor supplies both vptrs.

| Field | Record offset | Command offset | Representation |
| --- | --- | --- | --- |
| Resource | `0x10` | `0x30` | `CStrategicResource` definition pointer, serialized by key; not inline text. |
| Trade type | `0x18` | `0x38` | `EMarketTradeType`, serialized integer/token mapping. |
| Country | `0x1c` | `0x3c` | Generation-bearing `TPdxRef<CCountry>`. |
| Amount | `0x20` | `0x40` | Signed integer quantity. Native price computation converts it to fixed point with scale 100,000. |
| Price | `0x24` | `0x44` | Signed integer per-unit threshold used with amount. Zero has special unbounded-buy behavior in `CanPerformMonthlyTrade`. |
| ID | `0x28` | `0x48` | Manager-counter-assigned order identity, **not a resource index or global TPdxRef**. |

The manager embeds its array at `0x48`; the observed data pointer is at `0x50`,
count at `0x5c`, record stride `0x30` and next-ID counter at `0x60`. This does not
prove a safe external snapshot or pointer lifetime. No manager array was read
from the running process for this investigation.

## Generator Change

`native_counter_record_identity()` recognizes the complete eight-instruction
SysV counter/store/array-insert shape. It requires the same counter source and
destination, one increment, a 32-bit record store, unchanged argument forwarding,
the typed native `CPdxArray<Record, int>` insertion target, matching array/count
offsets, bounds/alignment and the full function extent. It does not rely on a
specific command name or hard-code this manager's offsets.

The enrichment pass joins the proven record member to its serializer field,
then to every expanded command field by its original writer instruction.
It emits `native_counter_record_identities` and field-level provenance. The
record explicitly has `research_callable=false` and lists its writes. It is
**not** a getter descriptor, candidate value, production action or executable
adapter. The audit retains this provenance without relaxing any blocker.

The three monthly-trade commands receive the identity evidence. Their executable
generated header remains byte-identical to offline-31. Existing amount, price
and identity candidate blockers are deliberately retained.

## Remaining Work And Validation Boundary

For Remove and Update, recover a bounded provider for an **entire existing
same-country record**, resolving its resource against the effective definition
database. Do not combine independently chosen resource/type/amount/price/ID
candidates. An unchanged Update candidate can test construction without promising
that changed values would be accepted by later gameplay rules.

For Add, the record ID is overwritten at insertion, but this does not justify
inventing quantity candidates. Recover the resource-dependent initial amount
and its effective defines or obtain an exact-version naturally captured candidate.
Factory/GUI reset values of `-1` are initialization evidence, not legal order
parameters. Preserve the native typed record lifetime and normal Builder path.

The next appropriate new-binary window can test these providers through
Factory -> Populate -> IsValid -> Destroy only. The currently loaded binary is
not replaced, and no missing scene is manufactured. Even a Remove IsValid true
would only confirm that its trivial validator returned true, not that any order
exists, could be removed or was executed. Paired capture and postcondition
requirements remain independent and unchanged.

## Bounded Record Hints (Offline-33)

`record_candidates.py` now recovers the complete 176-byte native
`GetMonthlyTrades` filter/copy loop, including its branches, country slot and
generation guards, named country DB/null globals, record stride and typed
array-insertion target. It cross-checks the separate counter/insertion evidence
before accepting a source. Matching names or serializer offsets alone do not
suffice. The native filter allocates an output array; it is **not called** by
the hint reader and is not treated as a no-ownership native getter.

The SDK generator emits one `native_country_record_sources` record and attaches
its provenance to the same three Commands. These annotations provide no scalar
candidate, population adapter or executable function dispatch. The generated
C++ header is byte-identical to offline-32, and all three existing population
blockers remain. No active consumer header, library or observer configuration
was replaced.

The same module supplies `discover_country_records()` for an explicitly supplied,
already identified owner pointer and bounded read callback. It reuses the existing
read budget, reads at most 512 records and 4,096 definition pointers, and returns
at most sixteen correlated tuples. It checks the actor's full country generation,
loaded definition membership, serialized field types/widths/ranges, overlaps and
duplicate same-country identities. A duplicate ID also invalidates a candidate
when its other row contains an unknown resource pointer. Unknown definition
pointers are never dereferenced. Changed reread bytes discard the hints.

The result explicitly retains important limits: double reads do not freeze the
world, uniqueness applies only to the bounded scan, definition indices are not
semantic IDs or resolved keys, and a copied signed quantity is not automatically
legal. Native IsValid is absent, no function is invoked and nothing is submitted.
The reader has **not** been attached to the running game or observer. It is a
tested preparation for a future game-thread provider, not that provider itself.

The exact eight-byte `CGameState::GetMarket` body is also retained: it loads a
pointer from `this + 0xad8` and returns. It was not called. Owner acquisition and
lifetime still belong to the future game-thread integration, not an arbitrary
external pointer inferred from a name.

Thirteen new fixture tests pass on both Windows and Ubuntu, including changed
memory, duplicate IDs, unknown definition pointers, generation mismatch, signed
counts, unsupported layouts and truncated scans. The isolated Ubuntu test used
0.22 CPU seconds and 16,800 KiB peak RSS; this is test-runner cost, **not** a live
monitoring overhead benchmark. The complete maintained suite has 517 passing
tests, including 73 SDK tests. Fresh exact-build recovery and 18 retained-Windows
cross-checks pass; Windows discovery was not rerun. Full native bytes, generated
metadata, original and corrected lint logs, fixture logs and final-source proof
are retained in `offline-33-20261019T2337Z/`.
