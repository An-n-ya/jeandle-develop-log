# JavaTypeAnalysis 缓存技术实现方案

## 1. 文档目的与项目边界

本文档根据 [Project.md](Project.md) 的项目要求、
[JavaTypeAnalysis-Final-Direction.md](JavaTypeAnalysis-Final-Direction.md) 的长期目标，以及
Jeandle LLVM/JDK 仓库当前实现，整理 Java 类型分析缓存的可执行技术方案。

文档重点回答：

- 项目实际需要解决什么问题；
- 哪些能力能够直接利用 LLVM new PassManager 实现；
- 哪些能力必须增加专门的缓存、修改通知或依赖追踪；
- 哪些内容属于一期必要交付，哪些属于后续增量分析方向；
- 如何证明缓存没有改变现有 `jeandle::getJavaType` 语义，并确实带来性能收益。

当前仓库尚未实现 `JavaTypeAnalysis`。现有
`JavaTypeAnalysis-V1-Summary.md` 是实现设计摘要，不是当前代码状态。当前代码仍由
`TypeCheckElimination` 和 `CHADevirtualization` 直接调用自由函数
`jeandle::getJavaType`。

本项目的安全边界是一次 Jeandle 编译：

```text
一次 optimize(Module) 调用
    -> 创建一个 Jeandle Pipeline
    -> Pipeline 持有 AnalysisManager
    -> 在该 Pipeline 的 Pass 和 driver 轮次间复用
    -> Pipeline 销毁时释放 Function JavaType 缓存
```

项目不默认跨不同 Java 编译任务永久复用包含 `Value *`、`BasicBlock *` 或 Klass
指针的结果。

## 2. 技术目标

### 2.1 语义目标

在不改变现有 `jeandle::getJavaType` 分析语义的前提下，为查询增加可复用、可失效、
可观测的缓存层。

`JavaType` 表达：

- `Klass = K`：非空对象已知是 `K` 或 `K` 的子类；
- `Exact = true`：运行时类型精确等于 `K`；
- `ExcludedKlasses`：对象一定不是这些类的实例；
- 当前不表达 nullability。

完整类型可表示为：

```text
FullType(V, C) = typeIntersect(BaseType(V), SharpenedType(V, C))
```

其中：

- `BaseType(V)` 来自 Value 自身、attribute、metadata、常量 oop 和数据来源；
- `SharpenedType(V, C)` 来自查询程序点上必然成立的支配分支和类型检查；
- PHI、Select 使用 `typeUnion` 合并不同来源；
- 同时成立的基础事实和路径事实使用 `typeIntersect` 合并。

核心正确性不变量为：

```text
CachedQuery(V, C, CurrentIR)
    ==
LegacyGetJavaType(V, C, CurrentIR)
```

### 2.2 一期必要目标

一期必须完成：

1. 建立由 LLVM `FunctionAnalysisManager` 管理的 `JavaTypeAnalysis`；
2. 对完全相同的完整查询进行平均 `O(1)` 哈希命中；
3. 缓存 known、unknown 和只有 `ExcludedKlasses` 的结果；
4. 迁移 `TypeCheckElimination`、`CHADevirtualization` 两个 LLVM Pass 消费者；
5. 正确处理 AnalysisManager 失效、DominatorTree 依赖和 Pass 内修改；
6. 保留旧自由函数供 JDK IR 构造期使用，并作为 miss 计算内核和正确性 oracle；
7. 提供 cache disable、shadow verify、hit/miss、容量、耗时和 callback 统计；
8. 通过 LLVM lit、Jeandle LLVM 测试和 Jeandle JDK 测试。

这里的平均 `O(1)` 指哈希查找不再重新遍历 IR、DT 或调用 VM。由于现有 API 按值返回
`JavaType`，理论上复制 `ExcludedKlasses` 仍需要 `O(E)`，但其集合当前使用小容量内联
存储，通常很小。

### 2.3 长期目标

在一期框架和性能数据基础上，逐步增加：

- 不同 Context 之间复用同一 Value 的基础类型；
- 单独缓存上下文锐化结果；
- 缓存 JVM 类型关系查询；
- 复用 Select、转发指令和 PHI 的递归子问题；
- 对协作式 IR 修改进行依赖感知的局部失效；
- 在同一 AnalysisManager 和 driver 生命周期内安全跨轮次复用。

### 2.4 非一期目标

以下内容不应作为一期成功的前置条件：

- 跨不同编译任务永久缓存 `Value *` 或 Klass；
- 对所有 LLVM Pass 的任意 IR 修改进行无侵入、全自动、单 entry 精确失效；
- 修改 `JavaType` 语义或同时引入 nullability 分析；
- 一开始就实现完整依赖图、LRU 和内存淘汰策略；
- 强制把 JDK IR 构造期调用迁入 FunctionAnalysisManager；
- 在没有测量数据前保证端到端编译时间达到固定收益。

