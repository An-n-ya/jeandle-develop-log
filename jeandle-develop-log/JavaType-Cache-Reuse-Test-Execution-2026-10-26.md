# JavaType 缓存复用测试执行记录

> 阅读入口（2026-10-27 整理）：[跨 pass 缓存测试总结](../汇报/跨pass缓存测试总结.md)。本文保留第一轮执行细节；后续完整流水线和 JVM 结果见[第二轮报告](JavaType-Cross-Pass-Production-Performance-2026-10-26.md)。

日期：2026-10-26。状态：P0–P3 完成，P4 完成指定流水线探测与部分负对照；任务 8 未执行。

本文记录实际执行结果，不修改原计划
[JavaType-Cache-Reuse-Test-Execution-Plan-2026-10-26.md](JavaType-Cache-Reuse-Test-Execution-Plan-2026-10-26.md)。
本轮默认范围是测试与测量，没有推进 CFF／RecoverTypeInfo 修改后 preserve
JavaTypeAnalysis 的生产实现。

## 1. 结论边界

本轮能够证明：

- TCE 同块连续查询会消费 Final 条目；TCE 浅层和深层输入只复用独立
  Base，Final 使用不同的 ContextBB 键。
- RecoverTypeInfo 对同一 receiver 的两个不同字段 load 复用同一个 Base，
  并分别写出正确的 `!java-klass` metadata。
- X01 CROSS-PASS 的下游首次查询直接命中上游 TCE 写入的 Final 条目；
  X01 PASS-LOCAL 的下游首次查询在边界清空后 miss，并重新插入 Base。
- X03 折叠引起的 selective invalidation 会删除 Final、保留 Base；
  CROSS-PASS 下游不重新插入 Base，而 PASS-LOCAL 会在边界后重新插入。
- TCE、RecoverTypeInfo、CFF、CHA 四个消费者都出现了实际查询和相应的
  Base／PathFacts／Final 轨迹；负对照保持零命中。
- X07 在关闭 PEA 的实际 `--jeandle` 流水线中仍有缓存消费。

本轮不能证明：

- 不能证明完整生产 pipeline 的收益；X07 只覆盖 PEA 关闭的 Jeandle pipeline。
- 不能证明正向加速。5 轮 pilot 的本轮进程级时间波动很大，且包含启动与 IR
  解析，不能据此下性能结论。
- 不能证明 JVM 应用级性能、完整 LVI oracle 工作量或任务 8 的 preserve 合同。
- 不能把现有 17 个全目录失败全部归为回归；其中 10 个 TCE 红项在初始 124
  项基线中就存在，另 7 个是扩大扫描范围后暴露的工具缺失。

机器可读汇总：

- `artifacts/java-type-cache-reuse-2026-10-26/summary/cases.csv`
- `artifacts/java-type-cache-reuse-2026-10-26/summary/query-trace.csv`
- `artifacts/java-type-cache-reuse-2026-10-26/summary/results.json`

## 2. P0：checkout、源码与现有行为

### 2.1 实际 checkout

| 项 | 实际值 |
| --- | --- |
| 远端 | `annya@100.122.220.40` |
| 仓库 | `/home/annya/playground/jeandle/jeandle/jeandle-llvm` |
| origin | `https://github.com/Atm2086/jeandle-llvm.git` |
| 分支 | `test/javatype-cache-design` |
| HEAD | `7857d0e33777bcaea8012d3e4bf17c93eccafca3` |
| tree | `6ec5ca7ea073a3112304705c89315272b9f1dd9c` |
| HEAD 提交时间 | `2026-10-25T11:43:37+08:00` |
| 原 feature ref | `feat/javatype-selective-invalidation` 同 commit |

reflog 表明测试分支从 `ea2953f61a85` checkout 后，于
`2026-10-26T12:43:39+08:00` 对 feature 分支做 fast-forward 到
`7857d0e3`；没有 force reset，没有创建 merge commit。

工作树仍含本轮未提交改动：

- 5 个已跟踪源码文件修改，`git diff --binary` SHA-256：
  `b457f239ae6cc53736561196afdc7174f05b28017445f1257e8e87b96abc8556`
