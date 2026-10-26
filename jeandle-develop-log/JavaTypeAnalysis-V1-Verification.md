# JavaTypeAnalysis V1 检验方案

> 本文档是 V1 实现的**验收与检验手册**，回答"代码写完了，怎么证明它是对的、可观测的、有收益的"。
> 所有命令均已在 `build/build-make-release`（release 构建）上实测可用。

## 0. 当前状态快照（截至 V1 提交 8019ed63c）

已实现（完整 V1，非仅阶段 1/2）：

- `llvm/include/llvm/Analysis/Jeandle/JavaTypeAnalysis.h`：QueryKey、Statistics、两个 Printer Pass、disable/verify 开关；
- `llvm/lib/Analysis/Jeandle/JavaTypeAnalysis.cpp`：带缓存的 `getJavaType`、`clear`、`invalidate`、影子校验、统计；
- 注册：`PassRegistry.def`（`java-type-analysis` 分析、`print<java-type-analysis>` 函数 Printer、`print<java-type-analysis-summary>` 模块 Printer）、`PassBuilder.cpp`、`Analysis/CMakeLists.txt`；
- 消费者迁移：`TypeCheckElimination.cpp:50`、`CHADevirtualization.cpp:180` 已改用 `FAM.getResult<JavaTypeAnalysis>`，并在修改 IR 后调用 `clear()`。

**尚未完成（本文档要补的）**：

1. `llvm/test/Jeandle/java-type-analysis/` 测试目录**不存在**（这是最大的缺口，V1-Summary 第 7 节与 Technical-Implementation 第 10 节都预告了它）；
2. 阶段 0 的**无缓存基线**尚未建立（Technical-Implementation 第 6 节阶段 0）；
3. `JavaTypeAnalysis-V1-Summary.md` 第 12 节仍写"只完成阶段 1 和阶段 2"，已过期，需要更新。

## 1. 检验的三个层面

| 层面 | 回答的问题 | 手段 |
|---|---|---|
| 正确性 | 缓存是否改变了 `getJavaType` 的语义？ | disable A/B diff、影子校验、lit 回归测试 |
| 可观测性 | 缓存是否真的在 hit/miss/clear？ | 两个 Printer Pass、统计计数 |
| 性能 | 缓存是否带来净收益？ | 阶段 0 基线 + hit/miss + 耗时对比 |

## 2. 正确性检验（已实测）

### 2.1 现有 lit 回归测试（必须全绿）

```bash
# 从源码目录跑（lit 从源码发现测试，build 目录只存输出）
build/build-make-release/bin/llvm-lit -sv llvm/test/Jeandle/
```

预期：73 个测试发现，69 通过、4 个 Unsupported（AArch64/RISCV 在 x86 主机上不支持）。

这两个消费者相关的既有用例是语义基线：

- `type-check-elimination/instanceof-known-subtype.ll`
- `cha-devirtualization/intersect-exact.ll`
- `java-type-metadata-recovery/recover-mutual-phi-cycle.ll`

### 2.2 缓存禁用 A/B（核心正确性检查）

`-jeandle-disable-java-type-cache` 让新接口**绕过缓存**直接走旧算法。同一输入下，缓存开/关的输出必须**逐字节一致**：

```bash
diff \
  <(build/build-make-release/bin/opt -S -passes="cha-devirtualization" \
      -jeandle-vm-callback-log=llvm/test/Jeandle/cha-devirtualization/Inputs/intersect-exact.cblog \
      llvm/test/Jeandle/cha-devirtualization/intersect-exact.ll 2>/dev/null) \
  <(build/build-make-release/bin/opt -S -passes="cha-devirtualization" -jeandle-disable-java-type-cache \
      -jeandle-vm-callback-log=llvm/test/Jeandle/cha-devirtualization/Inputs/intersect-exact.cblog \
      llvm/test/Jeandle/cha-devirtualization/intersect-exact.ll 2>/dev/null)
```

已实测：输出一致。对 `type-check-elimination` 的同名用例同样做一遍。

### 2.3 影子校验（hit 时的逐字段比对）

