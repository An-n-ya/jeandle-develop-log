# JavaType V2 性能回退：源码归因分析

分析日期：2026-10-30。

## 证据与范围

- 输入报告：`java-type-v2-cache-benchmark-report.md`。
- 本机 `/Users/annya/src/jeandle/jeandle-llvm` 与 SSH 测试机当前源码均为 `ad38f632672c881708d0894acf56b72414c095f2`，工作区干净。
- SSH 基线源码为 `ac545bb21e8931152ad9149e01f8304b214dbd91`。
- 本机保留的 `CachedJavaType.cpp` 与远程实测基线文件 SHA256 一致：`223a7aefad184d3aaf12ec57571d8c882b27059858f5a09e884ec753c9f26c19`，因此下文引用该本机文件作为基线。
- 读取并核对了 `/tmp/null-edge-ab-selective/manifest.json`、诊断 stderr、测试输入和补充实验报告。没有修改源码、远程环境或重新运行性能实验。
- GitHub compare 页面未能读取；实现结论来自上述已核对版本的完整本机源码及 SSH 只读证据。

## 核心结论

选择性失效确实保存了 Base 结果，但 V2 在命中之后仍增加了计算，并为没有复用的 Facts/Final 支付建表和销毁成本。最值得优先处理的是：

1. Base 命中后依然递归重算 select 的 value dimension。
2. Final 每次插入重新扫描依赖图、建立反向索引，下一次改写又可能因基本块依赖而删除。
3. null-edge 的负结果新增无条件支配树兜底遍历，重复扫描逐渐变长的 invoke 链。
4. Facts 的两张边表大量缓存廉价的空/false 结果，并在每次通知时全清。

这不只是缓存容器更重：V2 相比基线还改变了查询算法和精度处理。现有结果不足以将每个因素分别归因到多少毫秒，以下把确定的执行路径与待消融验证的性能贡献分开。

## 1. Base 命中不再意味着结束：最明确的深链放大

基线 `CachedJavaType.cpp:1434` 的 valueDimension 仅对 PHI 特殊处理，其余值直接进入共享 Base memo。深 select 链预热后，根值命中即可返回。

V2 `CachedJavaTypeV2.cpp:1931` 的逻辑是：

1. 查 Base。
2. 除非类型 Exact 或没有结构输入，否则继续执行。
3. 递归访问 select/identity/freeze 的输入；对输入求 facts，并做 typeUnion/typeIntersect。
4. 把结果放入查询局部的 `Q.ValueTypes`。

`Q.ValueTypes` 在每次顶层查询构造 `JavaTypeQueryContext` 时重建，不能保存上一次调用点的结果。`getBaseTypeInputs` 在 `CachedJavaTypeV2.cpp:184` 明确展开 select 的两臂。

对报告中的线性 select 链，深度 D 时，每个顶层查询会调用 Base 查询约 `2D+1` 次。首个根查询为 miss，随后递归使用 SCC 求解已经填好的 Base 结果。因此 F 个函数、每函数 C 个调用点时，命中数为：

`F × [C × (2D+1) − 1]`

| workload | C | D | 预测 Base hits | 原始诊断 hits |
|---|---:|---:|---:|---:|
| deep-static | 16 | 64 | 2,112,512 | 2,112,512 |
| wide-static | 64 | 16 | 2,161,664 | 2,161,664 |
| leaf-static | 32 | 0 | 31,744 | 31,744 |

三项精确吻合，构成比“高命中率”更有解释力的证据。高命中数的一部分恰恰来自重复展开。这里的 129 倍是深度 64 下热查询的 Base 调用次数量级对比，不是总查询或整个进程的加速空间。

这与深链约 94%～99% 回退、浅层约 29% 回退的方向一致，但不能据此独占归因；深度变化还会改变依赖维护等成本。

建议：为能够证明没有额外上下文细化的表达式提供直接返回 Base 的快路径；或者为有明确依赖/预算语义的 value dimension 设计复用策略。不能直接让所有 select 返回 Base，否则可能损失这次新增的类型精度。

## 2. Final 建立成本很高，而且依赖粒度让条目很快失效

`CachedJavaTypeV2.cpp:2029` 在 Final 启用时，每次完成顶层计算都尝试插入。

`JavaTypeCacheV2.cpp:52` 的 collectFinalDependencies 不使用温热的 Base 结果作为依赖摘要，而是：

- 遍历根值的 operand 图；
- 加入所有 null-edge 观察涉及的值和块；
- 从定义块、上下文块和观察块，沿 CFG 前驱闭包扩张；
- 即使查询因预算停止，依赖收集仍按自己的 4096 值/块、16384 边上限工作。

`JavaTypeCacheV2.cpp:349` 随后为每个依赖建立 `ByValue[Value] -> DenseSet<Key>` 和 `ByBlock[BB] -> DenseSet<Key>`。

深度 64 的链至少涉及 64 个 select 和 2 个参数，超过 Entry.Values 的 8 个内联槽位，必然需要额外存储。多个反向 DenseSet 及删除路径会增加分配和哈希维护；具体分配次数尚未用分配器剖析确认。

删除也很昂贵：`JavaTypeCacheV2.cpp:370` 的 erase 遍历条目的全部 Values/Blocks，从每个反向集合删除 key，空集合再销毁。

依赖范围还很保守：`JavaTypeCacheV2.cpp:539` 把修改指令所属块加入 AffectedBlocks；`JavaTypeCacheV2.cpp:455` 按块索引淘汰条目。查询发生在调用指令所在块，该上下文块也在 Final 依赖中，随后的调用改写就足以淘汰它，即使 Base 的 select/参数完全未变。

