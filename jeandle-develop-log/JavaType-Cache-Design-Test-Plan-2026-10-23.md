# JavaType 缓存设计的测试与决策方案

日期：2026-10-23。状态：P1-P5、S0/S1、核心正确性矩阵及相关 pass 回归已执行；
后续项与结果见
`JavaType-Cache-Design-Test-Execution-2026-10-23.md`。

源码依据：`357604c7724e49eace6fbfa42e4f671b12b5ff98`。远端 checkout 还有 `CachedJavaType.cpp` 的未提交格式调整和性能 TODO，已只读检查，没有修改。正式实验必须同时记录 HEAD、工作区补丁、源码和二进制哈希；不能仅用提交号代表被测程序。

本方案要回答四个问题：缓存是否可靠；失效是否删除了值得保留的结果；维护成本是否超过重算收益；收益能否出现在真实 pass 和完整编译中。所有参数和性能阈值均为建议起点，不是已有测量结论。

## 1. 先分开比较策略与数据结构

“更少失效”与“相同失效更便宜”是两个实验，不能混为一谈。

| 编号 | 候选 | 固定条件与目的 |
| --- | --- | --- |
| REF | 原始查询，每次独立计算 | 正确性参考、无跨查询缓存的性能对照 |
| FULL | 缓存开启，每个修改批次全清 | 评估选择性保留是否有净收益 |
| S0 | 当前选择性失效 | 默认比较基线 |
| S1 | S0，非 CFG 修改按 Affected 逐键删除 Base | 只测消除 Base 全表扫描的收益 |
| S2 | S1，上下文条目按 Value 分组 | 保持失效集合和发布规则不变，只换布局 |
| S3 | S2，上下文整层失效改为 epoch | 保持逻辑有效性不变，测延迟物理回收 |
| S4 | EntryID + 实际依赖反向索引 | 测更精细依赖的收益与维护成本，最后再实现 |

先做 S0→S1→S2→S3 的逐项对照，不要求一次实现全部候选。合并修改通知是另一条实验轴：对同一逻辑批次比较单独通知和合并通知，不同时更改布局。候选必须使用相同查询算法、预算、VM 结果、编译选项。若改变了算法精度或结果发布规则，单独标记为算法实验。

FULL 和候选应在相同的逻辑修改批次边界失效；另做单独通知/批量通知对照。否则无法判断收益来自策略还是通知次数。

## 2. 正确性测试：统一 Query—Mutate—Query 驱动器

建议抽一个测试驱动器，由各策略实现相同的查询和修改通知接口。事件描述及适配器为待实现接口，不要求先改生产 API。

```text
parse initial IR
install deterministic VM type model
create candidate analysis and its DT/LVI

for each logical step:
    warm the specified queries through the candidate
    if the step mutates IR:
        notify all planned changes while the old graph is intact
        apply the edits without querying midway
        repair candidate DT/LVI according to the production contract
        verifyFunction

    for each probe:
        observe candidate result and candidate-only counters
        build a fresh reference world from the current IR
        query the original engine in that reference world
        check the declared equality or semantic contract
```

### 2.1 真正独立的参考状态

参考查询必须重新构建 DT、LVI、AssumptionCache 等所需分析；不能沿用候选的 LVI。最清晰的实现是 CloneModule 后在独立分析管理器中运行参考查询，用 ValueToValueMap 映射活跃查询值和上下文。查询对象包含 Function/Argument/Instruction 时都应正确映射。

每个 probe 使用原始 `jeandle::getJavaType` 的冷调用；若再运行空的 CachedJavaType 获取截断诊断，它只是辅助诊断，不是独立的语义证明。

克隆、参考计算、LLVM verifier、预期类型计算全部放在正式性能计时之外。诊断时也应隔离参考调用的统计，例如单独进程，或只对候选调用前后取差值。全局 callback 计数不能把参考调用算成候选成本。

### 2.2 三种断言必须分开

