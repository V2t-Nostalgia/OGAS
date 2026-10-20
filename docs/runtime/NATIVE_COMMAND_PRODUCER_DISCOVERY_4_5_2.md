# Native Command Producer Discovery (4.5.2)

> Publication: original/local evidence paths below are provenance labels, not Git downloads. Use the [indexed archive and access status](../research/EVIDENCE_ARCHIVE.md); public copies may be privacy-redacted and originals remain retained.


研究日期：2026-10-20 UTC。范围：精确 Linux ELF 的静态、离线研究。
本轮没有连接游戏、调用 native 函数、提交命令、加载存档、替换 Runtime 或修改观察器。
已有增量观察器的活动不属于本报告新增的实验。

## 1. 三个方向性答案

| 问题 | 结论 | 证据边界 |
| --- | --- | --- |
| Q1：UI 是否有完整参数生产链？ | **有，且按领域分别实现。** 月度交易把资源、类型、Country、数量、价格和已有订单身份组装成原生记录，再构造 Command。建造还有不依赖 View 的构造辅助函数。 | 不等于游戏预先维护了全部合法 Command 的列表；按钮条件、点击时检查、提交后检查也不完全相同。 |
| Q2：AI 是否使用相同 Command 系统，参数来自哪里？ | **所调查的科研、建造、移动、即时市场、外交路径确实使用 CCommand。** 参数来自本国科技状态、所属殖民地和有效定义库、AI 舰队组目标、本国资源与外交关系。AI 先按国家入队，再统一提交。 | 这不是“所有 AI 行为均经过 Post”的证明。完整 AI Producer 还会改变随机数、计划、预算及其他 AI 内部状态，不能整体当只读查询。 |
| Q3：是否有显式 Country、无需 UI 的接口？ | **有领域级接口。** `FindBestBuildingSlot`、`CreateAddBuildableCommand`、`CanQueueResearch`、`ListPotentialWarGoals` 等接受具体国家或绑定该国的对象状态。 | “公共”在此仅指可被多个内部调用者复用，并非稳定导出的 SDK。未发现一个万能 `Country -> 所有合法行动` 接口；参数合法性也不赋予跨国提交权限。 |

因此，`paired_capture` **不是恢复候选与参数的必要前提**。完整 Producer 的静态恢复可以独立记录为研究证据 `native_producer_recovered`，但不能据此变更生产 Action Registry 的验证等级。

## 2. 二进制与证据

- ELF Build ID：`121ecb516cbc5f1d39917fbcc36620534384e2c2`。
- ELF SHA-256：`1c4c79a0ef8af7b984b797606373eb68b60fe421e4ef54c20e12e4a9398ba86b`。
- 输入 SDK：`.tmp/sdk-recovery/incremental-offline-33-20261019T2337Z/linux_sdk.json`。
- 新归档根目录，以下简称 **E**：`.runtime-evidence/native-command-producers-4.5.2-20261020-01/`。
- 每个 `pass-*/functions.json` 保存完整选定函数的机器码、SHA-256、逐指令解码、直接调用、间接调用及 RIP 引用；同目录保存原始符号清单与选择条件。
- `static-metadata-01/vtable-slices.json` 保存七个类的原始 vtable 切片与符号。切片可能包含 secondary-vtable header，不能把每个字都当作函数槽。
- `audit-01/audit.json` 将归档重新与 ELF 逐字节核对，并检查调用指令边界、E8 目标、重复函数一致性与 vtable 原始字节。

共保留 **236 个不同函数、59,494 行指令、245,043 字节函数体及 174 条指令边界确认的直接调用交叉引用**。这是函数证据量，**不是新增 Command 或实机覆盖量**。完整线性解码不等于完整 CFG、所有分支可达或实机调用证明。虚调用只有在另有匹配 vtable 证据时才解析为具体方法；其他间接边仍标为未解。

证据等级：**A** 为本报告直接展示的静态结构/数据流；**B** 为复用候选与副作用边界的待验证推导；**C** 为确定性夹具、实际调用安全性、执行、身份和同步的实机验证。下文提出的最小复用接口属于 B，不因其有符号名就成为可安全调用的生产接口；第 8 节给出分别验证的方法。

下文 RVA 沿用 SDK 命名，记录该 ELF 的 `st_value`。实际绑定必须结合精确版本和 load bias，不得把它们当跨进程绝对地址，更不能直接用于 Windows ABI。旧 4.4.6 捕获仅作研究线索，不充当本轮 4.5.2 执行证据。

## 3. AI 公共生产与提交路径

```text
CGameState::ProcessAI                         0x1b17060
  -> 遍历世界的 Country 引用，解析各国现有 AI
  -> 必要时创建 CCountryAI，SetOwner(Country)
  -> UpdateAIParallel                         0x28086c0
       -> 各国 Update / 领域模块
       -> 选择候选、构造 Command
       -> AddAICommandForPosting             0x26ec380
            设置 AI 标记 -> IsValid -> 本国 pending queue
  -> 对 AI 列表逐国 PostAICommandsToSession   0x26fdd90
       -> PostCommandToSession(command, true) 0x1b02540
       -> CSession::Post                     0x3ca7880
       -> session/backend 虚接口             [具体实现未在本轮穷尽]
       ... 同步、接收与调度关系需单独验证 ...
       -> ProcessSynchronousCommands         0x3ca8300
            -> IsValid -> Execute -> 清理
```

### 国家与调度证据

