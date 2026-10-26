# Java 类型分析缓存项目初步研究

## 1. 核心结论

项目理解总体正确：目标是把当前无状态的 `getJavaType` 查询封装成一个可复用的 LLVM Function Analysis，在同一函数的多个 Jeandle Pass、多个查询点和可复用的 PassManager 生命周期内缓存 Java 类型分析结果，减少重复的 IR/支配树遍历和 JVM 回调。

需要修正的一点是：并不是 `JavaType` 对象本身具有运行时“动态状态”，而是分析结论具有**程序点敏感性**。同一个 LLVM `Value`：

- 在没有查询上下文时，只有参数 attribute、调用返回 attribute、load metadata、PHI/select 传播得到的基础类型；
- 在某个具体基本块中，可能受到支配该位置的 `jeandle.check_instanceof` 分支约束，被锐化为更具体的类型；
- 在类型检查失败的分支中，还可能得到“排除某些类型”的负面约束。

因此，缓存不能只采用 `Value *` 作为上下文查询的键；基础类型和程序点类型需要分层缓存。AnalysisManager 也不会自动保证跨 Pass 复用：只有 IR 未改变，或变换 Pass 明确、正确地保留该分析时，缓存才能继续生效。

## 2. 现有实现与数据流

### 2.1 接口和实现

- 接口：`jeandle-llvm/llvm/include/llvm/IR/Jeandle/JavaType.h:80`
- 实现入口：`jeandle-llvm/llvm/lib/IR/Jeandle/JavaType.cpp:1125`
- 基础查询：`JavaType.cpp:326` 的 `getBaseJavaType`
- 上下文锐化：`JavaType.cpp:962` 的 `sharpenFromDominators`
- PHI 上下文分析：`JavaType.cpp:1061` 的 `getPhiJavaType`

接口为：

```cpp
JavaType getJavaType(Value *V, DominatorTree *DT = nullptr,
                     Instruction *Context = nullptr);
```

`JavaType` 包含三类信息：

```cpp
struct JavaType {
  uintptr_t Klass = 0;                   // 0 表示没有已知的正面类型
  bool Exact = false;                    // 是否确定为该精确类型
  SmallDenseSet<uintptr_t, 2> ExcludedKlasses; // 已排除的类型
};
```

注意：`Klass == 0` 不一定等于完全未知；如果 `ExcludedKlasses` 非空，分析仍然掌握有用的负面约束。该类型目前不表达 nullability。

### 2.2 类型信息来源

基础类型主要来自：

- Java 方法参数上的 `"java-klass"` / `"java-klass-exact"` attribute；
- call/invoke 返回值上的同名 attribute；
- load 上的 `!java-klass` / `!java-klass-exact` metadata；
- 常量 oop handle，通过 JVM 的 `GetOopKlass` 查询实际类型；
- PHI、select、bitcast、addrspacecast、freeze 的传播。

这些信息主要由 JDK 前端在 `jeandle-jdk/src/hotspot/share/jeandle/jeandleUtils.cpp` 和 `jeandleAbstractInterpreter.cpp` 中附加；LLVM 优化导致 metadata 丢失后，`RecoverTypeInfo` 会尝试恢复。

上下文锐化从 `Context` 所在基本块沿 DominatorTree 向上遍历，识别支配当前位置的 `jeandle.check_instanceof` 条件。条件追踪支持直接调用、icmp、整数 cast、and/or/xor、select 和 PHI 等模式。

`VMCallback.h` 已明确规定：同一编译期间，所有 JVM callback 对相同参数必须返回相同结果，record/replay 层还会检测违反该纯函数假设的情况。这为缓存类型关系查询提供了基础；但完整 `JavaType` 结果还依赖可变 IR，仍必须遵守 LLVM 分析失效规则。

### 2.3 当前消费者

真正位于 LLVM PassManager 中的直接调用有两处：

- `TypeCheckElimination.cpp:81`：查询被检查对象的类型，将确定成立或失败的 `check_instanceof` 折叠为常量；
- `CHADevirtualization.cpp:115`：查询虚调用 receiver 的类型，将 `Klass` 和 `Exact` 交给 JVM CHA 查询以决定能否去虚拟化。

JDK 前端还有两处直接调用：

- 数组元素 load 生成期间查询数组类型，据此附加元素类型 metadata；
- `null_check` 中存在一次当前结果未被使用的基础查询。

这两处发生在 IR 构造阶段，没有 `FunctionAnalysisManager`，不能直接迁移为 Function Analysis 查询。项目第一阶段应迁移两个 LLVM Pass 消费者，同时保留底层无缓存查询供前端使用，并单独确认 `null_check` 中的未使用调用是否应删除。

## 3. 现有 `getJavaType` 的使用方法

只查询值自身携带和传播得到的基础类型：

