# JavaTypeAnalysis V1 实现摘要

## 1. V1 目标

在不修改现有 `jeandle::getJavaType` 分析语义的前提下，为其增加一个由 LLVM new PassManager 管理的 Function Analysis 缓存层，并迁移 `TypeCheckElimination`、`CHADevirtualization` 两个 LLVM 消费者。

V1 的定位是：先建立正确、可失效、可观测的完整查询结果缓存，再根据真实 hit/miss 数据决定是否缓存基础类型、PHI 子问题、支配链事实或 JVM 类型关系。

## 2. 文件与注册

新增：

```text
llvm/include/llvm/Analysis/Jeandle/JavaTypeAnalysis.h
llvm/lib/Analysis/Jeandle/JavaTypeAnalysis.cpp
```

修改：

```text
llvm/lib/Analysis/CMakeLists.txt
llvm/lib/Passes/PassBuilder.cpp
llvm/lib/Passes/PassRegistry.def
llvm/lib/Transforms/Jeandle/TypeCheckElimination.cpp
llvm/lib/Transforms/Jeandle/CHADevirtualization.cpp
```

在 `PassRegistry.def` 中注册 Function Analysis，使现有 `PassBuilder::registerFunctionAnalyses(FAM)` 可以创建它。

保留 `llvm/IR/Jeandle/JavaType.h/.cpp` 中的旧自由函数，JDK 前端仍可在 IR 构造期直接使用。

## 3. Analysis 结构

```cpp
struct QueryKey {
  Value *V;
  BasicBlock *ContextBB; // nullptr 表示无上下文基础查询
};

class JavaTypeAnalysisResult {
public:
  JavaType getJavaType(Value *V, Instruction *Context = nullptr);
  void clear();
  bool invalidate(Function &, const PreservedAnalyses &,
                  FunctionAnalysisManager::Invalidator &);

private:
  Function &F;
  DominatorTree &DT; // FAM 所有，Result 仅持有引用
  DenseMap<QueryKey, JavaType, QueryKeyInfo> Cache;
};

class JavaTypeAnalysis : public AnalysisInfoMixin<JavaTypeAnalysis> {
public:
  using Result = JavaTypeAnalysisResult;
  Result run(Function &F, FunctionAnalysisManager &FAM);
};
```

分析结果按值返回，避免 `clear()` 后消费者持有失效引用。

## 4. 查询算法

1. 使用 `stripPointerCastsAndAliases()` 规范化 `Value`；
2. 使用 `Context ? Context->getParent() : nullptr` 构造上下文键；
3. 在 `DenseMap` 中查询完整 `JavaType`；
4. hit：按值返回缓存结果；
5. miss：调用旧 `jeandle::getJavaType`，保存并返回结果；
6. known、unknown 和只有 `ExcludedKlasses` 的结果全部缓存。

概念代码：

```cpp
V = V->stripPointerCastsAndAliases();
QueryKey K{V, Context ? Context->getParent() : nullptr};

if (auto It = Cache.find(K); It != Cache.end())
  return It->second;

JavaType R = Context ? jeandle::getJavaType(V, &DT, Context)
                     : jeandle::getJavaType(V);
Cache.try_emplace(K, R);
return R;
```

## 5. 生命周期与失效

- 缓存归属于一个 Function 的 `JavaTypeAnalysisResult`；
- 未修改 IR、返回 `PreservedAnalyses::all()` 时可以跨 Pass 复用；
- Pass 未保留 `JavaTypeAnalysis` 时，由 FAM 在 Pass 返回后销毁；
- `invalidate()` 同时检查 `DominatorTreeAnalysis` 依赖；
- 两个消费者在一次 `run()` 内成功修改 IR 后立即调用 `clear()`，避免 PassManager 尚未执行失效时使用陈旧结果；
- V1 不对单条 entry 做细粒度失效。

## 6. Consumer 迁移

原调用：

```cpp
jeandle::getJavaType(Obj, &DT, Context);
```

迁移为：

```cpp
auto &JTA = FAM.getResult<jeandle::JavaTypeAnalysis>(F);
JavaType T = JTA.getJavaType(Obj, Context);
```

`TypeCheckElimination` 在替换并删除 `check_instanceof` 后执行 `JTA.clear()`。

`CHADevirtualization` 仍保留自己的 `DominatorTree`/`DomTreeUpdater`；每个调用点优化成功并完成 `DTU.flush()` 后执行 `JTA.clear()`。

两个 Pass 的类型判断、IR 变换和 `PreservedAnalyses` 语义不变。

## 7. 正确性与可观测性

增加隐藏选项：

```text
-jeandle-disable-java-type-cache
-jeandle-verify-java-type-cache
```

- disable：同一新接口绕过缓存，直接调用旧算法，用于 A/B；
- verify：每次 hit 时用旧算法影子重算，并比较 `Klass`、`Exact`、`ExcludedKlasses`。

增加统计：

```text
queries / hits / misses / insertions / clears / bypasses
current entries / peak entries
hit time / miss computation time / total query time
JavaType 相关 JVM callback 实际调用次数
```

