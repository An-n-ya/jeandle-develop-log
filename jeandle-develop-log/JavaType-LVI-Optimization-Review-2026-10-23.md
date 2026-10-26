# getJavaType / LVI null-edge 优化代码审查

日期：2026-10-23。范围：只读审查服务器源码，未修改、构建或运行服务器代码；下面的代码是待验证建议，不是已测得收益。

后续实施修正：通用的“先提取约束”方案在共享布尔 DAG 压力输入上出现约 35.5% CPU 回退，最终只保留 Argument condition 的快速路径。实现、反例与用户指定的六轮主回放结果见[执行报告](JavaType-LVI-Argument-Undef-Optimization-Execution-2026-10-23.md)。以下保留当时的审查与实验假设，不代表最终落地范围。

## 依据与源码身份

- 性能依据：[执行报告](JavaType-Cache-Perf-Profiling-Execution-2026-10-23.md)。报告支持“本轮 L1 的主要剩余成本在上下文查询，尤其是 LVI”，并不证明所有 getJavaType 工作负载都有这个瓶颈；CFF 回放没有查询 LVI 样本。
- 服务器源码根：`annya@100.122.220.40:/home/annya/playground/jeandle/jeandle/jeandle-llvm/llvm`。
- 已核对 HEAD：`357604c7724e49eace6fbfa42e4f671b12b5ff98`，分支 `test/javatype-cache-design`，仍存在报告中的未提交改动。
- 重新计算的 `CachedJavaType.cpp`、`LazyValueInfo.cpp`、`ValueTracking.cpp` SHA-256 均与报告 `source-context.json` 一致。
- 同时查询了 [GitHub compare](https://github.com/jeandle/jeandle-llvm/compare/main...Atm2086:jeandle-llvm:feat/javatype-selective-invalidation) 的变更清单；它是不同状态，不能替代上述工作树。以下行号全部对应服务器工作树。

## 调用链与成本来源

```text
JavaTypeAnalysisResult::getJavaType
  → getCachedJavaType → factsAt
  → isNullEdge → LVINullEdgeOracle::operator()
  → LVI.getPredicateOnEdge(ICMP_EQ, V, null, From, To)
  → getValueOnEdge → getEdgeValue → getBlockValue → solve
  → solveBlockValueSelect
  → isGuaranteedNotToBeUndef(Cond, AC)
  → programUndefinedIfUndefOrPoison
```

关键位置：

| 服务器 LLVM 相对路径 | 行号 | 观察 |
| --- | --- | --- |
| `lib/Analysis/Jeandle/CachedJavaType.cpp` | 1276、1334–1341 | 非回边前驱逐个请求 null 证明，再递归合并路径事实 |
| `lib/Analysis/Jeandle/LVINullEdgeOracle.cpp` | 24–40 | 规范化指针后直接调用 LVI；没有自己的结果缓存 |
| `lib/Analysis/LazyValueInfo.cpp` | 933–950 | select 合并前无条件尝试 undef 证明，证明通过才提取条件约束 |
| 同上 | 1480–1533 | 条件无法识别时返回 `overdefined`；普通 `i1` 参数属于这种情况 |
| `lib/Analysis/ValueTracking.cpp` | 7767–7947、8270–8316 | undef 证明可能扫描定义后的指令；扫描预算为 32，循环先递减再检查 |
| `lib/Transforms/Jeandle/CHADevirtualization.cpp` | 477、483、612–615 | helper 修改后、RAUW 后及成功改写后清空 LVI |

这里 `isNullEdge` 是昂贵分析的入口。它要回答一个布尔问题，但通用 LVI 会求解指针值的格信息，并递归处理 select 输入。BaseTypes 保存 Java 类型；它不能代替这些指针/undef/路径事实。

## 第一优先：条件约束有用时，才证明 condition 不为 undef

这是比新增缓存更先值得尝试的改动。

当前逻辑：

```cpp
if (isGuaranteedNotToBeUndef(Cond, AC)) {
  TrueVal = TrueVal.intersect(*getValueFromCondition(
      SI->getTrueValue(), Cond, true, false));
  FalseVal = FalseVal.intersect(*getValueFromCondition(
      SI->getFalseValue(), Cond, false, false));
}
TrueVal.mergeIn(FalseVal);
```

建议在 `solveBlockValueSelect` 的原有 min/max、abs 特判之后替换这段：

```cpp
Value *Cond = SI->getCondition();
auto TrueConstraint = getValueFromCondition(
    SI->getTrueValue(), Cond, /*IsTrueDest=*/true,
    /*UseBlockValue=*/false);
auto FalseConstraint = getValueFromCondition(
    SI->getFalseValue(), Cond, /*IsTrueDest=*/false,
    /*UseBlockValue=*/false);
assert(TrueConstraint && FalseConstraint);

if ((!TrueConstraint->isOverdefined() ||
     !FalseConstraint->isOverdefined()) &&
    isGuaranteedNotToBeUndef(Cond, AC)) {
  TrueVal = TrueVal.intersect(*TrueConstraint);
  FalseVal = FalseVal.intersect(*FalseConstraint);
}
TrueVal.mergeIn(FalseVal);
return TrueVal;
```

正确性依据：

1. `UseBlockValue=false` 的接口契约明确保证不入求解 worklist、不会返回 `nullopt`（`LazyValueInfo.cpp:436` 附近）。这里先取得的是候选约束，尚未应用它。
2. `ValueLatticeElement::intersect` 中，另一侧为 `overdefined` 时直接返回当前值（`lib/Analysis/ValueLattice.cpp:78–92`）。两侧约束都为 `overdefined` 时，原来的 undef 证明无论真假都不影响结果。
3. 任何一侧存在约束时仍保留原来的 `isGuaranteedNotToBeUndef` 检查。不能因为预先提取了约束，就直接应用它。

对本轮输入的具体解释：`benchmark-java-type-cache-design.py:150–158` 生成的 condition 是没有 `noundef` 的普通参数 `%c`，select 的两个结果是 oop 指针。`getValueFromCondition` 对这个 `%c` 不匹配 icmp/trunc/overflow/not/and/or，直接返回 `overdefined`。因此这段路径的 undef 证明可以完全不执行，不只是从每层一次降为每个 Cond 一次。

代价：原来 undef 证明立即返回 false 的复杂条件，现在也要先做两次条件匹配。因此不能只测重复 `%c` 的合成输入；必须补复杂布尔条件和 undef 条件的对照。必要时可按条件形状做更窄的快速路径，但第一版不建议引入新的条件分类器。

## 第二优先：为仍然需要的 undef 证明做局部 memo

如第一项之后 ValueTracking 仍是热点，再添加 `Cond → bool` 局部缓存。

- 固定请求必须仍为 `isGuaranteedNotToBeUndef(Cond, AC)`；它与 NotPoison、NotUndefOrPoison 不是同一个问题。
- 第一版可仅覆盖一次 `solve()`，用作用域清理确保正常返回和 `MaxProcessedPerValue` 提前返回都释放结果。
- 更完整的方案是覆盖一次公开查询：`getValueInBlock`、`getValueOnEdge`、`getValueAtUse` 等入口及其嵌套调用。`getValueOnEdge:1801` 的循环可能多次调用 `solve()`，仅在 solve 内缓存不能复用整个 edge query 的重复 condition。
- 审查所有调用点：`LazyValueInfo.cpp:939`（select）、1021（binop-over-select）、1837（at-use）。仅修改第一处不覆盖其余路径。
- `false` 在相同 IR、AC 和证明参数下也可以 memo；含义是“本次未证明”，不等于“该值必为 undef”。
- 不跨 IR 修改保留普通 `Value*` 缓存。即使 Cond 本身没变，后面的 UB 使用、call 属性、assume 或 CFG 变化都可能改变证明。

先做第一项、后独立测第二项，避免把省掉工作和复用工作混为一个性能结论。

## 其他方向及不建议的捷径

1. **减少不必要的 LVI 清空值得后续审计，但工程风险更高。** 需要改写 helper 报告实际修改内容，并证明 LVI、PathFacts、FinalTypes 的保留契约。`ActualLVIObservesDereferenceMutationAfterClear` 和 `SelectiveResultStillDependsOnLVIInvalidation` 已显示依赖不仅来自被查询值的 SSA users。
2. **增加直接 null guard 快速路径，对当前热点未必有明显帮助。** LVI 的 `getEdgeValueLocal` 已处理直接条件边；`getEdgeValue:1730` 附近遇到单值 local result 就返回。重复实现前先统计有多少昂贵调用确实能被新 fast path 截断。缓存引擎注释提到 structural fast path，但实际 `isNullEdge` 实现直接委托 oracle，注释需与实现区分。
3. **不要把“不是直接 null guard”当作“不可能是 null edge”。** LVI 还能通过前驱、PHI/select、assume 等推导；跳过这些查询可以保持保守，但会丢失类型优化精度，必须显式评估。
4. **不要用 java-klass 已知代替 nonnull 证明，也不要随意增加 noundef。** 参数 `%c` 是否 noundef 是 IR 语义契约，必须由前端提供依据。
5. **不优先增加跨查询 edge-result 缓存。** 当前 Path/Final 命中为零，LVI 又频繁清空；新缓存同样要面对失效，先减少单次求解中的无用工作更直接。

## 验证建议

先将第一项作为独立实验，不放宽任何失效规则。

- 正确性：原 JavaType 单测和六组 Jeandle lit；补 `test/Analysis/LazyValueAnalysis/` 与 `test/Transforms/CorrelatedValuePropagation/`。现有 `select.ll` 中 `select_cond_may_undef` 是必查回归点。
- 新增覆盖：普通 i1 参数、noundef 参数、freeze、undef/poison、有效与无关 icmp、嵌套 and/or、指针与整数 select、循环、assume 和预算耗尽；确认有效约束仍受 undef 证明保护。
- 差分：旧/新 LVI 的实际查询返回值、最终 JavaType、输出 IR 和关键优化次数。只开启 `-jeandle-verify-java-type-cache` 不足以验证 LVI 改动，因为缓存/参考引擎可能共用同一个修改后的 LVI。
- 计数在独立诊断运行中记录：select 处理数、两侧约束均 overdefined 的次数、实际 undef 证明次数；若加 memo，再记录 hit/miss 和 ValueTracking 实际调用次数。
- 性能：分别比较原 S1、仅按需证明、仅局部 memo、两者组合；沿用同一构建配置和配对回放。除 deep/tce 外覆盖 wide/leaf/virtual，避免局部改善掩盖其他场景回退。
- 正式性能结论仍需报告约定的两个 session × 30 轮；“LVI 占 45%”不能当作这项修改的收益预测。

建议实施顺序：**按需证明 → 测量剩余热点 → 必要时局部 memo → 最后审计 LVI 清空契约**。
