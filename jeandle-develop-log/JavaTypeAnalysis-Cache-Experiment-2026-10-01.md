# JavaType 缓存分析试验报告

本报告记录 JavaType 缓存分析在当前工作区上的正确性回归、原始引擎对照，以及 FAM 和缓存实际接入验证。2026 年 10 月 1 日完整复跑后，17 个新增单元测试、91 个此前已有的 IR 测试，以及 TCE 和 CHA 的三模式共 87 条 RUN 命令全部通过。样例验证证明默认查询经过 FAM 提供的 JavaTypeAnalysisResult，进入 getCachedJavaType 并发生路径事实缓存命中。

结论只适用于本次记录的源码、配置和测试范围，不表示所有输入均正确，也不构成性能收益或真实 JVM 端到端验证。

## 环境与源码状态

| 项目 | 本次配置 |
|---|---|
| 实验时间 | 2026-10-01 10:30，Asia/Shanghai |
| 源码目录 | `/home/zjj/jeandle/jeandle-llvm` |
| HEAD | `1e61901b4a01aff42f0566afab6aa0f9cb5de3cc` |
| 提交说明 | `feat: isolate cached Java type analysis from the original query engine` |
| 构建目录 | `build/build-ninja-release` |
| LLVM | 22.0.0git |
| 平台 | WSL2 Linux x86_64 |
| 构建 | Ninja、Release、X86、LLVM_INCLUDE_TESTS=ON |
| 断言 | LLVM_ENABLE_ASSERTIONS=OFF |
| 本次构建和 lit 并发 | 2 |

实验对象是 HEAD 加未提交的工作区修改，不是纯 HEAD。修改涉及 `CachedJavaType.h`、`CachedJavaType.cpp` 和 `JavaTypeAnalysis.cpp`。完整的已跟踪文件差异保存在 `worktree.patch`，关键文件 SHA256 保存在 `manifest.json`。复跑前后已核对 HEAD、已跟踪差异和关键文件摘要未变化。

本次原始证据目录：

`/home/zjj/jeandle/jeandle-llvm/build/build-ninja-release/javatype-experiments/run-20261001-103023-m0eIBQ`

此前探索中曾出现缓存文件引用原文件内部 `MaxFactsJoinBlocks` 导致编译失败；当时用旧二进制运行的结果仅用于确认测试用法。本次该问题已不存在，脚本先成功执行增量构建，再运行测试。本报告的结果以本次完整复跑为准。

## 测试来源与覆盖范围

通过以下 Git 操作确认来源：

```bash
git log --follow -- llvm/unittests/IR/JavaTypeQueryTest.cpp
git ls-tree -r --name-only 1e61901b4^ llvm/test/Jeandle
git diff --name-status 1e61901b4^ -- \
  llvm/test/Jeandle/type-check-elimination \
  llvm/test/Jeandle/cha-devirtualization \
  llvm/test/Jeandle/java-type-metadata-recovery \
  llvm/test/Jeandle/constant-field-folding \
  llvm/test/Jeandle/arraycopy-specialization
```

`JavaTypeQueryTest.cpp` 是缓存提交新增的 548 行文件，包含 17 个单元测试，目标为 `JavaTypeQueryTests`。下表中的 91 个 IR 测试此前已经存在，所选目录相对缓存提交的父提交没有差异。

| 既有目录，位于 llvm/test/Jeandle 下 | 测试文件数 | 检查内容 |
|---|---:|---|
| type-check-elimination | 24 | 类型检查消除与保留、PHI、路径汇合、null edge、预算 |
| cha-devirtualization | 4 | 类型信息驱动的去虚化 |
| java-type-metadata-recovery | 26 | 类型恢复、incoming 边约束、循环、OSR |
| constant-field-folding | 36 | 字段和元数据折叠及相关类型推导 |
| arraycopy-specialization | 1 | OSR 数组类型恢复与 arraycopy 优化 |
| 合计 | 91 | 相关回归集，不是全部 Jeandle 测试 |

TCE 和 CHA 已直接迁移至 JavaTypeAnalysisResult。RecoverTypeInfo、ConstantFieldFolding 和 ArrayCopySpecialization 的直接查询仍使用原始接口。因此不能把所有 91 个用例都视为直接测试缓存引擎；其余目录用于检查相关公共逻辑和组合流程是否退化。

单元测试覆盖共享基础类型、freeze 规范化、共享路径事实、Unknown 缓存、按上下文块区分结果、修改条件和属性后的清理、PHI incoming 缓存命中后继续应用边约束、预算截断不发布结果、PHI 环中间结果不发布、冷热精度变化、关闭缓存及跨预算冷查询对照。测试使用模拟 VM callbacks，无需启动 JVM。

## 试验步骤

### 编译当前源码

在源码根目录执行：

```bash
cmake --build build/build-ninja-release \
  --target opt FileCheck JavaTypeQueryTests -j 2
```