验证覆盖：相同查询命中、unknown 命中、不同上下文隔离、cast 规范化、clear 后 miss、DT 失效、PHI/循环、TCE Pass 内修改、CHA CFG 修改，以及缓存开关两种模式下的 LLVM lit/JDK jtreg。

## 8. 空间策略

V1 不设 LRU 和固定容量。缓存按需插入，空间为自上次 clear 后实际不同查询数 `O(Q)`，并随 Function Analysis 失效整体释放。先统计峰值；只有真实数据证明存在内存压力时再设计容量策略。

## 9. V1 非目标

V1 不实现：

- 跨 Function 或跨编译缓存；
- 基础类型和上下文锐化的内部拆分缓存；
- PHI 递归中间状态缓存；
- 支配链前缀缓存；
- JVM `IsSubtype`/LCA 等关系缓存；
- 细粒度依赖跟踪和单 entry 失效。

## 10. V1 验收标准

- 旧 `getJavaType` 语义实现不变；
- 两个 LLVM 消费者完成迁移；
- cache on/off 的程序结果与现有测试一致；
- verify 模式下缓存命中不一致数为 0；
- 定向测试能稳定产生并验证 hit、miss 和 clear；
- 输出真实 workload 的 hit rate、条目峰值、callback 减少量、类型查询耗时及两个 Pass 耗时；
- 无 crash、悬空指针、错误 preserve 或明显端到端编译时间回退。

## 11. V1 与最终完整方向对比

最终完整方向详见同目录下的 `JavaTypeAnalysis-Final-Direction.md`。V1 与最终方向的关系是：V1 先建立稳定接口、AnalysisManager 生命周期、正确性 oracle 和性能测量基线；最终方向在此基础上逐步增加分层复用与依赖感知失效。

| 维度 | V1 | 最终完整方向 |
|---|---|---|
| 核心定位 | 旧 `getJavaType` 外层的完整结果 memoization | 分层、依赖感知的增量 Java 类型分析 |
| 分析语义 | 完全保留旧函数，miss 时直接调用旧函数 | 仍保持与旧函数等价，但可逐步拆分其内部计算阶段 |
| 所有权 | Function Analysis | 完整 JavaType 仍以 Function 为边界；纯 VM 关系可提升到编译级所有者 |
| 完整查询 key | `(CanonicalValue, ContextBB)` | `(CanonicalValue, CanonicalContext/Edge)`，并允许未来表示块内程序点 |
| Function | 由 Function Analysis 外层隐含 | 同样由外层作用域隐含，不必重复进入每条 key |
| IR/DT/VM 状态 | 不直接进入 key；修改后通过 clear/FAM 失效 | 不直接堆入 key；记录实际依赖、版本或 assumption token 判断有效性 |
| 缓存内容 | 完整 `JavaType` | 完整结果、基础类型、上下文锐化、递归子问题和 JVM 类型关系 |
| 基础类型复用 | 仅当完整 key 命中时被间接复用 | `CanonicalValue -> BaseJavaType`，可跨不同 Context 复用 |
| 上下文锐化复用 | 仅完整查询命中 | 独立缓存 `(Value, Context/Edge)` 的锐化结果，可继续复用支配事实 |
| PHI/Select | 每次 miss 由旧函数重新递归 | incoming/arm/转发源作为独立子问题复用，父节点重新合并 |
| 同源 Value | 仅规范化 pointer casts 和 aliases | 在语义证明允许时扩展同源映射；不会因 Klass 相同就合并独立 Value |
| JVM callback | miss 时照常调用 | 按 callback 名称、参数和 VM 有效期缓存，供不同查询和 Function 共享 |
| unknown | 作为普通完整结果缓存 | 区分 `Computing` 与 `Complete(unknown)`，避免循环临时状态污染 |
| DT 处理 | Result 持有 FAM 的 DT 引用，并在 DT 失效时整体失效 | DT 仍是 CFG 的派生依赖；只失效依赖变化支配关系的锐化结果 |
| Pass 内修改 | 消费者修改 IR 后立即 `clear()` | 通过修改通知、依赖反向索引或局部失效精确更新；无法证明时仍可 clear |
| Pass 间复用 | Pass 正确 preserve 且没有 clear 时复用 | 相同，并在局部修改后保留未受影响的 entry |
| driver 轮次复用 | 仅限同一分析所有者仍存活且结果被保留的安全轮次 | 明确 IR 身份、依赖与 VM assumption 后支持安全复用或显式状态传递 |
| 失效粒度 | Function Cache 整体清空/销毁 | attribute、metadata、operand、PHI edge、branch、DT、VM 关系级传播失效 |
| Value 生命周期 | 依靠 clear 和 FAM 失效纪律避免删除后继续查询 | 删除通知、安全 Value 句柄或反向索引主动移除 entry |
| 空间管理 | 不设 LRU，统计 `O(Q)` 峰值 | 根据分层 entry 和依赖图实测决定容量、淘汰与生命周期策略 |
| 正确性验证 | disable、hit shadow verify、旧函数作 oracle | 延续 oracle，并增加各层结果和各种局部失效场景验证 |
| 性能观测 | 总 queries/hits/misses、时间、容量和 callback 次数 | 分层 hit/miss、避免的 IR/DT 遍历、callback cache、失效维护和依赖图成本 |

