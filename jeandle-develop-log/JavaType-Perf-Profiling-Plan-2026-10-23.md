# getJavaType 性能瓶颈的 perf 采样执行计划

日期：2026-10-23。状态：本轮性能诊断已执行，结果、质量限制及未覆盖项见[执行报告](JavaType-Cache-Perf-Profiling-Execution-2026-10-23.md)。下文保留执行前计划。

目标：解释当前缓存为什么没有表现出可重复的进程时间收益，定位 getJavaType 的实际 CPU 开销，为下一轮缓存设计提供证据。交付以瓶颈报告和可复现采样数据为主；暂不实现 S2/S3/S4，不凭热点函数名直接更换容器。

前置材料：

- [原测试计划](JavaType-Cache-Design-Test-Plan-2026-10-23.md)
- [现有执行报告](JavaType-Cache-Design-Test-Execution-2026-10-23.md)
- `artifacts/java-type-cache-2026-10-23/session{1,2}/` 下的 manifest、summary、source.patch。

## 1. 要回答的问题和现有证据边界

按以下顺序回答：

1. 查询、失效及缓存生命周期合计占进程 CPU 的多少？可优化空间是否足够大？
2. 缓存开启后，省下的计算是否被查表、插入、JavaType 复制、分配、失效或销毁抵消？
3. Base、PathFacts、FinalTypes 分别在哪里花时间？成本由 N、A、上下文数 C、查询复用率还是 use 图规模驱动？
4. 失效保留的结果后来是否真的被复用？命中的是昂贵 DAG，还是廉价叶子？
5. 主要消费者是谁：TCE、CHA、CFF、RecoverTypeInfo、RepeatedCFF，还是分析生命周期维护？
6. 性能改善为何没有体现在进程墙钟：占比小、启动/解析占比高、调度噪声、callback 回放开销，还是缓存净开销高？这些都是待检验假设。

现有五组脚本主要运行 CHA 或 TCE→CHA，不是完整 Jeandle pipeline，更不是 JVM 真实编译。原报告的“完整流水线”命名不能作为覆盖证明。区间跨零表示未能区分，不代表已证明缓存无效，也不能据此认定 Base 删除不是瓶颈。

本计划依据本地保留源码和实验产物；执行 agent 必须重新验证远端状态。

## 2. 阶段 A：身份、权限和构建检查

### A1. 连接与源码身份

- 主机：`annya@100.122.220.40`。
- 仓库：`/home/annya/playground/jeandle/jeandle/jeandle-llvm`。
- 预计分支：`test/javatype-cache-design`；预计 HEAD：`357604c7724e49eace6fbfa42e4f671b12b5ff98`。
- 先按 `jeandle-code-access` 技能执行有超时的 SSH 预检，再读取适用的 AGENTS.md、分支、HEAD、diff、untracked 清单。HEAD 相同不代表被测源码相同。
- 保留原有未提交改动；复用测试分支。若分支或源码已变化，记录并解释新基线，不覆盖用户改动，不擅自 reset/clean/commit/push。
- 新采样脚本放 `llvm/utils/jeandle/`；结果放仓库外的持久目录，例如 `/home/annya/playground/jeandle/perf-results/<run-id>/`，避免输出污染源码身份。

### A2. perf 能力预检

记录 `uname -a`、`perf --version`、`perf version --build-options`（若支持）、`lscpu`、当前允许的 CPU affinity、CPU/core/SMT/NUMA 拓扑、governor、负载和 CPU 型号。特别检查是否有不同类型的 CPU 核。

读取 `kernel.perf_event_paranoid`；用实际目标的小输入分别尝试 `cycles:u` 计数和调用栈采样。`perf list` 列出事件不代表当前用户一定可使用。只采集本任务启动的进程，不默认 system-wide `-a`。

- 硬件事件不可用时，尝试 `cpu-clock:u` 软件采样，并明确无法提供硬件 cycles/IPC 的结论。
- 软件事件也被拒绝时，保留错误，完成构建和 workload 准备，报告所需权限。不要自动 sudo、调整 sysctl、为工具设置 capability 或关闭安全设置。
- 选择允许 CPU 中的一个同类型核，并记录 SMT sibling 是否忙碌；所有模式使用同一 affinity。不在构建或其他 benchmark 并发时测量，不自动修改整机频率策略。

