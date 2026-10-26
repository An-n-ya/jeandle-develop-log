# JavaType / LVI argument condition 优化执行报告

日期：2026-10-23。状态：实现、正确性验证及六轮主回放对照完成，已提交，未推送。

## 1. 分支与实现

- 服务器仓库：`annya@100.122.220.40:/home/annya/playground/jeandle/jeandle/jeandle-llvm`。
- 基线：`test/javatype-cache-design`，`8df28fa046fd59251be09a065a468c08628dd397`。
- 新分支：`perf/lvi-select-demand-undef`。
- 提交：`599e47ee8b8096695f6c723202573a5c12899520`。
- 提交后工作树干净；原 cache-design 分支指针未改变。

最终在 `llvm/lib/Analysis/LazyValueInfo.cpp:937` 附近新增 7 行：

```cpp
// getValueFromCondition cannot derive constraints from a plain argument.
// Avoid proving the condition is not undef when it cannot refine either arm.
if (isa<Argument>(Cond)) {
  TrueVal.mergeIn(FalseVal);
  return TrueVal;
}
```

当前 `getValueFromCondition` 无法从普通 Argument 条件中提取约束，返回 `overdefined`。原有逻辑即使证明 condition 不为 undef，对两个分支做的 intersect 也不会改变值。因此这里直接合并两侧结果；condition 为指令时仍走原来的证明与约束提取顺序。

这覆盖原报告中反复使用 `%c` 参数的 select 链，减少单次 LVI 求解内部的工作。没有新增缓存或改变分析失效规则。

补丁：[candidate.patch](artifacts/lvi-argument-undef-2026-10-23/final/candidate.patch)。源码及二进制身份：[identity-post.json](artifacts/lvi-argument-undef-2026-10-23/final/identity-post.json)。候选二进制在提交前构建，内嵌 revision 仍为基线；其源码内容与最终提交一致。

## 2. 实验发现与方案收窄

[前期审查](JavaType-LVI-Optimization-Review-2026-10-23.md) 建议先提取两侧约束，有用时才做 undef 证明。首版确实改善了主回放，但压力测试发现：条件是共享布尔 DAG 时，提前提取约束会重复遍历表达式，即使原来的 undef 证明很快失败也要支付这笔成本。

因此最终只保留 Argument 快速路径。以下为已完成的压力测试，各输入 4096 个函数、每函数 32 个 select，固定 CPU 16，10 个随机配对轮次。正数表示用户态 CPU 减少，负数表示增加；数字为配对百分比的中位数。

| 输入 | 首版：提前提取约束 | 最终：Argument 快速路径 |
| --- | ---: | ---: |
| 有关条件、参数可能 undef | -3.32% | -0.33% |
| 有关条件、参数 noundef | -0.21% | +0.22% |
| 无关条件、参数可能 undef | +6.16% | -0.27% |
| 共享布尔 DAG、参数可能 undef | **-35.54%** | +0.09% |

最终版消除了首版明显的 DAG 回退；四个压力输入的完整输出 IR 均与基线逐字节一致。这里的小幅差异不构成正式的无回退保证。

证据：[首版压力结果](artifacts/lvi-argument-undef-2026-10-23/eager-proposal/stress-summary.json)、[最终压力结果](artifacts/lvi-argument-undef-2026-10-23/final/stress-summary.json)、[压力输入生成及执行脚本](artifacts/lvi-argument-undef-2026-10-23/final/run-stress.py)。压力测试在用户要求六轮收口前已完成；六轮限制应用于下面的主回放。

## 3. 正确性验证

- `JavaTypeQueryTests`：**44/44 通过**。
- lit：**448 通过、17 不支持、0 失败**，共发现 465 项。范围包括 LazyValueAnalysis、CorrelatedValuePropagation、JumpThreading、LowerSwitch、Attributor，以及原来的六组 Jeandle 测试和 repeated-CFF。未支持项见日志。
- 新增 `llvm/test/Transforms/CorrelatedValuePropagation/select-demand-undef.ll`，14 个函数覆盖普通与 noundef Argument 条件、指针、undef/poison、freeze、有关/无关比较、and/or、assume、循环和共享布尔 DAG。FileCheck 预期由基线二进制生成，候选输出保持一致。
- 原报告六个主输入的完整输出 IR，均在开启 `-verify-each` 的独立运行中与基线逐字节一致。
- 修改行的 clang-format 检查及 `git diff --check` 通过。