1. **语义断言：所有策略都必须通过。** 完整、无环、预算充足的指定用例，冷热 JavaType 全字段相等；比较 Klass、Exact、Interfaces、ExcludedKlasses，不只比较 Klass。
2. **保留能力断言：仅约束宣称相应能力的策略。** 在手工确认独立的查询上，要求仍能命中或不再执行基础计算。FULL 可以不通过这类断言，不能因此标成正确性失败。
3. **成本断言：使用结构计数验证趋势。** 例如只删除一个 Base 时，S1 不应检查全部 N 个 Base 槽位；这不等于要求特定机器上的固定纳秒数。

epoch 的逻辑有效条目数和物理存储条目数不同，因此不可统一要求失效后 `map.size()==0`。测试接口应表达“旧结果不可命中”，并另行观察存储回收。

### 2.3 PHI 环与预算截断的判据

现有 `CompletePhiCacheCanImproveCyclePrecision` 已明确允许热结果比冷结果精细，不能要求所有用例冷热逐字段相等，也不能把 SkipVerification 记成通过。

- 主决策基准先采用无环、完整求值的输入，要求 skips=0，隔离缓存容器和失效策略的成本。
- 环/截断测试另列分组，覆盖预算 0、1、恰好够、较大预算，及不同预热顺序。
- 建立小型有限类层次模型，例如 Object、Animal、Cat、Dog、Other 和两个接口。以集合定义每个 JavaType 允许的非空动态类，独立计算简单 IR/guard/PHI 的可达类集合。
- 对循环使用有限集合上的固定点计算，保持 PHI 并行赋值和 CFG 边约束语义。若模型用的是可达状态过近似，应注明可能导致保守误报，不能称作完整执行语义。
- 在测试模型范围内，要求 `ActualClasses ⊆ AllowedClasses(Result)`；同时为若干手工可证用例要求明确精度，防止“总返回 unknown”轻易过关。
- 只比较“热结果比冷结果更窄”不能证明健全性；二者都可能错误。该有限模型也不构成任意 JVM 程序的证明。
- 严格遵守当前 JavaType 的非空使用合同；null 边按合同处理，不把 JavaType 当作完整 nullability 分析。

## 3. 定向正确性矩阵

每个用例均记录：初始 IR、预热查询序列、修改事件与时机、修改后 probes、明确的预期类型、可选的保留能力断言。用例名为建议新增或强化的测试名。

