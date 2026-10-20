# Producer / SDK 定向实机验收：4.5.2

> Publication: original/local evidence paths below are provenance labels, not Git downloads. Use the [indexed archive and access status](../research/EVIDENCE_ARCHIVE.md); public copies may be privacy-redacted and originals remain retained.


## 会话和边界

2026-10-20 UTC，用户确认已启动新进程并加载可丢弃存档。Linux PID `1103670`、start ticks `78626009`，ELF Build ID `121ecb516cbc5f1d39917fbcc36620534384e2c2`，SHA256 `1c4c79a0ef8af7b984b797606373eb68b60fe421e4ef54c20e12e4a9398ba86b`。

注入前核对 21 个内存函数 prefix，未发现已有 Runtime/Probe 映射或活动 IAG socket。只注入一次离线候选库，SHA256 `988dbb48de59e67549f225b396ed454e4273ee9474ab2d1efda9fb368a0d43c2`，得到 revision 4、Runtime instance `137952784172384` 和与 plan 一致的 SDK fingerprint。

本次不调用 Post/Execute，不操作暂停/恢复、不换档、不生成测试场景，不注册生产 Action，不提升 `paired_capture` / `live_verified`。不同阶段使用不同请求 ID 和新输出目录，旧证据全部保留。

## 先发现并隔离的调度错误

原计划先验证三条原生领域 provider，再补测 104 项。首个 `add_buildable_to_queue_command` 请求被库内的 `native_domain_requires_non_updating_idle` 门槛拒绝；构造、填参、IsValid 和析构调用数均为零。请求已有 completed 记录，不存在待重放的悬挂请求。runner 随即停止，没有把其他两条标为已验证。

这是准备阶段错误地将 `Idle` 更新参数当成暂停条件，而不是游戏未暂停。此前暂停实机报告已经记录过 `run_game_update=true`；本次 GameDate 从注入前至完整补测均固定为 `63097440`。

额外静态证据：`CIsPausedTrigger::ActualEvaluate` (`0x3be98a0`) 从全局 `0x5732de0` 读取 `CInGameIdler*`，检查其 `+0x594`；`CInGameIdler::SetPaused` (`0x1c9a910`) 在 `0x1c9aba8` 写入同一字段。vtable address point 为 `0x51f74e8`。只读外部观察确认当前实例的对应 vtable 和暂停位 `1`，没有调用 setter。

先修正外部 runner 的错误旗标判断，保留世界、日期、实例、SDK 和生命周期校验，然后在**原已加载库**上运行不依赖新领域 provider 的 104 项定向 SDK 补测。没有改变库的安全门，也没有静默将领域请求改成 legacy 参数来源。

## 104 项实测结果

| 指标 | 结果 |
| --- | ---: |
| 所选不同 Command / 结构预检通过 | 104 / 104 |
| 成功原生构造的不同 Command | 102 |
| 完成填参与 IsValid 的不同 Command | 85 |
| 至少一次 true / 只有 false | 17 / 68 |
| 缺当前候选 | 19 |
| 原生 IsValid 调用 / true / false | 983 / 17 / 966 |
| started / completed 请求 | 1002 / 1002 |
| 构造 / 析构对象 | 1000 / 1000 |
| 异常 / 悬挂请求 / 重复 started ID | 0 / 0 / 0 |
| 墙钟耗时 | 111.561 秒 |

缺候选的 19 项中，17 项仍完成安全 Factory/析构，未冒充已填参。缺失类型为 `CResolution` 11 项、`CMission` 4 项，其余分别为 `CVivariumCritter`、`CFederation`、`CWaystationNetwork`、scoped `CPointOfInterest`。

17 种 true 均来自 native predicate，不包含 constant validator：市场买入/卖出、领袖调任、开始/取消特殊研究项目，以及对活动事件链、考古、星界裂隙、第一次接触、局势、特殊项目的 Pin/Track 模板命令各六种。这不意味着它们都是战略执行 Action，尤其界面跟踪命令不能充当执行能力覆盖率。