### A3. 保持优化级别，获得可靠符号

优先检查现有 Release 二进制能否解析目标符号和调用栈。不能满足时，建立独立 profiling build，沿用现有 CMake 配置、编译器、目标、链接方式、LTO 和 `-O3 -DNDEBUG`，添加匹配的调试信息 `-g`。保存配置差异和完整构建日志。

不要直接用默认 RelWithDebInfo 替代原 Release 后跨构建比较，二者优化参数可能不同。四种策略必须来自同一个 profiling 二进制。先用 DWARF unwind；若需 frame pointer 构建，单独标记其配置，重新取得全部策略基线，不用 `-O0` 或全局关闭内联来改善可读性。

验证符号、debug sections、build-id、源文件行号和一个目标调用栈。只跑过 rebuild 不能证明先前异常来自陈旧对象；此前 benchmark 计数异常的根因仍需证据，保留一致性检查即可。

构建后重跑 JavaType 单测和相关六个 lit 目录；执行时确认实际数量，不硬编码 44/96 为未来验收条件。构建完成后冻结源码和二进制，采样期间不得重新链接目标。

产物：`environment.json`、`source.patch`、untracked 源文件快照及哈希、CMakeCache/compile commands 摘要、build log、二进制与符号哈希、预检失败日志。

## 3. 阶段 B：固定策略与 workload

### B1. 四个策略必须同输入比较

| 模式 | 开关 | 对照目的 |
| --- | --- | --- |
| ORIGIN / REF | `-jeandle-disable-java-type-cache` | 原始引擎，无跨查询缓存 |
| FULL | `-jeandle-java-type-force-full-invalidation` | 缓存查询引擎，每个现有通知全清 |
| S0 | `-jeandle-java-type-force-base-scan-invalidation` | 选择性失效，Base 全表扫描 |
| S1 | 无以上开关 | 当前逐 key Base 删除 |

ORIGIN 与 FULL 使用不同引擎，差异不全是缓存容器成本；FULL 与 S1 的差异包含保留策略收益，S0 与 S1 才隔离 Base 删除方式。若必须区分引擎与持久缓存开销，可在测试驱动器中另加“每次查询都创建空 JavaTypeCache”的 COLD-CACHED 对照，单独命名，不冒充 FULL。

采样运行显式关闭 `-jeandle-java-type-stats` 和 `-jeandle-verify-java-type-cache`，不带 `-debug`、统计打印、逐查询日志或计时插桩。保留查询所必需的 VM callback 回放；“不打印日志”不等于“不使用回放”。

### B2. 输入分层

| 层次 | 首批输入 | 用途 |
| --- | --- | --- |
| L1：现有 pass 回放 | deep-static、wide-static、leaf-static、tce-cha、virtual-cfg | 与既有实验衔接，覆盖便宜/昂贵查询和 CFG 修改 |
| L2：消费者与完整 pipeline | CFF 常量字段链、RecoverTypeInfo、RepeatedCFF；已有 pre-pea-high-tier-e2e 测试实际命令与配套 cblog | 确认热点在真实 pass 调用路径中出现 |
| L3：进程内查询轨迹 | Base 叶子/select DAG，带 guard 的上下文查询，合法 Query—Mutate—Query | 隔离查询、失效、生命周期机制 |

首轮 L1 全部四模式。L2 先选每类一个可回放输入，确认 callback coverage；没有合适完整回放时标为缺失，不能用组合 pass 的合成输入冒充完整 pipeline。真实 JVM 样本若不可获得，报告结论限于 LLVM 回放。

性能主组采用完整、无环、预算充足输入。PHI 环与截断另列诊断组，不强求冷热 IR 一致，更不能把 verification skip 计为通过。诊断运行检查四模式输出等价、关键优化数量、查询确实发生；完整 pipeline 要确认 DAG 未在目标消费者前被简化消失。callback 缺键作为覆盖不足保存，禁止补伪造默认值。

