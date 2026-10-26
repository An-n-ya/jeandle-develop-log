# JavaTypeAnalysis 最终完整方向

## 1. 最终目标

为 Jeandle 的 Java 类型分析建立一个分层、依赖感知、可跨 Pass 复用的分析系统。在不改变现有 `jeandle::getJavaType` 语义的前提下，实现以下能力：

- 完全相同且依赖仍然有效的完整查询平均 `O(1)` 命中；
- 不同上下文之间复用同一个 Value 的基础类型；
- 在相同程序点或相同支配事实下复用上下文锐化结果；
- 复用 PHI、Select 和转发指令的递归子问题；
- 缓存 JVM 类型关系，减少 `IsSubtype`、`GetCommonSuperKlass`、`IsEffectivelyFinal`、`GetOopKlass` 等 callback；
- 在 AnalysisManager 和安全的 driver 生命周期内跨 Pass、跨轮次复用；
- IR、CFG 或 VM 假设发生变化后，只失效真正依赖变化内容的结果；
- 通过正确性校验和分层性能统计，证明缓存结果等价于旧查询并具有实际收益。

最终系统不是单个 `DenseMap<Value *, JavaType>`，而是一套由完整查询缓存、基础类型缓存、上下文锐化缓存、递归子问题缓存、JVM 类型关系缓存和依赖失效机制组成的增量分析。

## 2. JavaType 的语义定义

`JavaType` 回答的问题是：

> 在指定程序位置，如果某个 LLVM SSA Value 表示一个非空 Java 对象，当前能够证明它属于哪个 Java 类、是否为精确运行时类型，以及一定不属于哪些类？

结果由以下事实组成：

- `Klass = K`：对象已知是 `K` 或 `K` 的子类；
- `Exact = true`：对象的运行时类型精确等于 `K`；
- `ExcludedKlasses`：对象一定不是这些类的实例；
- `JavaType` 当前不表示 nullability。

完整结果可以理解为：

```text
FullType(V, C) = typeIntersect(BaseType(V), SharpenedType(V, C))
```

其中：

- `BaseType(V)` 从 Value 自身及其数据来源获得上下文无关事实；
- `SharpenedType(V, C)` 从到达查询位置时必然成立的控制流约束获得事实；
- PHI、Select 等多来源值使用 `typeUnion` 合并候选类型；
- 同时成立的基础事实和路径事实使用 `typeIntersect` 合并。

## 3. 语义影响因素与工程缓存键

从宏观语义上，可以写成：

```text
T = Query(
    Function,
    IRState,
    Value,
    Context/Edge,
    CFG/Dominance,
    VMTypeState
)
```

这个公式描述“哪些状态可能改变答案”，不表示每条 entry 都要把这些对象全部放进哈希键。工程实现应拆成：

```text
查找身份：    (CanonicalValue, CanonicalContext)
外层作用域：  Function
有效性条件：  实际依赖的 IR、CFG、DT 和 VM 事实仍然有效
缓存内容：    JavaType、计算状态以及依赖信息
```

各因素的具体含义如下。

### 3.1 Function

Function 是 JavaType 分析的所有权和隔离边界。Argument attribute、指令、CFG 和 DominatorTree 都属于特定 Function。

Function Analysis 已经隐含当前 Function，因此通常不必把 `Function *` 重复放入每条 entry 的 key。提升到 Module 级也不会自动延长结果的安全生命周期，反而会扩大失效、并发和 Value 指针生命周期问题。

### 3.2 Value

Value 表示“正在询问哪个 SSA 对象值”。入口处可使用 `stripPointerCastsAndAliases()` 规范化能够证明等价的指针包装。

但 `Value *` 只是身份，不代表不可变版本。指令 operand、PHI incoming、attribute 或 metadata 改变后，指针地址可能不变而语义已经改变，因此完整缓存键不能只有 `Value *`。