- `ProcessAI` 从世界 `+0x548` 的 Country 引用数组、`+0x554` 的数量出发，不是 `GetLocalObserved()`；逐项执行数据库边界和完整 ID 比较。
- 创建 AI 的调用点 `0x1b17154`，设置 AI 为 `0x1b17164`；紧接着 `0x1b17174` 的虚槽 `+0xa8` 在 `CCountryAI` 表中对应 `SetOwner`，而不是任意编号写入。
- `CCountryAI::SetOwner` 在 `0x26ec79a..0x26ec79d` 把 Country `+0x20` 的完整引用写入 AI `+0x3a0`，随后重置本国 `CAICacheHelper`。它是初始化 mutator，不能为了查询而随意调用。
- `CCountryAI::GetCountry const()`，`0x26eae80`：读 `+0x3a0`，以低 24 位索引数据库，再核对对象的完整 ID。最后的虚槽 `+0x40` 由 `CCountry` vtable 解析为 `GetCountry const()`，其 `0x1a59e10` 函数体只返回自身。
- `UpdateAIParallel` 的普通并行分支经 `0x2808b20` 在 `0x2808c03` 调用 `CJob::WaitAndClear()`；渲染协作分支另经 `ParallelForRenderFrameIfNeeded`。本轮没有证明可从外部安全重入这些调度器。
- `ProcessAI` 调用更新的位置是 `0x1b172a0`；其返回后，`0x1b172d5` 在循环中逐国 flush。不能把原生 AI 的 worker 队列直接替代 OGAS 的游戏线程队列。

### 入队不是只读校验

`AddAICommandForPosting` 的关键指令：

```asm
0x26ec394  mov byte ptr [rsi + 0x16], 1 ; 入队前标记 AI 来源
0x26ec3a0  call qword ptr [rax + 0x48] ; Command::IsValid
0x26ec3b6  call CPdxMutex::Lock
0x26ec3d6  call CPdxArray<CCommand*>::InsertAtEmplace
0x26ec3de  call CPdxMutex::Unlock
0x26ec3fc  jmp  qword ptr [rax + 8]    ; 拒绝分支的 deleting destructor
```

成功时 Command 指针进入该 AI 的拥有型 pending 列表：嵌入数组 `+0x518`、数据 `+0x520`、数量 `+0x52c`，锁 `+0x5b0`。无效对象会被销毁；调用者不得再次析构或复用已经移交的指针。flush 在 `0x26fddc0` 提交，之后清零计数。

`PostCommandToSession` 的 bool 为 true 会跳过其一段本地玩家条件，但**不能推导为任意客户端可以控制任意国家**。`CSession::Post` 还有会话状态和虚接口检查，并填充 Command 的会话相关字段。`ProcessSynchronousCommands` 在 `0x3ca841c` 再次调用 IsValid，在成功分支 `0x3ca8924` 调用虚槽 `+0x50`，对应 Command 的 Execute。本轮没有恢复所有网络实现，也未证明 host/client 的授权等价性。

证据：E 的 `pass-01`、`pass-02`、`pass-03`、`pass-04`、`pass-07`、`pass-08` 与 vtable 切片。

## 4. 五类代表性生产链

### 4.1 月度交易：UI 参数生成的完整案例

在 [已有身份研究](SDK_MONTHLY_TRADE_IDENTITY_4_5_2.md) 的基础上连接参数来源，而不是重新把订单 ID 当候选标量枚举。

| 阶段 | 函数 / RVA | 参数来源及判断 |
| --- | --- | --- |
| 资源、方向与初值 | `SelectBuy 0x2f97280`、`SelectSell 0x2f972c0`、`InitAmount 0x2f99670`、`InitPrice 0x2f99770` | 资源来自 View 当前定义指针 `+0x5c0`，类型 `+0x5b8`。默认数量由资源 `+0x158` 与有效 `MARKET_MONTHLY_TRADE_FRACTION` 做原生定点运算及正值向上取整；不是猜固定数量。价格初值为零。 |
| 已有订单 | `CMarket::GetMonthlyTrades 0x1d4dec0`、`ShowWithData 0x2f97c00` | 取得同一国家的完整已有记录，复制资源、类型、数量、价格、ID。该 getter 不是新订单参数生成器。 |
| 组装记录 | `GetCurrentTradeData 0x2f99430` | resource/type 来自上述 View 字段，Country 来自 `GetLocalObserved`，amount/price/id 来自 `+0x608/+0x60c/+0x610`。输出为原生构造的 48 字节记录，含两个 vptr。 |
| UI 预检查 | `CanAddTrade 0x2f97b30` | 构造 Add Command，`0x2f97bc5` 调用 Add 的 IsValid；即使 View 正在编辑已有订单，这里也不是 Update 的弱校验。 |
| 点击提交 | `AddTrade 0x2f96fe0`、`CancelTrade 0x2f96e60` | ID 的符号选择 Add/Update；取消使用完整当前记录构造 Remove。验证通过后另建 heap copy，再走 Post。这些回调会提交，不能用作研究查询。 |

数量/价格可以继续被 UI 编辑；默认参数不是完整合法集合。`Remove::IsValid 0x4329230` 恒真，`Update::IsValid 0x4329350` 主要检查该国 ID 成员关系，**均不能取代完整游戏规则**。新建和已有订单的身份、资源及参数必须相关联，不能拼接独立随机候选。