| ID / 建议名称 | 场景与预期 | 主要防止的问题 |
| --- | --- | --- |
| C01 UnknownBecomesKnown | 缓存无类型属性的参数及派生 select；添加类型属性，结果从 unknown 变为给定类 | 遗漏“属性不存在”的依赖 |
| C02 TypeFactWeakens | 删除属性；或 Exact true→false；或子类→父类。修改后不得保留旧的更强结论 | 只测试精度增强，漏掉错误窄化 |
| C03 LoadAndCallTypeFacts | 分别改变 load metadata、call 返回类型属性，探测直接和传递结果 | 只支持 Argument 通知 |
| C04 CachedChildDependency | 先缓存子表达式，再查询父表达式使其命中子缓存；修改源值，父必须更新 | 命中缓存时没有登记依赖 |
| C05 SharedDiamond | 多条路径汇合到共同下游，同时修改两个根 | 重复传播、遗漏共享下游 |
| C06 CacheHoleInUseGraph | 中间值没有对应缓存条目，下游有；修改上游仍应使下游失效 | 遇到无缓存值就提前停止 |
| C07 RAUWUsesOldGraph | old→new 类型不同；修改前通知，RAUW 后删除 old，下游应得到 new 类型 | RAUW 后丢失旧依赖 |
| C08 CanonicalWrappers | cast/freeze 包装的多个查询；替换包装的操作数，探测规范化键和保留的底层值 | 键规范化与通知对象不一致 |
| C09 GuardNotAQueryKey | 缓存 obj 在后继块的类型；改变 check 的目标类或分支条件，obj 本身不变 | 只追踪查询值的 SSA users |
| C10 RealLVIStateChange | 使用实际 LVINullEdgeOracle，改变 null 条件/nonnull 事实，并预热 LVI；与重建 LVI 的参考比较 | 两边共用陈旧 oracle |
| C11 MemoryFactChange | 预热 LVI 的解引用事实，再改变/删除其来源；至少验证 oracle 的前后答案或缓存状态确受影响 | “调用了失效”被误当作语义覆盖 |
| C12 CFGAndPhiMembership | 删除边/删除 incoming，使 PHI 从 Animal 变成 Cat；同步维护 DT，探测关联 Final | 终结指令无 SSA users，PHI 未失效 |
| C13 DeleteBlockWithCachedLeaf | 待删块包含已经缓存的 load/call 叶子；通知整块内值并删除，所有旧键失效 | CFG 叶子保留留下悬垂键 |
| C14 DeadNarrowLoadInCFF | 先缓存可折叠但无用户的 narrow-oop load，再运行 CFF 的真实删除路径 | 已发现的条件通知遗漏 |
| C15 IdentityReuse | 删除旧对象、复用测试 EntryID 槽，旧依赖不得作用于新对象；Value 地址复用另作压力测试 | epoch/EntryID 的 ABA 问题 |
| C16 BudgetPublication | 截断子问题不得以“完整结果”跨查询复用；提高预算后可得到预期结果 | 临时 unknown 污染共享缓存 |
| C17 PhiCyclesAndOrder | 直接/互递归 PHI，多种合法预热顺序；按语义模型与手工精度断言 | 环中局部结果被错误发布 |
| C18 InvalidationLimits | 值数阈值前/等于/后，use 数阈值前/等于/后，各自单独构造 | 回退边界和两类预算混淆 |
| C19 BatchEquivalence | 同一批修改无中途查询，分别/合并通知；完整无环用例最终语义一致 | 合并通知漏事件 |
| C20 IndependentRetention | 两个独立类型子图，只改一个；检查另一个的后续命中/重算 | 总是全清也能通过所有测试 |
| C21 RepeatedMutation | A→B→A 多轮修改，每轮穿插查询；覆盖插入、删除、epoch 和旧依赖回收 | 只在第一次修改后正确 |
| C22 FAMBoundary | 正确 preserve 后复用；不 preserve 或 DT/LVI 失效时丢弃；下一次不得持有旧引用 | 跨 pass 生命周期失配 |

补充约束：

- C14 应在 FAM 自动丢弃结果前检查删除事件及旧条目的逻辑失效，或使用测试专用观察接口；pass 结束后只检查缓存已销毁会掩盖问题。不要解引用已删除的 Value 来检查缓存。
- C15 的槽位复用是确定性测试；不能以“多分配几次可能复用 Value 地址”作为唯一正确性测试。ASan 压力测试也不能保证发现仍合法地址上的错误键命中。
- C18 构造 use 阈值测试时保持不同值数低于 4096，例如多 operand 的指令；构造值阈值时避免 use 阈值抢先触发。记录实际被访问的数目，避免规模参数与触发点偏一。
- 对计划中的 begin/commit 接口，再增加“修改窗口内查询被拒绝”的调试断言测试；它不是当前接口已有保证。
- VM callbacks 当前合同是同一次编译内同参数同结果。当前方案测试编译生命周期切换及缓存重置；不在一次合法编译内随意改变 callback 结果来制造 epoch 场景。若未来改变合同，再新增 VM generation 测试。

## 4. 用三个小测试先检验测试本身的有效性

### 示例 A：完整结果发生明确变化，同时检查独立查询

初始类型模型：Cat 和 Dog 的共同父类为 Animal。

```llvm
define void @test(ptr "java-klass"="22" %a,
                  ptr "java-klass"="33" %b,
                  ptr "java-klass"="44" %independent, i1 %c) {
entry:
  %v = select i1 %c, ptr %a, ptr %b
  ret void
}
```

预热 `%v`、`%independent` 两次，确认测试确实走过缓存。修改前通知 `%v`，将 false operand 从 `%b` 换成 `%a`，保持 CFG 不变。修改后 `%v` 应为 Cat，独立查询仍为 44；具有选择性保留能力的策略应复用 independent。参考查询使用新分析状态。