## 3. 技术痛点

### 3.1 查询具有程序点敏感性

同一个 LLVM SSA Value 在不同位置可能得到不同结果：

- 无 Context 时只有基础类型；
- 成功的 `check_instanceof` 支配路径上可能被锐化；
- 失败路径上可能增加 `ExcludedKlasses`。

因此完整缓存不能只使用 `Value *`，顶层查询至少需要：

```text
(CanonicalValue, ContextBlock)
```

当前公开算法只读取 `Context->getParent()`，因此同一基本块中的普通顶层查询可以共享
Context key。如果未来引入块内指令顺序事实，key 必须扩展成真正的程序点。

### 3.2 PHI incoming 是 CFG 边语义

上下文敏感 PHI 查询会使用：

```text
IncomingBB -> PhiBB
```

这条边上的事实。内部递归缓存不能只记录 incoming value 和 incoming block，还需要目标块
或等价的 Edge key。顶层 `(Value, ContextBB)` 只能用于公开完整查询，不能直接套用到所有
PHI 子查询。

### 3.3 循环 PHI 不能把临时状态缓存成 unknown

当前实现使用 `Visited` 跳过循环 incoming。加入递归缓存后必须区分：

- `Absent`：尚未计算；
- `Computing`：当前递归栈上；
- `Complete(JavaType{})`：最终结果确实为 unknown；
- `Complete(JavaType)`：已完成结果。

互相递归 PHI 中，一个子问题在某个根查询内得到的临时结果不一定适合独立查询。
因此不能把遇到 `Computing` 时返回的临时 unknown 写成永久缓存。后续应采用 SCC/fixpoint，
或仅缓存完全退出递归栈且不依赖临时截断的结果。

### 3.4 LLVM IR 没有通用的自动版本号

`Value *` 只表示对象身份，不表示不可变版本。以下修改都可能在地址不变时改变答案：

- Argument 或 Call attribute 修改；
- Load metadata 修改；
- operand、PHI incoming 或 Select arm 修改；
- branch condition/successor 修改；
- CFG 和 DominatorTree 修改。

LLVM new PassManager 能判断整个 Analysis 是否被 preserve，但不会通知某条缓存 entry
具体读取的 operand 或 metadata 是否变化。精确局部失效必须依赖：

- 变换方显式调用修改通知接口；
- Value 删除/RAUW 的 `CallbackVH`；
- 依赖记录和反向索引；
- 无法证明时保守 `clear()` 或让 FAM 销毁整个 Analysis。

### 3.5 Pass 内修改早于 PassManager 失效

FAM 在 Transform Pass 返回后才根据 `PreservedAnalyses` 失效结果。在一个 `run()` 内，
消费者可能执行：

```text
查询 -> 修改 IR -> 再查询
```

因此 TCE 和 CHA 不能等待 Pass 返回后的自动失效。它们必须在每次成功修改后立即清理或
局部更新 JavaType 缓存。

### 3.6 JVM callback 生命周期和 replay

VM callback 合同只保证同一次编译内相同参数返回相同结果。这足以支持编译内缓存，
但不足以支持进程级永久缓存。

跨编译复用可能遇到：

- 类加载改变 `IsEffectivelyFinal` 等结论；
- Klass 指针生命周期或复用问题；
- 当前编译的 `.cblog` 因静态缓存命中而漏录 callback；
- record/replay 两侧 callback 集合不一致。

因此 JVM relation cache 初期必须限制在 Function 或单次 Pipeline 生命周期内。

### 3.7 性能收益不能仅由架构推导

TCE 和 CHA 在一次 Pass 内通常对每个调用点只查询一次。完整 query cache 的主要命中来源
可能是：

- 同一基本块内对相同 Value 的多个查询；
- 多个 Pass/driver 轮次重新查询仍然存在的 IR；
- 不同顶层查询共享基础类型、支配事实或 JVM 关系。

但是 Pass 之间存在 RecoverTypeInfo、EarlyCSE、InstCombine、SimplifyCFG 等 IR 修改，
可能频繁使完整缓存失效。因此 V1 完整缓存是必要的测量和正确性平台，但未必单独带来
显著性能收益。Base cache 和 JVM relation cache 可能具有更高实际收益。

### 3.8 JDK 构造期调用与 LLVM Pass 调用的生命周期不同

JDK 前端当前有两处直接调用：

- 对象数组 load 生成时查询数组类型，用于附加元素类型 metadata；
- `null_check` 中一次结果未使用的基础查询。

这些调用发生在 LLVM PassManager 运行前，没有 FAM。第一处应继续使用自由函数；第二处
应单独确认后删除无用调用。项目的“迁移现有调用”应解释为迁移两个 LLVM Pass 消费者，
而不是强制迁移前端构造期接口。

## 4. 可行性判断

