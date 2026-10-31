# NullEdge 测试改进执行记录（2026-10-30）

## 改动位置

测试机：`annya@100.122.220.40`。

原有 15 个跟踪文件改动、4 个新测试文件，以及环境/执行报告，合并为单个提交 `2754b2fbfa12`（21 文件）。原分支 `test/javatype-cache-design` 工作树清洁。

从该提交新建 worktree：`/home/annya/playground/jeandle/jeandle/jeandle-llvm-null-edge-benchmark`，分支 `codex/null-edge-benchmark`。独立 CMake Release、assertions OFF、GCC 16.1.1、X86 构建，未复用旧构建目录的对象文件。

测试改进提交：`e5475bb0df46`。两个远端工作树在提交后均清洁。两份可应用 patch 已保存在本地产物目录。

新实现位于 `llvm/utils/jeandle-null-edge-bench/`，同时修复 `LVINullEdgeOracle.cpp`：统计关闭时不读时钟、不增加本地 oracle 统计；预算控制不受影响。

## 五项建议的落实

1. `--cpu` 必填，启动即设置单核 affinity；先做相同二进制/flags 的 A/A，并记录 SMT 兄弟和 governor。没有修改共享机器的全局设置。
2. 分为 correctness、diagnostic、timed 三阶段。正确性检查的 reference 重算不污染诊断计数。正式计时关闭 stats、验证和输出；oracle 内部插桩也通过统计开关关闭。
3. 保留单函数结构，扩为 1024 个独立函数；全新 opt 进程重新解析输入和构建分析。样本 CPU 时间不足 200ms 时不判定性能收益。
4. 每个输入每轮随机排列 A/B，串行执行，保存逐轮命令、顺序、wall/CPU 时间、退出码、上下文切换计数。错误、缺摘要、IR 不一致、超时等立即失败。
5. 报告配对变化、bootstrap 95% 区间，使用 A/A 的逐轮绝对差异 P95 作为保守门槛。无标定、样本过短或区间未越过门槛均为 inconclusive。

进程 CPU 时间来自 getrusage，并非查询内部 CPU 时间。正式流程衡量 opt 端到端成本，诊断摘要辅助解释查询成本；两者不能混用。

## 正确性与脚本验证

基线和新目录均重新运行：

- JavaTypeQueryTests：48 个，47 通过；唯一失败同为 `CachedEntryNormalizesFreeze`。
- Jeandle lit：发现 810 个，25 unsupported、775 通过、1 XFAIL、9 失败；通过程序比较，失败集合逐条相同。
- 脚本四个回归测试通过：进程失败、缺摘要、IR 差异必须失败；过短样本必须 inconclusive，同时检查正式命令没有验证/统计插桩并且每轮包含 A/B。
- 五种生成输入的正确性、IR 等价、诊断和计时流程均执行。测试/构建结束后才开始计时。

首次 lit 因新构建缺少工具产生额外失败；补建 llvm-as/link/dis/extract、count、not、split-file、llvm-config/readobj、llc 后重新运行，上述为最终结果。这些工具均来自新目录构建。

## A/A 实测

固定 CPU 8（SMT 兄弟为 CPU 9）；每种输入 1024 函数。初次标定 3 个预热轮、15 个正式配对轮：

| 输入 | A 进程 CPU 中位数 ms | 配对 CPU 变化中位数 | 逐轮绝对变化 P95 |
|---|---:|---:|---:|
| deep-static | 245.9 | +0.16% | 1.29% |
| wide-static | 837.8 | +0.14% | 5.11% |
| leaf-static | 323.1 | −0.65% | 6.96% |
| tce-cha | 248.2 | +0.28% | 9.78% |
| virtual-cfg | 704.5 | +0.02% | 4.02% |

全部样本超过 200ms，所有 A/A 结果均为 inconclusive。中位配对偏差小于 1%，但尾部仍有接近 10% 的波动，不能认为共享机器上 1% 的改善已可可靠识别。

原报告使用查询内部墙钟时间，此处为更长输入的进程 CPU 时间，不能直接计算二者之间的“降噪倍数”。

初次标定的诊断阶段当时还合并了 cached/reference 检查，因此其诊断 counters 不作为生产路径计数；计时阶段已关闭观察者，不受此项影响。保存该轮原始 harness.py 供复现。最终版把两阶段拆开后，再完成 1 个预热轮、5 个正式轮的五输入 A/A 验证；全部满足时长门槛。精确数据见 `aa-final/summary.json`。

## A/B 流程验证

使用同一二进制，B 打开 `-jeandle-null-edge-block-lvi=true`，1 个预热轮、5 个正式配对轮，读取 15 轮 A/A 标定作为门槛。五种输入均完成三阶段检查、IR 等价和计时，全部满足 200ms 门槛；CPU 与墙钟两项均判为 inconclusive。

这五种输入经过预过滤后没有 oracle 调用，因此这次 A/B 只验证开关、标定文件和配对判断流程，不作为块级 LVI 或整体 NullEdge 优化的收益证据。要重新量化 NullEdge 本身，需要为基线应用相同的插桩开关后构建，并使用生产输入重新做 A/A 与 A/B。

## 产物

- 使用说明：`JavaType-NullEdge-Benchmark-Usage-2026-10-30.md`。
- 本地脚本、两轮 A/A、A/B 流程验证和测试日志：`artifacts/null-edge-benchmark-2026-10-30/`。
- `aa-pilot/` 保留 15 轮初次标定及当时脚本；`aa-final/` 为最终实现的 5 轮 A/A。
- 测试机的原始诊断 IR、日志和 SUCCESS 保存在 `/tmp/null-edge-aa-20261030/`、`/tmp/null-edge-aa-final-20261030/`、`/tmp/null-edge-ab-20261030/`。输入由 `/tmp/null-edge-workloads-20261030/cases.json` 指定，可用 generate.py 重建。

当前验证覆盖测试流程与合成输入，不替代生产 JVM 编译性能评估。
