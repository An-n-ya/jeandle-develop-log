# JavaType / NullEdge 性能测试

本目录提供固定 CPU、逐文件配对交错、诊断与计时分离的测试流程。它测量 `opt` 编译成本，不测 Java 程序运行速度。Linux、Python 3.9+，不需要第三方 Python 包。

## 目录和版本

2026-10-30 的整理：原有 NullEdge 工作树已合并到提交 `2754b2fbfa12`。改进测试位于分支 `codex/null-edge-benchmark`，干净 worktree 为：

```
/home/annya/playground/jeandle/jeandle/jeandle-llvm-null-edge-benchmark
```

原始工作树保留在 `../jeandle-llvm`。新目录单独配置构建，没有使用旧工作树的对象文件。

## 构建与正确性

从仓库根目录运行：

```bash
cmake -G Ninja -S llvm -B build -DCMAKE_BUILD_TYPE=Release \
  -DLLVM_ENABLE_ASSERTIONS=OFF -DLLVM_TARGETS_TO_BUILD=X86
env -u LD_LIBRARY_PATH ninja -C build opt JavaTypeQueryTests FileCheck \
  llvm-as llvm-link llvm-dis count not split-file llvm-config llvm-readobj llvm-extract llc
env -u LD_LIBRARY_PATH build/unittests/IR/JavaTypeQueryTests
env -u LD_LIBRARY_PATH build/bin/llvm-lit -s --timeout=300 build/test/Jeandle
python3 llvm/utils/jeandle-null-edge-bench/test_benchmark.py
```

测试机使用的编译器是 `/home/annya/playground/jeandle/jeandle/tools/bin/gcc` 与 `g++`；若默认编译器不支持该分支，请通过 `CMAKE_C_COMPILER` / `CMAKE_CXX_COMPILER` 指定。完整 lit 还需要相应测试工具（例如 llvm-link、llvm-as）；先构建缺失工具再判断失败原因。该分支已有语义测试失败，新增失败必须与基线逐条比较，不能只看总数。

## 1. 选择核心，先 A/A

```bash
lscpu -e=CPU,CORE,SOCKET,MAXMHZ
cat /sys/devices/cpu_core/cpus
cat /sys/devices/cpu_atom/cpus
cat /sys/devices/system/cpu/cpu8/topology/thread_siblings_list
```

本机 CPU 0–15 属于 cpu_core，16–31 属于 cpu_atom；8 和 9 是同一物理核心的线程。下面用 CPU 8 举例，执行前应确认 8 和 9 都空闲。脚本设置自身 affinity，全部子进程继承；绑核不等于独占。不要在构建、lit 或其他 benchmark 同时进行时测量。脚本不修改共享机器的 governor、Turbo 或系统服务。需要进一步降低噪声时，在独占测试环境中固定频率策略，并把策略与结果一起记录。

## 2. 生成足够长的输入

```bash
python3 llvm/utils/jeandle-null-edge-bench/generate.py \
  --out /tmp/null-edge-inputs --functions 1024
```

五个 workload 保留每个函数的调用点和 select 深度，仅增加独立函数数量：deep-static（16/64）、wide-static（64/16）、leaf-static（32/0）、tce-cha（16/64）、virtual-cfg（32/0），括号为每函数调用点数/select 深度。每次 `opt` 都从原始输入构建新的 IR 和分析状态。没有反复运行已经被优化过的模块，也没有跨进程预热 JavaType/LVI 缓存。

正式样本要求每臂进程 CPU 时间至少 200ms；任何一个有效样本不足，`sample_duration_ok=false`，不判定收益。若不足，用新目录提高 `--functions`，重新做 A/A。时间门槛是操作性默认值，不是统计保证；该时间包含解析等成本，也应结合诊断中的 query time 检查查询工作量是否足够。输入扩大后也要留意内存压力。

## 3. A/A 标定

```bash
python3 llvm/utils/jeandle-null-edge-bench/benchmark.py \
  --cases /tmp/null-edge-inputs/cases.json \
  --a build/bin/opt --b build/bin/opt --cpu 8 \
  --repeats 31 --warmups 3 --out /tmp/null-edge-aa
```

每轮对 A、B 的顺序随机化，但串行执行；预热轮也记录，统计时排除。seed 默认固定并写入 manifest。A/A 的两臂必须相同二进制、相同 flags，不能人为制造区别。`summary.json` 的 `absolute_pair_change_p95` 是逐轮绝对百分比差异的经验 95 分位，用于下一步的保守噪声门槛。A/A 自身始终标为 inconclusive，不会宣称同一程序变快。