### 示例 B：生命周期回归

由常量 oop 字段产生一个无用户 narrow load，先对该 load 做 base 查询，使它有真实条目。随后通过 CFF 的 T_OBJECT/T_ARRAY narrow 分支删除它。检查删除前通知覆盖及旧条目不可命中。不能只删除一个从未被查询的 load，否则漏通知实现也可能通过。

### 示例 C：测试应能抓住已知错误

在隔离的测试变体里故意启用以下错误之一：漏掉 C01 通知、在 C09 保留旧上下文、在 C04 不登记命中子结果的依赖（仅适用于 S4）。相应测试必须失败。错误注入开关只能存在于测试环境，不进入生产配置。

正确性用例至少要包含修改后结果确实改变的样本；只看缓存计数变化，或修改后结果仍为原类，不能充分验证陈旧结果会被拒绝。

## 5. 性能微基准：每组回答一个设计问题

统一记号：N=活跃缓存条目数，H=容量/历史高水位，A=受影响的活跃条目数，C=每个值的上下文数，B=一次逻辑批次的事件数，Q=批次间查询数，R=修改后会再次访问的旧条目比例。A 是实际观测值，不能拿 Changed 根数代替；记录 Base/Path/Final 分层值。

| ID | 独立变化的因素 | 固定或对照条件 | 能回答的问题 |
| --- | --- | --- | --- |
| P1 SparseBaseEdit | N=64/1K/16K/64K，A=1/8/64 | CFG 不变、无上下文全清干扰；每次只改独立子图 | S1 的代价是否摆脱 N，逐键删除在哪些比例优于扫描 |
| P2 ContextFanout | C=1/4/16/64，同时做固定值数与固定总 N 两组 | 改一个值，失效相同上下文集合 | Value 分组节省的扫描是否抵消两级查询和空间开销 |
| P3 BatchOverlap | B=1/8/32/128；下游闭包重叠率 0/50/90% | 不在批次中查询；同一最终 IR、同一探测序列 | 合并通知、入队去重分别省多少工作 |
| P4 ContextReset | 修改之间 Q=0/1/8/64；R=0/10/100% | 每次事件都按同一语义失效上下文 | epoch 延迟删除是否只是把成本转移到下一次查询/销毁 |
| P5 HistoryAndChurn | 同一活跃 N，不同 H；反复删除插入 | 高水位后下降 vs 从小表开始；循环 100/1K/10K 批次 | tombstone、旧 epoch 条目、依赖边是否累积，长期内存是否稳定 |
| P6 GraphShape | 链、共享菱形、宽扇出、低缓存覆盖的大 use 图 | 分别控制节点数、边数、缓存覆盖率 | 时间花在 SSA 遍历、重复入队还是缓存删除；S4 是否值得 |
| P7 QueryCostAndReuse | 叶子、共享 select DAG、CFG diamond/PHI；低/高复用 | 加入完全无失效及无复用对照 | 查询侧额外索引维护是否抵消失效收益 |
| P8 BudgetBoundary | 接近 4096 值与 16384 use 的独立扫描 | 同时记录 full-clear 原因与后续重算 | 阈值附近是否出现不可接受的性能突变 |

不要完整展开所有参数的笛卡尔积。先用每组低/高两点筛选，再对出现交叉点的轴加密；保留不利场景，包括小函数、便宜叶子、低复用、高修改率。

### 5.1 微基准的时间边界

- 隔离失效：预构造并预热相同语义状态，再计时一次失效；每个样本恢复状态，禁止对已清空缓存反复调用 invalidate 后宣称极快。
- 完整轨迹：计入预热/插入、所有查询、所有修改通知、DT/LVI 必要维护、依赖索引维护、epoch 回收及最终销毁。IR 解析可单独报告并放在此计时区外。
- 同时报告第一次填充和稳态重复轨迹，避免只看“缓存已经建好”的最佳状态。
- 纳秒级操作通过一批独立且等价的夹具放大计时，不靠每个操作插入时钟；可另作采样诊断。结果累积成 checksum，防止优化器消除计算。
- oracle、构造正确性模型、结果比较及 detailed logging 不进入正式计时。
- 真正全清所做的析构、索引注销与 epoch 最终回收必须计入完整轨迹，不能仅比较失效函数入口耗时。