### 11.1 V1 为最终方向保留的基础

- 对外使用统一的 `JavaTypeAnalysisResult::getJavaType` 接口，消费者不再直接绑定旧自由函数；
- Function Analysis 生命周期适合承载 Value、CFG、DT 相关结果；
- 旧函数继续作为 miss 路径和正确性 oracle，降低首次迁移风险；
- 完整查询 key 已区分 Value 与 Context，并对安全的 pointer casts/aliases 做规范化；
- disable、verify、hit/miss、耗时和容量统计可作为后续演进的对照基线；
- `clear()` 提供最终局部失效尚未完成时的保守正确性后备方案。

### 11.2 V1 暂时牺牲的能力

- 不同 Context 查询同一 Value 时不能独立复用基础类型；
- 完整查询 miss 会重新遍历 PHI/Select、支配链和 condition graph；
- IR 中即使只有无关部分变化，`clear()` 也会损失全部已有结果；
- 相同 JVM 类型关系会在不同 miss 中重复 callback；
- 无法在 Value 被重写后迁移仍然有效的同源或子问题结果；
- driver 轮次重建分析所有者后不能自动保留 Function 缓存。

V1 用上述命中率和复用范围上的牺牲，换取较小的实现范围、明确的生命周期、容易验证的失效纪律，以及可用于判断后续优化优先级的真实数据。最终方向不改变 V1 的正确性原则，而是逐步把“全部重新计算或全部清空”替换为“复用未变化层级并只失效真实依赖”。

## 12. V1 分阶段实施计划

接口阶段已经完成，后续实现按以下顺序推进。每个阶段单独编译和验证，避免在核心缓存尚未稳定时同时引入注册、消费者迁移和性能观测。

### 阶段 1：最小 Function Analysis 骨架

- 定义 `JavaTypeAnalysis::Key`；
- 实现 `JavaTypeAnalysisResult(Function &, DominatorTree &)`；
- 实现 `JavaTypeAnalysis::run()`，从 FAM 获取当前 Function 的 `DominatorTreeAnalysis` 并返回空 Result；
- 明确 Analysis 是工厂，Result 由 FAM 按 `(AnalysisKey, Function *)` 管理。

### 阶段 2：DenseMap 查询键

- 实现 `QueryKeyInfo::getEmptyKey()`；
- 实现 `QueryKeyInfo::getTombstoneKey()`；
- 使用 `(Value *, BasicBlock *)` 共同计算哈希；
- 使用两个指针完全相等判断 key 相等；
- 保证合法的 `ContextBB == nullptr` 不与 DenseMap 特殊 key 冲突。

### 阶段 3：最小完整结果缓存

- 在 API 边界规范化 `Value`；
- 按 `(CanonicalValue, ContextBB)` 查询缓存；
- hit 按值返回；
- miss 严格转调旧 `jeandle::getJavaType`；
- 缓存 known、unknown 和 exclusion-only 的全部完整结果。

### 阶段 4：生命周期与失效

- 实现 `clear()`，只清空 entry，不重置 Result 生命周期统计；
- 实现 new PassManager `invalidate()`；
- 同时跟踪 `JavaTypeAnalysis` 自身 preserve 状态和 `DominatorTreeAnalysis` 依赖。

### 阶段 5：正确性开关与观测

- 增加 cache disable 和 hit shadow verify 隐藏选项；
- Result 内统计单 Function 当前 Result 生命周期；
- 使用 LLVM Statistic 在事件发生时累计进程级历史汇总；
- 实现 Function Printer 和 Module Summary Printer；
- 增加查询时间、容量峰值和 JVM callback 实际调用次数统计。

### 阶段 6：构建与 PassManager 接入

- 加入 Analysis CMake；
- 在 PassBuilder 中包含接口；
- 在 PassRegistry 中注册 Function Analysis、Function Printer 和 Module Summary Printer。

### 阶段 7：消费者迁移

- 迁移 `TypeCheckElimination`；
- 迁移 `CHADevirtualization`；
- TCE 修改 IR 后立即 `clear()`；
- CHA 成功修改 CFG 并完成 `DTU.flush()` 后立即 `clear()`；
- 保持两者原有类型判断、IR 变换和 PreservedAnalyses 语义。

### 阶段 8：测试与验收

- 覆盖 hit、unknown hit、Context 隔离、cast/alias 规范化、clear 和 DT 失效；
- 覆盖 PHI/循环、TCE Pass 内修改和 CHA CFG 修改；
- 对比 cache on/off，确保程序结果一致；
- verify 模式缓存命中不一致数为 0；
- 运行 LLVM lit、JDK jtreg 和真实 workload，输出命中率、容量、callback 与耗时数据。

当前实施范围只完成阶段 1 和阶段 2，不提前实现查询缓存、统计、Printer、注册或消费者迁移。
