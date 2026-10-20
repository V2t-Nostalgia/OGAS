# Script、原生约束与 Producer 候选流水线（4.5.2）

> Publication: original/local evidence paths below are provenance labels, not Git downloads. Use the [indexed archive and access status](../research/EVIDENCE_ARCHIVE.md); public copies may be privacy-redacted and originals remain retained.


日期：2026-10-20 UTC。范围：离线开发、真实 ELF/规则/冻结存档分析、模拟验证。
**未连接 SSH/游戏 Runtime，未读取游戏进程，未注入，未调用真实游戏 IsValid/Post/Execute。**
旧存档、SDK、checkpoint、验证记录、生产 Action 和 Broker 准入均保留。

## 1. 已交付的机制

入口是 `services/stellaris_native_runtime/tools/plan_script_candidates.py`，不是
一组按 Command 手写的适配器。它遍历 SDK 的完整目录，复用原来的 ELF 索引、
调用点字面量恢复、serializer、WorldStateIndex 和 NativeCommandBuilder。

```text
精确 SDK / ELF / Token Registry
    -> 原生调用图、局部 Order 虚调用、载荷拒绝分支、短谓词
Paradox Script -> CWTools 有序 AST -> 三值规则模型
冻结存档 -> 类型化对象事实、完整 generation ID、已知对象关系
Producer / 枚举证据 -> 受约束的参数域
    -> 有界、证据排序的候选 -> 原生研究验证队列 -> 反馈 / 共享恢复工作表
```

这是“约束辅助的部分候选生成器”，**不是完整的 Stellaris 规则引擎或合法集合求解器**。
未知条件不填默认真值；枚举、指针、对象 ID、字符串也不使用随机值补齐。
候选的总体 `script_result` 保持 `unknown`，即使已知部分规则通过。

## 2. 完整目录实际覆盖

规范证据目录：
`.runtime-evidence/script-candidates-4.5.2-20261020-01/pass-07/`。
阶段目录 `pass-01` 到 `pass-06` 和失败/成功构建记录全部保留，不替换旧结果。

| 实测离线指标 | 数量 / 含义 |
| --- | --- |
| SDK Command 盘点 | 351，全部有结果行 |
| Factory/VTable/Size/IsValid/析构地址存在 | 351；只是元数据存在，不代表全部结构或生命周期已验证 |
| 完整 population layout | 241，沿用现有 SDK 的保守判断 |
| 发现的 CGameRules 包装器 | 159，确认调用 ScriptedRule Evaluate；规则名由精确符号规范化对应，注册 Token 尚未完全追到 |
| Command 可达脚本规则路径 | 26，路径可达不等于必需前置条件 |
| 可作唯一类型作用域线索 | 3：hire_and_assign_leader、initiate_cosmic_storm_command、shroud_delve |
| 有 Producer 字段证据 | 203，不代表 203 个 Producer 已可安全调用 |
| 有原生载荷比较线索 | 15；不把未证明的比较当作约束 |
| 有保守证明拒绝守卫 | 4 种 Command；本夹具候选实际由这些守卫剪除 0 个，不能宣称已经节省大量调用 |
| serializer/枚举交叉确认的短原生谓词 | 1，共用于 4 种 Command 的排序 |
| 生成完整类型化候选 | 135 种，共 2,076 个候选 |
| 剩余未生成完整候选 | 216 种；原因逐项保留，可重叠 |
| 当前新增真实游戏合法性调用 / 执行 | 0 / 0 |
| 新增 paired_capture / live_verified / 生产 Action | 0 / 0 / 0 |

主要阻碍包括 110 项 population layout 不完整、56 项静态生命周期安全性未确认，
以及 scoped ID、非平凡 owning 对象、自由文本、特殊场景、缺少参数语义等。
不能把这些数相加；同一 Command 可有多个阻碍。它们不是被静默跳过：
`recovery_worklist.json` 按共享缺口和证据 RVA 聚合，后续恢复一类能力即可重跑受影响目录。

定义索引覆盖本机所选 330 个文件，39 类定义来源映射；1 个错误来自非脚本的
`99_README_EDICTS.txt`，按解析错误保留。冻结存档读出 9,959 个对象事实，
默认每类型最多解析 512 个，报告保留完整可用数量和截断标记。

这不是此前 310 构造 / 174 原生 IsValid / 105 曾 true 的覆盖替代品。
本轮离线候选数与历史实机覆盖衡量的是不同层次，不能相加或据此降低已有状态。

## 3. 风暴切入点：没有专用 Command 逻辑

索引自动追出：