AI 对照：`CAIInteriorMinister::HandleMarketTrade 0x2757210` 使用本国资源、最近收入、资源 AI 需求，调用 `CMarket::IsValidResource`、`CalcResourceTradeAmount`、`CalcResourcePriceForAmount`、`CanBuyResource` 以及 AI 预算检查。`0x2757f09` 构造 **即时** `CMarketBuyResourceCommand`，`0x2757f14` 入 AI 队列；出售走 `SellResources`。这证明 AI 有非 UI 的市场参数计算路径，**不证明 AI 使用 UI 的月度订单 Producer**。未发现直接调用也不排除内联或其他路径。

证据：E `pass-01`、`pass-02`；既有 `offline-32` 完整月度函数与 `offline-33` 整记录来源证据均保留。

### 4.2 科研：国家科研状态与战略选择可以分开

UI：`CTechnologyViewTechnologyEntry::OnResearch 0x32df210` 从 entry `+0x90` 取得已选科技，转到 `CTechnologyView::OnResearch 0x32d9490`；后者获取 observed Country，调用 `CResearchTechnologyCommand` 构造器 `0x22a4180`、IsValid `0x22a42a0`，然后 heap copy 与 Post。

AI：`CAIInteriorMinister::UnlockTechnologies 0x2751f30` 取得其 AI 的 Country，访问 **Country `+0x15e0` 的 CTechnologyStatus**，而不是玩家的 View。以 area 0/1/2 和本 AI `CNoiseRandom` 生成的整数调用 `GetTechToResearch 0x20b3980`。例如：

```text
0x2751f64 CNoiseRandom::GetInteger
0x2751f70 GetTechToResearch(area=0, seed=返回值)
0x2751fb3 CResearchTechnologyCommand(country完整ID, technology*)
0x2751fbe AddAICommandForPosting
```

候选和规则的实际来源：

- `GetTechToResearch` 读取该状态中每 area 的已有研究项和候选数组，后者数据 `+0x110 + area*24`、数量 `+0x11c + area*24`。这不是从先前 Command 日志取科技。
- 小数组 helper `0x20b4200` 在 `0x20b4280` 调用 `CanQueueResearch`，再算 `GetAIWeight`，最后按显式 seed 加权选择；大数组分支也执行相应检查与评分。
- `CanQueueResearch 0x20afa60` 使用该状态的所属 Country `+0x10`、科技等级和研究区域/队列状态，并调用 `CTechnology::CanResearch 0x20953a0`。
- `CResearchTechnologyCommand::IsValid` 解析 Command Country，定位同一 `+0x15e0` 状态，`0x22a42ea` tail-call **相同的 CanQueueResearch**。UI 与 AI 在这里共享规则。

`UnlockTechnologies` 会消耗实际 AI RNG 并入队，不能作为只读候选接口。优先复用候选状态和 `CanQueueResearch`；如需原生加权选择，应固定显式随机输入，并另验其传递调用的副作用。候选数组完整生成/刷新条件、脚本权重的全部依赖尚未穷尽，不能宣称该数组覆盖所有理论可研究科技。

证据：E `pass-01` 到 `pass-05`，及后文持久化状态证据。

### 4.3 行星建造：已找到非 UI 的槽位与嵌套对象 Producer

UI `CSharedPlanetViewConstructionEntry::OnConstructImpl 0x31755b0` 解析当前 Colony、Zone、BuildingType、国家和已有建筑。在 `0x3175682` 通过 `GetBuildingFromArray` 将槽位/已有建筑与该国关联，`0x31756b4` 调用：

```cpp
NConstruction::CreateAddBuildableCommand(
    TPdxRef<CCountry>, CColony const&, CZone const&,
    CBuildingType const&, CBuilding const&, bool);  // 0x26d2e90
```

它**不读取本地 UI、不 Post**：先 `GetBuildQueueRefOwnedByCountry 0x285f390`，再调用 `CreateBuildable 0x217ae30`，最后返回 `CAddBuildableToQueueCommand`。返回的 Command 持有 `+0x20` 的拥有型 Buildable、`+0x28` 的完整 Country ref、`+0x2c` 的本国队列 ref。`CreateBuildable` 根据原生对象状态选择新建、升级、替换、维修及 externally-owned 子类，处理 null-object 与 generation 检查，而非要求调用者手填全部嵌套布局。

Linux SysV 契约也由调用点确认：隐藏 sret 在 RDI，Country 在 ESI，Colony/Zone/BuildingType/已有建筑依次在 RDX/RCX/R8/R9，最后的 bool 在栈上。**不能忽略 sret，把它误当返回裸指针。** bool 在此 UI 来自 entry `+0xd0 != -1`，true 分支选择升级类；尚未完整命名所有业务语义，不应自行试填。Windows 必须独立恢复其返回 ABI。

UI `CanConstruct 0x3174f70` 另做 observed-Country 与建筑权限检查，再构造临时 Command 并 IsValid/析构；点击也再次验证，再 clone/Post。这是按需查询，不是维护预生成命令列表。

AI 的参数来源已追到实际有效定义库与本国殖民地：

