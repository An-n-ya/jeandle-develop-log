# JavaType 缓存复用测试执行方案

> 阅读入口（2026-10-27 整理）：[跨 pass 缓存测试总结](../汇报/跨pass缓存测试总结.md)。本方案已进入执行，实际完成范围见[执行报告](JavaType-Cache-Reuse-Test-Execution-2026-10-26.md)。以下保留原设计要求，不把计划内容视为全部完成。

日期：2026-10-26。本文为执行前方案；其中的新增用例、对照模式和验收指标均为计划，实际结果以执行报告为准。

## 1. 任务目标与范围

为 getJavaType 缓存设计补充有辨识度的测试，重点回答：

1. 在 CFG 较浅、连续读取较多时，Base、PathFacts、Final 各自能节省什么工作？
2. 缓存收益能否出现在 TCE、CHA、CFF、RecoverTypeInfo 四个真实消费者中？
3. 前一个 pass 填充的缓存是否被后一个 pass 实际使用，贡献有多大？
4. 修改后保留的条目是否被再次访问？哪些修改或 pass 边界会阻断复用？
5. 哪些输入不值得缓存，或者会被 LVI、失效维护等成本抵消收益？

本任务优先增加测试、生成器和诊断能力，不以得到正向加速为验收目标。保留现有深 CFG、低复用和频繁修改用例作为对照。

默认交付范围是测试与测量。CFF／RecoverTypeInfo 修改后保留 JavaTypeAnalysis 属于独立的生产实现工作项：本轮先记录当前行为和生命周期断点，不为让测试命中而直接修改 preserve 合同。若执行任务明确包含该实现，再按第 8 节推进，并独立报告修改前后结果。

不要为了得到更高命中率而改变真实 pass 的变换语义、跳过失效通知，或直接将生产 LVI 替换成空 oracle。

## 2. 已知依据与需要重新核实的事项

本方案依据本地 2026-10-23 实验记录，以及 2026-10-26 读取的 GitHub 工作分支文件。远端 SSH 在讨论时连接超时，完整 compare 未取得；不能把 GitHub 文件状态当作远端测试 checkout 状态。

源码访问入口见 [jeandle-code-access 技能](../.agents/skills/jeandle-code-access/SKILL.md)。执行前应遵循实际任务中的授权范围；该技能的远端访问默认为只读。

工作分支：`Atm2086/jeandle-llvm:feat/javatype-selective-invalidation`。

已读取文件的 Git blob SHA（不是 commit SHA）：

| 文件 | Blob SHA |
| --- | --- |
| `llvm/lib/Transforms/Jeandle/TypeCheckElimination.cpp` | `0b6120840c0c9b3ab8f441b16e7b01b1e4903d06` |
| `llvm/lib/Transforms/Jeandle/RecoverTypeInfo.cpp` | `c48282404d8341ba5c8bd3157c62a29271f97f2e` |
| `llvm/lib/Transforms/Jeandle/ConstantFieldFolding.cpp` | `f608dd164e9e8cd917031c41b37490dd9be6d20f` |
| `llvm/lib/Analysis/Jeandle/JavaTypeAnalysis.cpp` | `a1ea64c4a868d9f97d6b0044adda2177dd01979d` |

已知观察：

- 现有生成器每增加一个 CHA 调用点，就增加一个串联的 `invoke → next`，查询数与 CFG 深度耦合。
- 现有 L1 性能记录中 Path/Final 命中均为 0，主要体现 Base 保留收益。
- 已有一个小型 CFF 回放，以及三个直接查询 API 的上下文复用测试；不能把本轮描述成首次测试 CFF 或首次验证上下文缓存。
- TCE 先做全部折叠决策，再批量通知和改写；修改后 preserve JavaTypeAnalysis。
- RecoverTypeInfo 在 emit 前完成查询，最后写类型 metadata；内部已有按 load 缓存的 `CtxCache`。修改后不 preserve JavaTypeAnalysis。
- CFF 在 pass 内多轮折叠时使用共享 JavaTypeAnalysis，并有修改通知；修改后不 preserve JavaTypeAnalysis。
- CFF 和 RecoverTypeInfo 无修改时返回 `PreservedAnalyses::all()`。
- JavaTypeAnalysis 持有 DT/LVI 引用；自身或任一依赖失效时会整体失效。

