<!-- SPDX-FileCopyrightText: 2026 Imperial Auto Governor contributors -->
<!-- SPDX-License-Identifier: CC-BY-SA-4.0 -->

# OGAS 开发指南

**[English](DEVELOPMENT.md) | 简体中文**

入口：[首页](../README.zh-CN.md)、[贡献规则](../CONTRIBUTING.zh-CN.md)、
[架构](ARCHITECTURE.md)、[文件索引](code-map/FILE_INDEX.md)。
源码 alpha 为 `v0.6.0-alpha.1`，Python 元数据使用 `0.6.0a1`。

## 环境与入口

需要 Python 3.11+、Pydantic v2 及已声明的平台依赖。在仓库根目录执行
`python -m pip install -e .`；可选 Qt 界面使用 `python -m pip install -e ".[overlay]"`。
Linux 抓包支持需要先安装 `libnetfilter-queue-dev`。不要为了运行研究工具修改
已正常工作的 VM、GPU 或显示配置。

```bash
python -m apps.control_center.web_console --help
python scripts/validation/run_tests.py --quiet
```

选择 `apps/control_center/` 中对应 Windows/Linux 的示例配置，制作私人副本，
再按[控制台说明](../apps/control_center/README.md)操作。控制台必须传 `--config`；
没有配置 TLS 与认证时只监听回环地址。另见[房主桥](../apps/host_bridge/README.md)
与[叠加层](../apps/game_overlay/README.md)。本 alpha 不发布二进制。

## 扩展现有边界

| 工作 | 位置与要求 |
| --- | --- |
| Application | `src/iag/applications/`：显式注册，独立工具/历史/模型绑定及测试 |
| 语义动作 | `action_registry.py`：稳定名称/版本、strict/frozen target、风险、能力和证据 |
| 执行 backend | 现有 Broker 契约：能力/support、单动作或锁定有序序列、规范化机器证据 |
| 原生动作 | 自注册 `actions/*.cpp`、Application/参数描述及审查过的版本绑定；未归类时进入 `etc` |
| 恢复/研究 | 现有 SDK Recovery、候选规划器、Builder 和 CGameIdler 研究队列；不建平行 Runtime |
| Content Pack | `content_packs/` 下的声明数据；不包含可执行 Python 或任意导入 |

Application 负责经济、战术和科研候选。Broker 负责公共执行边界，不负责领域规划。
新 Application 不得导入 transport/runtime 实现；架构测试中的旧依赖 allowlist
有意冻结，不得照搬。

保留严格快照新鲜度、完整对象 generation、权限、资源预留、副作用串行化、请求
身份、确认与存档续接。锁定序列只保证顺序，不保证原子性或回滚。
详见 [Broker](EXECUTION_BROKER.md)和[原生贡献](runtime/NATIVE_RUNTIME_ACTION_CONTRIBUTING.md)。

模型供应商使用现有 OpenAI/Anthropic SDK 适配器。优先使用
`request_body_overrides`/`extra_body`；只有证实 SDK 不兼容才增加 `raw_http`。
供应商 client 不应进入 Application。向现有 ModelPool 增加 endpoint，不复制客户端；
不能仅因备用端健康就重试完成状态不明、不可重复的请求。

## 研究与验证

| 证据 | 能够证明什么 |
| --- | --- |
| 静态恢复 | 与精确二进制输入绑定的布局/函数假设 |
| 离线/Mock 构造 | 指定测试夹具中的工具与内存布局行为 |
| 原生 `IsValid` | 指定参数和当前世界下的规则结果 |
| Paired capture | 项目文档规定的配对观察标准，不自动赋予执行准入 |
| 实机执行 | 该构建中已提交动作，并有专属权威/后置条件证据 |

不能从计数、RTTI、原生 true 或存档时间戳变化推断实机可用。保留被拒绝的参数及
失败/中断实验。探针与生产实现分离，不猜指针所有权，不热替换已注入 Runtime。
实机研究需要另行授权的可丢弃会话；常规测试与归档不会接入游戏。

当前 4.5.2 profile 有意限制原生生产执行，4.4.6 历史实验不能覆盖这一限制。
先读 [SDK 恢复](../services/stellaris_native_runtime/tools/sdk_recovery/README.md)、
[约束规划](../services/stellaris_native_runtime/tools/script_candidates/README.md)和
[验收证据](runtime/PRODUCER_VALIDATION_ACCEPTANCE_4_5_2.md)。

## 测试与源码检查

CI 在 Windows/Linux 使用 `python scripts/validation/run_tests.py --quiet` 并构建
原生契约测试。测试与所属模块相邻；测试源码进入 Git，运行输出不进入 Git。
SDK 测试另需：

```bash
python -m pip install -r services/stellaris_native_runtime/tools/sdk_recovery/requirements.txt
cmake -S services/stellaris_native_runtime -B build/native-tests -DIAG_NATIVE_RUNTIME_BUILD_TESTS=ON
cmake --build build/native-tests --config Release
ctest --test-dir build/native-tests -C Release --output-on-failure
```

这是常规测试编译，不是安装包/Release 打包。使用新输出目录，不清除旧证据。
可选集成变量为 `IAG_CWTOOLS_BRIDGE`、`IAG_CONSTRAINT_CODEC_TEST_EXE` 和
`IAG_CONSTRAINT_PREFLIGHT_REPORT`。配置方法见候选工具说明；应说明缺项，不能
把跳过的测试报告为通过。

Session Proxy 分帧、builder 和回包关联变更必须保留原 fixture 和失败测试。
载体改写继续保持等长，除非有明确文档证明特定路线不同。模型不得构造原始字节。
详见 [Session Proxy](SESSION_PROXY_MODE.md)及历史[协议研究](reference/v0_5_8/PACKET_INTERCEPTOR.md)。

## 证据与发布

研究数据走[独立归档](research/EVIDENCE_ARCHIVE.md)，不把 `.runtime-evidence/` 加入 Git。
保留原件、SHA-256、路径映射、源码/二进制/SDK 身份、工具版本及访问决定。
历史源码绑定未知时保持未知。没有分发许可时，不公开游戏可执行文件、未经审查的
存档、凭据、个人数据或展示图片。

本 alpha 的[发布流程](PUBLICATION.md)仅包含源码、证据归档和签名 Git Tag。
DCO trailer 与加密签名彼此独立。既有 `iag` 导入、协议名、可执行文件/配置路径、
Application 版本和载体 Mod 版本不因品牌或平台版本而机械修改。历史迁移清单不可变。
