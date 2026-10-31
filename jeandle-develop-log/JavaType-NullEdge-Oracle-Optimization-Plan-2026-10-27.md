# JavaType null 边判定（isNullEdge）的必要性与优化计划

日期：2026-10-27。状态：**待验证计划**。本文只基于本地源码只读分析（未构建、未运行、未采样），性能收益全部为待测假设；触发点是用户在本机 profiling 中观察到 `factsAt → isNullEdge → LVI::getPredicateOnEdge` 构成主要瓶颈。文中不含任何已测得数字。

前置材料：

- [性能采样执行报告](JavaType-Cache-Perf-Profiling-Execution-2026-10-23.md)（本报告已把 LVI 列为上下文查询的主要剩余成本）
- [LVI null-edge 优化代码审查](JavaType-LVI-Optimization-Review-2026-10-23.md)（同为 LVI 成本来源的调用链分析）
- [LVI Argument/Undef 优化执行报告](JavaType-LVI-Argument-Undef-Optimization-Execution-2026-10-23.md)（**回退教训**：通用"先提取约束"方案在共享布尔 DAG 压力输入上回退约 35.5% CPU，最终只保留 Argument condition 快速路径）
- [跨 pass 生产性能](JavaType-Cross-Pass-Production-Performance-2026-10-26.md)

## 1. 依据与源码身份

- 本地源码根：`/Users/annya/src/jeandle/jeandle-llvm`。
- 分支 `feat/javatype-selective-invalidation`，HEAD `7857d0e33777bcaea8012d3e4bf17c93eccafca3`，工作树干净（`git status --porcelain` 为空）。
- 文中行号**全部对应上述本地工作树**，不是服务器工作树；服务器状态需重新核对后再引用。

| 文件 | SHA-256（本地 HEAD） |
| --- | --- |
| `llvm/lib/Analysis/Jeandle/CachedJavaType.cpp` | `223a7aefad184d3aaf12ec57571d8c882b27059858f5a09e884ec753c9f26c19` |
| `llvm/lib/Analysis/Jeandle/LVINullEdgeOracle.cpp` | `abea3d83c59343b89fa6f7a7324bec7616b031915b216ff387842b773adfc667` |
| `llvm/lib/Analysis/LazyValueInfo.cpp` | `d1ce54cc6f01079e291dde2b5430a267007002fe620b2ff73fc2b83453989b19` |
| `llvm/lib/IR/Jeandle/JavaType.cpp` | `a32dda5470cf2f0af67558f9a3620b4058f1648fdc1cd4caafbf69ff44685b69` |
| `llvm/include/llvm/Analysis/Jeandle/CachedJavaType.h` | `a31e0270ee1a3e3148e912da43c8cff173bd298386d3d31422ae8ee98a990c65` |

证据边界：用户只提供了"`isNullEdge` 是 `factsAt` 的主要瓶颈"这一条性能观察，没有提供 oracle 调用次数、命中率、单次耗时分布。本文第 2 节的成本链解释来自源码阅读，第 4 节的收益排序来自对调用形态的推断，**都不是测量结论**。

## 2. 调用链与成本来源

```text
factsAt(V, BB)                                  CachedJavaType.cpp:1287
  for P in predecessors(BB)                     CachedJavaType.cpp:1333-1342
    isNullEdge(V, P, BB, Q)                     CachedJavaType.cpp:1274
      LVINullEdgeOracle::operator()             LVINullEdgeOracle.cpp:23
        [L0] 结构快路：From 终结指令直接测 icmp V,null
        [L1] LVI.getPredicateOnEdge(ICMP_EQ, V, null, From, To)
               → getValueOnEdge → getEdgeValue   LazyValueInfo.cpp:2065 / 1733
                   → getEdgeValueLocal（便宜）
                   → getBlockValue(From)（贵，需要 solve()）
                   → getPredicateResult → 一般返回 nullptr
phiValueType(PN)                                CachedJavaType.cpp:1368
  isNullEdge(Inc, IncBB, PN->getParent(), Q)   CachedJavaType.cpp:1398
```

