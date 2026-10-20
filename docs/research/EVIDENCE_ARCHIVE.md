<!-- SPDX-FileCopyrightText: 2026 Nostalgia and Imperial Auto Governor contributors -->
<!-- SPDX-License-Identifier: CC-BY-SA-4.0 -->

# OGAS Research Evidence

The source repository and the research data have different publication boundaries.
Large generated files do not belong in the source Git history. This publication
uses the independent [OGAS research-evidence repository](https://github.com/V2t-Nostalgia/OGAS-research-evidence).
The exact deployed revision, checksums and download verification are recorded in
[EVIDENCE_PUBLICATION.json](EVIDENCE_PUBLICATION.json), completed before the alpha tag.

## What the Index Means

`index.jsonl` maps every inventoried path to its original SHA-256, byte count,
snapshot stability, access decision, public SHA-256 and content-addressed gzip
object when available. `entry` points to a small, browsable per-file record.
The full original-path mapping and restricted local objects are retained by the
maintainer, not put in the source repository. Remote retained originals have
an explicit location/access status; they are not disguised as downloadable files.

| Access | Meaning |
| --- | --- |
| `public_original` | Exact original bytes are available; original and public SHA-256 match |
| `public_redacted_derivative_original_retained` | A labeled privacy-neutralized derivative is available; original hash and restricted original are retained |
| Restricted / not cleared / unreviewed | The index is public, the bytes are not. No public-original download is claimed |

All passes are inventoried, including failures, interrupted work, old checkpoints,
rejected candidates and intermediate corrections. Content-addressed storage
deduplicates bytes, not experimental paths. A snapshot of a changing file is
marked unstable; it must not be treated as an immutable completed experiment.

Originals are never edited by the export tool. Redaction removes private machine
paths/endpoints and project-specific external workspace identifiers from public
copies, not addresses/offsets needed for analysis. Possible credentials,
game executables, full saves/databases, screenshots and uncleared external
source/artwork are withheld rather than guessed safe. The export policy and
manual review are publication decisions, not proof of ownership or legal advice.

Exports require a new output directory. The restricted `snapshot-journal.jsonl`
records progress if publication is interrupted. `build --reuse-from OLD_EXPORT`
can reuse prior CAS objects only after checking their uncompressed hashes;
it still reviews current inputs and never overwrites the prior export.
`review --export EXPORT/public --output NEW_PUBLIC_TREE --deny-path REGEX`
creates a separate reviewed tree and a decision ledger. Identical-content aliases
are withheld together; denied objects are not copied into the publishable tree.
The pre-review export and restricted originals remain intact.

## Retrieve Actual Data

```bash
git clone https://github.com/V2t-Nostalgia/OGAS-research-evidence.git ../OGAS-research-evidence
python scripts/research/archive_evidence.py verify \
  --index ../OGAS-research-evidence/index.jsonl \
  --objects ../OGAS-research-evidence/objects
python scripts/research/archive_evidence.py restore \
  --index ../OGAS-research-evidence/index.jsonl \
  --objects ../OGAS-research-evidence/objects --output NEW_RESTORED_DIRECTORY
```

Run these commands from the OGAS source checkout; choose a new restore directory.
The restore operation verifies each object's uncompressed SHA-256. For a rotated
capture already compressed in the original experiment, restoring the object
recovers that original gzip file; decompress that file to inspect its records.
A public derivative does not reconstruct the private original. Read access
status before claiming original-byte reproduction.

Use the source Git commit, exact game version, ELF Build ID/PE identity, SDK
fingerprint, input hashes and tool versions in the receipts and artifacts.
`reported_context` preserves where a value appeared; it is not independent
verification of that value. Missing historical provenance is **unknown**. The
current source/archive association identifies the publication snapshot, not
the code that necessarily generated every historical experiment.

## Research Levels

Raw observations, aggregated machine reports and human interpretations must
remain distinguishable. Function/RTTI discovery is not construction; a mock
construction is not a game call; native IsValid is not execution; a save's
timestamp is not causal pairing; a local execution trial is not multiplayer
synchronization proof. Existing verification gates remain authoritative.

Useful entry documents:

- [Long Observe](../runtime/LONG_RUNNING_AI_COMMAND_CAPTURE_4_4_6.md), [events/situations](../runtime/EVENT_SITUATION_DISCOVERY_4_4_6.md), [performance/mods](../runtime/OBSERVE_PERFORMANCE_MOD_ANALYSIS.md)
- [SDK recovery](../runtime/SDK_RECOVERY_4_5_2.md), [expanded batches](../runtime/SDK_COMMAND_RECOVERY_EXPANSION_4_5_2.md), [incremental research](../runtime/SDK_INCREMENTAL_VALIDATION_4_5_2.md)
- [Producer acceptance](../runtime/PRODUCER_VALIDATION_ACCEPTANCE_4_5_2.md), [constraint pipeline](../runtime/SCRIPT_NATIVE_CONSTRAINT_PIPELINE_4_5_2.md), [semantic audit](../runtime/COMMAND_SEMANTIC_TECHNICAL_AUDIT_4_5_2.md)
- [Coordinates/codec](../runtime/COORDINATE_VALUE_REUSE_4_5_2.md) and [native catalog](../runtime/NATIVE_RUNTIME_ACTION_CATALOG_4_4_6.md)

## Restricted Access and Remaining Gaps

Ask the maintainer through a normal issue for a non-sensitive research-access
discussion; use [private security reporting](../../SECURITY.md) for sensitive
findings, never publish credentials or private originals in an issue. Access
depends on privacy/redistribution review and is not promised for proprietary
inputs. Obtain matching game binaries through your own lawful installation.

The index records what was present at export time. It cannot recreate inputs
already absent before this publication, repair historical missing provenance,
or remove material from earlier public Git history. Old migration manifests,
checkpoints and raw data remain unchanged. Current artwork exclusions do not
claim that the earlier history has been purged.
