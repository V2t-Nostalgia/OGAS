<!-- SPDX-FileCopyrightText: 2026 Imperial Auto Governor contributors -->
<!-- SPDX-License-Identifier: CC-BY-SA-4.0 -->

# 参与 OGAS

本指南对应 `v0.6.0-alpha.1`。

**[English](CONTRIBUTING.md) | 简体中文**

请先阅读[首页](README.zh-CN.md)和[开发指南](docs/DEVELOPMENT.zh-CN.md)。欢迎代码、
缺陷报告、独立审计和逆向研究；阴性结果与结论修正同样是有价值的证据。

## 最低证据要求

| 贡献类型 | 需要提供 |
| --- | --- |
| Bug Report | 精确代码位置/版本、复现条件、预期与实际行为、最小脱敏证据 |
| 修复或改进 | 范围与理由、回归测试、相关构建/测试输出及限制 |
| 独立审计 | 被审计 commit、具体问题/影响、复现或明确标注的假设，以及受到质疑的证据 |
| 逆向研究 | 精确游戏/平台/版本、ELF Build ID 或 PE/文件指纹、来源资料、工具版本、复现步骤与不确定项 |
| 执行动作/backend | 类型化语义 target、权限/候选校验、失败场景、原生/传输证据及动作专属确认 |

普通问题走 [issues](https://github.com/V2t-Nostalgia/OGAS/issues)，范围明确的修改走 PR。
安全漏洞请按 [SECURITY](SECURITY.md) 的渠道**私密报告**，不要公开利用细节。

## 架构边界

- 新 Application 只使用语义动作和 Execution Broker，不直接依赖 packet 模块、
  `SessionProxyController` 或 Native Runtime client。既有迁移 allowlist 是待减少的债务，不能照搬。
- 新 backend 实现同一契约，不建立第二套执行队列、平行 Runtime 或逐动作新增 Hook。
- 领域候选生成留在 Broker 外。模型不得编造对象 ID、wire target、地址或原生布局。
- 静态恢复、离线构造、原生 `IsValid`、命令观测、执行后置条件及多人同步是不同结论。
  `IsValid=true` 或捕获到 RTTI 都不能直接提升生产能力等级。
- 保留 stale-save 拒绝、权限、资源预留、副作用串行化、确认、防静默重放与存档续接。
  有序序列不是能够回滚的事务。

详见 [Broker 契约](docs/EXECUTION_BROKER.md)、
[原生动作要求](docs/runtime/NATIVE_RUNTIME_ACTION_CONTRIBUTING.md)和
[动作样例](services/stellaris_native_runtime/examples/example_action.cpp.example)。
Native 模块必须自述所属 Application 与参数；未归类能力进入 `etc`，不运行自主 Agent。

## 验证与数据

运行与 CI 相同的 `python scripts/validation/run_tests.py --quiet`。添加针对性回归，
原生修改还应运行相关 C++/平台检查。可选解析器和跨语言测试必须注明实际运行还是跳过。
实机测试需要另行取得可丢弃会话的明确授权。

禁止提交密钥、个人数据、私人端点、配置秘密、未经审查的存档/抓包、可执行产物或
研究输出目录。不要用 `git add -A` 把研究工作区整体塞进 PR。大体积已审查证据走
[独立归档](docs/research/EVIDENCE_ARCHIVE.md)，保留 SHA-256、路径映射、访问状态及源码/版本绑定。
失败、中断和被替代的实验也要保留；脱敏不得抹掉原件。

## 许可与 DCO

原创代码采用 **GPL-3.0-only**，原创文档采用 **CC-BY-SA-4.0**。保留
[NOTICE](NOTICE)、[项目起源](ORIGIN.md)、SPDX 信息及第三方 MIT 声明。
没有兼容分发权利时，不得复制 Mod 或游戏资源。

每个提交必须包含与作者身份一致的 [DCO 1.1](DCO) 签署行：

```text
Signed-off-by: Your Name <your-email>
```

`git commit -s` 添加该 trailer。加密签名 `git commit -S` 是**另一件事**，不能替代 DCO。
维护者发布提交和 Tag 使用已配置的长期密钥；贡献者不得创建临时密钥冒用该身份。
其他既有贡献规则不变。