| 位置 | 行号 | 观察 |
| --- | --- | --- |
| `factsAt` 前驱循环 | `CachedJavaType.cpp:1333-1342` | 每个非回边前驱**先**请求 null 证明，**再**递归合并路径事实 |
| `isNullEdge` | `CachedJavaType.cpp:1274-1281` | 只有可达性过滤，其余全部委派给 oracle；cached 版**没有** reference 版的结构兜底 |
| `LVINullEdgeOracle::operator()` | `LVINullEdgeOracle.cpp:23-70` | 指针规范化 + L0 结构快路 + L1 LVI 逐边查询；无自身缓存 |
| `LazyValueInfo::getPredicateOnEdge` | `LazyValueInfo.cpp:2065` | 逐边求 V 的格值，未局部判定时进入 `getBlockValue` + `solve()` |
| reference 引擎 `isNullEdge` | `JavaType.cpp:1033-1044` | oracle 之后还有 `isNullCheckPath` 支配链兜底；**与 cached 版语义不一致** |
| `typeUnion` 吸收性说明 | `JavaType.cpp:651` | `typeUnion({}, X) == {}`（第 3.2 节的核心依据） |

成本结构与上一轮 LVI 审查的结论一致：这个 oracle 要回答一个**布尔**问题，但通用 LVI 会去求解指针值的格信息，并在无法局部判定时触发跨函数的按需 `solve()`。而且这个 `solve()` 与 `factsAt` 自己的 CFG 递归互相交织，是最坏的一类"两层数据流套在一起"。

## 3. 第一部分：为什么一定要判 null 边

### 3.1 不是为了健全性

`isNullEdge` 的约定写得很明确（`CachedJavaType.cpp:1272-1273`、`JavaType.h:74-89`）：

> Only positive proof may return true; when in doubt, return false (keeping the edge is always sound).

即：**保留一条边永远 sound**，跳过一条**已证明**为 null 的边是精确的，跳过一条**未证明**的边才是不健全的。所以"判不判 null 边"是精度问题，"判错了"才是正确性问题。

设计注释（`CachedJavaType.cpp:1084-1096`）给出的精确性论证是：

1. `JavaType` 是**条件于非 null oop** 的类型描述（`JavaType.h:38-41`）；
2. 一条已证明 V 为 null 的边不携带任何非 null 类型约束；
3. 任何"V 在 B 处非 null"的动态执行都必然经由非 null 边到达 B；
4. 因此只对剩下的边取并集，仍然覆盖所有符合契约的执行。

### 3.2 但精度损失是"全有全无"，不是渐进的

```cpp
// JavaType.cpp:651
/// typeUnion treats unknown as absorbing (typeUnion({}, X) == {})
```

`factsAt` 的 join 里 **unknown 是吸收元**。而一条 null 边贡献的臂恰好几乎总是 `{}`：null 分支通常是 `throw NPE` / 异常调用，没有任何类型事实可推。

于是 Java 里最常见的 CFG 形状就会被抵消：

```text
      P: %c = icmp eq %V, null ; br i1 %c, %NullBB, %NonNullBB
     /                                                     \
 NullBB: ...throw NPE...                        NonNullBB: ...类型检查通过...
     \                                                     /
      +------------------> M <-----------------------------+

 factsAt(V, M) = join({} , "V is Foo") = {}        ← 不判 null 边时的结果
 factsAt(V, M) = "V is Foo"                        ← 判 null 边、且跳过 NullBB 之后
```

`phiValueType` 更敏感：`phi [null, entry], [obj, loop]` 会被 null 臂污染成 unknown，而这正是 Java 代码里最典型的 oop PHI 形态（`JavaType.h:105-109` 正是描述这个能力）。

**结论**：不判 null 边 ≈ 关掉 context-sensitive sharpening 的主要部分，而不是"略微变钝"。

### 3.3 反过来说：绝大多数 oracle 调用的产出是"什么都没证明"

指针值在一条边上被证明为 **null** 是罕见事件。因此：