两个 Value 最终都得到相同 `Klass`，也不表示它们是同一对象或拥有相同上下文事实。只有存在可证明的同源关系时才能共享 Value 层结果；独立 Value 之间最多共享 JVM 类型关系查询。

### 3.3 IRState

IRState 是当前 Function 代码状态的总称，包括：

- 指令是否存在，opcode 和 operand 是否改变；
- Argument、Call/Invoke 的 attribute 是否改变；
- Load 的 metadata 是否改变；
- PHI 的 `(incoming value, incoming block)` 是否改变；
- Select 的候选 operand 是否改变；
- branch condition、successor 和 CFG 是否改变。

并非 Function 中的任意修改都会影响每条 JavaType。最终方向追踪某次计算实际读取的 IR 子图，使无关指令修改不必清空全部缓存。

### 3.4 Context / Edge

Context 表示“在程序的哪里查询”。当前实现的普通查询主要以 `Context->getParent()` 所在 BasicBlock 为程序点，因此同一块中的普通查询通常具有相同上下文语义。

PHI incoming 是边语义：类型事实可能只在 `IncomingBB -> PhiBB` 这条边上成立。因此 PHI 子查询需要记录 incoming block、目标 block 和对应边，而不能只记录 PHI Value。

如果未来分析支持同一 BasicBlock 内不同指令位置的事实，Context 的规范形式需从 `BasicBlock *` 扩展为真正的程序点。

### 3.5 CFG 与 DominatorTree

CFG 表示程序可能采取的路径；DominatorTree 是从 CFG 推导出的“哪些路径必然经过”的查询索引。上下文锐化沿 DT 的直接支配链查找条件分支，并使用边支配判断某个类型检查的成功或失败结论是否在查询点必然成立。

DominatorTree 不是独立的业务事实，不应因为 DT 对象地址不同就产生不同缓存键。它应作为派生分析依赖：CFG 改变后必须同步更新或失效 DT，依赖旧支配关系的锐化结果也必须失效。

### 3.6 VMTypeState

VMTypeState 表示 JVM 提供的类型层次和编译期假设。JavaType 计算可能依赖：

- `IsSubtype(A, B)`；
- `GetCommonSuperKlass(A, B)`；
- `IsEffectivelyFinal(K)`；
- `GetOopKlass(id)`；
- `IsInterface(K)` 等辅助关系。

最终系统应缓存具体 callback 及参数的结果，并在 callback 合同保证稳定的生命周期内复用。对于可能受类加载或编译假设影响的结果，需要 VM generation、assumption token 或编译生命周期边界来保证有效性，不能默认永久有效。

## 4. 当前实现中的实际依赖

### 4.1 基础类型依赖

`BaseType(V)` 当前可能读取：

- Argument 上的 `java-klass`、`java-klass-exact` parameter attribute；
- Call/Invoke 上的 `java-klass`、`java-klass-exact` return attribute；
- Load 上的 `!java-klass`、`!java-klass-exact` metadata；
- 常量 oop handle 及其 `GetOopKlass` 结果；
- PHI 的全部 incoming value；
- Select 的 true/false value；
- BitCast、AddrSpaceCast、Freeze 的源 operand；
- 类型合并过程中使用的公共父类、子类型和接口关系。

依赖记录必须包含“事实不存在”的观察。例如一次查询因为 Argument 不含 `java-klass` 而返回 unknown，后来新增 attribute 时，旧 unknown 同样必须失效。

### 4.2 上下文锐化依赖

`SharpenedType(V, C)` 当前可能读取：

- 查询 Context 所在 BasicBlock；
- PHI incoming 的源块、目标块和 CFG 边；
- Context 到 Function 入口之间实际遍历的 DT 支配链；
- 支配块的 conditional branch、condition 和 successor；
- condition 中的 `jeandle.check_instanceof`、ICmp、整数 cast、And、Or、Xor、PHI、Select 等表达式图；
- 被检查对象和查询 Value 的规范化身份；
- check_instanceof 的目标 Klass 常量；
- null-check path 和边支配结论；
- `IsSubtype`、`GetCommonSuperKlass`、`IsEffectivelyFinal` 等 JVM 关系。