- 新增未跟踪目录 `llvm/test/Jeandle/java-type-cache-reuse/`
- 没有 commit、没有 push

完整身份、逐文件 SHA-256 和 tracked diff：

- `artifacts/java-type-cache-reuse-2026-10-26/remote-results/identity/checkout-identity.txt`
- `artifacts/java-type-cache-reuse-2026-10-26/remote-results/identity/worktree-tracked.diff`
- `artifacts/java-type-cache-reuse-2026-10-26/remote-results/identity/branch-and-toolchain-provenance.txt`

### 2.2 构建与二进制身份

| 项 | 实际值 |
| --- | --- |
| LLVM | `22.0.0git`，Optimized build，X86 target |
| 构建目录 | `build/build-ninja-profiling` |
| CMake generator/build type | Ninja / `Release` |
| assertions | OFF |
| 实际 C/C++ 编译器 | `tools/bin/gcc`、`tools/bin/g++` → GCC `15.3.0` |
| shell 默认 GCC | `16.1.1`，不是本次构建所用编译器 |
| CPU / 逻辑核 / 内存 | 32 逻辑核，65,568,784 kB |
| `opt` SHA-256 | `960d2e2c3dc499035bad0d77a43d02ea9307514c27c070e59fbbc87f82f2f10e` |
| `JavaTypeQueryTests` SHA-256 | `9f78105c03284c3da3a8bbe27a8fd7238ba8fcf8492475c4cc40ad8507cce6e3` |

完整 CMake cache 选择、编译器版本和构建文件哈希见
`remote-results/identity/build-identity.txt`；主机与工具链另见
`remote-results/identity/environment-identity.txt`。

### 2.3 源码身份与现有合同

计划中列出的四个 blob SHA 与实际 checkout 一致：

| 文件 | blob SHA |
| --- | --- |
| `TypeCheckElimination.cpp` | `0b6120840c0c9b3ab8f441b16e7b01b1e4903d06` |
| `RecoverTypeInfo.cpp` | `c48282404d8341ba5c8bd3157c62a29271f97f2e` |
| `ConstantFieldFolding.cpp` | `f608dd164e9e8cd917031c41b37490dd9be6d20f` |
| `JavaTypeAnalysis.cpp` | `a1ea64c4a868d9f97d6b0044adda2177dd01979d` |

实际行为与计划一致：

- TCE 先对全部 check 做查询和折叠决策，再对 changed checks 批量
  `invalidate`，最后 RAUW；有改写时 preserve DT、LVI 和 JavaTypeAnalysis。
- RecoverTypeInfo 在一次 pass 内共享 JavaTypeAnalysis 和 LVI 快照；每个
  load 通过按 load 记忆化的 `CtxCache` 查询 QueryBase；全部查询结束后才写
  metadata；有改写时不 preserve JavaTypeAnalysis。
- CFF 多轮共享同一个 JavaTypeAnalysis，并在替换前通知失效；有改写时只
  preserve CFGAnalyses，不 preserve JavaTypeAnalysis。
- CHA 在每个 site 改写前查询；成功改写后执行 CFG invalidation 并
  `LVI.clear()`；有改写时 preserve DT、LVI 和 JavaTypeAnalysis。
- JavaTypeAnalysis 持有 DT/LVI 引用；自身未保留或 DT/LVI 失效时整个 Result
  失效。

本轮没有修改上述四个 pass 的生产变换逻辑，只增加了诊断观测：

- `-jeandle-java-type-stats`
- `-jeandle-java-type-query-trace`
- pass `jeandle-java-type-cache-boundary`

查询轨迹在真实 `getJavaType` 返回后由 observer 记录；cache verify 的冷查询
不经过该 observer，不会通过二次查询制造命中。boundary pass 只在分析已存在
时清空缓存，不主动创建 JavaTypeAnalysis、DT 或 LVI，也不改 IR。

## 3. 测试设施与输入

新增 14 个 lit，全部通过：

- TCE：`tce-same-block.ll`、`tce-shallow.ll`、`tce-deep.ll`
- TCE 负对照：`tce-zero-overlap.ll`
- RecoverTypeInfo：`recover-shallow.ll`
- 跨 pass：`tce-recover-cross-pass.ll`、`tce-fold-recover.ll`、
  `tce-cff-cross-pass.ll`、`recover-cha-boundary.ll`、
  `cff-modify-tce.ll`