### B3. 让采样有足够执行时间

现有约 20–30 ms 进程不足以稳定观察小热点。先做不采样 pilot：按独立函数/方法份数逐级放大输入，保持单方法图形、深度、上下文数、查询/修改比不变。禁止仅加深 select 链或让一个函数无限膨胀，以免触发预算或改变缓存规模分布。

同一 case 的四模式冻结相同规模和工作量；不能为了每个策略都跑 10 秒而分别调不同迭代次数。建议每次至少约 5–15 秒目标 CPU 时间；若不能放大，批量重复固定真实输入，并分离 launcher 与 opt 的 PID/comm，保留进程启动成本。

若仍采不到足够 getJavaType 样本，再实现 L3 进程内驱动器：每轮恢复等价、合法的初始状态，验证 checksum 和查询/修改数量，不在已完成优化的同一 IR 上反复跑 pass。克隆/解析/预热和测量区分开；最终缓存析构及实际 DT/LVI 维护另计完整轨迹，不省略。

### B4. 现有微基准需要先审计

- `benchmark::State::PauseTiming()` 不会暂停 perf。P1–P4 中恢复 cache 的复制会出现在 perf 数据里；当前循环末尾缓存析构也处于 benchmark 计时区。不得把整个进程或 benchmark 总时间称为纯失效时间。
- 纯失效采样优先按完整调用栈选择 invalidate 子树；若采用 perf enable/disable 控制，应以一批独立预热 fixture 为测量单位，确认本机 perf 支持控制接口，避免每个纳秒级操作控制一次。完整轨迹则包含真实初始化、维护和回收，人工复制另列。
- P3 的 0% 参数仍构造共享合流链，不能把参数当实测重叠率；记录闭包交集/并集和实际 use 数。
- P4 当前只有 Q 轴，不能据此推导未覆盖的 R（修改后重访比例）。P5 的 `clear()` 可能改变容量，复制也可能改变历史状态，必须测实际容量再称为 H 对照。
- `BaseSlotsScanned` 等当前主要统计遍历到的活跃条目或 clear 前 size，不是 DenseMap 的空桶/tombstone/探测总数；S1 的 0 也不代表没有哈希探测。报告中准确命名，容量与探测成本另取证。

## 4. 阶段 C：先做无采样基线和 perf stat

无采样运行记录 wall、user、system、峰值 RSS；诊断性 `-time-passes` 若本版本支持可另跑一次，不能进入正式排名。

随后使用 `perf stat`。事件分小组，先软件调度指标，再 cycles/instructions，再 branch 指标；内存事件只在存在相关热点后追加。避免一次开太多事件造成严重 multiplexing；记录 time-enabled/time-running，低于预定 90% 的运行拆组重做。混合架构核使用本机支持且与所选 CPU 匹配的 PMU。

首批指标：

- wall、user/system CPU、task-clock、context-switches、cpu-migrations、page-faults；
- `cycles:u`、`instructions:u`，由相同统计范围计算 IPC；
- `branches:u`、`branch-misses:u`；
- 可用时再测 cache 相关事件。generic cache-misses 不能直接解释成 JavaType 缓存 miss，也不能直接证明 DenseMap 冲突。

四模式先各预热 3 次，再做 10 个随机配对轮次用于诊断；若要给出正式时间收益，预先固定为两个 session、各 30 轮，不事后追加到显著为止。输出直接的 S1–S0、S1–FULL、S1–ORIGIN 对比，不仅相对 FULL。

示例模板（变量须由 runner 验证；不是本轮已运行的命令）：

```bash
perf stat -x ';' -o "$OUT/stat-core.csv" \
  -e cycles:u,instructions:u -- \
  taskset -c "$CPU" "$OPT" -disable-output \
  '-passes=function(cha-devirtualization)' \
  -jeandle-java-type-stats=false -jeandle-verify-java-type-cache=false \
  "-jeandle-vm-callback-log=$CBLOG" "$IR" "${MODE_FLAGS[@]}"
```

