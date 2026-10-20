# Coordinate Value Reuse: 4.5.2

> Publication: original/local evidence paths below are provenance labels, not Git downloads. Use the [indexed archive and access status](../research/EVIDENCE_ARCHIVE.md); public copies may be privacy-redacted and originals remain retained.


2026-10-20，完全离线。复用已有的 `stellaris_save_map`、OGAS 现有移动实现、
共享 NativeCommandBuilder 和精确 Linux ELF；不访问进程、不调用原生函数、不修改生产 Action 或安装生成头文件。

最终证据目录：`.runtime-evidence/coordinate-reuse-4.5.2-20261020-01/pass-02/`。
[全目录新分类及通信 gate 状态](https://github.com/V2t-Nostalgia/OGAS-research-evidence/blob/ccd7bfdfa33e749d2ea3bffd4586573a629ee08b/paths/e5/e59988d9a8a1fe46dc953709c4d2f82b480607ff8c5a1522253f0f6b9a440a1a.md)、
[逐字段审计](https://github.com/V2t-Nostalgia/OGAS-research-evidence/blob/ccd7bfdfa33e749d2ea3bffd4586573a629ee08b/paths/4e/4e895ef9ab28faae6bbc1ff4df1ebaadb91b9b4d5eb9fb0ebe4ea523952f1c1c.md)、
[最终复核记录](https://github.com/V2t-Nostalgia/OGAS-research-evidence/blob/ccd7bfdfa33e749d2ea3bffd4586573a629ee08b/paths/de/de3799cc0aa4d50d9c935a4331975d27e1f29e97889b7fad6b46b2ad0929baa1.md)。
所有旧证据、存档、配置和 checkpoint 保留。

## 1. 直接复用的能力

`--spatial-model-root` 显式选择既有空间模型源码目录，导入其 `StellarisSave` 公共 API，
对 **同一 SHA-256 的冻结存档** 调用 `build_full_map(include_dynamic=True)`，没有复制坐标解析器。
复用原有 exporter，在新的证据目录输出 `spatial-model/map.json`、`systems.jsonl`。
解析器、重建器、模型、导出器等 6 份源文件 hash 和原文独立归档；没有改外部空间模型源码或覆盖其输出。
原有 NPZ 导出能力不变，本工具不额外要求 NumPy 或重新设计地图格式。

沿用已有空间模型的语义：

- 星系自己的 galaxy XY 与该星系内对象的 local XY 是两个坐标系，不能数值混用。
- 局部坐标按 `origin` 绑定星系，归一化为 `local_xy / outer_radius`，每个星系使用自己的半径。
- 不硬编码所有星系共用半径，也不把观测到的 `outer-inner=100` 当引擎约束。
- 不裁剪略超半径的真实对象；半径不是已经证明的命令合法性规则。
- `origin=0xffffffff` 的航行对象属于银河航行层，不作为局部移动候选。
- 空间模型的 hyperlane endpoint 明确是 inferred，本轮没有把它们写入 Command。

同一 `2384.01.25.sav`（SHA-256 `c5cfa0fce3e434a704a0a7bebaaa0a7c9c4f956376ee1334a96d4f481c6c39e2`）
重建 819 个星系、31,480 个局部对象点；排除 156 个银河航行对象，0 个未映射对象、0 个地图接入错误。
OGAS 原有对象索引每类型 512 项的预算不变，因此不是所有地图对象都会进入同一轮候选。

## 2. 精确 4.5.2 原生证据

Linux Build ID：`121ecb516cbc5f1d39917fbcc36620534384e2c2`，与上轮审计相同。
研究 SDK 指纹：`6a8f371d3b2753d35532ef013a841a8032701f31052b5965a7c4f3e97e155ea4`。
以下地址均为 module RVA，不是运行时绝对地址，也不适用于 Windows。

| 证据 | RVA / 结论 |
| --- | --- |
| `CCelestialCoordinate::WriteMembers` | `0x2284790`，typed CFixedPoint / CGalacticObject 引用序列化 |
| 原生 `(system, x, y)` 构造器 | `0x22846b0`，清 display height 与两个 flag 字节 |
| `SetDisplayHeight(float)` | `0x2286ee0`，乘 **100000** 后按原生分支量化 |
| scale 常量 | `0x45fefc8`，float32 bits `0050c347`，值 100000 |
| XY 反转换常量 | `0x45f8560`，float32 bits `acc52737`，约 `0.00001` |
| 坐标 vtable address point | `0x521f5c0`，同时核对构造器、Factory 写入和 serializer |
| `CalcFTLPointWith(system*)` | `0x260d110`，现有 `move_fleet.cpp` Linux 路径已经使用 |
| `CalcFTLPointWith(coordinate&)` | `0x260d010`，同样记录为可复用的原生 provider |

**4.5.2 不使用旧 4.4.6 文档写的 32768 坐标缩放。** 本轮恢复器从乘法常量、实际字段写入、
XY 反转换和 typed serializer 交叉恢复 100000，不把旧文档、训练模拟器步长或渲染比例当 ABI 常量。
没有在此推断 4.4.6 ELF 的真实缩放，旧版结论需要另行精确版本复核。

共享 `CCelestialCoordinate` 为 40 字节、8 字节对齐：vptr `+0`，X `+8`，Y `+16`，
display height `+24`，完整 generation-bearing origin `+32`，内部 flag `+36`，randomized `+37`，
尾部 padding `+38..+40`。Factory 已建立 vptr、origin 初值及 flag/height 状态。

地图只提供二维 XY；当前候选采用原生构造器已证明的 `height=0, randomized=false` 平面目标。
这不是声称地图已恢复原对象的完整显示高度。不会触发 `RandomizeDisplayHeightIfSet` 或擅自消耗 RNG。
不尝试反演依赖运行时显示比例的 `GetFloatCoordinate/GetDisplayCoordinate` 屏幕位置。

存档十进制值乘精确 native scale，只有落在 int64 lattice 上才接受；不使用浮点截断或擅定舍入规则。
不在 lattice 上、非有限或超范围的输入会被记录/拒绝。归一化输入先用对应星系半径反归一化。

## 3. 共享修复，不是逐命令适配器

`sdk_recovery/coordinate_values.py` 自动识别共享原生类型、serializer、转换常量、构造器和 vtable，
再按 native writer RVA、字段相对偏移和 Factory 类型证明绑定任意 Command 的嵌入成员。
没有 `fleet_fly_to_coordinates` / `fleet_send_to_location` 专用分支或常量表。

恢复器此前将坐标展平成标量后，误将末尾 padding 当成未恢复 payload。现在只为已证明的值区域补充
padding 证据，不创建额外可写字段，不清空对象，也不跳过未知成员或生命周期 gate。
实际匹配到 5 个 Command：

| Command | 嵌入起点 | 本轮结果 |
| --- | ---: | --- |
| `fleet_fly_to_coordinates` | 32 | 完整 layout 和 16 份类型化局部候选 |
| `fleet_send_to_location` | 32 | 完整 layout 和 16 份类型化局部候选 |
| `add_ship_to_coordinates` | 40 | 原 layout 已知，补齐坐标来源，16 份候选 |
| `build_megastructure_command` | 48 | 原 layout 已知，补齐坐标来源，16 份候选 |
| `ping_map_command` | 56 | 复用同一坐标能力，其他 selector / payload 缺口仍保留 |

Planner 将 X、Y、Origin、height、randomized 作为一个相关域，而不是独立笛卡尔积。
存在唯一、原生构造参数已证明的 CFleet 上下文时，将该舰队与其 `solar_system` 一并绑定，
只生成同星系局部点。多坐标共享上下文仍要求额外 Producer 关系，不擅自拼接两个上下文。

跨星系继续通过既有 `BuildMoveCoordinate -> CalcFTLPointWith`，由原生状态计算目的点；
本轮未另造航道入口推算器，也没有把 galaxy XY 写进 system-local 目标。
研究 metadata 记录两种原生 overload 及 SysV sret 的 `out, this, toward`，没有调用它们。

共享 Builder 本来就有 `SetSigned(i64)`、`SetObjectId` 和 `SetUnsigned(bool)`。
本轮增加其坐标 mock 回归，验证 signed XY、完整 origin generation、零 height/flag、
Factory vptr、内部字节和 padding 不被破坏，析构配对且不调用 IsValid/Post。
没有新增坐标专用 Builder 或平行对象布局。

## 4. 更新后的分类与剩余边界

完整命名 layout **265 -> 267**，具备类型化输入构造能力 **258 -> 260**。
完整候选覆盖 **162 -> 166 种**，有界计划 **2,484 -> 2,548**。

全 351 主分类互斥：163 typed-constructible、20 等调用者参数、7 等已有原生查询、
8 引擎身份绑定、36 语义绑定、75 ABI/生命周期缺口、42 非核心暂缓。
另有重叠维度：技术缺口总数 92 -> 90；不能把 primary 与 overlapping 数字相加。
这两个移动命令不再计入 ABI 缺口，巨构与按坐标生成舰船不再计入缺坐标参数。

**坐标恢复阶段的旧通信预检** 为 162 种 / 2,484 份计划；当时四类候选因研究 codec 尚未支持 i64
而失败关闭。这不是新的原生构造缺口。后续通信修复已使全部 166 种 / 2,548 份通过预检，见第 6 节。
完整新报告另外列出每项的 `existing_constraint_codec_plans` 与
`research_codec_blockers_not_native_ABI_gaps`。不能将 Builder mock 构造和离线候选宣称为已实机 IsValid。
坐标恢复阶段没有改动通信 gate；后续仅补齐严格类型化的 i64，不降低其他安全要求，也没有注册或提升任何生产 Action。

其他复用检查：

- 45 个 typed `CFixedPoint` 字段共享当前版本的物理缩放证据；非坐标数量仍需要领域参数来源/单位语义，
  不因知道 scale 就自动生成舰队经验、工作岗位数量等取值。
- 国家内 project ID 已有 `EnumerateScoped`，普通建筑 owning Buildable 已有 native Producer；
  这些既有能力不能再次笼统算作缺 resolver 或要求重写构造器。其既有验收和限制仍按各自报告保持。
- `fleet_orbit_planet` 的 orbitable union、队列 wrapper 的 owning `CFleetOrder`、事件 scope 等，
  不属于普通 CCelestialCoordinate；未因 XY 同名就视为本轮已解决。

## 5. 验证与使用

OGAS 维护测试 **656 项通过**，包含本轮 18 项；实际 CWTools 集成测试已启用。
既有空间模型地图测试 **49 项通过**，`-B` 与 `-p no:cacheprovider` 避免在外部源码目录写缓存。
原有 Builder 测试新增坐标用例后重新 MSVC `/W4 /WX` 编译并运行通过；最终 Linux metadata
头文件也在 Windows host 上独立编译/运行纯数据检查：351 Command、267 layout、312 lifecycle gate。
这是 host 编译与 mock，不是 Windows 游戏 ABI 验收或 Linux Runtime 新二进制实测。

复现沿用 [现有审计命令](COMMAND_SEMANTIC_TECHNICAL_AUDIT_4_5_2.md)，换用全新的 `--output`，追加：

```powershell
--spatial-model-root C:/path/to/spatial-source
```

外部空间模型不是安装依赖，不提供参数时旧管线继续运行；坐标字段正确归为需要类型化输入，而不是 ABI 失败。
来源 hash、地图与存档 SHA、候选关联、通信 gate、全部 351 项新分类和测试均已独立归档。
本轮 native calls / submitted / production promotions 均为 0。

## 6. 后续 i64 通信修复（2026-10-20）

新证据独立归档于 `.runtime-evidence/constraint-i64-4.5.2-20261020-01/`，旧证据不改写。
当前代码、CLI 和文档统一使用“存档空间模型”命名；新来源清单使用模块相对路径与 SHA-256，
不记录外部项目根目录名。历史原始来源证据仍原样保留。

现有链路现已完整支持：`Candidate(i64) -> NativeProbeBinding(i64) -> signed decimal wire ->
ParseRecoveredConstraintCandidate -> SDK field/type/width check -> SetSigned(i64) -> numeric JSON echo`。
`i64` 保持 `[-2^63, 2^63-1]`，不转换为 uint32、不经过 float；其余 kind 仍保持原 uint32 范围，
既有 i32 回显的 uint32 bit-pattern 表示不变。溢出、浮点、字符串、bool 不能充当 i64。
没有增加 u64、裸指针、offset 或任意内存写入入口。

研究目录发布 `probe_revision=7`。i64 请求在 revision 6 上发送前拒绝/跳过，不能热替换当前已加载库。
SDK 指纹、版本、field writable/width/bounds、完整 generation 引用、instance/world/date、暂停和生命周期
gate 保持；生产 Action、执行调度和提交逻辑不变。C++ 仅接受 SDK 已登记的 8 字节 i64 字段。

- 全目录离线通信预检：351 项遍历，**166 种 / 2,548 份**计划通过，无连接、无真实 native 调用。
- 新四类 `fleet_fly_to_coordinates`、`fleet_send_to_location`、`build_megastructure_command`、
  `add_ship_to_coordinates` 各 **16 份**通过，合计新增 64 份，无 codec blocker。
- Python 全回归 **665 项通过**，启用真实 CWTools、全目录 Python wire/JSON 预检及 C++ Mock 往返，
  并验证中性来源清单的模块相对路径、源文件 hash 和原文快照。
- C++ Builder 与 Producer/Probe 两个夹具 MSVC `/W4 /WX` 编译并运行通过。
- 跨语言往返使用真实 Python 请求 framing、C++ parser/Probe/Builder/serializer 与 Python 严格 JSON 读取；
  7 组包括 INT64_MIN/MAX、负数、超 32 位和超 2^53 的精确整数。C++ 另检查实际写入的 8 字节值、
  类型/宽度/边界/SDK 已恢复取值域拒绝和 Factory/析构配对。所有 Factory/IsValid/析构均为进程内 Mock，非游戏函数。

新预检文件为 `offline-preflight/preflight.json`，四类明细为 `coordinate-command-preflight.json`。
最终带 hash 的复核记录为 `review-final.json`；所有中间测试与修正记录均保留。
这不属于真实 Native IsValid、paired_capture、执行或联机同步验收；生产准入与 live_verified 均未提升。