| 阶段 | 静态证据 |
| --- | --- |
| 本国目标 | `CreateBuildPlan 0x2708db0` 从所属 Country `+0x2690/+0x269c` 的 `owned_planets`（实际元素为 Colony ref）构造殖民地列表，逐项 generation-check，并过滤已有建造。 |
| 建筑候选 | `FillBuildPlan` 的 task invoker `0x272e6b0` 从 `TGameDatabase<CBuildingTypeDatabase>::_pInstance + 0x48` 取有效类型数组，`0x272e6f7` 调用建筑版 `EstimateAndAppendToBuildPlan 0x273f6c0`。不是解析外部 Mod 文件后臆造对象指针。 |
| 规则和评分 | worker `0x273fe40` 遍历类型，检查国家科技模块、`CBuildingType::CanBuild(Country, Colony)`，计算成本、生产/维护、赤字及原生 AI 权重。技能/脚本权重与合法性不是同一件事。 |
| 参数关联 | `NBuildPlanEstimator::AppendToBuildPlan 0x28142e0` 在 `0x281430e` 调用 **FindBestBuildingSlot 0x2a7e990**。该查询按 Colony 的 District refs、各 District 的 Zone refs 遍历，并在 `0x2a7eaea` 调用 `CColony::CanAddBuilding(Zone, BuildingType, bool, Country, reason)`。返回 optional，包含 District/Zone 指针；没有可用目标就不生成该项。 |
| 嵌套对象 | 选中 Zone 后，构造 `CBuildableBuilding`，写入该 Colony/Zone 的完整引用和 BuildingType，交给拥有型加权 BuildPlan；排序字段的全部业务含义未恢复。 |
| 最终生产 | `BuildAndUpgradeDistrictsAndBuildings 0x2770200` 对选中项再检查队列、预算和维护等，取真实队列，在 `0x27707e3` 构造 AddBuildable Command，`0x277080c` 进入带成本的 AI 入队 helper。 |

共享规则链：`CAddBuildableToQueueCommand::IsValid` -> `CConstructionQueue::CanAddItem 0x21774c0` -> Buildable 虚槽 `+0x68`；`CBuildableBuilding` 的该槽由 vtable 证实为 `CanBuild 0x217d4b0`，再进入完整 `CBuildingType::CanBuild 0x226ba00`。之前的候选、槽位判断不能替代此最终检查。

重要副作用：完整 `CreateBuildPlan/FillBuildPlan` 修改 AI 计划并调度任务；`AddAICommandWithCostForPosting 0x2789bf0` 除构造/IsValid/clone/入队外，还调用 `WithdrawCost 0x26fa4c0` 更新 AI 成本记录。不能借它做 dry-run，也不能借用后再次释放它移出的 Buildable。

**这是最优先的复用候选：原生槽位查询 + 非 UI 构造辅助函数。** 但本轮只完成静态契约，未调用它们，也未证明所有传递脚本查询、分配及析构在外部研究上下文中安全。

证据：E `pass-01` 到 `pass-08`；`pass-07/direct-xrefs.json` 保留建筑候选 invoker 的 E8 调用点。

### 4.4 舰队移动：共享 Order，UI/AI 的 Command 包装不完全相同

- UI 坐标路径 `CMoveFleetOrderButton::OnClick(CCelestialCoordinate const&) 0x2da2df0`：坐标为输入；国家来自 `GetLocalObserved`，舰队列表来自按钮 `this+8`。`0x2da2e26` 构造 `CMoveToSystemPointFleetOrder 0x29a38b0`，根据 modifier key 等 UI 状态选 `EQueueMode`，`0x2da2e7c` 构造 **CQueueFleetsOrderCommand**，再 IsValid/copy/Post。
- UI 星系路径 `0x2da3000` 根据指定 Country 调用 `CalcMoveToOrbitable 0x260cac0`，分支选择轨道目标或 `CalcMoveToPoint 0x260cc90`。后者经按钮虚槽 `+0x78` 回到上述坐标路径，此虚边已有 `CMoveFleetOrderButton` vtable 证据。
- AI `CAIMilitaryMinister::MoveToTarget(CAIFleetGroup*) 0x27b43f0`：舰队组 `+0x48/+0x54` 给出舰队完整引用列表；比较实际舰速，选取协调移动的舰队，检查跃迁订单及 hyperlane windup。目标星系 ref 来自组 `+0x18`，经原生数据库 generation-check 后，在 `0x27b479b` 调用同一 `CalcMoveToPoint`，`0x27b47a8` 构造同一 MoveToSystemPoint Order。
- AI 在 `0x27b4819` 构造的是单舰队 **CQueueFleetOrderCommand**，显式传 Country、Fleet、owned Order、原生 queue enum 2；验证并于 `0x27b483e` 入 AI 队列。另一分支为原生 FollowFleet Order，不能混为坐标移动。
- 单舰队 Command 的 `IsValid 0x22e0330` 在 `0x22e03d9` 读取 Fleet controller ref，并与 Command Country 完整 ID 比较；不同 queue mode 还走不同 Order 可行性虚方法。

可复用的是显式星系/坐标解析、Order 构造和规则检查，不是 UI 按钮对象。完整 AI 方法还更新舰队组 status map，不能当纯查询。其战略目标如何首次产生、所有 pathfinding 与 Order 虚方法的传递约束未在本轮全部恢复；本报告不重新认定 queue 枚举的人类标签或所有移动模式。

证据：E `pass-01`、`pass-02`、`pass-03`、`pass-04` 与 vtable 切片。

### 4.5 外交/战争：双国家候选与原生领域规则

UI `CDiplomacyView::PostAction 0x2cbf990` clone 当前选定的 DiplomaticAction，再构造 `CDiploActionProposeCommand` 并 Post；该回调本身不是完整候选查询。`CWarGoalsView::Confirm 0x3392890` 还区分发起提议和设置防守战争目标，后者用不同 Command，不能统一为 DeclareWar。

