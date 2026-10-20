# Command 语义与技术审计：4.5.2

> Publication: original/local evidence paths below are provenance labels, not Git downloads. Use the [indexed archive and access status](../research/EVIDENCE_ARCHIVE.md); public copies may be privacy-redacted and originals remain retained.


日期：2026-10-20。范围：Linux SDK 全目录 351 项，重点复核此前没有候选的 216 项。
本轮完全离线，只读取精确 ELF、已有报告、历史存档及本机游戏文件；没有 SSH、进程访问、
注入、原生函数调用或生产 Action 修改。既有实机证据及所有旧轮次原样保留。

## 1. 证据入口

最终轮次：`.runtime-evidence/semantic-audit-4.5.2-20261020-01/pass-05/`。

- [全目录结构化审计](../research/EVIDENCE_ARCHIVE.md)：351 项的每个字段来源、类型、setter、缺口、Factory/IsValid/Execute/析构邻域、Producer、尝试过的恢复路径和证据 RVA。
- [351 项可读表](../research/EVIDENCE_ARCHIVE.md)：逐项主分类、输入构造能力、冻结夹具计划数和字段要求。
- [候选报告](../research/EVIDENCE_ARCHIVE.md)：有界候选、脚本/原生约束、历史反馈，以及与技术阻碍分开的候选搜索诊断。
- [共享恢复清单](../research/EVIDENCE_ARCHIVE.md)：55 组共享能力/参数要求、受影响 Command 和精确 RVA，不是逐命令适配清单。
- [最终一致性与测试记录](../research/EVIDENCE_ARCHIVE.md)：SDK 指纹、35 份代码快照核对、425 份本地脚本/GUI/本地化来源归档、测试及零原生调用声明。

精确 Linux ELF Build ID：`121ecb516cbc5f1d39917fbcc36620534384e2c2`。
SHA-256：`1c4c79a0ef8af7b984b797606373eb68b60fe421e4ef54c20e12e4a9398ba86b`。
最终研究 SDK 指纹：`bb16dce09bb1d6c6c194d4b5efc4ab851cd9bced8e9900b950a641d587732fb5`。

冻结存档为 `2384.01.25.sav`，SHA-256
`c5cfa0fce3e434a704a0a7bebaaa0a7c9c4f956376ee1334a96d4f481c6c39e2`。
存档含 9 条 Mod 元数据；本机外部基础文件不等于这个世界的实际有效 Mod 定义数据库。
本文的“存在对象”只指历史夹具，不是当前游戏，也不证明对象归属、操作可用或游戏规则成立。

## 2. 分类修正

不再将 `candidate_domain_missing`、未采集到自然命令、没有自由文本、缺少特定场景统一视为 ABI 失败。
每个参数分别记录来源、内存表示、Builder setter、候选供应和证据：

| 来源 | 含义 | 不能替代的工作 |
| --- | --- | --- |
| `caller_input` | 原生构造/复制或真实编辑对话框证明是调用者文本等输入 | 调用者提供值；不能用历史名称充当默认值 |
| `game_object_reference` | `TPdxRef<T>` 或其有序列表 | 当前世界解析完整 generation、归属及列表选择 |
| `game_definition_choice` | 原生静态定义对象 | 有效定义库和正确参数池绑定，不是自由字符串 |
| `engine_generated_context` | 国家内 record ID、human slot、关联交易字段、原生日期等 | 复用正确原生查询或恢复其身份关系 |
| `native_enum_choice` / `native_scalar_candidate_domain` | 有证据的枚举或普通标量域 | 枚举、数量和完整合法性不是同一概念 |
| `parameter_binding_not_yet_recovered` | 存储可以已知，但生产/消费关系仍未绑定 | 沿记录的函数、调用点、脚本来源继续恢复，不猜取 0/1 |

**主分类互斥，合计 351；另外保留可重叠的独立维度。** 不用一张互斥表掩盖同一命令的多个要求。

| 当前主分类 | 全部 351 | 原先无候选的 216 |
| --- | ---: | ---: |
| 已有类型化输入路径和夹具参数，或已证明空 payload | 159 | 29 |
| 等待调用者参数 | 20 | 20 |
| 等待已有原生状态 provider 查询 | 7 | 7 |
| 尚缺引擎内部参数/身份绑定 | 8 | 8 |
| 尚缺语义参数、参数池或 serializer 到成员绑定 | 38 | 38 |
| 真正存在布局、赋值或生命周期缺口 | 77 | 77 |
| 根据原生用途暂缓的非核心命令 | 42 | 37 |
| **合计** | **351** | **216** |

独立维度，**不可相加**：