- CFF／CHA：`cff-nonexact.ll`、`cha-shallow.ll`、`cha-deep.ll`
- pipeline：`x07-production-pipeline.ll`

对应 8 个完整 callback fixture 位于新增测试的 `Inputs/`。测试源码和
fixture 已保存到
`artifacts/java-type-cache-reuse-2026-10-26/remote-tests/java-type-cache-reuse/`，
逐文件 SHA-256 记录在
`remote-results/identity/checkout-identity.txt`。

已复用现有设施和负对照：

- `constant-field-folding/cache-reuse.ll`
- `java-type-analysis/selective-invalidation.ll`
- 现有 `JavaTypeCacheReuseTest` 三个直接 API 测试
- `-jeandle-verify-java-type-cache` 的全新参考查询

## 4. P1：TCE 与 RecoverTypeInfo

| 用例 | 查询 | PathFacts hit/miss | Final hit/miss | Base 插入 | 实际结果 |
| --- | ---: | ---: | ---: | ---: | --- |
| T01 同块 | 4 | 0/0 | 3/1 | 1 | 后 3 次同 Value/ContextBB 查询命中，4 个 check 均保留 |
| T01 浅层 4 兄弟块 | 4 | 0/4 | 0/4 | 1 | Final 跨 ContextBB 不共享，独立 Base 只插入一次 |
| T01 深链 | 4 | 2/3 | 0/4 | 1 | 首个 check 保留，后 3 个被上下文条件折叠；selective invalidation 删除 3 PathFacts、4 Final，Base 保留 |
| NEG 零重叠 | 4 | 0/0 | 0/4 | 4 | 4 个不同对象，每查询均 miss 并插入 Base |
| T02 Recover 浅层 | 2 | 0/2 | 0/2 | 1 | `%l0` 得 klass 7、`%l1` 得 klass 9；同一个 Base，Context 分别为 `%left/%right` |

T01 同块原始轨迹：

```text
ordinal 1: final_misses=1 base_insertions=1
ordinal 2: final_hits=1  base_insertions=0
ordinal 3: final_hits=1  base_insertions=0
ordinal 4: final_hits=1  base_insertions=0
```

RecoverTypeInfo 的最终 IR 显示两个不同字段 load 均被写 metadata：

```llvm
%l0 = load ..., !java-klass !0
%l1 = load ..., !java-klass !1
!0 = !{i64 7}
!1 = !{i64 9}
```

这证明复用来自同一个 QueryBase，而不是把同一 load 的固定点迭代重复计数。

## 5. P2：跨 pass 与 PASS-LOCAL／CROSS-PASS 消融

两种模式使用相同输入、查询引擎、DT/LVI 生命周期、callback fixture 和
pass 顺序；唯一差异是边界处是否运行
`jeandle-java-type-cache-boundary`。

### 5.1 X01：TCE 无改写 → RecoverTypeInfo

| 模式 | 查询 | Final hit/miss | Base 插入 | boundary | 下游首次查询 |
| --- | ---: | ---: | ---: | --- | --- |
| CROSS-PASS | 4 | 3/1 | 1 | 无 | ordinal 3 为 Final hit |
| PASS-LOCAL | 4 | 2/2 | 2 | `existing_analysis=1 action=clear` | ordinal 3 为 Final miss，随后 ordinal 4 hit |

CROSS-PASS 原始轨迹：

```text
ordinal 1: final_misses=1 base_insertions=1
ordinal 2: final_hits=1  base_insertions=0
ordinal 3: final_hits=1  base_insertions=0
ordinal 4: final_hits=1  base_insertions=0
```

Pass 边界在 TCE、RecoverTypeInfo 两侧分别有统计输出；CROSS-PASS 下游累计
Final hit 从 1 增至 3，且 Base 插入仍为 1。这直接证明下游两个查询都消费了
上游条目，而不是下游自身冷启动后形成的新 Final 条目。

### 5.2 X03：TCE 有折叠 → RecoverTypeInfo

TCE 对 exact receiver 折叠两个 check。折叠通知后的统计为：

