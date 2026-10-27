# JavaType 跨 pass 缓存：生产流水线、jtreg 与 profiling 测试方案

日期：2026-10-26。状态：待执行。本文只完成源码核对与实验设计，没有运行新的性能实验。

## 1. 要回答的问题

上一轮已经证明条目能被正常消费。本轮需要区分三个问题：

1. **整体改动是否值得**：当前缓存实现相对于原始 getJavaType 查询方式，是否降低真实优化／编译成本？
2. **跨 pass 共享贡献多少**：在 pass 内缓存行为相同的条件下，允许跨 pass 保留是否进一步降低成本？
3. **为什么变快或没有变快**：减少的重算能否在调用栈、instructions/cycles 和优化器时间中互相印证？

主要优化目标是编译器成本。即使生成代码的运行速度不变，LLVM Optimize 和总编译 CPU 时间下降也构成收益。不能要求 Java 方法执行次数增加时 getJavaType 查询数同比增加：这些查询发生在编译期间。

本轮以完整生产 pipeline 为主线，短流水线用于解释。不得为了得到好结果删掉标准 LLVM passes、关闭内联／PEA，或改动失效合同。PEA-off 等配置可以作为明确标记的消融组。

## 2. 当前证据和源码身份

### 2.1 上一轮的边界

见 [缓存复用测试执行记录](JavaType-Cache-Reuse-Test-Execution-2026-10-26.md)：

- 已有四个消费者的真实查询、X01 跨 pass Final 命中、X03 跨修改 Base 存活的证据。
- X07 只完成 `--jeandle --jeandle-pea-iterations=0`，没有覆盖默认 PEA 配置。
- 5 轮 pilot 约 20–72 ms，包含进程启动与 IR 解析，波动不足以支持性能结论。
- 完整 PEA 回放曾缺 `RequiresStrictLockOrder()`、`IsObjectKlass(9)` 等 callback 键。
- 缺少 pass invocation ID、条目代次及独立 LVI oracle 调用计数。
- CFF／RecoverTypeInfo 修改后 preserve 的生产实现没有执行。
- 既有 JavaType 单测有 1 个基线失败，Jeandle lit 有既有失败和工具缺失；新性能输入必须独立通过语义校验，不把既有失败误写为新增回归或全部通过。

### 2.2 本次只读核对

远端：`annya@100.122.220.40`。

| 项目 | 观察到的状态 |
| --- | --- |
| LLVM 仓库 | `/home/annya/playground/jeandle/jeandle/jeandle-llvm` |
| LLVM HEAD | `b121fa56710a0265d66ae5fa5c0b1cc0aa10ced6`，分支 `test/javatype-cache-design`，工作区干净 |
| JDK 仓库 | `/home/annya/playground/jeandle/jeandle/jeandle-jdk` |
| JDK HEAD | `1d56df159ebb4edbaa4613941dc952ffe0be8c64`，`main` 比 origin/main 超前 1 提交，工作区干净 |

执行时重新保存 HEAD、工作区 diff、未跟踪输入、编译配置和实际运行二进制／DSO 哈希。不能用源码 HEAD 代替正在运行的 opt 或 JVM 身份；重编 LLVM 也不自动证明 JVM 使用了同版本实现。

已核对的关键位置：

- `llvm/lib/Jeandle/Pipeline.cpp:144`：生产 pipeline；`:156` 起前段；`:298` 起后段；`:346` 附近完整 O-level 优化及 GC 降低。
- `llvm/lib/Transforms/Jeandle/JeandleInlineDriver.cpp:130`：内联轮次后的 root cleanup。
- `llvm/lib/Transforms/Jeandle/RepeatedConstantFolding.cpp:27`：直接调用 CFF，再执行 SCCP／SimplifyCFG，按结果通知 FAM。
- `llvm/tools/opt/optdriver.cpp:303`：`-jeandle-inline-callee-ir`；`:800` 附近 `--jeandle` 默认选择 O3。
- `llvm/lib/Analysis/Jeandle/JavaTypeAnalysisStats.cpp:287` 附近：已有手工边界清理 pass，仅清已有 JavaType 缓存。
- `src/hotspot/share/jeandle/jeandleCompiler.cpp:196`：VM 参数转发和 `JeandleLLVMOptions`。
- `src/hotspot/share/jeandle/jeandleCompilation.cpp:1350`：真实 Java 编译、IR／callback 录制与阶段计时；`:1478` 附近输出统计。
- `src/hotspot/share/jeandle/jeandle_globals.hpp:79`、`PartialEscapeIterative.cpp:57` 附近：当前默认 PEA 开启、轮次上限 2。Pipeline.cpp 中“PEA-off 为默认”的注释与实际选项不一致，应以实际配置和执行轨迹为准。