- L1 层的 `getPredicateResult` 绝大多数返回 `nullptr` → oracle 答 false → 该次 LVI 求解是纯开销；
- 真正需要"是"的场合集中在两类形状：**(a)** `From` 终结指令自己就在测 `icmp V, null`（L0 已覆盖，不碰 LVI）；**(b)** 条件由**支配块**给出，例如 `%c = icmp eq %V, null; br i1 %c, %A, %C` 之后 `A: br label %B`，边 `A -> B` 的 null 性只能靠 V 在 `A` 末尾的块值推出（这是 L1 唯一真正不可替代的作用）。

这个分布决定了优化方向：**把提问次数砍下去**，而不是把每次提问做快。

### 3.4 实验 E0：先量化"值不值"

在改结构之前，用最小成本回答两个问题：不判 null 边能省多少时间？会丢多少精度？

```cpp
// 临时：把 oracle 换成恒 false（保留全部边，sound）
JavaType T = jeandle::getCachedJavaType(
    V, DT, Ctx,
    [](Value *, BasicBlock *, BasicBlock *) { return false; },
    Cache, Info);
```

测量项：

| 指标 | 含义 | 期望 |
| --- | --- | --- |
| 进程 CPU / `TotalQueryTimeNanoseconds` | 直接回答"省多少时间" | 若收益 < 5%，说明 profile 里的 `isNullEdge` 占比被其它成本掩盖，先做别的事 |
| `FinalTypes` 中 Known → Unknown 的条数 | 回答"丢多少精度" | 若近乎全部 Known 消失，说明 null 边判定是 sharpening 的前提，必须保留 |
| `NumCachedJavaTypeBudgetExhausted` 变化 | 排除预算干扰 | 应基本不变 |

同时补四个 stat（`JavaTypeAnalysisStats.cpp` 已有 `ALWAYS_ENABLED_STATISTIC` 体系）：

- `NullOracleCalls`：调用总次数
- `NullOracleStructural`：L0 结构快路解决的数量（**关键**：区分"调用多"还是"每次贵"）
- `NullOracleTrue`：答"是"的比例（预期很低）
- `NullOracleNanoseconds`：累计耗时

只有确定"L0 解决比例低、True 比例低、耗时占比高"同时成立，第 4 节的方案才值得投入。

## 4. 第二部分：优化方案

**总原则**：所有改动都只能让 oracle **少被问**，或让它**更早答 false**；任何让 oracle 更容易答 true 的改动都是健全性风险，一律不做。少于问只损失精度。

### S1：`factsAt` 里 join 一旦成 unknown 就短路（零风险，先做）

```diff
   JavaType Joined;
   bool First = true;
   for (BasicBlock *P : predecessors(BB)) {
     if (Q.DT.dominates(BB, P))
       continue;
     if (isNullEdge(V, P, BB, Q))
       continue;
     JavaType E = factsAt(V, P, Q);
     mergePathFacts(E, edgeGuard(P, BB, V, Q.DT));
     joinArm(Joined, First, std::move(E));
+    if (Joined.isUnknown())
+      break; // unknown 吸收：其余臂不可能改变结果
   }
```

正确性论证：`isUnknown()` 成立后，累加器是 `{}`（Klass 0、Interfaces 空、ExcludedKlasses 空）。此后 `typeUnion` 的两条分支（`JavaType.cpp:314` 双方 Klass 均 0 走 exclusion 交集、`JavaType.cpp:321` 单侧已知 Klass）都只能产出空结果，所以**输出与不短路严格相等**。

收益：只要块内出现一条 unknown 臂（Java 中极常见，null 分支/异常分支），该块剩余所有边的 `isNullEdge` 调用全部省掉。代价：后续前驱不再递归，少写一些 `PathFacts`（次要，且命中预算的路径本来也不贵）。

同样的 idiom 本文件已在用：`getBaseJavaTypeCase` 的 PHI join（`CachedJavaType.cpp:397-399`）、`phiValueType`（`CachedJavaType.cpp:1426-1427`）。

风险：`break` 只依赖累计结果、不引入 map 迭代顺序依赖，符合文件里"确定性"的约定（`CachedJavaType.cpp:1108-1109`）。

### S2：否定性预过滤——V 在这条支配链上根本没出现就别问