执行前核对上述行为、pass 注册名称和真实 pipeline 顺序。若代码已变化，更新文档中的预期，不能为满足旧预期而修改正确实现。

## 3. 实验分层与输入设计

### 3.1 分开三个证据层次

| 层次 | 用途 | 结论边界 |
| --- | --- | --- |
| API／单测 | 确定缓存键、失效、保留及生命周期机制 | 不能直接声称真实 pass 或完整编译加速 |
| 真实 pass 短流水线 | 检查真实查询入口、修改节奏和跨消费者复用 | 人为组合需标明，不等同生产 pipeline |
| 生产 pipeline／真实回放 | 检查表达式存活、中间 pass 失效和最终收益 | LLVM 回放不能直接外推 JVM 应用性能 |

### 3.2 解耦查询数、表达式成本、CFG 深度

准备三类 CFG：

1. **单基本块**：共享 select DAG，多个 check 或字段 load；主要隔离 Base／Final。
2. **浅层分叉**：一个 guard 加少量层级的分叉；多个兄弟块使用相同对象，观察不同 Final 键下的 Base／PathFacts 共享。
3. **串联深 CFG**：保留现有输入，作为 LVI 和上下文失效压力组。

CHA 多调用点输入优先尝试 `switch → 多个兄弟块`，每块一个 invoke 并各自返回，共用合法的异常出口；在增加 sites 时保持支配深度基本不变。是否能共享 PathFacts 以实际查询轨迹为准，不预设命中。

表达式至少包括便宜叶子和中等规模共享 DAG。DAG 使用多个独立条件、不同叶子；避免只有同一个条件连续 select、被前置优化轻易压缩。控制预算，主要性能组使用完整无环查询。

每个短流水线和完整 pipeline 测试均记录目标 pass 入口处的实际 DAG 节点数、块数和查询点数。输入在进入目标 pass 前消失时，不能把零查询当作高速缓存收益。

### 3.3 少量参数先筛选

| 轴 | 初始建议点 |
| --- | --- |
| 修改间隔内的查询数 | 1、8、32 |
| 相邻查询批次的对象重叠率 | 0%、50%、100% |
| 基础表达式 | 叶子、中等共享 DAG |
| CFG | 单块、浅层、深层 |
| 修改 | 无修改、独立纯计算修改、call／memory 修改、相关类型事实修改 |

不展开完整笛卡尔积。先完成第 9 节的最小批次，再对出现收益转折的轴加密。人为调整读写节奏属于机制回放；真实 pass 测试必须保留 pass 自身的执行节奏。

## 4. 四个消费者的定向用例

### T01：TCE 同块批量查询

- 同块中多个 `check_instanceof` 使用相同对象／共享 DAG。
- 目标类使用非 Object 类型，避免 Object 快速路径绕过 getJavaType。
- 分别构造全部不可折叠、可折叠与不可折叠混合的输入；查询结果必须被使用，防止前置 DCE 删除。
- 确认全部决策先查询、最后统一改写的实际执行顺序。
- 验证重复的同 Value／同 ContextBB 查询出现 Final 复用；折叠后的输出符合预期。
- 增加零对象重叠对照，测量缓存开销。

### T02：RecoverTypeInfo 同 receiver 多字段

- 多个不同字段 load 使用同一个 QueryBase，先放在同块，再扩展到浅层兄弟块。
- 确保 load 满足该 pass 的跟踪条件，函数满足 root Java method 条件，并能实际触发上下文查询。
- 以多个不同 load 为复用来源，不能靠反复迭代同一个 load 的固定点轮次制造查询量：内部 `CtxCache` 可能已拦截这些请求。
- 验证各 load 的 metadata 正确；观察同块 Final 复用、跨块 Base／PathFacts 复用。
- 区分该 pass 自身的 callback memoization、固定点传播与 JavaTypeAnalysis 缓存收益。

### T03：CFF JavaType 查询路径

- 使用非常量 oop receiver 和多个 `load_klass`／`get_class` 消费点，避免常量对象身份路径绕过 getJavaType。
- 提供合法的 nonnull 条件，让查询前置检查通过。
- exact 类型组验证成功折叠后共享 Base 的复用。
- 非 exact 类型组验证已经查询、但不能折叠时的连续读取；必须以诊断证明进入过 getJavaType。
- 增加相同 receiver 的多轮情形，但不能将已被消除、没有实际查询的轮次算成缓存命中。