```cpp
jeandle::JavaType Base = jeandle::getJavaType(Obj);
if (Base.isKnown()) {
  use(Base.Klass, Base.Exact);
}
```

查询某个程序点上的锐化类型：

```cpp
DominatorTree &DT = FAM.getResult<DominatorTreeAnalysis>(F);
jeandle::JavaType AtUse = jeandle::getJavaType(Obj, &DT, ContextInst);

if (AtUse.isKnown()) {
  usePositiveType(AtUse.Klass, AtUse.Exact);
}
for (uintptr_t Excluded : AtUse.ExcludedKlasses) {
  useNegativeConstraint(Excluded);
}
```

使用约束：

- 需要上下文锐化时，`DT` 和 `Context` 应同时提供；只传 `Context` 而不传 `DT`，当前实现会退化为基础查询；
- `Context` 表示“在哪条指令处询问 `V` 的类型”，不是 `V` 的定义位置；
- 上下文类型依赖 JVM 回调已经注册；
- 返回结果不包含是否为 null。当前两个 Pass 的使用成立，是因为 `check_instanceof` / receiver 的 IR 契约提供了所需的 non-null 条件。

## 4. 最小案例：同一个值在三个位置具有三种结论

设 `K_OBJECT = 100`、`K_DOG = 200`，并且 JVM 知道 `Dog <: Object`：

```llvm
define void @demo(ptr addrspace(1) "java-klass"="100" %obj) {
entry:
  %is_dog = call i1 @jeandle.check_instanceof(
      ptr inttoptr (i64 200 to ptr), ptr addrspace(1) %obj)
  br i1 %is_dog, label %yes, label %no

yes:
  call void @use(ptr addrspace(1) %obj) ; ContextYes
  ret void

no:
  call void @use(ptr addrspace(1) %obj) ; ContextNo
  ret void
}
```

三个查询的预期结果如下：

| 查询 | 结果 | 含义 |
| --- | --- | --- |
| `getJavaType(%obj)` | `{K_OBJECT, false, {}}` | 只知道参数声明类型 |
| `getJavaType(%obj, DT, ContextYes)` | `{K_DOG, IsEffectivelyFinal(K_DOG), {}}` | 真分支由支配检查锐化为 Dog |
| `getJavaType(%obj, DT, ContextNo)` | `{K_OBJECT, false, {K_DOG}}` | 假分支仍以 Object 为上界，但确定不是 Dog |

这正是 TypeCheckElimination 的作用基础：如果在 `yes` 中再次检查 `%obj instanceof Dog`，可以折叠为 `true`；如果在 `no` 中再次进行相同检查，可以利用 `ExcludedKlasses` 折叠为 `false`。

仓库中已有两个可直接观察该功能的例子：

- `type-check-elimination/instanceof-known-subtype.ll` 展示基础类型使检查折叠为 `true`；
- `cha-devirtualization/intersect-exact.ll` 展示支配检查把 receiver 锐化为 effectively-final 类型并触发去虚拟化。

在当前 release 构建上运行这两个 lit 测试，结果为 2/2 通过。

## 5. 分析类的大致位置和初步构造

### 5.1 推荐位置

保留现有语义内核：

- `llvm/include/llvm/IR/Jeandle/JavaType.h`
- `llvm/lib/IR/Jeandle/JavaType.cpp`

新增 Function Analysis：

- `llvm/include/llvm/Analysis/Jeandle/JavaTypeAnalysis.h`
- `llvm/lib/Analysis/Jeandle/JavaTypeAnalysis.cpp`
- 将实现文件加入 `llvm/lib/Analysis/CMakeLists.txt`；
- 在 `PassBuilder.cpp` 包含新头文件，并在 `PassRegistry.def` 的 `FUNCTION_ANALYSIS` 区注册，例如 `java-type`；
- 当前 Jeandle pipeline 已调用 `PassBuilder::registerFunctionAnalyses(FAM)`，注册后可由现有 FAM 获取。

先保留 `getJavaType` 自由函数很重要：JDK 前端在 PassManager 运行前仍需要基础查询，而且这样可以先把“缓存与生命周期改造”和“既有复杂语义重构”分开验证。

### 5.2 初步类形态

```cpp
class JavaTypeAnalysisResult {
public:
  JavaTypeAnalysisResult(Function &F, DominatorTree &DT);

  JavaType getJavaType(Value *V, Instruction *Context = nullptr);

  bool invalidate(Function &F, const PreservedAnalyses &PA,
                  FunctionAnalysisManager::Invalidator &Inv);

private:
  Function &F;
  DominatorTree &DT;

  DenseMap<Value *, JavaType> BaseCache;
  DenseMap<std::pair<Value *, BasicBlock *>, JavaType> ContextCache;
};

class JavaTypeAnalysis : public AnalysisInfoMixin<JavaTypeAnalysis> {
  friend AnalysisInfoMixin<JavaTypeAnalysis>;
  static AnalysisKey Key;

public:
  using Result = JavaTypeAnalysisResult;
  Result run(Function &F, FunctionAnalysisManager &FAM);
};
```