## 3. 对照模式：分开整体收益与跨 pass 收益

| 模式 | 定义 | 作用 |
| --- | --- | --- |
| ORIGINAL | 当前二进制使用 `-jeandle-disable-java-type-cache`，走原始查询引擎 | 相同 pipeline 下，比较整体缓存方案与原始查询路径 |
| PASS-LOCAL | 新查询引擎、现有选择性失效；每次真实消费者 pass 调用开始时清已有 JavaType 缓存，保留 pass 内复用 | 隔离跨 pass 保留贡献 |
| CROSS-PASS | 当前正常实现，按真实 preserve／invalidate 合同跨 pass 共享 | 候选方案 |
| FULL（辅助） | 新查询引擎，每次修改通知全清 | 仅对代表样本区分选择性失效贡献 |
| HISTORICAL（补充） | 明确的缓存改动前 commit／构建 | 验证实际历史版本到当前版本的变化，单独说明其他差异 |

主要报告 ORIGINAL → CROSS-PASS 和 PASS-LOCAL → CROSS-PASS。两种百分比不能相加。

ORIGINAL 不是完整历史二进制：当前 pass 接入、通知开销和查询调度可能仍在。正式声称“整个改动相对以前提升多少”时，应确认原始引擎与目标历史版本的关系；如需精确历史比较，增加 HISTORICAL，但不要把期间所有变更都归因于缓存。

所有主对照保持相同优化级别、内联／PEA／GC 配置、查询预算、VM callback 结果、输入模块和语义输出要求。若缓存改变精度或优化决策，另列“优化质量变化”组，不能继续当作完全同工作量的纯缓存加速。

### 3.1 将 pass-local 消融接入实际 pipeline

上一轮的显式 `jeandle-java-type-cache-boundary` 适合短序列，但不能假设它覆盖 `--jeandle` 内部所有位置。

本轮建议新增一个测试专用开关（名称待实现，例如 `-jeandle-java-type-pass-local`），在四个真实消费者的每次 run 入口调用统一 helper：

- PASS-LOCAL：用 `FAM.getCachedResult` 查已有 JTA，有则清条目；不得为清理而创建分析。
- CROSS-PASS／ORIGINAL：执行同一轻量 hook 的对应分支；不改变 IR、DT/LVI 生命周期或 PA。
- CFF 内部多轮仍属一次 pass invocation，不在每次查询或内部轮次清理。
- `RepeatedConstantFolding` 直接调用的每次 CFF.run、内联清理里的消费者也必须覆盖。
- 其他不查询 JTA 的 pass 不必插清理；但需要诊断它们是否销毁分析。缓存生命周期以实际 FAM 行为为准。

若改用 PassInstrumentation，先证明它能看到直接 `.run()` 调用的边界；没有覆盖就不能将结果称为“禁止所有跨 pass 复用”。

新增 hook 的配置也必须能经 `-XX:JeandleLLVMOptions=...` 传入 JVM。正式运行关闭 trace／stats，不在每次命中处计时。

## 4. 生产 pipeline：主测试应直接调用真实构建器

下图是当前源码的阶段概括，不是手写替代 pipeline。正式回放调用 `jeandle<O3>`／同一生产 `optimize(..., O3, MethodCompilation)`。

```text
JavaOperationLower(0)
  → RecoverTypeInfo → InstSimplify → TCE → RepeatedCFF
  → EarlyCSE → InstCombine → SimplifyCFG → ADCE
  → RecoverTypeInfo → CHA → ProfileDevirtualization
  → JeandleInlineDriver（实际配置的内联轮次）
      含 root cleanup：InstSimplify → RecoverTypeInfo → TCE
      → RepeatedCFF → EarlyCSE → InstCombine → SimplifyCFG
      → ADCE → RecoverTypeInfo
  → PEA 开启时：高层循环优化／清理 → PartialEscapeIterative
  → InstSimplify → RecoverTypeInfo → TCE → RepeatedCFF
  → CopySpecialization → TCE
  → 循环／safepoint 处理、GC barriers、JavaOperationLower(1)
  → 标准 O3 → narrow-oop／statepoint 处理
  → JavaOperationLower(9)／清理 → TLS rewrite → InstSimplify

RepeatedCFF：CFF → SCCP → SimplifyCFG → 必要时再次 CFF
```