`-jeandle-verify-java-type-cache` 在**每次 hit** 时用旧算法重算，逐字段比较 `Klass`、`Exact`、`ExcludedKlasses`，不一致立即 `reportFatalInternalError`：

```bash
build/build-make-release/bin/opt -S -passes="cha-devirtualization" \
  -jeandle-verify-java-type-cache \
  -jeandle-vm-callback-log=llvm/test/Jeandle/cha-devirtualization/Inputs/intersect-exact.cblog \
  llvm/test/Jeandle/cha-devirtualization/intersect-exact.ll >/dev/null 2>&1 \
  && echo "verify OK" || echo "verify FAILED"
```

> ⚠️ 重要局限：影子校验只在 **hit** 时生效。当前两个消费者在单 pass 内对每个调用点只查一次、且每次折叠后都 `clear()`，典型场景是 **0 hit**。因此该开关在现有用例上实际不触发任何比对。要让它真正起作用，必须先写能产生 hit 的测试（见 4.3）。

## 3. 可观测性检验（已实测）

### 3.1 进程级统计（模块 Printer）

`print<java-type-analysis-summary>` 是模块级 pass，打印**进程级**累计计数（不依赖 `-stats`，release 构建可用）：

```bash
build/build-make-release/bin/opt -S \
  -passes="module(function(cha-devirtualization),print<java-type-analysis-summary>)" \
  -jeandle-vm-callback-log=llvm/test/Jeandle/cha-devirtualization/Inputs/intersect-exact.cblog \
  llvm/test/Jeandle/cha-devirtualization/intersect-exact.ll 2>&1 >/dev/null | head -15
```

已实测输出（该用例）：

```text
JavaTypeAnalysis process summary after module: ...
  queries: 1
  hits: 0
  misses: 1
  hit rate: 0.00%
  insertions: 1
  clears: 1
  bypasses: 0
  peak entries in one result: 1
  hit time (ns): 0
  miss computation time (ns): 2883
  total query time (ns): 6049
```

注意 `queries:1, hits:0, clears:1`——**这是 V1 的正常形态**：每个调用点只查一次、折叠后立即 clear、且消费者不 preserve 分析，所以没有复用。这正说明 V1 是"正确性 + 测量平台"，还不是性能收益来源。

### 3.2 语法坑：模块 Printer 必须用 module() 嵌套

直接写 `-passes="cha-devirtualization,print<java-type-analysis-summary>"` 会报错：

```text
opt: unknown function pass 'print<java-type-analysis-summary>'
```

因为 `cha-devirtualization` 是函数级 pass，解析器把后续 pass 也当函数级。正确写法是显式嵌套：

```text
module(function(cha-devirtualization),print<java-type-analysis-summary>)
```

### 3.3 函数 Printer 的局限

`print<java-type-analysis>` 是函数级 pass，只打印**当前分析结果生命周期内**的计数。由于 CHA/TCE 改完 IR 后不 preserve `JavaTypeAnalysis`，FAM 会在 pass 边界销毁结果，随后 Printer 拿到的就是一个全新的空结果：

```bash
build/build-make-release/bin/opt -S \
  -passes="cha-devirtualization,print<java-type-analysis>" \
  -jeandle-vm-callback-log=llvm/test/Jeandle/cha-devirtualization/Inputs/intersect-exact.cblog \
  llvm/test/Jeandle/cha-devirtualization/intersect-exact.ll 2>&1 >/dev/null | grep -A 11 "JavaTypeAnalysis"
```

已实测：显示 `queries: 0`。**结论：要观察统计，用模块 Printer（3.1），不要用函数 Printer。**

### 3.4 `-stats` 不可用（release 构建）

```bash
build/build-make-release/bin/opt ... -stats
# 输出：Statistics are disabled.  Build with asserts or with -DLLVM_FORCE_ENABLE_STATS
```