| 能力 | 可行性 | 一期必要性 | 结论 |
| --- | --- | --- | --- |
| 完整查询平均 `O(1)` 命中 | 高 | 必须 | `DenseMap<QueryKey, JavaType>` 可直接实现 |
| FunctionAnalysisManager 接入 | 高 | 必须 | Pipeline 已持有并注册 FAM |
| TCE/CHA 消费者迁移 | 高 | 必须 | 当前只有这两个 LLVM Pass 直接调用 |
| 跨 Pass 复用 | 高但有条件 | 必须 | Pass 必须正确 preserve，IR 变化时必须更新或失效 |
| 同一 driver 多轮复用 | 高但有条件 | 必须支持 | driver 已显式执行 FAM invalidation |
| Base/Sharpened 分层 | 高 | 二期 | 需要拆分或注入现有计算内核 |
| JVM 类型关系缓存 | 高 | 二期优先 | callback 已有单次编译纯函数合同 |
| Select/转发子问题缓存 | 高 | 二/三期 | DAG 情况简单，需处理依赖失效 |
| PHI 循环子问题缓存 | 中 | 三期 | 需要 SCC/fixpoint 或严格完成态策略 |
| Value 删除/RAUW 自动失效 | 高 | 建议尽早 | 可复用 `CallbackVH` 模式 |
| operand/metadata/attribute 自动局部失效 | 低 | 非一期 | LLVM 无通用通知，必须由变换方协作 |
| 任意 IR 修改只失效真实依赖 | 有条件可行 | 长期目标 | 依赖图只能覆盖接入通知纪律的 Pass |
| 跨编译共享完整类型结果 | 低且风险高 | 不需要 | Value/Klass/VM 假设生命周期不安全 |
| 显著性能提升 | 待实测 | 必须验证 | 不能用 hit rate 代替真实耗时和 callback 数据 |

总体判断：项目可行，应批准实施；但“完整依赖图和任意修改下的全自动精确失效”应作为
后续扩展，而不是一期验收前置条件。

## 5. 总体技术架构

### 5.1 类型信息生产与消费关系

```text
JDK 前端 attribute / metadata
                │
                │ LLVM 优化可能丢失部分 load metadata
                ▼
        RecoverTypeInfo 恢复 metadata
                │
                ▼
     getJavaType / JavaTypeAnalysis 读取和传播
                │
          ┌─────┴─────┐
          ▼           ▼
 TypeCheckElimination  CHADevirtualization
```

`RecoverTypeInfo` 是 Java 类型事实的生产/恢复 Pass；`getJavaType` 是读取、传播和按程序点
锐化这些事实的查询。JavaType 在没有 RecoverTypeInfo 时仍能运行，但可能因为 metadata
缺失返回 unknown，从而损失 TCE/CHA 优化机会。

### 5.2 缓存层次

```text
一次 Jeandle 编译
└── FunctionAnalysisManager
    └── JavaTypeAnalysisResult(Function)
        ├── FullCache[(Value, ContextBlock)]
        ├── BaseCache[Value]                         // 二期
        ├── SharpenCache[(Value, ContextBlock/Edge)] // 二期
        ├── RecursiveCache[SubproblemKey]            // 三期
        ├── RelationCache[(CallbackKind, Args)]      // 二期
        └── DependencyGraph / Modification API       // 四期
```

Function 是完整 JavaType 缓存的自然所有权边界，因为 Value、Argument attribute、CFG 和
DT 都属于 Function。纯 JVM 类型关系不依赖 Function，最终可以提升到单次编译所有者，
但初期放在 Function Analysis 内更简单、安全。

### 5.3 顶层查询 key

V1 使用：

```text
QueryKey {
  CanonicalValue
  ContextBlock  // nullptr 表示基础查询
}
```

规范化规则必须与旧接口一致：

```cpp
V = V->stripPointerCastsAndAliases();
```

不能仅因为两个 Value 得到相同 Klass 就合并它们。只有 pointer cast、alias 等能够证明
同源的包装才能共享 Value 身份。Freeze、PHI、Select 是否等价必须由各自语义决定。

### 5.4 内部 Context/Edge key

二期之后建议显式区分：

```text
ProgramPoint =
  None
  | Block(ContextBB)
  | Edge(IncomingBB, DestBB)
```

公开普通查询使用 `Block`；PHI incoming 使用 `Edge`。这样可以避免不同 PHI 目标边共享
错误锐化结果。

### 5.5 生命周期

- `JavaTypeAnalysisResult` 归属于单个 Function；
- FAM 在首次 `getResult<JavaTypeAnalysis>(F)` 时创建结果；
- 后续 Pass 正确 preserve 时复用同一结果；
- Pass 未 preserve 或 DT 依赖失效时销毁结果；
- driver 使用同一 FAM，并在每个步骤后执行显式 invalidation；
- Pipeline 销毁时释放全部 Function 缓存；
- 不将完整 JavaType 缓存提升为 Module Analysis。