LVI 的 null 证明只能来自**支配该查询点**的条件或 assume/guard（`LazyValueInfo.cpp:1762` 的 `intersectAssumeOrGuardBlockValueConstantRange`）。而这些都以 V 为操作数。所以：

```text
每次顶层查询构建一次: UsedBlocks = { B | B 中存在 V 的 user }      // 来自 V->users(), O(#uses)
isNullEdge(V, From, To):
  沿 From 的 idom 链向上走，直到 V 的定义块（含）为止               // O(链长)
  若链上没有任何块 ∈ UsedBlocks → 不可能存在支配该边的 null 证明 → false（不调 oracle）
```

这是**反证式**过滤，不是证明式：它只决定"不去问"，因此永远不会产生错误答案，最坏情况只是少了一点精度。

收益预期最大：3.3 节已经论证绝大多数边的答案是 false，而这条过滤不碰 LVI、不碰 VM 回调，纯 O(链长) 指针比较。

风险：`UsedBlocks` 的构建成本要与收益权衡（`V->users()` 在大函数里可能很大）。建议懒构建 + 只构建一次/每查询，并加 stat 观察 `V` 的平均 user 数。

### S3：对称化支配链扫描，并把 reference 版的结构兜底补回来

`JavaType.cpp:989-1027` 的 `isNullCheckPath` 已经实现了"沿 idom 链找 `icmp eq/ne V, null` 分支，再看 `From` 是否被 null 侧边支配"。cached 引擎**完全没有这层**（`CachedJavaType.cpp:1274-1281` 只调 oracle），因此：

- 精度上：cached 版对 threaded 形状完全依赖 LVI；
- 差分验证上：两引擎同输入可能给出不同结果——这是潜在的一致性隐患，不只是性能问题。

建议：

1. 把 `isNullCheckPath` 提到共享位置（或复制到 cached 引擎）作为 L0 的第二层；
2. **对称化**：同一段扫描同时识别 null 侧与非 null 侧，返回三值而不是 bool：
   - 被 null 侧边支配 → `Null`
   - 被非 null 侧边支配 → `NonNull`
3. 扫描到 V 的定义块即停止（V 定义点以上不存在该值，`JavaType.cpp:1844-1847` 的 seed cut 论证同理）。

正确性：纯支配关系推理 + 现有 `isNullCheckPath` 的既有论证（`NullBB == OtherBB` 时要 `continue`，重复边不能给结论）。**成本远低于任何 LVI 查询**。

### S4：粒度从 (V, 边) 提升到 (V, From) 块级三值状态

观察：V 是 SSA 值，**沿一条 CFG 边不可能变成 null**。因此

- V 在 `From` 末尾必为 null ⇒ `From` 的**所有**出边都是 null 边；
- V 在 `From` 末尾必非 null ⇒ `From` 的**所有**出边都不是 null 边。

一个块级结论可以覆盖该块的全部出边，而当前实现是逐边各问一次 LVI（`getValueOnEdge` 内部同样要算 `getBlockValue(From)`，即 N 次重复劳动）。

```text
enum class Nullness { Unknown, NonNull, Null };

Nullness nullnessAtBlockEnd(V, From, Q);        // 结果缓存于 (V, From)

isNullEdge(V, From, To):
  if (!Q.DT.isReachableFromEntry(From)) return false;        // 保持现状
  switch (nullnessAtBlockEnd(V, From, Q)) {
    case Nullness::Null:    return true;                     // 覆盖所有出边
    case Nullness::NonNull: return false;                    // 覆盖所有出边
    case Nullness::Unknown: break;
  }
  // 块级未知时才需要边的粒度：终结指令自己就在测 V（L0 结构快路）
  return structuralNullTestOnTerminator(V, From, To);
```

`nullnessAtBlockEnd` 的三级实现，从便宜到贵：

1. **S3 的对称化支配链扫描**（不碰 LVI）；
2. `LVI.getConstant(V, From->getTerminator())` → 返回 `ConstantPointerNull` 即 `Null`（一次 `getValueInBlock`，比 `getValueOnEdge` 少一层 `getEdgeValueLocal`）；
3. 二者都不定时，才退回逐边 `LVI.getPredicateOnEdge`（并受 S5 预算约束）。