runner 用参数数组执行命令，不使用 eval。每个 case/mode/round 单独输出文件。

## 5. 阶段 D：perf record 调用栈采样

先以 `cycles:u`、199 Hz、DWARF 8 KiB user stack 做 pilot；实际选项以服务器安装的 perf 为准。硬件事件不可用时统一切换 `cpu-clock:u`，不能把两种事件的占比混合比较。

```bash
perf record -e cycles:u -F 199 --call-graph dwarf,8192 \
  -o "$OUT/perf.data" -- \
  taskset -c "$CPU" "$OPT" -disable-output \
  '-passes=function(cha-devirtualization)' \
  -jeandle-java-type-stats=false -jeandle-verify-java-type-cache=false \
  "-jeandle-vm-callback-log=$CBLOG" "$IR" "${MODE_FLAGS[@]}"

perf report -i "$OUT/perf.data" --stdio --no-children \
  --show-nr-samples --sort comm,dso,symbol > "$OUT/self.txt"
perf report -i "$OUT/perf.data" --stdio --children \
  --show-nr-samples --sort comm,dso,symbol > "$OUT/inclusive.txt"
perf script -i "$OUT/perf.data" > "$OUT/stacks.txt"
```

每个 case/mode 先固定 3 份独立 profile，轮次内随机模式顺序，profile 与构建/stat/其他 profile 不并行。无采样、stat、record 是独立运行，采样运行的 elapsed 不进入无插桩性能排名。

质量检查与停止条件：

- 记录 event、频率、原始样本数、period 权重、lost/throttle 信息、unknown 比例和截断调用栈情况。
- 递归栈较深时检查 8 KiB 是否截断；必要时增大 stack dump 或单独测试 frame-pointer 构建，并记录采样开销变化。
- 目标相关未知帧应尽量低于 1%，lost 应为 0；超过则先修复符号、unwind 或频率，做不到就把对应归因标为不完整，不隐藏 unknown。
- 以同工作量对比采样开销，预设 5% 为调查阈值；过高时降低频率或减少 stack dump，不能把受扰动 profile 当精确成本分解。
- 主要热点归因争取每模式累计至少 1,000 个相关有效样本，这是调查门槛，不是统计精度保证。少于 100 个样本的子热点不作排名依据。
- 如果数量不足，事先限定第二阶段为更长输入或固定批次，最多每 case/mode 5 分钟目标 CPU 时间。仍不足就报告低占比/证据不足，转 L3 机制测试，不不断提高频率直到出现想要的热点。
- 用低频/高频两档抽查一个代表 case，确认热点顺序没有被采样扰动改变。

从原始栈生成 flamegraph 作为辅助；保存生成器版本。`perf annotate` 只用于前几个已确认热点，验证具体行、内联调用及热点是否落在查表、集合操作或分配，而不是仅看 demangled 函数名。

## 6. 阶段 E：按成本归因，补必要的结构诊断

先提供整进程视图，再提供 getJavaType 子树视图。区分 self/exclusive 与 children/inclusive，递归帧去重；不能把父子 inclusive 百分比相加。过滤子树后的百分比分母可能变化，报告必须注明“占整个 opt 用户态样本”或“占 JavaType 相关样本”。用 event period 权重而非只按样本个数计算 cycles 分布。

| 成本组 | 预期入口/操作（先在实际源码确认） | 要提取的证据 |
| --- | --- | --- |
| 基础类型计算 | 原始 getJavaType、getBaseJavaTypeRaw/Case、select/PHI 遍历 | 冷计算、重复 DAG、叶子与复杂查询分别占比 |
| 上下文与类型运算 | factsAt、valueDimension、edgeGuard、typeUnion/typeIntersect、接口/排除集合 | CFG 遍历、集合合并、递归成本 |
| 缓存访问与存储 | Base/Path/Final 查找、插入、rehash，JavaType 拷贝/销毁 | 哪层、什么调用者、容量和分配 |
| 失效 | JavaTypeCache::invalidate、use graph/worklist、erase、clear | SSA 遍历 vs 表操作 vs 类型析构 |
| 分析生命周期 | JavaTypeAnalysisResult、FAM 丢弃、DT 更新、LVI clear/rebuild | 是否过早销毁缓存、维护成本 |
| VM 与回放 | subtype/common-super 等 callback；回放查键、字符串处理、I/O | 真正类型计算与 replay 框架分开 |
| 其余进程 | 启动、解析、其他优化、输出、模块析构 | 缓存优化的进程占比上限 |