- 258 项已有可写字段、Builder setter 和生命周期 gate，提供正确类型化输入即可构造。
  其中仍可能缺语义绑定、当前对象或调用者输入，也包含非核心命令；不是 258 个新生产 Action。
- 28 项包含调用者输入要求；20 项以此作为首要待办。
- 92 项有技术缺口，其中 77 项为核心主分类，其余与非核心暂缓重叠。
- 34 项有尚缺的引擎参数绑定；10 项涉及已存在的状态 provider，其中 7 项为主分类。
- 137 项仍有某种语义参数绑定要求；6 项存在状态发现/解析能力缺口。
- 此夹具中，能够证明“所需对象确实不存在”的数量为 0。这个数字不表示所有场景或合法性已满足。
  例如未知 collection 不会被当成空表；未完整建模的外交、事件或其他规则也不会凭对象存在就变为 true。

非核心 42 项按真实 native 子系统/方法、类型引用和 Producer 归类，覆盖大厅、设置、聊天、
文件传输、热加入、同步、镜头 presence、控制者分配和诊断作弊。仅调用 CSession 不足以排除；
`pausegame` 调用 `CInGameIdler::SetPaused`，仍保留为运行时命令。没有根据名字含 lobby/chat 就自动排除。
证据不充分的用途不强行归类，仍可出现在待绑定清单。

## 3. 亲自复核的反例

**陆军改名**：`change_army_name_command.name` 是调用者提供的 `CPersistentName`，不是需要从世界寻找的对象。
原生文本复制构造、`CArmyRenameDialog::DoRename`、原版 `rename_dialog.gui` 的编辑框及英文重命名
Localization 共同解释用途；ABI 仍由原生证据确认。已有精确版本历史记录已成功填充文本并配对析构。
现归入等待调用者参数，技术缺口为空；不会为提高候选数自动捏造名字。

**风暴对象**：`activate_cosmic_storm_command` 的 `CCosmicStorm` 是运行时对象引用，不是静态风暴类型。
修正嵌套 manager 存档索引后，这份夹具实际包含 4 个对象，现生成 4 个引用候选。
`CCosmicStormManager` 的 native ref-database base、序列化 token 和 `storms/storms` 集合相互核对。
历史配对记录仅复用生命周期证据，不复用旧 true 的合法性或跨世界 ID。

**国家内 ID**：`cancel_project_command` 等 7 项所需 ID 由现有 SDK Probe 的
`ScopedBindingFor` / `EnumerateScoped` 提供。缺少的是未来当前世界查询，不是新的对象布局或 resolver。
原生日期同样保留已有查询来源，不从日历文本猜测 packed uint32。

**传统与飞升**：两者原生参数都可能使用 `CTraditionType`，但静态数据库存在多个池。
此前类型名匹配甚至可能把飞升 key 放进传统命令。现在保留 native pool 的地址与 Producer 绑定缺口，
不因对象类型相同就混用，不将规则拒绝判为 ABI 失败。

**文本不全是自由文本**：法令、议程、遗珍、trait 的 CString 可以承载定义 key。
原生 `CCountry::AddEdict(CEdict const*)` / `RemoveEdict` 等和游戏定义能解释机制，但将这些 lookup
关系自动绑定回具体字符串字段仍有缺口。当前按参数绑定工作处理，不能套用改名的 caller-text 规则。

**战争数组的两个不同缺口**：

- `prepare_war_command` 的 native `CPdxArray<TPdxRef<CCountry>, int>` 成员在 `+40`；Execute 将其交给
  `CCountryAI::AddExtraAttackers`。物理区域已恢复，serializer 通过临时投影写出，尚未证明命名 token
  与此成员的直接填充关系。因此记为参数绑定缺口，不宣称 ABI 未知，也不发出危险可写别名。
- `diplo_action_start_proxy_war_command.attackers` 是 `CPdxArray<NWar::SWarAttendantData, int>`，
  同样位于 `+40`，但不是简单国家引用数组。已恢复 record writer RVA `34938640`、国家引用 `+8`
  和 owning persistent 字段 `+16`；元素大小、完整构造/赋值/释放仍未闭合，属于真正复杂值能力缺口。

## 4. 实际工具修改与恢复增量

沿用 `NativeCommandBuilder`、SDK Generator、CWTools 和既有候选管线，没有新增执行框架或命令布局副本。

1. `sdk_recovery/value_recovery.py` 批量恢复 normal CFG、构造复制参数、inline CString 初始状态、
   CFixedPoint 存储及生命周期。只排除不可达 EH 清理区，不跳过真实分支；不明调用继续阻止安全 gate。
2. `linux_elf.py` 根据编码函数签名和实际 load width 恢复按值枚举；不把带隐藏 this 的普通方法当静态转换器。
   对已有输出文件提前拒绝，避免覆盖旧 SDK。