- selective invalidation 1 次
- Base invalidated `0`
- Final invalidated `1`

| 模式 | 下游 Base 场景 | 累计 Base 插入 | boundary |
| --- | --- | ---: | --- |
| CROSS-PASS | 被删 Final 重新计算，独立 Base 保留 | 1 | 无 |
| PASS-LOCAL | 边界清空仍存活的 Base，下游重新插入 | 2 | `existing_analysis=1 action=clear` |

CROSS-PASS ordinal 3 的 `base_insertions=0`，而 ordinal 4 命中重新形成的
Final；PASS-LOCAL ordinal 3 的 `base_insertions=1`。这是“跨修改后 Base 存活
并被下游消费”的直接对照。

### 5.3 消融贡献的解释边界

消融证明的是查询层条目复用和 Base 重算差异，不等价于 pass 总时间差异。
边界 clear 的成本包含在 PASS-LOCAL 中；本轮的计时噪声不足以把该差异外推为
净性能收益。

## 6. P3：四个消费者与生命周期断点

| ID / 用例 | 查询 | Final hit/miss | Base 插入 | 修改／边界 | 观察结果 |
| --- | ---: | ---: | ---: | --- | --- |
| T03 CFF 非 exact | 2 | 1/1 | 1 | 0 | 两次真实查询，第二次 Final hit；不能折叠，两个 `load_klass` 保留 |
| T04 CHA 浅层 | 4 | 0/4 | 1 | 4 CFG invalidation | 4 个 invoke 均改写；Final 全删，Base 保留 |
| T04 CHA 深层 | 4 | 0/4 | 1 | 4 CFG invalidation | 查询数保持 4，深 CFG 增加重复分块；同样 4 个改写 |
| X02 TCE → CFF | 2 | 1/1 | 1 | 0 | 第二个消费者首次查询即为 Final hit |
| X04 CFF → TCE | 2 | 1/1 | 1 | 0 | 反方向同样首次查询命中，Base 只插入一次 |
| X05 Recover → CHA | 2 | 0/2 | 2 | boundary `existing_analysis=0` | Recover 后分析已销毁；CHA 新分析读取 `%field` 的 metadata 7，并改写成 `Optimized_target` |
| X06 CFF 修改 → TCE | 2 | 0/2 | 2 | boundary `existing_analysis=0` | CFF 修改后分析已销毁；TCE 冷启动，无旧缓存命中 |

X05 的 devirtualization 和 `"monomorphic-target"` 记为 metadata 带来的优化
能力，不记作旧 JavaType 缓存命中。X06 的 boundary `action=none` 也证明两个
模式在该处没有差异，因为生产合同在边界前已经销毁分析。

## 7. P4：pipeline、负对照与计时

### 7.1 X07

已运行：

```text
opt -disable-output --jeandle --jeandle-pea-iterations=0 \
  -jeandle-java-type-stats -jeandle-java-type-query-trace \
  -jeandle-vm-callback-log=.../pipeline-tce-cff.cblog \
  .../x07-production-pipeline.ll
```

查询轨迹为：

```text
1 miss / Base insert
2 Final hit
3 miss / Base insert
4 Final hit
5 Final hit
```

这证明关闭 PEA 的实际 `--jeandle` pipeline 中存在 Base 和 Final 消费；不证明
完整生产 pipeline 或 PEA 打开时的行为。

### 7.2 现有 CFF 与失效模式对照

- 现有 CFF `cache-reuse.ll`：6 查询，Final 3 hit/3 miss，Base 插入 1，
  2 次 selective invalidation，0 clear。
- 现有 `selective-invalidation.ll`：
  - selective 模式：3 查询，4 Base 插入，5 次 selective invalidation，
    0 Base invalidated，0 clear。
  - FULL 模式：3 查询，12 Base 插入，5 次 clear，12 Base invalidated。

该对照沿用现有 ORIGIN/FULL/选择性设施，只用于展示失效集合差异，不与新的
PASS-LOCAL／CROSS-PASS 混为同一归因。

### 7.3 5 轮 pilot

每组 1000 个函数，1 轮 warmup，5 轮正式测量；每轮按奇偶交替模式顺序。
计时边界包含进程启动和 IR 解析，关闭 query trace。原始逐轮数据在
`remote-results/timing/`。