理想失效追踪的是这些实际读取的依赖，而不是笼统地认为 Function 中所有 IR 都影响结果。

## 5. 最终分层缓存结构

### 5.1 完整查询缓存

```text
(CanonicalValue, CanonicalContext/Edge) -> FullJavaType
```

用于满足完全相同语义查询平均 `O(1)` 命中。完整结果依赖基础结果、锐化结果以及二者合并时使用的 JVM 类型关系。

### 5.2 基础类型缓存

```text
CanonicalValue -> BaseJavaType
```

同一个 Value 在多个上下文查询时复用 attribute、metadata 和数据流传播结果。基础类型通常不依赖 Context 和 DT，因此 CFG-only 修改不应自动破坏所有基础结果。

### 5.3 上下文锐化缓存

```text
(CanonicalValue, ContextBlock/Edge) -> SharpenedJavaType
```

复用支配链遍历、branch condition 追踪和路径类型约束。未来可继续拆分为支配链前缀或单个分支事实，以扩大相邻程序点之间的复用。

### 5.4 PHI、Select 与转发子问题缓存

递归计算缓存每个 incoming、arm 或源 operand 的子结果，父节点只负责按照当前结构进行 union/intersection。这样不同顶层查询遇到相同子图时，不必重复遍历整个 IR。

对于 `bitcast/addrspacecast/alias` 等可证明同源的 Value，可规范化到共同来源。Freeze、PHI、Select 是否能进一步视为等价来源，必须由各自语义证明，不能仅因最后得到同一 Klass 就合并。

### 5.5 JVM 类型关系缓存

```text
(IsSubtype, A, B, VMEpoch)           -> bool
(GetCommonSuperKlass, A, B, VMEpoch) -> Klass
(IsEffectivelyFinal, K, VMEpoch)     -> bool
(GetOopKlass, id, VMEpoch)           -> Klass
```

关系缓存可以被不同 Function、Value 和 JavaType 层共同使用。它适合放在比完整 JavaType Function Cache 更高的编译生命周期所有者中，但前提是 callback 合同、并发和 VM 假设失效规则明确。

## 6. Entry 状态与依赖图

理想 entry 在概念上包含：

```text
Entry {
  QueryKey
  State: Absent | Computing | Complete
  JavaType Result              // Complete 时有效，包括最终 unknown
  IRDependencies
  CFGEdgeDependencies
  DominanceDependencies
  VMRelationDependencies
  RevisionOrEpoch
}
```

递归状态必须区分：

- `Absent`：尚未计算；
- `Computing`：正在递归计算，仅用于 PHI/循环检测；
- `Complete(JavaType{})`：计算已经完成，结果确实为 unknown。

`Computing` 不能被当作最终 unknown 长期保存，否则循环 PHI 的临时状态会污染后续查询。

依赖关系形成有向图：

```text
attribute / metadata / operand / edge / VM relation
                    ↓
        BaseType 或 SharpenedType
                    ↓
              FullJavaType
```

系统还需要反向索引，使某个依赖变化时能找到所有下游 entry 并传播失效。

## 7. 失效策略

### 7.1 粗粒度阶段

为 Function 维护统一 IR epoch 或在 Pass 修改后调用 `clear()`。任何潜在相关修改都使全部 Function entry 失效。

优点是正确性容易建立；缺点是无关修改也会损失命中率。统一 IR epoch 是快速、保守的有效性边界，不等于细粒度失效。

### 7.2 细粒度最终阶段

按照实际依赖处理修改：

- attribute/metadata 改变，只失效依赖该来源事实的基础和完整结果；
- PHI incoming 改变，失效该 PHI 及依赖它的父级子问题；
- branch condition 或 successor 改变，失效依赖该分支事实的锐化结果；
- CFG/DT 改变，失效受影响的支配关系和锐化结果，基础结果尽量保留；
- 某个 VM 关系失效，失效关系缓存及所有使用它的 JavaType 结果；
- 删除 Value 前移除相关 entry，或使用能够感知 Value 删除/替换的安全句柄机制，避免悬空 `Value *`。

