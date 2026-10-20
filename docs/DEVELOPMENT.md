<!-- SPDX-FileCopyrightText: 2026 Imperial Auto Governor contributors -->
<!-- SPDX-License-Identifier: CC-BY-SA-4.0 -->

# OGAS Development

**English | [简体中文](DEVELOPMENT.zh-CN.md)**

See the [overview](../README.md), [contribution rules](../CONTRIBUTING.md),
[architecture](ARCHITECTURE.md) and [file index](code-map/FILE_INDEX.md).
The source alpha is `v0.6.0-alpha.1`; Python metadata uses `0.6.0a1`.

## Environment and Entry Points

Python 3.11+, Pydantic v2 and the declared platform dependencies are required.
Install from the repository root with `python -m pip install -e .`; use
`python -m pip install -e ".[overlay]"` for the optional Qt UI.
Linux packet support needs `libnetfilter-queue-dev` before pip installation.
Do not alter a working VM/GPU/display configuration to run research tools.

```bash
python -m apps.control_center.web_console --help
python scripts/validation/run_tests.py --quiet
```

Choose the Windows/Linux example configuration in `apps/control_center/`,
make a private copy, and follow the [console guide](../apps/control_center/README.md).
The console requires `--config`; keep it on loopback unless TLS and authentication
are configured. See the [host bridge](../apps/host_bridge/README.md) and
[overlay](../apps/game_overlay/README.md) guides. No binary is published for this alpha.

## Extend the Existing Boundaries

| Work | Location and requirement |
| --- | --- |
| Application | `src/iag/applications/`: explicit registry, private tools/history/model binding and tests |
| Semantic action | `action_registry.py`: stable name/version, strict/frozen target, risk, capabilities and evidence |
| Execution backend | Existing Broker contract: capability/support, one action or locked ordered sequence, normalized machine evidence |
| Native action | Self-registering `actions/*.cpp`, Application/parameter descriptor and reviewed version binding; use `etc` while unclassified |
| Recovery/research | Existing SDK recovery, candidate planner, Builder and CGameIdler research queue; no parallel Runtime |
| Content Pack | Declarative data under `content_packs/`; no executable Python or arbitrary imports |

Applications own economic/tactical/research candidate generation. The Broker
owns the public execution boundary, not domain planning. New code must not
import transport/runtime implementations from Applications. Legacy allowlists
in architecture tests are intentionally frozen. Do not copy those dependencies.

Keep strict snapshot freshness, full object generations, authority, resource
reservation, serialized side effects, request identity, confirmation and save
continuation. A locked sequence is ordered, not atomic or reversible.
See [Broker details](EXECUTION_BROKER.md) and
[native contributions](runtime/NATIVE_RUNTIME_ACTION_CONTRIBUTING.md).

Model providers use the existing OpenAI/Anthropic SDK adapters. Prefer
`request_body_overrides`/`extra_body`; use `raw_http` only for demonstrated SDK
incompatibility. Provider clients do not belong in Applications. Add endpoints
to an existing ModelPool rather than duplicating clients, and never retry an
uncertain non-repeatable request just because a fallback endpoint is healthy.

## Research and Verification

| Evidence | What it establishes |
| --- | --- |
| Static recovery | Layout/function hypotheses tied to exact binary inputs |
| Offline/mock construction | Tooling and memory-layout behavior in the stated test fixture |
| Native `IsValid` | Rule result for the supplied parameters and current world |
| Paired capture | The project's documented paired observation standard, not automatic execution admission |
| Live execution | A submitted action with action-specific authoritative/postcondition evidence on that build |

Do not infer live availability from counts, RTTI, a native true result or a
changed save timestamp. Retain rejected parameters and failed/interrupted runs.
Keep probes separate from production, do not guess pointer ownership, and do
not hot-replace an injected runtime. Live research needs a separately authorized
disposable session; ordinary tests and archive operations never attach to a game.

The current 4.5.2 profile deliberately gates native production execution.
Historical 4.4.6 trials do not override it. Start with
[SDK recovery](../services/stellaris_native_runtime/tools/sdk_recovery/README.md),
[constraint planning](../services/stellaris_native_runtime/tools/script_candidates/README.md)
and [acceptance evidence](runtime/PRODUCER_VALIDATION_ACCEPTANCE_4_5_2.md).

## Tests and Source Checks

CI uses `python scripts/validation/run_tests.py --quiet` on Windows/Linux and
builds the native contract tests. Tests live beside their modules. Keep test
sources in Git, not runtime outputs. SDK tests additionally use:

```bash
python -m pip install -r services/stellaris_native_runtime/tools/sdk_recovery/requirements.txt
cmake -S services/stellaris_native_runtime -B build/native-tests -DIAG_NATIVE_RUNTIME_BUILD_TESTS=ON
cmake --build build/native-tests --config Release
ctest --test-dir build/native-tests -C Release --output-on-failure
```

This is ordinary test compilation, not installer/release packaging. Use a new
output directory; do not erase prior evidence. Optional integration variables:
`IAG_CWTOOLS_BRIDGE`, `IAG_CONSTRAINT_CODEC_TEST_EXE` and
`IAG_CONSTRAINT_PREFLIGHT_REPORT`. Their setup is in the candidate-tool guide;
report omissions rather than claiming skipped tests passed.

Changes to Session Proxy framing/builders/correlation need their original
fixtures and failure tests. Carrier rewrites remain length-preserving unless
an explicitly documented route proves otherwise. Models never author bytes.
See [Session Proxy](SESSION_PROXY_MODE.md) and the historical
[packet study](reference/v0_5_8/PACKET_INTERCEPTOR.md).

## Evidence and Publication

Use the [evidence archive](research/EVIDENCE_ARCHIVE.md), not `.runtime-evidence/`
in Git. Preserve originals, SHA-256, path mapping, source/binary/SDK identity,
tool versions and access decisions. Unknown historical source binding stays
unknown. Do not redistribute game executables, unreviewed saves, credentials,
private data or presentation art without rights.

The [publication procedure](PUBLICATION.md) for this alpha is source, evidence
archive and signed Git tag only. DCO trailers and cryptographic signatures are
separate. Existing `iag` imports, protocol names, executable/configuration paths,
Application versions and carrier Mod versions are not mechanically renamed or
reset to the platform version. Historical migration manifests are immutable.