## 6. 真实 pass 与完整流水线

至少覆盖以下消费者及其组合：

| 场景 | 必测输入特征 |
| --- | --- |
| TCE→CHA | 同一基础 DAG 跨 pass 复用；折叠改变 guard 后上下文必须失效 |
| CHA | 静态 linkTo、带 CFG guard 的虚调用、多引用实参 narrowing、失败/回滚路径 |
| CFF | 同一个 receiver 跨轮复用、narrow decode 与直接 narrow、无用户 load、常量字段链 |
| RecoverTypeInfo | 共享查询基值、PHI、只在 emit 阶段写 metadata 的生命周期 |
| RepeatedCFF | cleanup 后进入下一轮，FAM/DT/LVI 生命周期正确 |
| 完整 Jeandle pipeline | 当前 pre-pea-high-tier-e2e 回放，以及后续真实编译样本 |

现有生成式 256 层 select 实验继续保留，作为“昂贵基础表达式存活”的专项；必须增加完整 pipeline，检查表达式是否在进入被测 pass 前已被简化。

真实样本按方法大小、PHI 数、上下文数、查询/修改比、pass 分布分层，固定选择规则并保留调优集与未参与调优的验证集。没有 JVM 真实样本时，结论明确限于 LLVM 回放，不能外推应用编译或运行时间。

### 6.1 输出与 callback 回放

- 对选定的完整无环基准，要求规范化后的输出 IR 一致，并检查关键优化确实发生，防止跳过优化看似更快。原有适合字节比较的夹具可以继续字节比较。
- 对允许精度变化的环/预算组，不能把 IR 不同自动判错，也不能仅凭 IR verifier 通过认定正确；需要手工语义夹具、有限模型或可执行行为检查，并报告优化质量差异。
- VM 回放是按参数键查表，不是顺序消费日志。每个策略需要足够的 callback 键；旧策略录制的 cblog 缺少新策略所需键，应标记为回放覆盖不足，不能伪造默认结果或算成缓存失败。
- 合成测试用完整、确定性的类型模型供各策略查询；真实 record/replay 用匹配版本和配置验证。分别记录 callback 次数与不同键数，不要求各策略调用次数相等。
- 在不同进程地址布局下重复回放，检查数据结构迭代顺序是否改变 callback 键集合。稳定插入顺序本身不足以抵消来自不稳定上游遍历的影响。

## 7. 诊断与正式计时分开

现有 benchmark 脚本在计时模式开启 `-jeandle-java-type-stats`，并打印统计；其结果应称为“带统计的进程墙钟时间”。新实验分两遍：

| 模式 | 开关与用途 |
| --- | --- |
| 正确性/诊断 | 开启统计、独立冷参考、IR verifier；记录下面的结构计数，不据此做最终性能排名 |
| 正式性能 | 关闭 stats、verification、debug logging 和统计打印；同样输入、策略、随机种子；只在外层计时 |

必需指标：

- 主指标：完整轨迹时间、真实 pass/完整 pipeline 的进程时间；与 FULL、S0 的配对差异。
- 查询：顶层请求数；分层真实计算次数；递归与顶层命中分别计数；预算/环事件及语义精度。现有 BaseHits 仅覆盖 base-only 查询，不能直接当作所有 Base 子查询命中率。
- 失效：根数、不同值访问数、use/依赖边访问数、入队次数、最大工作队列、实际扫描槽位、分层逻辑失效数、物理回收数、回退原因。
- 复用：被保留且后来实际命中的条目数、失效后又被查询并重算的条目数。累计 retained 不等于节省的计算量。
- 内存：分层容量/字节估计、反向依赖边数、旧 epoch 条目、分配次数和高水位；独立进程的峰值 RSS 为补充，不能单独代表缓存占用。
- 尾部：诊断运行可采集批次延迟。只有足够多批次时报告 p95/p99；30 次进程样本不足以给出可信的 p99。

