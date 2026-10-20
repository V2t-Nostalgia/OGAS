<!-- SPDX-FileCopyrightText: 2026 Imperial Auto Governor contributors -->
<!-- SPDX-License-Identifier: CC-BY-SA-4.0 -->

## Change / 变更

Scope, motivation, affected layers; link the issue or audited commit.
范围、原因、影响层级；关联 issue 或被审计 commit。

## Evidence / 证据

Game/platform/build fingerprint where relevant; reproducible steps; archive
entry + SHA-256; limitations. Distinguish static, mock, native IsValid, paired
capture and live execution. Include failures, not only successful samples.
如涉及游戏，请注明平台/精确构建指纹、复现步骤、归档条目与 SHA-256、限制；
区分静态、Mock、原生 IsValid、配对捕获与实机执行，并保留失败样本。

## Checks / 检查

- [ ] `python scripts/validation/run_tests.py --quiet`; relevant C++/platform tests and optional skips reported / 已运行统一测试，说明相关 C++/平台测试及跳过项
- [ ] New code respects Broker/semantic boundaries, authority, confirmation and no-silent-replay rules / 新代码遵守 Broker、语义、权限、确认及防静默重放边界
- [ ] Native tools declare Application/typed parameters; unclassified tools stage in `etc`; no evidence-level promotion by inference / 原生工具自述归属与参数，未归类进入 `etc`，不凭推断晋级
- [ ] No credentials, private data, unreviewed game assets/saves/captures or generated binaries; large evidence uses the archive / 无凭据、隐私、未经审查游戏资料或二进制，大数据走归档
- [ ] Licenses/attribution preserved; every commit has DCO `Signed-off-by` (not replaced by a cryptographic signature) / 保留许可归属，每个提交含 DCO 签署，不能用加密签名替代