| 输入 | 模式 | 中位数 | 最小值–最大值 |
| --- | --- | ---: | ---: |
| nochange-1000 | CROSS-PASS | 29,966,426 ns | 20,406,491–72,208,073 ns |
| nochange-1000 | PASS-LOCAL | 49,389,734 ns | 25,683,065–70,451,051 ns |
| folded-1000 | CROSS-PASS | 23,635,503 ns | 20,476,878–66,438,107 ns |
| folded-1000 | PASS-LOCAL | 26,022,835 ns | 21,458,963–50,338,106 ns |

区间重叠明显、单模式内波动远大于多数模式间差异。本文只记录原始结果，不把
中位数方向写成加速结论。

## 8. 测试与正确性结果

### 8.1 本轮测试

| 检查 | 命令 | 结果 |
| --- | --- | --- |
| 新增 lit | `build/.../bin/llvm-lit -sv llvm/test/Jeandle/java-type-cache-reuse` | rc 0；14/14 passed |
| JavaType 单测 | `build/.../unittests/IR/JavaTypeQueryTests --gtest_color=no` | rc 1；46/47 passed |
| Jeandle lit 全目录 | `build/.../bin/llvm-lit -sv llvm/test/Jeandle` | rc 1；765 passed，25 unsupported，17 failed |

单测失败是现有 `JavaTypeQueryTest.CachedEntryNormalizesFreeze`：期望 klass
`22`，实际 `0`。初始 `unit-tests-baseline.log` 中同样是该唯一失败。

完整日志和命令：

- `remote-results/new-lit-final-14.command`
- `remote-results/new-lit-final-14.log`
- `remote-results/unit-tests-final.command`
- `remote-results/unit-tests-final.log`
- `remote-results/jeandle-lit-final-807.command`
- `remote-results/jeandle-lit-final-807.log`

### 8.2 全目录失败的归因

初始基线只扫描 124 个测试：113 passed、1 unsupported、10 failed；10 个失败
全部是 TCE 用例。最终全目录扫描的 17 个失败包含这同样的 10 个 TCE 红项：

- `condition-value-domain.ll`
- `context-phi-select.ll`
- `deep-condition.ll`
- `freeze-and-identity-patterns.ll`
- `frozen-obj-check.ll`
- `null-arm-type.ll`
- `null-guard-forms.ll`
- `switch-and-frozen-guards.ll`
- `trunc-value-domain.ll`
- `xor-both-traced.ll`

另 7 个因扩大扫描范围暴露，日志显示为工具缺失，不在初始 124 项范围内：

- 缺 `llvm-extract`：
  `SafepointElimination/gc-leaf-deopt-not-coverage.ll`
- 缺 `split-file`：
  `SafepointElimination/strip-mine-exit-current-iv.ll`、
  `copy-specialization/invalid-copy.ll`
- 缺 `llc`：
  `copy-specialization/clone-expansion.ll` 和 3 个 `X86/*` 用例

因此可以说“14 个新增 lit 全过，未观察到新增失败”，不能仅凭这次 807 扫描
声称整个仓库零回归。

### 8.3 独立缓存校验

对 17 个关键诊断另跑
`-jeandle-verify-java-type-cache`，全部 rc 0，未出现 verification failure。
除 X07 外，统计块均给出 `verification skips: 0`：

- 2 查询用例：verifications 2
- 4 查询用例：verifications 4
- 现有 CFF 复用用例：verifications 6，skips 0

X07 的 `--jeandle` 内部 pipeline 没有暴露 function statistics printer，因此
该次 verify 只能确认 rc 0、无失败标记，不能从日志取得 verifications 数值。

校验日志：

- `remote-results/verification/*.command`
- `remote-results/verification/*.log`
- `remote-results/verification/*.rc`

该校验使用未缓存参考引擎与冷缓存诊断，不等价于完整 JVM 应用级语义验证。

## 9. 失败、偏差与未覆盖项