不把“结果没有变化”直接计作误失效：事实变了但结果偶然相同，不代表原条目可在不验证的情况下安全保留。精确的保留能力断言应来自手工已知独立的依赖结构。

## 8. 公平、可复现的测量流程

1. 在每个候选上完成正确性矩阵和相关 lit 套件；无 oracle 覆盖的 skip 单独列为未验证。
2. 正式速度使用相同 Release 配置；断言/ASan/UBSan 构建用于正确性与生命周期诊断，不与 Release 速度混排。
3. 固定机器、CPU affinity（环境支持时）、并行度、输入及 callback 数据；记录编译器、CMakeCache、CPU/系统和运行命令。不要一边构建一边计时。
4. 每个 case 每种策略先预热，初始可用 3 次；然后至少 30 个配对轮次，每轮随机排列策略，保留固定种子。计时顺序和硬件缓存预热规则对所有候选相同。
5. 极短进程由启动/解析主导时增加每次输入的工作量，另用进程内微基准确认机制；不要简单扣除一个空进程时间后当成真实 pass 时间。
6. 报告每个 case 的中位数、绝对差值、速度比与配对 bootstrap 95% 区间。轮次存在明显漂移/相关性时增加独立 session 或使用分块重采样，不把单次会话的区间解释成跨机器保证。
7. 区间跨零记为“本次未能区分”，不记为稳定收益。需要继续采样时预先定义第二阶段批次，不反复跑到出现显著结果才停止。
8. 保留逐样本数据和失败样本；允许的异常剔除规则预先声明，不能因某次慢而事后删除。
9. 至少在第二个独立 session 验证入选候选；真实验证集保持冻结。大量扫描参数的探索结论必须在留出样本确认，避免挑最有利 case。
10. 记录 HEAD、含 staged/unstaged 的补丁、相关 untracked 新测试/代码、源码/opt/输入/cblog/脚本哈希。基准启动和结束都检查身份未变化，并保留构建日志保证二进制确实来自记录的源码。

建议输出结构：

```text
run-id/
  manifest.json
  source.patch
  inputs/                  # IR、callback model/cblog、trace、seed
  correctness.json         # pass/fail/unverified + oracle 类型
  diagnostics.json         # 结构计数与内存
  samples.csv              # case、strategy、session、round、time
  summary.json
  failures/                # 可重放的最小复现
```

## 9. 状态机随机测试作为第二道防线

在定向测试稳定后增加受限生成器：先仅生成合法的无环参数/select/cast/PHI CFG，操作为 query、add/remove type fact、replace operand、RAUW、delete dead value、legal CFG edit。用结构化修改保证类型、支配和 PHI predecessor 一致，每步提交后 verifyFunction。

初期建议固定 100 个种子、每个 50 个事件，作为可控的 nightly 起点；运行时长评估后再扩展。发现失败时保存 IR、事件序列和 seed，并用保持 IR 合法性的简化器缩减事件与图。后来再把循环作为单独生成域加入，使用相应 oracle。

增加变形关系：

- 相同逻辑批次在“无中途查询”条件下，合并通知与逐项通知的完整无环结果一致；修改本身仍按相同顺序执行。
- 插入对目标查询无影响的独立子图，不改变其完整结果。
- 冷启动、合法预热、重复查询对完整无环用例返回相同结果。
- 一批修改和逆修改后，在最终 IR/VM 状态相同的条件下返回同样的完整结果。

涉及提前删除的批次要在所有根仍存活时收集依赖；不能保存已删除的裸指针，等批次末才通知。

## 10. 如何由测试结果选择设计

正确性是硬门槛。性能、内存与实现复杂度用同一组固定样本评估，优先选择在目标 workload 上有可重复净收益的最简单方案。