Pass 侧调用形态变为：

```cpp
auto &JTA = FAM.getResult<jeandle::JavaTypeAnalysis>(F);
jeandle::JavaType ObjType = JTA.getJavaType(Obj, CheckCB);
```

### 5.3 初步缓存策略

第一阶段建议采用两级、按需填充的函数内缓存：

1. 先按现有 API 一致的规则规范化 `Value`，消除 pointer cast / alias 造成的等价键；
2. 无上下文查询使用 `BaseCache[Value]`；
3. 上下文查询使用 `ContextCache[(Value, ContextBB)]`；
4. 已知、未知和只有排除集合的结果全部缓存，避免对“分析失败”反复计算；
5. 第一阶段的上下文 miss 可以直接调用现有完整自由函数；验证生命周期正确后，再拆分计算内核，使 context miss 显式复用同一 `Value` 的 `BaseCache` 结果；
6. Function Analysis 失效时整体释放缓存，第一阶段不需要 LRU；
7. 记录 base/context hit、miss、缓存项数量、JVM 回调次数和查询耗时。

以基本块而非具体 `Instruction *` 作为公开上下文键，符合当前算法：它只读取 `Context->getParent()` 并分析支配分支，同一基本块内的普通公开查询结论相同。这比 `(Value, Instruction)` 更容易命中。内部 PHI incoming 分析若也要缓存，还需要表达目标块/边信息，不能直接复用这个简化键。

第一阶段可以只缓存完整公开查询，以最小改动验证生命周期和收益；如果 miss 成本仍高，再评估对基础递归、条件追踪、支配链前缀或纯 JVM 类型关系回调增加子缓存。

## 6. 初步技术路线

1. 建立无缓存基线：统计 `getJavaType` 调用次数、各 JVM 回调次数、两个消费 Pass 的时间；
2. 引入 `JavaTypeAnalysis` 和惰性两级缓存，保持现有自由函数作为计算内核；
3. 完成 PassBuilder/FAM 注册，迁移 TypeCheckElimination 和 CHADevirtualization；
4. 明确并测试 PreservedAnalyses 纪律，先采用保守的整分析失效；
5. 增加 LLVM lit 测试，覆盖命中、未知结果缓存、不同上下文不串值、IR 变化后重算和 DominatorTree 依赖失效；
6. 运行 jeandle-llvm 与 jeandle-jdk 现有测试，重点复用大型 `TestTypeCheckElimination.java`；
7. 用 release 构建进行多轮性能测量，通过 `-time-passes`、缓存统计和 JVM callback 统计比较改造前后；
8. 根据真实 miss 分布再决定是否引入更细的子问题缓存或上下文等价归并。

## 7. 当前识别出的重难点（暂不展开具体方案）

- 上下文缓存键的完备性，尤其是 PHI incoming 的边语义与 `DestBB`；
- PHI/loop 循环图中的递归缓存、访问中状态和结果顺序无关性；
- 非 CFG 修改也会改变类型结论，例如 attribute、metadata、operand、branch condition 和 RAUW；
- Transform Pass 在一次 `run` 内边查询边删除/替换 IR 时，缓存可能在 PassManager 执行失效前已经陈旧；
- 缓存键中的 `Value *`、`BasicBlock *` 和 `Instruction *` 被删除后的生命周期安全；
- JavaTypeAnalysis 与 DominatorTreeAnalysis 的依赖失效传播；
- “跨 Pass/跨轮复用”与保守正确性失效之间的命中率平衡；
- JVM Klass 指针、类层次关系和 callback 结果在一次编译生命周期内的有效性边界；
- nullability 未建模带来的 API 适用范围和未来消费者约束；
- 缓存查表/内存开销可能超过简单基础查询成本，必须按查询类型分层评估；
- 缓存改变 JVM callback 调用集合后，对 callback record/replay 测试数据完整性的影响；
- LLVM Core、Analysis 与 HotSpot 链接边界，避免为前端基础查询引入反向组件依赖。

## 8. 适合作为申请书的项目表述

本项目拟面向 Jeandle JIT 编译热路径，设计并实现一种程序点敏感的 Java 类型分析缓存。项目以 LLVM new PassManager 的 Function Analysis 为载体，将值自身的基础 Java 类型和由控制流支配条件产生的上下文锐化类型分层缓存，在保证 IR 变换后正确失效的前提下，实现类型分析结果跨优化 Pass 复用。项目将迁移 TypeCheckElimination、CHADevirtualization 等现有消费者，建立命中率、回调次数和 Pass 耗时统计，并通过 LLVM lit、Jeandle JDK jtreg 及编译性能测试验证正确性与性能收益。