3. `sdk_recovery/array_recovery.py` 用 CFG 合并的参数位置来源追踪 data/count、寄存器破坏、空数组分支、
   原生数组类型与元素 serializer。只证明位置关系，不声称输入值不变、函数无副作用或结果可缓存。
4. `semantic_audit.py` 提供 strict/frozen 字段契约、互斥主分类与独立能力维度。vtable 选择真实执行函数，
   记录成员到 callee 的参数流，而非按 Command 英文名猜测用途。
5. `snapshot.py` 支持 nested manager、数字索引/计数器消歧和精确原生 collection selector。
   保留完整 generation；每类型最多解析 512 项，实际数量与截断独立记录。
6. `planner.py` 不再将 inline script / scripted effect / scripted trigger 当静态定义数据库，
   优先匹配完整原生类型，修正 councilor 的真实定义目录。仍不捏造未知字符串、标量或对象。
7. 现有 `plan_script_candidates.py` 增加共享恢复、历史生命周期、语义审计和游戏来源搜索参数。
   `candidate_generation_diagnostics` 与真正 `blockers` 分开；原始诊断没有删除。

本轮可重现结果：

| 指标 | 旧 pass-07 | 本轮最终 pass-05 |
| --- | ---: | ---: |
| 全目录 | 351 | 351 |
| 完整命名 population layout | 241 | 265 |
| 生成完整夹具候选的 Command | 135 | 162 |
| 有界候选总数 | 2,076 | 2,484 |

共享恢复新增：45 个 CFixedPoint 存储字段、18 个 inline CString 字段、9 个按值枚举字段，
17 项额外生命周期 gate。最终 gate 总数为 312，包含静态及精确历史配对证据，**不是本轮执行了 312 次原生构造**。
CFixedPoint 的 64 位存储不等于其语义单位已经恢复；未知换算与参数来源仍阻止自动生成候选。

数组分析有可运行通用实现及反例测试，但真实目录新增安全 reference-array 字段数为 **0**。
本轮的实际收益是识别临时投影与 owning record 两类不同阻碍，不能把测试 fixture 的成功算成游戏覆盖。

修正对象索引后，夹具中明确解析出 4 风暴、62 局势、120 议会职位、343 首次接触、52 考古站点、
4 谍报行动、4 协议、106 星界裂隙等对象；人口组可用 2,234 项，按 512 上限解析。
星界裂隙、风暴、灵能光环的 collection binding 来自 native manager 的 typed database base 与持久字段。
`CContract` 等不明 collection 保留解析缺口；1 个 Exhibit 解析错误单独记录，不被伪装为场景不存在。

## 5. 尚未解决的共享问题与已尝试路径

每项剩余 Command 都保留 exact ELF 函数/调用点、字段/对象来源、存档索引和规则查询五类尝试记录。
对于字段来源未闭合的命令，报告不会把原生规则当成自由选择的变量，也没有从名字生成参数。

| 剩余共享问题 | 本轮已经尝试、取得的证据 | 具体未闭合部分 |
| --- | --- | --- |
| owning record / container | native Factory、数组 vptr、data/count CFG、元素 WriteMembers、析构邻域 | stride、深复制、元素构造/释放及 allocator 关系；不能裸写指针 |
| EventScope、ShipDesign、species template 等复杂值 | 递归 serializer、嵌套 subobject、构造/赋值/析构符号与可达调用 | 部分 type discriminator、owning 参数及成员初始化；不能以零值代替合法复杂对象 |
| 有生命周期副作用的 Factory/析构 | normal CFG、可达分支、已知 native value recipe、精确旧配对报告 | opaque callees 或外部写未证明安全；39 项仍有此技术要求，含非核心 |
| CString 定义 key / 普通整数语义 | native consumer、UI/AI 构造参数、规则/GUI/Localization 定位 | 完整 lookup 到命名字段的绑定、枚举域、定义池选择或单位，不能泛化 caller input |
| session slot、交易 record 等内部身份 | 成员到 `GetHuman/AccessHuman` 实参的数据流、交易记录已有证据 | actor 与国家关联、record 内相关字段必须一起取得，不能逐字段随机组合 |
| 状态 provider / Mod 定义 | native ref DB、既有 scoped query、CWTools 嵌套对象、外部定义来源 | 部分 manager schema 未绑定；外部文件与实际加载数据库仍未对齐 |
| 复杂间接边 | 精确指令边界、vtable、调用图和未解边预算 | 不能据一个未解虚调用宣称完整函数行为或所有规则已恢复 |