966 次 false 中 587 次保留原生 reason，其余没有原生解释文本。它们仍是参数候选/场景/上下文的未分类拒绝，不能整体归因于 ABI 错误，也不能宣称都已找到合法参数。

probe / validator 累计记录区间分别为 270.767 / 84.964 毫秒；这是内部经过时间，不是 CPU 采样占比或整轮观测开销基准。请求之间有 0.1 秒间隔。

与 expanded batch 按 C++ class identity 去重，避免动态 Token 名称改变造成重复计数：

| 累计不同 Command | 旧基线 | 新增 | 合并 |
| --- | ---: | ---: | ---: |
| 原生构造 | 309 | 1 | 310 |
| 填参及原生 IsValid | 154 | 19 | 173 |
| 至少一次 IsValid=true | 87 | 17 | 104 |

同一进程、世界、Runtime 和日期在补测结束时均通过 runner 的一致性检查。这不是独立重载存档的确定性证明，也不是执行后置条件或多人同步证据。

## 修正及剩余窗口

修正后的研究协议 revision 5 以精确 profile + function signature + idler vtable 校验真实暂停状态，返回独立的 `fixture_paused`。非暂停、未知状态或缺失恢复资料均 fail-closed。`run_game_update` 不再作为暂停状态使用，生产 Prepare/Post/Verify 调度保持原样。

修正源码已分别构建 Linux `.so` 和 Windows `.dll`；Linux 四项 CTest、Windows 三个 C++ 测试程序和 548 项 Python 测试通过。Windows 未恢复该 idler/领域 ABI，仍不宣告 native domain provider。测试覆盖原生暂停 + Idle(true)、未暂停、未知 idler、旧 revision 拒绝、日期漂移及原有生命周期隔离。

新离线 readiness 为 `.runtime-evidence/producer-validation-prep-4.5.2-20261020-01/ready-20261020T093128Z/readiness.json`；它记录修正后的库哈希及源码快照，不替换旧 receipt。实机监督工具的 `--domain-only` 可在新目录派生同 SDK 的剩余领域计划，省略已经完成的 104 项，原 plan 保留不变。

**第一窗口结束时三条领域路径尚未获得实机验收**：普通新建筑、开始科研、取消科研。revision 4 没有热替换或再次注入。用户随后批准了新进程补充窗口，结果如下；原失败记录仍保留，不能改写为一次连续成功的验收。

## 剩余三路径补充验收（已完成）

用户重启并确认同一可丢弃存档已暂停。新 PID `1195296`、start ticks `79090017`，与第一窗口不同。注入前再次确认精确 ELF、21 个原始内存 prefix、无既有 Runtime/Probe、真实 idler vtable 及暂停位 `1`，随后只注入一次修正版库，SHA256 `33009e7adad57c4bfe82fab4bd538b35293c839fb8db94e23a238f779283db17`。

加载目录确认 revision `5`、Runtime instance `134761900533088` 和原 plan 的 SDK fingerprint。新派生计划保持原 SDK，只保留三条领域路径并清空 legacy 补测列表；先测科研，再测持有 Buildable 的建筑命令。**104 项未重跑，351 项仅查询目录，未全量测试**。

两轮均通过，世界 `98018282283648`、GameDate `63097440` 和 Runtime 身份保持不变。52 次请求全部报告 `fixture_paused=true`，同时仍全部为 `run_game_update=true`，实机验证了修正后的区分。

| 路径 | 每轮候选 | 两轮 IsValid 调用 | true / false | 证据结论 |
| --- | ---: | ---: | ---: | --- |
| 开始科研 | 16 | 32 | 0 / 32 | 从 Country 0 实际 alternatives 取得参数，CanQueueResearch 与最终 IsValid 均拒绝本轮候选 |
| 取消科研 | 2 | 4 | 4 / 0 | 从 Country 0 当前任务取得 `tech_administrative_ai`、`tech_society_1`，均通过原生合法性检查 |
| 普通新建筑 | 8 | 16 | 2 / 14 | 原生槽位查询与 sret Producer 在共享 Builder 中构造拥有型对象；`building_clone_vats` 在两轮均通过最终 IsValid |