不能移除中间 EarlyCSE／InstCombine／SimplifyCFG 来提高缓存存活率。它们造成的断点正是实际收益边界。

### 4.1 配置组

| 配置 | 要求 |
| --- | --- |
| PROD | MethodCompilation、O3、正常内联、实际默认 PEA／GC／profile 配置；记录最终生效选项 |
| NO-PEA | 与 PROD 相同，仅关闭 PEA；用于解释 PEA 及其前置优化带来的变化 |
| NO-INLINE | 与 PROD 相同，仅关闭内联；用于解释内联引入的查询和断点 |
| PRODUCTION-JVM | 恢复正常应用编译触发与线程配置，验证受控结果的外推范围 |

先完成 PROD 三模式；另外两种消融只对代表样本做，不展开全部组合。PEA-off 或 inline-off 不可作为默认生产结果的替代品。

## 5. 输入：从真实 Java 编译建立固定语料

### 5.1 第一批候选

优先从已有 jtreg 的真实 Java 场景录制，选择约 20–40 个不同 root methods 作为初始语料；这是建议规模，不是已经收集的样本。

| 家族 | 现有候选／构造方向 | 观察重点 |
| --- | --- | --- |
| 类型恢复到去虚化 | `typeMetadataRecovery/TestRecoverTypeInfoEnablesChaDevirt.java`、`TestRecoverTypeInfo.java` | 字段 load CSE、恢复 metadata、CHA 消费；区分新事实收益和缓存复用 |
| 数组与接口 | `typeMetadataRecovery/TestRecoverArrayElementType.java` | array element receiver、共享基值、接口／虚调用 |
| 多类型检查 | `typeCheckElimination/TestTypeCheckElimination.java` | 批量查询、guard、失败判定、浅／中等 CFG |
| 常量折叠与清理 | `constantFieldFolding/TestRepeatedConstantFolding.java` | CFF 内部轮次与 wrapper 边界；先确认真的进入 JavaType 查询路径 |
| 内联 | `TestInline.java`、已存在 accessor／返回对象调用链场景 | 每轮内联后的类型恢复、重复消费者调用 |
| PEA | `pea/TestInstanceOfVirtualObjectPEA.java`、`TestPEAArrayLengthBoundsAndTypes.java`、`TestPrePEAArrayLengthUnroll.java` | 默认 PEA 与高层循环变换之后的实际查询 |
| 负对照 | 小型算术方法、少引用方法、低重访方法 | 查询极少或零查询时的额外开销 |

随后加入项目实际使用的 Java 工作负载产生的 root methods，至少覆盖集合／迭代、对象字段遍历、接口调用、初始化／常量对象和小型循环。只有定向 jtreg 时，结论明确限定为该语料。

入选规则依据输入形状和基线编译成本，不能依据候选加速幅度。预先冻结全语料；高查询热点可另列定向子集，但不能替代全体。保存零查询与负收益方法。

### 5.2 录制材料

使用当前 JDK 已有开关录制：

```text
-XX:+UseJeandleCompiler
-XX:+JeandleDumpIR
-XX:+JeandleRecordVMCallbacks
-XX:JeandleDumpDirectory=<本轮独立输出目录>
```

每个编译单元至少保存：优化前 `.ll`、`.cblog`、需要时的 `_inline_callees.ll`、优化后 IR、有效 VM／LLVM 选项、root 方法名和签名、OSR bci、编译层级／尝试编号、类加载器区分信息、类层次与 profile 来源。

录制与计时分开。不要开启 dump、callback recorder、IR print 或 query trace 来做正式 JVM 性能测量。

### 5.3 回放资格检查

先让每个输入在完整 PROD、三个主模式下跑通，验证输出和关键优化。当前 opt 支持：

```sh
"$CACHE_OPT" -disable-output -passes='jeandle<O3>' \
  -jeandle-inline=default -jeandle-pea=true -jeandle-pea-iterations=2 \
  -jeandle-vm-callback-log="$CACHE_CBLOG" \
  -jeandle-inline-callee-ir="$CACHE_CALLEE_IR" "$CACHE_ROOT_IR"
```

