<!-- SPDX-FileCopyrightText: 2026 Imperial Auto Governor contributors -->
<!-- SPDX-License-Identifier: CC-BY-SA-4.0 -->

# Contributing to OGAS

**English | [简体中文](CONTRIBUTING.zh-CN.md)**

Start with the [overview](README.md) and [development guide](docs/DEVELOPMENT.md).
These guidelines accompany `v0.6.0-alpha.1`.
Code, bug reports, independent audits and reverse-engineering research are
welcome. Negative results and corrections are valuable evidence.

## Minimum Evidence

| Contribution | Include |
| --- | --- |
| Bug report | Exact code location/version, reproducible conditions, expected/actual behavior and minimal sanitized evidence |
| Fix or improvement | Scope, rationale, regression tests, relevant build/test output and limitations |
| Independent audit | Audited commit, concrete finding/impact, reproduction or a clearly labeled hypothesis; identify the evidence being challenged |
| Reverse engineering | Exact game/platform/version, ELF Build ID or PE/file fingerprint, source artifacts, tool versions, reproduction and uncertainty |
| Executable action/backend | Typed semantic target, authority/candidate checks, failure cases, native/transport evidence and action-specific confirmation |

Use [issues](https://github.com/V2t-Nostalgia/OGAS/issues) for ordinary bugs and
pull requests for scoped changes. Report vulnerabilities **privately** through
the channel in [SECURITY](SECURITY.md), not in a public issue.

## Architecture Boundaries

- New Applications use semantic actions and the Execution Broker, never packet
  modules, `SessionProxyController` or a Native Runtime client directly. Existing
  migration allowlists are debt to reduce, not examples to copy.
- A new backend implements the same contract. Do not add a second execution
  queue, a parallel Runtime, or a Hook per action.
- Domain candidate generation stays outside the Broker. Models must not invent
  object IDs, wire targets, addresses or native layouts.
- Static recovery, offline construction, native `IsValid`, observed commands,
  execution postconditions and multiplayer synchronization are distinct claims.
  `IsValid=true` or captured RTTI does not promote a production capability.
- Preserve stale-save rejection, permissions, reservations, serialized effects,
  confirmation, no-silent-replay behavior and save continuation. Ordered
  sequences are not rollback transactions.

See [Broker contracts](docs/EXECUTION_BROKER.md),
[native action requirements](docs/runtime/NATIVE_RUNTIME_ACTION_CONTRIBUTING.md)
and the [example](services/stellaris_native_runtime/examples/example_action.cpp.example).
Native modules declare their Application and parameters; unclassified tools
stage under `etc`, without an autonomous agent.

## Verification and Data

Run `python scripts/validation/run_tests.py --quiet`, the same entry point as
CI. Add focused tests and relevant C++/platform checks for native changes.
Report optional parser/cross-language tests as run or skipped. Live testing
requires separate, explicit authorization for a disposable session.

Never commit keys, personal data, private endpoints, configuration secrets,
unreviewed saves/captures, executable artifacts or research output directories.
Do not use `git add -A` to sweep a research worktree into a PR. Large reviewed
evidence belongs in the [separate archive](docs/research/EVIDENCE_ARCHIVE.md),
with SHA-256, path mapping, access status and source/version binding. Preserve
failed, interrupted and superseded runs; redaction must not erase originals.

## Licensing and DCO

Original code is **GPL-3.0-only**; original documentation is **CC-BY-SA-4.0**.
Keep [NOTICE](NOTICE), [origin](ORIGIN.md), SPDX information and third-party MIT
notices. Do not copy mod/game resources without compatible rights.

Every commit requires the [DCO 1.1](DCO) sign-off matching its author identity:

```text
Signed-off-by: Your Name <your-email>
```

`git commit -s` adds the trailer. A cryptographic signature (`git commit -S`)
is **different** and does not replace DCO. Maintainer publication commits and
tags use the configured long-term key; contributors must not create temporary
keys to imitate that identity. Existing contribution rules otherwise remain.