注意 2 只能证明"是常量"，不能直接证明"非 null"：`getConstant` 在 overdefined 时返回 nullptr。若需要更积极的 `NonNull`，可用 `LVI.getPredicateAt(ICMP_EQ, V, null, From->getTerminator(), /*UseBlockValue=*/true)`，但要留意该 API 在块值无法判定时会**再沿 From 的入边回推**（`LazyValueInfo.cpp:2102-2156`），可能比单次块值查询更贵。建议先只上 1，2 单独 A/B。

正确性：结论方向只依赖"SSA 值不在边上改变 nullness"，两条蕴含都成立；`Unknown` 时退回原路径，等价于现有行为。

预期收益：把 N 次逐边 LVI 查询降到每块 1 次甚至 0 次，且 `NonNull` 是最常见的答案。次要收益：与 S3 一起把 cached 引擎的精度补回 reference 的水平。

### S5：oracle 预算 + 开关（给编译时间硬上界）

与现有 `FactsBudget` / `PhiBudget` 完全同构（`CachedJavaType.cpp:1129` 的 `getFactsJoinBudget()`、`CachedJavaType.cpp:38` 的 `NumCachedJavaTypeBudgetExhausted`）：

- 新 option：`jeandle-max-null-edge-oracle-calls`（每顶层查询），默认值由 E0 的分布决定；
- 超预算一律答 false（keep edge，sound），并 ++ 一个独立 stat；
- 预算 = 0 即等价于 E0 的"恒 false"实验，天然提供一个开关。

关于 `Info.SkipVerification`：超预算后的结果仍然是正确的 join（只是更钝），**不需要**为了健全性置位；但若要求"冷/热、不同预算下结果必须逐字一致"的差分验证，则应复用现有 `FactsTruncated` / `SkipVerification` 的处理方式，把预算耗尽也算作一次截断。两种策略选一种并写进注释，不要留模糊空间。

### S6：跨查询缓存 (V, From) 块级状态（可选，收益待测）

放进 `JavaTypeCache`（与 `PathFacts` 并列，`CachedJavaType.h:57-60`）：

- 键 `(V, From)`，值 `Nullness`。比 `(V, From, To)` 小 1/#succ 倍；
- 命中来源：同一个 V 在不同 Context（不同 BB）被查询时，`FinalTypes` 按 `(V, 上下文块)` 建键，跨块不命中，于是 CFG 会被反复走一遍，null 结论可复用；
- 失效：必须与 `PathFacts` 走**同一套**规则。`CachedJavaType.h:72-78` 已明确"触及 calls / memory / terminators 的变更会改变 guard 和 LVI 事实"，null 边状态正是这类事实，不能沿用 `BaseTypes` 的宽松规则。
- 键里含 `Value *`，因此必须参与 `invalidate()` 的 use-closure 擦除，否则会留下悬垂键。

风险最高的一项：失效协议和"确定性"约定都要求严格遵守。建议最后做，且必须先有 E0 的命中率数据支撑。

### S7：冗余臂免问（可选）

```cpp
JavaType E = factsAt(V, P, Q);
mergePathFacts(E, edgeGuard(P, BB, V, Q.DT));
if (!First && typeUnion(Joined, E) == Joined)
  continue;                              // 加这条臂 ≈ 跳过它，无需知道是否 null
if (isNullEdge(V, P, BB, Q))
  continue;
joinArm(Joined, First, std::move(E));
```

输出严格等价（`typeUnion(Joined, E) == Joined` 意味着该臂不改变 join），省掉"两臂推出同一个类"情形的 oracle 调用。注意 `typeUnion` 可能触发 VM 回调 `GetCommonSuperKlass`（`JavaType.cpp:345`），需要实测是否比 LVI 便宜——若同量级则改为便宜的充分条件（Klass 相同且 exclusions/interfaces 是子集）。

## 5. 落地顺序与判定标准