变量由脚本解析实际文件；无 callee 材料且确实不会成功请求 callee IR 时可省略相应参数。以上示例还须补齐与录制 JVM 一致的其他配置；不能仅凭命令成功就认定完全等价。

callback 缺键属于录制覆盖不足，不是缓存慢或快；不得随意补 true／false，也不得靠关 PEA／内联绕过后继续称为生产测量。

不同 JVM 进程中的 Klass／Method／oop 标识可能不同，禁止直接拼接不同进程的 cblog。优先在同一固定 VM 状态和对象身份下扩充所需查询记录；否则需有经过校验的标识重映射，或将该样本标为不可用于固定输入三模式比较。

若历史基线要求不同 callback schema 或根本不支持当前 pipeline，单列兼容性范围，不将回放失败作为性能数据。报告总捕获数、可三模式回放数、拒绝原因，防止仅保留容易回放的样本却声称代表全部编译。

## 6. 性能主实验：消除短进程噪声，同时保留真实编译单位

### 6.1 建议新增原生批量回放 runner

解析／准备输入后，对每个样本执行同一生产 pipeline；每次编译都使用新模块、新分析管理器／分析结果和独立回放生命周期。保持一次真实 root compilation 的边界。

```text
准备本次输入与正确 callback 上下文（不计优化时间）
  → 创建本次生产 pipeline／分析状态
  → 运行完整 pipeline
  → 析构／回收本次分析状态
  → 保存阶段时间；诊断运行另做输出验证
```

分别记录 pipeline 执行区间，以及包含其分析构造／销毁的优化生命周期区间。给出边界定义，不能只计算热缓存查询片段而漏掉填充、失效和回收。

禁止对已经优化过的模块重复运行来放大收益；禁止跨不同编译请求共享 JTA。不要把真实方法复制成一个巨型 module 来代替独立编译，这会改变 module pass 行为和内联条件。

回放所有样本或重复完整语料，使每模式每轮有效优化工作约 2–10 秒；保持各模式相同语料、顺序、重复次数。先 pilot 决定放大量，不根据加速结果挑选。

如果暂不开发 runner，可先用现有 opt 多进程回放收集诊断与端到端数据；包含启动／解析的时间单独命名，不能充当纯优化时间。`-time-passes` 类细粒度工具适合诊断，正式时间以低扰动测量为准。

### 6.2 重复、环境与统计

- 性能与构建／其他 benchmark 不并行，固定同类 CPU 核，记录温度／调度／频率异常证据，不擅自修改系统设置。
- 相同 Release 优化选项；profiling 构建只按需要增加符号，不能用 Debug 的下降百分比替代 Release 结果。
- 预热后，建议 2 个独立 session，每个 20–30 个随机配对 block；每 block 跑全体三模式。先冻结轮数或精度规则，不见显著就无限追加。
- 主指标：整份固定语料的优化生命周期时间和 CPU 成本；附每方法时间、大小分层、P50／P95、正负变化分布。
- 总体净收益按总时间比计算：`1 - sum(T_candidate) / sum(T_baseline)`；不要平均每个小方法的百分比。
- 置信区间按独立配对运行／block 重采样；同进程复制方法不能伪装成独立样本。
- 同时报置信区间、绝对时间和配对变化。区间跨零或收益低于测量分辨率时，结论写“尚未测出稳定净收益”。

诊断证明跨 pass 命中、重算下降是必要机制证据，不能替代时间和 CPU 成本证据。

## 7. jtreg：可以用，但要测内部编译成本

jtreg 本身主要服务回归／功能测试，提供 JVM 选择、隔离和结果收集。建议让它承担三件事：

1. 执行真实 Java 场景并检查语义、异常、deopt、输出和关键优化。
2. 驱动真实 Jeandle 编译并记录输入语料。
3. 运行受控的子 JVM 性能驱动，采集编译指标；性能结论来自这些指标，而非 jtreg 整套 elapsed。

不要在普通 jtreg 中加入“必须快 5%”这类时间断言。功能回归稳定执行，性能比较由独立脚本统计。

### 7.1 控制组与生产组

| 组别 | 驱动方式 | 目的 |
| --- | --- | --- |
| JVM-CONTROLLED | 沿用已有测试可用的 `-Xcomp -Xbatch -XX:-TieredCompilation` 与 compileonly；确认目标方法由 Jeandle 编译，使用串行／受控编译 | 降低编译任务集合差异，验证 LLVM 回放结果在真实 VM callbacks 下仍成立 |
| JVM-PRODUCTION | 正常预热、实际 profile／tiering／后台编译配置 | 验证真实触发方式下的编译成本与应用启动／吞吐边界 |