AI `MakeAIDiplomaticAction(Country const*, CountryAI*) 0x27f6670`：

1. 从当前国家列表取得接收国，排除自己，解析完整引用；worker `0x2803d40` 调用 `GetDiplomacyModule::CanActWith`、`GetRelation`/`HasContact` 和本 AI 的 `IsAllowedToPropose(recipient, action_token)`。
2. `0x2803e99` 调用 `BuildProposalList 0x27f2b60`，参数为 **actor ref、recipient ref、action token、输出拥有型数组、随机输入、mutex**。普通分支用 `CreateEmptyAction 0x26465f0`，再通过虚槽 `+0xb0/+0xb8` 设置 Actor/Recipient；这两个槽在 base 和 DeclareWar vtable 中均解析为 `SetActor/SetRecipient`。
3. 特殊分支自行生成额外参数。例如 `0x27f33f5` 的 `NAIUtil::SelectWarGoalType 0x27e8d00` 调用 `NWarGoal::ListPotentialWarGoals 0x214b860`，对给定两国调用 `IsPotential`；随后逐候选执行 `CWarGoalType::IsPossible 0x214f8b0`，再算 `CalcAIWeight`。**候选、规则与偏好评分确实可分离。**
4. `ShouldProposeAction 0x27f0040` 还检查联邦 cooldown、先前拒绝、IsSelectable、ShouldAIPropose 和接受度。它会排除“游戏规则合法但 AI 不想做”的行动，不能把输出当完整合法集合。
5. 完整 Producer 等待任务、选择候选并移交所有权，在 `0x27f6d6c` 调用 scoped-ptr 版 `CDiploActionProposeCommand` 构造器 `0x22c7f10`，`0x27f6d7b` 调用 IsValid，copy 后 `0x27f6db5` 入 AI 队列。UI 有 raw-pointer 和 scoped-ptr 两种构造重载，不能仅因类名相同就假定 ABI 相同。

`CDiploActionProposeCommand::IsValid 0x22c80a0` 委托嵌套 Action 虚槽 `+0x60`，在 DeclareWar 中为 `IsProposable(bool, reason)`；不是统一检查所有外交参数的中央 switch。联盟、臣属协议、和平等分支还有各自原生对象生成过程。本轮保留完整 BuildProposalList，但未逐一证明其所有分支和所有虚边，不宣称全部外交操作已可调用。

这里存在显式双 Country 的领域 Producer，但完整 `MakeAIDiplomaticAction` 消耗 AI RNG、管理并行上下文并提交，**不是只读 API**。最小查询候选是 `ListPotentialWarGoals + IsPossible`，而不是直接调用整个外交 AI。

证据：E `pass-01`、`pass-03` 到 `pass-06` 与 vtable 切片。

## 5. UI / AI 复用与跨 Country 能力

| 领域 | 公共部分 | 私有上下文 / 差异 | 更合适的最小复用边界 |
| --- | --- | --- | --- |
| 科研 | 同一 Command 构造器、同一 CanQueueResearch | UI 选中科技与 observed Country；AI 的本国候选与 RNG 评分 | 指定国家的 CTechnologyStatus 候选及规则，再经现有 Builder |
| 建造 | Buildable 类型、队列规则、完整 BuildingType 规则 | UI 槽位选择；AI 本国殖民地、经济计划与预算 | FindBestBuildingSlot / CanAddBuilding，再用非 UI CreateAddBuildableCommand |
| 移动 | MoveToSystemPoint Order、坐标派生与 Order 规则 | UI 多舰队包装、modifier；AI 单舰队包装、group goal/状态 | 指定 Country + 合法 Fleet/目标解析，再构造原生 Order/Command |
| 月度市场 | 原生记录和 Add/Update/Remove Command | 参数组装 View 绑定 observed Country；所见 AI 路径为即时交易 | 既有订单用本国完整记录；新增订单复用已恢复的资源/define 计算，不伪造 View |
| 外交/战争 | nested Action、Propose Command、IsProposable、WarGoal 规则 | UI 当前 Action；AI cooldown、偏好、接受度与随机筛选 | 双 Country 的 potential/rule 查询，按行动选择原生参数生成函数 |

跨国隔离依据是 **对应国家的真实运行时对象与完整引用**，不是简单替换一个 country 整数。建造队列可能因外部所有权而不同；舰队控制国不一定等于简单 owner；科研候选属于具体国家状态；外交必须同时绑定 Actor/Recipient。

AI 自己的 SetOwner、cache、预算和模块生命周期不能随意移植。`PostCommandToSession(..., true)` 也不是 OGAS 的授权方案。未来仍必须保持 `Application -> Broker -> Runtime`、权限/快照检查及现有 `CGameIdler` 游戏线程队列；此报告没有改变它们。

## 6. 存档确定性与世界状态恢复

### 6.1 已恢复的上游链

```text
相同版本/有效定义/规则/存档及初始化条件
  -> CGameState::Load(CFile*, ...)            0x1b41b50
       -> 解压分支 ExtractFile，CTextLexer/CReader
       -> CReader::Read(CPersistent&)         0x42e8830
       -> CPersistent::Read                  0x42e4c10
            -> ReadWithoutInitPostRead       0x42e41b0
                 -> virtual +0x28 ReadMember
            -> virtual +0x30 InitPostRead
       -> CGameState::InitPostLoad            0x1b13f10
  -> 恢复后的国家/舰队/殖民地/队列与派生索引
  -> 本文的 UI / AI / 非 UI 原生查询
  -> 参数构造、再次规则检查、Command Producer
```

