# Native Producer 统一验收准备：4.5.2

> Publication: original/local evidence paths below are provenance labels, not Git downloads. Use the [indexed archive and access status](../research/EVIDENCE_ARCHIVE.md); public copies may be privacy-redacted and originals remain retained.


## 范围与状态

本文的初始阶段是离线实现、构建和模拟验证，没有访问游戏。2026-10-20 获准的新进程实机窗口结果另见 [PRODUCER_VALIDATION_ACCEPTANCE_4_5_2.md](PRODUCER_VALIDATION_ACCEPTANCE_4_5_2.md)。原始离线 readiness、源码快照和失败批次均保留；不得用后续修正后的源码解释此前已加载库的行为。

目标从“独立字段池组合”推进到“指定国家的原生状态/领域查询提供关联参数”。保留 `Application -> Broker -> Native Runtime`、现有 `CGameIdler` 队列，以及共享 `NativeCommandBuilder`。

新证据根目录：`.runtime-evidence/producer-validation-prep-4.5.2-20261020-01/`。已有生成 consumer header、基线报告、原始证据和 checkpoint 未覆盖。

精确 Linux ELF Build ID 为 `121ecb516cbc5f1d39917fbcc36620534384e2c2`，SHA256 为 `1c4c79a0ef8af7b984b797606373eb68b60fe421e4ef54c20e12e4a9398ba86b`。领域查询的 Windows ABI 尚未恢复，因此 Windows **不宣告这些 provider 可用**；不是把 Linux 地址用于 Windows。

## 已实现的参数路径

| Command | 关联参数来源 | 构造和验证 | 本阶段边界 |
| --- | --- | --- | --- |
| `CResearchTechnologyCommand` | 指定 Country 的 `CTechnologyStatus`、按研究区域保存的实际 alternatives、有效科技定义库 | `CanQueueResearch` 与共享 Builder 的 Factory/类型化填充/最终 IsValid/析构 | 不执行完整科研 AI，不消耗 AI 选择用的 RNG；不宣称候选列表覆盖所有理论科技 |
| `CCancelResearchTechnologyCommand` | 同一 Country 的已有研究任务，保留任务中真实 technology 定义 | 共享 Builder；最终使用取消命令自己的 IsValid，而非误用开始研究的规则 | 没有当前任务就记录缺候选，不主动开始研究制造条件 |
| `CAddBuildableToQueueCommand`，普通新建筑分支 | 本国 Colony refs、其 District/Zone 关系、实际 BuildingType 数据库、`FindBestBuildingSlot(..., false)` | 游戏 Factory 分配 -> 正确结束默认值生命周期 -> `CreateAddBuildableCommand` 显式 sret 就地构造 -> 核对嵌套 Buildable 和完整对象身份 -> IsValid -> 游戏 deleting destructor | 不直接填私有队列/owning pointer，不 memcpy C++ 对象；升级、替换、维修和 externally-owned subtype 暂不冒充普通新建 |

源码分别在 `command_producers.cpp`、`command_builder.cpp`、`sdk_probe.cpp`，均属于现有服务。领域 provider 不注册生产 Action，不新增 Hook、执行队列或 RPC 服务。未来受审 Action 可以复用同一 provider/Builder，而不是再手写一套命令布局。

### 建造生命周期

`CreateAddBuildableCommand` 返回的是含有 owning Buildable 的完整 Command 值，不是裸指针。Linux 调用点确认：隐藏 sret 为 RDI，Country 为 ESI，Colony/Zone/Type/已有 Building 为 RDX/RCX/R8/R9，最后 bool 在栈上；RAX 返回 sret 目标。

Builder 复用生成元数据中的游戏 Factory 分配，检查动态类型及 IsValid、token、deleting destructor。新 `ReconstructFromProducer` 还要求已恢复的生命周期安全标记、Linux ABI、正确的 primary 非删除析构槽，然后让原生 Producer 在原分配中构造新值。最终由 Builder 调游戏的 deleting destructor，释放 Command 和其嵌套拥有型对象。

没有另造一个分配器、clone 布局或研究专用 Command 表。原生构造异常后不能假设对象仍有效：该分配被隔离，不猜析构，报告 `call_exception` / `destroyed=false` 并终止批测。C++ catch 不承诺拦住 SIGSEGV 或引擎 abort；此时 started journal 保留悬而未决请求，禁止自动重放。

普通分支以外的原生 Buildable 会正确析构并标为 `native_building_subtype_not_covered`，可继续下一个有界候选；真正的国家、队列、Colony/Zone 或外层 vtable 不一致则停止，不降低检查标准。

### 查询边界