```text
CInitiateCosmicStormCommand::IsValid                     0x22e8ca0
  -> 栈上构造 CInitiateCosmicStormFleetOrder             0x29d95b0
  -> 从该对象 vtable +0xa8 恢复 IsPossible               0x29d9920
     -> IsPossible_CheckFleet                           0x29d9cc0
        -> CGameRules::CanCountryInitiateStorm           0x1ae5f50
     -> CGameRules::CanInitiateStormOnPlanet             0x1ae60b0
```

地址是精确 ELF 的静态地址/偏移证据，不是一次运行的绝对 Hook 接口。
绑定 ELF Build ID：`121ecb516cbc5f1d39917fbcc36620534384e2c2`。
原生规则包括控制国飞升能力、恒星目标、轨道中的启动状态、星系风暴标记；
还存在 DLC、移动能力和其他硬编码判断，脚本不覆盖全部条件。

原生短谓词通用识别器另外恢复：

- `CFleet::IsShipClass(EShipClass)`：`0x2931730`，三条指令的只读字段比较。
- 该字段与 `CFleet::WriteMembers` 在相同偏移的 `ship_class` 写出关联。
- `GetShipClassTokenFromEnum` 的边界检查、Token 表与返回路径共同把参数 3 映射为
  `shipclass_science_ship`，没有在生成器中手写“风暴必须选科研船”。
- 同一恢复机制适用于 active_reconnaissance、survey_planet_order、initiate_cosmic_storm、
  sustain_cosmic_storm 四种 Command。
- queue_mode 优先值 2 来自已有 UI Producer 调用点，域仍取 SDK 恢复的枚举，而非猜测。

在本次冻结夹具中，首选由独立枚举池变成科研船 Fleet 12、恒星 Planet 0、queue_mode 2。
这些 ID 只属于这份存档，不是通用常量或可复用到当前进程的目标。
规则与原生谓词的唯一类型关联仍标为 advisory / UNKNOWN，不会错误删除其他路径候选。
控制国绑定、动态 flag/轨道集合等尚未完整恢复，**不宣称这个候选一定合法，更未宣称执行成功**。

## 4. 三种约束证据如何合并

**脚本**：CWTools 保留重复字段、比较符、匿名值、引号和位置。部分求值器支持
AND/OR/NOR/NAND、单子句 NOT、tooltip 包装、if/else 链、有限脚本 trigger、已知作用域
和集合量词。缺集合、动态 `@root` flag、参数化 trigger、未知枚举/分支/默认值均 UNKNOWN。
未知条件即使出现在 NOT 下也不会变成 true。技术记录按 technology/level 成对解释。

**原生**：调用图保留未解虚边和预算。只对匹配安全形状的谓词/枚举建立摘要；
载荷守卫同时要求拒绝分支及绕开检查的返回路径均可证明为零。
隐式寄存器写、部分写、opaque call、潜在载荷写不能被误当作初始参数事实。
这里只恢复相等/不等的保守子集，没有把任意 C++ 代码“翻译成游戏规则”。

**Producer / 状态**：复用已恢复构造参数及调用点字面量、原生枚举域、对象引用和外部
定义 key。无证据的 scalar、时间、字符串和复杂对象不随意取 0/1。best-first 搜索只展开
有界域，不先展开巨大 Cartesian product；所有域截断和搜索截断可见。

生产 Action 不导入这些私有布局。既有 non-UI Native Producer 路径继续存在，
本工具未重写普通建造 owning Buildable、科研领域查询或原生执行链。

## 5. 原生校验与反馈闭环

`validate_constraint_candidates.py` 默认只检查离线计划。显式 `--native` 才使用未来的
revision-6 Runtime（i64 字段要求 revision 7）；它没有 loader、注入、重启、暂停、换档或游戏命令提交能力。

现有 `validate_recovered_command` 研究请求新增受限 `constraint_plan` 选择方式，
仍在同一个 CGameIdler 队列调用同一个 NativeCommandBuilder。未创建并行 Runtime、
执行队列、MCP Server、Action API 或另一套 Command 布局。

每次请求重新核对 Runtime instance、world、GameDate、暂停状态、SDK 指纹、字段名称/
类型/完整性、enum domain、完整 generation 引用和生命周期。客户端不发送字段 offset
或任意 native pointer；32 位非枚举 scalar、未支持的 owning 类型仍直接拒绝。
已恢复的类型化 i64 坐标走 SDK 宽度/边界检查和 SetSigned，不扩大为 raw 写入。实际填充值必须
与返回的类型化 bindings 一致。现有生产路径的 update gate 保持不变。