| 观测结果 | 倾向的选择 |
| --- | --- |
| P1 中 A 固定而 S0 随 N 增长，S1 消除该趋势 | 采用逐键 Base 删除 |
| P2 高 C 明显获益，但低 C 查询/内存回退 | 分组方案按实际 C 分布评估，必要时小组使用短数组 |
| P3 共同下游重复遍历占主要成本 | 优先批量通知与入队去重，不必先换缓存布局 |
| P4 失效入口很快，但查询/销毁总时间未下降 | epoch 只是推迟成本，不据此采用 |
| P5 物理条目或依赖边随轮次持续增长 | 回收策略不合格，即便短跑很快也不采用 |
| P6 SSA 图很大、实际缓存依赖很少，且真实回放频繁出现 | 才有充分理由评估 S4 的反向依赖图 |
| P7 无修改或低复用场景大幅变慢 | 查询侧维护过重，需要减轻或放弃该设计 |
| 合成输入获益，完整 pipeline 无收益 | 暂不宣称产品收益；检查热场景是否被提前优化消除 |

性能验收阈值在实验前定：例如把加权完整编译时间至少降低 3%、关键小方法组退化不超过 2%、缓存内存增加不超过 10% 作为讨论起点。这些数值需要结合噪声和产品目标调整，不能冒充行业标准，也不能等看完结果再选阈值。无真实样本权重时只报告各组结果和 Pareto 取舍，不制造一个等权平均总分。

优先落实的最小版本：C01/C02/C04/C07/C09/C10/C14/C18/C19/C20，P1/P2/P3/P4/P5，以及 TCE→CHA、CFF、RecoverTypeInfo、RepeatedCFF 的真实 pass 回归。先比较 S0 和 S1，再由数据决定是否实现 S2/S3/S4。

## 11. 已核对的现有代码与测试入口

- [现有性能脚本](https://github.com/Atm2086/jeandle-llvm/blob/357604c7724e49eace6fbfa42e4f671b12b5ff98/llvm/utils/jeandle/benchmark-java-type-invalidation.py)：已有源码/二进制记录、随机配对轮次、bootstrap、输出对照；需要拆分 stats 与正式计时并扩展场景。
- [JavaTypeQueryTest.cpp](https://github.com/Atm2086/jeandle-llvm/blob/357604c7724e49eace6fbfa42e4f671b12b5ff98/llvm/unittests/IR/JavaTypeQueryTest.cpp)：已有 RAUW、CFG、guard、回退及环预算测试；可抽公共驱动器。
- [LVI 相关失效测试](https://github.com/Atm2086/jeandle-llvm/blob/357604c7724e49eace6fbfa42e4f671b12b5ff98/llvm/unittests/IR/JavaTypeQueryTest.cpp#L762)：当前 DereferenceChangeDropsContextualResults 使用 nullptr oracle，验证的是清表行为；还需实际 LVI 的语义变化用例。
- [JavaTypeAnalysis.cpp](https://github.com/Atm2086/jeandle-llvm/blob/357604c7724e49eace6fbfa42e4f671b12b5ff98/llvm/lib/Analysis/Jeandle/JavaTypeAnalysis.cpp#L139)：现有冷热检查共享 DT/LVI，不能替代独立分析参考。
- [统计接口](https://github.com/Atm2086/jeandle-llvm/blob/357604c7724e49eace6fbfa42e4f671b12b5ff98/llvm/include/llvm/Analysis/Jeandle/JavaTypeAnalysisStats.h)：注意 BaseHits 与累计 retained 的口径。
- [VMCallback 合同](https://github.com/Atm2086/jeandle-llvm/blob/357604c7724e49eace6fbfa42e4f671b12b5ff98/llvm/include/llvm/IR/Jeandle/VMCallback.h)：编译内纯函数、按参数键回放和迭代顺序约束。

本地旧的 V1 检验文档与 `build_shells/test-javatype-cache.sh` 有针对旧实现的计数/开关假设，实施时必须按当前契约更新，不能把旧的 clears/hits 固定数字直接当作新设计验收标准。
