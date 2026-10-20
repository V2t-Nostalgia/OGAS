<!-- SPDX-FileCopyrightText: 2026 Imperial Auto Governor contributors -->
<!-- SPDX-License-Identifier: CC-BY-SA-4.0 -->

# OGAS 源码与证据发布

本流程适用于 `v0.6.0-alpha.1`，Python 包版本为 `0.6.0a1`。
它只发布源码、独立研究证据和签名 Git Tag，**不执行 Release 打包脚本、不构建正式
安装包、不分发可执行二进制，也不创建 GitHub Release 或 Draft Release**。
普通编译、单元测试和 CI 仍需执行。旧版流程保留在
[v0.5.10 历史](https://github.com/V2t-Nostalgia/OGAS/blob/v0.5.10/docs/PUBLICATION.md)。

## 顺序与边界

1. 核对 `main`、`v0.5.10` 基线、实际改动和未提交研究；禁止 reset/clean 或覆盖原始资料。
2. 当前品牌使用 OGAS；保留历史名称、真实作者、许可和稳定内部标识。
   Application/Mod/协议版本与项目版本分别管理，不机械统一。
3. 先将 `.runtime-evidence/`、`.publication/` 和缓存/构建产物隔离于源码 Git。
   逐项审查源码与证据中的凭据、隐私、第三方版权，不使用 `git add -A`。
4. 完整清点本地/远端研究资料，包括失败、中断、旧 checkpoint 与修正前结果。
   内容寻址压缩存储保留 SHA-256 和路径映射；受限原件保留本地或服务器，不伪称公开。
5. 完成三组双语文档、元数据、贡献入口、Native Runtime 说明及代码地图，核对实际
   拟提交集合中的相对链接。未跟踪/被忽略文件的存在不能证明发布链接有效。
6. 执行 Python/C++/静态检查。可选集成测试必须区分已运行和跳过。
   所有验证使用新输出目录；不注入、不操作当前游戏、不热替换 Runtime。
7. 将可公开源码整理为带 DCO 与现有长期密钥签名的提交。归档绑定这一可获取的
   源码 checkpoint；历史 batch 的源码关系只按原有证据记录，缺失时标未知。
8. 通过独立证据仓库发布经审查的原件和标明的脱敏副本；保存全清单、访问状态、
   原始/公开 SHA-256、游戏/SDK 身份及工具版本。为索引签名，不使用不存在的 Release Assets。
9. 重新从远端获取公开归档，逐对象解压核对 SHA-256，检查原始记录可用性。
   将实际 archive commit、source checkpoint 和验证结果写入
   [发布凭据](research/EVIDENCE_PUBLICATION.json)。
10. 提交最终链接/归档凭据，签名 Tag 并推送 `main` 与 Tag。检查远端对象和签名，
    不能把本地签名、本地文件或尚未上传的目录当作已发布成功。

## 签名与 DCO

```bash
git commit -S -s -m "Prepare OGAS v0.6.0-alpha.1 source and research checkpoint"
# 归档已上传并核验后，提交最终 publication receipt
git commit -S -s -m "Record verified OGAS alpha evidence publication"
git tag -s v0.6.0-alpha.1 -m "OGAS v0.6.0-alpha.1: source and research evidence"
git push origin main
git push origin v0.6.0-alpha.1
git verify-commit HEAD
git verify-tag v0.6.0-alpha.1
git ls-remote origin refs/heads/main refs/tags/v0.6.0-alpha.1 'refs/tags/v0.6.0-alpha.1^{}'
```

`-s` 是 DCO trailer，`-S` 是加密签名，两者不能替代。Tag 也需单独加密签名。
只使用已配置的长期密钥；不得创建临时密钥冒充维护者。公开密钥可从维护者已注册的
[GitHub GPG keys](https://github.com/V2t-Nostalgia.gpg) 获取，核对签名指纹和 GitHub 验证状态。

## 独立审计

从[证据访问指南](research/EVIDENCE_ARCHIVE.md)进入数据，而不是只读汇总。
区分 raw observation、自动推断、人工解释、Native IsValid、实际执行与多人同步。
本轮不会自动提升生产 action 的验证等级。游戏二进制/存档、敏感状态及未获准分发的
外部资源不能因“归档完整”而直接公开；受限项目的缺口与获取条件必须明确列出。

仓库正式地址：[V2t-Nostalgia/OGAS](https://github.com/V2t-Nostalgia/OGAS)。
本流程不登记 DOI、不声称新的二进制已发布，也不追溯性改写旧版验收记录。