关键虚边已由 `CGameState` vtable 确认：`+0x20` 为 CPersistent::Read，`+0x28` 为 `CGameState::ReadMember 0x1b08ad0`，`+0x30` 为 `InitPostRead 0x1b0b180`。`ReadWithoutInitPostRead` 在 `0x42e4279` 以实际 token 调用 ReadMember；CPersistent::Read 在 `0x42e4c39` 调 InitPostRead。

`CGameState::ReadMember` 的国家数据库分支在 `0x1b0a3bb` 读取数据库，再于 `0x1b0a3ea` 调 `TPdxRefDatabase<CCountry>::BuildObjectListIfChanged`，目标为世界 `+0x540` 的 Country 数组，正是 ProcessAI 随后读取的 header/data/count 位置。原生 `CreateNewObject(unsigned id) 0x1bc5630` 以低 24 位定位 slot，在 `0x1bc581d` 把传入完整 ID 写入新 Country `+0x20`。本轮没有穷尽数据库 reader 调用该重载的所有分支，不能把这一点扩大为所有对象类型的加载证明。

可直接连到 Producer 的持久化实例：

| 持久化字段 | 恢复/序列化证据 | Producer 使用 |
| --- | --- | --- |
| Country `tech_status` | `CCountry::WriteMembers` 在 `0x2339ffb..0x233a00a` 以 token `0x2dfb` 写 `+0x15e0`；ReadMember 有同一子对象的读取分支 | 科研 AI 和 Research Command IsValid 都用 Country `+0x15e0` |
| Country `owned_planets` | `0x233b8fd` 写 `TPdxRef<CColony>` 数组，源 `+0x2690` | 建造 AI 按同一国家的殖民地列表选择目标 |
| Fleet `movement_manager`、已有 `current_order/order` | `CFleet::WriteMembers 0x291bc70` 与 `ReadMember 0x291c620`，movement manager 位于 `+0x508` | AI 移动检查已有订单/跃迁状态；恢复已有 Order 不等于产生一个新的 Queue Command |
| Colony `districts` 与 ConstructionQueue `owner/items` | `CColony::WriteMembers 0x285c010`、ReadMember `0x285cbd0`；队列 WriteMembers `0x2176870` / ReadMember `0x2176920` | 槽位遍历、国家队列解析和 CanAddItem |
| AI `random_seed/random_count` | `CCountryAI::WriteMembers 0x26f36f0` 有 token `0x3fc3/0x3fc4`；ReadMember 在 `0x26f4aab/0x26f521c` 写 `+0x330/+0x32c` | 科研等 AI Producer 消耗的随机输入属于可研究的状态依赖，不是不可解释的“随机性” |

以上是选定分支的证据。既有 serializer 索引仍是有限数据流恢复结果，某些复杂 writer/临时值 offset 未解或不适合作为内存布局；不能把全索引直接当作完整世界结构。

### 6.2 四类状态必须分开

1. **持久化状态**：上述对象、引用、队列、科技以及已有 RNG 读写分支。
2. **加载恢复的运行时对象**：原生数据库、对象分配和 full-ID 解析。跨进程指针地址不是其语义身份。
3. **加载后恢复/计算的状态**：`InitPostRead` 调 `UpdateDatabaseArrays 0x1b0b9c0`、Fleet/Country 等 `PostGameStateReadInit`，并生成地图；`InitPostLoad` 初始化 trigger/effect 数据库、执行 save fixes，再进行各对象 InitPostLoad。不能假设所有缓存字节相同，也不能省略这些初始化。
4. **额外输入和后续行为**：AI 显式 RNG、UI modifier/选中状态、加载回调、脚本、网络输入及之后的时间推进。原生 AI 的“选什么”不等于具体参数的“是否合法”。

这支持把固定存档作为确定性夹具的研究方向，**并未实测证明游戏全局完全确定**。在所有影响规则的状态与输入相同的条件下，应尝试重复取得同一语义规则结果；不能以未来事件有随机性来否定加载时持久化世界的可重复性，也不能仅凭同一 GameDate 认定完整状态相同。

存档加载器恢复对象和已有订单；本轮没有发现其为每种未来行动预生成完整 Command 列表的证据。更符合已有调用关系的是：**恢复世界后，UI/AI/领域函数按需产生候选与参数**。这不需要先等待网络 Command 历史。

证据：E `pass-05` 到 `pass-08`、`static-metadata-01`。未重新加载任何当前存档。

### 6.3 未来 Deterministic Fixture 方案，尚未执行

在另行授权的干净基准世界中，固定精确二进制、有效 Mod 内容与加载顺序、规则和原始存档 hash，等待加载初始化完成且时间不推进。记录 Country/目标的语义身份与完整引用、具体 action 输入、queue mode、必要显式随机输入；分别测试：

- 原生对象与候选查询；同时保留原始遍历顺序和规范化语义集合，避免排序隐藏影响 AI 随机选择的顺序差异。
- 原生规则、Producer 输出和最终 Command IsValid；构造后正常析构，不默认提交。
- 在独立、相同基准状态重复，比较语义参数、定义 key、对象关系和结果，不比较 ASLR 指针或 vptr 数值。
- 记录调用前后 GameDate、相关规则状态、RNG 和对象身份；检查查询是否发生可观察的状态变更。