| 阶段 | 改动 | 风险 | 预期收益 | 进入下一阶段的条件 |
| --- | --- | --- | --- | --- |
| 0 | E0 实验 + 四个 stat | 无 | 决定方向 | `NullOracleTrue` 比例低且 `NullOracleNanoseconds` 占比高 |
| 1 | S1 join 短路 | 无（输出严格等价） | 中～大 | 编译时间不回退，lit 全绿 |
| 2 | S2 否定性预过滤 | 低 | **大** | `NullOracleCalls` 显著下降且 sharpen 结果不变 |
| 3 | S3 对称化支配链 + 补 reference 兜底 | 低 | 大，且修精度一致性 | 差分验证不再出现 cached/reference 差异 |
| 4 | S5 预算 + 开关 | 无 | 上界/可关 | 压力输入无 CPU 回退 |
| 5 | S4 块级三值状态 | 中（语义等价性需推敲） | 中～大 | 单次耗时下降、调用次数再降 |
| 6 | S7 / S6 | 中 | 小～中 | 有命中率数据支撑 |

**每次只上一条，每条单独测量。** 上一轮的教训很具体：通用"先提取约束"方案在共享布尔 DAG 压力输入上回退约 35.5% CPU，最终只保留了 Argument condition 快速路径（见[执行报告](JavaType-LVI-Argument-Undef-Optimization-Execution-2026-10-23.md)）。S2/S3/S4 都属于"每条边多做一点结构判断"的改动，正是最容易被压力输入反噬的形态，必须逐条回放。

## 6. 必须守住的不变量

1. **健全性方向**：任何改动只能让 oracle **少答 true**，不能多答 true。少问 = 少精度；多答 true = 可能跳过一条本不该跳的边。
2. **确定性**：`CachedJavaType.cpp:1108-1109` 的约定——前驱按 `pred_begin` 的 use-list 顺序遍历，缓存只按键查找/插入/删除，不遍历缓存决定查询顺序。S1 的 `break` 不违反（只依赖累计结果）；**不要**按"信息量"重排前驱，那会破坏 VM 回调录制/回放的一致性。
3. **重复边**：`edgeGuard`（`CachedJavaType.cpp:1231`）与 `isNullCheckPath` 都有"两个后继相同 ⇒ 无结论"的处理，S3 的对称化版本必须保留，否则会得到不健全的结论。
4. **`{}` 是中性元，不是错误**：所有过滤的兜底必须是 `{}` / keep edge。
5. **差分验证**：cached 引擎与 reference 引擎（`JavaType.cpp`）必须对同一输入给出一致结果；S3 的目标之一就是修掉 cached 版缺少 `isNullCheckPath` 带来的精度差。任何 `SkipVerification` 的语义变化都要在注释里显式写出理由。

## 7. 交付物

- 阶段 0：`environment.json`、四个新增 stat 的实际计数、恒 false oracle 的 A/B 数据（进程 CPU、`TotalQueryTimeNanoseconds`、Known→Unknown 变化条数）。
- 阶段 1-6：每条改动独立的 patch + 前后测量表 + 回退记录；lit 覆盖建议：
  - 菱形 null 检查（null 臂在前 / 在后各一例，验证与顺序无关）；
  - threaded null 检查（条件与边不在同一块）；
  - 重复边（两个后继相同）；
  - `phi [null, entry], [obj, loop]`；
  - 不可达块 / irreducible CFG（触发 fuse 路径）；
  - 预算耗尽路径（单测最好能直接调 `nullnessAtBlockEnd` / `isNullEdge`）。
- 报告：本文的"执行版"，需明确区分猜测与测量。

## 8. 未覆盖 / 待确认

- 用户 profiling 的具体输入与采样方式未知（合成 workload 还是 JVM 真实编译？CHA/TCE 单独跑还是全 pipeline？），决定这些数字能否外推到生产。
- `NullOracleTrue` 的真实比例未测；若意外偏高，说明"多数调用白干"的判断有误，S2 的收益会缩水。
- S4 第 2 级（`LVI.getConstant`）与第 3 级（逐边 `getPredicateOnEdge`）的成本比未测。
- 是否存在"oracle 结果影响 pass 决策从而改变 IR"的反馈路径（如 devirtualization 成功后 IR 变化），会影响 S6 的失效频率，需在落地前确认。