### 5.6 失效原则

V1：

```text
无法证明局部更新安全 -> clear 整个 Function cache
Pass 未接入更新纪律   -> 不 preserve JavaTypeAnalysis
```

长期方向：

```text
attribute / metadata / operand / edge / VM relation
                         ↓
              Base 或 Sharpen entry
                         ↓
                    Full entry
```

通过反向索引从变化依赖找到下游 entry 并传播失效。依赖记录必须包括“事实不存在”的观察，
例如缺少 `java-klass` attribute 导致的 unknown，否则后续新增 attribute 时旧 unknown 不会
正确失效。

## 6. 分阶段技术方案

### 阶段 0：建立无缓存基线

目标：回答当前查询是否足够昂贵、重复发生在哪里，以及哪一层最值得缓存。

工作内容：

1. 统计总查询、基础查询、上下文查询数量；
2. 统计 PHI/Select/转发节点访问量；
3. 统计 DT 节点和 condition graph 节点访问量；
4. 分 callback 统计 `IsSubtype`、LCA、effectively-final、oop klass 等实际调用次数；
5. 记录 JavaType 总耗时、TCE/CHA Pass 耗时和 Jeandle LLVM Optimize 耗时；
6. 选择固定的 LLVM lit、JDK jtreg 和实际编译 workload 作为后续 A/B 基线。

阶段输出：基线报告和后续性能决策依据。

### 阶段 1：V1 Function Analysis 与完整缓存

#### 6.2.1 新增文件

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

#### 6.2.2 Analysis 结构

```cpp
class JavaTypeAnalysisResult {
public:
  JavaType getJavaType(Value *V, Instruction *Context = nullptr);
  void clear();

  bool invalidate(Function &F, const PreservedAnalyses &PA,
                  FunctionAnalysisManager::Invalidator &Inv);

private:
  Function &F;
  DominatorTree &DT;
  DenseMap<QueryKey, JavaType, QueryKeyInfo> FullCache;
};

class JavaTypeAnalysis : public AnalysisInfoMixin<JavaTypeAnalysis> {
public:
  using Result = JavaTypeAnalysisResult;
  Result run(Function &F, FunctionAnalysisManager &FAM);
};
```

结果按值返回，避免调用者在 `clear()` 后继续持有失效引用。

#### 6.2.3 查询流程

```text
1. 规范化 Value
2. Context 转换为 ContextBB
3. FullCache 查找
4. hit：返回副本
5. miss：调用旧 jeandle::getJavaType
6. 保存包括 unknown/exclusions 在内的完整结果
7. 返回结果
```

V1 不改变 `JavaType.cpp` 的旧计算语义，也不尝试缓存内部递归状态。

#### 6.2.4 AnalysisManager 失效

`invalidate()` 应遵循 LLVM 现有 Analysis 模式：

```text
JavaTypeAnalysis 未 preserve -> 整体失效
DominatorTreeAnalysis 失效  -> 整体失效
否则                         -> 保留
```

不要把 `JavaTypeAnalysis` 加入 `CFGAnalyses` 集合，因为它还依赖 attribute、metadata、
operand 和 VM 事实，并非只依赖 CFG。

#### 6.2.5 消费者迁移

TCE 和 CHA 使用：

```cpp
auto &JTA = FAM.getResult<jeandle::JavaTypeAnalysis>(F);
JavaType T = JTA.getJavaType(V, Context);
```

TCE 在所有成功 IR 修改路径后立即 `JTA.clear()`，包括：

- `instanceof Object` 折叠；
- known subtype 折叠；
- incompatible/excluded 折叠。

CHA 在完成调用点重写、CFG 更新并执行 `DTU.flush()` 后立即 `JTA.clear()`。

若 Pass 在每次修改后都已把 JTA 更新到最终 IR 状态，可以显式 preserve
`JavaTypeAnalysis`；否则不 preserve，让 FAM 在 Pass 返回后销毁。正确性优先于命中率。

#### 6.2.6 V1 可观测性

增加隐藏选项：

```text
-jeandle-disable-java-type-cache
-jeandle-verify-java-type-cache
```

- disable：统一走新接口，但不查/写缓存；
- verify：每次 hit 都调用旧算法重算并比较完整结果。

V1 统计：

- queries、hits、misses、insertions；
- clears、bypasses；
- current entries、peak entries；
- hit/miss/total query time；
- shadow mismatch；
- JavaType 相关 VM callback 实际调用次数。

阶段门槛：正确性测试通过且 shadow mismatch 为 0，才能进入内部算法拆分。

### 阶段 2：Base、Sharpen 与 JVM relation 分层缓存

目标：扩大不同 Context、不同完整查询之间的复用。

#### 6.3.1 拆分计算内核