1. 完整生产 pipeline（PEA 打开）未跑通。尝试 `--jeandle` 时 callback log
   缺少 `RequiresStrictLockOrder()`；另一次使用
   `pre-pea-high-tier-e2e.cblog` 的尝试在 TCE 缺少 `IsObjectKlass(9)`。
   原始失败在 `remote-results/x07-probe.log` 和
   `remote-results/x07-jeandle-pea-off-probe.log`。
2. X07 最终交付只覆盖 `--jeandle --jeandle-pea-iterations=0`。
3. LVI oracle 调用次数没有单独计数；现有统计记录 invalidation visited、
   uses/slots scanned 和 LVI clear 次数，不能代替 oracle call count。
4. 诊断没有单独记录 pass invocation ID 和缓存条目代次；查询 ordinal 与
   boundary 位置可用于定位，但不能替代完整的生命周期标签。
5. P4 已完成零重叠、深 CFG 和现有深 CFG 设施，但未完成“便宜叶子 vs 中等
   共享 DAG”的配对计时负对照。
6. pilot 计时噪声大，不能形成稳定性能结论；未做跨 session 复测。
7. 未做 JVM 应用回放或应用性能测量。
8. 任务 8（CFF／RecoverTypeInfo preserve JavaTypeAnalysis 的生产实现）未做。
9. 本轮源码、测试和 hook 均未 commit、未 push。

## 10. 复现命令

构建：

```sh
cd /home/annya/playground/jeandle/jeandle/jeandle-llvm/build/build-ninja-profiling
ninja opt JavaTypeQueryTests
```

测试：

```sh
cd /home/annya/playground/jeandle/jeandle/jeandle-llvm
build/build-ninja-profiling/bin/llvm-lit -sv llvm/test/Jeandle/java-type-cache-reuse
build/build-ninja-profiling/unittests/IR/JavaTypeQueryTests --gtest_color=no
build/build-ninja-profiling/bin/llvm-lit -sv llvm/test/Jeandle
```

诊断、校验和计时：

```sh
OUT=/home/annya/playground/jeandle/perf-results/2026-10-26-javatype-cache-reuse
bash "$OUT/scripts/run_diagnostics.sh"
bash "$OUT/scripts/run_verification.sh"

python3 "$OUT/scripts/run_ablation_timing.py" \
  --opt build/build-ninja-profiling/bin/opt \
  --callback-log llvm/test/Jeandle/java-type-cache-reuse/Inputs/tce-recover.cblog \
  --input "$OUT/bench-nochange.ll" \
  --output-dir "$OUT/timing" --label nochange-1000 --rounds 5

python3 "$OUT/scripts/run_ablation_timing.py" \
  --opt build/build-ninja-profiling/bin/opt \
  --callback-log llvm/test/Jeandle/java-type-cache-reuse/Inputs/tce-recover.cblog \
  --input "$OUT/bench-folded.ll" \
  --output-dir "$OUT/timing" --label folded-1000 --rounds 5
```

每个诊断的精确 argv 已由脚本写入对应的 `diagnostics/*.command` 和
`verification/*.command`；每轮计时命令保存在对应 CSV 的 `command` 列。

## 11. 交付物索引

本地源码与测试快照：

- `artifacts/java-type-cache-reuse-2026-10-26/remote-src/`
- `artifacts/java-type-cache-reuse-2026-10-26/remote-tests/java-type-cache-reuse/`

本地原始结果：

- `artifacts/java-type-cache-reuse-2026-10-26/remote-results/identity/`
- `artifacts/java-type-cache-reuse-2026-10-26/remote-results/diagnostics/`
- `artifacts/java-type-cache-reuse-2026-10-26/remote-results/verification/`
- `artifacts/java-type-cache-reuse-2026-10-26/remote-results/timing/`
- `artifacts/java-type-cache-reuse-2026-10-26/remote-results/*.log`

本地机器可读汇总：

- `artifacts/java-type-cache-reuse-2026-10-26/summary/cases.csv`
- `artifacts/java-type-cache-reuse-2026-10-26/summary/query-trace.csv`
- `artifacts/java-type-cache-reuse-2026-10-26/summary/results.json`
- `artifacts/java-type-cache-reuse-2026-10-26/scripts/summarize_results.py`

远端原始目录：

`/home/annya/playground/jeandle/perf-results/2026-10-26-javatype-cache-reuse/`