受控组不代表正常 MDO／PGO 行为；两组分开报告。恢复生产并发前，确认计时和缓存实现的线程语义。

### 7.2 实际已有的子 JVM 参数陷阱

`TestRecoverTypeInfoEnablesChaDevirt` 是 `@run driver`，自己用 `createLimitedTestJavaProcessBuilder` 构造子 JVM，并自带 `JeandleLLVMOptions`、compileonly 和 IR print 参数。不能假定 jtreg 外层的 VM_OPTIONS 会传给这些子进程。

执行 agent 应增加明确的实验模式参数或单独性能 driver，由统一函数合并 LLVM options，并打印／保存实际子 JVM argv。计时 driver 不保留原功能测试的 print-before／print-after。用诊断确认缓存模式确实生效，不能只看外层命令。

性能采集串行运行（jtreg JOBS=1 或等效设置），A/B/C 各自新 JVM，并随机交替顺序。独立子 JVM 已提供隔离时，不额外假设外层 othervm 会控制所有子 JVM 参数。

### 7.3 JVM 中测什么

当前 `-XX:+CITime` 输出 Jeandle Compile、Abstract Interpret、LLVM Optimize、LLVM CodeGen、Finalize 及编译数量，可先作为受控串行编译的诊断入口。

但 `jeandleCompilation.cpp` 使用进程级静态 `elapsedTimer` 数组和静态计数；timer 由 `os::elapsed_counter()` 累加，属于 elapsed 时间，不是线程 CPU 时间。输出为秒并只保留三位小数。并发准确性需要核实，不能直接把这些值当作可靠的多编译线程 CPU 总量。

建议主测量使用每次 compilation 的局部计时，必要时增加线程 CPU clock，在结束后聚合输出：

```text
method identity / compilation attempt / OSR bci / compiler thread
LLVM Optimize elapsed_ns / thread_cpu_ns
total compile elapsed_ns / thread_cpu_ns
success or bailout / code size / compiled methods count
```

优先在单编译线程、相同编译任务集合下验证；不要盲设 JVM 不接受的 CICompilerCount，检查构建约束和实际线程行为。若没有安全的并发聚合，本轮只能对串行受控组作精确编译时间结论。

同时检查目标方法是否真的编译、是否 fallback 到其他编译器、OSR／重编译／deopt 次数、内联与优化输出是否相近。正常生产组任务数改变时报告其系统效应，不只按方法平均后宣称同工作量收益。

### 7.4 如何放大编译工作

优先批量编译多个不同真实方法或扩大固定语料。仅让已编译 Java 方法执行更多循环，主要增加执行时间，不能增加 JTA 工作。

需要重复编译时，可使用新 JVM 或经验证的 WhiteBox 编译控制；必须确认 Jeandle 支持、编译真正发生，且不把 deopt／classloading／排队时间算进优化器时间。WhiteBox 重编译属于受控压力组，不替代正常生产负载。

普通 JMH 稳态吞吐可能把 JIT 成本放在 warmup 中，不适合作为本轮唯一主指标。应用启动、达到稳态的时间和稳态吞吐可作为补充。

## 8. profiling：用调用栈解释净收益

### 8.1 两层采样

1. **原生完整 pipeline 回放**：工作量固定、C++ 栈清楚，用于主归因。
2. **真实目标子 JVM**：过滤 Jeandle 编译线程／优化器调用栈，验证相同热点在 VM 中也下降。

不要只 profile jtreg 控制进程。driver 启动子 JVM 时，明确目标 PID／TID、继承关系和编译窗口；保留 PID、comm、DSO 以区分 javac、应用执行、GC 与 Jeandle 编译。

保持实际优化等级和内联，准备实际承载代码的 libjvm／LLVM DSO 或静态链接二进制的匹配符号与 build-id。不要为使函数名更漂亮而只对一个版本关闭内联或优化。

C++ 编译器栈是主要目标；若还要展示生成的 Java 代码栈，另行验证 JVM JIT 符号映射能力，不能默认 native DWARF 可完整解释 Java 帧。

### 8.2 分开 timing、stat、record