A/A 应重复若干独立会话。若仍有明显漂移，先处理核心争用、负载和样本长度；不要用增加重复次数掩盖系统性偏差。

## 4. A/B 配对测试

例如比较块级 LVI 开关：

```bash
python3 llvm/utils/jeandle-null-edge-bench/benchmark.py \
  --cases /tmp/null-edge-inputs/cases.json \
  --a build/bin/opt --b build/bin/opt \
  --b-flag=-jeandle-null-edge-block-lvi=true --cpu 8 \
  --calibration /tmp/null-edge-aa/summary.json \
  --repeats 31 --warmups 3 --out /tmp/null-edge-ab
```

`--a-flag` / `--b-flag` 可重复；以 `-` 开头的值使用等号语法。比较两个实现时，将 `--a` / `--b` 分别指向同配置构建的不可变二进制。基线也应关闭相同的插桩。不要在测量中重建二进制。

注意：当前五个合成输入在预过滤后 oracle 调用为零，因此上面的开关示例用于验证测试流程，不足以评价块级 LVI 的收益。真正评价该开关应使用触达 oracle 的语料。E0 可能改变优化后的 IR；脚本遇到差异会停止，此时应单独进行精度/行为分析，不能绕过门禁宣称等价提速。

对每个输入，先单独执行 cached/reference 正确性检查，再执行开启 stats、verify-each 的诊断，保存 IR 和摘要；正确性重算不会污染诊断计数。输出 IR 必须一致，进程必须成功且摘要必须存在。预算/循环导致的 verification skips 应人工检查；通过差分不代表所有查询均被比较。

正式计时只执行 `-disable-output`，不加 stats、verify 或 summary。oracle 的内部计时现在也受 stats 开关保护。外部同时记录：

- `wall_ns`：整个 opt 的墙钟时间，包括启动、解析、优化与退出。
- `cpu_ns`：串行子进程的高分辨率 user+system CPU 时间，来自 `getrusage(RUSAGE_CHILDREN)` 差值；不是线程查询时间。
- 自愿/非自愿上下文切换次数，辅助发现调度干扰。

不要把诊断中的 LVI 时间再加到 query time 上；前者已包含在后者中。进程 CPU 时间可减少抢占等待影响，但不能消除缓存、频率和核心争用。

## 5. 结果判断和文件

每轮计算 `100 * (B/A - 1)`，负值表示 B 更快。对配对变化的中位数做 4000 次 bootstrap，报告 95% 区间。区间必须整体超出 A/A 噪声门槛，且全部样本足够长，才标为 improvement/regression；否则 inconclusive。没有提供 calibration 或显式 `--noise-floor-pct`，也不自动判定收益。

`--calibration` 必须来自相同输入规模、核心、指标和相近环境；脚本不会替你证明环境相同。若不同日期的 A/A 噪声范围更大，采用较大范围。bootstrap 区间假设轮次近似独立，不能消除持续漂移或代表生产输入分布。

输出目录必须是新目录，包含：

- `manifest.json`：完整输入配置、参数、CPU affinity、SMT 兄弟、governor、二进制和输入 SHA256。
- `samples.jsonl`：逐轮命令、模式、顺序、时间、退出码、调度计数；预热/诊断/正式阶段分开标注。
- `*-a.ll` / `*-b.ll`、`*.stderr`：诊断 IR 和摘要。
- `summary.json`：中位时间、配对变化、置信区间、噪声门槛、样本长度和判定。
- `SUCCESS`：流程完成；不表示获得显著收益。失败和超时不会生成此标记。

缺统计、非零退出、超时、非预期 IR 差异、正式阶段输出、二进制/输入在运行中变化，都使实验失败。不要把缺失值补零。

## 使用真实语料

`--cases` 接收显式 JSON 数组，每个文件单独配对交错，不先跑完整个 A 再跑 B：

```json
[
  {
    "name": "frozen-null-edge",
    "input": "/absolute/path/frozen-null-edge.ll",
    "callback": "/absolute/path/Inputs/frozen-null-edge.cblog",
    "passes": "function(type-check-elimination)"
  }
]
```

应从实际 RUN 命令人工核实 passes 与 callback，保留真正需要的额外参数；不能把只解析第一个 RUN 的扫描当成完整 lit 覆盖。name 应唯一，使用普通文件名字符。小文件可作为成本分布诊断，通常不足 200ms，脚本会如实标记 inconclusive。要测微小查询成本，需要另外构造保留 null 形状的独立函数批次，而不是重复已经命中的同一查询。测试语料文件的中位时间之和也不等于完整语料端到端时间的中位数。