把现有静态内部函数逐步整理成可注入缓存的 evaluator，同时保留无缓存路径：

```text
getBaseType(V)
getSharpenedType(V, ProgramPoint)
getFullType(V, ProgramPoint)
```

旧自由函数使用 NoCache evaluator，新 Analysis 使用 Cached evaluator。shadow verify 继续把旧
自由函数作为语义 oracle，避免在一次提交中同时改变语义和缓存。

#### 6.3.2 Base cache

```text
CanonicalValue -> BaseJavaType
```

复用：

- Argument/Call attribute 解析；
- Load metadata 解析；
- oop handle 类型；
- Select/转发源；
- 多个 Context 对同一 Value 的基础类型。

#### 6.3.3 Sharpen cache

```text
(CanonicalValue, Block/Edge) -> SharpenedJavaType
```

复用 DT 支配链遍历、branch condition 追踪、边支配判断和 exclusions。

如果希望不同查询点共享单个支配分支事实，可以后续增加：

```text
(BranchInst, QueryValue, TakenEdge) -> BranchJavaTypeFact
```

但应先用 Context 完整锐化缓存测量，不必一开始实现支配链前缀缓存。

#### 6.3.4 JVM relation cache

建议先放在 Function Analysis 生命周期内：

```text
(IsSubtype, A, B)           -> bool
(GetCommonSuperKlass, A, B) -> Klass
(IsEffectivelyFinal, K)     -> bool
(IsInterface, K)            -> bool
(GetOopKlass, id)           -> Klass
```

规则：

- directional callback 不交换参数；
- LCA 可用 `(min(A,B), max(A,B))` 规范化；
- `false` 和 `0` 同样缓存；
- 缓存只按 key 查找，不依赖 pointer-key map 的迭代顺序；
- 不缓存 `UpdateToStaticOptVirtualCall` 等有副作用 callback；
- 不使用进程级静态缓存；
- relation cache 不得导致 record 与 replay 的 callback 集合不一致。

阶段输出：分层 hit/miss、callback 减少量和各层耗时数据。

### 阶段 3：递归子问题与循环 PHI

目标：避免不同完整查询反复遍历相同 PHI、Select 和转发数据流图。

实施顺序：

1. 先缓存无环 Select 和 bitcast/addrspacecast 等转发子问题；
2. 为递归 entry 增加 `Absent/Computing/Complete` 状态；
3. 明确 `Computing` 只能用于循环检测，不能作为最终 unknown；
4. 对互递归 PHI 使用 SCC/fixpoint；
5. PHI incoming key 使用 `Edge(IncomingBB, DestBB)`；
6. 验证从不同 PHI 根开始查询得到顺序无关的最终结果；
7. 继续保留旧 DFS 实现作为 shadow oracle，直到新算法测试充分。

`RecoverTypeInfo` 的有限格单调下降、程序顺序 sweep 和互递归 PHI 测试可作为主要参考。

### 阶段 4：依赖感知局部失效

仅在数据证明 `clear()` 频率和重算成本成为主要瓶颈后实施。

建议接口：

```cpp
void invalidateValue(Value *V);
void invalidateInstruction(Instruction *I);
void invalidatePhi(PHINode *PN);
void invalidateCFG(ArrayRef<CFGUpdate> Updates);
void invalidateSharpening();
void clear();
```

依赖节点可包含：

- Function parameter attribute；
- Call return attribute；
- Load metadata；
- instruction opcode/operand；
- PHI incoming value/block；
- Select arm；
- branch condition/successor；
- CFG edge和支配事实；
- JVM relation key。

使用反向索引传播：

```text
Dependency -> Base/Sharpen/Recursive Entry -> Full Entry
```

同时使用 `CallbackVH` 处理 Value 删除和 RAUW。需要注意，`CallbackVH` 无法观察普通
operand、metadata 或 attribute 修改，这些修改仍依赖显式通知。

未接入通知接口的标准 LLVM Pass 不得 preserve `JavaTypeAnalysis`；由 FAM 保守整项失效。
这使细粒度机制可以渐进落地，而不要求一次修改所有 LLVM Transform Pass。

## 7. 验证与验收

### 7.1 正确性验证

#### 7.1.1 Shadow verify

每次 cache hit：

```text
Cached = cache entry
Fresh  = legacy getJavaType(CurrentIR)
比较 Klass、Exact、ExcludedKlasses
```

known、unknown 和只有 exclusions 的结果全部参与比较。

#### 7.1.2 LLVM 定向测试

至少覆盖：