- 正式 timing：不采样、不输出详细 stats。
- `perf stat`：task-clock、cycles、instructions、context-switches、cpu-migrations、page-faults；branch/cache 事件仅按需要补充。
- `perf record`：调用栈，先用 99–199 Hz、DWARF；pilot 检查丢样、未知帧、截断及开销，再决定时长／频率／栈大小。
- 每个代表输入／语料至少重复若干次 profile，不能凭一张偶然火焰图下结论。

本机曾使用 Intel hybrid PMU；执行时重新确认 CPU 属于 cpu_core 还是 cpu_atom，选择相匹配的事件，排除 0% running 数据。不要混用不同核类型的 cycles 总量。

以下命令只作模板；runner 和文件列表参数待实现，变量由执行脚本提供：

```sh
# CACHE_RUN 是已校验的真实回放／目标 JVM 命令数组。
taskset -c "$CACHE_CPU" perf stat \
  -e task-clock,context-switches,cpu-migrations,page-faults \
  -e "$CACHE_PMU/cycles/u" -e "$CACHE_PMU/instructions/u" \
  -- "${CACHE_RUN[@]}"

taskset -c "$CACHE_CPU" perf record \
  -e cpu-clock:u -F 199 --call-graph dwarf,16384 \
  -o "$CACHE_PERF_DATA" -- "${CACHE_RUN[@]}"

perf report --stdio -i "$CACHE_PERF_DATA"
perf script -i "$CACHE_PERF_DATA" > "$CACHE_STACK_TEXT"
```

`cpu-clock` 权重与 CPU 时间相关；用 cycles 事件采样时权重是 cycles，不能当作纳秒。硬件 PMU 不可用时仍可用允许的 CPU 时间采样并如实说明限制。

runner 把输入解析／克隆排除在自身 timer 外，不代表 perf 自动排除了它们。必须用优化器栈／线程时间窗口或显式采样控制隔离；同时保留整进程视图，不能把 setup 样本归到 JTA。

### 8.3 要看的栈与成本分类

预期需要检查的链条是：

```text
真实消费者 run
  → JavaTypeAnalysisResult::getJavaType
    → 原始 getJavaType 或 getCachedJavaType
      → Base 传播／PHI／select
      → factsAt／edge facts
        → LVINullEdgeOracle
          → LazyValueInfo predicate／solve
```

同时归类：缓存查询容器开销、失效遍历／删除、条目与分析析构、DT/LVI 更新、VM callback、其他 pipeline 工作、解析／克隆／初始化。

观察预期：PASS-LOCAL → CROSS-PASS 时，下游重复 Base／factsAt／LVI 工作可能减少；ORIGINAL → CROSS-PASS 时可能同时减少 pass 内和跨 pass 重算。失效或容器维护成本可能抵消节省，必须显示。

Base 命中不保证 LVI solve 减少；Path/Final 命中也可能非常便宜。不要把某条栈不下降当作采样错误，也不要将 hardware cache-misses 下降等同于 JavaType 逻辑缓存命中。

### 8.4 交付的可视化

1. ORIGINAL／PASS-LOCAL／CROSS-PASS 三张完整调用栈火焰图，支持点击查看上下游。
2. 两张差分火焰图：ORIGINAL→CROSS-PASS、PASS-LOCAL→CROSS-PASS。
3. 每固定编译数的绝对成本分解图：Base、上下文／LVI、维护、其他优化；保留未归类部分。
4. pass invocation 时间线或矩阵：标出填充、首次跨 pass 消费、失效与销毁，说明节省发生在哪些边界。

绝对图和差分图使用相同工作量、事件、权重和缩放口径，不把每张火焰图独立归一为 100% 后仅凭宽度宣称变快。若工具按百分比显示，应附绝对采样权重／CPU 时间表。

采样不能精确计数函数调用。命中次数、重算次数和条目来源来自独立诊断轨迹；perf 用于成本归因。inclusive 父子成本不相加，递归帧去重；排他分类总和应可核对。

现有 perf-viewer 可以复用，但先检查它是否保留 sample period、能否按 PID/TID／pass 过滤，以及差分是否使用共同单位。

## 9. 正确性、任务集合与基线控制