- 原生函数先检查精确 profile/SDK 身份和对应机器码 prefix。建造的 key 偏移另由 `0x2183230` serializer 的 `Buildable+8 -> BuildingType+0x10` 数据流确认。
- 所有对象保留 full-generation ref，并经原生数据库重新解析；返回的 District/Zone 必须是同一 Colony 列表中的配对。
- 原生指针只在一次游戏线程请求内存在；返回报告记录国家、定义 key 和候选语义身份，不将这些指针变成上层工具参数。
- 每次请求至多 16 个候选、64 次直接领域查询；建造至多扫描 512 个定义、16 个本国殖民地，对 district/zone 列表另有限额。这里的查询计数不是引擎内所有嵌套函数的调用次数。
- 自动 Country 从有效 observed Country 和有界国家数据库选择；没有任何领域候选且没有发生原生规则调用的空国家可以跳过。已开始求值后不把 64 次预算再乘以国家数量。实际选择的 Country 明确写入报告。
- 静态函数体没有 Post，并不能证明所有传递脚本求值完全没有缓存/RNG 副作用。**这些查询仍待实机安全性及重复性验证**，本轮不因此变成生产只读 API。
- 保持 Factory/Producer 的默认来源标记，不调用会入队及改变 AI 预算的 `AddAICommandForPosting`，也不试改 AI 标记以提高 true 数量。来源上下文可能是 false 的原因之一，不能把它误判为字段恢复错误。

报告的 `native_rule_valid` 仅指所用 provider 的前置规则：科研的 CanQueueResearch 或建造的槽位/CanAddBuilding 判断；**不表示完整行动合法性**。最终 Command 的 `native_is_valid` 独立记录。穷举候选时最后一个结果可能为 false，因此另有 `has_native_valid_candidate` 和不同 Command 的 ever-true/negative-only 汇总，不用最后一次结果覆盖历史成功。

## 统一批次

新 `prepare_validation_window.py` 复用现有 recovery audit 与 SDK emitter，不重新逆向。输入为 `incremental-offline-33-20261019T2337Z/linux_sdk.json` 和不可变的 expanded batch 报告。

最终准备结果 `prepared-inputs-v3/` 包含：

- `recovered_sdk.hpp`：独立生成的候选 consumer，不替换旧 header。
- `audit.json`：全部 351 个 Command 的原有恢复审计与 blocker。
- `plan.json`：三个领域 provider，以及 **104 个定向补测项**。排除既往 true-only 和静态阻碍；已进入领域路径的 Command 不再重复走独立字段池。

因此计划覆盖 **107 个不同 Command**，并非新增 107 个可用 Action，也不是重跑 351 项。158 个静态 blocker 仍如实保留。AddBuildable 的普通新建筑路径由 Producer lane 探测；它此前的 serializer 字段可写，并不表示 serializer 之外的 owning Buildable 已具备完整业务参数，不能将静态 eligible 等同于语义完备。

候选 SDK 的 canonical fingerprint 为 `f84eed28dfa08fae0188b7ca61f2f979910a17ae954240f0d72c15762021d466`。`describe_recovered_commands` 公布已编译 SDK fingerprint 及研究 provider 名单；**它不是 Broker tool manifest**。修正后的领域批测要求 revision 5，以确认原生暂停状态检查已经编译进去；旧 revision 4 不可复用该 lane。runner 在任何原生探测前核对 plan 与实际加载的 SDK，不允许拿新审计配旧二进制，更不允许静默回退到旧候选路径。

首次生成的 `prepared-inputs/`、`prepared-inputs-v2/` 和早期失败构建也保留。v2 去除两项跨 lane 重复；v3 将动态 Token/模板命令的审计类名映射到 emitter 的真实 SDK 请求名，例如 `token_0_197`，避免类名不在运行时目录中。生成 header 和其 fingerprint 均未变。该 fallback 名只用于研究目录，绝不是生产 semantic Action 名。失败构建中的 `.inc` 打包遗漏、以及模拟测试提示文本变更均已修正，不属于实机崩溃证据。

## 复现

仓库根目录离线准备，输出目录必须不存在：

```bash
python services/stellaris_native_runtime/tools/prepare_validation_window.py \
  --sdk .tmp/sdk-recovery/incremental-offline-33-20261019T2337Z/linux_sdk.json \
  --baseline .runtime-evidence/sdk-expanded-batch-20261019-01/batch/report.json \
  --output .runtime-evidence/producer-preparation-new
```

在独立构建目录选择候选 SDK，使用绝对路径：

```bash
cmake -S services/stellaris_native_runtime -B /tmp/ogas-producer-build-new \
  -DIAG_NATIVE_RUNTIME_BUILD_TESTS=ON -DCMAKE_BUILD_TYPE=Release \
  -DIAG_NATIVE_RUNTIME_RECOVERED_SDK_HEADER=/absolute/path/recovered_sdk.hpp
cmake --build /tmp/ogas-producer-build-new -j1
ctest --test-dir /tmp/ogas-producer-build-new --output-on-failure
```