1. 相同完整查询产生 hit；
2. unknown 结果被缓存；
3. 只有 exclusions 的结果被缓存；
4. 相同 Value、不同 Context 不串值；
5. pointer cast/alias 规范化；
6. ContextBB key 与当前语义一致；
7. PHI incoming edge 区分；
8. 自循环和互递归 PHI；
9. Select、bitcast、addrspacecast、freeze；
10. attribute、metadata 和 operand 变化后重新计算；
11. branch、successor、CFG 和 DT 变化后重新计算；
12. Value 删除、RAUW 和地址复用风险；
13. TCE Pass 内连续查询与修改；
14. CHA 修改 CFG、刷新 DT 后继续查询；
15. cache disable/on 输出一致；
16. shadow mismatch 始终为 0；
17. VM callback record/replay 可重现。

现有代表性用例可继续作为语义基线：

- `llvm/test/Jeandle/type-check-elimination/instanceof-known-subtype.ll`；
- `llvm/test/Jeandle/cha-devirtualization/intersect-exact.ll`；
- `llvm/test/Jeandle/java-type-metadata-recovery/recover-mutual-phi-cycle.ll`。

#### 7.1.3 JDK 验证

- 运行 `TestTypeCheckElimination.java`；
- 运行 RecoverTypeInfo/CHA 相关 jtreg；
- 运行 Jeandle JDK 既有测试集合；
- 对 cache on、cache off 分别验证运行结果和生成 IR；
- 调试构建开启 verifier 和 shadow verify。

### 7.2 性能验证

#### 7.2.1 必要指标

- Full/Base/Sharpen/Recursive/Relation 各层 hit、miss；
- 各层 entry 当前值和峰值；
- clear 次数、原因和清理 entry 数；
- 避免的 IR、condition graph、DT 节点遍历数；
- 各 VM callback 的逻辑查询数、缓存命中和真实调用数；
- hit 查找、miss 计算、失效维护时间；
- JavaType 总耗时；
- TCE、CHA Pass 时间；
- `Jeandle LLVM Optimize` 时间；
- 端到端编译时间和生成代码质量。

#### 7.2.2 测量方法

- 使用 release 构建；
- 固定机器、JDK 配置、输入方法和编译级别；
- 先预热，再进行多轮独立测量；
- 比较中位数、分位数和波动范围，不使用单次结果；
- 同时比较 cache disabled、V1、分层缓存三个版本；
- query 内部计时应可关闭，避免统计本身污染 JIT 热路径；
- 使用 `-time-passes`/LLVM Pass timing 与 Jeandle 现有优化总计时交叉验证。

### 7.3 验收标准

正确性硬门槛：

- cache on/off 所有测试结果一致；
- shadow mismatch 为 0；
- 无 crash、use-after-free、错误 preserve 或 record/replay 缺项；
- IR 修改后不返回旧结果；
- 不改变 TCE/CHA 优化语义和生成代码正确性。

性能门槛：

- 输出真实 workload 的分层 hit/miss 和 callback 减少量；
- JavaType 查询自身耗时有稳定下降；
- TCE/CHA 不出现统计显著回退；
- 缓存查找、维护和内存成本小于避免的计算成本；
- 端到端优化时间至少无显著回退。

“显著降低”应在阶段 0 基线后转化为明确的数值目标。如果 JavaType 仅占总编译时间很小
比例，则不应以不现实的整体编译时间降幅否定查询缓存本身；但也不能仅凭较高 hit rate
宣称项目获得性能收益。

## 8. 仓库中可借鉴的缓存实践

### 8.1 RecoverTypeInfo 的 callback memoization

位置：`llvm/lib/Transforms/Jeandle/RecoverTypeInfo.cpp`

原用途：在一次 RecoverTypeInfo Pass 内缓存：

- `GetFieldType`；
- `GetOopKlass`；
- `IsEffectivelyFinal`；
- `IsUnverifiedInterface`；
- `GetCommonSuperKlass`。

与本项目关系：它是 JVM relation cache 的直接原型。

可复用实践：

- 按 callback 参数构造 key；
- LCA 对称参数规范化；
- 缓存 `0` 和 `false`；
- 不依赖缓存迭代顺序；
- 在 callback replay 约束下保持确定性。

不能直接复用的部分：这些 map 当前是 `run()` 局部变量，Pass 返回后销毁，不能跨 Pass。

### 8.2 RecoverTypeInfo 的数据流 fixpoint

原用途：从 Argument、Call、metadata、oop handle 和字段地址传播 Java 类型，重新为丢失
类型信息的 field load 附加 metadata。

与本项目关系：提供循环 PHI、互递归 PHI、Select 和转发图的收敛算法参考。

可复用实践：

- Top/Known/Bottom 格；
- 单调下降；
- 程序顺序 sweep；
- 避免 pointer-key map 迭代导致 replay 非确定性；
- 循环上限作为防御措施；
- 互递归 PHI 定向测试。

### 8.3 PhiValues 的惰性缓存和 CallbackVH

位置：

- `llvm/include/llvm/Analysis/PhiValues.h`；
- `llvm/lib/Analysis/PhiValues.cpp`。