`build/build-make-release` 的 `LLVM_ENABLE_ASSERTIONS=OFF`、`LLVM_FORCE_ENABLE_STATS=OFF`。需要统计计数时：
- 用两个 Printer Pass（推荐，release 可用）；
- 或用 `build-make-debug`（若已构建），或重配 `-DLLVM_FORCE_ENABLE_STATS=ON`。

## 4. 需要补写的 lit 测试（`llvm/test/Jeandle/java-type-analysis/`）

这是当前最大的缺口。按优先级排列，每个测试都是 `.ll` + 可选的 `Inputs/*.cblog`，用 `opt` + `FileCheck` 验证。可参考 `cha-devirtualization/intersect-exact.ll` 的写法。

### 4.1 正确性类（P0，必须）

1. **相同查询命中**：同一对象同一块内两次查询，第二次命中，结果一致；
2. **unknown 结果也被缓存**：分析失败/未知的结果不重复计算；
3. **只有 ExcludedKlasses 的结果也被缓存**；
4. **不同 Context 不串值**：同一 Value 在不同块（真分支/假分支）得到不同结果，互不污染；
5. **cast/alias 规范化**：`bitcast` 包装后的 Value 与源 Value 命中同一 key；
6. **clear 后重新 miss**：`clear()` 后再查同一 key 变 miss 且结果正确；
7. **DT 失效**：CFG 变化后结果不返回旧值；
8. **TCE 在 pass 内修改 IR 后立即 clear**；
9. **CHA 修改 CFG、`DTU.flush()` 后立即 clear**。

### 4.2 开关类（P0）

10. **cache on/off 输出一致**：同一输入加/不加 `-jeandle-disable-java-type-cache`，`FileCheck` 结果相同；
11. **verify 模式下 mismatch 为 0**：构造有 hit 的输入，加 `-jeandle-verify-java-type-cache` 不触发 fatal。

### 4.3 观测类（P1，用于证明"真的在缓存"）

12. **hit/miss/clear 计数**：用模块 Printer 的 `CHECK` 断言 `queries`、`hits`、`misses`、`clears` 的具体值；
13. **构造一次命中**：两个 `check_instanceof` 测同一对象、且第一个**不触发折叠**（不 clear），第二个同块查询应命中。这是让影子校验（2.3）真正起作用的唯一途径。

### 4.4 说明

- 测试放源码 `llvm/test/Jeandle/java-type-analysis/` 下，lit 运行时从源码发现，**无需重跑 cmake**；
- 涉及 VM 回调的用例需要 `.cblog` 文件（见 `VMCallbackLog` 的 record/replay 机制），回调日志必须与测试 IR 严格对应。

## 5. 验收标准（对应 V1-Summary 第 10 节）

正确性硬门槛：

- [ ] `llvm-lit -sv llvm/test/Jeandle/` 全绿（69 通过 + 4 不支持）；
- [ ] 所有用例 cache on/off 输出一致；
- [ ] verify 模式（在有 hit 的测试上）mismatch 为 0；
- [ ] 无 crash、无 use-after-free、无错误 preserve；
- [ ] IR 修改后不返回旧结果（clear/失效纪律正确）。

可观测性门槛：

- [ ] 模块 Printer 能稳定输出 hit/miss/clear；
- [ ] 定向测试能稳定产生并验证 hit、miss、clear；
- [ ] 输出真实 workload 的 hit rate、条目峰值、callback 减少量、查询耗时、两个 Pass 耗时。

性能门槛（依赖阶段 0 基线）：

- [ ] JavaType 查询自身耗时稳定下降；
- [ ] TCE/CHA 无统计显著回退；
- [ ] 端到端优化时间至少无显著回退。

## 6. 已知待办（写给下一阶段）

1. 建立阶段 0 无缓存基线（查询次数、callback 次数、Pass 耗时）；
2. 用真实数据回答"V1 完整缓存是否带来净收益"——当前 0 hit，收益极可能来自后续的 Base cache / JVM relation cache（见 `JavaTypeAnalysis-Final-Direction.md` 阶段 2）；
3. 更新 `JavaTypeAnalysis-V1-Summary.md` 第 12 节（已实现完整 V1，非仅阶段 1/2）。