若结果不同，先检查隐含加载回调、缺失规则/Mod 输入、未纳入的 RNG、UI/网络行动、初始化时机及迭代顺序；再研究真正非确定性。两次 IsValid true 也不能证明执行或同步。当前运行中的长期世界不被重载、暂停或当作“相同存档已复现”的替代品。

## 7. OGAS 最小后续路径

优先级保持为：

1. **直接复用已经恢复的非 UI Producer**：先做建造的槽位查询与 `CreateAddBuildableCommand`。先验证返回 ABI、拥有型嵌套对象及原生 copy/clone/析构，不手工复制 vptr 或 scoped pointer。
2. **复用候选/规则，再用现有 Builder**：本国科研状态 + CanQueueResearch；显式双 Country 的 WarGoal potential/possible；原生市场整记录/数量计算；舰队目标派生和控制国检查。
3. **确无适用原生机制时才继续字段恢复**：复杂协议条款、未解 Order 或未完成的私有上下文，不因为难追踪就让全部 351 项退回随机字段枚举。

本报告静态研究时点的 `NativeCommandBuilder` 负责 Factory、类型化填充、IsValid、释放与析构，但没有公开的任意 Producer 返回对象接管接口。直接返回含 owning pointer 的 Command 不能用 memcpy 塞入它，更不能重复析构。后续按这一边界加入了受限、精确 ABI 的就地 Producer 构造，见第 10 节；没有建立第二套命令布局或执行器。

候选必须绑定同一个 world、快照和明确国家；离开游戏线程后优先返回稳定语义事实，不长期缓存 native 指针。上层模型只选择已审查候选，不接收任意 native ID、队列地址或 raw target。Broker 的权限、资源 reservation、串行副作用和后置确认全部保留。

本轮未修改 Broker、生产 Action、生成 consumer header、SDK 准入级别或当前 Runtime。`native_producer_recovered` 仅为本文的研究分类，未增加新的生产状态枚举。

## 8. 验证目标与授权边界

| 目标 | 最小下一步实验 | 不能由此推导 |
| --- | --- | --- |
| 参数正确 | 固定夹具中，对比原生领域查询、语义对象身份与同目标 UI/AI 的参数来源；无 Post | 候选全集完整、可执行或跨国授权 |
| 原生构造正确 | 在既有游戏线程队列调用指定 Producer 或现有 Builder，检查类型、关键字段、clone/析构配对与无泄漏 | IsValid 或业务成功 |
| 原生合法性 | 同一世界/国家/输入下调用最终 IsValid，分别记录 AI 来源上下文；原生规则 false 不是结构失败 | true 即成功提交或游戏效果 |
| 实际执行 | **另获可丢弃会话和显式提交授权后**，单个已审查请求走既有 Broker/Post，查询原生结果与存档后置条件 | 联机身份与同步无误 |
| 多帝国与同步 | 先单机/host 上两个明确授权国家，核对对象归属、actor/controller、无跨国候选污染；之后另做有授权参与者的 host/client 对照 | 从 force bool、AI flag 或一个国家成功推导任意客户端权限 |

潜在风险包括脚本查询消耗随机数/缓存、错误 sret/所有权导致崩溃、AI 计划/预算被隐式修改，以及主线程工作量。完整 AI Update、UnlockTechnologies、CreateBuildPlan、MakeAIDiplomaticAction、所有点击回调均排除在未经单独审查的“只读调用”白名单之外。研究需要侵入式调用时先取授权，不将当前进程拿来试错。

尚缺：UI 候选菜单的所有生成路径、科研候选刷新完整依赖、AI 战略目标生成、外交所有特殊分支及未知虚边、各查询传递副作用、Windows Producer ABI、实际执行与 host/client 权限。这里没有把未知归因于“缺网络捕获”，也没有为这些缺口降低安全要求。

后续离线实现及统一实机窗口清单见 [Producer 验收准备](PRODUCER_VALIDATION_WINDOW_4_5_2.md)。初稿时尚未调用实机查询；后续获准验收的增量证据独立记录于第 10 节，不自动改变本文其他静态结论或生产准入。

## 9. 工具、复现与测试

新增离线工具 `services/stellaris_native_runtime/research/discover_command_producers.py` 复用现有 ELF 解析器及指令边界核验器。只打开本地 ELF/SDK；精确身份不符时拒绝，输出目录必须不存在；明确记录缺失的请求 RVA、未解间接调用和间接跳转。原始 scanner 的 `constructor_rva` 字段在此表示所选 xref 目标，也可能是普通函数，并不保证是构造器。

示例，输出请用新的目录名：

```powershell
python services/stellaris_native_runtime/research/discover_command_producers.py `
  --linux-binary .tmp/sdk-recovery/stellaris-linux `
  --sdk .tmp/sdk-recovery/incremental-offline-33-20261019T2337Z/linux_sdk.json `
  --output .runtime-evidence/producer-reproduction-new `
  --inventory-pattern 'CCountryAI|CAIInterior|NConstruction|NPlanetBuildingUtil' `
  --function-pattern 'CCountryAI::(GetCountry|AddAICommandForPosting|PostAICommandsToSession)|NConstruction::CreateAddBuildableCommand|NPlanetBuildingUtil::FindBestBuildingSlot'