### T04：CHA 浅 CFG 共享表达式

- 兄弟块中的多个调用共享 receiver 或引用参数 DAG。
- 先选择改写对 CFG 影响较小的合法路径；涉及 receiver null-check 分裂的路径单列。
- 与相同 sites、相近表达式规模的串联 CFG 输入配对。
- 记录调用点成功变换数、Base 重算、上下文命中和 LVI 工作量。
- 不假设改写 call 后 Final 仍可保留；按当前失效合同确定预期。

## 5. 跨 pass 用例

以同一对象 `%v` 同时连接多个真实消费者：`instanceof(%v)`、`load %v.field`、`load_klass(%v)`／`get_class(%v)`、`invoke target(%v)`。各用例只放所需消费者，保持输入小而可解释。

优先采用生产 pipeline 中实际存在的顺序；用于定位机制的其他组合必须标注为人为短流水线。

| ID | 组合 | 输入条件与预期 |
| --- | --- | --- |
| X01 | TCE 无改写 → RecoverTypeInfo | TCE 确实查询但不能判定检查结果；后者读取相同对象、尽量同块。验证跨消费者 Final／Base 复用。RecoverTypeInfo 后续 emit 不妨碍此前消费旧条目。 |
| X02 | TCE 无改写 → CFF | 两者都必须进入查询。可用非 exact 类型让 CFF 查询后不折叠，验证跨 pass 共享。 |
| X03 | TCE 有折叠 → RecoverTypeInfo 或 CHA | 被折叠检查不改变共享对象 DAG；预期上下文失效，验证存活 Base 被下游再次消费。 |
| X04 | CFF 已查询但无改写 → TCE | 验证反方向复用；CFF 提前返回且从未查询的输入不合格。 |
| X05 | RecoverTypeInfo 有 metadata 写入 → CHA | 当前实现下是分析生命周期断点。验证新类型信息被读取；不把 metadata 带来的优化能力记作旧缓存命中。 |
| X06 | CFF 有修改 → 下游消费者 | 当前实现下应丢弃分析；作为断点对照。未来实现 preserve 后另跑，不覆盖原始结果。 |
| X07 | 已验证短序列 → 生产 pipeline | 检查中间标准 LLVM pass 是否丢弃分析，以及表达式是否被提前简化。 |

每个跨 pass 用例必须证明：前一 pass 填充了什么、后一个 pass 查询了什么、是否还是同一个有效缓存条目、之间发生了哪些修改或分析销毁。

不能仅凭两个 pass 都调用 getJavaType，或者分析实例仍存在，就宣称跨 pass 复用。

## 6. 对照模式与归因

沿用现有 ORIGIN／FULL／选择性失效模式，但遵循以下边界：

- ORIGIN 使用原始查询引擎；与新引擎的差异不能全部归因于缓存容器。
- FULL 与选择性失效应在相同的逻辑修改边界接收相同通知。
- 若比较 S0／S1，保持查询算法和失效集合一致，只隔离 Base 删除方式。

新增一个测试专用的跨 pass 消融对照：

| 模式 | 行为 |
| --- | --- |
| PASS-LOCAL | pass 内正常使用选择性缓存；在指定 pass 边界清空 JavaType 缓存条目 |
| CROSS-PASS | 同样的 pass 内行为；按生产 preserve／invalidate 合同跨边界保留 |

两种模式必须使用相同查询引擎、DT/LVI 生命周期、修改通知、输入和预算。PASS-LOCAL 只清已有 JavaType 缓存，不主动创建分析，不额外丢弃／重建 DT 或 LVI。边界 hook 的具体实现由执行者按当前 PassManager 接口选择。

以相同位置的边界 hook 实现两种模式；清理、填充和销毁成本计入相应测量。若需估计清理动作本身的成本，可单独诊断，但不得把强制清理的全部差异称作纯查询节省。

PASS-LOCAL 与 CROSS-PASS 的差异用于量化跨 pass 保留策略的净贡献。若当前合同已在某边界销毁分析，两者该处没有差异是合理结果。

为隔离 pass 内跨查询收益，可在 API 机制测试使用同一新引擎的逐查询冷缓存对照；不要把其强制清表成本全部算成计算算法收益。

## 7. 诊断、正确性和性能测量

### 7.1 诊断记录

诊断构建或诊断模式建议记录：