不设置该编译选项时，原有默认 consumer 路径保持不变。Factory、字段、IsValid 与析构仍全部来自同一 SDK，研究和生产没有平行布局。

## 下一次实机窗口

需要一次新的 Linux 4.5.2 会话、一个可丢弃的较完整存档，等待加载初始化完成后保持暂停。优先包含有 Colony/District/Zone、可用建筑空间、资源和科研候选/当前研究的普通国家；不必寻找 ID、点击按钮或等待 AI 发命令。没有的条件会跳过，不制造世界状态。

窗口获准后只加载一次新候选 Runtime。**不得在已加载旧 Runtime 的进程里热替换或重复注入。** 本工具本身不提供 loader、读档、暂停、恢复或提交功能。

使用同一 endpoint，运行一个入口，全部证据写到新目录：

```bash
python services/stellaris_native_runtime/tools/validate_recovered_commands.py \
  --native-domain --repeat 2 --candidates 16 --interval 0.1 --max-seconds 900 \
  --plan /absolute/path/prepared-inputs-v3/plan.json \
  --output /absolute/path/producer-acceptance-new
```

执行顺序：

1. 核对精确 Build、SDK fingerprint、同一 Runtime instance、目录及 provider 能力。
2. 在现有 CGameIdler 队列内逐请求做三类领域参数/构造/IsValid/析构，重复两轮，比较有序语义输入与规则结果。
3. 在同一世界及 GameDate 上补测 plan 中 104 项，不重跑其他旧项目。每次最多一个 validator 请求；总时间预算和批间身份检查继续有效。
4. 归档每次 started/completed、每个候选、每项 Command、窗口总结和不可比较原因。异常/连接断开不自动重放 pending 请求。

领域调用要求原生暂停状态为 true，而不是要求 `run_game_update=false`。已知暂停实机报告及本次窗口均观测到 `Idle(true)`：此参数控制 application/update 调度，不等同于模拟暂停状态。revision 4 新增的非 updating 限制因此是准备阶段的回归错误，首个领域请求被拒绝且未构造对象。

revision 5 在现有游戏线程上，只读检查精确版本的 `CInGameIdler` singleton、vtable 和 `+0x594` 暂停位；`CIsPausedTrigger::ActualEvaluate` 和 `SetPaused` 的静态读写证据及本次外部内存观察支持这一字段。无 profile/signature、错误 vtable、未知或非暂停状态均拒绝领域探测，不提交暂停命令。runner 另外检查每次调用前后及轮次间的 GameDate、世界、Runtime、输入源；更新标志只作为诊断记录。缺候选和正常 IsValid=false 不是逆向失败，也不自动否定结构恢复。revision 5 随后在用户批准的新进程补充窗口完成两轮三路径验证，不能将此解释为对旧 revision 4 的热替换。

同一进程的重复结果只说明该夹具下的重复性；**不冒充独立重载存档的确定性证明**。独立重载对照、完整 RNG/脚本副作用审计、多帝国授权和多人同步仍需另行实验。

## 可用 Action 的准入

本窗口默认仍只做 `Construct/Populate -> IsValid -> Destroy`，不调用 Post/Execute，不注册新生产 Action，不自动提升 `paired_capture` 或 `live_verified`。

下一步可直接使用这些共享构造能力填写受审语义 Action，而不用再恢复 Factory/owning pointer/sret。真正进入可用状态还需要：语义目标和合法候选、权限及快照检查、资源 reservation、明确的执行后置条件，以及另行授权的实际提交证据。

未来执行确认优先核对原生科研任务/建造队列中的国家、目标、定义和对象身份，再与保存后的持久化状态对应；仅 IsValid=true、Post 返回、同一时间出现存档或弱 validator 恒真均不算业务成功。现有 save continuation 和 authoritative confirmation 不能为提速而绕过。当前尚未实现的新 postcondition 不能伪装成自动确认。

## 离线验证

已运行的模拟用例覆盖 Factory/默认值析构/原生 Producer/拥有型子对象析构、错误 ABI 平台拒绝、代码 signature 不符、完整 generation、外来 Zone、规则 false、候选耗尽、原生构造 C++ 异常隔离、固定日期/实例漂移、SDK-plan 不符及断线不重放。

Linux `.so` 和 Windows `.dll` 离线构建；Linux CTest 四项、Windows 三个 C++ 测试程序及维护 Python 测试结果保存在证据根目录的 UTC 构建/审计目录。它们是编译和模拟证据，不增加原有 309 构造 / 154 native IsValid / 87 ever-true 实机基线。

没有更改 Broker、Action 生产权限或旧 consumer header，也没有新增长程实验。实机窗口仅按授权加载一次候选 Runtime；后续修正只离线构建，未修改或热替换已经加载的库。