模板、内联、allocator 共享函数必须按调用栈/源行归属；不能把所有 DenseMap、malloc/free 都计给 JavaType。缓存析构可能不位于查询/失效子树下，需要检查 FAM 的析构路径。分类无法确定的样本留在 unclassified。

若 perf 已能解释主要成本，停止增加插桩。若缺少原因，则在独立诊断运行加入默认关闭的计数/紧凑事件缓冲，结束时统一输出，不每次查询读时钟或打印日志。最小诊断项按热点选择：

- 分层顶层/递归 hit、miss、真正计算次数、查询预算/环状态；现有 BaseHits 不能代表递归命中。
- 每个消费者的查询数、修改批次、失效数、FAM 生命周期，Entry 的平均/高水位数量与容量。
- 保留后实际命中的条目、失效后再次计算的条目；累计 retained 本身不代表收益。
- Visit/use/enqueue/max-worklist、清除原因；上下文全清和仅 key 删除分开。
- 若要加入 EntryID 记录重访，必须是测试专用且处理删除/身份复用，不依赖裸 Value 地址作为永久 ID。

不得为了统计复用复活已经删除的 Value。诊断计数在 reference 查询前后隔离；诊断运行不用于正式速度排名。

把诊断数据与相同 workload 的无采样耗时、perf stat 和 profile 并列。S1 的热点百分比下降，只有结合相同工作量的总成本才意味着节省；单看火焰图宽度不能证明绝对时间下降。

## 7. 依据结果提出下一轮设计实验

以下是决策分支，不是预先指定的优化方案。报告最多给出 1–3 个优先实验，每项附源行/调用栈、实际占比、受益 workload、维护成本和验收指标。

| 可复现观测 | 优先验证的实验 |
| --- | --- |
| JavaType 总 CPU 占比很小，真实 pass 也不热 | 保持简单缓存；明确收益上限，优先其他编译热点 |
| 大量廉价叶子查表/插入比计算更贵 | leaf fast path、按成本选择缓存；验证查询精度与低复用场景 |
| Base DAG 反复计算、生命周期过短 | 调整共享范围/preserve 契约；先确保跨 pass 正确性 |
| 高 C 下 Path/Final 扫描与存储占主导 | 测按 Value 分组，并计入两级 lookup、空间和低 C 回退 |
| 上下文全清和重新填充都很贵 | 先识别全清原因与重访；epoch 需把后续查询/最终回收计入，不能只测入口 |
| 共同闭包重复 use 遍历很热 | 合并通知、入队去重；保持通知发生在旧图仍存活时 |
| SSA 图大、实际缓存依赖少，且遍历确为主成本 | 再考虑 EntryID+反向依赖，计入每次查询的登记和注销 |
| JavaType 集合/拷贝/分配热 | 改结果表示、move/共享存储或分配方式，检验所有权与生命周期 |
| LVI/DT 或 callback 热 | 优先对应分析/回放路径；不能把 replay 查表收益外推为 JVM callback 收益 |

可报告 Amdahl 上限：若某可移除成本约占同一 CPU 计量范围的 p，理想 CPU 加速上限为 `1/(1-p)`。cycles 占比不自动等于 wall 时间占比；等待/调度明显时不把它当墙钟保证，固定频率或 CPU 时间假设要写明。

## 8. 可复现产物、脚本与验收

建议新增一个 runner `llvm/utils/jeandle/profile-java-type-cache.py`，支持 preflight、prepare、baseline/stat、record、report 阶段，以及明确的 `--case`、`--mode`、`--cpu`、`--seed`、`--out`。保留原 benchmark 脚本用途；修复其身份记录缺口：tracked patch 需包含 staged+unstaged（例如相对 HEAD 的完整 diff），并记录相关 untracked 正文与哈希。源码、二进制、输入和 cblog 在运行前后均验身份。