```

选择先经过 raw symbol pattern，再匹配 demangled function pattern；需要精确函数可传 `--function-rva 0x...`。直接 E8 xref 扫描可用 `--xref-pattern`，其范围不包括内联、所有 tail-call 或间接调用。`pass-03` 起保存完整选择参数和缺失地址诊断；早期曾请求的 `0x3ca8380` 并非独立函数入口，未进入任何函数证据，实际 dispatcher 为 `0x3ca8300`。

E 中 `collect_world_metadata.py` 可重新导出 vtable 和既有 serializer 元数据；`audit_archive.py` 可重新比对八轮归档与精确 ELF，选择 `--run-tests` 归档测试结果。两者均只生成新的输出目录，不操作游戏。归档中的字节不是新二进制或可注入 Probe。

本轮新增七项 fixture 测试：直接/外部跳转与内部 CFG 区别、间接边保留、RIP 数据引用、截断/不可解码边界、原始字节/hash、缺失 RVA、输出不可覆盖和错版本拒绝。维护测试入口：

```powershell
python scripts/validation/run_tests.py --quiet
```

**524 项维护测试通过**，包括本轮七项。测试是离线/模拟对象验证；本文引用的既有验收基线为 309 构造、154 IsValid、87 曾 true，本轮不增加这些实机覆盖。运行中增量观察器的独立新结果以其 journal 为准。没有新增 `paired_capture` 或 `live_verified`。

## 10. 后续原生参数路径实机验证

2026-10-20，在用户批准的新 Linux 4.5.2 可丢弃会话中，三个领域参数路径通过同一个已恢复 SDK、共享 `NativeCommandBuilder` 和既有 CGameIdler 队列，完成两轮有界 `Create/Populate/IsValid/Destroy`。没有等待 UI/AI 先提交 Command，也没有通过完整 AI Update、Command 历史或网络 payload 生成候选。

- 开始科研：从 Country 0 的实际 alternatives 获取 16 个候选；两轮 32 次最终 IsValid 均 false，与所用 CanQueueResearch 前置查询一致。保留正在研究、科技条件等原生提示，不将状态拒绝判为布局失败。
- 取消科研：从同一国家的两个现有研究任务解析科技；两轮 4 次均 true，没有真正取消任务。
- 普通新建筑：从原生 Country/Colony/District/Zone 和有效 BuildingType 数据库取得关系，再由 FindBestBuildingSlot 与 CreateAddBuildableCommand 在游戏 Factory 分配中构造；两轮共 16 次，`building_clone_vats` 的同一语义候选各一次 true，其余 14 次 false。该 owning Buildable 路径的 Factory、外层/内层类型与对象身份检查、最终 IsValid 和删除析构均正常返回。

52 次请求与 52 次 Command 构造/析构完整配对；两个轮次的有序语义输入、前置规则、最终结果、原生原因文本相同，世界/日期/Runtime 身份保持一致。更新参数仍是 `Idle(true)`，实际暂停由精确原生 idler 状态独立确认；修正的研究协议为 revision 5。

这些结果证明原生世界状态和领域规则可直接提供可构造的关联参数，其中两个路径取得正向合法性证据。但候选扫描被截断，不证明完整合法集合、任意国家生产权限、传递脚本完全无缓存/RNG 副作用，亦不证明独立重载存档确定性。没有 Post/Execute、实际执行后置条件或多人同步实验，不提升 `paired_capture` / `live_verified`。Windows 领域 ABI 仍未恢复，不宣告对应 provider。

完整逐候选报告、初次暂停条件回归及修正过程、累计覆盖和证据目录见 [Producer / SDK 定向实机验收](PRODUCER_VALIDATION_ACCEPTANCE_4_5_2.md)。本次后续构建的离线维护测试为 548 项，和上文静态研究阶段的 524 项分别保留。

## 11. 后续脚本与硬编码约束流水线

2026-10-20 后续离线实现将社区脚本解析、精确 ELF 调用/拒绝分支/短谓词恢复、
既有 SDK/Producer 字段证据和冻结存档对象合并到同一个有界候选生成器。
全目录 351 项均有结果，135 种生成完整类型化候选；这不是新增实机覆盖或生产准入。
未来原生验证复用现有 CGameIdler、Builder、IsValid 和析构路径，仅扩展受限研究请求，
本轮未连接或修改游戏进程，未自动提交命令。

当前脚本与原生条件仍是部分模型；未证明的参数绑定、原生判断和 Mod 有效状态保留 UNKNOWN。
完整方法、覆盖数、反馈限制、离线/未来窗口入口与证据路径见
[Script / Native 候选约束流水线](SCRIPT_NATIVE_CONSTRAINT_PIPELINE_4_5_2.md)。

## 12. 后续参数来源与构造能力审计

全目录 351 项已经重新审计，不能将旧候选生成器的缺参诊断直接作为构造失败。
陆军名称属于调用者输入；风暴引用在冻结存档中因 nested manager 漏读而丢失，现已修正；
国家内项目 ID 已有原生查询，应等待当前状态而非重复恢复 resolver。
同一原生类型的多个定义池、serializer 临时投影、owning record 与普通引用数组也分别处理。
共享恢复、所有 351 项字段来源/调用点/未闭合证据，以及旧 216 项的分类迁移详见
[Command 语义与技术审计](COMMAND_SEMANTIC_TECHNICAL_AUDIT_4_5_2.md)。
这些是离线结构与语义证据，不改变本文件第 10 节的实机验收数量，不新增生产 Action 或实机准入。