建筑通过项的完整语义身份为 `country=16777218;colony=12;zone=24;building=building_clone_vats;mode=new`。国家和完整对象引用来自当前原生数据库、所属殖民地及返回槽位关系，不是手工寻找 ID 或从历史 Command 重放。它是多国家参数发现的研究证据，不授权生产 Broker 跨国家执行。

其他建筑样本的原生 reason 包括已有首府、资源不足、缺科技和类型数量上限等；不把这些拒绝整体视为恢复失败。所有八个槽位前置检查均为 true，但仅一个最终 Command 合法，实证说明 `native_rule_valid` 不能替代最终 IsValid。

开始科研的 16 个候选均被拒绝；其中包含两个当前正在研究的科技，保留了“正在研究”等原生文本。其余有原生前置提示或没有解释文本，尚不能逐项确定完整拒绝原因。没有执行取消科研来制造开始科研的条件，也没有因此否定原有已验证科研结构。

两轮分别耗时 3.095 / 2.961 秒。26 个有序候选的语义身份、参数绑定、前置规则、最终合法性及状态在两轮间一致，原生 reason 文本也相同。52 个 started/completed 请求全部配对，52 个原生 Command 构造/析构全部配对，异常、重复请求、悬挂请求均为零。报告的 probe / validator 累计经过时间为 29.210 / 2.105 毫秒，不是 CPU 使用率。

按原 expanded 基线、104 项补测及本次领域结果的 C++ class identity 合并，累计成功构造 **310** 种、完成填参/原生 IsValid **174** 种、至少一次 true **105** 种。本次新增的已填参/已调用 IsValid/ever-true 类型均为 `CAddBuildableToQueueCommand`，不将重复两轮或已验证过的科研类重复加数。

**本轮三条构造与验证路径均已完成，但只有两条在本夹具取得正向合法性证据。** 搜索受到 16 候选/64 次领域查询等原有限额约束；科研和建筑报告 search truncated，不能声称已枚举完整合法集合。同一会话的重复性仍不是独立重载存档的确定性证明。全程未调用 Post/Execute，未实际建造或取消科研，也未提升任何生产准入等级。

## 证据

本地根目录：`.runtime-evidence/producer-validation-live-4.5.2-20261020-01/`。

- `attempt-20261020T084913Z/`：部署/注入 receipt、加载目录、首轮拒绝及窗口停止记录。
- `pause-static-20261020T091438Z.json`：精确 ELF 的暂停字段与调度反汇编证据。
- `backfill-20261020T091601Z/paused-preflight.json`：外部只读的世界、日期、idler vtable 和原生暂停位。
- `backfill-20261020T091601Z/remote-evidence/batch/`：完整 104 项报告、每项候选与 started/completed journal。
- `review-20261020T092412Z.json`：生命周期配对和按类名去重的增量汇总。
- `pause-static-20261020T092848Z.json`：新增 profile 中 pause prefix、全局地址、vtable 和 offset 与精确 ELF 的自动对照。
- `health-20261020T093102Z.json`：最终只读复查，PID/start ticks、世界、日期、暂停位、Runtime 目录及已加载文件哈希保持不变；本轮始终只有一次注入。
- `attempt-20261020T094606Z/`：修正版新进程的独立部署/注入 receipt、domain-only plan、完整两轮报告和请求 journal。
- `domain-review-20261020T095153Z.json`：三路径逐候选汇总、生命周期配对、同会话重复性、按类名累计覆盖与原始证据 SHA256。
- `health-20261020T095253Z.json`：补充窗口后的只读复查，PID/start ticks、世界、日期、原生暂停位、目录和加载库哈希不变，进程正常存活。

远端原始目录分别为 `<RESEARCH_HOME>/iag-captures/producer-acceptance-20261020T084913Z-c3b58208`、`<RESEARCH_HOME>/iag-captures/producer-backfill-20261020T091601Z`，未覆盖或清理。

补充窗口远端原始目录为 `<RESEARCH_HOME>/iag-captures/producer-acceptance-20261020T094606Z-b7862c0a`，亦独立保留。