- Function、pass 名和本次 pass invocation ID。
- 顶层查询 Value／ContextBB 的稳定测试编号、查询模式和结果。
- Base／PathFacts／Final 各层查找、命中、插入及失效；覆盖递归 Base 查找，不能仅统计顶层 base-only 查询。
- 条目填充所属 pass invocation、条目代次，以及本次命中所属 pass。
- 条目填充后是否经过修改通知、通知种类，以及分析实例的创建／销毁原因。
- LVI oracle 调用数；如果另测内部 solve 次数，要单独命名，不能混为一个指标。
- 查询是否预算截断、是否涉及 PHI 环、正确性校验是否跳过。

条目被删除后重新插入应有新代次。诊断标签不能把 Value 地址复用误识别为旧条目存活；不要解引用已删除的 Value。观测数据结构不应改变被测缓存布局或生产策略。

主要分开报告同 pass 命中、跨 pass 命中、跨修改后命中，以及最终没有再被访问的保留条目。单独增加“下游首次查询是否使用上游条目”的明细，避免下游自身热起来后的命中掩盖跨 pass 来源。

### 7.2 正确性

- 完整无环主要用例中，比较 JavaType 全字段：Klass、Exact、Interfaces、ExcludedKlasses。
- 修改相关事实的用例必须至少包含一个预期答案发生变化的 probe；另放一个独立 probe 检验保留。
- 独立参考应基于修改后的 IR 和新建的 DT／LVI 等依赖，避免参考与候选共用陈旧分析。
- IR verifier、参考重算与详细诊断不进入性能计时。
- 检查关键优化数量和 metadata／调用点结果；同算法的 pass 边界消融应得到一致输出。
- 主要性能组要求完整求值、校验 skips 为 0。循环和预算截断另组测试，不用盲目的冷热全字段相等判定。
- VM callback 模型必须完整、确定；record/replay 按键覆盖各模式所需调用，缺项不能用伪造默认值填补。

### 7.3 计时

- 同时报告目标 pass／短流水线时间，以及完整回放或生产 pipeline 时间。
- 微基准的 IR 解析／克隆／参考计算置于计时之外；端到端测量说明是否包含解析。不得混用两种边界。
- 性能模式关闭详细事件追踪、校验和逐查询计时；诊断模式单独运行。
- 使用预热、随机配对顺序及原始逐轮数据。先以 3–5 轮 pilot 判断量级；若用于稳定性能结论，再依据波动增加配对轮次并跨 session 复测。
- 通过多份独立等价夹具或足够长的回放放大时间，不通过无限加深 CFG 或耗尽查询预算放大。
- 不并发运行相互干扰的性能任务；记录 CPU、构建参数、二进制哈希和运行命令。
- 报告绝对时间与相对变化；查询层加速不能替代完整 pipeline 结果，负收益也必须保留。

## 8. CFF／RecoverTypeInfo 支持 preserve 的后续工作项

以下为设计建议，不是已完成的正确性审计，也不是本测试任务默认要求的生产修改。

### 8.1 RecoverTypeInfo

建议路径：收集待写 metadata 的 loads → 在写入前批量 invalidate → emit → preserve JavaTypeAnalysis、DT 和 LVI。

原因：emit 前可能缓存了某 load 的 unknown，以及依赖该 load 的 select／PHI 结果。新增类型 metadata 后，这些旧结果必须失效；仅仅保留偏保守结果也会让下游错过新事实。

当前自定义 Java 类型 metadata 不改变 CFG，也不是已检查的 LVI 事实来源；在重新核实代码后可保留 LVI。使用现有 load 修改通知可能保守清空全部 PathFacts／Final，但仍可保留独立 Base；第一版不必新增精细 metadata 通知。

验收：修改 load 及其派生查询反映新类型；独立子图在下游仍可命中；分析与依赖对象生命周期正确。

### 8.2 CFF

先审计所有替换、插入和删除路径的通知，包括 narrow decode、无用户 load、死 GEP 和多轮折叠。不要假设 pass 内已有通知就自动证明可以安全跨 pass 保留。

重点核实 LVI：JavaTypes.invalidate 只维护 JavaType 缓存，DT/LVI 由调用者维护。已读取的主流程没有显式 LVI 清理，应检查 LVI 自身机制能覆盖哪些修改；未覆盖时，在下一次依赖它的查询前更新或清理。