脚本以 `set -euo pipefail` 执行，构建失败即停止，不会继续使用旧二进制报告成功。本次增量编译并重新链接了 JavaTypeQueryTests，其他目标已为最新。

### 运行缓存单元测试

```bash
build/build-ninja-release/unittests/IR/JavaTypeQueryTests \
  --gtest_filter='JavaTypeQueryTest.*'
```

结果为 17/17 通过。需要单独审核 PHI 发布规则时可使用：

```bash
build/build-ninja-release/unittests/IR/JavaTypeQueryTests \
  --gtest_filter='JavaTypeQueryTest.PhiCycleIntermediateIsNotPublished'
```

### 运行此前已有的 IR 回归测试

```bash
build/build-ninja-release/bin/llvm-lit -sv -j 2 \
  llvm/test/Jeandle/type-check-elimination \
  llvm/test/Jeandle/cha-devirtualization \
  llvm/test/Jeandle/java-type-metadata-recovery \
  llvm/test/Jeandle/constant-field-folding \
  llvm/test/Jeandle/arraycopy-specialization
```

结果为 91/91 通过，无失败或跳过。lit 耗时约 0.35 秒，仅表示测试工具报告的运行时长，不用于推断缓存加速。

### 对 TCE 和 CHA 执行三模式验证

脚本读取两个目录中现有的 RUN 行，保留其中的 pipeline、回调日志及 FileCheck 断言，分别向 opt 加入以下选项：

| 模式 | opt 参数 | 执行路径 |
|---|---|---|
| default | 无额外缓存参数 | Result 调用缓存引擎 |
| original | `-jeandle-disable-java-type-cache` | Result 绕过缓存，调用原始引擎 |
| verify | `-jeandle-verify-java-type-cache` | 缓存结果与原始结果对照，并执行冷缓存诊断 |

两个目录共 28 个测试文件、29 条 RUN 命令，其中一个文件有两条 RUN。每种模式 29 条全部通过，共 87 条成功执行。它们是同一批用例的重复执行，不能与 91 个测试简单相加当作独立用例数。

三模式验证的主要检查是各模式都满足原有 FileCheck 断言；没有对全部 29 条命令的输出做逐字节比较。

脚本中的 RUN 适配器只支持当前这些用例的单行 `opt ... | FileCheck ...` 形式；遇到新增的续行或其他 lit 替换会明确报错，需扩展适配器或使用标准 lit 配置，不会静默跳过。

### 核实 FAM 与缓存路径

源码调用链为：

```text
TypeCheckElimination / CHADevirtualization
  → FAM.getResult<jeandle::JavaTypeAnalysis>(F)
  → JavaTypeAnalysisResult::getJavaType(V, Context)
  → getCachedJavaType(V, &DT, Context, IsNullEdge, Cache, Info)
```

缓存开关 `jeandle-disable-java-type-cache` 默认 false。Result 使用 FAM 管理的 DominatorTree 和 LazyValueInfo。关闭缓存仍经过 FAM 和 Result，只切换其内部查询引擎。

选取 `merge-direct-use.ll`，使用模块级累计统计 Printer，避免 Pass 修改 IR 后 Result 被 FAM 失效重建而丢失原 Result 的计数：

```bash
build/build-ninja-release/bin/opt -S \
  -passes='function(type-check-elimination),print<java-type-analysis-summary>' \
  -jeandle-vm-callback-log=llvm/test/Jeandle/type-check-elimination/Inputs/merge-direct-use.cblog \
  llvm/test/Jeandle/type-check-elimination/merge-direct-use.ll \
  > /tmp/merge-direct-use.actual.ll 2> /tmp/merge-direct-use.stats.log
```

分别不加参数、增加 disable 参数、增加 verify 参数运行。三个模式使用独立 opt 进程，累计统计互不混入。

| 计数 | default | original | verify |
|---|---:|---:|---:|
| queries | 3 | 3 | 3 |
| path facts hits | 2 | 0 | 2 |
| path facts misses | 3 | 0 | 3 |
| final type hits | 0 | 0 | 0 |
| final type misses | 3 | 0 | 3 |
| base insertions | 1 | 0 | 1 |
| clears | 1 | 1 | 1 |
| bypasses | 0 | 3 | 0 |
| verifications | 0 | 0 | 3 |
| verification skips | 0 | 0 | 0 |

默认模式确实出现 2 次共享路径事实命中，而不是仅创建了 FAM Result。关闭缓存后 3 次查询全部 bypass。verify 模式 3 次验证均未跳过，且没有差异报错。本样例没有最终类型缓存命中，不能用它单独证明 FinalTypes 命中分支；该分支另由单元测试覆盖。

### 检查输出 IR 的正确性

该用例的两个分支都在通过同一类型检查后进入汇合块，因此汇合块的重复检查应折叠为 `ret i1 true`；前面两个分支的检查必须保留。FileCheck 同时检查这些预期。