原始 deep-static 诊断显示：16,384 次查询、16,384 次 Final miss、16,384 条 Final 失效、0 hits；Base 则没有任何条目被失效。这说明相同的查询一直保留 Base，却重复建设和销毁 Final。

还要注意 key 的复用机会：Final key 是 `(Value, ContextBB)`。测试的相邻 invoke 使用不同的上下文块；即使条目不失效，也不能假定下一个调用点会命中前一个 Final。仅调整失效范围未必能让这些输入受益。

建议先做关闭 Final 的消融，保留 Base/Defined/Facts，测试是否明显恢复。若成立，再考虑按重复查询频率决定是否收录、用依赖摘要减少二次遍历、降低反向索引分配成本。收紧块依赖必须保留隐式 LVI/负事实依赖的正确性，不能简单删除块依赖。

## 3. oracle 返回 false 后，新增一次支配树向上扫描

基线 `CachedJavaType.cpp:1276` 在可达性检查后直接返回 oracle 答案。

V2 `CachedJavaTypeV2.cpp:752` 则在 oracle 没有证明 null 后继续调用 isNullCheckPath；后者在 `:708` 沿 idom 一直走到根。

deep-static 的 CFG 是逐个 invoke/next 串联，大部分 terminator 不是条件分支。兜底扫描不会得到 null 证明，但仍逐层访问祖先。

每个后续调用点的 factsAt 又会递归处理所有先前块。对理想的 C 个调用点线性链：

- 一次完整扫描所有调用点的前驱边工作合计约为 O(C²)；
- 如果每条被访问的边还向上走 O(C) 的支配链，额外工作可达到 O(C³)。

这是一种该输入形状下的放大量级推导，不是全部 CFG 的复杂度定理，也没有以 profiler 证明其实际 CPU 占比。

报告中“预过滤后 oracle 调用为零”不能排除这条路径。至少从实现看，外层 computeNullEdge 在 oracle 返回 false 后仍进入兜底；需要明确零计数指的是昂贵 LVI 求解还是整个外层 helper。不能把没有昂贵 oracle 调用等同于没有 null-edge 工作。

建议给 idom 访问次数、兜底请求/命中数增加独立诊断，再做该路径的隔离实验。优化时应缓存合适粒度的结构性 null 事实或使用经证明完备的预索引，而不是删掉为正确性/精度修复加入的兜底。

## 4. Facts 把廉价结果变成两份缓存维护

基线缓存的是 `(V, BB)` 的完成 PathFacts。V2 改为 guard 和 null 两张 `(V, From, To)` 表，但 factsAt 的中间结果仍只在查询局部 Q.Processed 里。

`CachedJavaTypeV2.cpp:765`、`:1795` 每次做边查询时先查表，miss 后计算，再插入。对于没有 guard 的 invoke 边，computeEdgeGuard 本可迅速返回空类型；现在仍为这个空结果维护 guard 表。false 的 null 结果也要单独存储。

`JavaTypeCacheV2.cpp:581` 每次普通失效无条件清空 Facts。deep-static 的 122,880 次 guard 计算加 122,880 次 null 计算，恰好得到报告的 245,760 条边记录，且没有命中。

因此报告所说“翻倍”在边记录数量上成立，但不能理解成总查询成本简单翻倍；旧 PathFacts 的缓存语义与新两张边表也不同。

可消融地先关闭共享边表的发布，保留查询局部 Processed，以测量跨查询表的净收益。若要对 invoke 等无条件控制流的 guard 直接返回空事实，应保留原有值归一化和定义性语义。

## 5. 失效次数与统计口径的补充

CHA 静态 linkTo 改写有两处通知：`CHADevirtualization.cpp:350` 的改写前通知，以及 `:493` 的旧调用 RAUW/删除前通知。deep-static 原始计数确认为每 16,384 次查询发生 32,768 次通知。

不能直接删除第二次通知：两个阶段之间可能发生变化，必须先验证一次通知能否覆盖完整旧 use 闭包、目的块及随后创建的 IR。它是进一步优化点，但本例最大成本更可能来自第一次通知前已经做了昂贵的缓存建设；需要消融或剖析确认。

不优先怀疑日志/计时：`JavaTypeAnalysis.cpp:134` 在没有 Observer 时直接返回 Query，不读取时钟。报告主计时关闭 stats，因而诊断事件不能解释主测量的 29%～99% 回退。不过，带 stats 的 query/invalidation 时间只能用于定位方向，不能与无 stats 的进程 CPU 时间相减得到严格的开销分摊。

## 建议的验证顺序

固定同一 V2 提交、同一求解语义，分别对以下因素做单变量消融：

1. **Final 关闭**：保留 Base/Defined/Facts；测依赖收集、反向索引和条目维护的净成本。
2. **跨查询 Facts 发布关闭**：保持 query-local Processed 和计算逻辑，测 guard/null 两张表的净成本。
3. **select value dimension 快路径**：先诊断访问数与上下文细化收益，再实现有证明前提的快路径。
4. **结构性 null 兜底诊断/优化**：统计 idom 总访问数与真正获得证明的次数，测嵌套扫描占比。

每步仍检查 A/B IR 及相关正确性测试；对更精确的求解语义不能只依赖旧基线 IR 完全相同，还应保留新版本的 oracle/预算/PHI/freeze/失效专项验证。真实 JVM 样本应同时观察编译 CPU 和优化后代码效果。

最有希望的方向是保留已验证有用的 Base 选择性失效，让低复用负载接近 Base-only 的低开销路径，再对确实可复用的上下文结果按需付费，而不是先扩大缓存和维护范围。