本轮复用了既有精确 ELF DWARF 审计：21 个 CU、55,388 个 DIE，目标游戏类型无匹配，未截断；
该结果只能说明这份类型查询没有提供补充布局，不能外推“所有 DWARF 都没用”。
已有 Ghidra 导出研究入口保留。本轮没有运行 Ghidra，也没有把受限指令分析称为完整反编译/符号执行。
后续可对记录的复杂 owning 函数定向导出 p-code；其缺口仍开放，不宣告无法恢复。

主动检索了 Stellaris Wiki 的风暴、陆军、命名/存档 Modding 等页面，但本次访问被登录/客户端挑战阻断，
未取得可信正文，所以没有用搜索摘要或论坛代替 ABI 证据。离线批量检索原版 scripts/GUI/英文
Localization 共 2,366 个文件，并与 native literal/类型/Producer 锚点关联；这些文本命中仅为语义线索。
425 份实际使用或命中的本地来源按 hash 独立归档，未修改安装目录。

## 6. 验证与复现

- 维护入口 `python scripts/validation/run_tests.py --quiet`：**638 项通过**，包含本轮 43 项新增测试，
  设置 `IAG_CWTOOLS_BRIDGE` 后实际运行社区 parser 集成测试，而非依赖跳过结果。
- 最终生成 header 用 MSVC C++20 `/W4 /WX` 编译并运行纯元数据检查，351 项边界检查通过，
  265 layout / 312 lifecycle gate 与 JSON SDK 指纹一致；没有调用游戏地址。
- 原有 Builder、Producer、Action contract 三个 mock-only C++ 测试可执行文件重新运行通过。
  它们不是新 Runtime 的实机测试；本轮未修改其 C++ 来源、未构建/加载 Linux Runtime。
- 默认离线 `validate_constraint_candidates.py` 通过 162 种 / 2,484 份计划编码预检，明确
  `connected=false`、`native_calls=0`、`submitted=false`、`production_promotions=0`。
- 最终复核确认 35 份代码与快照 hash 一致，报告生成期间无 source drift，原始 ELF/存档 hash 未变。
  旧证据、checkpoint、配置和 pass-01 至 pass-04 均保留。

可重跑同一入口，输出必须使用不存在的新目录：

```powershell
python services/stellaris_native_runtime/tools/plan_script_candidates.py `
  --sdk .tmp/sdk-recovery/incremental-offline-33-20261019T2337Z/linux_sdk.json `
  --elf .tmp/sdk-recovery/stellaris-linux `
  --tokens .tmp/sdk-recovery/incremental-offline-33-20261019T2337Z/linux_tokens.json `
  --parser-bridge .tmp/cwtools-bridge-build-20261020-01/CwtoolsBridge.dll `
  --game-root 'C:/Program Files (x86)/Steam/steamapps/common/Stellaris' `
  --save 'path/to/disposable/2384.01.25.sav' `
  --output .runtime-evidence/semantic-audit-reproduction-new `
  --recover-values --search-game-sources `
  --audit-baseline .runtime-evidence/script-candidates-4.5.2-20261020-01/pass-07/report.json `
  --lifecycle-evidence .runtime-evidence/sdk-expanded-batch-20261019-01/batch/report.json `
  --feedback-report .runtime-evidence/producer-validation-live-4.5.2-20261020-01/backfill-20261020T091601Z/remote-evidence/batch/report.json
```

最终 pass-05 复用了 pass-04 的 v3 fact cache；它同时绑定存档、adapter、parser、内容和原生 collection
证据，不兼容旧缓存时拒绝复用。上例不传缓存时可从冻结存档重建。

本轮完成的是更准确的全目录分类和共享构造恢复。没有给新命令实机准入，也没有新增
`paired_capture` / `live_verified`。类型化构造、候选生成、原生 IsValid、实际执行与多人同步仍分别取证。

## 7. 后续复用存档空间模型

以上数字保留为本审计 pass-05 的历史结果。后续离线工作直接复用了已有存档地图模块，
核实 4.5.2 的 100000 定点缩放，修复共享坐标值 padding 及参数相关域，完整 layout 增至 267，
候选增至 166 种 / 2,548 份。移动的两种坐标命令不再作为 ABI 缺口；坐标恢复阶段的研究通信 gate 当时仍拒绝其 i64，
不能把这一历史限制与原生构造能力混为一谈。后续 revision-7 研究 codec 已补齐严格 i64，
166 种 / 2,548 份计划均通过离线通信预检，未进行真实 Native IsValid。
最新主分类、全部 351 项新报告和边界见
[Coordinate Value Reuse](COORDINATE_VALUE_REUSE_4_5_2.md)。旧 pass、日志和原始证据未覆盖。