```text
run-id/
  manifest.json                 # 源码/构建/CPU/perf/事件/命令/随机顺序/时间
  source.patch
  sources-untracked/
  build/                        # CMakeCache、构建日志、symbols/build-id
  inputs/                       # IR、cblog、seed、轨迹与内容哈希
  correctness.json              # 输出等价、关键变换、coverage/skip
  baseline/samples.csv          # 同工作量 wall/user/system/RSS 原始数据
  stat/                         # 每 case/mode/round 原始事件和调度数据
  profiles/<case>/<mode>/<run>/ # perf.data、stderr、self、inclusive、stacks
  diagnostics/                  # 单独运行的结构计数
  attribution.csv               # 分类、分母、样本/权重、归因质量
  failures/                     # 错误命令、日志、输入与失败身份
  report.md
```

验收要求：

1. ORIGIN/FULL/S0/S1 的开关、输入工作量和构建一致，身份可追溯。
2. 至少完成 L1 全部输入的总体成本调查；完成一个可用的 L2 回放，或明确记录缺失和原因。
3. 报告采样范围、符号/unwind/lost 状态、profile 开销，不把 paused fixture 构建算作纯 invalidate。
4. 给出整进程、JavaType 子树、按消费者三个视图；可分辨查询、失效、分配/回收、DT/LVI、callback、外部开销。
5. 每个主要结论有至少三份 profile 的重复性证据和结构解释。证据不足时明确“尚不能归因”，零样本不写成零开销。
6. 按当前结果列出有依据的下一轮实验及测量指标，不仅交一张火焰图，也不自动实现新的 cache 方案。
7. 在本地 `jeandle-develop-log/` 保存最终中文报告和小型汇总/原始样本；大 perf.data 持久保存在服务器并给出确切位置和哈希。

执行顺序：A 身份/构建 → B 输入校验与 pilot → C stat → D profile → E 必要诊断 → 设计建议。只有 profiling build/测试驱动器确需改动时才写代码；每阶段的失败不掩盖已收集的数据。完成这一轮诊断后结束，不自行扩展为缓存重构。

## 9. 可复制给执行 agent 的任务

> 请执行 `jeandle-develop-log/JavaType-Perf-Profiling-Plan-2026-10-23.md`。连接计划中的服务器，先验证并保留 `test/javatype-cache-design` 工作区及全部未提交改动，完成 perf 能力检查和同优化级别的符号构建。对 ORIGIN/FULL/S0/S1 做固定 workload 的无采样基线、perf stat 和调用栈采样，区分查询计算、缓存操作、失效、回收、DT/LVI、callback 与启动解析成本。先复用已有输入，按计划处理短进程及 benchmark PauseTiming 范围问题，再按观测补最小诊断。产出可复现原始数据、调用栈/热点源行归因、证据质量说明及下一轮缓存设计实验建议；暂不实现 S2/S3/S4，不 commit/push，不修改整机 perf 安全配置。遇到权限或回放覆盖阻塞时保留失败证据并完成其余可执行阶段。

## 10. 工具依据

命令选项最终以服务器的本地帮助为准；当前官方参考如下：

- [Linux perf record 文档](https://raw.githubusercontent.com/torvalds/linux/master/tools/perf/Documentation/perf-record.txt)：事件、采样频率、DWARF/FP 调用栈和 stack dump 配置。
- [Linux perf stat 文档](https://raw.githubusercontent.com/torvalds/linux/master/tools/perf/Documentation/perf-stat.txt)：事件计数与运行统计。
- [Linux perf report 文档](https://raw.githubusercontent.com/torvalds/linux/master/tools/perf/Documentation/perf-report.txt)：self/children、样本数、符号/源行与过滤后百分比口径。
- [Linux perf 权限文档](https://docs.kernel.org/admin-guide/perf-security.html)：perf_event_paranoid 与进程采集权限。