不能仅在 pass 退出时清理：相关问题也可能发生于当前 pass 的后续查询／后续轮次。可采用保留 LVI 对象、清空其内部缓存的保守方式，避免 JavaTypeAnalysis 持有失效引用。CFF 不改 CFG 时 DT 可以保留。

完成维护后再 preserve JavaTypeAnalysis 及依赖。测试同时覆盖 pass 内重查和跨 pass 重查，并与全新分析参考比较。

### 8.3 共同约束

只增加 `PA.preserve<JavaTypeAnalysis>()` 不够。当前结果失效逻辑还依赖 DT/LVI；必须确保它们有效且被 FAM 保留。

生产修改前后分别保留 X05／X06 的结果：修改前用于说明生命周期断点，修改后用于量化跨 pass 保留。不能合并成一份未注明实现差异的数据。

## 9. 执行顺序与阶段验收

| 阶段 | 工作 | 完成标准 |
| --- | --- | --- |
| P0 | 核对 checkout、源码、四个 pass 入口及 pipeline；复用现有测试设施 | 身份记录、现有行为表、计划偏差清单齐全 |
| P1 | T01、T02；单块与浅层版本 | 两个真实 pass 的查询入口、语义结果和复用机制均有证据 |
| P2 | X01、X03；实现 PASS-LOCAL／CROSS-PASS 对照 | 至少一条跨 pass 连续读取路径和一条跨修改 Base 路径被验证；不要求一定正向加速 |
| P3 | T03、T04、X02、X04、X05、X06 | 四个消费者均覆盖，生命周期断点有明确结果 |
| P4 | X07 和零重叠、深 CFG、便宜叶子负对照 | 说明短流水线收益是否能进入完整 pipeline，以及适用边界 |

优先完成 P0–P2，形成可独立审阅的首批结果；随后继续 P3–P4。若某个预期路径在当前实现中不可达，提交查询轨迹和原因，选择同目的替代输入，不强行制造命中。

总体验收不设“必须加速多少”的阈值。必须能回答：缓存何时填入、为何存活或失效、谁实际消费、节省多少重算、净时间变化多少。

## 10. 交付物

1. 小型、可读的 IR／单元测试及完整 VM callback fixture，包含正向和负向预期。
2. 参数化生成器或现有生成器扩展，明确区分 CFG 形状、查询量、表达式规模与修改节奏。
3. 诊断模式与可重放的计时脚本，包含 pass 边界消融。
4. 源码／二进制身份、命令、原始诊断和逐轮时间，采用 JSON／CSV 等机器可读格式。
5. 执行报告：实际完成矩阵、正确性、三层命中来源、跨 pass 贡献、LVI 工作量、时间结果、失败／未覆盖项。
6. 若做生产 preserve 改动，单独提交实现说明、维护合同与相关回归，分开呈现修改前后数据。

建议报告主表：`用例 / pipeline / 模式 / 查询数 / 分层命中 / 跨 pass 命中 / 修改后命中 / Base 重算 / oracle 调用 / 优化数量 / pass 时间 / 完整时间`。

## 11. 相关材料

- [原缓存设计测试方案](JavaType-Cache-Design-Test-Plan-2026-10-23.md)
- [原测试执行记录](JavaType-Cache-Design-Test-Execution-2026-10-23.md)
- [性能诊断执行报告](JavaType-Cache-Perf-Profiling-Execution-2026-10-23.md)
- [直接查询 API 的上下文复用实验](JavaType-Context-Cache-Reuse-Execution-2026-10-23.md)
- [现有输入生成与测试脚本](../benchmark-java-type-cache-design.py)

## 12. 可直接交给执行 agent 的任务说明

> 请按本方案执行 JavaType 缓存复用测试，先核对实际 checkout 和现有实现，再依次完成 P0–P4。优先交付 TCE／RecoverTypeInfo 连续读取、跨 pass 共享，以及 PASS-LOCAL／CROSS-PASS 消融。复用已有测试设施，保留负对照，使用实际查询轨迹证明缓存被消费，不以正向加速为验收条件。默认范围是测试与测量；将 CFF／RecoverTypeInfo 修改后 preserve 的生产实现作为独立工作项，只有任务明确包含时才推进。记录所有源码身份、命令、原始结果和未覆盖项，不把本文计划写成已完成结论。