原用途：按需计算并缓存 PHI 图最终可达的非 PHI Value。

与本项目关系：提供 PHI 递归图、Value 删除/RAUW 和局部依赖失效模式。

可复用实践：

- 查询时惰性填充；
- 对 PHI SCC 统一处理；
- 使用 `CallbackVH` 监听 Value 删除和 RAUW；
- operand 修改由使用者显式调用 `invalidateValue()`；
- 通过可达关系找到受影响的上游 PHI。

### 8.4 LazyValueInfo 的 `(Value, BasicBlock/Edge)` 缓存

位置：

- `llvm/include/llvm/Analysis/LazyValueInfo.h`；
- `llvm/lib/Analysis/LazyValueInfo.cpp`。

原用途：缓存某个 LLVM Value 在基本块、指令或 CFG 边上的常量和取值范围约束。

与本项目关系：查询形态最接近程序点敏感 Java 类型分析。

可复用实践：

- Value + BasicBlock 的缓存组织；
- 缓存 unknown/overdefined 结果；
- `CallbackVH` 删除保护；
- `forgetValue()`、`eraseBlock()`、`threadEdge()`、`clear()` 更新接口；
- 无法局部维护时保守清理。

### 8.5 FunctionAnalysisManager 生命周期

位置：

- `llvm/lib/Jeandle/Pipeline.cpp`；
- `llvm/lib/Transforms/Jeandle/JeandleInlineDriver.cpp`；
- LLVM `PassManager.h`。

原用途：缓存 Function Analysis 结果，并根据 `PreservedAnalyses` 跨 Pass 复用或失效。

与本项目关系：是 JavaTypeAnalysis 的生命周期所有者。

可复用实践：

- `FAM.getResult<Analysis>(F)`；
- `Result::invalidate()`；
- `PreservedAnalyses::preserve<Analysis>()`；
- driver 内 `FAM.invalidate()`；
- 删除 Function 前 `FAM.clear()`；
- Analysis 对 DT 等下游分析的依赖失效传播。

### 8.6 VMCallbackLog 的参数到结果映射

位置：

- `llvm/include/llvm/IR/Jeandle/VMCallback.h`；
- `llvm/lib/IR/Jeandle/VMCallbackLog.cpp`。

原用途：记录和离线重放 JVM callback，验证单次编译内相同参数返回相同结果。

它不是性能缓存：录制 trampoline 仍会先执行真实 callback，再对新 key 进行记录。

与本项目关系：

- 为 JVM relation cache 提供纯函数合同；
- 规定缓存行为必须保持 record/replay callback 集合可重现；
- 说明不能使用跨编译静态缓存导致当前 `.cblog` 漏项；
- 提醒避免 pointer-key 容器的非确定迭代控制 callback 集合。

## 9. 可被项目复用的现有接口

| 接口 | 当前用途 | 本项目复用方式 |
| --- | --- | --- |
| `jeandle::getJavaType` | 无缓存 Java 类型查询 | V1 miss 内核、JDK 构造期接口、shadow oracle |
| `jeandle::typeUnion` | 合并 PHI/Select 候选类型 | Base/递归子问题合并 |
| `jeandle::typeIntersect` | 合并基础类型与路径约束 | FullType 计算 |
| `jeandle::extractKlassConstant` | 从 IR Value 提取 Klass 常量 | condition trace、TCE 和缓存 evaluator |
| `jeandle::areKlassesIncompatible` | 判断 Java 单继承下类型不兼容 | TCE 和 relation cache 使用者 |
| `Value::stripPointerCastsAndAliases` | 规范化 pointer cast/alias | 顶层 Value key 规范化 |
| `jeandle::getVMCallbacks` | 获取已注册 JVM callback | relation cache miss 路径 |
| `jeandle::getOopHandleId` | 识别常量 oop handle | BaseType/GetOopKlass 缓存 |
| `DominatorTreeAnalysis` | 提供支配树 | SharpenedType 依赖 |
| `BasicBlockEdge`/`DT.dominates` | 边支配判断 | 成功/失败分支事实与 PHI incoming |
| `DomTreeUpdater` | 变换后维护 DT | CHA 修改 CFG 后更新并再查询 |
| `FunctionAnalysisManager::getResult` | 获取/缓存分析结果 | 消费者统一入口 |
| `FunctionAnalysisManager::invalidate` | 应用 Pass 失效结果 | driver 多步骤生命周期 |
| `FunctionAnalysisManager::clear` | 删除 Function 前清分析 | 防止 Function/Value 悬空 |
| `PreservedAnalyses` | 声明分析是否仍有效 | JavaTypeAnalysis 跨 Pass 复用纪律 |
| `AnalysisManager::Invalidator` | 检查依赖分析失效 | 检查 DominatorTreeAnalysis |
| `CallbackVH` | Value 删除/RAUW 回调 | 清除 Value 及其反向依赖 entry |
| `PhiValues::invalidateValue` 模式 | operand 变化通知 | 设计 JavaType `invalidateValue/Phi` |
| `LazyValueInfo::forgetValue` 模式 | 清理指定 Value 缓存 | 设计局部失效 API |
| `LazyValueInfo::eraseBlock` 模式 | CFG block 删除通知 | 清理 Context/Edge 缓存 |
| `LazyValueInfo::threadEdge` 模式 | CFG edge 修改通知 | 局部失效支配事实 |
| `STATISTIC`/LLVM Pass timing | Pass 统计与耗时 | hit/miss、callback 和 Pass 性能验证 |