证据：[单测日志](artifacts/lvi-argument-undef-2026-10-23/final/unit-tests.log)、[lit 日志](artifacts/lvi-argument-undef-2026-10-23/final/lit-tests.log)、[新增测试](artifacts/lvi-argument-undef-2026-10-23/final/select-demand-undef.ll)、[六输入输出哈希](artifacts/lvi-argument-undef-2026-10-23/final/output-equality.json)。

## 4. 六轮主回放性能

按用户指示，仅使用最先完成的六轮，即 round 0–5，共 **72 次计时运行**（六场景 × 两二进制 × 六轮）。收到指示时后续轮次已经开始，随后终止；多余记录保留在原始文件中，不纳入本表。

沿用原报告六个输入及回调日志，双方均使用默认 S1 缓存模式。同一 profiling 构建配置：Release、`-O3 -DNDEBUG -g`、X86-only，关闭 assertions、LTO、RTTI 和 EH。每个二进制/场景预热一次，固定 CPU 16，每轮随机排列场景及双方执行顺序，串行运行，不与构建、其他测试或采样并发。计时关闭 stats、缓存重算校验和 `-verify-each`；CPU 时间由直接子进程的 `wait4` 获取。

| 场景 | 基线 user 秒，中位数 | 最终版 user 秒，中位数 | 配对 CPU 减少，中位数 |
| --- | ---: | ---: | ---: |
| deep-static | 5.7157 | 4.3196 | **24.43%** |
| tce-cha | 5.7724 | 4.3380 | **24.84%** |
| wide-static | 16.0800 | 14.6597 | **8.85%** |
| leaf-static | 4.9720 | 4.9438 | 0.65% |
| virtual-cfg | 11.0424 | 10.9881 | 0.49% |
| cff-cache-reuse | 6.2910 | 6.3477 | **-0.64%** |

最后一列先按每轮计算 `100 × (1 − candidate / baseline)`，再取中位数，因此不必等于前两列中位数的比值。CFF 的小幅变慢如实保留；六轮数据不足以区分其来源或保证生产无回退。

证据：[六轮汇总](artifacts/lvi-argument-undef-2026-10-23/final/summary-six-rounds.json)、[72 次运行原始数据与命令](artifacts/lvi-argument-undef-2026-10-23/final/timings-six-rounds.json)、[选择规则](artifacts/lvi-argument-undef-2026-10-23/final/selection.json)、[输入和二进制身份](artifacts/lvi-argument-undef-2026-10-23/final/identity.json)、[构建配置](artifacts/lvi-argument-undef-2026-10-23/final/build-configuration.json)。

## 5. 范围与产物

这是一个 session 的六轮诊断性对照，没有执行两个 session × 30 轮正式验收，也没有运行完整 JVM 编译或真实 Java 方法性能测试。按照六轮收口指示，没有继续执行最终版本的 perf 采样；不能把首版采样的热点占比当作最终版本证据。

服务器最终版产物目录：

```text
/home/annya/playground/jeandle/perf-results/2026-10-23-lvi-argument-undef/
```

首版反例产物目录为同级的 `2026-10-23-lvi-demand-undef/`。原 10 月 23 日报告冻结 opt 已保存为该目录的 `report-frozen-opt`，SHA-256 仍为 `fcd3fd2fa57c5bef3f1aef5372c936e627b08bc332cc1adabcfb6e5f947e3079`。

本地保留[记录包](artifacts/lvi-argument-undef-2026-10-23/records.tar.gz)及其解包文件；不包含大型二进制和压力输入，输入可由保存的脚本重建。最终性能结论以带 `six-rounds` 的文件为准，临时 `summary.json` 不是六轮最终汇总。