调度器按排序连续尝试：正常 false 继续下一个候选，true 结束该 Command 的覆盖回合。
异常、超时不明、世界改变或不再暂停则停止原生批次；保留 started/completed journal，
不重放 pending 请求。缺参/不支持可以保留原因后继续其他 Command。

反馈区分历史观察和可复用的精确夹具证据。此次导入 104 种 Command 的 1,002 条旧观察，
其中 983 条有原生布尔结果；因其世界/内容/存档绑定不足，可跨到本夹具复用的数量为 0。
拒绝只排除有充分状态证据的同一输入，不从本地化错误文本臆造普遍规则。
相同完整夹具结果矛盾时会撤销缓存并报告缺少依赖，不投票“学出真值”。

world/date 相同仍不等于所有 paused UI 输入、RNG、初始化缓存完全相同。
实际批测报告明确保留这一限制，不将时间关联或 IsValid true 冒充 paired_capture。

## 6. 工具选择与诚实边界

[CWTools](https://github.com/cwtools/cwtools/wiki/Overview) 适合解析、作用域/定义信息；
[Jomini](https://github.com/rakaly/jomini) 提供高效低层 Clausewitz 解析。
两者都不是完整运行时合法性求解器。本机已有 .NET 而没有 Rust 工具链，因此先接 CWTools，
没有重新写一个通用脚本语法解析器。NuGet 警告、版本锁、许可和词法修正见工具 README。

[Ghidra HighFunction / p-code](https://ghidra.re/ghidra_docs/api/ghidra/program/model/pcode/HighFunction.html)
适合后续为复杂参数流提供 SSA/类型和 CFG 证据。本轮未运行 Ghidra，也不把手写的保守
子集称作完整反编译器。报告的共享缺口/RVA 可作为后续定向分析输入。

[angr 的官方限制说明](https://docs.angr.io/en/stable/advanced-topics/gotchas.html)
指出函数摘要精度和路径膨胀问题。对大量依赖 native World State 的 IsValid，不应通过
伪造外部函数返回值或未初始化内存来“求出合法参数”。本轮没有运行完整符号执行，
更没有把未建模状态当作可自由选择的 SMT 变量。

冻结夹具为历史 `2384.01.25.sav`，版本 Cygnus v4.5.2，含 9 条 Mod 元数据；
其记录顺序不冒称当前 launcher 实际加载顺序。当前索引的本机外部文件与这些 Mod 的
有效加载数据库尚未对齐，因此脚本结果只作排序证据，不作权威硬剪枝。

## 7. 验证与下一窗口

维护测试命令：`python scripts/validation/run_tests.py --quiet`。
设置 `IAG_CWTOOLS_BRIDGE` 可一并运行实际社区解析器集成测试；未设置时这些可选测试跳过。
本轮最终 595 项通过，新增 47 项；日志独立归档于同级证据目录。

Windows `/W4 /WX` 构建通过，Builder / Producer / Action contract 三个 C++ 离线夹具通过，
Runtime DLL 已离线编译但未加载。本轮未连接 Ubuntu，因此 **Linux 新二进制未重建/实测**。
Windows 的已验证暂停查询仍缺失，此新研究模式在那里失败关闭，不能因编译通过就宣告实机可用。

离线 native-plan 编码预检覆盖 135 种 / 2,076 份计划，但不是 Native IsValid 验收。
未来授权窗口应使用精确 SDK 重新构建的 Linux revision-7 Runtime、一次干净加载/注入，
取得新鲜 instance/world/date 后运行同一批处理入口，不需要逐条手工点击或找 ID。
当前已加载 Runtime 不能热替换，不会为本任务主动重启或重新注入它。

复现命令、产物含义、安全阈值、内容层格式和未来原生入口详见
[工具说明](../../services/stellaris_native_runtime/tools/script_candidates/README.md)。

## 8. 后续全目录语义与技术审计

上文 135 种 / 2,076 候选和 595 测试属于旧 pass-07 阶段，不应将当时 216 项无候选全部理解为 ABI 缺失。
2026-10-20 后续审计已独立区分调用者输入、运行时引用、已有原生查询、内部身份、参数绑定和真实
布局/生命周期问题。共享恢复及对象索引修正后，最终离线结果为 265 份完整命名 layout、
162 种 / 2,484 候选、638 项测试通过；所有 351 项均有逐字段审计。
258 项的“提供类型化输入即可构造”不等于 258 个生产 Action，也不表示满足游戏规则。
具体互斥分类、原先 216 项迁移、实例纠错及精确证据入口见
[Command 语义与技术审计](COMMAND_SEMANTIC_TECHNICAL_AUDIT_4_5_2.md)。
本次后续阶段零原生调用、零准入提升，未改当前 Runtime 或生产 Action。