其中 `PhiValues` 和 `LazyValueInfo` 是设计模式参考，不表示 JavaTypeAnalysis 应直接依赖或
调用它们。它们分析的是通用 LLVM 值事实，不能替代 JVM Klass 语义。

## 10. 预计代码改动范围

### 一期新增

```text
jeandle-llvm/llvm/include/llvm/Analysis/Jeandle/JavaTypeAnalysis.h
jeandle-llvm/llvm/lib/Analysis/Jeandle/JavaTypeAnalysis.cpp
jeandle-llvm/llvm/test/Jeandle/java-type-analysis/...
```

### 一期修改

```text
jeandle-llvm/llvm/lib/Analysis/CMakeLists.txt
jeandle-llvm/llvm/lib/Passes/PassBuilder.cpp
jeandle-llvm/llvm/lib/Passes/PassRegistry.def
jeandle-llvm/llvm/lib/Transforms/Jeandle/TypeCheckElimination.cpp
jeandle-llvm/llvm/lib/Transforms/Jeandle/CHADevirtualization.cpp
```

### 二期可能修改

```text
jeandle-llvm/llvm/include/llvm/IR/Jeandle/JavaType.h
jeandle-llvm/llvm/lib/IR/Jeandle/JavaType.cpp
jeandle-llvm/llvm/lib/Transforms/Jeandle/RecoverTypeInfo.cpp
```

二期对 `JavaType.cpp` 的修改应以抽取共享 evaluator/查询接口为主，不改变现有语义。
是否让 RecoverTypeInfo 共享更高层 JVM relation cache，应在确认生命周期、组件依赖和收益
后单独实施，不与 V1 强绑定。

JDK 前端第一处 `getJavaType` 调用继续保留；`null_check` 中未使用结果应作为独立清理提交，
避免把无关行为变化混入缓存实现。

## 11. 主要风险与控制措施

| 风险 | 后果 | 控制措施 |
| --- | --- | --- |
| Context key 不完整 | 不同程序点串值 | V1 只缓存公开查询；PHI 使用独立 Edge key |
| unknown 与 Computing 混淆 | 循环 PHI 错误 | V1 不缓存递归；后续使用完成态/SCC |
| Pass 内修改未 clear | 同一 `run()` 返回旧结果 | 所有消费者修改路径立即清理或通知 |
| 错误 preserve | 跨 Pass 使用陈旧结果 | 默认不 preserve；完成更新纪律后才 preserve |
| DT 失效未传播 | 路径锐化错误 | `invalidate()` 检查 `DominatorTreeAnalysis` |
| Value 删除后悬空 | 崩溃或地址复用误命中 | `CallbackVH`、修改后 clear、FAM 生命周期 |
| callback 静态缓存跨编译 | Klass/假设错误、replay 漏项 | 严格限制在单次 Pipeline/Function 生命周期 |
| 缓存成本超过计算成本 | JIT 编译变慢 | disable A/B、分层统计、按数据决定扩展 |
| 统计本身开销过高 | 性能数据失真 | 内部计时可关闭，release 多轮复测 |
| 一次重构语义和缓存 | 难以定位错误 | 旧函数保留为 oracle，分阶段抽取 evaluator |

## 12. 最终实施建议

推荐执行顺序：

1. 阶段 0 建立无缓存基线；
2. 阶段 1 完成 V1 Function Analysis、消费者迁移和正确性框架；
3. 根据真实数据优先实现 Base cache 和 JVM relation cache；
4. 再实现 Sharpen cache 和无环递归子问题缓存；
5. 对循环 PHI 使用独立的 SCC/fixpoint 方案；
6. 只有 clear/重算被证明是主要瓶颈时，再建设依赖图和局部失效；
7. 始终保留无法证明安全时整体失效的后备路径。

项目的核心价值不是构造尽可能复杂的缓存，而是在严格保持旧查询等价的前提下，使：

```text
缓存查找与维护成本
    <
被避免的 IR/DT 遍历和 JVM callback 成本
```

一期应以“正确接入、可验证、可测量”为完成标准；分层缓存和局部失效应由实际 workload
数据驱动，而不是在缺少基线时一次性实现全部长期目标。