在单个 Pass 的 `run()` 内，AnalysisManager 尚未执行 Pass 返回后的失效流程。任何“边查询边修改 IR”的消费者都必须使用明确的修改通知、局部失效或保守 `clear()`，不能等待 PassManager 自动处理。

## 8. 生命周期与跨 Pass 复用

完整 JavaType 缓存的自然边界仍是 Function Analysis：

- Function 是 Value、CFG 和 DT 的共同作用域；
- 同一个 Function Analysis 结果可在被正确 preserve 的多个 Pass 之间复用；
- driver 轮次间只有在同一个 AnalysisManager/分析所有者仍存活、IR 身份和依赖仍有效时才能复用；
- 如果 driver 重建 AnalysisManager，需要显式提升缓存所有权或传递分析状态，不能仅通过改成 Module Analysis 假装旧 Value 仍然有效；
- JVM 纯类型关系缓存可使用更高的编译级生命周期，与 Function JavaType cache 分离。

跨 Pass、跨轮次复用的前提始终是“依赖有效”，而不是单纯延长对象存活时间。

## 9. 正确性不变量与验证

核心正确性不变量是：

```text
CacheQuery(V, C, CurrentState)
    ==
FreshLegacyGetJavaType(V, C, CurrentState)
```

最终系统应保留以下验证能力：

- cache disable：统一新接口但绕过缓存，用作 A/B 基线；
- shadow verify：hit 时调用旧算法重算并逐字段比较；
- known、unknown、只有 exclusions 的结果都参与验证；
- 覆盖不同 Context、PHI/循环、incoming edge、cast 规范化和 Value 删除；
- 覆盖 attribute/metadata、operand、CFG、DT 和 JVM 假设修改后的失效；
- 覆盖 TypeCheckElimination 与 CHADevirtualization 在 Pass 内修改 IR 的场景；
- 在旧函数仍作为语义 oracle 的阶段，不改变旧算法本身。

## 10. 性能目标与度量

需要分别测量每个缓存层，而不能只统计一个总 hit rate：

- 完整查询 hit/miss；
- 基础类型 hit/miss；
- 上下文锐化 hit/miss；
- PHI/Select/转发子问题 hit/miss；
- JVM 关系 hit/miss 和实际 callback 次数；
- 避免的 IR 节点遍历数、DT 节点遍历数；
- hit 查找耗时、miss 计算耗时、失效维护耗时；
- entry 当前数量、峰值和依赖图内存；
- JavaType 接口总耗时；
- TypeCheckElimination、CHADevirtualization Pass 耗时；
- 整体编译时间与代码质量是否回退。

最终性能目标不是追求表面 hit rate，而是在保证结果等价的前提下，使：

```text
缓存查找与维护开销
    <
被避免的 IR/DT 遍历和 JVM callback 开销
```

## 11. 从 V1 到最终方向的演进顺序

1. 建立 Function Analysis 和完整查询缓存，保留旧函数作为 miss 路径及正确性 oracle；
2. 获取真实 workload 的查询重复度、上下文分布、clear 频率和 callback 成本；
3. 拆分 `BaseType` 与 `SharpenedType`，扩大不同上下文之间的基础类型复用；
4. 缓存 JVM 类型关系和 PHI/Select 递归子问题；
5. 引入 IR/CFG/VM 依赖记录及反向索引；
6. 将统一 clear/epoch 逐步替换为局部失效；
7. 在生命周期和假设机制明确后扩展到安全的 driver 轮次及更高层 VM 关系复用。

V1 是最终方向的正确性基线和测量平台，不是最终缓存算法本身。最终方向在 V1 接口和生命周期框架上增加分层复用与依赖感知失效，而不是推翻旧 `getJavaType` 的分析语义。