脚本对三个模式的输出分别执行 FileCheck，并比较输出字符串。结果：三份 IR 都符合断言，且逐字节一致。原始输出保存在 `output-default.ll`、`output-original.ll`、`output-verify.ll`。

`CHECK` 要求出现指定内容，`CHECK-NEXT` 限定下一行，`CHECK-NOT` 限定检查区间内不得出现某内容，`CHECK-LABEL` 划分检查区域。PASS 表示这些断言成立，并非仅表示 opt 未崩溃。

## 结果总结与限制

| 检验项 | 本次结果 |
|---|---|
| 构建当前工作区 | 成功 |
| 新增缓存单元测试 | 17/17 通过 |
| 此前已有 IR 回归测试 | 91/91 通过 |
| TCE 和 CHA 默认模式 | 29/29 RUN 通过 |
| TCE 和 CHA 原始模式 | 29/29 RUN 通过 |
| TCE 和 CHA 校验模式 | 29/29 RUN 通过 |
| FAM 和共享缓存接入 | 源码链路及运行计数相互印证 |
| 样例新旧输出比较 | 三模式 FileCheck 通过，输出逐字节相同 |

当前结果支持继续开发或进行后续合并工作，但仍有以下边界：

- 预算截断或 PHI 环场景会跳过严格相等校验；三模式成功不表示每次查询均做了比较。需要结合明确期望结果的单元测试判断这些场景。
- 缓存命中可能节省预算或提高 PHI 环中的精度，不能把样例的字节一致结论扩大成所有输入必须字节一致。
- 本次是 Release 且断言关闭，没有运行 Debug、ASan 或 UBSan 配置。
- 没有执行真实 JDK/JVM、jtreg、全部 Jeandle 或全部 LLVM 测试，没有测量端到端性能。
- 跨预算直接对照的单元测试目前主要使用一个冷查询 fixture；热缓存查询顺序、复杂接口组合以及更多失效场景仍可扩充。

目录内旧版 `JavaTypeAnalysis-V1-Verification.md` 针对旧实现，涉及旧测试数量、旧统计字段及仅在 hit 时校验的描述，不适用于本报告的实现。本文不修改旧文档，仅明确本次版本与结果。

## 一键复现与证据保存

交付脚本：

`/home/zjj/jeandle/build_shells/test-javatype-cache.sh`

从任意目录执行：

```bash
/home/zjj/jeandle/build_shells/test-javatype-cache.sh
```

可覆盖源码、已配置构建目录、并发和新的结果目录：

```bash
LLVM_SRC=/home/zjj/jeandle/jeandle-llvm \
LLVM_BUILD=/home/zjj/jeandle/jeandle-llvm/build/build-ninja-release \
JOBS=2 \
RESULT_DIR=/tmp/javatype-cache-new-run \
/home/zjj/jeandle/build_shells/test-javatype-cache.sh
```

RESULT_DIR 必须尚不存在，防止覆盖旧证据。不指定时，每次在构建目录 `javatype-experiments/` 下创建唯一子目录。默认沿用已经配置的 LLVM 构建，不自动安装依赖、重置源码或安装 LLVM，不调用现有 `test.sh` 的 JDK 测试。

| 证据文件 | 内容 |
|---|---|
| manifest.json | 时间、平台、HEAD、源码和构建位置、关键源码 SHA256 |
| worktree.patch、git-status.txt | 相对 HEAD 的已跟踪修改及状态 |
| CMakeCache.txt、opt-version.txt | 构建配置及工具版本 |
| reproduce.sh | 本次实际执行的脚本副本 |
| build.log | 构建成功或失败记录 |
| unit.log、unit.xml | 单元测试输出 |
| lit.log、lit.json | 91 个回归测试结果 |
| matrix.log、matrix.json、matrix/ | 三模式 RUN 命令、退出码及逐条日志 |
| stats.json、stats-*.log、stats-*.command | FAM 缓存证据、原始统计及命令 |
| output-*.ll | 样例三模式的输出 IR |
| SUCCESS.txt | 全部步骤和断言成功后才生成 |

脚本复现的是实验流程；要复现本次精确源码，应在独立干净 checkout 中检出 manifest 的 HEAD，再检查并应用 worktree.patch，根据保存的 CMake 配置重新配置构建目录，然后通过 LLVM_SRC 和 LLVM_BUILD 指向该副本运行。不要把 patch 重复应用到已经含有这些改动的当前工作区，也不要直接复用其他绝对路径下的 CMakeCache。此次没有未跟踪源码；脚本一般只列出未跟踪文件，不自动归档其内容。

统计断言固定于当前样例，例如默认路径命中 2 次。后续改变实现或 fixture 后若计数变化，脚本会失败，需审核差异后更新期望，不能把所有计数变化都直接判定为语义错误。