- 功能测试先跑 ORIGINAL／PASS-LOCAL／CROSS-PASS，检查新增回归和既有基线失败。
- 固定输入回放比较规范化输出 IR、关键优化数量；含环／预算差异时做额外语义检查，不把 IR 不同一概算错误或收益。
- 缓存禁用模式可能产生更多 callback 请求，应在正式计时前确保覆盖。
- 记录每个 pass 的 invocation、查询数、跨 pass 首次消费、Base 重算、Path/Final 命中、oracle 调用，以及 FAM 失效原因。
- 性能主模式不得混入新的 CFF／RecoverTypeInfo preserve 实现或 LVI 算法优化。若推进这些改动，新增独立实验维度。
- 当前 RepeatedCFF 及标准清理会丢弃分析。即使未来 CFF 自身 preserve，也不能假定它能跨过整个 wrapper 存活；以真实诊断为准。

## 10. 执行阶段、产物与结论模板

| 阶段 | 内容 | 完成条件 |
| --- | --- | --- |
| A | 固定源码／二进制，扩展生产 pass-local 消融和低扰动计时 | JVM 与 opt 模式均能验证；无额外 DT/LVI 重建；直接 run 边界覆盖 |
| B | 真实 Java 录制与全 pipeline 回放资格检查 | 固定语料、完整 callbacks／callee 材料、三模式结果对齐，拒绝样本有原因 |
| C | 三模式完整优化生命周期性能 | 足够长的随机配对、跨 session 数据、置信区间及负收益分布 |
| D | 代表样本和全语料 profiling | 原始 perf.data、符号身份、火焰图、差分图、绝对成本表、质量检查 |
| E | jtreg 子 JVM 受控测量及生产负载补测 | 子进程参数已验证，目标编译数量与状态可核对，优化／总编译／应用指标分开 |

先执行 A–C，不因一份火焰图看起来更窄就跳过性能测量；D 可解释 C，E 验证真实 VM 环境。

建议产物目录：`identity/`、`corpus/manifest.json`、`diagnostics/`、`timing/raw.csv`、`profiles/`、`jvm/`、`report.md`。保留命令、seed、逐轮原始数、失败样本与环境信息。

报告至少给出：

- 固定语料规模、回放覆盖率、编译工作量、默认配置。
- ORIGINAL→CROSS-PASS 的绝对／相对变化与区间。
- PASS-LOCAL→CROSS-PASS 的绝对／相对变化与区间。
- 跨 pass 消费下降的重算量，以及对应栈的绝对 CPU／cycles 变化。
- JVM LLVM Optimize、总编译成本和应用时间；不能将三者混写。
- 不利样本、生命周期断点、测量噪声和未覆盖范围。

可接受的结论包括“整体缓存有收益，但跨 pass 增量很小”或“合成机制成立，当前生产配置未测出稳定收益”。目标是给出可信边界，不是预设必须证明正向加速。

## 11. 参考资料

- [前一轮测试设计](JavaType-Cache-Reuse-Test-Execution-Plan-2026-10-26.md)
- [前一轮执行报告](JavaType-Cache-Reuse-Test-Execution-2026-10-26.md)
- [已有 perf 执行报告](JavaType-Cache-Perf-Profiling-Execution-2026-10-23.md)
- [jeandle-code-access 技能](../.agents/skills/jeandle-code-access/SKILL.md)
- [OpenJDK jtreg FAQ](https://github.com/openjdk/jtreg/blob/master/src/share/doc/javatest/regtest/faq.md)：用途、JVM 隔离和 VM options。
- [OpenJDK 测试指南](https://github.com/openjdk/jdk/blob/master/doc/testing.md)：测试选择、JOBS、VM options 与 microbench 支持。
- [perf record 手册](https://man7.org/linux/man-pages/man1/perf-record.1.html)：采样事件、DWARF call graph 和 Intel hybrid 支持。

## 12. 可交给执行 agent 的任务说明

> 按本文完成 JavaType 缓存的生产性能实验。先核对当前源码和实际二进制，补齐完整 pipeline／JVM 可用的 pass-local 消融，再从真实 Java 场景录制固定 IR、VM callbacks 和 inline callee 材料，以完整 MethodCompilation O3、默认内联及 PEA 比较 ORIGINAL／PASS-LOCAL／CROSS-PASS。使用新模块和分析生命周期放大真实编译工作，分开诊断、计时与 perf 采样。jtreg 用作真实场景、正确性和子 JVM 驱动，明确将参数传到目标进程，不以测试套件 elapsed 代替编译成本。交付配对原始数据、置信区间、跨 pass 来源诊断、调用栈／差分火焰图及 JVM 补测结果。保留负收益、回放失败和基线失败，不混入新的 preserve 或 LVI 优化。
